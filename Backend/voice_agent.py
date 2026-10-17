"""
Sakhi-Sahayak voice safety agent (Python conversion of voiceAgent.js).

The module is designed for python-socketio.AsyncServer. It keeps one in-memory
state per connected socket, applies the supplied Hindi/Marathi/English local
distress-keyword gate, dispatches emergency notifications, and manages the
recording/resolution lifecycle.

Privacy note: transcript text is not written to disk by this module. Evidence
audio is uploaded separately by the client and handled by evidence_recorder.py.
"""
from __future__ import annotations

import asyncio
import logging
import secrets
import time
from datetime import datetime, timezone
from typing import Any

from orchestrator import (
    STATES,
    get_edge_condition,
    get_nearest_police,
    is_valid_transition,
    analyze_transcript,
)
from evidence_recorder import create_metadata
from emergency_dispatcher_brevo import dispatch_full_emergency, dispatch_live_location

logger = logging.getLogger("sakhi_sahayak.voice_agent")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO)

# The keyword lists are intentionally based on the source JS.
DISTRESS_KEYWORDS: dict[str, list[str]] = {
    "english": [
        "help", "save me", "stop", "please no", "leave me", "don't touch",
        "someone help", "let me go", "get away", "call police", "i am scared",
        "please help", "he is following", "following me", "kidnap", "attack",
        "assault", "rape", "molest", "harass", "threatening", "stalking",
        "i need help", "someone is following me", "don't hurt me", "call 911",
        "help me", "stay away", "leave me alone", "stop it", "no please",
        "somebody help", "save me please", "get off me", "police",
    ],
    "hindi_roman": [
        "bachao", "madad", "chhodo", "mat karo", "koi hai", "police bulao",
        "mujhe bachao", "chhoddo", "jane do", "ruko", "koi madad karo",
        "dar lag raha", "peecha kar raha", "maar raha", "pakad liya",
        "help karo", "bachao koi", "mujhe chhoddo", "hato", "hatiye",
        "koi bachao", "mujhe chhodo", "police ko call karo", "mujhe maar raha hai",
        "chhod do", "kya kar rahe ho", "dur raho", "mat chuo", "mujhe mat chuo",
        "madad karo", "koi to madad karo", "mujhe jane do", "peeche pad gaya",
        "bachaao", "baचao", "madat", "chodo", "chod do", "mujhe chodo",
    ],
    "hindi_devanagari": [
        "बचाओ", "मदद", "छोड़ो", "मत करो", "कोई है", "पुलिस बुलाओ",
        "मुझे बचाओ", "छोड़ दो", "जाने दो", "रुको", "कोई मदद करो",
        "डर लग रहा", "पीछा कर रहा", "मार रहा", "पकड़ लिया", "हेल्प करो",
        "बचाओ कोई", "मुझे छोड़ दो", "हटो", "हटिये", "कोई बचाओ", "मुझे छोड़ो",
        "पुलिस को कॉल करो", "मुझे मार रहा है", "क्या कर रहे हो", "दूर रहो",
        "मत छुओ", "मुझे मत छुओ", "मदद करो", "कोई तो मदद करो",
        "मुझे जाने दो", "पीछे पड़ गया", "हेल्प", "मदद चाहिए", "बचाओ मुझे",
        "पुलिस", "कोई तो आओ", "मुझे बचा लो", "मार डालेगा", "मार रहा है",
        "पकड़ लिया है", "छोड़ दे", "हट जा", "हट जाओ", "दूर हट", "दूर हटो",
        "कोई सुनो", "कोई आओ", "बचा लो", "सहायता", "मदद कीजिए",
    ],
    "marathi_roman": [
        "vachva", "madad kara", "sodha", "naka karu", "polees bolva",
        "koni ahe ka", "sahayya kara", "mala sodha", "thamba", "mala vachva",
        "paathlag karto", "bhiti vatay", "mala dhara", "madat kara",
        "polees bolava", "madad havi", "mala jaau dya", "dur raha",
        "koni tari ya", "mala sparsh karu naka", "mala madat kara",
        "koni madatila ya ka", "sagla theek nahi",
    ],
    "marathi_devanagari": [
        "वाचवा", "मदत करा", "सोडा", "नका करू", "पोलीस बोलवा", "कोणी आहे का",
        "सहाय्य करा", "मला सोडा", "थांबा", "मला वाचवा", "पाठलाग करतो",
        "भीती वाटतय", "मला धरा", "मदत करा", "मदत हवी", "मला जाऊ द्या",
        "दूर राहा", "कोणी तरी या", "मला स्पर्श करू नका", "मला मदत करा",
        "कोणी मदतीला या का", "सगळं ठीक नाही", "पोलीस", "मदत", "वाचवा मला",
        "सोड", "सोडा मला", "कोणी या", "मला मारतोय", "मला पकडलं", "सोड दे",
    ],
}
ALL_KEYWORDS_LIST = list(dict.fromkeys(
    keyword.lower().strip()
    for words in DISTRESS_KEYWORDS.values()
    for keyword in words
))
SUSPICIOUS_SOUND_PATTERNS = [
    "scream", "screaming", "shriek", "shrieking", "yelling", "shouting",
    "crying", "sobbing", "wailing", "whimpering", "weeping",
    "glass breaking", "breaking glass", "bang", "crash", "slap", "hitting",
    "gunshot", "gun shot", "explosion", "thud", "smash",
    "ahhh", "aaah", "aaaa", "noooo", "nooo",
    "chillana", "rona", "cheekh", "cheekh rahi", "chillao",
    "chikh", "chikhi", "kiski awaaz",
]

