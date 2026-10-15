"""
Sakhi-Sahayak Orchestrator (Python)
-----------------------------------
Python conversion of orchestrator.js.

Responsibilities:
- Defines the LangGraph-style state names, transitions, and edge labels.
- Sends Hindi/Marathi/English safety transcripts to OpenRouter.
- Supports structured tool calls for emergency alerts, nearest-police lookup,
  and threat-email dispatch.
- Logs transcript analysis locally in the evidence directory.

Environment:
    OPENROUTER_API_KEY
    OPENROUTER_MODEL (optional; defaults to openai/gpt-4o-mini)
    SAFETY_DATA_PATH (optional; defaults to ./safety_data.json)
    EVIDENCE_DIR (optional; defaults to ./evidence)

This module analyzes transcripts and returns actions. The caller (voice agent /
state machine) must manage the intercept countdown and invoke emergency dispatch.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

import httpx

logger = logging.getLogger("sakhi_sahayak.orchestrator")

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini")

BASE_DIR = Path(__file__).resolve().parent
SAFETY_DATA_PATH = Path(os.getenv("SAFETY_DATA_PATH", str(BASE_DIR / "safety_data.json")))
EVIDENCE_DIR = Path(os.getenv("EVIDENCE_DIR", str(BASE_DIR / "evidence")))

# Optional async/sync callback for the converted email module. Set this from the
# application during startup if you want transcript emails dispatched here.
_transcription_email_sender: Callable[..., Any] | None = None
_nearest_police_provider: Callable[[float, float], Any] | None = None


def set_nearest_police_provider(callback: Callable[[float, float], Any] | None) -> None:
    """Optionally use the application's local SQLite police-station catalogue."""
    global _nearest_police_provider
    _nearest_police_provider = callback


def set_transcription_email_sender(callback: Callable[..., Any] | None) -> None:
    """Register a callback compatible with send_transcription_email(payload)."""
    global _transcription_email_sender
    _transcription_email_sender = callback


STATES = {
    "IDLE": "IDLE",
    "MONITORING": "MONITORING",
    "THREAT_DETECTED": "THREAT_DETECTED",
    "INTERCEPT_COUNTDOWN": "INTERCEPT_COUNTDOWN",
    "EMERGENCY_PROTOCOL": "EMERGENCY_PROTOCOL",
    "RECORDING": "RECORDING",
    "RESOLVED": "RESOLVED",
}

EDGES = {
    STATES["IDLE"]: [STATES["MONITORING"]],
    STATES["MONITORING"]: [
        STATES["IDLE"], STATES["THREAT_DETECTED"], STATES["EMERGENCY_PROTOCOL"]
    ],
    STATES["THREAT_DETECTED"]: [
        STATES["MONITORING"], STATES["INTERCEPT_COUNTDOWN"], STATES["EMERGENCY_PROTOCOL"]
    ],
    STATES["INTERCEPT_COUNTDOWN"]: [
        STATES["MONITORING"], STATES["EMERGENCY_PROTOCOL"]
    ],
    STATES["EMERGENCY_PROTOCOL"]: [STATES["RECORDING"]],
    STATES["RECORDING"]: [STATES["RESOLVED"]],
    STATES["RESOLVED"]: [STATES["MONITORING"]],
}

EDGE_CONDITIONS = {
    "IDLE->MONITORING": "Route started / Sarthi activated",
    "MONITORING->IDLE": "Route ended / Sarthi disabled",
    "MONITORING->THREAT_DETECTED": "Orchestrator LLM confirms distress",
    "MONITORING->EMERGENCY_PROTOCOL": "User presses manual SOS",
    "THREAT_DETECTED->MONITORING": 'User clicks "I\'m Safe"',
    "THREAT_DETECTED->INTERCEPT_COUNTDOWN": "5-second timer starts",
    "THREAT_DETECTED->EMERGENCY_PROTOCOL": "High-confidence local distress match; immediate SOS",
    "INTERCEPT_COUNTDOWN->MONITORING": 'User clicks "I\'m Safe"',
    "INTERCEPT_COUNTDOWN->EMERGENCY_PROTOCOL": "5 seconds elapsed without cancellation",
    "EMERGENCY_PROTOCOL->RECORDING": "Dispatch attempted; evidence capture starts",
    "RECORDING->RESOLVED": "User confirms safety or recording timeout",
    "RESOLVED->MONITORING": "Agent resets after resolution",
}


