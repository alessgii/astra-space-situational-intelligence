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

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, validator
from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
load_dotenv(BASE_DIR / ".env")


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
            "Consulta llamaradas solares OBSERVADAS recientemente en NASA DONKI. "
            "No es un pronóstico de llamaradas futuras."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 30,
                    "description": "Número de días recientes que se consultarán.",
                }
            },
            "required": ["days"],
            "additionalProperties": False,
        },
    },
}

AGENT_SYSTEM_PROMPT = """Eres ASTRA, un asistente de inteligencia situacional espacial.
Responde en el idioma del usuario. Usa get_space_weather cuando necesites llamaradas
solares observadas. No presentes observaciones históricas como pronósticos. Si preguntan
por el futuro, explica que DONKI no predice llamaradas y limita tus conclusiones a los
datos disponibles. Sé breve, indica fechas, clase de la llamarada y posibles limitaciones.
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
        async with httpx.AsyncClient(timeout=12.0) as client:
            response = await client.get("https://api.nasa.gov/DONKI/FLR", params=params)
            response.raise_for_status()
            payload = response.json()
    except httpx.TimeoutException as error:
        raise HTTPException(status_code=503, detail="NASA DONKI tardó demasiado en responder.") from error
    except (httpx.HTTPError, ValueError) as error:
        raise HTTPException(status_code=502, detail="No fue posible obtener datos válidos de NASA DONKI.") from error

    if not isinstance(payload, list):
        raise HTTPException(status_code=502, detail="NASA DONKI devolvió un formato inesperado.")
    return payload


async def get_space_weather_result(days: int) -> SolarFlareResponse:
    end_date = datetime.now(timezone.utc).date()
    start_date = end_date - timedelta(days=days - 1)
    events = compact_flares(await fetch_donki_flares(start_date, end_date))
    strongest = max(events, key=lambda event: flare_strength(event.class_type), default=None)

    summary = (
        f"NASA DONKI registró {len(events)} llamarada(s) solar(es) entre "
        f"{start_date.isoformat()} y {end_date.isoformat()}."
        if events
        else "NASA DONKI no registró llamaradas solares en el intervalo consultado."
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
            detail="Falta instalar la dependencia ibm-watsonx-ai.",
        ) from error

    credentials = Credentials(
        url=os.environ["WATSONX_URL"],
        api_key=os.environ["IBM_CLOUD_API_KEY"],
    )
    return ModelInference(
        model_id=os.getenv("WATSONX_MODEL_ID", "ibm/granite-3-3-8b-instruct"),
        credentials=credentials,
        project_id=os.environ["WATSONX_PROJECT_ID"],
    )


async def watsonx_chat(model, messages: list[dict[str, Any]]) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(
            model.chat,
            messages=messages,
            tools=[SPACE_WEATHER_TOOL],
            tool_choice_option="auto",
        )
    except Exception as error:
        raise HTTPException(
            status_code=502,
            detail="watsonx no pudo procesar la consulta.",
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
        raise HTTPException(status_code=502, detail="watsonx devolvió una respuesta inesperada.") from error

    tool_calls = assistant_message.get("tool_calls") or []
    if not tool_calls:
        return (assistant_message.get("content") or "Sin respuesta del modelo.", None, None)

    tool_call = tool_calls[0]
    function = tool_call.get("function") or {}
    if function.get("name") != "get_space_weather":
        raise HTTPException(status_code=502, detail="watsonx solicitó una herramienta no permitida.")

    try:
        arguments = json.loads(function.get("arguments") or "{}")
        days = int(arguments["days"])
        if not 1 <= days <= 30:
            raise ValueError
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise HTTPException(status_code=502, detail="watsonx generó argumentos de herramienta inválidos.") from error

    tool_result_model = await get_space_weather_result(days)
    tool_result = tool_result_model.model_dump(mode="json")
    messages.extend(
        [
            assistant_message,
            {
                "role": "tool",
                "tool_call_id": tool_call.get("id"),
                "name": "get_space_weather",
                "content": json.dumps(tool_result, ensure_ascii=False),
            },
        ]
    )
    final_response = await watsonx_chat(model, messages)
    try:
        answer = final_response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as error:
        raise HTTPException(status_code=502, detail="watsonx no generó una respuesta final válida.") from error
    return (answer, "get_space_weather", tool_result)


app = FastAPI(
    title="ASTRA Space Situational Intelligence API",
    version="0.1.0",
    description="Receives natural-language space queries for later watsonx processing.",
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
        answer="La integración está lista, pero faltan las credenciales de watsonx en el servidor.",
        received_at=datetime.now(timezone.utc),
    )


@app.get("/api/space-weather/solar-flares", response_model=SolarFlareResponse)
async def recent_solar_flares(
    days: int = Query(default=3, ge=1, le=30),
) -> SolarFlareResponse:
    """Return a token-conscious view of observed DONKI solar flares."""
    return await get_space_weather_result(days)


# Keep this last: API routes must be evaluated before the catch-all static mount.
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
