"""Reolink HTTP API client for PTZ control and auto-tracking.

Uses a persistent, thread-safe shared client to avoid overwhelming
the camera with repeated TLS handshakes and logins.
"""

from __future__ import annotations

import http.client
import json
import logging
import os
import ssl
import threading
import time
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)

# Reolink uses a self-signed certificate — skip verification for local LAN calls.
_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE

# PTZ burst duration in seconds (how long the camera moves before Stop).
_PTZ_BURST_SEC = max(0.08, float(os.getenv("AIHUB_REOLINK_PTZ_BURST_SEC", "0.35")))
_PTZ_SPEED = max(1, min(64, int(os.getenv("AIHUB_REOLINK_PTZ_SPEED", "14"))))
_API_MAX_RETRIES = 2


@dataclass
class ReolinkConfig:
    host: str
    user: str
    password: str
    timeout_sec: int
    channel: int


def load_reolink_config() -> ReolinkConfig:
    channel = int(os.getenv("AIHUB_REOLINK_CHANNEL", "0"))
    return ReolinkConfig(
        host=os.getenv("AIHUB_REOLINK_HOST", "").strip(),
        user=os.getenv("AIHUB_REOLINK_USER", "admin").strip(),
        password=os.getenv("AIHUB_REOLINK_PASSWORD", "").strip(),
        timeout_sec=int(os.getenv("AIHUB_REOLINK_TIMEOUT_SEC", "10")),
        channel=max(0, channel),
    )


class ReolinkClient:
    """Persistent-connection Reolink HTTP API client.

    Thread-safe via a lock.  Reconnects automatically on connection errors.
    Reuses a single HTTPS connection and login token across all callers.
    """

    def __init__(self, cfg: ReolinkConfig) -> None:
        self._cfg = cfg
        self._lock = threading.Lock()
        self._conn: http.client.HTTPSConnection | None = None
        self._token: str = ""
        # Metrics
        self._api_calls = 0
        self._api_errors = 0
        self._reconnects = 0

    def _connect(self) -> None:
        """Create a fresh HTTPS connection."""
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
        self._conn = http.client.HTTPSConnection(
            self._cfg.host, timeout=self._cfg.timeout_sec, context=_SSL_CTX,
        )
        self._token = ""
        self._reconnects += 1

    def _login(self) -> None:
        """Authenticate and cache the token."""
        if self._conn is None:
            raise RuntimeError("Cannot login: no active connection")
        payload = json.dumps([
            {
                "cmd": "Login",
                "action": 0,
                "param": {
                    "User": {
                        "userName": self._cfg.user,
                        "password": self._cfg.password,
                    }
                },
            }
        ])
        self._conn.request(
            "POST", "/cgi-bin/api.cgi?cmd=Login",
            payload, {"Content-Type": "application/json"},
        )
        body = json.loads(self._conn.getresponse().read())
        token = body[0].get("value", {}).get("Token", {}).get("name", "")
        if not token:
            raise RuntimeError(f"Reolink login failed: {body}")
        self._token = token

    def _ensure_ready(self) -> None:
        if self._conn is None:
            self._connect()
        if not self._token:
            self._login()

    def _raw_api(self, cmd: str, params: dict | None = None) -> list[dict]:
        """Single API call attempt (no retry, no lock)."""
        self._ensure_ready()
        if self._conn is None:
            raise RuntimeError("Cannot call API: no active connection")
        payload_obj: dict = {"cmd": cmd, "action": 0}
        if params:
            payload_obj["param"] = params
        payload = json.dumps([payload_obj])
        self._conn.request(
            "POST", f"/cgi-bin/api.cgi?cmd={cmd}&token={self._token}",
            payload, {"Content-Type": "application/json"},
        )
        return json.loads(self._conn.getresponse().read())

    def api(self, cmd: str, params: dict | None = None) -> list[dict]:
        """Thread-safe API call with automatic reconnect on failure."""
        with self._lock:
            self._api_calls += 1
            last_exc: Exception | None = None
            for attempt in range(_API_MAX_RETRIES + 1):
                try:
                    return self._raw_api(cmd, params)
                except Exception as exc:
                    last_exc = exc
                    self._api_errors += 1
                    log.warning(
                        "Reolink API %s failed (attempt %d/%d): %s",
                        cmd, attempt + 1, _API_MAX_RETRIES + 1, exc,
                    )
                    # Reconnect and re-login for next attempt
                    self._connect()
                    try:
                        self._login()
                    except Exception as login_exc:
                        log.warning("Reolink re-login failed: %s", login_exc)
                        self._token = ""
            raise RuntimeError(f"Reolink API {cmd} failed after {_API_MAX_RETRIES + 1} attempts: {last_exc}")

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                except Exception:
                    pass
                self._conn = None
            self._token = ""

    def metrics(self) -> dict[str, Any]:
        return {
            "api_calls": self._api_calls,
            "api_errors": self._api_errors,
            "reconnects": self._reconnects,
            "connected": self._conn is not None,
            "has_token": bool(self._token),
        }

    # ------------------------------------------------------------------
    # PTZ
    # ------------------------------------------------------------------

    def ptz_control(self, op: str, speed: int = 15) -> list[dict]:
        return self.api("PtzCtrl", {"channel": self._cfg.channel, "op": op, "speed": speed})

    def ptz_stop(self) -> list[dict]:
        return self.api("PtzCtrl", {"channel": self._cfg.channel, "op": "Stop", "speed": 1})

    def ptz_burst(self, op: str, speed: int = 15, duration: float = _PTZ_BURST_SEC) -> tuple[bool, str]:
        """Move in *op* direction for *duration* seconds, then stop."""
        start_resp = self.ptz_control(op, speed)
        ok_start, reason_start = _is_success_response(start_resp)
        if not ok_start:
            return False, f"ptz_start_failed:{reason_start}"
        time.sleep(duration)
        stop_resp = self.ptz_stop()
        ok_stop, reason_stop = _is_success_response(stop_resp)
        if not ok_stop:
            return False, f"ptz_stop_failed:{reason_stop}"
        return True, ""

    def ptz_preset(self, preset_id: int = 0) -> list[dict]:
        return self.api(
            "PtzCtrl",
            {"channel": self._cfg.channel, "op": "ToPos", "id": preset_id, "speed": 25},
        )

    # ------------------------------------------------------------------
    # Auto-tracking
    # ------------------------------------------------------------------

    def set_auto_tracking(self, enabled: bool) -> list[dict]:
        return self.api(
            "SetAiCfg",
            {
                "channel": self._cfg.channel,
                "aiTrack": 1 if enabled else 0,
                "trackType": {
                    "dog_cat": 0,
                    "face": 0,
                    "people": 1 if enabled else 0,
                    "vehicle": 0,
                },
            },
        )


