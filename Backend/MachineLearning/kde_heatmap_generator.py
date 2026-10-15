"""Generate frontend-ready safety layers from the supplied Maharashtra/Nagpur workbook.

The workbook currently stores comma-separated records in the first Excel column.
This parser supports that layout and ordinary multi-column Excel sheets.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import openpyxl
from sklearn.cluster import DBSCAN

logging.basicConfig(level=logging.INFO)
LOGGER = logging.getLogger(__name__)
BASE_DIR = Path(__file__).resolve().parent
DEFAULT_INPUT = BASE_DIR / "maharashtra_crime_data.xlsx"
DEFAULT_OUTPUT = Path(os.getenv("SAFETY_DATA_FILE", str(BASE_DIR.parent / "safety_data.json")))


def process_excel(filename):
    """Read either CSV-like single-cell rows or a normal tabular Excel sheet."""
    wb = openpyxl.load_workbook(filename, data_only=True, read_only=True)
    sheet = wb.active
    rows = list(sheet.iter_rows(values_only=True))
    wb.close()
    if not rows:
        return []

    first = next((str(row[0]).strip() for row in rows if row and row[0] is not None), "")
    # Current supplied workbook has the entire CSV record in column A.
    if "," in first and len([v for v in rows[0] if v is not None]) == 1:
        parsed = []
        for row in rows:
            if not row or row[0] is None:
                continue
            try:
                parsed.append(next(csv.reader([str(row[0])])))
            except (csv.Error, StopIteration):
                continue
        header = [str(v).strip() for v in parsed[0]]
        return [
            {header[i]: values[i].strip() if i < len(values) else ""
             for i in range(len(header))}
            for values in parsed[1:]
        ]

    headers = [str(v).strip() if v is not None else "" for v in rows[0]]
    output = []
    for row in rows[1:]:
        if not any(v is not None for v in row):
            continue
        output.append({
            headers[i] or f"field_{i}": row[i]
            for i in range(min(len(headers), len(row)))
        })
    return output


def _as_float(value):
    try:
        number = float(value)
        if not np.isfinite(number):
            return None
        return number
    except (TypeError, ValueError):
        return None


def generate_safety_data(input_path=DEFAULT_INPUT, output_path=DEFAULT_OUTPUT):
    raw_data = process_excel(input_path)
    if not raw_data:
        raise ValueError(f"No usable rows found in safety workbook: {input_path}")

    categorized = {
        "police_stations": [], "hospitals": [], "danger_zones": [],
        "metro_stations": [], "black_spots": [], "tactical_units": [],
        "safe_zones": [], "moderate_zones": [], "risk_zones": [],
        "hostels_pgs": [], "educational_institutions": [], "corporate_areas": [],
        "other_points": [],
    }
    risk_points = []
    type_counts = Counter()
    valid_coordinate_records = 0

    for item in raw_data:
        item_type = str(item.get("type", "")).strip().lower()
        type_counts[item_type or "unknown"] += 1
        lat = _as_float(item.get("lat"))
        lng = _as_float(item.get("lng"))
        if lat is None or lng is None or not (-90 <= lat <= 90) or not (-180 <= lng <= 180):
            continue
        valid_coordinate_records += 1
        risk = str(item.get("risk", item.get("risk_level", "")) or "").strip().lower()
        point = {
            "name": str(item.get("name") or "Unknown"),
            "lat": lat, "lng": lng,
            "description": str(item.get("description") or item.get("context") or ""),
            "contact": str(item.get("contact") or item.get("phone") or ""),
            "type": item_type,
        }
        if item_type == "police_station":
            point.update({"zone": item.get("zone", ""), "address": item.get("location", "")})
            categorized["police_stations"].append(point)
        elif item_type == "hospital":
            categorized["hospitals"].append(point)
        elif item_type == "metro_station":
            categorized["metro_stations"].append(point)
        elif item_type == "black_spot":
            categorized["black_spots"].append(point)
            risk_points.append((lat, lng, str(item.get("severity") or "High")))
        elif item_type == "tactical_unit":
            categorized["tactical_units"].append(point)
        elif item_type == "nmc_zone":
            point["risk"] = risk.title() if risk else "Unknown"
            categorized["risk_zones"].append(point)
            if risk in {"high", "critical", "elevated"}:
                risk_points.append((lat, lng, risk.title()))
            elif risk in {"low", "safe"}:
                categorized["safe_zones"].append(point)
            elif risk == "moderate":
                categorized["moderate_zones"].append(point)
        elif item_type == "hostel_pg":
            categorized["hostels_pgs"].append(point)
        elif item_type == "educational_institution":
            categorized["educational_institutions"].append(point)
        elif item_type == "mihan_corporate":
            categorized["corporate_areas"].append(point)
        else:
            categorized["other_points"].append(point)

    # DBSCAN uses haversine distance in radians. eps=0.015 radians is ~95 km,
    # which is too large for city-level clustering; use ~1.5 km for local clusters.
    if risk_points:
        coords_rad = np.radians(np.array([[p[0], p[1]] for p in risk_points], dtype=float))
        labels = DBSCAN(eps=0.015 / 60.0, min_samples=2, metric="haversine").fit_predict(coords_rad)
        for label in sorted(set(labels)):
            if label == -1:
                continue
            members = [risk_points[i] for i in range(len(risk_points)) if labels[i] == label]
            centroid_lat = float(np.mean([p[0] for p in members]))
            centroid_lng = float(np.mean([p[1] for p in members]))
            severity_order = {"critical": 3, "high": 2, "elevated": 2, "medium": 1}
            max_severity = max((p[2].lower() for p in members),
                               key=lambda s: severity_order.get(s, 0))
            categorized["danger_zones"].append({
                "center": [centroid_lat, centroid_lng],
                "lat": centroid_lat, "lng": centroid_lng,
                "radius": 800 if len(members) > 5 else 500,
                "severity": "Critical" if max_severity == "critical" else "High",
                "incidents": len(members),
                "source": "clustered_risk_points",
            })

    categorized["metadata"] = {
        "source_file": Path(input_path).name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_records": len(raw_data),
        "records_with_valid_coordinates": valid_coordinate_records,
        "category_counts": dict(type_counts),
        "danger_zone_clusters": len(categorized["danger_zones"]),
        "note": "Clusters are derived from the supplied black-spot and labeled high/critical risk-zone records; they are not a validated crime prediction.",
    }
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(categorized, indent=2), encoding="utf-8")
    LOGGER.info("Generated %s from %d source rows (%d geolocated, %d clusters)",
                output_path, len(raw_data), valid_coordinate_records, len(categorized["danger_zones"]))
    return categorized


if __name__ == "__main__":
    generate_safety_data()