agent_states: dict[str, dict[str, Any]] = {}
_agent_tasks: dict[str, set[asyncio.Task[Any]]] = {}


def normalize_text(text: str) -> str:
    import re
    normalized = (text or "").lower()
    normalized = re.sub(r"""[!?.,'"\-_।॥()\[\]{}]""", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def find_distress_keywords(transcript: str) -> list[str]:
    """Find phrases on token boundaries, avoiding matches inside unrelated words."""
    normalized = normalize_text(transcript)
    padded = f" {normalized} "
    # Common standalone words can occur in harmless contexts (e.g. "bus stop").
    # They are only high-confidence when the complete transcript is the word or
    # when the surrounding phrase explicitly signals distress.
    ambiguous_single_words = {"stop", "police", "help", "मदद", "पुलिस", "मदत"}
    exact_or_contextual = {
        "stop", "please stop", "stop it", "no stop", "help", "help me",
        "please help", "someone help", "call police", "police help",
        "मदद", "मदद करो", "मदद चाहिए", "पुलिस", "पुलिस बुलाओ", "मदत करा",
    }
    matched: list[str] = []
    for keyword in ALL_KEYWORDS_LIST:
        normalized_keyword = normalize_text(keyword)
        if len(normalized_keyword) < 2 or f" {normalized_keyword} " not in padded:
            continue
        if normalized_keyword in ambiguous_single_words:
            if normalized not in exact_or_contextual and not any(
                phrase in padded for phrase in (
                    " call police ", " police help ", " help me ", " please help ",
                    " someone help ", " i need help ", " mujhe bachao ",
                    " police bulao ", " मदद चाहिए ", " पुलिस बुलाओ ",
                )
            ):
                continue
        matched.append(keyword)
    return list(dict.fromkeys(matched))



def detect_keyword_language(matched_keywords: list[str]) -> str:
    scores = {"en-IN": 0, "hi-IN": 0, "mr-IN": 0}
    for keyword in matched_keywords:
        lower = keyword.lower()
        if lower in DISTRESS_KEYWORDS["english"]:
            scores["en-IN"] += 1
        if lower in DISTRESS_KEYWORDS["hindi_roman"] or lower in DISTRESS_KEYWORDS["hindi_devanagari"]:
            scores["hi-IN"] += 1
        if lower in DISTRESS_KEYWORDS["marathi_roman"] or lower in DISTRESS_KEYWORDS["marathi_devanagari"]:
            scores["mr-IN"] += 1
        if any("\u0900" <= char <= "\u097f" for char in keyword):
            if any(item in keyword for item in DISTRESS_KEYWORDS["hindi_devanagari"]):
                scores["hi-IN"] += 1
            if any(item in keyword for item in DISTRESS_KEYWORDS["marathi_devanagari"]):
                scores["mr-IN"] += 1
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "unknown"


def _now_ms() -> int:
    return int(time.time() * 1000)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _create_agent_state(socket_id: str, user_data: dict[str, Any] | None = None) -> dict[str, Any]:
    user_data = user_data or {}
    now = _now_ms()
    return {
        "status": STATES["IDLE"],
        "userId": socket_id,
        "userName": user_data.get("name"),
        "userPhone": user_data.get("phone"),
        "emergencyEmail": user_data.get("emergencyEmail") or user_data.get("emergency_email"),
        "emergencyPhone": user_data.get("emergencyPhone") or user_data.get("emergency_phone"),
        "emergencyName": user_data.get("emergencyName") or user_data.get("emergency_name"),
        "currentLocation": None,
        "threatTranscript": None,
        "threatSeverity": None,
        "detectedLanguage": None,
        "interceptTimerId": None,
        "recordingStartTime": None,
        "recordingTimerId": None,
        "trackingId": None,
        "nearestPolice": None,
        "createdAt": now,
        "stateHistory": [{"state": STATES["IDLE"], "timestamp": now, "reason": "Agent initialized"}],
    }


def get_state(socket_id: str) -> dict[str, Any]:
    if socket_id not in agent_states:
        agent_states[socket_id] = _create_agent_state(socket_id)
    return agent_states[socket_id]


def set_state(socket_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    state = get_state(socket_id)
    state.update(updates)
    return state


async def _emit_room(io: Any, socket_id: str, event: str, payload: dict[str, Any]) -> None:
    await io.emit(event, payload, to=socket_id)


async def _emit_all(io: Any, event: str, payload: dict[str, Any]) -> None:
    await io.emit(event, payload)


def _log_transition(socket_id: str, from_state: str, to_state: str, reason: str) -> None:
    valid = is_valid_transition(from_state, to_state)
    edge_label = get_edge_condition(from_state, to_state)
    logger.info(
        "[VoiceAgent] state transition socket=%s %s -> %s | edge=%s | reason=%s | valid=%s",
        socket_id, from_state, to_state, edge_label, reason, valid,
    )
    state = get_state(socket_id)
    state.setdefault("stateHistory", []).append({
        "state": to_state, "timestamp": _now_ms(), "reason": reason, "edge": edge_label,
    })


def _spawn(socket_id: str, coro: Any) -> asyncio.Task[Any]:
    task = asyncio.create_task(coro)
    _agent_tasks.setdefault(socket_id, set()).add(task)
    task.add_done_callback(lambda done: _agent_tasks.get(socket_id, set()).discard(done))
    return task


async def start_monitoring(socket_id: str, io: Any, user_data: dict[str, Any] | None = None) -> None:
    user_data = user_data or {}
    state = get_state(socket_id)
    old_status = state["status"]
    # Starting a fresh monitoring session must not carry a previous incident ID
    # or stale transcript into the next incident.
    set_state(socket_id, {
        "status": STATES["MONITORING"],
        "userName": user_data.get("name") or state.get("userName"),
        "userPhone": user_data.get("phone") or state.get("userPhone"),
        "emergencyEmail": user_data.get("emergencyEmail") or user_data.get("emergency_email") or state.get("emergencyEmail"),
        "emergencyPhone": user_data.get("emergencyPhone") or user_data.get("emergency_phone") or state.get("emergencyPhone"),
        "emergencyName": user_data.get("emergencyName") or user_data.get("emergency_name") or state.get("emergencyName"),
        "currentLocation": user_data.get("location") or state.get("currentLocation"),
        "threatTranscript": None,
        "threatSeverity": None,
        "detectedLanguage": None,
        "interceptTimerId": None,
        "_countdownTask": None,
        "recordingStartTime": None,
        "recordingTimerId": None,
        "trackingId": None,
        "nearestPolice": None,
    })
    _log_transition(socket_id, old_status, STATES["MONITORING"], "Route started / monitoring activated")
    await _emit_room(io, socket_id, "agent-state-update", {
        "status": STATES["MONITORING"],
        "message": "Voice monitoring active. Listening for distress signals in Hindi, Marathi & English.",
        "langGraphState": STATES["MONITORING"],
        "supportedLanguages": ["hi-IN", "mr-IN", "en-IN"],
    })


async def stop_monitoring(socket_id: str, io: Any) -> None:
    state = get_state(socket_id)
    _cancel_task(state.get("interceptTimerId"))
    _cancel_task(state.get("_countdownTask"))
    _cancel_task(state.get("recordingTimerId"))
    old_status = state["status"]
    set_state(socket_id, {
        "status": STATES["IDLE"], "threatTranscript": None, "threatSeverity": None,
        "detectedLanguage": None, "interceptTimerId": None, "_countdownTask": None,
        "recordingStartTime": None, "recordingTimerId": None, "trackingId": None,
        "nearestPolice": None,
    })
    _log_transition(socket_id, old_status, STATES["IDLE"], "Route ended / monitoring stopped")
    await _emit_room(io, socket_id, "agent-state-update", {
        "status": STATES["IDLE"], "message": "Voice monitoring stopped.", "langGraphState": STATES["IDLE"],
    })


def _cancel_task(task: Any) -> None:
    if isinstance(task, asyncio.Task) and not task.done():
        task.cancel()


async def process_transcript(socket_id: str, transcript: str, location: dict[str, Any] | None, io: Any) -> None:
    """Process completed STT text through the local safety gate and LLM orchestrator.

    High-confidence local distress phrases escalate immediately so an external LLM
    outage cannot delay a clear SOS. If no local phrase matches, the transcript is
    sent to the orchestrator LLM, which can still identify contextual threats.
    """
    state = get_state(socket_id)
    if state["status"] != STATES["MONITORING"]:
        logger.info("Ignoring transcript for %s; state=%s", socket_id, state["status"])
        return

    transcript = str(transcript or "").strip()
    if not transcript:
        return

    current_location = location or state.get("currentLocation")
    set_state(socket_id, {"currentLocation": current_location})
    logger.info('[VoiceAgent] transcript received for socket=%s (%d chars)', socket_id, len(transcript))

    matched_keywords = find_distress_keywords(transcript)
    normalized = normalize_text(transcript)
    matched_sounds = [pattern for pattern in SUSPICIOUS_SOUND_PATTERNS if pattern in normalized]

    # A direct distress phrase is the fastest/high-confidence path: don't wait for LLM.
    if matched_keywords or matched_sounds:
        keyword_language = detect_keyword_language(matched_keywords) if matched_keywords else "unknown"
        nearest_station = None
        if isinstance(current_location, dict):
            lat = current_location.get("lat")
            lng = current_location.get("lng", current_location.get("lon"))
            if lat is not None and lng is not None:
                try:
                    nearest_station = await asyncio.to_thread(get_nearest_police, float(lat), float(lng))
                except (TypeError, ValueError):
                    logger.exception("Nearest-police lookup failed")

        tracking_id = f"TRK-{secrets.token_hex(4).upper()}"
        reason = (
            f"Suspicious sound terms detected: {', '.join(matched_sounds)}."
            if matched_sounds and not matched_keywords
            else f"Local distress keywords detected: {', '.join(matched_keywords[:8])}."
        )
        old_status = state["status"]
        set_state(socket_id, {
            "status": STATES["THREAT_DETECTED"],
            "threatTranscript": transcript,
            "threatSeverity": "critical",
            "detectedLanguage": keyword_language,
            "trackingId": tracking_id,
            "nearestPolice": nearest_station,
        })
        _log_transition(socket_id, old_status, STATES["THREAT_DETECTED"], reason)
        await _emit_room(io, socket_id, "agent-state-update", {
            "status": STATES["THREAT_DETECTED"], "trackingId": tracking_id,
            "message": "Distress phrase detected. Activating emergency protocol immediately.",
            "langGraphState": STATES["THREAT_DETECTED"], "langGraphEdge": "local_distress_match",
            "nearestStation": nearest_station,
        })
        await _emit_room(io, socket_id, "voice-analysis", {
            "transcript": transcript, "distress": True,
            "keywords": list(dict.fromkeys(matched_keywords + matched_sounds)),
            "action": "trigger_emergency_alert", "severity": "critical",
            "summary": reason, "detectedLanguage": keyword_language,
            "langGraphState": STATES["THREAT_DETECTED"], "nearestStation": nearest_station,
        })
        await execute_emergency_protocol(socket_id, io)
        return

    # No local keyword match: let the orchestrator assess context, idioms and implied threats.
    user_info = {
        "name": state.get("userName") or "Unknown",
        "phone": state.get("userPhone") or "N/A",
        "trackingId": state.get("trackingId"),
    }
    try:
        llm_result = await analyze_transcript(
            transcript,
            current_location if isinstance(current_location, dict) else None,
            user_info,
        )
    except Exception as exc:
        logger.warning("Orchestrator analysis unavailable: %s", exc)
        await _emit_room(io, socket_id, "voice-analysis", {
            "transcript": transcript,
            "distress": False,
            "keywords": [],
            "action": "analysis_unavailable",
            "summary": "No local distress phrase matched, and LLM analysis is unavailable. Please use the SOS button if you feel unsafe.",
            "error": str(exc),
            "langGraphState": STATES["MONITORING"],
        })
        return

    await handle_orchestrator_response(
        socket_id, llm_result, transcript, io,
        str(llm_result.get("detectedLanguage") or "unknown"),
    )


async def handle_orchestrator_response(
    socket_id: str, llm_result: dict[str, Any], transcript: str, io: Any, keyword_language: str = "unknown"
) -> None:
    state = get_state(socket_id)
    if llm_result.get("action") == "trigger_emergency_alert":
        tracking_id = f"TRK-{secrets.token_hex(4).upper()}"
        detected_lang = llm_result.get("detectedLanguage") or keyword_language or "unknown"
        _log_transition(socket_id, state["status"], STATES["THREAT_DETECTED"], f"LLM confirmed threat: {llm_result.get('summary', '')}")
        set_state(socket_id, {
            "status": STATES["THREAT_DETECTED"], "threatTranscript": transcript,
            "threatSeverity": llm_result.get("severity") or "high",
            "detectedLanguage": detected_lang, "trackingId": tracking_id,
            "nearestPolice": llm_result.get("nearestStation"),
        })
        await _emit_room(io, socket_id, "agent-state-update", {
            "status": STATES["THREAT_DETECTED"], "transcript": transcript,
            "severity": llm_result.get("severity") or "high", "summary": llm_result.get("summary"),
            "trackingId": tracking_id, "detectedLanguage": detected_lang,
            "langGraphState": STATES["THREAT_DETECTED"], "langGraphEdge": "Orchestrator LLM confirms distress",
        })
        await _emit_room(io, socket_id, "voice-analysis", {
            "transcript": transcript, "distress": True, "keywords": [],
            "action": "threat_confirmed", "severity": llm_result.get("severity") or "high",
            "summary": llm_result.get("summary"), "detectedLanguage": detected_lang,
            "langGraphState": STATES["THREAT_DETECTED"],
        })
        # Let the state-machine countdown give the user a brief cancellation window.
        # The local keyword gate above is reserved for the immediate fail-safe path.
        await start_intercept_countdown(socket_id, io)
    else:
        await _emit_room(io, socket_id, "voice-analysis", {
            "transcript": transcript, "distress": False, "keywords": [],
            "action": "no_action", "summary": llm_result.get("summary") or "No threat detected.",
            "detectedLanguage": llm_result.get("detectedLanguage") or keyword_language or "unknown",
            "langGraphState": STATES["MONITORING"],
        })


async def start_intercept_countdown(socket_id: str, io: Any) -> None:
    state = get_state(socket_id)
    _log_transition(socket_id, state["status"], STATES["INTERCEPT_COUNTDOWN"], "5-second intercept timer started")
    set_state(socket_id, {"status": STATES["INTERCEPT_COUNTDOWN"]})
    await _emit_room(io, socket_id, "agent-state-update", {
        "status": STATES["INTERCEPT_COUNTDOWN"], "countdown": 5,
        "message": 'THREAT DETECTED! Click "I\'m Safe" within 5 seconds to cancel.',
        "langGraphState": STATES["INTERCEPT_COUNTDOWN"], "langGraphEdge": "5s timer starts",
    })

    async def countdown() -> None:
        try:
            for remaining in range(4, 0, -1):
                await asyncio.sleep(1)
                if get_state(socket_id)["status"] != STATES["INTERCEPT_COUNTDOWN"]:
                    return
                await _emit_room(io, socket_id, "intercept-countdown-tick", {"remaining": remaining})
            if get_state(socket_id)["status"] == STATES["INTERCEPT_COUNTDOWN"]:
                await execute_emergency_protocol(socket_id, io)
        except asyncio.CancelledError:
            return

    task = _spawn(socket_id, countdown())
    set_state(socket_id, {"interceptTimerId": task, "_countdownTask": task})


async def cancel_intercept(socket_id: str, io: Any) -> None:
    state = get_state(socket_id)
    if state["status"] not in (STATES["INTERCEPT_COUNTDOWN"], STATES["THREAT_DETECTED"]):
        logger.info("Cannot cancel intercept; state=%s", state["status"])
        return
    _cancel_task(state.get("interceptTimerId"))
    _cancel_task(state.get("_countdownTask"))
    _log_transition(socket_id, state["status"], STATES["MONITORING"], 'User clicked "I\'m Safe" — intercept cancelled')
    set_state(socket_id, {
        "status": STATES["MONITORING"], "threatTranscript": None, "threatSeverity": None,
        "detectedLanguage": None, "interceptTimerId": None, "trackingId": None, "nearestPolice": None,
    })
    await _emit_room(io, socket_id, "agent-state-update", {
        "status": STATES["MONITORING"], "message": "Intercept cancelled. Returning to monitoring mode.",
        "langGraphState": STATES["MONITORING"], "langGraphEdge": 'User clicks "I\'m Safe"',
    })


async def execute_emergency_protocol(socket_id: str, io: Any) -> None:
    state = get_state(socket_id)
    if state["status"] in {STATES["EMERGENCY_PROTOCOL"], STATES["RECORDING"], STATES["RESOLVED"]}:
        return  # Avoid duplicate dispatch while an incident is already active or resolved.
    old_status = state["status"]
    _log_transition(socket_id, old_status, STATES["EMERGENCY_PROTOCOL"], "Threat confirmed — escalating")
    set_state(socket_id, {"status": STATES["EMERGENCY_PROTOCOL"]})
    logger.warning(
        "EMERGENCY_PROTOCOL: user=%s phone=%s location=%s transcript=%s tracking=%s",
        state.get("userName") or "Unknown", state.get("userPhone") or "N/A",
        state.get("currentLocation"), state.get("threatTranscript"), state.get("trackingId"),
    )
    payload = {
        "trackingId": state.get("trackingId"),
        "userName": state.get("userName"),
        "userPhone": state.get("userPhone"),
        "emergencyEmail": state.get("emergencyEmail"),
        "emergencyPhone": state.get("emergencyPhone"),
        "emergencyName": state.get("emergencyName"),
        "location": state.get("currentLocation"),
        "transcript": state.get("threatTranscript"),
        "severity": state.get("threatSeverity"),
        "detectedLanguage": state.get("detectedLanguage") or "unknown",
        "nearestStation": state.get("nearestPolice"),
        "timestamp": _now_iso(),
        "langGraphState": STATES["EMERGENCY_PROTOCOL"],
    }
    await _emit_room(io, socket_id, "agent-state-update", {
        "status": STATES["EMERGENCY_PROTOCOL"], "trackingId": state.get("trackingId"),
        "message": "Emergency protocol active. Dispatching alerts and starting evidence recording.",
        "langGraphState": STATES["EMERGENCY_PROTOCOL"], "langGraphEdge": "Emergency escalation",
        "detectedLanguage": state.get("detectedLanguage"),
    })
    location = state.get("currentLocation")
    lat = location.get("lat") if isinstance(location, dict) else None
    lng = location.get("lng", location.get("lon")) if isinstance(location, dict) else None
    maps = f"https://maps.google.com/maps?q={lat},{lng}" if lat is not None and lng is not None else None
    await _emit_all(io, "emergency-alert", {
        **payload, "googleMapsLink": maps, "nearestPolice": state.get("nearestPolice"),
    })

    dispatch_results: dict[str, Any] = {}
    try:
        # This is the single owner of emergency email/SMS/location dispatch. Avoid
        # sending a second copy of the same emergency email from send_email.py.
        dispatch_results = await dispatch_full_emergency(io, payload)
    except Exception:
        logger.exception("Multi-channel emergency dispatch failed")
    email_result = dispatch_results.get("email") or {}
    sms_result = dispatch_results.get("sms") or {}
    location_result = dispatch_results.get("liveLocation") or {}
    await _emit_room(io, socket_id, "dispatch-results", {
        "trackingId": state.get("trackingId"),
        "emailSent": bool(email_result.get("success")),
        "smsSent": bool(sms_result.get("success")),
        "locationStreaming": bool(location_result.get("success")),
        "emailMessageId": email_result.get("messageId"),
        "detectedLanguage": state.get("detectedLanguage"),
        "dispatchResults": dispatch_results,
    })

    # Keep the state machine coherent: EMERGENCY_PROTOCOL transitions directly
    # to RECORDING, then RECORDING -> RESOLVED -> MONITORING.
    set_state(socket_id, {"threatLevel": 0, "interceptTimerId": None})
    await start_recording(socket_id, io)


async def start_recording(socket_id: str, io: Any) -> None:
    state = get_state(socket_id)
    _log_transition(socket_id, state["status"], STATES["RECORDING"], "Evidence capture started")
    recording_start = _now_ms()
    set_state(socket_id, {"status": STATES["RECORDING"], "recordingStartTime": recording_start})
    await _emit_room(io, socket_id, "agent-state-update", {
        "status": STATES["RECORDING"], "recordingStartTime": recording_start,
        "message": "Recording evidence. Maximum 8 minutes.",
        "langGraphState": STATES["RECORDING"], "langGraphEdge": "Auto-start evidence capture",
    })
    await _emit_room(io, socket_id, "start-evidence-recording", {
        "trackingId": state.get("trackingId"), "maxDuration": 8 * 60 * 1000,
    })

    async def recording_timeout() -> None:
        try:
            await asyncio.sleep(8 * 60)
            if get_state(socket_id)["status"] == STATES["RECORDING"]:
                await resolve_emergency(socket_id, io, "Recording time limit reached (8 min)")
        except asyncio.CancelledError:
            return

    task = _spawn(socket_id, recording_timeout())
    set_state(socket_id, {"recordingTimerId": task})


async def resolve_emergency(socket_id: str, io: Any, reason: str = "Safety confirmed by user") -> None:
    state = get_state(socket_id)
    _cancel_task(state.get("interceptTimerId"))
    _cancel_task(state.get("_countdownTask"))
    _cancel_task(state.get("recordingTimerId"))
    _log_transition(socket_id, state["status"], STATES["RESOLVED"], reason)
    metadata = {
        "trackingId": state.get("trackingId"), "userName": state.get("userName"),
        "userPhone": state.get("userPhone"), "location": state.get("currentLocation"),
        "transcript": state.get("threatTranscript"), "severity": state.get("threatSeverity"),
        "detectedLanguage": state.get("detectedLanguage"),
        "recordingDuration": _now_ms() - state["recordingStartTime"] if state.get("recordingStartTime") else 0,
        "resolvedAt": _now_iso(), "resolveReason": reason,
        "stateHistory": state.get("stateHistory", []),
    }
    tracking_id = state.get("trackingId") or f"RESOLVED-{secrets.token_hex(4).upper()}"
    try:
        create_metadata(tracking_id, metadata)
    except Exception:
        logger.exception("Could not save resolution metadata")
    set_state(socket_id, {"status": STATES["RESOLVED"]})
    await _emit_room(io, socket_id, "agent-state-update", {
        "status": STATES["RESOLVED"], "message": "Emergency resolved. Returning to monitoring.",
        "langGraphState": STATES["RESOLVED"], "langGraphEdge": reason,
    })
    await _emit_room(io, socket_id, "stop-evidence-recording", {"trackingId": state.get("trackingId")})
    await _emit_all(io, "emergency-resolved", {
        "trackingId": state.get("trackingId"), "resolvedAt": _now_iso(), "reason": reason,
    })

    async def reset_after_resolution() -> None:
        try:
            await asyncio.sleep(2)
            current = get_state(socket_id)
            if current["status"] == STATES["RESOLVED"]:
                set_state(socket_id, {
                    "status": STATES["MONITORING"], "threatTranscript": None, "threatSeverity": None,
                    "detectedLanguage": None, "interceptTimerId": None, "recordingStartTime": None,
                    "recordingTimerId": None, "trackingId": None, "nearestPolice": None,
                })
                _log_transition(socket_id, STATES["RESOLVED"], STATES["MONITORING"], "Auto-reset after resolution")
                await _emit_room(io, socket_id, "agent-state-update", {
                    "status": STATES["MONITORING"], "message": "Agent reset. Monitoring resumed.",
                    "langGraphState": STATES["MONITORING"], "langGraphEdge": "Agent resets, route continues",
                })
        except asyncio.CancelledError:
            return

    _spawn(socket_id, reset_after_resolution())


async def cleanup_agent(socket_id: str) -> None:
    tasks = list(_agent_tasks.pop(socket_id, set()))
    for task in tasks:
        if not task.done():
            task.cancel()
    state = agent_states.pop(socket_id, None)
    if state:
        logger.info("Cleaned up agent state for %s", socket_id)


# JavaScript-name aliases ease integration while migrating.
normalizeText = normalize_text
findDistressKeywords = find_distress_keywords
detectKeywordLanguage = detect_keyword_language
startMonitoring = start_monitoring
stopMonitoring = stop_monitoring
processTranscript = process_transcript
handleOrchestratorResponse = handle_orchestrator_response
startInterceptCountdown = start_intercept_countdown
cancelIntercept = cancel_intercept
executeEmergencyProtocol = execute_emergency_protocol
startRecording = start_recording
resolveEmergency = resolve_emergency
cleanupAgent = cleanup_agent
getState = get_state
setState = set_state
logTransition = _log_transition

__all__ = [
    "STATES", "DISTRESS_KEYWORDS", "SUSPICIOUS_SOUND_PATTERNS", "agent_states",
    "normalize_text", "find_distress_keywords", "detect_keyword_language",
    "get_state", "set_state", "start_monitoring", "stop_monitoring",
    "process_transcript", "handle_orchestrator_response", "start_intercept_countdown",
    "cancel_intercept", "execute_emergency_protocol", "start_recording",
    "resolve_emergency", "cleanup_agent",
    "startMonitoring", "stopMonitoring", "processTranscript", "cancelIntercept",
    "resolveEmergency", "cleanupAgent", "getState", "detectKeywordLanguage",
]
