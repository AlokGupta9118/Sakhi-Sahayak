"""
Socket.IO WebRTC signaling for Sakhi-Sahayak.

Designed for python-socketio AsyncServer, usually attached to FastAPI using
socketio.ASGIApp. Signaling relays SDP offers/answers and ICE candidates only;
the audio/video media stream remains peer-to-peer when WebRTC connects.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("sakhi.webrtc")


def setup_webrtc_signaling(sio: Any) -> None:
    """Register WebRTC event handlers on a python-socketio AsyncServer."""

    @sio.on("webrtc-join")
    async def webrtc_join(sid: str, data: dict | None = None) -> None:
        data = data or {}
        tracking_id = str(data.get("trackingId", "")).strip()
        role = str(data.get("role", "unknown"))
        if not tracking_id:
            await sio.emit("webrtc-error", {"error": "trackingId is required"}, to=sid)
            return

        room = f"webrtc-{tracking_id}"
        await sio.enter_room(sid, room)
        logger.info("[WebRTC] %s joined room %s (socket: %s)", role, room, sid)
        await sio.emit(
            "webrtc-peer-joined",
            {"peerId": sid, "role": role},
            room=room,
            skip_sid=sid,
        )

    @sio.on("webrtc-offer")
    async def webrtc_offer(sid: str, data: dict | None = None) -> None:
        data = data or {}
        tracking_id = str(data.get("trackingId", "")).strip()
        sdp = data.get("sdp")
        if not tracking_id or sdp is None:
            await sio.emit("webrtc-error", {"error": "trackingId and sdp are required"}, to=sid)
            return
        room = f"webrtc-{tracking_id}"
        logger.info("[WebRTC] SDP offer received in room %s", room)
        await sio.emit("webrtc-offer", {"sdp": sdp, "from": sid}, room=room, skip_sid=sid)

    @sio.on("webrtc-answer")
    async def webrtc_answer(sid: str, data: dict | None = None) -> None:
        data = data or {}
        tracking_id = str(data.get("trackingId", "")).strip()
        sdp = data.get("sdp")
        if not tracking_id or sdp is None:
            await sio.emit("webrtc-error", {"error": "trackingId and sdp are required"}, to=sid)
            return
        room = f"webrtc-{tracking_id}"
        logger.info("[WebRTC] SDP answer received in room %s", room)
        await sio.emit("webrtc-answer", {"sdp": sdp, "from": sid}, room=room, skip_sid=sid)

    @sio.on("webrtc-ice-candidate")
    async def webrtc_ice_candidate(sid: str, data: dict | None = None) -> None:
        data = data or {}
        tracking_id = str(data.get("trackingId", "")).strip()
        candidate = data.get("candidate")
        if not tracking_id or candidate is None:
            await sio.emit(
                "webrtc-error",
                {"error": "trackingId and candidate are required"},
                to=sid,
            )
            return
        room = f"webrtc-{tracking_id}"
        await sio.emit(
            "webrtc-ice-candidate",
            {"candidate": candidate, "from": sid},
            room=room,
            skip_sid=sid,
        )

    @sio.on("webrtc-leave")
    async def webrtc_leave(sid: str, data: dict | None = None) -> None:
        data = data or {}
        tracking_id = str(data.get("trackingId", "")).strip()
        if not tracking_id:
            return
        room = f"webrtc-{tracking_id}"
        await sio.leave_room(sid, room)
        logger.info("[WebRTC] Socket %s left room %s", sid, room)
        await sio.emit("webrtc-peer-left", {"peerId": sid}, room=room, skip_sid=sid)

    @sio.event
    async def disconnect(sid: str, *args: Any) -> None:
        # python-socketio removes a disconnected socket from its rooms.
        # Capture rooms before disconnect via a custom disconnect handler only
        # if your app needs peer-left notifications. The server's manager may
        # no longer retain these rooms by the time this event fires.
        logger.info("[WebRTC] Socket disconnected: %s", sid)

    logger.info("[WebRTC] Signaling handlers registered")


# Preserve the original module's public function name.
setupWebRTCSignaling = setup_webrtc_signaling
