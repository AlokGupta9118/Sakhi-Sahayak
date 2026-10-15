"""Run the safety-data generation pipeline from any working directory."""
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent


def run_complete_pipeline():
    print("Starting Sakhi-Sahayak safety analysis pipeline")
    print("=" * 60)
    try:
        from kde_heatmap_generator import generate_safety_data
        safety_file = Path(os.getenv("SAFETY_DATA_FILE", str(PROJECT_DIR / "safety_data.json")))
        generated = generate_safety_data(BASE_DIR / "maharashtra_crime_data.xlsx", safety_file)
        print(f"Generated {safety_file}")
        print(f"Source records: {generated['metadata']['source_records']}")
        print(f"Records with valid coordinates: {generated['metadata']['records_with_valid_coordinates']}")
        print(f"Danger-zone clusters: {len(generated['danger_zones'])}")
    except Exception as exc:
        print(f"Safety-data generation failed: {exc}")
        raise

    try:
        from safe_pathfinder import EnhancedSafeRoutePlanner
        planner = EnhancedSafeRoutePlanner(
            location_name=os.getenv("ROUTE_LOCATION_NAME", "Nagpur, Maharashtra, India"),
            safety_data_path=str(safety_file),
            cache_graph=True,
            graph_cache_path=os.getenv("ROUTE_GRAPH_CACHE", str(PROJECT_DIR / "road_network.graphml")),
        )
        print(f"Road graph loaded: {len(planner.G.nodes)} nodes, {len(planner.G.edges)} edges")
        print("Route planner ready for API requests.")
    except Exception as exc:
        print(f"Route planner initialization failed (check network/dependencies): {exc}")
        raise


if __name__ == "__main__":
    run_complete_pipeline()
