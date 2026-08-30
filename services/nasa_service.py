"""NASA external API clients: DONKI solar-flare data and JPL SBDB comet approaches."""

import os
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

import httpx
from fastapi import HTTPException

from config import NASA_HTTP_TIMEOUT
from models.space_models import (
    CometApproachEvent,
    CometApproachResponse,
    SolarFlareEvent,
    SolarFlareResponse,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# DONKI — solar flares
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# JPL SBDB — comet close approaches
# ---------------------------------------------------------------------------

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
