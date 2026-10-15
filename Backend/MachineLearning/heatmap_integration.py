"""Small manual integration smoke test for the safety map and route planner."""
import os
from pathlib import Path
from safe_pathfinder import EnhancedSafeRoutePlanner

BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent


def test_integration():
    planner = EnhancedSafeRoutePlanner(
        location_name=os.getenv("ROUTE_LOCATION_NAME", "Nagpur, Maharashtra, India"),
        safety_data_path=os.getenv("SAFETY_DATA_FILE", str(PROJECT_DIR / "safety_data.json")),
        cache_graph=True,
        graph_cache_path=os.getenv("ROUTE_GRAPH_CACHE", str(PROJECT_DIR / "road_network.graphml")),
    )
    print("Loaded layers:", {
        "danger_zones": len(planner.danger_zones),
        "safe_zones": len(planner.safe_zones),
        "police_stations": len(planner.police_stations),
        "hospitals": len(planner.hospitals),
        "black_spots": len(planner.black_spots),
    })
    route = planner.find_safe_route(21.1458, 79.0882, 21.1200, 79.0500, optimization="safest")
    if route.get("found"):
        print("Route stats:", {k: v for k, v in route["route_stats"].items() if k != "edges"})
        planner.visualize_route(route, str(PROJECT_DIR / "safest_route.html"))
    else:
        print("No route found:", route.get("error"))


if __name__ == "__main__":
    test_integration()
