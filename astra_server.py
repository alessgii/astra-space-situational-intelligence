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

# 12s was too tight for these upstream NASA/JPL services on a slow day (especially
# with the shared DEMO_KEY); give the connection more room before giving up.
NASA_HTTP_TIMEOUT = httpx.Timeout(20.0, connect=8.0)


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

COMET_TOOL = {
    "type": "function",
    "function": {
        "name": "get_visible_comets",
        "description": (
            "Queries UPCOMING close approaches of comets to Earth from NASA/JPL's "
            "Small-Body Database (SBDB) Close-Approach Data API. Distance to Earth is "
            "the best proxy for potential observability available here; it is NOT a "
            "guarantee of naked-eye or binocular visibility, which also depends on the "
            "comet's actual brightness at the time."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 30,
                    "description": "Number of upcoming days to query for comet close approaches.",
                }
            },
            "required": ["days"],
            "additionalProperties": False,
        },
    },
}

TOOLS = [SPACE_WEATHER_TOOL, COMET_TOOL]

AGENT_SYSTEM_PROMPT = """"You are ASTRA, a space situational intelligence assistant. 
Respond in the user's language. Use get_space_weather when you need observed solar flares. 
This tool ONLY queries the past (days that have already passed), never the future.
 If the user asks about 'this week', 'the past few days', or a similar range, interpret that as days=7 
 (or the number of days elapsed from the start of that week until today) and always use an integer between 1 and 30. 
 Never leave days empty, as non-numeric text, or outside that range. Do not present historical observations as forecasts.
  If they ask about the future, explain that DONKI does not predict flares and limit your conclusions to the available data.
   Be brief, state dates, flare class, and potential limitations.
Use get_visible_comets when the user asks about comets they could observe or that are approaching Earth.
This tool ONLY queries UPCOMING close approaches (from today forward), never the past.
If the user asks about 'this week', 'the next few days', or a similar range, interpret that as days=7
and always use an integer between 1 and 30. Never leave days empty, as non-numeric text, or outside that range.
Distance to Earth is only a rough proxy for observability: a close comet is not necessarily bright enough
to see with the naked eye or binoculars. Be brief, state the comet's designation, close-approach date, and
distance, and note that estimated brightness is not part of this data source."
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


async def fetch_donki_flares(start_date: date, end_date: date) -> list[dict[str, Any]]:
    params = {
        "startDate": start_date.isoformat(),
        "endDate": end_date.isoformat(),
        "api_key": nasa_api_key(),
    }
    try:
        async with httpx.AsyncClient(timeout=NASA_HTTP_TIMEOUT) as client:
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


async def fetch_jpl_comet_approaches(
    start_date: date, end_date: date, dist_max_au: float
) -> dict[str, Any]:
    params = {
        "date-min": start_date.isoformat(),
        "date-max": end_date.isoformat(),
        "dist-max": str(dist_max_au),
        "kind": "c",
        "sort": "date",
    }
    try:
        async with httpx.AsyncClient(timeout=NASA_HTTP_TIMEOUT) as client:
            response = await client.get("https://ssd-api.jpl.nasa.gov/cad.api", params=params)
            response.raise_for_status()
            payload = response.json()
    except httpx.TimeoutException as error:
        raise HTTPException(status_code=503, detail="NASA/JPL SBDB took too long to respond.") from error
    except (httpx.HTTPError, ValueError) as error:
        raise HTTPException(status_code=502, detail="Could not retrieve valid data from NASA/JPL SBDB.") from error

    if not isinstance(payload, dict):
        raise HTTPException(status_code=502, detail="NASA/JPL SBDB returned an unexpected format.")
    return payload


def compact_comet_approaches(payload: dict[str, Any]) -> list[CometApproachEvent]:
    # A too-restrictive query returns a zero-count payload with no "fields"/"data"
    # keys at all (e.g. {"signature": {...}, "count": 0}) — that's a valid empty
    # result, not a malformed response, so we treat it as "no comets found".
    fields: list[str] = payload.get("fields") or []
    rows: list[list[str]] = payload.get("data") or []
    if not fields or not rows:
        return []

    index = {name: position for position, name in enumerate(fields)}

    def _float(row: list[str], key: str) -> Optional[float]:
        value = row[index[key]] if key in index else None
        try:
            return float(value) if value not in (None, "") else None
        except (TypeError, ValueError):
            return None

    def _parsed_date(row: list[str]) -> Optional[datetime]:
        raw = row[index["cd"]] if "cd" in index else None
        if not raw:
            return None
        try:
            return datetime.strptime(raw, "%Y-%b-%d %H:%M").replace(tzinfo=timezone.utc)
        except ValueError:
            return None

    events = [
        CometApproachEvent(
            designation=str(row[index["des"]]) if "des" in index else "unknown",
            close_approach=_parsed_date(row),
            distance_au=_float(row, "dist"),
            distance_min_au=_float(row, "dist_min"),
            velocity_rel_kms=_float(row, "v_rel"),
            absolute_magnitude_h=_float(row, "h"),
            source_url=(
                f"https://ssd.jpl.nasa.gov/tools/sbdb_lookup.html#/?sstr={row[index['des']]}"
                if "des" in index
                else None
            ),
        )
        for row in rows
    ]
    return sorted(
        events,
        key=lambda event: event.close_approach or datetime.max.replace(tzinfo=timezone.utc),
    )


async def get_visible_comets_result(days: int, max_distance_au: float = 0.5) -> CometApproachResponse:
    start_date = datetime.now(timezone.utc).date()
    end_date = start_date + timedelta(days=days - 1)
    payload = await fetch_jpl_comet_approaches(start_date, end_date, max_distance_au)
    events = compact_comet_approaches(payload)
    closest = min(
        events,
        key=lambda event: event.distance_au if event.distance_au is not None else float("inf"),
        default=None,
    )

    summary = (
        f"NASA/JPL SBDB found {len(events)} comet close approach(es) within {max_distance_au} AU "
        f"between {start_date.isoformat()} and {end_date.isoformat()}."
        if events
        else f"NASA/JPL SBDB found no comet close approaches within {max_distance_au} AU in the queried interval."
    )
    return CometApproachResponse(
        source="NASA/JPL SBDB (CAD API)",
        query_start=start_date,
        query_end=end_date,
        max_distance_au=max_distance_au,
        event_count=len(events),
        closest_distance_au=closest.distance_au if closest else None,
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


WATSONX_TIMEOUT_SECONDS = 45.0


async def watsonx_chat(model, messages: list[dict[str, Any]]) -> dict[str, Any]:
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(
                model.chat,
                messages=messages,
                tools=TOOLS,
                tool_choice_option="auto",
            ),
            timeout=WATSONX_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError as error:
        raise HTTPException(
            status_code=504,
            detail="watsonx took too long to respond.",
        ) from error
    except Exception as error:
        raise HTTPException(
            status_code=502,
            detail="watsonx could not process the request.",
        ) from error


TOOL_RESULT_GETTERS = {
    "get_space_weather": get_space_weather_result,
    "get_visible_comets": get_visible_comets_result,
}


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
    if tool_name not in TOOL_RESULT_GETTERS:
        raise HTTPException(status_code=502, detail="watsonx requested a disallowed tool.")

    try:
        raw_arguments = function.get("arguments") or "{}"
        arguments = json.loads(raw_arguments)
        # granite-4-h-small sometimes double-encodes the arguments: the first
        # json.loads() yields a JSON string instead of a dict, so parse again.
        if isinstance(arguments, str):
            arguments = json.loads(arguments)
        days = int(float(arguments["days"]))
        if not 1 <= days <= 30:
            raise ValueError
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        logger.error(
            "Invalid tool_call arguments for %s: %r",
            tool_name,
            function.get("arguments"),
        )
        raise HTTPException(status_code=502, detail="watsonx generated invalid tool arguments.") from error

    tool_result_model = await TOOL_RESULT_GETTERS[tool_name](days)
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


@app.get("/api/comets/close-approaches", response_model=CometApproachResponse)
async def upcoming_comet_approaches(
    days: int = Query(default=14, ge=1, le=30),
    max_distance_au: float = Query(default=0.5, gt=0, le=1.3),
) -> CometApproachResponse:
    """Return a token-conscious view of upcoming near-Earth comet approaches (NASA/JPL SBDB)."""
    return await get_visible_comets_result(days, max_distance_au)


# Keep this last: API routes must be evaluated before the catch-all static mount.
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")