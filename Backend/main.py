"""Sakhi-Sahayak backend: FastAPI + local SQLite + Socket.IO.

Existing frontend REST routes are preserved. Audio is transcribed by /api/transcribe;
completed transcripts enter voice_agent.py through that route (when socketId is supplied)
or through the Socket.IO `voice-transcript` event. voice_agent.py owns keyword checks,
LLM orchestration, state transitions, emergency dispatch, and evidence lifecycle.
"""
from __future__ import annotations

import os
import asyncio
import json
import math
import uuid
import logging
import tempfile
import sqlite3
import threading
from pathlib import Path
from datetime import datetime, timezone
from typing import Any
from contextlib import contextmanager

import bcrypt
import httpx
import socketio
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

# Load environment before importing modules that read provider configuration.
load_dotenv()

from audio_transcriber import transcribe_audio
from evidence_recorder import save_evidence, list_evidence as list_saved_evidence, EVIDENCE_DIR as RECORDER_EVIDENCE_DIR, create_metadata
from emergency_dispatcher import dispatch_full_emergency, dispatch_live_location, EMERGENCY_EMAIL, EMERGENCY_PHONE
from webrtc_signaling import setup_webrtc_signaling
from orchestrator import set_nearest_police_provider
from voice_agent import (
    agent_states, get_state, set_state, start_monitoring as agent_start_monitoring,
    stop_monitoring as agent_stop_monitoring, process_transcript,
    execute_emergency_protocol, cancel_intercept, resolve_emergency, cleanup_agent,
    find_distress_keywords,
)

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("sakhi-sahayak")

BASE_DIR = Path(__file__).resolve().parent
SAFETY_DATA_FILE = Path(os.getenv("SAFETY_DATA_FILE", str(BASE_DIR / "safety_data.json")))
EVIDENCE_DIR = Path(os.getenv("EVIDENCE_DIR", str(BASE_DIR / "evidence")))
EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
DATABASE_FILE = Path(os.getenv("DATABASE_FILE", str(BASE_DIR / "sakhi_sahayak.db"))).resolve()
PORT = int(os.getenv("PORT", "5001"))
MAX_UPLOAD_BYTES = 50 * 1024 * 1024

# Socket.IO ASGI integration lets existing Socket.IO clients continue to connect.
sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*", max_http_buffer_size=10 * 1024 * 1024)
api = FastAPI(title="Sakhi-Sahayak API", version="1.0.0")
api.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])
app = socketio.ASGIApp(sio, other_asgi_app=api)

live_tracking_data: dict[str, dict[str, Any]] = {}
# agent_states is the same dictionary owned by voice_agent.py, so HTTP and
# Socket.IO paths cannot drift into separate state machines.
setup_webrtc_signaling(sio)


def load_safety_data() -> dict[str, Any]:
    try:
        with SAFETY_DATA_FILE.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        logger.exception("Could not load safety data from %s", SAFETY_DATA_FILE)
        return {"danger_zones": [], "police_stations": [], "hospitals": [], "metro_stations": []}


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    radius = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))


def distance_text(km: float) -> str:
    return f"{km:.1f} km" if km > 1 else f"{km * 1000:.0f} m"


def nearest_from_list(items: list[dict[str, Any]], lat: float, lng: float) -> dict[str, Any] | None:
    nearest = None
    best = float("inf")
    for item in items:
        try:
            item_lat = item.get("lat")
            item_lng = item.get("lng")
            if item_lat is None or item_lng is None:
                center = item.get("center")
                if isinstance(center, list) and len(center) >= 2:
                    item_lat, item_lng = center[0], center[1]
            if item_lat is None or item_lng is None:
                continue
            dist = haversine_km(lat, lng, float(item_lat), float(item_lng))
            if dist < best:
                best = dist
                nearest = {**item, "distance": dist, "distanceText": distance_text(dist)}
        except (TypeError, ValueError):
            continue
    return nearest