def _is_success_response(resp: Any) -> tuple[bool, str]:
    if not isinstance(resp, list) or not resp:
        return False, "empty_response"
    for item in resp:
        if not isinstance(item, dict):
            return False, "invalid_response_item"
        if int(item.get("code", 0) or 0) != 0:
            err = item.get("error") or {}
            detail = str(err.get("detail", "")).strip()
            rsp_code = err.get("rspCode")
            if detail:
                return False, f"code={item.get('code')} detail={detail[:120]}"
            if rsp_code is not None:
                return False, f"code={item.get('code')} rspCode={rsp_code}"
            return False, f"code={item.get('code')}"
        value = item.get("value")
        if isinstance(value, dict):
            rsp_code = value.get("rspCode")
            if rsp_code is not None:
                rsp_code_str = str(rsp_code).strip()
                if rsp_code_str not in {"0", "200"}:
                    detail = str(value.get("detail", "")).strip()
                    if detail:
                        return False, f"value.rspCode={rsp_code_str} detail={detail[:120]}"
                    return False, f"value.rspCode={rsp_code_str}"
    return True, ""


# ---------------------------------------------------------------------------
# Shared singleton client
# ---------------------------------------------------------------------------
_shared_client: ReolinkClient | None = None
_shared_lock = threading.Lock()


def get_shared_client() -> ReolinkClient:
    """Return (and lazily create) the shared Reolink client singleton."""
    global _shared_client
    with _shared_lock:
        if _shared_client is None:
            cfg = load_reolink_config()
            if not cfg.host:
                raise RuntimeError("AIHUB_REOLINK_HOST is not configured")
            _shared_client = ReolinkClient(cfg)
            log.info("Created shared Reolink client for %s", cfg.host)
        return _shared_client


def execute_camera_intent(intent: str) -> str:
    """Execute a camera intent and return a human-readable status message (Swedish)."""
    cfg = load_reolink_config()
    if not cfg.host:
        return "Reolink-kameran är inte konfigurerad."

    try:
        client = get_shared_client()
    except RuntimeError as exc:
        return f"Kunde inte ansluta till kameran: {exc}"

    try:
        if intent == "camera_follow_start":
            ok, reason = _is_success_response(client.set_auto_tracking(True))
            if not ok:
                return f"Kunde inte aktivera följning: {reason}"
            return "Automatisk följning aktiverad."

        if intent == "camera_follow_stop":
            ok, reason = _is_success_response(client.set_auto_tracking(False))
            if not ok:
                return f"Kunde inte avaktivera följning: {reason}"
            return "Automatisk följning avaktiverad."

        ptz_map = {
            "camera_ptz_left": "Left",
            "camera_ptz_right": "Right",
            "camera_ptz_up": "Up",
            "camera_ptz_down": "Down",
            "camera_zoom_in": "ZoomInc",
            "camera_zoom_out": "ZoomDec",
        }
        if intent in ptz_map:
            ok, reason = client.ptz_burst(ptz_map[intent], speed=_PTZ_SPEED, duration=_PTZ_BURST_SEC)
            if not ok:
                log.warning("PTZ burst failed for %s: %s", intent, reason)
                return f"Kunde inte styra PTZ: {reason}"
            labels = {
                "camera_ptz_left": "Vrider vänster.",
                "camera_ptz_right": "Vrider höger.",
                "camera_ptz_up": "Tittar upp.",
                "camera_ptz_down": "Tittar ner.",
                "camera_zoom_in": "Zoomar in.",
                "camera_zoom_out": "Zoomar ut.",
            }
            return labels.get(intent, "Kamerakommando skickat.")

        if intent == "camera_reset":
            ok, reason = _is_success_response(client.ptz_preset(0))
            if not ok:
                return f"Kunde inte återställa kameran: {reason}"
            return "Kameran återställs till utgångsläge."

        return "Okänt kamerakommando."

    except Exception as exc:
        log.error("Camera intent %s exception: %s", intent, exc)
        return f"Kunde inte styra kameran: {type(exc).__name__}"
