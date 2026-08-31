"""Base Pydantic models: SpaceDomain, Location, ChatRequest, Intent, ChatResponse."""

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


class SpaceDomain(str, Enum):
    SPACE_WEATHER = "space_weather"
    NEAR_EARTH_OBJECTS = "near_earth_objects"
    COMETS = "comets"
    UNKNOWN = "unknown"


class Location(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    location: Optional[Location] = None

    @field_validator("message")
    @classmethod
    def message_must_not_be_blank(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("message must not be blank")
        return normalized


class Intent(BaseModel):
    domain: SpaceDomain
    confidence: float = Field(ge=0, le=1)
    suggested_tool: Optional[str] = None


class ChatResponse(BaseModel):
    request_id: str
    status: str
    received_message: str
    intent: Intent
    next_action: str
    answer: str
    received_at: datetime
    tool_used: Optional[str] = None
    tool_result: Optional[dict[str, Any]] = None
