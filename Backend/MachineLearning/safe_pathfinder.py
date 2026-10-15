"""Safety-weighted route planning using OSMnx, NetworkX and safety-data JSON.

Safety scores are heuristic indicators based on the supplied dataset; they are not
validated crime probabilities and cannot guarantee that a route is safe.
"""
import json
import logging
import math
import os
from pathlib import Path
from typing import Dict, List, Optional

import folium
import networkx as nx
import numpy as np
import osmnx as ox
from shapely.geometry import LineString, Point
from shapely.strtree import STRtree

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_SAFETY_DATA = Path(
    os.getenv("SAFETY_DATA_FILE", str(BASE_DIR.parent / "safety_data.json"))
)
DEFAULT_GRAPH_CACHE = Path(
    os.getenv("ROUTE_GRAPH_CACHE", str(BASE_DIR.parent / "road_network.graphml"))
)


class EnhancedSafeRoutePlanner:
    def __init__(
        self,
        location_name: str = "Nagpur, Maharashtra, India",
        safety_data_path: Optional[str] = None,
        cache_graph: bool = True,
        graph_cache_path: Optional[str] = None,
    ):
        self.location_name = location_name
        self.safety_data_path = str(safety_data_path or DEFAULT_SAFETY_DATA)
        self.graph_cache_path = Path(graph_cache_path or DEFAULT_GRAPH_CACHE)
        self.G = None
        self.safety_data: Dict = {}
        self.danger_zones: List[Dict] = []
        self.safe_zones: List[Dict] = []
        self.police_stations: List[Dict] = []
        self.hospitals: List[Dict] = []
        self.metro_stations: List[Dict] = []
        self.tactical_units: List[Dict] = []
        self.black_spots: List[Dict] = []
        self.danger_geometries: List[Dict] = []
        self.safe_geometries: List[Dict] = []
        self.danger_spatial_index = None

        if cache_graph:
            self._load_or_download_graph(str(self.graph_cache_path))
        else:
            self._load_road_network()

        self._load_safety_data()
        self._build_spatial_index()
        self._calculate_enhanced_edge_safety_scores()

    def _load_or_download_graph(self, cache_path: str) -> None:
        """Load a valid cache, or download and save a new graph."""
        path = Path(cache_path)
        if path.exists():
            try:
                self.G = ox.load_graphml(filepath=path)
                if self.G is not None and self.G.number_of_nodes():
                    logger.info(
                        "Loaded cached graph: %d nodes, %d edges",
                        self.G.number_of_nodes(), self.G.number_of_edges()
                    )
                    return
                logger.warning("Cached road graph is empty; rebuilding it.")
            except Exception:
                logger.exception("Cached graph is invalid; rebuilding it.")

        self._load_road_network()
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            ox.save_graphml(self.G, filepath=path)
            logger.info("Saved road graph cache to %s", path)
        except Exception:
            # Routing can still work for this process if cache saving fails.
            logger.exception("Could not save graph cache to %s", path)

    def _load_road_network(self) -> None:
        """Download a drivable road network using the installed OSMnx API."""
        logger.info("Downloading road network for %s...", self.location_name)
        try:
            # clean_periphery is not supported by newer OSMnx versions.
            self.G = ox.graph_from_place(
                self.location_name,
                network_type="drive",
                simplify=True,
                retain_all=False,
                truncate_by_edge=False,
            )
            if self.G is None or not self.G.number_of_nodes():
                raise RuntimeError(f"OSMnx returned an empty graph for {self.location_name!r}")

            for u, v, _key, data in self.G.edges(keys=True, data=True):
                if data.get("geometry") is None:
                    a, b = self.G.nodes[u], self.G.nodes[v]
                    data["geometry"] = LineString([(a["x"], a["y"]), (b["x"], b["y"])])
            logger.info("Downloaded graph: %d nodes, %d edges",
                        self.G.number_of_nodes(), self.G.number_of_edges())
        except Exception:
            logger.exception("Error downloading road network")
            raise

    def _load_safety_data(self) -> None:
        """Load map layers; missing data is allowed but logged."""
        path = Path(self.safety_data_path)
        try:
            with path.open("r", encoding="utf-8") as file:
                self.safety_data = json.load(file)
            if not isinstance(self.safety_data, dict):
                raise ValueError("Safety data JSON must have an object at its root.")

            for name in (
                "danger_zones", "safe_zones", "police_stations", "hospitals",
                "metro_stations", "tactical_units", "black_spots"
            ):
                value = self.safety_data.get(name, [])
                setattr(self, name, value if isinstance(value, list) else [])
            logger.info(
                "Safety data loaded: danger=%d, safe=%d, police=%d, hospitals=%d, black spots=%d",
                len(self.danger_zones), len(self.safe_zones), len(self.police_stations),
                len(self.hospitals), len(self.black_spots)
            )
        except FileNotFoundError:
            logger.warning("Safety data not found at %s; using road distance only.", path)
            self.safety_data = {}
        except (json.JSONDecodeError, ValueError):
            logger.exception("Invalid safety-data file: %s", path)
            raise

    @staticmethod
    def _valid_coordinates(lat, lng) -> bool:
        try:
            lat, lng = float(lat), float(lng)
            return math.isfinite(lat) and math.isfinite(lng) and -90 <= lat <= 90 and -180 <= lng <= 180
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _record_point(record):
        try:
            lat, lng = float(record["lat"]), float(record["lng"])
            if -90 <= lat <= 90 and -180 <= lng <= 180:
                return Point(lng, lat)
        except (KeyError, TypeError, ValueError):
            pass
        return None

    def _build_spatial_index(self) -> None:
        """Create approximate local buffers and an STRtree for danger zones."""
        self.danger_geometries = []
        self.safe_geometries = []
        self.danger_spatial_index = None

        for zone in self.danger_zones:
            try:
                center = zone["center"]  # expected format: [latitude, longitude]
                lat, lng = float(center[0]), float(center[1])
                if not self._valid_coordinates(lat, lng):
                    continue
                radius_m = max(0.0, float(zone.get("radius", 500) or 500))
                polygon = Point(lng, lat).buffer(radius_m / 111320.0)
                self.danger_geometries.append({
                    "geometry": polygon,
                    "severity": str(zone.get("severity", "High")).title(),
                    "incidents": max(1.0, float(zone.get("incidents", 1) or 1)),
                    "radius": radius_m,
                })
            except (KeyError, TypeError, ValueError, IndexError):
                logger.debug("Skipping malformed danger zone: %r", zone)

        for zone in self.safe_zones:
            try:
                lat, lng = float(zone["lat"]), float(zone["lng"])
                if self._valid_coordinates(lat, lng):
                    self.safe_geometries.append({
                        "geometry": Point(lng, lat).buffer(0.005),
                        "name": zone.get("name", "Safe Zone"),
                        "risk": zone.get("risk", "Low"),
                    })
            except (KeyError, TypeError, ValueError):
                logger.debug("Skipping malformed safe zone: %r", zone)

        geometries = [zone["geometry"] for zone in self.danger_geometries]
        if geometries:
            self.danger_spatial_index = STRtree(geometries)
        logger.info("Built danger-zone spatial index with %d zones", len(geometries))

    def _danger_candidates(self, line):
        """Handle STRtree results from both Shapely 1.x and 2.x."""
        if self.danger_spatial_index is None:
            return []
        results = self.danger_spatial_index.query(line)
        candidates = []
        for result in results:
            if isinstance(result, (int, np.integer)):  # Shapely 2.x returns indices
                index = int(result)
                if 0 <= index < len(self.danger_geometries):
                    candidates.append(self.danger_geometries[index])
            else:  # Shapely 1.x returns geometry objects
                for zone in self.danger_geometries:
                    if zone["geometry"] is result or zone["geometry"].equals(result):
                        candidates.append(zone)
                        break
        return candidates

    def _calculate_enhanced_edge_safety_score(self, edge_geometry: LineString) -> Dict:
        danger_penalty = 0.0
        for zone in self._danger_candidates(edge_geometry):
            polygon = zone["geometry"]
            if edge_geometry.intersects(polygon):
                intersection = edge_geometry.intersection(polygon)
                fraction = intersection.length / edge_geometry.length if edge_geometry.length else 0.0
                severity = {"Critical": 2.0, "High": 1.5, "Medium": 1.0, "Low": 0.5}.get(zone["severity"], 1.0)
                incidents = min(zone["incidents"] / 10.0, 3.0)
                danger_penalty += fraction * severity * max(0.1, incidents)
            else:
                distance = edge_geometry.distance(polygon)
                if distance < 0.001:
                    danger_penalty += (1 - distance / 0.001) * 0.3

        safe_bonus = 0.0
        for zone in self.safe_geometries:
            polygon = zone["geometry"]
            if edge_geometry.intersects(polygon):
                safe_bonus += 0.3
            elif edge_geometry.distance(polygon) < 0.002:
                safe_bonus += 0.1

        police_bonus = 0.0
        for station in self.police_stations:
            point = self._record_point(station)
            if point is not None:
                distance_m = edge_geometry.distance(point) * 111320
                if distance_m < 500:
                    police_bonus += 0.2 * (1 - distance_m / 500)

        hospital_bonus = 0.0
        for hospital in self.hospitals:
            point = self._record_point(hospital)
            if point is not None:
                distance_m = edge_geometry.distance(point) * 111320
                if distance_m < 500:
                    hospital_bonus += 0.15 * (1 - distance_m / 500)

        black_spot_penalty = 0.0
        for spot in self.black_spots:
            point = self._record_point(spot)
            if point is not None:
                distance_m = edge_geometry.distance(point) * 111320
                if distance_m < 100:
                    black_spot_penalty += 0.5 * (1 - distance_m / 100)

        total_penalty = danger_penalty + black_spot_penalty
        total_bonus = safe_bonus + police_bonus + hospital_bonus
        multiplier = max(0.1, min(2.0, 1.0 - min(total_penalty, 0.9) + total_bonus))
        return {
            "safety_multiplier": multiplier,
            "risk_score": min(1.0, max(0.0, total_penalty)),
            "danger_penalty": danger_penalty,
            "black_spot_penalty": black_spot_penalty,
            "safe_bonus": safe_bonus,
            "police_bonus": police_bonus,
            "hospital_bonus": hospital_bonus,
        }

    @staticmethod
    def _haversine_length(coords) -> float:
        total = 0.0
        for (lon1, lat1), (lon2, lat2) in zip(coords, coords[1:]):
            phi1, phi2 = math.radians(lat1), math.radians(lat2)
            dphi, dlambda = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
            a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
            total += 6371000 * 2 * math.asin(min(1.0, math.sqrt(a)))
        return total

    def _calculate_enhanced_edge_safety_scores(self) -> None:
        logger.info("Calculating safety weights for road edges...")
        for count, (_u, _v, _key, data) in enumerate(self.G.edges(keys=True, data=True), start=1):
            geometry = data.get("geometry")
            if geometry is None:
                continue
            try:
                distance = float(data.get("length", 0) or 0)
            except (TypeError, ValueError):
                distance = 0.0
            if distance <= 0:
                distance = self._haversine_length(list(geometry.coords))

            metrics = self._calculate_enhanced_edge_safety_score(geometry)
            data["base_distance"] = distance
            for key, value in metrics.items():
                data[key] = float(value)
            # Lower edge cost is preferred by Dijkstra.
            data["weight"] = distance / max(metrics["safety_multiplier"], 0.1)
            data["safe_weight"] = distance / max(metrics["safety_multiplier"] ** 2, 0.01)
            if count % 5000 == 0:
                logger.info("Processed %d edges...", count)
        logger.info("Safety weights calculated for %d edges", self.G.number_of_edges())

    def find_safe_route(
        self, start_lat: float, start_lon: float, end_lat: float, end_lon: float,
        optimization: str = "balanced"
    ) -> Optional[Dict]:
        if optimization not in {"safest", "shortest", "balanced"}:
            return {"found": False, "error": "optimization must be safest, balanced, or shortest"}
        if not all(self._valid_coordinates(a, b) for a, b in ((start_lat, start_lon), (end_lat, end_lon))):
            return {"found": False, "error": "Invalid start or end latitude/longitude"}
        if self.G is None or self.G.number_of_nodes() == 0:
            return {"found": False, "error": "Road network is empty"}

        try:
            start = ox.distance.nearest_nodes(self.G, X=float(start_lon), Y=float(start_lat))
            end = ox.distance.nearest_nodes(self.G, X=float(end_lon), Y=float(end_lat))
            weight = {"safest": "safe_weight", "balanced": "weight", "shortest": "base_distance"}[optimization]
            path = nx.dijkstra_path(self.G, source=start, target=end, weight=weight)
            return {
                "found": True,
                "path_nodes": path,
                "route_stats": self._calculate_route_statistics(path),
                "start_coords": (float(start_lat), float(start_lon)),
                "end_coords": (float(end_lat), float(end_lon)),
                "optimization": optimization,
            }
        except nx.NetworkXNoPath:
            return {"found": False, "error": "No road path exists between the specified points"}
        except nx.NodeNotFound:
            return {"found": False, "error": "Could not find a road-network node near the coordinates"}
        except Exception as exc:
            logger.exception("Error finding route")
            return {"found": False, "error": str(exc)}

    def _calculate_route_statistics(self, path_nodes: List) -> Dict:
        distance = risk_total = multiplier_total = safe_total = police_total = hospital_total = 0.0
        edges = []
        for u, v in zip(path_nodes, path_nodes[1:]):
            parallel = self.G.get_edge_data(u, v)
            if not parallel:
                continue
            data = min(parallel.values(), key=lambda item: float(item.get("weight", item.get("length", math.inf))))
            edge_distance = float(data.get("base_distance", data.get("length", 0)) or 0)
            risk = float(data.get("risk_score", 0) or 0)
            multiplier = float(data.get("safety_multiplier", 1) or 1)
            distance += edge_distance
            risk_total += risk
            multiplier_total += multiplier
            safe_total += float(data.get("safe_bonus", 0) or 0)
            police_total += float(data.get("police_bonus", 0) or 0)
            hospital_total += float(data.get("hospital_bonus", 0) or 0)
            edges.append({
                "from": u, "to": v, "distance": edge_distance,
                "risk_score": risk, "safety_multiplier": multiplier,
                "geometry": data.get("geometry"),
            })

        count = len(edges)
        avg_risk = risk_total / count if count else 0.0
        avg_multiplier = multiplier_total / count if count else 1.0
        return {
            "total_distance_meters": distance,
            "total_distance_km": distance / 1000,
            "average_risk_score": avg_risk,
            "average_safety_multiplier": avg_multiplier,
            "model_based_safety_score": round(max(0, min(100, 100 * (1 - avg_risk))), 1),
            "total_safety_bonus": safe_total,
            "total_police_bonus": police_total,
            "total_hospital_bonus": hospital_total,
            "num_edges": count,
            "edges": edges,
        }

    def visualize_route(self, route_result: Dict, output_file: str = "enhanced_safe_route.html") -> None:
        if not route_result.get("found"):
            logger.warning("Cannot visualize: no route found")
            return
        start_lat, start_lon = route_result["start_coords"]
        end_lat, end_lon = route_result["end_coords"]
        map_obj = folium.Map(location=[(start_lat + end_lat) / 2, (start_lon + end_lon) / 2], zoom_start=13)

        for zone in self.danger_zones:
            try:
                lat, lng = zone["center"]
                severity = str(zone.get("severity", "High")).title()
                color = {"Critical": "darkred", "High": "red", "Medium": "orange", "Low": "yellow"}.get(severity, "red")
                folium.Circle([lat, lng], radius=float(zone.get("radius", 500)), color=color,
                              fill=True, fill_opacity=0.25,
                              popup=f"Risk zone · {severity} · Incidents: {zone.get('incidents', 0)}").add_to(map_obj)
            except (KeyError, TypeError, ValueError):
                continue

        for zone in self.safe_zones:
            try:
                folium.Circle([float(zone["lat"]), float(zone["lng"])], radius=300, color="green",
                              fill=True, fill_opacity=0.2,
                              popup=f"Safe zone · {zone.get('name', 'Unknown')}").add_to(map_obj)
            except (KeyError, TypeError, ValueError):
                continue

        for records, label, color, icon in (
            (self.police_stations, "Police station", "blue", "info-sign"),
            (self.hospitals, "Hospital", "green", "plus"),
            (self.black_spots, "Black spot", "black", "warning-sign"),
        ):
            for record in records:
                point = self._record_point(record)
                if point is not None:
                    folium.Marker([point.y, point.x],
                                  popup=f"{label} · {record.get('name', 'Unknown')}",
                                  icon=folium.Icon(color=color, icon=icon)).add_to(map_obj)

        for edge in route_result["route_stats"].get("edges", []):
            geometry = edge.get("geometry")
            if geometry is not None:
                risk = float(edge.get("risk_score", 0))
                color = "green" if risk < 0.3 else "orange" if risk < 0.6 else "red"
                folium.PolyLine([[lat, lon] for lon, lat in geometry.coords],
                                color=color, weight=5, opacity=0.85).add_to(map_obj)

        stats = route_result["route_stats"]
        folium.Marker([start_lat, start_lon], popup="Start",
                      icon=folium.Icon(color="green", icon="play", prefix="fa")).add_to(map_obj)
        folium.Marker([end_lat, end_lon], popup="Destination",
                      icon=folium.Icon(color="red", icon="stop", prefix="fa")).add_to(map_obj)
        summary = (
            "<div style='position:fixed;bottom:35px;left:35px;z-index:1000;background:white;"
            "padding:12px;border:1px solid #bbb;border-radius:8px;font:13px Arial'>"
            "<b>Route metrics (heuristic)</b><br>"
            f"Distance: {stats['total_distance_km']:.2f} km<br>"
            f"Average risk index: {stats['average_risk_score']:.2f}<br>"
            f"Safety score: {stats['model_based_safety_score']:.1f}/100<br>"
            f"Police bonus: {stats['total_police_bonus']:.2f}<br>"
            f"Hospital bonus: {stats['total_hospital_bonus']:.2f}</div>"
        )
        map_obj.get_root().html.add_child(folium.Element(summary))
        map_obj.save(output_file)
        logger.info("Map saved to %s", output_file)

    def get_route_safety_report(self, route_result: Dict) -> str:
        if not route_result.get("found"):
            return f"No route found: {route_result.get('error', 'unknown error')}"
        stats = route_result["route_stats"]
        risk = stats["average_risk_score"]
        assessment = "LOWER RELATIVE RISK INDEX" if risk < 0.2 else (
            "MODERATE RELATIVE RISK INDEX" if risk < 0.5 else "HIGHER RELATIVE RISK INDEX"
        )
        return f"""========== ROUTE SAFETY REPORT ==========
Optimization mode: {route_result['optimization']}
Distance: {stats['total_distance_km']:.2f} km ({stats['total_distance_meters']:.0f} m)
Segments: {stats['num_edges']}
Average risk index: {risk:.2f}/1.00
Heuristic safety score: {stats['model_based_safety_score']:.1f}/100
Average safety multiplier: {stats['average_safety_multiplier']:.2f}x
Safe-zone bonus: +{stats['total_safety_bonus']:.2f}
Police proximity bonus: +{stats['total_police_bonus']:.2f}
Hospital proximity bonus: +{stats['total_hospital_bonus']:.2f}
Assessment: {assessment}
Note: Scores use supplied data and heuristics; they are not validated crime probabilities or safety guarantees.
========================================"""

if __name__ == "__main__":
    planner = EnhancedSafeRoutePlanner(
        location_name=os.getenv("ROUTE_LOCATION_NAME", "Nagpur, Maharashtra, India"),
        safety_data_path=str(DEFAULT_SAFETY_DATA),
        cache_graph=True,
        graph_cache_path=str(DEFAULT_GRAPH_CACHE),
    )
    # Example coordinates within Nagpur (not Mumbai).
    start = (21.1458, 79.0882)
    end = (21.1200, 79.0500)
    for mode in ("safest", "balanced", "shortest"):
        result = planner.find_safe_route(*start, *end, optimization=mode)
        print(f"\n{mode.upper()} ROUTE")
        if result.get("found"):
            print(planner.get_route_safety_report(result))
            if mode == "safest":
                planner.visualize_route(result, "safest_route.html")
        else:
            print(result.get("error", "Route not found"))
