import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  MapContainer, TileLayer, Marker, Popup, Circle, Polyline,
  useMap, useMapEvents
} from 'react-leaflet';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import './SarthiMap.css';
import MetroRoutesLayer from './MetroRoutesLayer';
const CITY = [21.1458, 79.0882];

const defaultIcon = new L.Icon({
  iconRetinaUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png',
  iconUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png',
  shadowUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png',
  iconSize: [25, 41], iconAnchor: [12, 41], popupAnchor: [1, -34], shadowSize: [41, 41],
});
L.Marker.prototype.options.icon = defaultIcon;

function point(item) {
  if (Array.isArray(item?.center) && item.center.length >= 2) {
    return [Number(item.center[0]), Number(item.center[1])];
  }
  const lat = item?.lat ?? item?.latitude;
  const lng = item?.lng ?? item?.lon ?? item?.longitude;
  return lat != null && lng != null ? [Number(lat), Number(lng)] : null;
}
function validPoint(p) {
  return Array.isArray(p) && p.length === 2 && p.every(Number.isFinite) &&
    Math.abs(p[0]) <= 90 && Math.abs(p[1]) <= 180;
}
function poiIcon(color, glyph, count = null) {
  const label = count && count > 1 ? count : glyph;
  return L.divIcon({
    className: 'sarthi-poi-icon-wrap',
    html: `<span class="sarthi-poi-icon" style="--poi-color:${color}">${label}</span>`,
    iconSize: [36, 36], iconAnchor: [18, 18], popupAnchor: [0, -18],
  });
}
const POI = {
  police: { color: '#2563eb', glyph: '✚', title: 'Police station' },
  hospital: { color: '#dc2626', glyph: '✚', title: 'Hospital' },
  metro: { color: '#475569', glyph: 'M', title: 'Transit station' },
  safe: { color: '#059669', glyph: '✓', title: 'Safe zone' },
  school: { color: '#7c3aed', glyph: 'S', title: 'Educational institution' },
  hostel: { color: '#c2410c', glyph: 'H', title: 'Hostel / PG' },
  corporate: { color: '#475569', glyph: 'C', title: 'Corporate area' },
  tactical: { color: '#0f766e', glyph: '✦', title: 'Support unit' },
  black: { color: '#7e22ce', glyph: '!', title: 'Black spot' },
};

function MapClick({ onMapClick }) {
  useMapEvents({ click: (event) => onMapClick?.({ lat: event.latlng.lat, lng: event.latlng.lng }) });
  return null;
}

function MapEffects({ location, routeOptions, routeStart, routeEnd, onInitialReveal }) {
  const map = useMap();
  const didIntroRef = useRef(false);
  useEffect(() => {
    const timer = window.setTimeout(() => map.invalidateSize(), 140);
    return () => window.clearTimeout(timer);
  }, [map]);

  // Intro animation: zoom to the current location, then reveal the surrounding area.
  useEffect(() => {
    const lat = Number(location?.lat);
    const lng = Number(location?.lng);
    if (didIntroRef.current || location?.isApproximate || !Number.isFinite(lat) || !Number.isFinite(lng)) return;
    didIntroRef.current = true;
    const target = L.latLng(lat, lng);
    map.flyTo(target, 16, { animate: true, duration: 1.7, easeLinearity: 0.22 });
    // Keep the marker's arrival animation visible while Leaflet flies to GPS.
    const revealTimer = window.setTimeout(() => onInitialReveal?.(), 1750);
    return () => window.clearTimeout(revealTimer);
  }, [map, location?.lat, location?.lng, location?.isApproximate, onInitialReveal]);

  // When the user selects a fresh GPS start, move the map to that exact point.
  useEffect(() => {
    const start = routeStart
      ? [Number(routeStart.lat ?? routeStart.latitude), Number(routeStart.lng ?? routeStart.lon ?? routeStart.longitude)]
      : null;
    if (validPoint(start)) {
      map.flyTo(start, Math.max(map.getZoom(), 15), {
        animate: true,
        duration: 0.8,
      });
    }
  }, [map, routeStart]);

  useEffect(() => {
    const coords = (routeOptions || [])
      .flatMap((route) => route.coords || [])
      .map((p) => Array.isArray(p) ? p : point(p))
      .filter(validPoint);
    const start = routeStart
      ? [Number(routeStart.lat ?? routeStart.latitude), Number(routeStart.lng ?? routeStart.lon ?? routeStart.longitude)]
      : null;
    const end = routeEnd
      ? [Number(routeEnd.lat ?? routeEnd.latitude), Number(routeEnd.lng ?? routeEnd.lon ?? routeEnd.longitude)]
      : null;
    if (validPoint(start)) coords.push(start);
    if (validPoint(end)) coords.push(end);
    if (coords.length > 1) {
      map.fitBounds(L.latLngBounds(coords), { padding: [54, 54], maxZoom: 16, animate: true });
    }
  }, [map, routeOptions, routeStart, routeEnd]);

  return null;
}

