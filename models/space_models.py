"""Space data Pydantic models: solar flares, comet close approaches, and near-Earth asteroids."""

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel


class SolarFlareEvent(BaseModel):
    id: str
    class_type: Optional[str] = None
    begin_time: Optional[datetime] = None
    peak_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    active_region: Optional[int] = None
    source_location: Optional[str] = None
    source_url: Optional[str] = None


class SolarFlareResponse(BaseModel):
    source: str
    query_start: date
    query_end: date
    observed_events_only: bool
    event_count: int
    strongest_class: Optional[str] = None
    summary: str
    events: list[SolarFlareEvent]
    fetched_at: datetime


class CometApproachEvent(BaseModel):
    designation: str
    close_approach: Optional[datetime] = None
    distance_au: Optional[float] = None
    distance_min_au: Optional[float] = None
    velocity_rel_kms: Optional[float] = None
    absolute_magnitude_h: Optional[float] = None
    source_url: Optional[str] = None


class CometApproachResponse(BaseModel):
    source: str
    query_start: date
    query_end: date
    max_distance_au: float
    event_count: int
    closest_distance_au: Optional[float] = None
    summary: str
    events: list[CometApproachEvent]
    fetched_at: datetime


# ---------------------------------------------------------------------------
# Near-Earth Asteroids (NASA NeoWs)
# ---------------------------------------------------------------------------

class AsteroidCloseApproach(BaseModel):
    id: str
    name: str
    close_approach_date: Optional[date] = None
    miss_distance_km: Optional[float] = None
    miss_distance_au: Optional[float] = None
    relative_velocity_kms: Optional[float] = None
    estimated_diameter_min_m: Optional[float] = None
    estimated_diameter_max_m: Optional[float] = None
    is_potentially_hazardous: bool = False
    absolute_magnitude_h: Optional[float] = None
    source_url: Optional[str] = None


class AsteroidResponse(BaseModel):
    source: str
    query_start: date
    query_end: date
    event_count: int
    hazardous_count: int
    closest_miss_km: Optional[float] = None
    summary: str
    events: list[AsteroidCloseApproach]
    fetched_at: datetime
