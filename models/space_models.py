"""Space data Pydantic models: solar flares and comet close approaches."""

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
