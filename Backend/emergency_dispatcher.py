"""Sakhi-Sahayak emergency dispatcher.

Features:
- Resend email alerts to the emergency contact and nearest police station.
- Twilio SMS alerts, with email fallback when SMS cannot be submitted.
- Socket.IO live-location and dashboard events.
- Duplicate-alert suppression by tracking ID.
- HTML emergency email and SMS message builders.

Environment variables:
    RESEND_API                 Resend API key
    RESEND_FROM_EMAIL          Verified sender, e.g. "Sakhi-Sahayak <alerts@yourdomain.com>"
    EMERGENCY_EMAIL            Default emergency contact email
    EMERGENCY_PHONE            Default emergency contact phone
    TWILIO_ACCOUNT_SID
    TWILIO_AUTH_TOKEN
    TWILIO_PHONE_NUMBER        Twilio number in E.164 format, e.g. +1...
    TWILIO_TRIAL_TEMPLATE      Optional trial-only body/template identifier. Set only if
                               your Twilio trial setup explicitly accepts this value.

Integration:
    from emergency_dispatcher import dispatch_full_emergency
    result = await dispatch_full_emergency(sio, alert_data)

`sio` should be a python-socketio AsyncServer instance.
"""

from __future__ import annotations

import asyncio
import html
import logging
import os
import re
import time
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx

try:
    from twilio.rest import Client as TwilioClient
except ImportError:  # Twilio is optional until SMS is configured.
    TwilioClient = None  # type: ignore[assignment,misc]

logger = logging.getLogger("sakhi_sahayak.dispatcher")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO)

RESEND_API_KEY = os.getenv("RESEND_API", "").strip()
RESEND_FROM_EMAIL = os.getenv(
    "RESEND_FROM_EMAIL", "Sakhi-Sahayak <onboarding@resend.dev>"
).strip()
EMERGENCY_EMAIL = os.getenv("EMERGENCY_EMAIL", "").strip()
EMERGENCY_PHONE = os.getenv("EMERGENCY_PHONE", "").strip()
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "").strip()
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "").strip()
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER", "").strip()
TWILIO_TRIAL_TEMPLATE = os.getenv("TWILIO_TRIAL_TEMPLATE", "").strip()

RESEND_API_URL = "https://api.resend.com/emails"
INDIA_TZ = ZoneInfo("Asia/Kolkata")

_twilio_client = None
if (
    TwilioClient is not None
    and TWILIO_ACCOUNT_SID
    and TWILIO_AUTH_TOKEN
    and TWILIO_PHONE_NUMBER
):
    try:
        _twilio_client = TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        logger.info("[Dispatcher] Twilio API initialized")
    except Exception:
        logger.exception("[Dispatcher] Could not initialize Twilio client")
elif any((TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER)):
    logger.warning("[Dispatcher] Twilio configuration is incomplete")

# tracking_id -> monotonic timestamp of the last accepted dispatch
_dispatched_alerts: dict[str, float] = {}
_dispatch_lock = asyncio.Lock()


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat()


def _india_time() -> str:
    return datetime.now(INDIA_TZ).strftime("%d/%m/%Y, %I:%M:%S %p IST")