@contextmanager
def get_db():
    """Yield a short-lived SQLite connection and always close it after use."""
    conn = sqlite3.connect(DATABASE_FILE, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """Create the local database and tables if they do not exist."""
    DATABASE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with get_db() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            phone TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            emergency_name TEXT,
            emergency_phone TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS police_stations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            phone TEXT,
            email TEXT,
            zone TEXT,
            officer_in_charge TEXT,
            type TEXT,
            category TEXT DEFAULT 'station',
            lat REAL NOT NULL,
            lng REAL NOT NULL,
            address TEXT,
            description TEXT
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_police_stations_category ON police_stations(category)")


def get_station_rows() -> list[dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute("""SELECT id, name, phone, email, zone,
            officer_in_charge AS officerInCharge, type, category, lat, lng,
            address, description FROM police_stations WHERE category = 'station'""").fetchall()
    if rows:
        return [dict(row) for row in rows]
    # Keep the existing JSON data usable until stations are imported into SQLite.
    return load_safety_data().get("police_stations", [])


# The orchestrator and voice agent use the same local SQLite station catalogue as
# the existing frontend routes, with safety_data.json as a fallback.
set_nearest_police_provider(
    lambda lat, lng: nearest_from_list(get_station_rows(), lat, lng)
    or nearest_from_list(load_safety_data().get("police_stations", []), lat, lng)
)


@api.on_event("startup")
async def startup() -> None:
    try:
        init_db()
        logger.info("Using local SQLite database: %s", DATABASE_FILE)
    except Exception:
        logger.exception("Could not initialize local SQLite database")
        raise


@api.on_event("shutdown")
async def shutdown() -> None:
    # SQLite connections are opened per operation and closed automatically.
    return None


@api.get("/")
async def root():
    return {"service": "Sakhi-Sahayak", "status": "running", "database": "sqlite", "database_file": str(DATABASE_FILE)}


@api.get("/health")
async def health():
    try:
        with get_db() as conn:
            conn.execute("SELECT 1").fetchone()
        return {"ok": True, "sqlite": True, "database_file": str(DATABASE_FILE)}
    except Exception:
        logger.exception("SQLite health check failed")
        return {"ok": False, "sqlite": False}


@api.post("/api/signup")
async def signup(payload: dict[str, Any]):
    name = str(payload.get("userName", "")).strip()
    phone = str(payload.get("userPhone", "")).strip()
    password = str(payload.get("userPassword", ""))
    emergency_name = str(payload.get("emergencyName", "")).strip() or None
    emergency_phone = str(payload.get("emergencyPhone", "")).strip() or None
    if not name or not phone or not password:
        raise HTTPException(400, "Name, phone, and password are required.")
    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    try:
        with get_db() as conn:
            cursor = conn.execute("""INSERT INTO users(name, phone, password, emergency_name, emergency_phone)
                VALUES(?, ?, ?, ?, ?)""", (name, phone, hashed, emergency_name, emergency_phone))
            user_id = cursor.lastrowid
            row = conn.execute("""SELECT id, name, phone, emergency_name, emergency_phone
                FROM users WHERE id = ?""", (user_id,)).fetchone()
        return {"success": True, "user": dict(row), "msg": "Signup successful!"}
    except sqlite3.IntegrityError:
        raise HTTPException(409, "User already exists! Please login.")
    except sqlite3.Error:
        logger.exception("SQLite signup failed")
        raise HTTPException(500, "Signup failed.")


@api.post("/api/login")
async def login(payload: dict[str, Any]):
    phone = str(payload.get("userPhone", "")).strip()
    password = str(payload.get("userPassword", ""))
    if not phone or not password:
        raise HTTPException(400, "Phone and password are required.")
    with get_db() as conn:
        row = conn.execute("""SELECT id, name, phone, password, emergency_name, emergency_phone
            FROM users WHERE phone = ?""", (phone,)).fetchone()
    if not row or not bcrypt.checkpw(password.encode(), row["password"].encode()):
        raise HTTPException(401, "Invalid phone number or password.")
    user = dict(row)
    user.pop("password", None)
    return {"success": True, "user": user, "msg": "Login successful!"}


@api.get("/api/danger-zones")
async def danger_zones():
    return load_safety_data().get("danger_zones", [])


@api.get("/api/metro-routes")
async def get_metro_routes():
    """Fetch Nagpur Metro route geometry through the backend."""
    query = """
    [out:json][timeout:25];
    (
      relation(9571557);
      relation(10659365);
    );
    out geom;
    """

    endpoints = [
        "https://overpass-api.de/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter",
    ]

    last_error = None

    async with httpx.AsyncClient(
        timeout=30.0,
        follow_redirects=True,
        headers={"User-Agent": "Sakhi-Sahayak/1.0"},
    ) as client:
        for endpoint in endpoints:
            try:
                response = await client.post(
                    endpoint,
                    data={"data": query},
                )
                response.raise_for_status()

                result = response.json()

                if not isinstance(result.get("elements"), list):
                    raise ValueError("Invalid Overpass response")

                return result

            except (httpx.HTTPError, ValueError) as exc:
                last_error = exc
                logger.warning(
                    "Metro route request failed for %s: %s",
                    endpoint,
                    exc,
                )

    raise HTTPException(
        status_code=502,
        detail="Metro route data is temporarily unavailable.",
    )


@api.get("/api/safety-data")
async def safety_data():
    """Return all geospatial layers for the frontend map (zones, services, and POIs)."""
    return load_safety_data()


@api.get("/api/safety-metrics")
async def safety_metrics():
    """Return reproducible dataset/cluster counts for the dashboard and project evaluation."""
    data = load_safety_data()
    metadata = data.get("metadata", {})
    category_keys = (
        "police_stations", "hospitals", "danger_zones", "metro_stations",
        "black_spots", "tactical_units", "safe_zones", "moderate_zones",
        "risk_zones", "hostels_pgs", "educational_institutions", "corporate_areas",
        "other_points",
    )
    counts = {key: len(data.get(key, [])) for key in category_keys}
    source_records = int(metadata.get("source_records", sum(
        counts.get(key, 0) for key in category_keys if key not in {"danger_zones"}
    )))
    geocoded = int(metadata.get("records_with_valid_coordinates", source_records))
    return {
        "success": True,
        "source_records": source_records,
        "records_with_valid_coordinates": geocoded,
        "coordinate_coverage_percent": round(100 * geocoded / source_records, 2) if source_records else 0.0,
        "source_category_count": len(metadata.get("category_counts", {})),
        "category_counts": metadata.get("category_counts", counts),
        "map_layer_counts": counts,
        "danger_zone_clusters": len(data.get("danger_zones", [])),
        "generated_at": metadata.get("generated_at"),
        "source_file": metadata.get("source_file"),
        "model_evaluation_note": (
            "These are dataset and clustering coverage metrics, not predictive accuracy. "
            "Accuracy/precision/recall require independently labeled ground-truth outcomes."
        ),
    }


@api.post("/api/safety-data/regenerate")
async def regenerate_safety_data():
    """Regenerate map layers from MachineLearning/maharashtra_crime_data.xlsx."""
    try:
        from MachineLearning.kde_heatmap_generator import generate_safety_data
        result = await asyncio.to_thread(
            generate_safety_data,
            BASE_DIR / "MachineLearning" / "maharashtra_crime_data.xlsx",
            SAFETY_DATA_FILE,
        )
        return {
            "success": True,
            "source_records": result.get("metadata", {}).get("source_records", 0),
            "danger_zone_clusters": len(result.get("danger_zones", [])),
            "safety_data": result,
        }
    except Exception as exc:
        logger.exception("Safety data generation failed")
        raise HTTPException(500, f"Could not regenerate safety data: {exc}")


_route_planner = None
_route_planner_lock = threading.Lock()


def get_route_planner():
    """Lazily create one reusable planner; graph download/cache work happens only on first route request."""
    global _route_planner
    if _route_planner is not None:
        return _route_planner
    with _route_planner_lock:
        if _route_planner is not None:
            return _route_planner
        try:
            from MachineLearning.safe_pathfinder import EnhancedSafeRoutePlanner
        except ImportError as exc:
            raise RuntimeError(
                "Safe-route dependencies are missing. Install the requirements listed in "
                "requirements-backend-fixed.txt, including osmnx, networkx, shapely and folium."
            ) from exc
        location_name = os.getenv("ROUTE_LOCATION_NAME", "Nagpur, Maharashtra, India")
        graph_cache = Path(os.getenv("ROUTE_GRAPH_CACHE", str(BASE_DIR / "road_network.graphml")))
        graph_cache.parent.mkdir(parents=True, exist_ok=True)
        _route_planner = EnhancedSafeRoutePlanner(
            location_name=location_name,
            safety_data_path=str(SAFETY_DATA_FILE),
            cache_graph=True,
            graph_cache_path=str(graph_cache),
        )
        return _route_planner


def _route_coordinates(route_result):
    """Convert the route's edge geometries into frontend [lat, lng] and GeoJSON [lng, lat] arrays."""
    lat_lng = []
    segments = []
    for edge in route_result.get("route_stats", {}).get("edges", []):
        geometry = edge.get("geometry")
        if geometry is None:
            continue
        try:
            coords = list(geometry.coords)
        except (AttributeError, TypeError):
            continue
        segment_lat_lng = [[float(y), float(x)] for x, y, *_ in coords]
        if lat_lng and segment_lat_lng and lat_lng[-1] == segment_lat_lng[0]:
            lat_lng.extend(segment_lat_lng[1:])
        else:
            lat_lng.extend(segment_lat_lng)
        segments.append({
            "coordinates": segment_lat_lng,
            "risk_score": round(float(edge.get("risk_score", 0)), 4),
            "safety_multiplier": round(float(edge.get("safety_multiplier", 1)), 4),
            "distance_meters": round(float(edge.get("distance", 0)), 2),
        })
    return lat_lng, segments


@api.get("/api/safe-route/health")
async def safe_route_health():
    """Lightweight readiness check; does not download the road graph."""
    try:
        import importlib.util
        missing = [name for name in ("osmnx", "networkx", "shapely", "folium", "sklearn", "numpy")
                   if importlib.util.find_spec(name) is None]
        return {
            "success": True,
            "ready": not missing,
            "planner_initialized": _route_planner is not None,
            "missing_dependencies": missing,
            "location_name": os.getenv("ROUTE_LOCATION_NAME", "Nagpur, Maharashtra, India"),
            "safety_data_exists": SAFETY_DATA_FILE.exists(),
            "graph_cache_exists": Path(os.getenv("ROUTE_GRAPH_CACHE", str(BASE_DIR / "road_network.graphml"))).exists(),
        }
    except Exception as exc:
        return {"success": False, "ready": False, "error": str(exc)}


@api.post("/api/safe-route")
async def safe_route(payload: dict[str, Any]):
    """Find a road-network route weighted by danger zones and proximity to support services.

    Request JSON:
      {"start":{"lat":21.1458,"lng":79.0882},
       "end":{"lat":21.1200,"lng":79.0500},
       "optimization":"safest"}
    Optimization can be safest, balanced, or shortest. `compareModes` optionally
    calculates alternative-route tradeoffs for real measured route metrics.
    """
    def parse_point(value, prefix):
        if isinstance(value, dict):
            lat_value, lng_value = value.get("lat"), value.get("lng", value.get("lon"))
        else:
            lat_value, lng_value = payload.get(prefix + "Lat"), payload.get(prefix + "Lng")
        try:
            lat_value, lng_value = float(lat_value), float(lng_value)
        except (TypeError, ValueError):
            raise HTTPException(400, f"Provide {prefix}.lat and {prefix}.lng as numbers.")
        if not (math.isfinite(lat_value) and math.isfinite(lng_value)
                and -90 <= lat_value <= 90 and -180 <= lng_value <= 180):
            raise HTTPException(400, f"Invalid coordinates for {prefix}.")
        return lat_value, lng_value

    start = parse_point(payload.get("start"), "start")
    end = parse_point(payload.get("end"), "end")
    optimization = str(payload.get("optimization", "safest")).lower()
    if optimization not in {"safest", "balanced", "shortest"}:
        raise HTTPException(400, "optimization must be safest, balanced, or shortest.")

    try:
        planner = await asyncio.to_thread(get_route_planner)
        result = await asyncio.to_thread(
            planner.find_safe_route, start[0], start[1], end[0], end[1], optimization
        )
        if not result.get("found"):
            return {"success": False, "found": False, "error": result.get("error", "No route found")}
        stats = result.get("route_stats", {})
        coordinates, segments = _route_coordinates(result)
        avg_risk = float(stats.get("average_risk_score", 0.0))
        response = {
            "success": True,
            "found": True,
            "optimization": optimization,
            "start": {"lat": start[0], "lng": start[1]},
            "end": {"lat": end[0], "lng": end[1]},
            "route": coordinates,
            "coordinates_format": "[latitude, longitude]",
            "geojson": {"type": "LineString", "coordinates": [[lng, lat] for lat, lng in coordinates]},
            "segments": segments,
            "route_stats": {
                "total_distance_meters": round(float(stats.get("total_distance_meters", 0)), 2),
                "total_distance_km": round(float(stats.get("total_distance_km", 0)), 3),
                "average_risk_score": round(avg_risk, 4),
                "model_based_safety_score": round(max(0.0, min(100.0, (1 - avg_risk) * 100)), 1),
                "average_safety_multiplier": round(float(stats.get("average_safety_multiplier", 1)), 4),
                "num_edges": int(stats.get("num_edges", len(segments))),
                "total_police_bonus": round(float(stats.get("total_police_bonus", 0)), 3),
                "total_hospital_bonus": round(float(stats.get("total_hospital_bonus", 0)), 3),
            },
            "safety_data_metadata": load_safety_data().get("metadata", {}),
            "safety_score_note": (
                "The safety score is a heuristic derived from supplied risk-zone data and route-edge weights; "
                "it is not a guarantee of real-world safety or a validated crime probability."
            ),
        }
        if payload.get("compareModes") is True:
            comparisons = {}
            for mode in ("safest", "balanced", "shortest"):
                alt = result if mode == optimization else await asyncio.to_thread(
                    planner.find_safe_route, start[0], start[1], end[0], end[1], mode
                )
                if alt.get("found"):
                    alt_stats = alt.get("route_stats", {})
                    comparisons[mode] = {
                        "distance_km": round(float(alt_stats.get("total_distance_km", 0)), 3),
                        "average_risk_score": round(float(alt_stats.get("average_risk_score", 0)), 4),
                        "model_based_safety_score": round(
                            max(0.0, min(100.0, (1 - float(alt_stats.get("average_risk_score", 0))) * 100)), 1
                        ),
                    }
            response["route_comparison"] = comparisons
            shortest = comparisons.get("shortest")
            safest = comparisons.get("safest")
            if shortest and safest:
                response["route_comparison"]["safest_vs_shortest"] = {
                    "distance_increase_percent": round(
                        (safest["distance_km"] - shortest["distance_km"]) / shortest["distance_km"] * 100, 2
                    ) if shortest["distance_km"] else None,
                    "risk_reduction_percent": round(
                        (shortest["average_risk_score"] - safest["average_risk_score"])
                        / shortest["average_risk_score"] * 100, 2
                    ) if shortest["average_risk_score"] else None,
                }
        return response
    except HTTPException:
        raise
    except RuntimeError as exc:
        logger.exception("Safe-route planner is not ready")
        raise HTTPException(503, str(exc))
    except Exception as exc:
        logger.exception("Safe-route calculation failed")
        raise HTTPException(500, f"Safe-route calculation failed: {exc}")


@api.get("/api/nearest")
async def nearest(lat: float, lng: float):
    data = load_safety_data()
    return {
        "police_station": nearest_from_list(data.get("police_stations", []), lat, lng),
        "hospital": nearest_from_list(data.get("hospitals", []), lat, lng),
        "metro": nearest_from_list(data.get("metro_stations", []), lat, lng),
        "danger_zone": nearest_from_list(data.get("danger_zones", []), lat, lng),
    }


@api.get("/api/sos-nearest-station")
async def sos_nearest_station(lat: float, lng: float):
    station = nearest_from_list(get_station_rows(), lat, lng)
    source = "sqlite"
    if station is None:
        station = nearest_from_list(load_safety_data().get("police_stations", []), lat, lng)
        source = "json_fallback"
    if station is None:
        raise HTTPException(404, "No police stations found nearby")
    return {"success": True, "source": source, "station": station,
            "userLocation": {"lat": lat, "lng": lng,
             "googleMapsLink": f"https://maps.google.com/maps?q={lat},{lng}",
             "timestamp": datetime.now(timezone.utc).isoformat()}}


@api.get("/api/police-stations")
async def police_stations():
    try:
        stations = get_station_rows()
        return {"success": True, "count": len(stations), "stations": stations}
    except Exception:
        logger.exception("Police station query failed")
        raise HTTPException(500, "Failed to load police stations")


@api.post("/api/transcribe")
async def transcribe(
    audio: UploadFile = File(...),
    socketId: str | None = Form(default=None),
    userName: str | None = Form(default=None),
    userPhone: str | None = Form(default=None),
    lat: float | None = Form(default=None),
    lng: float | None = Form(default=None),
    audioMode: str | None = Form(default=None),
):
    """Transcribe uploaded audio, then optionally pass the transcript to voice_agent.

    Existing clients may keep calling this route with only `audio`. Clients that
    want the complete live safety workflow should also send their Socket.IO `socketId`.
    Alternatively, they can call this route and emit `voice-transcript` with the
    returned transcript, but must not do both for the same recording.
    """
    contents = await audio.read()
    if not contents:
        raise HTTPException(400, "No audio file provided")
    if len(contents) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Audio file is too large")
    suffix = Path(audio.filename or "audio.webm").suffix or ".webm"
    tmp_name = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(contents)
            tmp_name = tmp.name
        try:
            transcript, language, transcription_provider = await transcribe_audio(
                contents=contents,
                suffix=suffix,
                tmp_name=tmp_name,
                prefer_audio_understanding=(str(audioMode or "").lower() == "sarthi"),
            )
        except RuntimeError as exc:
            logger.exception("All audio transcription providers failed")
            raise HTTPException(502, f"Audio transcription failed: {exc}") from exc

        transcript = transcript.strip()
        language = str(language or "unknown").lower()
        if not transcript:
            return {"success": True, "transcript": "", "language": language,
                    "transcription_provider": transcription_provider,
                    "isSupported": language.startswith(("hi", "mr", "en")),
                    "distress_detected": False, "keywords_found": [],
                    "analysis": {"action": "no_action", "summary": "No speech was recognized."}}

        location = {"lat": lat, "lng": lng} if lat is not None and lng is not None else None
        analysis = None
        if socketId:
            state = get_state(socketId)
            user_data = {"name": userName, "phone": userPhone, "location": location}
            if state.get("status") in {"IDLE", "RESOLVED"}:
                await agent_start_monitoring(socketId, sio, user_data)
            elif state.get("status") == "MONITORING":
                set_state(socketId, {
                    "userName": userName or state.get("userName"),
                    "userPhone": userPhone or state.get("userPhone"),
                    "currentLocation": location or state.get("currentLocation"),
                })
            else:
                raise HTTPException(409, f"Voice agent is currently {state.get('status')}; transcript was not processed.")
            await process_transcript(socketId, transcript, location, sio)
            state = get_state(socketId)
            analysis = {"action": "trigger_emergency_alert" if state.get("trackingId") else "no_action",
                        "summary": "Transcript forwarded to voice safety agent.",
                        "langGraphState": state.get("status"), "trackingId": state.get("trackingId")}

        found = find_distress_keywords(transcript)
        llm_or_agent_threat = bool(analysis and analysis.get("action") == "trigger_emergency_alert")
        return {
            "success": True,
            "transcript": transcript,
            "language": language,
            "transcription_provider": transcription_provider,
            "isSupported": language.startswith(("hi", "mr", "en")),
            "distress_detected": bool(found) or llm_or_agent_threat,
            "keywords_found": found,
            "analysis": analysis,
        }
    finally:
        if tmp_name:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass


_whisper_model = None


@api.post("/api/upload-evidence")
async def upload_evidence(evidence: UploadFile = File(...), trackingId: str = Form("UNKNOWN")):
    data = await evidence.read()
    if not data:
        raise HTTPException(400, "No evidence file provided")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Evidence file is too large")
    safe_tracking = "".join(c for c in trackingId if c.isalnum() or c in "-_:")[:100] or "UNKNOWN"
    suffix = Path(evidence.filename or "evidence.webm").suffix or ".webm"
    target = EVIDENCE_DIR / f"{safe_tracking}_{uuid.uuid4().hex}{suffix}"
    target.write_bytes(data)
    return {"success": True, "trackingId": safe_tracking, "filename": target.name, "url": f"/evidence/{target.name}"}


@api.get("/api/evidence/{tracking_id}")
async def list_evidence(tracking_id: str):
    files = [p.name for p in EVIDENCE_DIR.glob(f"{tracking_id}_*") if p.is_file()]
    return {"success": True, "trackingId": tracking_id, "files": files}


@api.get("/evidence/{filename}")
async def get_evidence(filename: str):
    target = (EVIDENCE_DIR / filename).resolve()
    if target.parent != EVIDENCE_DIR.resolve() or not target.is_file():
        raise HTTPException(404, "Evidence not found")
    return FileResponse(target)


async def broadcast_emergency(sid: str, data: dict[str, Any]) -> dict[str, Any]:
    """Route a manual SOS through the same voice-agent emergency protocol."""
    data = data or {}
    state = get_state(sid)
    if state.get("status") in {"EMERGENCY_PROTOCOL", "RECORDING"}:
        await sio.emit("agent-state-update", {
            "status": state.get("status"), "trackingId": state.get("trackingId"),
            "message": "An emergency incident is already active; duplicate SOS was ignored.",
        }, to=sid)
        return {"trackingId": state.get("trackingId"), "status": state.get("status"), "duplicate": True}

    location = data.get("location") or state.get("currentLocation") or {}
    if not isinstance(location, dict):
        location = {}
    if data.get("lat") is not None:
        location = {**location, "lat": data.get("lat")}
    if data.get("lng") is not None:
        location = {**location, "lng": data.get("lng")}

    # Initialize the state first; start_monitoring resets incident-specific fields.
    if state.get("status") in {"IDLE", "RESOLVED"}:
        await agent_start_monitoring(sid, sio, {
            "name": data.get("userName") or state.get("userName"),
            "phone": data.get("userPhone") or state.get("userPhone"),
            "location": location,
        })
        state = get_state(sid)

    tracking_id = str(data.get("trackingId") or f"SOS-{uuid.uuid4().hex[:10].upper()}")
    set_state(sid, {
        "userName": data.get("userName") or state.get("userName"),
        "userPhone": data.get("userPhone") or state.get("userPhone"),
        "currentLocation": location,
        "threatTranscript": data.get("transcript") or "Manual SOS button pressed",
        "threatSeverity": data.get("severity") or "critical",
        "trackingId": tracking_id,
    })
    await execute_emergency_protocol(sid, sio)
    final_state = get_state(sid)
    return {"trackingId": final_state.get("trackingId"), "status": final_state.get("status")}


@sio.event
async def connect(sid, environ, auth=None):
    logger.info("Socket.IO client connected: %s", sid)
    get_state(sid)


@sio.on("location-update")
async def location_update(sid, data):
    data = data or {}
    live_tracking_data[sid] = data
    state = get_state(sid)
    location = data.get("location") if isinstance(data.get("location"), dict) else data
    if isinstance(location, dict) and (location.get("lat") is not None):
        set_state(sid, {"currentLocation": location})
    await sio.emit("family-dashboard-sync", live_tracking_data)
    state = get_state(sid)
    if state.get("status") in {"EMERGENCY_PROTOCOL", "RECORDING"} and state.get("trackingId"):
        await dispatch_live_location(sio, {"trackingId": state["trackingId"], **location,
                                           "userName": state.get("userName"), "userPhone": state.get("userPhone")})


@sio.on("start-monitoring")
async def socket_start_monitoring(sid, data=None):
    data = data or {}
    location = data.get("location")
    # The frontend may start monitoring when route guidance begins and again
    # when Sarthi is toggled. Do not reset an already-active state or log an
    # invalid MONITORING -> MONITORING transition.
    current_state = get_state(sid)
    if current_state.get("status") == "MONITORING":
        set_state(sid, {
            "userName": data.get("userName", data.get("name")) or current_state.get("userName"),
            "userPhone": data.get("userPhone", data.get("phone")) or current_state.get("userPhone"),
            "currentLocation": location or current_state.get("currentLocation"),
        })
        await sio.emit("agent-state-update", {
            "status": "MONITORING",
            "message": "Sarthi safety monitoring remains active.",
            "langGraphState": "MONITORING",
        }, to=sid)
        return
    if location is None and (data.get("lat") is not None or data.get("lng") is not None):
        location = {"lat": data.get("lat"), "lng": data.get("lng")}
    await agent_start_monitoring(sid, sio, {
        "name": data.get("userName", data.get("name")),
        "phone": data.get("userPhone", data.get("phone")),
        "location": location,
    })


@sio.on("stop-monitoring")
async def socket_stop_monitoring(sid):
    await agent_stop_monitoring(sid, sio)


@sio.on("voice-transcript")
async def voice_transcript(sid, data):
    """Single transcript ingress: route all STT text through voice_agent."""
    data = data or {}
    transcript = str(data.get("transcript") or "").strip()
    if not transcript:
        await sio.emit("voice-analysis", {"distress": False, "action": "no_action",
                                           "error": "Empty transcript"}, to=sid)
        return
    state = get_state(sid)
    location = data.get("location")
    if location is None and (data.get("lat") is not None or data.get("lng") is not None):
        location = {"lat": data.get("lat"), "lng": data.get("lng")}
    if state.get("status") in {"IDLE", "RESOLVED"}:
        await agent_start_monitoring(sid, sio, {
            "name": data.get("userName", data.get("name")),
            "phone": data.get("userPhone", data.get("phone")),
            "location": location,
        })
    elif state.get("status") == "MONITORING":
        set_state(sid, {
            "userName": data.get("userName", data.get("name")) or state.get("userName"),
            "userPhone": data.get("userPhone", data.get("phone")) or state.get("userPhone"),
            "currentLocation": location or state.get("currentLocation"),
        })
    else:
        await sio.emit("voice-analysis", {
            "action": "ignored", "distress": False,
            "summary": f"Voice agent is currently {state.get('status')}.",
            "langGraphState": state.get("status"),
        }, to=sid)
        return
    await process_transcript(sid, transcript, location, sio)


@sio.on("trigger-sos")
async def trigger_sos(sid, data):
    await broadcast_emergency(sid, data or {})


@sio.on("safety-confirmed")
async def safety_confirmed(sid, data=None):
    state = get_state(sid)
    if state.get("status") in {"THREAT_DETECTED", "INTERCEPT_COUNTDOWN"}:
        await cancel_intercept(sid, sio)
    elif state.get("status") == "RECORDING":
        await resolve_emergency(sid, sio, "Safety confirmed by user")
    else:
        await sio.emit("agent-state-update", {"status": state.get("status", "IDLE"),
                                               "message": "Safety confirmation received."}, to=sid)


@sio.on("intercept-cancel")
async def intercept_cancel(sid, data=None):
    await cancel_intercept(sid, sio)


@sio.on("evidence-upload")
async def evidence_upload(sid, data):
    data = data or {}
    tracking_id = str(data.get("trackingId") or "UNKNOWN")
    audio_data = data.get("audioData")
    if not audio_data:
        return
    import base64
    try:
        raw = base64.b64decode(audio_data, validate=True)
    except Exception:
        logger.warning("Invalid evidence payload from %s", sid)
        return
    if len(raw) > MAX_UPLOAD_BYTES:
        return
    fmt = str(data.get("format") or "webm").lstrip(".")
    try:
        saved = save_evidence(tracking_id, raw, fmt)
    except Exception:
        logger.exception("Could not save uploaded evidence")
        await sio.emit("evidence-save-error", {"trackingId": tracking_id}, to=sid)
        return
    await sio.emit("evidence-saved", {"trackingId": tracking_id, **saved}, to=sid)


@sio.on("sarthi-mode-engaged")
async def sarthi_mode_engaged(sid, data=None):
    logger.info("Sarthi mode engaged by %s", sid)


@sio.event
async def disconnect(sid):
    live_tracking_data.pop(sid, None)
    await cleanup_agent(sid)
    await sio.emit("family-dashboard-sync", live_tracking_data)
    logger.info("Socket.IO client disconnected: %s", sid)


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, reload=True)
