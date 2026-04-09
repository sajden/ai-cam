"""operatorhub_router.py — reverse proxy for the real Operator Hub app via ai-hub."""
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


def _build_proxy_url(request: Request, full_path: str) -> str:
    suffix = f"/operatorhub-app/{full_path}".rstrip("/")
    if not full_path:
        suffix = "/operatorhub-app"
    if request.url.query:
        return f"{OPERATOR_HUB_PROXY_BASE_URL}{suffix}?{request.url.query}"
    return f"{OPERATOR_HUB_PROXY_BASE_URL}{suffix}"


async def _proxy_request(request: Request, full_path: str) -> Response:
    target_url = _build_proxy_url(request, full_path)
    body = await request.body()
    headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in {"host", "connection", "content-length"}
    }

    try:
        async with httpx.AsyncClient(follow_redirects=False, timeout=1800.0) as client:
            upstream = await client.request(
                request.method,
                target_url,
                content=body if body else None,
                headers=headers,
            )
    except Exception as exc:  # pragma: no cover
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


@router.get("/operatorhub")
async def operatorhub_root(request: Request) -> Response:
    return await _proxy_request(request, "boards/daily")


@router.api_route(
    "/operatorhub-app",
    methods=["GET", "HEAD", "POST", "PATCH", "DELETE", "OPTIONS"],
)
async def operatorhub_app_root(request: Request) -> Response:
    return await _proxy_request(request, "")


@router.api_route(
    "/operatorhub-app/{full_path:path}",
    methods=["GET", "HEAD", "POST", "PATCH", "DELETE", "OPTIONS"],
)
async def operatorhub_app_proxy(full_path: str, request: Request) -> Response:
    return await _proxy_request(request, full_path)
