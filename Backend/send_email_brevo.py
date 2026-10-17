"""

Sakhi-Sahayak email dispatcher (Python conversion of send-email.js).



Environment:

    BREVO_API_KEY    Required Brevo API key.

    BREVO_SENDER_EMAIL Required verified sender address in Brevo.

    TARGET_EMAIL     Optional recipient override; defaults to the address in the JS source.



Functions:

    await send_emergency_email(alert_data)

    await send_transcription_email(data)

"""

from __future__ import annotations



import html

import logging

import os

from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo



import httpx



logger = logging.getLogger("sakhi_sahayak.send_email")

if not logger.handlers:

    logging.basicConfig(level=logging.INFO)



BREVO_API_KEY = os.getenv("BREVO_API_KEY", "").strip()

TARGET_EMAIL = os.getenv("TARGET_EMAIL", os.getenv("EMERGENCY_EMAIL", "")).strip()

BREVO_SENDER_EMAIL = os.getenv("BREVO_SENDER_EMAIL", "").strip()
BREVO_SENDER_NAME = os.getenv("BREVO_SENDER_NAME", "Sakhi-Sahayak").strip()

BREVO_EMAIL_URL = "https://api.brevo.com/v3/smtp/email"

INDIA_TZ = ZoneInfo("Asia/Kolkata")
DATABASE_FILE = Path(os.getenv("DATABASE_FILE", str(Path(__file__).resolve().parent / "sakhi_sahayak.db"))).resolve()


def _get_emergency_contact_from_db(identifier: str | None) -> dict[str, str]:
    if not identifier or not DATABASE_FILE.exists():
        return {}
    try:
        import sqlite3
        with sqlite3.connect(DATABASE_FILE) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT emergency_name, emergency_phone, emergency_email FROM users WHERE phone = ? OR name = ?",
                (str(identifier).strip(), str(identifier).strip()),
            ).fetchone()
            if row:
                return {
                    "emergency_name": str(row["emergency_name"] or "").strip(),
                    "emergency_phone": str(row["emergency_phone"] or "").strip(),
                    "emergency_email": str(row["emergency_email"] or "").strip(),
                }
    except Exception:
        pass
    return {}



LANGUAGE_MAP: dict[str, dict[str, str]] = {

    "hi-IN": {"name": "Hindi", "flag": "🇮🇳", "color": "#F59E0B"},

    "hi": {"name": "Hindi", "flag": "🇮🇳", "color": "#F59E0B"},

    "mr-IN": {"name": "Marathi", "flag": "🇮🇳", "color": "#8B5CF6"},

    "mr": {"name": "Marathi", "flag": "🇮🇳", "color": "#8B5CF6"},

    "en-IN": {"name": "English", "flag": "🇬🇧", "color": "#3B82F6"},

    "en": {"name": "English", "flag": "🇬🇧", "color": "#3B82F6"},

    "unknown": {"name": "Auto-Detected", "flag": "🌐", "color": "#64748B"},

}





def get_language_display(lang_code: str | None) -> dict[str, str]:

    return LANGUAGE_MAP.get(str(lang_code or "unknown"), LANGUAGE_MAP["unknown"])





def _now_india() -> str:

    return datetime.now(INDIA_TZ).strftime("%d/%m/%Y, %I:%M:%S %p")





def _esc(value: Any, fallback: str = "") -> str:

    return html.escape(str(value if value is not None else fallback), quote=True)





def _location_values(location: Any) -> tuple[Any, Any]:

    if not isinstance(location, dict):

        return None, None

    return location.get("lat"), location.get("lng", location.get("lon"))





def _maps_link(location: Any) -> str | None:

    lat, lng = _location_values(location)

    if lat is None or lng is None:

        return None

    return f"https://maps.google.com/maps?q={lat},{lng}"





def _station_html(station: Any, transcription: bool = False) -> str:

    if not isinstance(station, dict):

        return ""

    parts = [

        '<div style="background:rgba(96,165,250,.08);border:1px solid rgba(96,165,250,.25);'

        'border-radius:12px;padding:16px;margin-bottom:20px;">',

        '<p style="color:#94A3B8;font-size:11px;margin:0 0 8px;text-transform:uppercase;">'

        'NEAREST POLICE STATION</p>',

        f'<p style="color:white;font-size:15px;font-weight:700;">🚔 {_esc(station.get("name"), "Unknown station")}</p>',

    ]

    contact = station.get("contact")

    phone = station.get("phone")

    email = station.get("email")

    distance = station.get("distanceText", station.get("distance_text"))

    if contact:

        parts.append(f'<p style="color:#4ADE80;">📞 {_esc(contact)}</p>')

    if phone:

        phone_text = ", ".join(map(str, phone)) if isinstance(phone, list) else str(phone)

        parts.append(f'<p style="color:#4ADE80;">📞 {_esc(phone_text)}</p>')

    if email:

        parts.append(f'<p style="color:#60A5FA;">📧 {_esc(email)}</p>')

    if distance:

        parts.append(f'<p style="color:#F59E0B;">📏 {_esc(distance)} away</p>')

    parts.append("</div>")

    return "".join(parts)





