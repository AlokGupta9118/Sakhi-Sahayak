# Sakhi-Sahayak frontend

Responsive React + Vite frontend for the Sakhi-Sahayak FastAPI/Socket.IO backend. The app uses the existing component structure and integrates authentication, safety-data layers, safety-weighted route planning, nearest support points, voice transcription, incident evidence, live location updates, and the family live view.

## Requirements

- Node.js 20.19+ (or a version supported by the installed Vite release)
- The Sakhi-Sahayak Python backend running on port `5001`
- Browser location permission for live GPS features
- Microphone permission and backend Whisper + FFmpeg setup for voice checks

## Run locally

```bash
npm install
cp .env.example .env
npm run dev
```

On Windows PowerShell, use `Copy-Item .env.example .env` instead of `cp` if needed.

Start the backend from its backend directory in a separate terminal:

```bash
pip install -r requirements-backend-integrated.txt
uvicorn main:app --host 0.0.0.0 --port 5001 --reload
```

If the backend bundle has the fixed requirements file under a different name, use that exact filename. The frontend defaults to `http://localhost:5001`; override `VITE_API_BASE_URL` and `VITE_SOCKET_URL` in `.env` if necessary. Restart Vite after changing `.env`.

## Frontend/backend integration

| Feature | Backend contract |
| --- | --- |
| Sign up / sign in | `POST /api/signup`, `POST /api/login` |
| Safety layers / cluster metrics | `GET /api/safety-data`, `GET /api/danger-zones`, `GET /api/safety-metrics` |
| Rebuild generated layers | `POST /api/safety-data/regenerate` |
| Route planner diagnostics / routes | `GET /api/safe-route/health`, `POST /api/safe-route` |
| Nearest support | `GET /api/nearest`, `GET /api/sos-nearest-station`, `GET /api/police-stations` |
| Voice check | `POST /api/transcribe` with `audio`, `socketId`, user details and GPS coordinates |
| Incident evidence | `POST /api/upload-evidence`, `GET /api/evidence/{tracking_id}`, `GET /evidence/{filename}` |
| Live monitoring | Socket.IO `location-update`, `start-monitoring`, `stop-monitoring`, `sarthi-mode-engaged` |
| SOS / voice agent | Socket.IO `trigger-sos`, `voice-analysis`, `agent-state-update`, `safety-confirmed`, `intercept-cancel` |
| Evidence and family view | Socket.IO `evidence-upload`, `evidence-saved`, `family-dashboard-sync`, `emergency-broadcast-sent` |

Voice recording is user-started and limited to a short clip. When the voice agent flags an incident and returns a tracking ID, the clip is forwarded through the `evidence-upload` socket event. Do not also emit `voice-transcript` for that same clip: `/api/transcribe` already hands the transcript to the voice agent when `socketId` is supplied.

## Notes and known limitations

- Route calculation is performed by the backend's OSMnx/NetworkX safety-weighted planner, not by a client-side OSRM approximation. The first route request may download and cache the road graph, and needs backend internet access.
- Geocoding for place-name inputs uses OpenStreetMap Nominatim. Coordinate input (`latitude, longitude`) is available as a fallback.
- The route score is a heuristic based on supplied risk data; it is not a validated crime probability or a guarantee of safety. Dataset counts and coordinate coverage are not model-accuracy metrics.
- The current backend's `family-dashboard-sync` broadcasts the live-tracking dictionary to connected sockets and does not implement account-linked family pairing or server-side authorization. Treat the family live view as a development/demo feature until backend authorization and trusted-contact pairing are added; a frontend route guard alone is not a security boundary.
- Account updates, contact CRUD, and companion matching are not exposed by the current backend, so the UI does not pretend those features are persisted or live.
- A successful frontend lint/static parse does not prove provider dispatch, Whisper inference, real browser microphone permission, or live Socket.IO behavior. Test those with the backend configured in your own environment before relying on this for safety-critical use.

## Quality checks

```bash
npm run lint
npm run build
```
