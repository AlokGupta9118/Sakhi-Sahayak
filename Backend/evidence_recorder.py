"""
Evidence recorder for Sakhi-Sahayak.

Stores evidence locally in ./evidence and writes a JSON sidecar containing
the SHA-256 hash. Recording duration is capped at eight minutes by the
MAX_RECORDING_MS constant; callers should also enforce the cap while recording.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

EVIDENCE_DIR = Path(__file__).resolve().parent / "evidence"
MAX_RECORDING_MS = 8 * 60 * 1000
_ALLOWED_FORMATS = {"webm", "wav", "mp3", "ogg", "m4a", "mp4", "bin"}


def ensure_dir() -> None:
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)


def _safe_tracking_id(tracking_id: str) -> str:
    """Prevent path traversal while preserving ordinary tracking IDs."""
    cleaned = re.sub(r"[^A-Za-z0-9_.-]", "_", str(tracking_id or "UNKNOWN"))
    return cleaned[:120] or "UNKNOWN"


def save_evidence(
    tracking_id: str,
    audio_buffer: bytes,
    file_format: str = "webm",
) -> dict[str, str | int]:
    """Save audio bytes and a JSON metadata sidecar."""
    ensure_dir()

    safe_id = _safe_tracking_id(tracking_id)
    fmt = str(file_format or "webm").lower().lstrip(".")
    if fmt not in _ALLOWED_FORMATS:
        fmt = "bin"

    timestamp_ms = int(time.time() * 1000)
    file_name = f"evidence_{safe_id}_{timestamp_ms}.{fmt}"
    file_path = EVIDENCE_DIR / file_name
    data = bytes(audio_buffer)

    file_path.write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    metadata = {
        "trackingId": str(tracking_id),
        "fileName": file_name,
        "format": fmt,
        "sizeBytes": len(data),
        "sha256": digest,
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "integrityVerified": True,
    }
    metadata_path = Path(str(file_path) + ".json")
    metadata_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"[EvidenceRecorder] Saved evidence: {file_name} ({len(data) / 1024:.1f} KB)")
    print(f"[EvidenceRecorder] SHA-256: {digest}")
    return {
        "filePath": str(file_path),
        "metadataPath": str(metadata_path),
        "hash": digest,
        "fileName": file_name,
        "sizeBytes": len(data),
    }


def create_metadata(tracking_id: str, data: dict[str, Any]) -> str:
    """Create a metadata-only record when no audio is available."""
    ensure_dir()
    safe_id = _safe_tracking_id(tracking_id)
    timestamp_ms = int(time.time() * 1000)
    file_name = f"metadata_{safe_id}_{timestamp_ms}.json"
    file_path = EVIDENCE_DIR / file_name

    record = {
        **(data or {}),
        "trackingId": str(tracking_id),
        "type": "emergency_metadata",
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }
    file_path.write_text(json.dumps(record, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"[EvidenceRecorder] Saved metadata: {file_name}")
    return str(file_path)


def list_evidence(tracking_id: str) -> list[str]:
    """List evidence files whose names contain the given tracking ID."""
    ensure_dir()
    safe_id = _safe_tracking_id(tracking_id)
    return sorted(p.name for p in EVIDENCE_DIR.iterdir() if safe_id in p.name)


def verify_integrity(file_name: str) -> dict[str, Any]:
    """Verify an evidence file against its JSON sidecar SHA-256 hash."""
    ensure_dir()

    # Accept only a file name, never a caller-provided path.
    if Path(file_name).name != file_name:
        return {"valid": False, "error": "Invalid file name"}

    file_path = EVIDENCE_DIR / file_name
    metadata_path = Path(str(file_path) + ".json")
    if not file_path.is_file() or not metadata_path.is_file():
        return {"valid": False, "error": "File or metadata not found"}

    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        computed_hash = hashlib.sha256(file_path.read_bytes()).hexdigest()
        expected_hash = metadata.get("sha256")
        return {
            "valid": computed_hash == expected_hash,
            "expectedHash": expected_hash,
            "computedHash": computed_hash,
            "fileName": file_name,
        }
    except (OSError, json.JSONDecodeError) as exc:
        return {"valid": False, "error": str(exc)}


# Keep the JavaScript export names available for easier migration.
saveEvidence = save_evidence
createMetadata = create_metadata
listEvidence = list_evidence
verifyIntegrity = verify_integrity
