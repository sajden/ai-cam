from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.request
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, status
from openai import OpenAI
from pydantic import BaseModel, Field


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("codex-gateway")

APP_VERSION = "0.4.0"
TOKEN = os.getenv("CODEX_GATEWAY_TOKEN", "").strip()
BACKEND = os.getenv("CODEX_GATEWAY_BACKEND", "codex_cli").strip().lower()
MODEL = os.getenv("CODEX_MODEL", "").strip()
API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
CODEX_BIN = os.getenv("CODEX_CLI_BIN", "codex").strip() or "codex"
CODEX_TIMEOUT_SEC = int(os.getenv("CODEX_TIMEOUT_SEC", "60"))
CODEX_CLI_SANDBOX = os.getenv("CODEX_CLI_SANDBOX", "read-only").strip() or "read-only"
CODEX_CLI_APPROVAL = os.getenv("CODEX_CLI_APPROVAL", "never").strip() or "never"
CODEX_CLI_ENABLE_SEARCH = os.getenv("CODEX_CLI_ENABLE_SEARCH", "1").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
CODEX_MODEL_FAST = os.getenv("CODEX_MODEL_FAST", "").strip()
CODEX_MODEL_FAST_FOR_SEARCH = os.getenv("CODEX_MODEL_FAST_FOR_SEARCH", "1").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
CODEX_MODEL_FAST_FOR_SHORT = os.getenv("CODEX_MODEL_FAST_FOR_SHORT", "1").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
CODEX_FAST_SHORT_CHARS = int(os.getenv("CODEX_FAST_SHORT_CHARS", "90"))
CODEX_MEMORY_LIMIT = int(os.getenv("CODEX_MEMORY_LIMIT", "12"))
CODEX_MEMORY_LIMIT_SEARCH = int(os.getenv("CODEX_MEMORY_LIMIT_SEARCH", "8"))
CODEX_AUTH_FILE = os.getenv("CODEX_AUTH_FILE", "/root/.codex/auth.json").strip()
_default_thread_map_file = os.path.join(
    os.path.dirname(CODEX_AUTH_FILE) or ".",
    "conversation_threads.json",
)
CODEX_THREAD_MAP_FILE = os.getenv("CODEX_THREAD_MAP_FILE", _default_thread_map_file).strip()

app = FastAPI(title="codex-gateway", version=APP_VERSION)

# ---------------------------------------------------------------------------
# ChatGPT OAuth token manager
# ---------------------------------------------------------------------------
_token_lock = threading.Lock()
_cached_access_token: str = ""
_token_expires_at: float = 0.0
_thread_map_lock = threading.Lock()
_thread_map_cache: dict[str, str] | None = None


