"""APIRouter for /api/space-weather/solar-flares and /api/comets/close-approaches."""

from fastapi import APIRouter, Query

from models.space_models import CometApproachResponse, SolarFlareResponse
from services.nasa_service import get_space_weather_result, get_visible_comets_result

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