def build_emergency_sos_html(data: dict[str, Any]) -> str:

    severity = str(data.get("severity") or "HIGH").upper()

    severity_color = {

        "CRITICAL": "#DC2626", "HIGH": "#EF4444",

        "MEDIUM": "#F59E0B", "LOW": "#3B82F6",

    }.get(severity, "#EF4444")

    lang = get_language_display(data.get("detectedLanguage", data.get("detected_language")))

    location = data.get("location")

    lat, lng = _location_values(location)

    maps = _maps_link(location)

    transcript = data.get("transcript")

    tracking_id = _esc(data.get("trackingId", data.get("tracking_id")), "N/A")

    user_name = _esc(data.get("userName", data.get("user_name")), "Unknown User")

    user_phone = _esc(data.get("userPhone", data.get("user_phone")), "N/A")

    timestamp = _esc(data.get("timestamp") or _now_india())

    location_text = f"{_esc(lat)}, {_esc(lng)}" if lat is not None and lng is not None else "Location unavailable"

    map_button = (

        f'<a href="{_esc(maps)}" target="_blank" rel="noopener" style="display:block;background:#16A34A;'

        f'color:white;text-align:center;padding:16px;border-radius:12px;font-weight:700;text-decoration:none;'

        f'margin-bottom:20px;">📍 OPEN LOCATION IN GOOGLE MAPS</a>' if maps else ""

    )

    transcript_block = (

        '<div style="background:rgba(239,68,68,.08);border:1px solid rgba(239,68,68,.25);'

        f'border-radius:12px;padding:16px;margin-bottom:20px;"><p style="color:#94A3B8;font-size:11px;">'

        f'DETECTED DISTRESS SPEECH ({lang["flag"]} {lang["name"]})</p><p style="color:#FCA5A5;font-size:15px;'

        f'font-style:italic;">"{_esc(transcript)}"</p></div>'

    ) if transcript else ""

    return f"""<!doctype html><html><head><meta charset="UTF-8"></head>

<body style="margin:0;padding:24px;background:#0F172A;font-family:Arial,Helvetica,sans-serif;color:white;">

<table width="100%" cellpadding="0" cellspacing="0"><tr><td align="center">

<table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;background:#1E293B;border:2px solid {severity_color};border-radius:16px;">

<tr><td style="background:{severity_color};padding:24px 32px;"><h1 style="margin:0;">🚨 EMERGENCY SOS ALERT</h1>

<p>Sakhi-Sahayak Safety System • EMERGENCY_PROTOCOL</p></td></tr>

<tr><td style="padding:28px;">

<p><b style="color:{severity_color};">{_esc(severity)} SEVERITY</b> &nbsp; {lang["flag"]} {_esc(lang["name"])}

<br><small style="color:#94A3B8;">Tracking ID: {tracking_id}</small></p>

<table width="100%" cellpadding="12" style="background:#0F172A;border-radius:12px;">

<tr><td><small>USER</small><br><b>{user_name}</b></td><td align="right"><small>PHONE</small><br><b>{user_phone}</b></td></tr>

<tr><td colspan="2"><small>GPS COORDINATES</small><br>{location_text}</td></tr></table>

{map_button}{transcript_block}

<div style="background:rgba(139,92,246,.08);padding:16px;border-radius:12px;margin-bottom:20px;">

<small>LANGGRAPH STATE MACHINE</small><p>IDLE → MONITORING → THREAT_DETECTED → INTERCEPT_COUNTDOWN → <b>EMERGENCY_PROTOCOL</b> → RECORDING → RESOLVED</p></div>

{_station_html(data.get("nearestStation", data.get("nearest_station")))}

<p style="color:#94A3B8;font-size:12px;text-align:center;">⏰ Alert dispatched: {timestamp}</p></td></tr>

<tr><td style="background:#0F172A;padding:18px;text-align:center;color:#94A3B8;font-size:11px;">

Automated emergency alert from Sakhi-Sahayak<br>Sent to: {_esc(TARGET_EMAIL)}</td></tr>

</table></td></tr></table></body></html>"""





