"""weather_router.py — FastAPI router for the weather dashboard."""
from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse

from .weather import (
    WEATHER_DASHBOARD_HTML,
    fetch_indoor_air,
    fetch_pollen,
    fetch_warnings,
    fetch_water_temp,
    fetch_weather,
)

router = APIRouter(prefix="/weather", tags=["weather"])


@router.get("", response_class=HTMLResponse)
def weather_board() -> HTMLResponse:
    return HTMLResponse(content=WEATHER_DASHBOARD_HTML)


@router.get("/api")
def weather_api() -> JSONResponse:
    return JSONResponse(content=fetch_weather())


@router.get("/warnings")
def weather_warnings() -> JSONResponse:
    return JSONResponse(content=fetch_warnings())


@router.get("/pollen")
def weather_pollen() -> JSONResponse:
    return JSONResponse(content=fetch_pollen())


@router.get("/water")
def weather_water() -> JSONResponse:
    return JSONResponse(content=fetch_water_temp())


@router.get("/indoor")
def weather_indoor() -> JSONResponse:
    return JSONResponse(content=fetch_indoor_air())
