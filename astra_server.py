"""ASTRA API entry point.

This module adds the first backend boundary without changing the existing demo.
Run it with: uvicorn astra_server:app --reload
"""

import os
import asyncio
import json
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

import logging

import httpx
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, validator
from dotenv import load_dotenv

logger = logging.getLogger("astra")


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
load_dotenv(BASE_DIR / ".env")

logging.basicConfig(level=logging.INFO)


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

    @validator("message")
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


class AsteroidEvent(BaseModel):
    id: str
    name: str
    absolute_magnitude: Optional[float] = None
    estimated_diameter_min_meters: Optional[float] = None
    estimated_diameter_max_meters: Optional[float] = None
    potentially_hazardous: bool
    close_approach_date: date
    relative_velocity_kph: Optional[float] = None
    miss_distance_kilometers: Optional[float] = None
    orbiting_body: Optional[str] = None
    source_url: Optional[str] = None


class AsteroidResponse(BaseModel):
    source: str
    query_start: date
    query_end: date
    upcoming_events_only: bool
    event_count: int
    hazardous_count: int
    closest_asteroid: Optional[str] = None
    summary: str
    events: list[AsteroidEvent]
    fetched_at: datetime


DOMAIN_KEYWORDS = {
    SpaceDomain.SPACE_WEATHER: {
        "solar", "sol", "llamarada", "llamaradas", "tormenta solar",
        "geomagnética", "geomagnetica", "telecomunicaciones", "cme",
        "flare", "flares", "space weather", "sunspot",
    },
    SpaceDomain.NEAR_EARTH_OBJECTS: {
        "asteroide", "asteroides", "asteroid", "asteroids", "neo", "nea",
        "objeto cercano", "impacto", "close approach", "potentially hazardous",
    },
    SpaceDomain.COMETS: {
        "cometa", "cometas", "comet", "comets", "visible", "observar",
        "observación", "observacion", "binoculares",
    },
}

TOOL_BY_DOMAIN = {
    SpaceDomain.SPACE_WEATHER: "get_space_weather",
    SpaceDomain.NEAR_EARTH_OBJECTS: "get_near_earth_objects",
    SpaceDomain.COMETS: "get_visible_comets",
}

SPACE_WEATHER_TOOL = {
    "type": "function",
    "function": {
        "name": "get_space_weather",
        "description": (
            "Queries OBSERVED solar flares recently recorded in NASA DONKI. "
            "This is not a forecast of future flares."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 30,
                    "description": "Number of recent days to query.",
                }
            },
            "required": ["days"],
            "additionalProperties": False,
        },
    },
}

NEAR_EARTH_OBJECTS_TOOL = {
    "type": "function",
    "function": {
        "name": "get_near_earth_objects",
        "description": (
            "Queries near-Earth asteroid approaches from today onward using NASA NeoWs. "
            "The query window can contain at most 7 days."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 7,
                    "description": "Number of days to query, including today.",
                }
            },
            "required": ["days"],
            "additionalProperties": False,
        },
    },
}

AGENT_SYSTEM_PROMPT = """You are ASTRA, a space situational intelligence assistant.
Respond in the user's language. Use get_space_weather when you need observed solar flares.
This tool ONLY queries the past (days that have already passed), never the future.
If the user asks about 'this week', 'the past few days', or a similar range, interpret that as days=7
(or the number of days elapsed from the start of that week until today) and always use an integer between 1 and 30.
Never leave days empty, as non-numeric text, or outside that range. Do not present historical observations as forecasts.
If they ask about future solar flares, explain that DONKI does not predict them and limit your conclusions to available data.
Use get_near_earth_objects for near-Earth asteroid approaches. It queries from today onward and requires days between 1 and 7.
Do not imply that a potentially hazardous classification means an impact is predicted.
Be brief, state dates, relevant measurements, sources, and potential limitations.
"""

def detect_intent(message: str) -> Intent:
    """Provide a lightweight hint; watsonx will make the final tool decision."""
    normalized = message.casefold()
    scores = {
        domain: sum(keyword in normalized for keyword in keywords)
        for domain, keywords in DOMAIN_KEYWORDS.items()
    }
    domain, score = max(scores.items(), key=lambda item: item[1])

    if score == 0:
        return Intent(domain=SpaceDomain.UNKNOWN, confidence=0.0)

    confidence = min(0.55 + (score - 1) * 0.12, 0.91)
    return Intent(
        domain=domain,
        confidence=confidence,
        suggested_tool=TOOL_BY_DOMAIN[domain],
    )


