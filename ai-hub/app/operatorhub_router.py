"""operatorhub_router.py — reverse proxy for the real Operator Hub app via ai-hub.

Adding a new API endpoint to operator-hub requires NO changes here.
The wildcard /api/{path} route forwards everything automatically.
"""
from __future__ import annotations

import os

import httpx
from fastapi import APIRouter, HTTPException, Request, Response

router = APIRouter(tags=["operatorhub"])

OPERATOR_HUB_PROXY_BASE_URL = os.getenv(
    "OPERATOR_HUB_PROXY_BASE_URL", "http://operator-hub:8787"
).rstrip("/")

_PROXY_HEADERS = (
    "content-type",
    "content-length",
    "cache-control",
    "etag",
    "last-modified",
    "location",
    "accept-ranges",
    "content-range",
)


def _build_url(base: str, request: Request) -> str:
    if request.url.query:
        return f"{base}?{request.url.query}"
    return base


async def _proxy(target_url: str, request: Request, timeout: float = 60.0) -> Response:
    body = await request.body()
    headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in {"host", "connection", "content-length"}
    }
    try:
        async with httpx.AsyncClient(follow_redirects=False, timeout=timeout) as client:
            upstream = await client.request(
                request.method,
                target_url,
                content=body if body else None,
                headers=headers,
            )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Operator Hub unavailable: {exc}") from exc

    response_headers = {
        key: value for key, value in upstream.headers.items() if key.lower() in _PROXY_HEADERS
    }
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        headers=response_headers,
        media_type=upstream.headers.get("content-type"),
    )


# ── Static app shell ────────────────────────────────────────────────────────

@router.get("/operatorhub")
async def operatorhub_root(request: Request) -> Response:
    url = _build_url(f"{OPERATOR_HUB_PROXY_BASE_URL}/operatorhub-app/boards/daily", request)
    return await _proxy(url, request, timeout=1800.0)


@router.api_route(
    "/operatorhub-app",
    methods=["GET", "HEAD", "POST", "PATCH", "DELETE", "OPTIONS"],
)
async def operatorhub_app_root(request: Request) -> Response:
    url = _build_url(f"{OPERATOR_HUB_PROXY_BASE_URL}/operatorhub-app", request)
    return await _proxy(url, request, timeout=1800.0)


@router.api_route(
    "/operatorhub-app/{full_path:path}",
    methods=["GET", "HEAD", "POST", "PATCH", "DELETE", "OPTIONS"],
)
async def operatorhub_app_proxy(full_path: str, request: Request) -> Response:
    url = _build_url(f"{OPERATOR_HUB_PROXY_BASE_URL}/operatorhub-app/{full_path}", request)
    return await _proxy(url, request, timeout=1800.0)


# ── API wildcard — forwards ALL /api/* to operator-hub ──────────────────────
# No changes needed here when adding new endpoints to server.mjs.

@router.api_route(
    "/api/{full_path:path}",
    methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
)
async def api_wildcard_proxy(full_path: str, request: Request) -> Response:
    url = _build_url(f"{OPERATOR_HUB_PROXY_BASE_URL}/api/{full_path}", request)
    return await _proxy(url, request)