def build_transcription_html(data: dict[str, Any]) -> str:

    lang = get_language_display(data.get("language"))

    severity = data.get("severity")

    location = data.get("location")

    lat, lng = _location_values(location)

    maps = _maps_link(location)

    map_button = (

        f'<a href="{_esc(maps)}" target="_blank" rel="noopener" style="display:block;background:#16A34A;'

        f'color:white;text-align:center;padding:14px;border-radius:12px;text-decoration:none;">'

        f'📍 VIEW LOCATION ON GOOGLE MAPS</a>' if maps else ""

    )

    severity_badge = (

        f'<span style="color:#EF4444;font-weight:bold;">{_esc(severity).upper()} THREAT</span>'

        if severity else ""

    )

    transcript = _esc(data.get("transcript"), "(no transcript)")

    summary = data.get("summary")

    summary_block = (

        f'<div style="background:rgba(96,165,250,.08);padding:16px;border-radius:12px;margin-bottom:20px;">'

        f'<small>ORCHESTRATOR LLM ANALYSIS</small><p>{_esc(summary)}</p></div>'

    ) if summary else ""

    tracking_id = _esc(data.get("trackingId", data.get("tracking_id")), "N/A")

    user_name = _esc(data.get("userName", data.get("user_name")), "Unknown")

    timestamp = _esc(data.get("timestamp") or _now_india())

    location_text = f"{_esc(lat)}, {_esc(lng)}" if lat is not None and lng is not None else "Unknown"

    return f"""<!doctype html><html><head><meta charset="UTF-8"></head>

<body style="margin:0;padding:24px;background:#0F172A;font-family:Arial,Helvetica,sans-serif;color:white;">

<table width="100%" cellpadding="0" cellspacing="0"><tr><td align="center">

<table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;background:#1E293B;border:2px solid {lang["color"]};border-radius:16px;">

<tr><td style="background:{lang["color"]};padding:24px 32px;"><h1 style="margin:0;">🎤 THREAT TRANSCRIPTION DETECTED</h1>

<p>Sakhi-Sahayak Voice Agent • {lang["flag"]} {_esc(lang["name"])} detected</p></td></tr>

<tr><td style="padding:28px;"><p>{lang["flag"]} {_esc(lang["name"])} &nbsp; {severity_badge}</p>

<div style="background:rgba(239,68,68,.08);padding:20px;border-radius:12px;margin-bottom:20px;">

<small>TRANSCRIBED SPEECH</small><p style="color:#FCA5A5;font-size:18px;font-style:italic;">"{transcript}"</p></div>

{summary_block}

<div style="background:rgba(139,92,246,.08);padding:16px;border-radius:12px;margin-bottom:20px;">

<small>LANGGRAPH STATE MACHINE</small><p>MONITORING → <b>THREAT_DETECTED</b> → INTERCEPT_COUNTDOWN → EMERGENCY_PROTOCOL</p></div>

{_station_html(data.get("nearestStation", data.get("nearest_station")), True)}

<p>User: <b>{user_name}</b><br>Tracking: <code>{tracking_id}</code><br>Location: {location_text}</p>

{map_button}<p style="color:#94A3B8;font-size:12px;text-align:center;">⏰ {timestamp}</p></td></tr>

<tr><td style="background:#0F172A;padding:18px;text-align:center;color:#94A3B8;font-size:11px;">

Sakhi-Sahayak Voice Agent • STT → Orchestrator → Email Dispatch</td></tr>

</table></td></tr></table></body></html>"""