def _get(obj: Any, key: str, default: Any = None) -> Any:
    """Read a value from either a dict or an object."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _maps_link(location: Any) -> str | None:
    if not location:
        return None
    lat = _get(location, "lat")
    lng = _get(location, "lng")
    if lat is None or lng is None:
        return None
    try:
        return f"https://maps.google.com/maps?q={float(lat)},{float(lng)}"
    except (TypeError, ValueError):
        return None


def normalize_phone(phone: str) -> str:
    """Normalize a phone number to E.164; bare 10-digit numbers default to India."""
    raw = str(phone or "").strip()
    if not raw:
        raise ValueError("Phone number is empty")

    # Keep a leading '+' as a signal that the input already includes a country code.
    if raw.startswith("+"):
        digits = re.sub(r"\D", "", raw)
        if not 8 <= len(digits) <= 15:
            raise ValueError("Phone number must contain 8–15 digits")
        return f"+{digits}"

    digits = re.sub(r"\D", "", raw)
    if digits.startswith("00"):
        digits = digits[2:]
    if len(digits) == 10:
        return f"+91{digits}"
    if len(digits) == 11 and digits.startswith("0"):
        return f"+91{digits[1:]}"
    if len(digits) == 12 and digits.startswith("91"):
        return f"+{digits}"
    if 8 <= len(digits) <= 15:
        # A non-Indian number without '+' is treated as a country-code-prefixed number.
        return f"+{digits}"
    raise ValueError("Phone number must contain a valid country code and 8–15 digits")


def _language_display(language: str | None) -> dict[str, str]:
    language = (language or "unknown").lower()
    known = {
        "en": {"name": "English", "flag": "🇬🇧", "color": "#60A5FA"},
        "hi": {"name": "Hindi", "flag": "🇮🇳", "color": "#F59E0B"},
        "mr": {"name": "Marathi", "flag": "🇮🇳", "color": "#F59E0B"},
        "bn": {"name": "Bengali", "flag": "🇮🇳", "color": "#34D399"},
        "ta": {"name": "Tamil", "flag": "🇮🇳", "color": "#A78BFA"},
        "te": {"name": "Telugu", "flag": "🇮🇳", "color": "#A78BFA"},
        "unknown": {"name": "Unknown language", "flag": "🌐", "color": "#94A3B8"},
    }
    return known.get(language, {"name": language.upper(), "flag": "🌐", "color": "#94A3B8"})


def _optional_station_line(station: Any, key: str, prefix: str) -> str:
    value = _get(station, key)
    if not value:
        return ""
    if isinstance(value, (list, tuple)):
        value = ", ".join(str(item) for item in value)
    value = html.escape(str(value))
    if key == "distanceText":
        value = f"{value} away"
    return (
        '<p style="color:#94A3B8;font-size:13px;margin:4px 0;">'
        f"{prefix} {value}</p>"
    )


def build_emergency_email_html(alert_data: dict[str, Any]) -> str:
    tracking_id = html.escape(str(alert_data.get("trackingId") or "N/A"))
    user_name = html.escape(str(alert_data.get("userName") or "Unknown User"))
    user_phone = html.escape(str(alert_data.get("userPhone") or "N/A"))
    transcript = html.escape(str(alert_data.get("transcript") or ""))
    severity = str(alert_data.get("severity") or "high").lower()
    severity_label = html.escape(severity.upper())
    location = alert_data.get("location")
    nearest = alert_data.get("nearestStation") or {}
    lang = _language_display(alert_data.get("detectedLanguage"))
    severity_colors = {
        "critical": "#DC2626",
        "high": "#EF4444",
        "medium": "#F59E0B",
        "low": "#3B82F6",
    }
    color = severity_colors.get(severity, "#EF4444")
    maps_link = _maps_link(location)

    lat = _get(location, "lat") if location else None
    lng = _get(location, "lng") if location else None
    coords = (
        f"{html.escape(str(lat))}, {html.escape(str(lng))}"
        if lat is not None and lng is not None
        else "Location unavailable"
    )

    station_html = ""
    if nearest:
        station_name = html.escape(str(_get(nearest, "name", "Unknown station")))
        station_html = f"""
        <div style="background:rgba(96,165,250,.08);border:1px solid rgba(96,165,250,.25);border-radius:12px;padding:16px;margin-bottom:20px;">
          <p style="color:#94A3B8;font-size:11px;margin:0 0 8px;text-transform:uppercase;">NEAREST POLICE STATION</p>
          <p style="color:white;font-size:15px;font-weight:700;margin:0 0 4px;">🚔 {station_name}</p>
          {_optional_station_line(nearest, 'contact', '📞')}
          {_optional_station_line(nearest, 'phone', '📞')}
          {_optional_station_line(nearest, 'email', '📧')}
          {_optional_station_line(nearest, 'officerInCharge', '👮 Officer:')}
          {_optional_station_line(nearest, 'distanceText', '📏')}
        </div>
        """

    maps_button = (
        f'<a href="{html.escape(maps_link, quote=True)}" target="_blank" '
        'style="display:block;background:#16A34A;color:white;text-align:center;'
        'padding:16px;border-radius:12px;font-size:16px;font-weight:700;'
        'text-decoration:none;margin-bottom:20px;">📍 OPEN LOCATION IN GOOGLE MAPS</a>'
        if maps_link
        else ""
    )
    transcript_html = (
        '<div style="background:rgba(239,68,68,.08);border:1px solid rgba(239,68,68,.25);'
        'border-radius:12px;padding:16px;margin-bottom:20px;">'
        f'<p style="color:#94A3B8;font-size:11px;margin:0 0 6px;">DETECTED DISTRESS SPEECH '
        f'({lang["flag"]} {html.escape(lang["name"])})</p>'
        f'<p style="color:#FCA5A5;font-size:15px;font-style:italic;margin:0;">"{transcript}"</p>'
        '</div>'
        if transcript
        else ""
    )
    timestamp = html.escape(str(alert_data.get("timestamp") or _india_time()))
    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#0F172A;font-family:Arial,Helvetica,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#0F172A;padding:32px 12px;"><tr><td align="center">
<table width="600" cellpadding="0" cellspacing="0" style="max-width:100%;background:#1E293B;border-radius:16px;overflow:hidden;border:2px solid {color};">
<tr><td style="background:{color};padding:24px 32px;"><h1 style="color:white;margin:0;font-size:24px;font-weight:900;">🚨 EMERGENCY SOS ALERT</h1>
<p style="color:white;margin:8px 0 0;font-size:14px;">Sakhi-Sahayak Safety System • Emergency notification</p></td></tr>
<tr><td style="padding:28px;"><p><span style="color:{color};font-weight:bold;">{severity_label} SEVERITY</span>
&nbsp; <span style="color:{html.escape(lang['color'])};">{lang['flag']} {html.escape(lang['name'])}</span>
<span style="float:right;color:#94A3B8;font-family:monospace;">{tracking_id}</span></p>
<table width="100%" cellpadding="12" cellspacing="0" style="background:#0F172A;border-radius:12px;margin-bottom:20px;color:white;">
<tr><td><span style="color:#94A3B8;font-size:12px;">USER</span><br><b>{user_name}</b></td>
<td align="right"><span style="color:#94A3B8;font-size:12px;">PHONE</span><br><b>{user_phone}</b></td></tr>
<tr><td colspan="2"><span style="color:#94A3B8;font-size:12px;">GPS COORDINATES</span><br>{coords}</td></tr></table>
{maps_button}{transcript_html}{station_html}
<p style="color:#94A3B8;font-size:12px;text-align:center;">⏰ Alert dispatched: {timestamp}</p></td></tr>
<tr><td style="background:#0F172A;padding:20px 32px;border-top:1px solid #1E293B;"><p style="color:#94A3B8;font-size:11px;margin:0;text-align:center;">Automated emergency alert from Sakhi-Sahayak Women Safety System.<br>If this is a false alarm, contact the user directly.</p></td></tr>
</table></td></tr></table></body></html>"""