def nasa_api_key() -> str:
    configured_key = os.getenv("NASA_API_KEY", "").strip()
    if not configured_key or configured_key == "NASA_API_KEY":
        return "DEMO_KEY"
    return configured_key


def flare_strength(class_type: Optional[str]) -> tuple[int, float]:
    if not class_type:
        return (0, 0.0)
    normalized = class_type.strip().upper()
    class_rank = {"A": 1, "B": 2, "C": 3, "M": 4, "X": 5}
    try:
        magnitude = float(normalized[1:])
    except (TypeError, ValueError):
        magnitude = 0.0
    return (class_rank.get(normalized[:1], 0), magnitude)


def compact_flares(raw_events: list[dict[str, Any]]) -> list[SolarFlareEvent]:
    events = [
        SolarFlareEvent(
            id=str(event.get("flrID") or "unknown"),
            class_type=event.get("classType"),
            begin_time=event.get("beginTime"),
            peak_time=event.get("peakTime"),
            end_time=event.get("endTime"),
            active_region=event.get("activeRegionNum"),
            source_location=event.get("sourceLocation"),
            source_url=event.get("link"),
        )
        for event in raw_events
    ]
    return sorted(
        events,
        key=lambda event: event.begin_time.timestamp() if event.begin_time else 0.0,
        reverse=True,
    )


def compact_asteroids(raw_events: dict[str, list[dict[str, Any]]]) -> list[AsteroidEvent]:
    events: list[AsteroidEvent] = []
    for approach_date, asteroids in raw_events.items():
        for asteroid in asteroids:
            diameter = asteroid.get("estimated_diameter", {}).get("meters", {})
            approaches = asteroid.get("close_approach_data") or [{}]
            approach = next(
                (
                    item
                    for item in approaches
                    if item.get("close_approach_date") == approach_date
                ),
                approaches[0],
            )
            events.append(
                AsteroidEvent(
                    id=str(asteroid.get("id") or asteroid.get("neo_reference_id") or "unknown"),
                    name=str(asteroid.get("name") or "Unknown asteroid"),
                    absolute_magnitude=asteroid.get("absolute_magnitude_h"),
                    estimated_diameter_min_meters=diameter.get("estimated_diameter_min"),
                    estimated_diameter_max_meters=diameter.get("estimated_diameter_max"),
                    potentially_hazardous=bool(
                        asteroid.get("is_potentially_hazardous_asteroid", False)
                    ),
                    close_approach_date=approach.get("close_approach_date") or approach_date,
                    relative_velocity_kph=(
                        approach.get("relative_velocity", {}).get("kilometers_per_hour")
                    ),
                    miss_distance_kilometers=(
                        approach.get("miss_distance", {}).get("kilometers")
                    ),
                    orbiting_body=approach.get("orbiting_body"),
                    source_url=asteroid.get("nasa_jpl_url"),
                )
            )
    return sorted(
        events,
        key=lambda event: (
            event.close_approach_date,
            event.miss_distance_kilometers
            if event.miss_distance_kilometers is not None
            else float("inf"),
        ),
    )


async def fetch_donki_flares(start_date: date, end_date: date) -> list[dict[str, Any]]:
    params = {
        "startDate": start_date.isoformat(),
        "endDate": end_date.isoformat(),
        "api_key": nasa_api_key(),
    }
    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            response = await client.get("https://api.nasa.gov/DONKI/FLR", params=params)
            response.raise_for_status()
            payload = response.json()
    except httpx.TimeoutException as error:
        raise HTTPException(status_code=503, detail="NASA DONKI took too long to respond.") from error
    except (httpx.HTTPError, ValueError) as error:
        raise HTTPException(status_code=502, detail="Could not retrieve valid data from NASA DONKI.") from error

    if not isinstance(payload, list):
        raise HTTPException(status_code=502, detail="NASA DONKI returned an unexpected format.")
    return payload