async def _send_email(subject: str, html_body: str, text_body: str, recipient: str | None = None) -> dict[str, Any]:
    target = (str(recipient or "").strip() or TARGET_EMAIL).strip()
    if not BREVO_API_KEY:
        logger.error("[SendEmail] BREVO_API_KEY is missing; email was not sent.")
        return {"success": False, "error": "Brevo API not configured", "recipient": target}
    if not BREVO_SENDER_EMAIL or "@" not in BREVO_SENDER_EMAIL:
        return {"success": False, "error": "BREVO_SENDER_EMAIL must be a verified sender address", "recipient": target}
    if not target or "@" not in target:
        return {"success": False, "error": "Recipient emergency email is not configured", "recipient": target}

    payload = {
        "sender": {"name": BREVO_SENDER_NAME, "email": BREVO_SENDER_EMAIL},
        "to": [{"email": target}],
        "subject": subject,
        "htmlContent": html_body,
        "textContent": text_body,
    }
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                BREVO_EMAIL_URL,
                headers={"api-key": BREVO_API_KEY, "accept": "application/json", "Content-Type": "application/json"},
                json=payload,
            )
        if response.is_success:
            result = response.json() if response.content else {}
            message_id = result.get("messageId")
            logger.info("[SendEmail] Email accepted by Brevo for %s; id=%s", target, message_id)
            return {"success": True, "messageId": message_id, "recipient": target}
        try:
            details = response.json()
        except ValueError:
            details = response.text
        logger.error("[SendEmail] Brevo failed (%s): %s", response.status_code, details)
        return {"success": False, "error": str(details), "recipient": target}
    except Exception as exc:
        logger.exception("[SendEmail] Email request failed")
        return {"success": False, "error": str(exc), "recipient": target}


async def send_emergency_email(alert_data: dict[str, Any]) -> dict[str, Any]:

    severity = str(alert_data.get("severity") or "HIGH").upper()

    tracking = alert_data.get("trackingId", alert_data.get("tracking_id", "Sakhi-Sahayak"))

    location = alert_data.get("location")

    lat, lng = _location_values(location)

    text_body = (

        "EMERGENCY SOS ALERT\n"

        f"User: {alert_data.get('userName', alert_data.get('user_name', 'Unknown'))} "

        f"({alert_data.get('userPhone', alert_data.get('user_phone', 'N/A'))})\n"

        f"Severity: {severity}\nTranscript: {alert_data.get('transcript') or 'N/A'}\n"

        f"Location: {lat}, {lng}" if lat is not None and lng is not None else

        "EMERGENCY SOS ALERT\n"

        f"User: {alert_data.get('userName', alert_data.get('user_name', 'Unknown'))}\n"

        f"Severity: {severity}\nTranscript: {alert_data.get('transcript') or 'N/A'}\nLocation: Unknown"

    )

    text_body += f"\nTime: {alert_data.get('timestamp') or _now_india()}"

    subject = f"🚨 EMERGENCY SOS — {severity} — {tracking} — Sakhi-Sahayak"

    user_emergency_email = str(
        alert_data.get("emergencyEmail") or alert_data.get("emergency_email") or ""
    ).strip()
    if not user_emergency_email:
        contact_info = _get_emergency_contact_from_db(
            alert_data.get("userPhone") or alert_data.get("userName") or alert_data.get("phone")
        )
        user_emergency_email = contact_info.get("emergency_email", "")

    recipient = user_emergency_email if (user_emergency_email and "@" in user_emergency_email) else TARGET_EMAIL

    return await _send_email(subject, build_emergency_sos_html(alert_data), text_body, recipient=recipient)





async def send_transcription_email(data: dict[str, Any]) -> dict[str, Any]:

    lang = get_language_display(data.get("language"))

    transcript = str(data.get("transcript") or "")

    tracking = data.get("trackingId", data.get("tracking_id", "Sakhi-Sahayak"))

    location = data.get("location")

    lat, lng = _location_values(location)

    location_text = f"{lat}, {lng}" if lat is not None and lng is not None else "Unknown"

    timestamp = _now_india()

    html_data = {**data, "timestamp": data.get("timestamp") or timestamp}

    text_body = (

        "THREAT TRANSCRIPTION DETECTED\n"

        f"Language: {lang['name']}\nTranscript: {transcript}\n"

        f"Severity: {data.get('severity') or 'Unknown'}\n"

        f"User: {data.get('userName', data.get('user_name', 'Unknown'))}\n"

        f"Location: {location_text}\nTime: {timestamp}"

    )

    subject = f"🎤 THREAT DETECTED — {lang['flag']} {lang['name']} — {transcript[:40]}... — {tracking}"

    return await _send_email(subject, build_transcription_html(html_data), text_body)





# JavaScript-name aliases ease migration of callers.

sendEmergencyEmail = send_emergency_email

sendTranscriptionEmail = send_transcription_email

getLanguageDisplay = get_language_display



__all__ = [

    "TARGET_EMAIL", "LANGUAGE_MAP", "get_language_display",

    "build_emergency_sos_html", "build_transcription_html",

    "send_emergency_email", "send_transcription_email",

    "sendEmergencyEmail", "sendTranscriptionEmail", "getLanguageDisplay",

]
