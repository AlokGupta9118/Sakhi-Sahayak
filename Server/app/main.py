import os
import json
import tempfile
import logging

# ── Make ffmpeg available to Whisper ──
# ffmpeg.exe is placed in this directory (copied from imageio-ffmpeg)
APP_DIR = os.path.dirname(os.path.abspath(__file__))
os.environ["PATH"] = APP_DIR + os.pathsep + os.environ.get("PATH", "")

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import whisper

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Load Whisper model on startup (uses GPU if available) ──
logger.info("Loading Whisper 'base' model (first run downloads ~150MB)...")
model = whisper.load_model("base")
logger.info("✅ Whisper model loaded successfully!")

# ── Distress keywords (Hindi + English) ──
DISTRESS_KEYWORDS = [
    # English
    "help", "help me", "save me", "stop", "leave me", "let me go",
    "please stop", "don't touch", "somebody help", "emergency",
    # Hindi / Hinglish
    "bachao", "bachao mujhe", "chhodo", "chhod do", "ruko",
    "mat karo", "dur raho", "police", "koi bachao", "madad",
    "madad karo", "jane do", "hatiye", "shaamaat"
]

app = FastAPI(title="Sakhi-Sahayak Whisper AI", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def home():
    return {"message": "Sakhi-Sahayak Whisper AI Pipeline is active.", "model": "base"}


@app.get("/api/danger-zones")
def get_danger_zones():
    zone_path = os.path.join(os.path.dirname(__file__), '../danger_zones.json')
    if os.path.exists(zone_path):
        with open(zone_path, 'r') as f:
            return json.load(f)
    return []


@app.post("/api/transcribe")
async def transcribe_audio(audio: UploadFile = File(...)):
    """
    Accepts a WAV/WebM audio file, transcribes it with Whisper,
    and checks for distress keywords.
    """
    if not audio.filename:
        raise HTTPException(status_code=400, detail="No audio file provided")

    # Save uploaded audio to a temp file
    suffix = ".wav" if "wav" in (audio.content_type or "") else ".webm"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = await audio.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        logger.info(f"Transcribing audio file: {tmp_path} ({len(content)} bytes)")

        # Run Whisper transcription
        result = model.transcribe(tmp_path)
        transcript = result.get("text", "").strip()
        language = result.get("language", "unknown")

        logger.info(f"Transcript: '{transcript}' (Language: {language})")

        # Check for distress keywords
        transcript_lower = transcript.lower()
        keywords_found = [kw for kw in DISTRESS_KEYWORDS if kw in transcript_lower]
        distress_detected = len(keywords_found) > 0

        if distress_detected:
            logger.warning(f"🚨 DISTRESS DETECTED! Keywords: {keywords_found}")

        return {
            "success": True,
            "transcript": transcript,
            "language": language,
            "distress_detected": distress_detected,
            "keywords_found": keywords_found
        }

    except Exception as e:
        logger.error(f"Transcription error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        # Clean up temp file
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
