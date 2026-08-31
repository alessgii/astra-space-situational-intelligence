"""APIRouter for space data endpoints: solar flares, comet approaches, and asteroids."""

from fastapi import APIRouter, Query

from models.space_models import AsteroidResponse, CometApproachResponse, SolarFlareResponse
from services.nasa_service import (
    get_near_earth_objects_result,
    get_space_weather_result,
    get_visible_comets_result,
)

router = APIRouter()


@router.get("/api/space-weather/solar-flares", response_model=SolarFlareResponse)
async def recent_solar_flares(
    days: int = Query(default=3, ge=1, le=30),
) -> SolarFlareResponse:
    """Return a token-conscious view of observed DONKI solar flares."""
    return await get_space_weather_result(days)


@router.get("/api/comets/close-approaches", response_model=CometApproachResponse)
async def upcoming_comet_approaches(
    days: int = Query(default=14, ge=1, le=30),
    max_distance_au: float = Query(default=0.5, gt=0, le=1.3),
) -> CometApproachResponse:
    """Return a token-conscious view of upcoming near-Earth comet approaches (NASA/JPL SBDB)."""
    return await get_visible_comets_result(days, max_distance_au)


@router.get("/api/asteroids/close-approaches", response_model=AsteroidResponse)
async def upcoming_asteroid_approaches(
    days: int = Query(default=7, ge=1, le=7, description="Days ahead to query (NeoWs max: 7)."),
) -> AsteroidResponse:
    """Return upcoming near-Earth asteroid close approaches from NASA NeoWs (CNEOS)."""
    return await get_near_earth_objects_result(days)