// Lightweight geographic clustering avoids piles of overlapping icons in dense city areas.
// Nearby points of the same category become a count bubble; clicking it reveals each record.
function clusteredPoints(items = [], type, zoom) {
  const meta = POI[type];
  const list = (Array.isArray(items) ? items : [])
    .map((item, index) => ({ item, index, p: point(item) }))
    .filter((x) => validPoint(x.p));

  const cell = zoom >= 15 ? 0.0012 : zoom >= 13 ? 0.0032 : 0.008;
  const groups = new Map();
  for (const entry of list) {
    const key = `${Math.round(entry.p[0] / cell)}:${Math.round(entry.p[1] / cell)}`;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(entry);
  }

  return [...groups.entries()].map(([key, entries]) => {
    const lat = entries.reduce((sum, x) => sum + x.p[0], 0) / entries.length;
    const lng = entries.reduce((sum, x) => sum + x.p[1], 0) / entries.length;
    return {
      key: `${type}-${key}`,
      position: [lat, lng],
      entries,
      icon: poiIcon(meta.color, meta.glyph, entries.length),
      meta,
    };
  });
}

function ClusterLayer({ items, type, zoom }) {
  const clusters = useMemo(() => clusteredPoints(items, type, zoom), [items, type, zoom]);
  return clusters.map((cluster) => (
    <Marker key={cluster.key} position={cluster.position} icon={cluster.icon}>
      <Popup>
        <div className="sarthi-popup">
          <strong>{cluster.entries.length > 1
            ? `${cluster.entries.length} ${cluster.meta.title.toLowerCase()} locations`
            : cluster.entries[0].item.name || cluster.meta.title}</strong>
          {cluster.entries.map(({ item, index }) => (
            <div className="sarthi-popup-entry" key={item.id ?? `${cluster.key}-${index}`}>
              <b>{item.name || cluster.meta.title}</b>
              {item.severity && <small>Severity: {item.severity}</small>}
              {item.risk && <small>Risk: {item.risk}</small>}
              {item.address && <small>{item.address}</small>}
              {(item.phone || item.contact) && <small>{item.phone || item.contact}</small>}
            </div>
          ))}
        </div>
      </Popup>
    </Marker>
  ));
}

function ZoomReporter({ onZoom }) {
  const map = useMap();
  useEffect(() => {
    const update = () => onZoom(map.getZoom());
    update();
    map.on('zoomend', update);
    return () => map.off('zoomend', update);
  }, [map, onZoom]);
  return null;
}

