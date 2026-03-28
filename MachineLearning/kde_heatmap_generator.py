import numpy as np
import pandas as pd
import openpyxl
import csv
import io
import json
import logging
from sklearn.neighbors import KernelDensity
from sklearn.cluster import DBSCAN

logging.basicConfig(level=logging.INFO)

def process_excel(filename):
    logging.info(f"Processing Excel data from {filename}...")
    try:
        wb = openpyxl.load_workbook(filename)
        sheet = wb.active
        rows = [r[0] for r in sheet.iter_rows(values_only=True) if r[0]]
        
        final_data = []
        current_header = None
        
        for line in rows:
            if 'type,' in line or 'lat,lng' in line:
                current_header = [h.strip() for h in line.split(',')]
                continue
                
            if current_header:
                f = io.StringIO(line)
                reader = csv.reader(f)
                try:
                    values = next(reader)
                    item = {}
                    for i, val in enumerate(values):
                        if i < len(current_header):
                            key = current_header[i] if current_header[i] else f"field_{i}"
                            item[key] = val
                    final_data.append(item)
                except: continue
        return final_data
    except Exception as e:
        logging.error(f"Failed to process excel: {e}")
        return []

def generate_safety_data():
    raw_data = process_excel('maharashtra_crime_data.xlsx')
    if not raw_data: return

    # Categorize data
    categorized = {
        "police_stations": [],
        "hospitals": [],
        "danger_zones": [],
        "metro_stations": [],
        "black_spots": [],
        "tactical_units": [],
        "safe_zones": []
    }

    crime_coords = []
    
    for item in raw_data:
        try:
            item_type = item.get('type')
            lat = float(item.get('lat', 0))
            lng = float(item.get('lng', 0))
            if lat == 0 or lng == 0: continue
            
            clean_item = {
                "name": item.get('name', 'Unknown'),
                "lat": lat,
                "lng": lng,
                "description": item.get('description', ''),
                "contact": item.get('contact', item.get('phone', ''))
            }

            if item_type == 'police_station':
                categorized["police_stations"].append(clean_item)
            elif item_type == 'hospital':
                categorized["hospitals"].append(clean_item)
            elif item_type == 'metro_station':
                categorized["metro_stations"].append(clean_item)
            elif item_type == 'black_spot':
                categorized["black_spots"].append(clean_item)
                crime_coords.append([lat, lng])
            elif item_type == 'tactical_unit':
                categorized["tactical_units"].append(clean_item)
            elif item_type == 'nmc_zone':
                risk = item.get('risk_level', '').lower()
                clean_item["risk"] = risk
                if risk in ['high', 'critical', 'elevated']:
                    crime_coords.append([lat, lng])
                else: # Low/Safe
                    categorized["safe_zones"].append(clean_item)
        except: continue

    # KDE & DBSCAN for Danger Zones (Heatmap)
    if crime_coords:
        logging.info("Generating Danger Zones cluster via KDE/DBSCAN...")
        crime_array = np.array(crime_coords)
        scanner = DBSCAN(eps=0.015, min_samples=2, metric='haversine')
        labels = scanner.fit_predict(np.radians(crime_array))
        
        unique_labels = set(labels)
        for k in unique_labels:
            if k == -1: continue
            xy = crime_array[labels == k]
            centroid = np.mean(xy, axis=0)
            categorized["danger_zones"].append({
                "center": [centroid[0], centroid[1]],
                "radius": 800 if len(xy) > 5 else 500,
                "severity": "Critical" if len(xy) > 3 else "High",
                "incidents": len(xy)
            })

    # Save to Server folder
    with open('../Server/safety_data.json', 'w') as f:
        json.dump(categorized, f, indent=4)
    
    logging.info(f"Successfully processed {len(raw_data)} items and saved to ../Server/safety_data.json")

if __name__ == "__main__":
    generate_safety_data()
