import networkx as nx
import math
import json

def get_distance(lat1, lon1, lat2, lon2):
    R = 6371e3
    r_lat1, r_lat2 = math.radians(lat1), math.radians(lat2)
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)

    a = math.sin(d_lat/2) * math.sin(d_lat/2) + \
        math.cos(r_lat1) * math.cos(r_lat2) * \
        math.sin(d_lon/2) * math.sin(d_lon/2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

    return R * c

# Safety Impedance Mod: Increase the edge weight linearly if it touches a KDE Red Zone.
def calculate_safety_impedance(edge, danger_zones):
    penalty = 1.0 # Baseline multiplier
    
    # Check simple bounds collision
    for zone in danger_zones:
        # Distance from edge average coordinate to Danger Zone center
        edge_mid_lat = (edge[0]['lat'] + edge[1]['lat']) / 2
        edge_mid_lon = (edge[0]['lng'] + edge[1]['lng']) / 2
        
        dist = get_distance(edge_mid_lat, edge_mid_lon, zone['center'][0], zone['center'][1])
        
        # If the edge passes inside the 600m red radius, heavily penalise it.
        # This will instruct A* or Dijkstra's algorithms inside NetworkX to avoid this edge completely.
        if dist < zone['radius']:
            # Apply an artificial inflation
            penalty += 10000.0  # Safe Route Logic
    
    return penalty

def suggest_safe_route(start, destination, danger_zones_path='../Server/danger_zones.json'):
    G = nx.Graph()
    
    # 1. Load mocked open-street map edges
    edges = [
        # (NodeA, NodeB, default_distance_cost, mid coordinates block)
        ('A', 'B', {'weight': 400, 'lat': 28.6189, 'lng': 77.2170}), # Very prone to red zone
        ('A', 'C', {'weight': 500, 'lat': 28.6180, 'lng': 77.2100}), # Completely clear of Red Zone
        ('C', 'B', {'weight': 500, 'lat': 28.6250, 'lng': 77.2100})  # Completely clear of Red Zone
    ]
    
    with open(danger_zones_path, 'r') as f:
        danger_zones = json.load(f)
        
    for u, v, data in edges:
        # 2. Modify Edge Impedance based on Heatmap collisions
        base_cost = data['weight']
        mock_edge = [{"lat": data['lat'], "lng": data['lng']}, {"lat": data['lat']+0.001, "lng": data['lng']+0.001}]
        
        impedance_multiplier = calculate_safety_impedance(mock_edge, danger_zones)
        safe_weight = base_cost * impedance_multiplier
        
        G.add_edge(u, v, weight=safe_weight)

    # 3. Dijkstra’s Algorithm
    try:
        path = nx.dijkstra_path(G, source=start, target=destination)
        print("Safe Route Computed:", path)
        return path
    except nx.NetworkXNoPath:
        print("No route exists.")
        return None

if __name__ == '__main__':
    suggest_safe_route('A', 'B')
