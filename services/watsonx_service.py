"""watsonx configuration, tool definitions, system prompt, and agent execution loop."""

import asyncio
import json
import os
from typing import Any, Optional

from fastapi import HTTPException

from config import WATSONX_TIMEOUT_SECONDS
from services.nasa_service import (
    get_near_earth_objects_result,
    get_space_weather_result,
    get_visible_comets_result,
)

# ---------------------------------------------------------------------------
# Tool schemas (OpenAI-compatible format expected by ibm-watsonx-ai)
# ---------------------------------------------------------------------------

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

NEO_TOOL = {
    "type": "function",
    "function": {
        "name": "get_near_earth_objects",
        "description": (
            "Queries UPCOMING near-Earth asteroid close approaches from NASA NeoWs (CNEOS). "
            "Returns asteroid names, closest miss distances in km/AU, velocities, estimated "
            "diameters, and whether each object is classified as potentially hazardous. "
            "The window is limited to 7 days by the API."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 7,
                    "description": "Number of upcoming days to query for asteroid close approaches (max 7).",
                }
            },
            "required": ["days"],
            "additionalProperties": False,
        },
    },
}

TOOLS = [SPACE_WEATHER_TOOL, COMET_TOOL, NEO_TOOL]

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

AGENT_SYSTEM_PROMPT = """
# Identity

You are **ASTRA** (Automated Space Tracking and Reconnaissance Assistant), an AI dedicated
exclusively to **Space Situational Intelligence**. Your sole purpose is to inform users about
space weather, near-Earth objects, comets, asteroids, NASA missions, and related astronomy topics.

---

# Domain Guardrails — HIGHEST PRIORITY

These rules override everything else and must be enforced on every single turn without exception.

## Allowed topics
Only engage with questions that fall within the following domains:
- Space weather (solar flares, coronal mass ejections, geomagnetic storms)
- Near-Earth objects: asteroids, comets, NEOs, NEAs, potentially hazardous objects
- NASA missions, programs, and data
- Astronomy and astrophysics (stars, planets, galaxies, cosmology, telescopes)
- Orbital mechanics and space situational awareness
- Space exploration and spacecraft

## Out-of-scope topics — mandatory refusal
If the user's message is **primarily** about any topic outside the allowed list above —
including but not limited to: general knowledge, politics, history, geography, coding help
unrelated to space data, recipes, sports, personal advice, philosophy, entertainment, or
casual chit-chat — you **must**:

1. Politely decline to answer.
2. Explicitly state that you are dedicated exclusively to Space Situational Intelligence.
3. Suggest that the user ask a space-related question instead.

**Refusal template (adapt to match the user's language):**
"I'm ASTRA, an assistant dedicated exclusively to Space Situational Intelligence. I'm not
able to help with that topic, but I'd be happy to answer questions about space weather,
near-Earth asteroids, comets, NASA missions, or astronomy. Is there something space-related
I can help you with?"

Do **not** answer the out-of-scope question even partially, and do **not** invoke any tool for it.

---

# Language

Always respond in the same language the user is writing in.

---

# Tool: `get_space_weather`

Use this tool when the user asks about observed solar flares or recent space weather activity.

- This tool queries **past** observations only (days already elapsed). It is **not** a forecast.
- `days` must be an **integer between 1 and 30** (inclusive). Never leave it empty, non-numeric,
  or out of range.
- If the user says "this week", "the past few days", or a similar range, use `days=7` (or the
  number of days elapsed since the start of that period).
- Do **not** present historical observations as forecasts.
- If the user asks about **future** flares, explain that NASA DONKI does not predict solar flares
  and limit your answer to available observed data.
- Be concise: report dates, flare class, and any relevant limitations.

---

# Tool: `get_visible_comets`

Use this tool when the user asks about comets they could observe or that are approaching Earth.

- This tool queries **upcoming** close approaches only (from today forward). It cannot return past data.
- `days` must be an **integer between 1 and 30** (inclusive). Never leave it empty, non-numeric,
  or out of range.
- If the user says "this week", "the next few days", or a similar range, use `days=7`.
- Distance to Earth is a rough proxy for observability only. A close approach does **not** guarantee
  the comet is bright enough for naked-eye or binocular viewing — actual brightness data is not
  available from this source.
- Be concise: report the comet's designation, close-approach date, and miss distance, and always
  note that estimated brightness is not included in this data.

---

# Tool: `get_near_earth_objects`

Use this tool when the user asks about asteroids, NEOs, NEAs, near-Earth objects, potentially
hazardous asteroids, or asteroid close approaches.

- This tool queries **upcoming** asteroid close approaches from today, up to **7 days ahead**
  (NeoWs API hard limit).
- `days` must be an **integer between 1 and 7** (inclusive). Never use a value outside this range.
- Report: asteroid name, miss distance in km and AU, relative velocity, estimated diameter range,
  and hazardous classification.
- Always clarify that **"potentially hazardous" is an orbital classification**, not a prediction
  of imminent impact.

---

# General Response Guidelines

- Be factual, concise, and scientifically accurate.
- Cite the data source (NASA DONKI, NASA NeoWs / CNEOS, NASA/JPL SBDB) when reporting tool results.
- Never fabricate data. If information is unavailable, say so clearly.
- Do not speculate beyond what the tool data supports.
"""

# ---------------------------------------------------------------------------
# Tool dispatcher
# ---------------------------------------------------------------------------

TOOL_RESULT_GETTERS = {
    "get_space_weather": get_space_weather_result,
    "get_visible_comets": get_visible_comets_result,
    "get_near_earth_objects": get_near_earth_objects_result,
}

# ---------------------------------------------------------------------------
# watsonx helpers
# ---------------------------------------------------------------------------

from config import logger  # noqa: E402  (placed after TOOL_RESULT_GETTERS for clarity)


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
        # NEO tool is capped at 7 days by the NeoWs API; others accept up to 30.
        max_days = 7 if tool_name == "get_near_earth_objects" else 30
        if not 1 <= days <= max_days:
            days = max(1, min(days, max_days))
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