async def fetch_neows_asteroids(
    start_date: date,
    end_date: date,
) -> dict[str, list[dict[str, Any]]]:
    params = {
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "api_key": nasa_api_key(),
    }
    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            response = await client.get(
                "https://api.nasa.gov/neo/rest/v1/feed",
                params=params,
            )
            response.raise_for_status()
            payload = response.json()
    except httpx.TimeoutException as error:
        raise HTTPException(status_code=503, detail="NASA NeoWs took too long to respond.") from error
    except (httpx.HTTPError, ValueError) as error:
        raise HTTPException(status_code=502, detail="Could not retrieve valid data from NASA NeoWs.") from error

    near_earth_objects = payload.get("near_earth_objects") if isinstance(payload, dict) else None
    if not isinstance(near_earth_objects, dict) or not all(
        isinstance(events, list) for events in near_earth_objects.values()
    ):
        raise HTTPException(status_code=502, detail="NASA NeoWs returned an unexpected format.")
    return near_earth_objects


async def get_space_weather_result(days: int) -> SolarFlareResponse:
    end_date = datetime.now(timezone.utc).date()
    start_date = end_date - timedelta(days=days - 1)
    events = compact_flares(await fetch_donki_flares(start_date, end_date))
    strongest = max(events, key=lambda event: flare_strength(event.class_type), default=None)

    summary = (
        f"NASA DONKI recorded {len(events)} solar flare(s) between "
        f"{start_date.isoformat()} and {end_date.isoformat()}."
        if events
        else "NASA DONKI recorded no solar flares in the queried interval."
    )
    return SolarFlareResponse(
        source="NASA DONKI",
        query_start=start_date,
        query_end=end_date,
        observed_events_only=True,
        event_count=len(events),
        strongest_class=strongest.class_type if strongest else None,
        summary=summary,
        events=events,
        fetched_at=datetime.now(timezone.utc),
    )


async def get_asteroid_result(days: int) -> AsteroidResponse:
    start_date = datetime.now(timezone.utc).date()
    end_date = start_date + timedelta(days=days - 1)
    events = compact_asteroids(await fetch_neows_asteroids(start_date, end_date))
    hazardous_count = sum(event.potentially_hazardous for event in events)
    closest = min(
        events,
        key=lambda event: (
            event.miss_distance_kilometers
            if event.miss_distance_kilometers is not None
            else float("inf")
        ),
        default=None,
    )

    summary = (
        f"NASA NeoWs listed {len(events)} near-Earth asteroid approach(es) between "
        f"{start_date.isoformat()} and {end_date.isoformat()}; "
        f"{hazardous_count} are classified as potentially hazardous."
        if events
        else "NASA NeoWs listed no near-Earth asteroid approaches in the queried interval."
    )
    return AsteroidResponse(
        source="NASA NeoWs",
        query_start=start_date,
        query_end=end_date,
        upcoming_events_only=True,
        event_count=len(events),
        hazardous_count=hazardous_count,
        closest_asteroid=closest.name if closest else None,
        summary=summary,
        events=events,
        fetched_at=datetime.now(timezone.utc),
    )


def watsonx_is_configured() -> bool:
    required = ("IBM_CLOUD_API_KEY", "WATSONX_PROJECT_ID", "WATSONX_URL")
    return all(
        os.getenv(name, "").strip() not in {"", name}
        for name in required
    )


def create_watsonx_model():
    try:
        from ibm_watsonx_ai import Credentials
        from ibm_watsonx_ai.foundation_models import ModelInference
    except ImportError as error:
        raise HTTPException(
            status_code=503,
            detail="The ibm-watsonx-ai dependency is not installed.",
        ) from error

    credentials = Credentials(
        url=os.environ["WATSONX_URL"],
        api_key=os.environ["IBM_CLOUD_API_KEY"],
    )
    try:
        return ModelInference(
            model_id=os.getenv("WATSONX_MODEL_ID", "ibm/granite-4-h-small"),
            credentials=credentials,
            project_id=os.environ["WATSONX_PROJECT_ID"],
        )
    except Exception as error:
        raise HTTPException(
            status_code=502,
            detail=(
                "Could not initialise the watsonx model. Ensure that "
                "WATSONX_MODEL_ID is a model supported in your project/region "
                "and that the project_id has an associated Watson Machine "
                f"Learning instance. Detail: {error}"
            ),
        ) from error


async def watsonx_chat(model, messages: list[dict[str, Any]]) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(
            model.chat,
            messages=messages,
            tools=[SPACE_WEATHER_TOOL, NEAR_EARTH_OBJECTS_TOOL],
            tool_choice_option="auto",
        )
    except Exception as error:
        raise HTTPException(
            status_code=502,
            detail="watsonx could not process the request.",
        ) from error