def build_sms_message(alert_data: dict[str, Any]) -> str:
    location = alert_data.get("location")
    maps_link = _maps_link(location) or "Location unavailable"
    name = str(alert_data.get("userName") or "Unknown")
    phone = str(alert_data.get("userPhone") or "N/A")
    severity = str(alert_data.get("severity") or "HIGH").upper()
    tracking_id = str(alert_data.get("trackingId") or "N/A")
    transcript = str(alert_data.get("transcript") or "").strip()
    speech = f' Speech: "{transcript[:60]}"' if transcript else ""
    return (
        f"EMERGENCY SOS - Sakhi-Sahayak. Ref: {tracking_id}. "
        f"User: {name} ({phone}). Severity: {severity}. "
        f"Location: {maps_link}.{speech} Time: {_india_time()}"
    )


async def _send_resend_email(
    recipient: str, subject: str, html_body: str, text_body: str
) -> dict[str, Any]:
    if not RESEND_API_KEY:
        return {"success": False, "error": "RESEND_API is not configured"}
    if not recipient or "@" not in recipient:
        return {"success": False, "error": f"Invalid recipient email: {recipient!r}"}

    payload = {
        "from": RESEND_FROM_EMAIL,
        "to": [recipient],
        "subject": subject,
        "html": html_body,
        "text": text_body,
    }
    headers = {
        "Authorization": f"Bearer {RESEND_API_KEY}",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(RESEND_API_URL, json=payload, headers=headers)
        if response.is_success:
            try:
                body = response.json()
            except ValueError:
                body = {}
            return {"success": True, "messageId": body.get("id"), "status_code": response.status_code}

        try:
            error_body = response.json()
        except ValueError:
            error_body = {"message": response.text[:1000]}
        # Response body is useful for diagnosing 403/401 errors. Never log the API key.
        logger.error("Resend rejected email: status=%s response=%s", response.status_code, error_body)
        return {
            "success": False,
            "status_code": response.status_code,
            "error": error_body,
        }
    except Exception as exc:
        logger.exception("Resend request failed for recipient %s", recipient)
        return {"success": False, "error": str(exc)}


async def dispatch_email(alert_data: dict[str, Any]) -> dict[str, Any]:
    recipients: list[str] = []
    if EMERGENCY_EMAIL:
        recipients.append(EMERGENCY_EMAIL)

    station_email = _get(alert_data.get("nearestStation") or {}, "email")
    if isinstance(station_email, (list, tuple)):
        station_emails = [str(item).strip() for item in station_email if str(item).strip()]
    elif station_email:
        station_emails = [str(station_email).strip()]
    else:
        station_emails = []
    for email_address in station_emails:
        if email_address not in recipients:
            recipients.append(email_address)

    if not recipients:
        return {"success": False, "error": "No emergency email recipients configured"}

    html_body = build_emergency_email_html(alert_data)
    text_body = build_sms_message(alert_data)
    subject = (
        f"EMERGENCY SOS ALERT - {str(alert_data.get('severity') or 'HIGH').upper()} - "
        f"{alert_data.get('trackingId') or 'Sakhi-Sahayak'}"
    )

    async def send_one(recipient: str) -> dict[str, Any]:
        result = await _send_resend_email(recipient, subject, html_body, text_body)
        return {"recipient": recipient, **result}

    results = await asyncio.gather(*(send_one(recipient) for recipient in recipients))
    successful = [item for item in results if item.get("success")]
    return {
        "success": bool(successful),
        "recipients": results,
        "messageId": successful[0].get("messageId") if successful else None,
        "totalSent": len(successful),
        "totalFailed": len(results) - len(successful),
    }


async def dispatch_sms(alert_data: dict[str, Any]) -> dict[str, Any]:
    raw_phones: list[str] = []
    recipient_phone = alert_data.get("recipientPhone") or EMERGENCY_PHONE
    if recipient_phone:
        raw_phones.append(str(recipient_phone))

    station_phone = _get(alert_data.get("nearestStation") or {}, "phone")
    if isinstance(station_phone, (list, tuple)):
        raw_phones.extend(str(phone) for phone in station_phone if phone)
    elif station_phone:
        raw_phones.append(str(station_phone))

    unique_phones: list[str] = []
    invalid_phones: list[dict[str, str]] = []
    for raw_phone in raw_phones:
        try:
            normalized = normalize_phone(raw_phone)
        except ValueError as exc:
            invalid_phones.append({"phone": raw_phone, "error": str(exc)})
            continue
        if normalized not in unique_phones:
            unique_phones.append(normalized)

    if not unique_phones:
        return {
            "success": False,
            "method": "none",
            "error": "No valid SMS recipient phone numbers configured",
            "invalidRecipients": invalid_phones,
        }

    message = build_sms_message(alert_data)
    logger.info("Attempting SMS dispatch to %d recipient(s)", len(unique_phones))

    if _twilio_client:
        sent_ids: list[str] = []
        failures: list[dict[str, str]] = []
        for phone in unique_phones:
            # Trial accounts may only accept a predefined template/body. Set this env var
            # only if your account explicitly supports the configured identifier.
            body_to_send = TWILIO_TRIAL_TEMPLATE or message
            try:
                response = await asyncio.to_thread(
                    _twilio_client.messages.create,
                    body=body_to_send,
                    from_=TWILIO_PHONE_NUMBER,
                    to=phone,
                )
                sent_ids.append(response.sid)
                logger.info(
                    "Twilio accepted SMS request to %s (SID: %s, status: %s)",
                    phone,
                    response.sid,
                    getattr(response, "status", "unknown"),
                )
            except Exception as exc:
                error_text = str(exc)
                failures.append({"phone": phone, "error": error_text})
                logger.warning("Twilio failed for recipient %s: %s", phone, error_text)

        if sent_ids:
            return {
                "success": True,
                "method": "twilio",
                "phones": unique_phones,
                "requestIds": sent_ids,
                "message": "Twilio accepted the SMS request; delivery status may still be pending",
                "failedRecipients": failures,
                "invalidRecipients": invalid_phones,
                "trialTemplateUsed": bool(TWILIO_TRIAL_TEMPLATE),
            }

    # Email fallback does not mean an SMS was sent.
    if RESEND_API_KEY and EMERGENCY_EMAIL:
        fallback_html = (
            '<div style="font-family:Arial,sans-serif;padding:24px;border:2px solid #EF4444;">'
            '<h2 style="color:#EF4444;">SMS delivery fallback notification</h2>'
            f"<p>SMS could not be submitted to: {html.escape(', '.join(unique_phones))}</p>"
            f"<pre style=\"white-space:pre-wrap;\">{html.escape(message)}</pre></div>"
        )
        fallback = await _send_resend_email(
            EMERGENCY_EMAIL,
            f"SMS FALLBACK NOTICE - {alert_data.get('trackingId') or 'SOS'}",
            fallback_html,
            f"SMS could not be submitted to: {', '.join(unique_phones)}\n\n{message}",
        )
        if fallback.get("success"):
            return {
                "success": False,
                "method": "email_fallback",
                "phones": unique_phones,
                "messageId": fallback.get("messageId"),
                "note": "Fallback email was accepted; this is not SMS delivery confirmation.",
                "failedRecipients": invalid_phones,
            }

    return {
        "success": False,
        "method": "none",
        "phones": unique_phones,
        "message": "SMS was not accepted by Twilio and email fallback was unavailable or failed",
        "invalidRecipients": invalid_phones,
    }


async def dispatch_live_location(sio: Any, data: dict[str, Any]) -> dict[str, Any]:
    if sio is None:
        logger.error("No Socket.IO instance for location dispatch")
        return {"success": False, "error": "No Socket.IO instance"}

    location = data.get("location") or {}
    lat = data.get("lat", _get(location, "lat"))
    lng = data.get("lng", _get(location, "lng"))
    maps_link = _maps_link({"lat": lat, "lng": lng}) if lat is not None and lng is not None else None
    payload = {
        "trackingId": data.get("trackingId"),
        "lat": lat,
        "lng": lng,
        "userName": data.get("userName"),
        "userPhone": data.get("userPhone"),
        "timestamp": _now_iso(),
        "googleMapsLink": maps_link,
    }
    await sio.emit("emergency-location-update", payload)
    tracking_id = data.get("trackingId")
    if tracking_id:
        await sio.emit("live-location-stream", payload, room=f"webrtc-{tracking_id}")
    return {"success": True, "method": "socketio+webrtc"}


async def _emit_safely(sio: Any, event: str, payload: dict[str, Any]) -> None:
    if sio is not None:
        await sio.emit(event, payload)


async def dispatch_full_emergency(
    sio: Any, alert_data: dict[str, Any]
) -> dict[str, Any]:
    tracking_id = str(alert_data.get("trackingId") or "UNKNOWN")
    now = time.monotonic()

    async with _dispatch_lock:
        previous = _dispatched_alerts.get(tracking_id)
        if previous is not None and now - previous < 60:
            logger.warning("Duplicate alert suppressed for %s", tracking_id)
            return {"suppressed": True, "trackingId": tracking_id}
        _dispatched_alerts[tracking_id] = now

    logger.warning(
        "EMERGENCY DISPATCH | trackingId=%s | user=%s | severity=%s",
        tracking_id,
        alert_data.get("userName") or "Unknown",
        str(alert_data.get("severity") or "HIGH").upper(),
    )

    results: dict[str, Any] = {
        "trackingId": tracking_id,
        "timestamp": _now_iso(),
        "email": None,
        "sms": None,
        "liveLocation": None,
        "policeDashboard": None,
    }

    email_result, sms_result = await asyncio.gather(
        dispatch_email(alert_data),
        dispatch_sms(alert_data),
        return_exceptions=True,
    )
    if isinstance(email_result, BaseException):
        logger.exception("Email dispatch raised an exception", exc_info=email_result)
        results["email"] = {"success": False, "error": str(email_result)}
    else:
        results["email"] = email_result

    if isinstance(sms_result, BaseException):
        logger.error("SMS dispatch raised an exception: %s", sms_result)
        results["sms"] = {"success": False, "error": str(sms_result)}
    else:
        results["sms"] = sms_result

    location = alert_data.get("location")
    if sio is not None and location:
        try:
            results["liveLocation"] = await dispatch_live_location(
                sio,
                {
                    "trackingId": tracking_id,
                    "lat": _get(location, "lat"),
                    "lng": _get(location, "lng"),
                    "location": location,
                    "userName": alert_data.get("userName"),
                    "userPhone": alert_data.get("userPhone"),
                },
            )
        except Exception as exc:
            logger.exception("Live location dispatch failed")
            results["liveLocation"] = {"success": False, "error": str(exc)}
    else:
        results["liveLocation"] = {
            "success": False,
            "error": "No Socket.IO instance or location available",
        }

    if sio is not None:
        try:
            maps_link = _maps_link(location)
            await _emit_safely(
                sio,
                "emergency-dispatch-complete",
                {
                    "trackingId": tracking_id,
                    "userName": alert_data.get("userName"),
                    "userPhone": alert_data.get("userPhone"),
                    "location": location,
                    "transcript": alert_data.get("transcript"),
                    "severity": alert_data.get("severity"),
                    "nearestStation": alert_data.get("nearestStation"),
                    "timestamp": _now_iso(),
                    "googleMapsLink": maps_link,
                    "dispatchResults": {
                        "emailSent": bool((results["email"] or {}).get("success")),
                        "smsSent": bool((results["sms"] or {}).get("success")),
                        "locationStreaming": bool((results["liveLocation"] or {}).get("success")),
                    },
                },
            )
            await _emit_safely(
                sio,
                "sms-relay-request",
                {
                    "trackingId": tracking_id,
                    "phoneNumber": EMERGENCY_PHONE,
                    "countryCode": "+91",
                    "message": build_sms_message(alert_data),
                    "timestamp": _now_iso(),
                },
            )
            results["policeDashboard"] = {"success": True}
        except Exception as exc:
            logger.exception("Police dashboard notification failed")
            results["policeDashboard"] = {"success": False, "error": str(exc)}
    else:
        results["policeDashboard"] = {"success": False, "error": "No Socket.IO instance"}

    logger.info(
        "Dispatch summary | email=%s | sms=%s | location=%s | dashboard=%s",
        bool((results["email"] or {}).get("success")),
        bool((results["sms"] or {}).get("success")),
        bool((results["liveLocation"] or {}).get("success")),
        bool((results["policeDashboard"] or {}).get("success")),
    )
    return results


async def cleanup_old_dispatch_records() -> None:
    """Remove duplicate-suppression entries older than five minutes."""
    now = time.monotonic()
    async with _dispatch_lock:
        expired = [
            tracking_id
            for tracking_id, dispatched_at in _dispatched_alerts.items()
            if now - dispatched_at > 300
        ]
        for tracking_id in expired:
            _dispatched_alerts.pop(tracking_id, None)


# JavaScript-style aliases retained for compatibility with existing call sites.
buildEmergencyEmailHTML = build_emergency_email_html
buildSMSMessage = build_sms_message
dispatchEmail = dispatch_email
dispatchSMS = dispatch_sms
dispatchLiveLocation = dispatch_live_location
dispatchFullEmergency = dispatch_full_emergency
