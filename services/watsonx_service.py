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

AGENT_SYSTEM_PROMPT = """You are ASTRA, a space situational intelligence assistant.
Respond in the user's language.
Use get_space_weather when you need observed solar flares.
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
distance, and note that estimated brightness is not part of this data source.
Use get_near_earth_objects when the user asks about asteroids, NEOs, NEAs, near-Earth objects,
potentially hazardous asteroids, or asteroid close approaches.
This tool queries UPCOMING asteroid close approaches (from today, up to 7 days ahead).
Always use an integer between 1 and 7 for days. Report the asteroid name, miss distance in km and AU,
velocity, estimated size range, and whether it is classified as potentially hazardous.
Clarify that 'potentially hazardous' is an orbital classification, not a prediction of impact.
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