async def run_watsonx_agent(message: str) -> tuple[str, Optional[str], Optional[dict[str, Any]]]:
    model = create_watsonx_model()
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": AGENT_SYSTEM_PROMPT},
        {"role": "user", "content": message},
    ]
    first_response = await watsonx_chat(model, messages)
    try:
        assistant_message = first_response["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as error:
        raise HTTPException(status_code=502, detail="watsonx returned an unexpected response.") from error

    tool_calls = assistant_message.get("tool_calls") or []
    if not tool_calls:
        return (assistant_message.get("content") or "No response from the model.", None, None)

    tool_call = tool_calls[0]
    function = tool_call.get("function") or {}
    tool_name = function.get("name")
    maximum_days_by_tool = {
        "get_space_weather": 30,
        "get_near_earth_objects": 7,
    }
    if tool_name not in maximum_days_by_tool:
        raise HTTPException(status_code=502, detail="watsonx requested a disallowed tool.")

    try:
        raw_arguments = function.get("arguments") or "{}"
        arguments = json.loads(raw_arguments)
        # granite-4-h-small sometimes double-encodes the arguments: the first
        # json.loads() yields a JSON string instead of a dict, so parse again.
        if isinstance(arguments, str):
            arguments = json.loads(arguments)
        days = int(float(arguments["days"]))
        if not 1 <= days <= maximum_days_by_tool[tool_name]:
            raise ValueError
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        logger.error(
            "Invalid tool_call arguments for %s: %r",
            tool_name,
            function.get("arguments"),
        )
        raise HTTPException(status_code=502, detail="watsonx generated invalid tool arguments.") from error

    if tool_name == "get_space_weather":
        tool_result_model = await get_space_weather_result(days)
    else:
        tool_result_model = await get_asteroid_result(days)
    tool_result = tool_result_model.model_dump(mode="json")
    messages.extend(
        [
            assistant_message,
            {
                "role": "tool",
                "tool_call_id": tool_call.get("id"),
                "name": tool_name,
                "content": json.dumps(tool_result, ensure_ascii=False),
            },
        ]
    )
    final_response = await watsonx_chat(model, messages)
    try:
        answer = final_response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as error:
        raise HTTPException(status_code=502, detail="watsonx did not generate a valid final response.") from error
    return (answer, tool_name, tool_result)


app = FastAPI(
    title="ASTRA Space Situational Intelligence API",
    version="0.1.0",
    description="Receives natural-language space queries for later watsonx processing.",
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Guarantee JSON responses even for bugs we didn't anticipate.

    Without this, an uncaught exception falls through to Starlette's default
    handler, which returns a *plain text* 500 response — that breaks any
    frontend doing `await response.json()`.
    """
    logger.exception("Unhandled error while processing %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "An unexpected internal error occurred in the ASTRA server."},
    )


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "astra-api"}


@app.post("/api/chat", response_model=ChatResponse)
async def receive_question(payload: ChatRequest) -> ChatResponse:
    intent = detect_intent(payload.message)
    understood = intent.domain is not SpaceDomain.UNKNOWN

    if watsonx_is_configured():
        answer, tool_used, tool_result = await run_watsonx_agent(payload.message)
        return ChatResponse(
            request_id=str(uuid4()),
            status="completed",
            received_message=payload.message,
            intent=intent,
            next_action="none",
            answer=answer,
            received_at=datetime.now(timezone.utc),
            tool_used=tool_used,
            tool_result=tool_result,
        )

    return ChatResponse(
        request_id=str(uuid4()),
        status="accepted",
        received_message=payload.message,
        intent=intent,
        next_action="configure_watsonx_credentials",
        answer="The integration is ready, but watsonx credentials are missing on the server.",
        received_at=datetime.now(timezone.utc),
    )


@app.get("/api/space-weather/solar-flares", response_model=SolarFlareResponse)
async def recent_solar_flares(
    days: int = Query(default=3, ge=1, le=30),
) -> SolarFlareResponse:
    """Return a token-conscious view of observed DONKI solar flares."""
    return await get_space_weather_result(days)


@app.get("/api/near-earth-objects/asteroids", response_model=AsteroidResponse)
async def upcoming_asteroids(
    days: int = Query(default=3, ge=1, le=7),
) -> AsteroidResponse:
    """Return a token-conscious view of upcoming asteroid approaches from NeoWs."""
    return await get_asteroid_result(days)


# Keep this last: API routes must be evaluated before the catch-all static mount.
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
