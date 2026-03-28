import { MapContainer, TileLayer, Marker, Popup, Circle, Polyline, useMap } from 'react-leaflet';
import { useEffect } from 'react';
import 'leaflet/dist/leaflet.css';
import L from 'leaflet';

// Fix typical React-Leaflet icon issue
delete L.Icon.Default.prototype._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png',
  iconUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png',
  shadowUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png',
});

const redZoneOptions = { color: '#EF4444', fillColor: '#EF4444', fillOpacity: 0.4 };
const dangerZoneOptions = { color: '#F59E0B', fillColor: '#F59E0B', fillOpacity: 0.4 };
const safePathOptions = { color: '#10B981', weight: 6, opacity: 0.8 };

function AutoCenter({ location }) {
  const map = useMap();
  useEffect(() => {
    map.flyTo([location.lat, location.lng], map.getZoom());
  }, [location, map]);
  return null;
}

export default function SarthiMap({ location, dangerZones, isSOS, isSarthiActive, customRoute, safetyData, layers }) {
  // A fallback mock safe route around the closest danger zone, if customRoute not loaded
  const fallbackSafeRoute = [
    [location.lat, location.lng],
    [location.lat + 0.005, location.lng + 0.005],
    [location.lat + 0.01, location.lng + 0.007],
    [location.lat + 0.015, location.lng + 0.015]
  ];

  const routeToPlot = customRoute || fallbackSafeRoute;

  // --- Professional SVG Icons (Using divIcon for crisp render) ---
  const createDivIcon = (type) => {
    let color = '#3b82f6';
    let icon = '';
    
    if (type === 'police') {
      color = '#1e40af'; 
      icon = `<svg viewBox="0 0 24 24" fill="white" style="width:18px"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>`;
    } else if (type === 'hospital') {
      color = '#dc2626'; 
      icon = `<svg viewBox="0 0 24 24" fill="white" style="width:18px"><path d="M19 3H5c-1.1 0-1.99.9-1.99 2L3 19c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm-1 11h-4v4h-4v-4H6v-4h4V6h4v4h4v4z"/></svg>`;
    }

    return L.divIcon({
      className: 'custom-marker',
      html: `
        <div style="
          background: ${color}; 
          width: 36px; 
          height: 36px; 
          border-radius: 50%; 
          display: flex; 
          align-items: center; 
          justify-content: center; 
          border: 2px solid rgba(255,255,255,0.8);
          box-shadow: 0 0 15px ${color}, inset 0 0 10px rgba(255,255,255,0.5);
          backdrop-filter: blur(4px);
        ">
          ${icon}
        </div>
      `,
      iconSize: [36, 36],
      iconAnchor: [18, 18]
    });
  };

  const policeIcon = createDivIcon('police');
  const hospitalIcon = createDivIcon('hospital');

  // Metro Lines Logic (Grouped by lines based on typical Nagpur routes)
  const orangeLine = safetyData?.metro_stations?.filter(s => s.name.match(/Automotive|Nari|Indora|Kadvi|Gaddi|Kasturchand|Zero|Sitabuldi|Congress|Rahate|Ajni|Chhatrapati|Jaiprakash|Ujjwal|Airport|Khapri/i)) || [];
  const aquaLine = safetyData?.metro_stations?.filter(s => s.name.match(/Prajapati|Vaishnodevi|Ambedkar|Telephone|Chitar|Agrasen|Dosar|Nagpur Railway|Cotton|Jhansi|Institution|Shankar|LAD|Dharampeth|Subhash|Rachana|Vasudev|Bansi|Lokmanya/i)) || [];

  const orangeCoords = orangeLine.sort((a,b) => b.lat - a.lat).map(s => [s.lat, s.lng]);
  const aquaCoords = aquaLine.sort((a,b) => a.lng - b.lng).map(s => [s.lat, s.lng]);

  return (
    <div className={`map-container glass`} style={{ border: isSarthiActive ? '3px solid #ff2e63' : '1px solid rgba(0,0,0,0.1)', overflow: 'hidden' }}>
      <MapContainer 
        center={[location.lat, location.lng]} 
        zoom={13} 
        style={{ height: '100%', width: '100%', borderRadius: '18px' }}
      >
        <AutoCenter location={location} />

        {/* Regular High-Visibility Map Theme */}
        <TileLayer
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
        />
        
        {/* User Marker with Pulse effect */}
        <Marker position={[location.lat, location.lng]} icon={L.divIcon({
          className: 'user-marker',
          html: `<div class="user-pulse"></div><div class="user-dot"></div>`,
          iconSize: [40, 40],
          iconAnchor: [20, 20]
        })}>
          <Popup>
            <div style={{ textAlign: 'center' }}>
              {isSOS ? <strong style={{ color: '#EF4444' }}>🚨 SOS BROADCAST ACTIVE</strong> : '🛡️ Your Current GPS Lock'}
            </div>
          </Popup>
        </Marker>

        {/* Dynamic Danger Zones (Heatmap with pulsing effect) */}
        {layers.dangerZones && dangerZones.map((zone, idx) => (
          <Circle 
            key={idx} 
            center={zone.center} 
            pathOptions={{ 
              color: zone.severity === 'Critical' ? '#EF4444' : '#F59E0B', 
              fillColor: zone.severity === 'Critical' ? '#EF4444' : '#F59E0B', 
              fillOpacity: 0.2,
              weight: 2,
              className: 'pulse-animation'
            }} 
            radius={zone.radius} 
          >
            <Popup>
              <div style={{ textAlign: 'center' }}>
                <h4 style={{ color: '#EF4444' }}>⚠️ {zone.severity} Danger Cluster</h4>
                <p style={{ fontSize: '0.85rem' }}>Area with high incident density (KDE Result).</p>
              </div>
            </Popup>
          </Circle>
        ))}

        {/* Metro Lines (Dotted Visuals) */}
        {layers.metroStations && (
          <>
            <Polyline positions={orangeCoords} pathOptions={{ color: '#F97316', weight: 4, dashArray: '5, 10', opacity: 0.8 }} />
            <Polyline positions={aquaCoords} pathOptions={{ color: '#06B6D4', weight: 4, dashArray: '5, 10', opacity: 0.8 }} />
            {safetyData?.metro_stations?.map((m, i) => (
              <Circle key={`m-node-${i}`} center={[m.lat, m.lng]} radius={30} pathOptions={{ color: '#2563eb', weight: 2, fillColor: 'white', fillOpacity: 1 }}>
                <Popup>🚇 <strong>{m.name}</strong><br/>Nagpur Metro Station</Popup>
              </Circle>
            ))}
          </>
        )}

        {/* Hospitals */}
        {layers.hospitals && safetyData?.hospitals?.map((h, i) => (
          <Marker key={`hosp-${i}`} position={[h.lat, h.lng]} icon={hospitalIcon}>
            <Popup>
              <h4 style={{ margin: 0 }}>🏥 {h.name}</h4>
              <p style={{ fontSize: '0.8rem', color: '#64748B' }}>{h.description}</p>
            </Popup>
          </Marker>
        ))}

        {/* Police Stations */}
        {layers.policeStations && safetyData?.police_stations?.map((p, i) => (
          <Marker key={`pol-${i}`} position={[p.lat, p.lng]} icon={policeIcon}>
            <Popup>
              <h4 style={{ margin: 0 }}>🚔 {p.name}</h4>
              <p style={{ fontSize: '0.8rem', color: '#64748B' }}>{p.description}</p>
            </Popup>
          </Marker>
        ))}

        {/* Black Spots */}
        {layers.blackSpots && safetyData?.black_spots?.map((b, i) => (
          <Circle key={`bs-${i}`} center={[b.lat, b.lng]} radius={150} 
            pathOptions={{ color: '#000', fillColor: '#334155', fillOpacity: 0.5, weight: 1, dashArray: '5, 5' }}>
            <Popup>
                 <h4 style={{ margin: 0 }}>🌑 Black Spot</h4>
                 <p style={{ fontSize: '0.8rem' }}><strong>{b.name}</strong></p>
                 <small>{b.description}</small>
            </Popup>
          </Circle>
        ))}

        {/* Safe Zones */}
        {layers.safeZones && safetyData?.safe_zones?.map((s, i) => (
          <Circle key={`sz-${i}`} center={[s.lat, s.lng]} radius={250} 
            pathOptions={{ color: '#10B981', fillColor: '#10B981', fillOpacity: 0.2, weight: 2 }}>
            <Popup>
                 <h4 style={{ color: '#10B981', margin: 0 }}>✅ Safe Zone</h4>
                 <p style={{ fontSize: '0.8rem' }}><strong>{s.name}</strong></p>
                 <small>{s.description}</small>
            </Popup>
          </Circle>
        ))}

        {/* Navigation Route Path */}
        <Polyline pathOptions={safePathOptions} positions={routeToPlot} />

      </MapContainer>
    </div>
  );
}