def _load_auth_file() -> dict[str, Any]:
    try:
        with open(CODEX_AUTH_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        log.warning("Failed to read %s: %s", CODEX_AUTH_FILE, exc)
        return {}


def _parse_jwt_exp(token: str) -> float:
    """Extract exp claim from a JWT without verification."""
    import base64
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return 0.0
        # Add padding
        payload_b64 = parts[1] + "=" * (4 - len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        return float(payload.get("exp", 0))
    except Exception:
        return 0.0


def _load_thread_map_from_disk() -> dict[str, str]:
    try:
        with open(CODEX_THREAD_MAP_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
        if not isinstance(raw, dict):
            return {}
        out: dict[str, str] = {}
        for k, v in raw.items():
            ck = str(k).strip()
            cv = str(v).strip()
            if ck and cv:
                out[ck] = cv
        return out
    except FileNotFoundError:
        return {}
    except Exception as exc:
        log.warning("Failed to read %s: %s", CODEX_THREAD_MAP_FILE, exc)
        return {}


def _persist_thread_map_to_disk(data: dict[str, str]) -> None:
    try:
        parent = os.path.dirname(CODEX_THREAD_MAP_FILE) or "."
        os.makedirs(parent, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=parent,
            prefix="thread-map-",
            suffix=".tmp",
            delete=False,
        ) as tmp:
            json.dump(data, tmp, ensure_ascii=False, indent=2)
            tmp_path = tmp.name
        os.replace(tmp_path, CODEX_THREAD_MAP_FILE)
    except Exception as exc:
        log.warning("Failed to persist %s: %s", CODEX_THREAD_MAP_FILE, exc)


def _thread_map_get(conversation_id: str) -> str:
    global _thread_map_cache
    key = conversation_id.strip()
    if not key:
        return ""
    with _thread_map_lock:
        if _thread_map_cache is None:
            _thread_map_cache = _load_thread_map_from_disk()
        return str(_thread_map_cache.get(key, "")).strip()


def _thread_map_set(conversation_id: str, thread_id: str) -> None:
    global _thread_map_cache
    key = conversation_id.strip()
    value = thread_id.strip()
    if not key or not value:
        return
    with _thread_map_lock:
        if _thread_map_cache is None:
            _thread_map_cache = _load_thread_map_from_disk()
        _thread_map_cache[key] = value
        _persist_thread_map_to_disk(_thread_map_cache)


def _thread_map_delete(conversation_id: str) -> None:
    global _thread_map_cache
    key = conversation_id.strip()
    if not key:
        return
    with _thread_map_lock:
        if _thread_map_cache is None:
            _thread_map_cache = _load_thread_map_from_disk()
        if key not in _thread_map_cache:
            return
        del _thread_map_cache[key]
        _persist_thread_map_to_disk(_thread_map_cache)


def _extract_thread_id(stdout: str, stderr: str) -> str:
    for raw in (stdout + "\n" + stderr).splitlines():
        line = raw.strip()
        if not line.startswith("{") or '"thread_id"' not in line:
            continue
        try:
            event = json.loads(line)
        except Exception:
            continue
        if str(event.get("type", "")).strip() != "thread.started":
            continue
        tid = str(event.get("thread_id", "")).strip()
        if tid:
            return tid
    return ""


def _compact_proc_error(proc: subprocess.CompletedProcess[str]) -> str:
    stderr = (proc.stderr or "").strip()
    stdout = (proc.stdout or "").strip()
    detail = stderr or stdout or f"codex_cli_rc:{proc.returncode}"
    return detail[:400]


def _refresh_access_token(refresh_token: str) -> tuple[str, float]:
    """Use the refresh_token to get a new access_token from OpenAI."""
    payload = json.dumps({
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": "app_EMoamEEZ73f0CkXaXp7hrann",
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://auth.openai.com/oauth/token",
        method="POST",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        body = json.loads(resp.read())
    new_access = body.get("access_token", "")
    new_refresh = body.get("refresh_token", "")
    if not new_access:
        raise RuntimeError(f"Token refresh returned no access_token: {body}")
    # Update auth.json on disk so it survives restarts
    try:
        auth_data = _load_auth_file()
        if auth_data:
            tokens = auth_data.get("tokens", {})
            tokens["access_token"] = new_access
            if new_refresh:
                tokens["refresh_token"] = new_refresh
            auth_data["tokens"] = tokens
            with open(CODEX_AUTH_FILE, "w", encoding="utf-8") as f:
                json.dump(auth_data, f, indent=2)
            log.info("Updated auth.json with refreshed token")
    except Exception as exc:
        log.warning("Failed to persist refreshed token: %s", exc)
    exp = _parse_jwt_exp(new_access)
    return new_access, exp


def _get_access_token() -> str:
    """Get a valid access token, refreshing if needed."""
    global _cached_access_token, _token_expires_at
    with _token_lock:
        now = time.time()
        # Return cached if still valid (with 60s margin)
        if _cached_access_token and _token_expires_at > now + 60:
            return _cached_access_token
        auth = _load_auth_file()
        tokens = auth.get("tokens", {})
        access_token = tokens.get("access_token", "")
        refresh_token = tokens.get("refresh_token", "")
        if access_token:
            exp = _parse_jwt_exp(access_token)
            if exp > now + 60:
                _cached_access_token = access_token
                _token_expires_at = exp
                log.info("Loaded access token from auth.json (expires in %.0fs)", exp - now)
                return access_token
        # Token expired or missing — refresh
        if not refresh_token:
            raise RuntimeError("No refresh_token available, run: codex login --device-auth")
        log.info("Access token expired, refreshing...")
        new_token, new_exp = _refresh_access_token(refresh_token)
        _cached_access_token = new_token
        _token_expires_at = new_exp
        log.info("Token refreshed (expires in %.0fs)", new_exp - now)
        return new_token


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


def _require_auth(authorization: str | None = Header(default=None)) -> None:
    if not TOKEN:
        return
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing bearer token",
        )
    supplied = authorization.replace("Bearer ", "", 1).strip()
    if supplied != TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid token",
        )


class AskRequest(BaseModel):
    text: str = Field(min_length=1)
    conversation_id: str | None = None
    memory: list[dict[str, Any]] = Field(default_factory=list)
    system_prompt: str | None = None
    allow_search: bool = False


def _memory_limit(req: AskRequest) -> int:
    if req.allow_search:
        return max(1, CODEX_MEMORY_LIMIT_SEARCH)
    return max(1, CODEX_MEMORY_LIMIT)


def _effective_model(req: AskRequest) -> str:
    if not CODEX_MODEL_FAST:
        return MODEL
    if CODEX_MODEL_FAST_FOR_SEARCH and req.allow_search:
        return CODEX_MODEL_FAST
    if CODEX_MODEL_FAST_FOR_SHORT and len((req.text or "").strip()) <= CODEX_FAST_SHORT_CHARS:
        return CODEX_MODEL_FAST
    return MODEL


def _build_input(req: AskRequest) -> list[dict[str, Any]]:
    parts: list[dict[str, Any]] = []
    if req.system_prompt:
        parts.append(
            {
                "role": "system",
                "content": [{"type": "input_text", "text": req.system_prompt}],
            }
        )
    if req.memory:
        mem_lines = []
        for item in req.memory[-_memory_limit(req):]:
            role = str(item.get("role", "unknown"))
            text = str(item.get("text", ""))
            mem_lines.append(f"{role}: {text}")
        parts.append(
            {
                "role": "system",
                "content": [
                    {
                        "type": "input_text",
                        "text": "Tidigare kontext:\n" + "\n".join(mem_lines),
                    }
                ],
            }
        )
    parts.append(
        {
            "role": "user",
            "content": [{"type": "input_text", "text": req.text}],
        }
    )
    return parts


def _build_codex_prompt(req: AskRequest) -> str:
    parts: list[str] = []
    if req.system_prompt:
        parts.append(req.system_prompt.strip())
    if req.memory:
        mem_lines = []
        for item in req.memory[-_memory_limit(req):]:
            role = str(item.get("role", "unknown"))
            text = str(item.get("text", "")).strip()
            if text:
                mem_lines.append(f"{role}: {text}")
        if mem_lines:
            parts.append("Tidigare kontext:\n" + "\n".join(mem_lines))
    parts.append(
        "Svara kort och tydligt på svenska om inte användaren uttryckligen ber om annat.\n"
        f"Användarfråga: {req.text}"
    )
    return "\n\n".join(parts).strip()


def _codex_login_status() -> tuple[bool, str]:
    if not shutil.which(CODEX_BIN):
        return False, "codex_cli_missing"
    try:
        proc = subprocess.run(
            [CODEX_BIN, "login", "status"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except Exception as exc:  # pragma: no cover
        return False, f"codex_login_status_error:{type(exc).__name__}"
    output = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode == 0 and "logged in" in output.lower():
        return True, output.strip()
    return False, output.strip() or f"codex_login_status_rc:{proc.returncode}"


_login_verified = False


def _ask_with_codex_cli(req: AskRequest) -> tuple[str, bool, str, str]:
    global _login_verified
    if not shutil.which(CODEX_BIN):
        raise HTTPException(status_code=500, detail="codex_cli_missing")

    # Only check login once — saves ~3s per request
    if not _login_verified:
        logged_in, _ = _codex_login_status()
        if not logged_in:
            raise HTTPException(
                status_code=503,
                detail="codex_not_logged_in (run: codex login --device-auth)",
            )
        _login_verified = True

    prompt = _build_codex_prompt(req)

    selected_model = _effective_model(req)

    def _build_cmd(output_path: str, *, resume_thread_id: str = "") -> list[str]:
        cmd = [CODEX_BIN]
        if CODEX_CLI_ENABLE_SEARCH and req.allow_search:
            # Enables Codex web_search tool in this request.
            cmd.append("--search")
        cmd.extend(["-a", CODEX_CLI_APPROVAL, "-s", CODEX_CLI_SANDBOX, "exec"])
        cmd.extend(
            [
                "--skip-git-repo-check",
                "--json",
                "--output-last-message",
                output_path,
            ]
        )
        if selected_model:
            cmd.extend(["--model", selected_model])
        if resume_thread_id:
            cmd.extend(["resume", resume_thread_id, prompt])
        else:
            cmd.append(prompt)
        return cmd

    def _run_attempt(cmd: list[str], output_path: str) -> tuple[bool, str, str, str]:
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=CODEX_TIMEOUT_SEC,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return False, "", "", "codex_cli_timeout"
        except Exception as exc:  # pragma: no cover
            return False, "", "", f"codex_cli_exec_error:{type(exc).__name__}"

        thread_id = _extract_thread_id(proc.stdout or "", proc.stderr or "")
        if proc.returncode != 0:
            return False, "", thread_id, f"codex_cli_failed:{_compact_proc_error(proc)}"
        try:
            with open(output_path, "r", encoding="utf-8") as fh:
                text = fh.read().strip()
        except Exception as exc:  # pragma: no cover
            return False, "", thread_id, f"codex_cli_output_error:{type(exc).__name__}"
        if not text:
            return False, "", thread_id, "codex_cli_empty_output"
        return True, text, thread_id, ""

    with tempfile.NamedTemporaryFile(prefix="codex-last-", suffix=".txt", delete=False) as tmp:
        output_path = tmp.name

    conversation_id = (req.conversation_id or "").strip()
    mapped_thread_id = _thread_map_get(conversation_id) if conversation_id else ""

    try:
        if mapped_thread_id:
            ok, text, thread_id, error_detail = _run_attempt(
                _build_cmd(output_path, resume_thread_id=mapped_thread_id),
                output_path,
            )
            if ok:
                effective_thread_id = thread_id or mapped_thread_id
                if conversation_id and effective_thread_id:
                    _thread_map_set(conversation_id, effective_thread_id)
                return text, True, effective_thread_id, selected_model
            log.warning(
                "Resume failed for conversation=%s thread=%s: %s",
                conversation_id,
                mapped_thread_id,
                error_detail,
            )
            if conversation_id:
                _thread_map_delete(conversation_id)

        ok, text, thread_id, error_detail = _run_attempt(_build_cmd(output_path), output_path)
        if not ok:
            if error_detail == "codex_cli_timeout":
                raise HTTPException(status_code=504, detail=error_detail)
            raise HTTPException(status_code=502, detail=error_detail)
        if conversation_id and thread_id:
            _thread_map_set(conversation_id, thread_id)
        return text, False, thread_id, selected_model
    finally:
        try:
            os.remove(output_path)
        except Exception:
            pass


def _build_messages(req: AskRequest) -> list[dict]:
    """Build standard chat.completions messages list."""
    messages: list[dict] = []
    if req.system_prompt:
        messages.append({"role": "system", "content": req.system_prompt})
    if req.memory:
        mem_lines = []
        for item in req.memory[-_memory_limit(req):]:
            role = str(item.get("role", "unknown"))
            text = str(item.get("text", "")).strip()
            if text:
                mem_lines.append(f"{role}: {text}")
        if mem_lines:
            messages.append({
                "role": "system",
                "content": "Tidigare kontext:\n" + "\n".join(mem_lines),
            })
    messages.append({"role": "user", "content": req.text})
    return messages


def _ask_with_openai(req: AskRequest, api_key: str) -> str:
    """Direct OpenAI chat.completions API call — no subprocess, ~1-2s response time."""
    if not MODEL:
        raise HTTPException(status_code=500, detail="CODEX_MODEL is not set")
    client = OpenAI(api_key=api_key)
    kwargs: dict = {
        "model": MODEL,
        "messages": _build_messages(req),
        "reasoning_effort": "low",
    }
    if req.allow_search:
        kwargs["tools"] = [{"type": "web_search_preview"}]
    try:
        resp = client.chat.completions.create(**kwargs)
        text = resp.choices[0].message.content or ""
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"openai_error:{type(exc).__name__}:{exc}")
    if not text.strip():
        raise HTTPException(status_code=502, detail="openai_empty_response")
    return text.strip()


@app.on_event("startup")
def _warmup() -> None:
    """Pre-warm Codex CLI on startup: login check + one lightweight request."""
    if BACKEND not in ("codex_cli",):
        return

    def _do_warmup() -> None:
        global _login_verified
        t0 = time.time()
        try:
            logged_in, status_text = _codex_login_status()
            if logged_in:
                _login_verified = True
                log.info("Warmup: login OK in %.1fs", time.time() - t0)
                # Fire a trivial request to warm up model/connection cache
                t1 = time.time()
                warmup_req = AskRequest(text="Hej", system_prompt="Svara med ett ord.")
                _ask_with_codex_cli(warmup_req)
                log.info("Warmup: first request in %.1fs", time.time() - t1)
            else:
                log.warning("Warmup: not logged in: %s", status_text[:100])
        except Exception as exc:
            log.warning("Warmup failed: %s", exc)

    threading.Thread(target=_do_warmup, daemon=True).start()


@app.get("/v1/health", dependencies=[Depends(_require_auth)])
def health() -> dict[str, Any]:
    token_ok = False
    token_status = "unknown"
    if BACKEND == "chatgpt_oauth":
        try:
            _get_access_token()
            token_ok = True
            token_status = f"valid (expires in {_token_expires_at - time.time():.0f}s)"
        except Exception as exc:
            token_status = f"error: {exc}"
    elif BACKEND == "openai":
        token_ok = bool(API_KEY)
        token_status = "api_key_set" if token_ok else "no_api_key"
    else:
        logged_in, status_text = _codex_login_status()
        token_ok = logged_in
        token_status = status_text[:160]
    return {
        "ok": True,
        "service": "codex-gateway",
        "version": APP_VERSION,
        "backend": BACKEND,
        "model": MODEL or "(default)",
        "token_ok": token_ok,
        "token_status": token_status,
    }


@app.post("/v1/ask", dependencies=[Depends(_require_auth)])
def ask(req: AskRequest) -> dict[str, Any]:
    t0 = time.time()

    resume_used = False
    thread_id = ""
    used_model = MODEL
    if BACKEND == "chatgpt_oauth":
        api_key = _get_access_token()
        text = _ask_with_openai(req, api_key)
    elif BACKEND == "openai":
        if not API_KEY:
            raise HTTPException(status_code=500, detail="OPENAI_API_KEY is not set")
        text = _ask_with_openai(req, API_KEY)
    else:
        text, resume_used, thread_id, used_model = _ask_with_codex_cli(req)

    elapsed = time.time() - t0
    log.info("Ask completed in %.1fs (backend=%s, model=%s)", elapsed, BACKEND, used_model or "default")

    return {
        "ok": True,
        "model": used_model or "(default)",
        "backend": BACKEND,
        "text": text.strip(),
        "search_used": bool(CODEX_CLI_ENABLE_SEARCH and req.allow_search),
        "resume_used": resume_used,
        "thread_id": thread_id,
        "elapsed_sec": round(elapsed, 2),
    }