def is_valid_transition(from_state: str, to_state: str) -> bool:
    """Return whether the transition exists in the declared state graph."""
    return to_state in EDGES.get(from_state, [])


def get_edge_condition(from_state: str, to_state: str) -> str:
    """Return the human-readable condition for a state transition."""
    return EDGE_CONDITIONS.get(f"{from_state}->{to_state}", "Unknown transition")


def haversine_distance(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Distance between two GPS coordinates in kilometres."""
    radius_km = 6371.0
    lat1_rad, lat2_rad = math.radians(lat1), math.radians(lat2)
    d_lat = math.radians(lat2 - lat1)
    d_lng = math.radians(lng2 - lng1)
    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(d_lng / 2) ** 2
    )
    # Clamp against small floating-point errors.
    a = min(1.0, max(0.0, a))
    return radius_km * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _load_safety_data() -> dict[str, Any]:
    try:
        with SAFETY_DATA_PATH.open("r", encoding="utf-8") as file:
            payload = json.load(file)
        return payload if isinstance(payload, dict) else {}
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Could not read safety data at %s: %s", SAFETY_DATA_PATH, exc)
        return {}


def get_nearest_police(lat: float, lng: float) -> dict[str, Any] | None:
    """Find the nearest station using the configured provider or safety_data.json."""
    if _nearest_police_provider is not None:
        try:
            station = _nearest_police_provider(float(lat), float(lng))
            if station is not None:
                return station
        except Exception:
            logger.exception("Configured police-station provider failed; trying JSON fallback")
    stations = _load_safety_data().get("police_stations", [])
    nearest: dict[str, Any] | None = None
    min_distance = float("inf")

    for station in stations:
        try:
            station_lat = float(station["lat"])
            station_lng = float(station["lng"])
        except (KeyError, TypeError, ValueError):
            continue

        distance = haversine_distance(float(lat), float(lng), station_lat, station_lng)
        if distance < min_distance:
            min_distance = distance
            nearest = {
                "name": station.get("name"),
                "contact": station.get("contact"),
                "email": station.get("email"),
                "lat": station_lat,
                "lng": station_lng,
                "description": station.get("description"),
                "distance": round(distance, 3),
                "distanceText": (
                    f"{distance:.1f} km" if distance > 1
                    else f"{distance * 1000:.0f} m"
                ),
            }
    return nearest


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "trigger_emergency_alert",
            "description": (
                "Triggers an emergency alert when a genuine threat to the user's "
                "safety is detected. This returns a threat action to the caller."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "severity": {
                        "type": "string",
                        "enum": ["low", "medium", "high", "critical"],
                        "description": "Threat severity level.",
                    },
                    "summary": {
                        "type": "string",
                        "description": "Brief threat summary, maximum 200 characters.",
                    },
                    "detected_language": {
                        "type": "string",
                        "enum": ["hi-IN", "mr-IN", "en-IN", "unknown"],
                        "description": "Detected supported language.",
                    },
                },
                "required": ["severity", "summary", "detected_language"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_nearest_police",
            "description": "Looks up the nearest police station from GPS coordinates.",
            "parameters": {
                "type": "object",
                "properties": {
                    "lat": {"type": "number", "description": "Latitude"},
                    "lng": {"type": "number", "description": "Longitude"},
                },
                "required": ["lat", "lng"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_threat_email",
            "description": "Requests a threat-transcription email for a confirmed threat.",
            "parameters": {
                "type": "object",
                "properties": {
                    "transcript": {"type": "string"},
                    "language": {"type": "string"},
                    "severity": {"type": "string"},
                    "summary": {"type": "string"},
                },
                "required": ["transcript", "language", "severity", "summary"],
            },
        },
    },
]

SYSTEM_PROMPT = r"""
You are an AI safety agent protecting women during navigation, part of the
Sakhi-Sahayak safety system. Analyze transcripts for genuine threats.

STRICTLY support only Hindi (hi-IN), Marathi (mr-IN), and Indian English (en-IN).
Do not trigger for other languages. Consider context and ignore casual mentions
of distress words in harmless contexts, such as movies, news, or jokes.

Hindi examples include: bachao, madad, chhodo, mat karo, police bulao,
mujhe bachao, jane do, ruko, dar lag raha, peecha kar raha, maar raha,
pakad liya, dur raho, mat chuo.
Marathi examples include: vachva, madad kara, police bolva, mala sodha,
thamba, mala vachva, paathlag karto, bhiti vatay, mala jaau dya, dur raha.
English examples include: help, save me, stop, please no, leave me, don't touch,
someone help, let me go, get away, call police, I am scared, following me,
kidnap, attack, assault, rape, molest, harass, stalking, don't hurt me.

If a direct plea for help or an immediate threat is present, call
trigger_emergency_alert with an appropriate severity and language.
Severity: critical for immediate physical danger or a direct plea for help;
high for harassment/stalking/aggressive confrontation or an explicit SOS command;
medium for following or an uncomfortable situation; low for uncertain concerns.
Err on the side of caution but do not treat an obvious harmless context as a threat.

If there is no threat, return JSON with action="no_action", a short summary,
and detected_language. Never claim an email or SMS was sent unless the caller
confirms the relevant dispatch result.
"""


def _write_transcript_log(
    transcript: str, location: dict[str, Any] | None, user_info: dict[str, Any] | None
) -> None:
    try:
        EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
        log_path = EVIDENCE_DIR / "orchestrator_logs.txt"
        user_info = user_info or {}
        location = location or {}
        line = (
            f"[{datetime.now(timezone.utc).isoformat()}] "
            f"User: {user_info.get('name', 'Unknown')} | "
            f"LatLng: {location.get('lat', 0)},{location.get('lng', 0)} | "
            f'Transcript: "{transcript}"\n'
        )
        with log_path.open("a", encoding="utf-8") as file:
            file.write(line)
    except OSError:
        logger.exception("Failed to write transcript log")


async def _call_email_sender(payload: dict[str, Any]) -> bool:
    if _transcription_email_sender is None:
        logger.warning(
            "No transcription email callback registered; email was not sent."
        )
        return False
    try:
        result = _transcription_email_sender(payload)
        if inspect.isawaitable(result):
            result = await result
        return bool(result.get("success", True)) if isinstance(result, dict) else bool(result)
    except Exception:
        logger.exception("Transcription email callback failed")
        return False


def _parse_tool_arguments(raw_arguments: str) -> dict[str, Any]:
    try:
        value = json.loads(raw_arguments or "{}")
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        logger.warning("OpenRouter returned invalid tool arguments")
        return {}


async def _process_tool_calls(
    tool_calls: list[dict[str, Any]],
    location: dict[str, Any] | None,
    user_info: dict[str, Any] | None,
    transcript: str,
) -> dict[str, Any]:
    location = location or {}
    user_info = user_info or {}
    final_action: dict[str, Any] = {
        "action": "no_action",
        "summary": "No threat detected.",
        "detectedLanguage": "unknown",
    }

    for call in tool_calls:
        function = call.get("function") or {}
        function_name = function.get("name")
        args = _parse_tool_arguments(function.get("arguments", "{}"))

        if function_name == "trigger_emergency_alert":
            severity = args.get("severity", "high")
            if severity not in {"low", "medium", "high", "critical"}:
                severity = "high"
            language = args.get("detected_language", "unknown")
            if language not in {"hi-IN", "mr-IN", "en-IN", "unknown"}:
                language = "unknown"
            summary = str(args.get("summary", "Potential safety threat detected."))[:200]

            station = None
            try:
                lat, lng = location.get("lat"), location.get("lng")
                if lat is not None and lng is not None:
                    station = await asyncio.to_thread(get_nearest_police, float(lat), float(lng))
            except (TypeError, ValueError):
                logger.warning("Invalid coordinates; skipping nearest-station lookup")

            # Do not dispatch email from the analysis layer. The voice agent owns
            # the countdown and emergency protocol, and the emergency dispatcher
            # sends one coordinated email/SMS/location alert after escalation.
            final_action = {
                "action": "trigger_emergency_alert",
                "severity": severity,
                "summary": summary,
                "detectedLanguage": language,
                "nearestStation": station,
                "userInfo": user_info,
            }

        elif function_name == "get_nearest_police":
            station = await asyncio.to_thread(
                get_nearest_police, float(args["lat"]), float(args["lng"])
            )
            # This tool is informational; it does not itself trigger an SOS.
            if final_action.get("action") == "no_action":
                final_action = {
                    "action": "no_action",
                    "summary": "Nearest police station lookup completed.",
                    "detectedLanguage": "unknown",
                    "nearestStation": station,
                }

        elif function_name == "send_threat_email":
            # A threat-email request is treated as a confirmed threat action. The
            # voice agent then runs the countdown and the emergency dispatcher
            # owns the actual notification, avoiding a pre-countdown duplicate.
            language = str(args.get("language") or "unknown")
            if language not in {"hi-IN", "mr-IN", "en-IN", "unknown"}:
                language = "unknown"
            severity = str(args.get("severity") or "high").lower()
            if severity not in {"low", "medium", "high", "critical"}:
                severity = "high"
            summary = str(args.get("summary") or "Threat detected.")[:200]
            station = None
            try:
                lat, lng = location.get("lat"), location.get("lng")
                if lat is not None and lng is not None:
                    station = await asyncio.to_thread(get_nearest_police, float(lat), float(lng))
            except (TypeError, ValueError):
                logger.warning("Invalid coordinates; skipping nearest-station lookup")
            final_action = {
                "action": "trigger_emergency_alert",
                "severity": severity,
                "summary": summary,
                "detectedLanguage": language,
                "nearestStation": station,
                "userInfo": user_info,
            }

    # Await optional email tasks and expose the real outcome instead of claiming
    # dispatch succeeded before the provider callback completes.
    task = final_action.pop("emailTask", None)
    if task is not None:
        final_action["emailDispatched"] = await task

    return final_action


async def analyze_transcript(
    transcript: str,
    location: dict[str, Any] | None = None,
    user_info: dict[str, Any] | None = None,
    *,
    api_key: str | None = None,
    timeout: float = 25.0,
) -> dict[str, Any]:
    """
    Analyze one transcript using OpenRouter's chat-completions API.

    Returns an action dictionary. If an API key is missing or the request fails,
    this raises RuntimeError so the caller can decide how to handle the failure.
    """
    transcript = (transcript or "").strip()
    if not transcript:
        return {
            "action": "no_action",
            "summary": "Empty transcript.",
            "detectedLanguage": "unknown",
        }

    key = api_key or OPENROUTER_API_KEY
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY is not configured")

    location = location or {}
    user_info = user_info or {}
    await asyncio.to_thread(_write_transcript_log, transcript, location, user_info)

    user_message = f"""Analyze this voice transcript captured near the user's phone.

Transcript: {transcript}
User location: {location.get('lat', 'Unknown')}, {location.get('lng', 'Unknown')}
User: {user_info.get('name', 'Unknown')} (Phone: {user_info.get('phone', 'N/A')})

Only Hindi (hi-IN), Marathi (mr-IN), and Indian English (en-IN) are supported.
If a genuine threat exists, call trigger_emergency_alert with severity and language.
If there is no threat, respond with JSON:
{{"action":"no_action","summary":"reason","detected_language":"xx-IN"}}
"""

    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        "tools": TOOLS,
        "tool_choice": "auto",
        "temperature": 0.1,
        "max_tokens": 500,
    }
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://sakhi-sahayak.app",
        "X-Title": "Sakhi Sahayak LangGraph Orchestrator",
    }

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(OPENROUTER_URL, headers=headers, json=payload)
        if response.is_error:
            detail = response.text[:1000]
            raise RuntimeError(f"OpenRouter API error {response.status_code}: {detail}")
        data = response.json()
    except (httpx.HTTPError, json.JSONDecodeError) as exc:
        logger.exception("OpenRouter request failed")
        raise RuntimeError(f"OpenRouter request failed: {exc}") from exc

    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError("OpenRouter returned no choices")

    message = choices[0].get("message") or {}
    tool_calls = message.get("tool_calls") or []
    if tool_calls:
        return await _process_tool_calls(tool_calls, location, user_info, transcript)

    content = message.get("content") or ""
    try:
        parsed = json.loads(content)
        return {
            "action": parsed.get("action", "no_action"),
            "summary": parsed.get("summary", "No threat detected."),
            "detectedLanguage": parsed.get("detected_language", "unknown"),
        }
    except (json.JSONDecodeError, AttributeError):
        return {
            "action": "no_action",
            "summary": content[:200] or "No threat detected.",
            "detectedLanguage": "unknown",
        }


# JavaScript-style aliases for easier migration.
getNearestPolice = get_nearest_police
isValidTransition = is_valid_transition
getEdgeCondition = get_edge_condition
analyzeTranscript = analyze_transcript
setTranscriptionEmailSender = set_transcription_email_sender