export default function SarthiMap({
  location, dangerZones = [], isSOS = false, isSarthiActive = false,
  routeOptions = [], routeStart, routeEnd, safetyData, layers = {},
  onMapClick, trackedUsers = {},
}) {
  const [zoom, setZoom] = useState(13);
  const [introDone, setIntroDone] = useState(false);
  const onZoom = useCallback((nextZoom) => setZoom(nextZoom), []);
  const reveal = useCallback(() => setIntroDone(true), []);

  const lat = Number(location?.lat ?? location?.latitude);
  const lng = Number(location?.lng ?? location?.lon ?? location?.longitude);
  const hasLocation = Number.isFinite(lat) && Number.isFinite(lng) &&
    Math.abs(lat) <= 90 && Math.abs(lng) <= 180;
  const center = hasLocation ? [lat, lng] : CITY;
  const data = safetyData || {};
  const show = (key) => layers[key] !== false;
  const zones = dangerZones.length ? dangerZones : (data.danger_zones || []);

  const userIcon = useMemo(() => L.divIcon({
    className: 'sarthi-user-marker-wrap',
    html: `<div class="sarthi-user-marker ${isSOS ? 'is-sos' : ''} ${isSarthiActive ? 'is-tracking' : ''} ${!introDone ? 'intro-arrival' : ''}">
      <span class="user-halo halo-one"></span><span class="user-halo halo-two"></span>
      <span class="user-core"><span class="user-core-dot"></span></span>
      <span class="user-marker-label">${isSOS ? 'SOS ACTIVE' : 'YOU ARE HERE'}</span>
    </div>`,
    iconSize: [120, 76], iconAnchor: [60, 27],
  }), [isSOS, isSarthiActive, introDone, location?.isApproximate]);

  return (
    <div className="safety-map-shell">
      <MapContainer center={center} zoom={13} scrollWheelZoom zoomControl className="safety-map">
        <MapEffects location={location} routeOptions={routeOptions} routeStart={routeStart} routeEnd={routeEnd} onInitialReveal={reveal} />
        <ZoomReporter onZoom={onZoom} />
        <MapClick onMapClick={onMapClick} />
        <TileLayer
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
        />

        {hasLocation && !location?.isApproximate && Number(location?.accuracy) > 0 && (
          <Circle
            center={center}
            radius={Math.min(250, Math.max(20, Number(location.accuracy)))}
            pathOptions={{
              color: '#0d9488',
              fillColor: '#14b8a6',
              fillOpacity: 0.055,
              opacity: 0.35,
              weight: 1.5,
              dashArray: '4 7',
            }}
          />
        )}

        {hasLocation && <Marker position={center} icon={userIcon} zIndexOffset={1200}>
          <Popup><strong>{isSOS ? 'SOS active' : 'Your location'}</strong>
            <div>{location?.isApproximate ? 'Approximate location' : `GPS accuracy: ${Math.round(Number(location?.accuracy) || 0)} m`}</div>
          </Popup>
        </Marker>}

        {Object.entries(trackedUsers || {}).map(([id, tracked]) => {
          const p = point(tracked);
          if (!validPoint(p)) return null;
          const trackedIcon = poiIcon(tracked.isSOS ? '#dc2626' : '#0d9488', tracked.isSOS ? '!' : '•');
          return <Marker key={`tracked-${id}`} position={p} icon={trackedIcon}>
            <Popup><strong>{tracked.userName || `Traveler ${id.slice(0, 5)}`}</strong>
              <div>{tracked.isSOS ? 'SOS signal reported' : 'Live shared location'}</div></Popup>
          </Marker>;
        })}

        {show('dangerZones') && zones.map((zone, index) => {
          const p = point(zone);
          if (!validPoint(p)) return null;
          const severity = String(zone.severity || zone.risk || '').toLowerCase();
          const critical = severity.includes('critical') || severity.includes('severe');
          const high = critical || severity.includes('high');
          const color = critical ? '#b91c1c' : high ? '#ef4444' : '#f59e0b';
          return <Circle key={`risk-${zone.id ?? index}`} center={p}
            radius={Math.max(80, Number(zone.radius) || (critical ? 600 : high ? 450 : 300))}
            pathOptions={{ color, fillColor: color, fillOpacity: 0.13, weight: 2.5, opacity: 0.85 }}>
            <Popup><div className="sarthi-popup"><strong>{zone.name || 'Risk area'}</strong>
              <span className={`risk-pill ${critical ? 'critical' : high ? 'high' : 'moderate'}`}>{zone.severity || zone.risk || 'Unclassified'} risk</span>
              {zone.incidents != null && <small>{zone.incidents} source records</small>}
              <small>Dataset-based indication, not a prediction of an incident.</small></div></Popup>
          </Circle>;
        })}

        {show('blackSpots') && (data.black_spots || []).map((spot, index) => {
          const p = point(spot);
          if (!validPoint(p)) return null;
          return <Circle key={`black-${spot.id ?? index}`} center={p}
            radius={Math.max(45, Number(spot.radius) || 130)}
            pathOptions={{ color: '#7e22ce', fillColor: '#a855f7', fillOpacity: 0.19, weight: 2, dashArray: '5 6' }}>
            <Popup><div className="sarthi-popup"><strong>{spot.name || 'Reported black spot'}</strong>
              {spot.description && <small>{spot.description}</small>}
              <small>Recorded point from supplied dataset.</small></div></Popup>
          </Circle>;
        })}

        {show('policeStations') && <ClusterLayer items={data.police_stations} type="police" zoom={zoom} />}
        {show('hospitals') && <ClusterLayer items={data.hospitals} type="hospital" zoom={zoom} />}
        <MetroRoutesLayer stations={data.metro_stations || []} visible={show('metroStations')} />
        {show('safeZones') && <ClusterLayer items={data.safe_zones} type="safe" zoom={zoom} />}
        {show('tacticalUnits') && <ClusterLayer items={data.tactical_units} type="tactical" zoom={zoom} />}
        {show('hostels') && <ClusterLayer items={data.hostels_pgs} type="hostel" zoom={zoom} />}
        {show('education') && <ClusterLayer items={data.educational_institutions} type="school" zoom={zoom} />}
        {show('corporate') && <ClusterLayer items={data.corporate_areas} type="corporate" zoom={zoom} />}

        {routeOptions.map((route, index) => {
          const coords = (route.coords || []).map((p) => Array.isArray(p) ? p : point(p)).filter(validPoint);
          const start = routeStart
            ? [Number(routeStart.lat ?? routeStart.latitude), Number(routeStart.lng ?? routeStart.lon ?? routeStart.longitude)]
            : null;
          const end = routeEnd
            ? [Number(routeEnd.lat ?? routeEnd.latitude), Number(routeEnd.lng ?? routeEnd.lon ?? routeEnd.longitude)]
            : null;
          if (coords.length < 2) return null;
          const startConnector = validPoint(start) ? [start, coords[0]] : [];
          const endConnector = validPoint(end) ? [coords[coords.length - 1], end] : [];
          return (
            <React.Fragment key={`route-${route.id ?? index}`}>
              {/* Dashed connectors show the short off-road snap from the chosen point to the road graph. */}
              {startConnector.length === 2 && <Polyline positions={startConnector}
                pathOptions={{ color: route.color || '#0f766e', weight: 3, opacity: 0.9, dashArray: '5 7', lineCap: 'round' }} />}
              <Polyline positions={coords}
                pathOptions={{ color: route.color || '#0f766e', weight: 6, opacity: 0.95, lineCap: 'round', lineJoin: 'round' }}>
                <Popup><strong>{route.label || 'Planned route'}</strong>
                  {route.distanceKm != null && <div>{route.distanceKm} km (road network distance)</div>}
                  {route.score != null && <div>Model-based safety score: {route.score}/100</div>}
                  <div>Dashed ends connect your selected points to the nearest mapped road.</div>
                </Popup>
              </Polyline>
              {endConnector.length === 2 && <Polyline positions={endConnector}
                pathOptions={{ color: route.color || '#0f766e', weight: 3, opacity: 0.9, dashArray: '5 7', lineCap: 'round' }} />}
            </React.Fragment>
          );
        })}

        {validPoint(routeStart && [Number(routeStart.lat), Number(routeStart.lng ?? routeStart.lon)]) &&
          <Marker position={[Number(routeStart.lat), Number(routeStart.lng ?? routeStart.lon)]} icon={poiIcon('#059669', 'A')}><Popup>Route start</Popup></Marker>}
        {validPoint(routeEnd && [Number(routeEnd.lat), Number(routeEnd.lng ?? routeEnd.lon)]) &&
          <Marker position={[Number(routeEnd.lat), Number(routeEnd.lng ?? routeEnd.lon)]} icon={poiIcon('#dc2626', 'B')}><Popup>Route destination</Popup></Marker>}
      </MapContainer>

      <div className="map-top-chip"><span className="map-live-dot" /> Safety map <span className="map-chip-divider" /> {zoom >= 15 ? 'Detailed view' : zoom >= 13 ? 'Area view' : 'Regional view'}</div>
      <div className="map-layer-legend">
        <span><i className="legend-risk" /> Risk area</span>
        <span><i className="legend-blackspot" /> Black spot</span>
        <span><i className="legend-poi police">✚</i> Police</span>
        <span><i className="legend-poi hospital">✚</i> Hospital</span>
        <span><i className="legend-poi safe">✓</i> Safe zone</span>
        <span><i className="legend-current" /> You</span>
      </div>
      <div className="map-attribution-note">© OpenStreetMap contributors</div>
    </div>
  );
}
