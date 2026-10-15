# Sakhi-Sahayak — integrated voice safety + geospatial route backend

## What's included

- `main.py`: preserves existing REST and Socket.IO endpoints and adds frontend APIs for safety layers, clustering metrics, and safety-weighted road routing.
- `voice_agent.py`, `orchestrator.py`, `emergency_dispatcher.py`, `evidence_recorder.py`, `send_email.py`, `webrtc_signaling.py`: the existing voice/SOS pipeline.
- `MachineLearning/maharashtra_crime_data.xlsx`: supplied geospatial dataset.
- `MachineLearning/kde_heatmap_generator.py`: converts the workbook into frontend-ready `safety_data.json` layers and DBSCAN risk clusters.
- `MachineLearning/safe_pathfinder.py`: OSMnx road graph + NetworkX route planning with edge weights influenced by risk zones, black spots, safe zones, police proximity, and hospital proximity.
- `safety_data.json`: generated map data for immediate frontend use.

## Install and run

Use Python 3.11 or 3.12 in a virtual environment, then:

```bash
pip install -r requirements-backend-integrated.txt
# Install FFmpeg separately if you use Whisper transcription.
python -m MachineLearning.kde_heatmap_generator
uvicorn main:app --host 0.0.0.0 --port 5001 --reload
```

The route planner is lazy-loaded on the first route request. It downloads the OpenStreetMap road graph for `ROUTE_LOCATION_NAME` (default: `Nagpur, Maharashtra, India`) and caches it in `road_network.graphml`. That first request requires internet access. Set `ROUTE_LOCATION_NAME` and `ROUTE_GRAPH_CACHE` in `.env` to change the area/cache. Existing APIs remain available.

## Frontend endpoints

### `GET /api/safety-data`
Returns map layers as JSON:
- `danger_zones`: clustered risk points with `center: [lat, lng]`, `radius`, `severity`, and cluster count.
- `black_spots`, `risk_zones`, `moderate_zones`, `safe_zones`.
- `police_stations`, `hospitals`, `metro_stations`, `tactical_units`.
- `hostels_pgs`, `educational_institutions`, `corporate_areas`.
- `metadata`: dataset size, category counts, generation timestamp, and data-quality caveat.

### `GET /api/danger-zones`
Returns only the danger-zone cluster list (preserved route).

### `GET /api/safety-metrics`
Returns reproducible data coverage metrics and counts. These are dataset/clustering metrics, not predictive model accuracy.

### `POST /api/safety-data/regenerate`
Rebuilds `safety_data.json` from the included workbook. Call after replacing/updating the workbook.

### `GET /api/safe-route/health`
Checks whether the route planner's Python dependencies and safety data are available without downloading the road graph.

### `POST /api/safe-route`
Request:
```json
{
  "start": {"lat": 21.1458, "lng": 79.0882},
  "end": {"lat": 21.1200, "lng": 79.0500},
  "optimization": "safest",
  "compareModes": true
}
```

`optimization` can be `safest`, `balanced`, or `shortest`. The response includes:
- `route`: `[[lat, lng], ...]` for Leaflet/Google Maps polyline rendering.
- `geojson`: standard GeoJSON `LineString` with `[lng, lat]` coordinates.
- `segments`: per-edge coordinates, risk score, safety multiplier, and distance.
- `route_stats`: distance, average modeled risk, model-based safety score, and support-service bonuses.
- `route_comparison` when `compareModes: true`: actual computed distance/risk metrics for safest, balanced, and shortest routes plus safest-vs-shortest tradeoffs.

Alternative flat request format is also accepted:
```json
{"startLat": 21.1458, "startLng": 79.0882,
 "endLat": 21.1200, "endLng": 79.0500, "optimization": "balanced"}
```

Example frontend fetch:
```javascript
const response = await fetch("http://localhost:5001/api/safe-route", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    start: { lat: userLat, lng: userLng },
    end: { lat: destinationLat, lng: destinationLng },
    optimization: "safest",
    compareModes: true
  })
});
const data = await response.json();
if (data.success && data.found) {
  // Leaflet: L.polyline(data.route, { color: "green" }).addTo(map)
  // GeoJSON consumers: data.geojson
}
```

## Existing voice/SOS flow

- `/api/transcribe` transcribes audio. Send `socketId` (and optional user/location fields) in the multipart request to forward the transcript to `voice_agent.py`.
- Alternatively, call `/api/transcribe`, then emit Socket.IO `voice-transcript` with the returned transcript. Do not use both methods for the same recording.
- Manual SOS event: `trigger-sos`; location updates: `location-update`.
- Emergency delivery integrations depend on the configured provider credentials.

## Environment variables

```env
OPENROUTER_API_KEY=...
OPENROUTER_MODEL=openai/gpt-4o-mini
EMERGENCY_EMAIL=...
EMERGENCY_PHONE=...
RESEND_API=...
DATABASE_FILE=./sakhi_sahayak.db
SAFETY_DATA_FILE=./safety_data.json
ROUTE_LOCATION_NAME=Nagpur, Maharashtra, India
ROUTE_GRAPH_CACHE=./road_network.graphml
EVIDENCE_DIR=./evidence
WHISPER_MODEL=base
```

Configure Twilio variables if SMS delivery uses Twilio. Keep credentials private.

## Current dataset metrics (computed from the supplied workbook)

- Source records parsed: **201**
- Records with valid latitude/longitude: **201/201 (100%)**
- Source categories: **9**
- DBSCAN risk clusters generated: **7**
- Individual black-spot points: **74**
- Police stations: **28**
- Metro stations: **38**
- Hospitals: **7**
- Educational institutions: **14**
- Hostels/PGs: **17**
- Corporate-area points: **8**
- Tactical units: **5**
- Labeled NMC risk zones: **10**

These values describe the provided dataset and the current preprocessing run, not general Maharashtra coverage. The dataset does not provide independent ground-truth labels for evaluating predictive accuracy, so do not claim accuracy/precision/recall or crime-prediction performance without a labeled test set. The route API computes route-specific distance/risk tradeoffs only after a route is requested. The safety score is a heuristic and does not guarantee a route is safe.

## Notes

- This system uses historical/curated points and a heuristic risk-weighted road graph; it is not a future-crime predictor.
- Do not label routes as guaranteed safe. Present them as model-ranked routes and allow users to choose another route.
- The route engine requires OpenStreetMap network access the first time it builds a graph for the configured area. A pre-existing GraphML cache can avoid that download.
