# Sakhi-Sahayak

**AI-powered women's safety platform with real-time location monitoring and safe-route assistance.**

Sakhi-Sahayak is a safety-focused application designed to help users access route guidance, emergency-support information, and location-based safety features through a web interface.

## Key Features

- Safe-route planning using road-network data.
- Interactive maps and location-based safety information.
- Emergency-support and nearby-station discovery.
- SOS-related workflows and live location updates.
- Voice transcription and evidence-recording capabilities.
- Family live-view interface.
- Real-time communication using Socket.IO.

> Safety notice: Route scores and recommendations are estimates, not guarantees of safety. Do not rely on this application as a replacement for emergency services.

## Technology Stack

### Frontend
- React
- Vite
- TypeScript / JavaScript
- Tailwind CSS
- React Router
- React Leaflet

### Backend
- Python
- FastAPI
- Socket.IO
- SQLite
- NetworkX / OSMnx for road-network routing

## Repository Structure

- `Client/` — frontend application
- `Backend/` — backend application

The exact internal structure may evolve as the project develops.

## Getting Started

### Prerequisites

- Git
- Node.js and npm
- Python
- Internet connectivity for map data and supported external services

### 1. Clone the repository

```bash
git clone https://github.com/AlokGupta9118/Sakhi-Sahayak.git
cd Sakhi-Sahayak
```

### 2. Start the backend

Open a terminal:

```bash
cd Server_final
python -m venv .venv
```

Activate the virtual environment.

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

Install the dependencies:

```bash
pip install -r requirements-backend-integrated.txt
```

Configure the required environment variables using a local `.env` file, if the application supports them.

Start the API:

```bash
uvicorn main:app --host 127.0.0.1 --port 5001 --reload
```

Backend health check:

`http://127.0.0.1:5001/health`

API documentation:

`http://127.0.0.1:5001/docs`

### 3. Start the frontend

Open another terminal:

```bash
cd Client
npm install
```

Configure the frontend environment variables in the appropriate local `.env` file. For example:

```env
VITE_API_BASE_URL=http://localhost:5001
VITE_SOCKET_URL=http://localhost:5001
```

Start the development server:

```bash
npm run dev
```

Use the local URL printed by Vite.

> Check the existing project README and configuration files for the exact dependency filenames, environment variables, and ports before running these instructions. Some features may require additional system dependencies or external services.

## Configuration and Security

- Never commit API keys, passwords, tokens, or private environment files.
- Do not commit real user records, local databases, or private evidence.
- Protect location data and emergency-related information.
- Authenticate and authorize access to private APIs and live location streams before production use.
- Use HTTPS and secure deployment configuration.

## Current Limitations

- Route safety scores are heuristic estimates and should not be interpreted as verified guarantees.
- Routing coverage depends on the configured geographic region and available road-network data.
- Emergency delivery, voice transcription, and other integrations depend on their configuration and service availability.

## Future Improvements

- Stronger authentication and authorization.
- Secure family/contact pairing.
- Automated tests and continuous integration.
- Production-grade database and evidence storage.
- Improved observability and deployment documentation.

## License

No license has been specified yet. Add an appropriate license before permitting others to reuse or redistribute this project.

