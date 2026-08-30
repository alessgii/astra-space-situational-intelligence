"""APIRouter for /api/health and /api/chat."""

from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from models.schemas import ChatRequest, ChatResponse, Intent, SpaceDomain
from services.watsonx_service import run_watsonx_agent, watsonx_is_configured

router = APIRouter()

# ---------------------------------------------------------------------------
# Intent detection (lightweight keyword heuristic)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "astra-api"}


@router.post("/api/chat", response_model=ChatResponse)
async def receive_question(payload: ChatRequest) -> ChatResponse:
    intent = detect_intent(payload.message)

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
