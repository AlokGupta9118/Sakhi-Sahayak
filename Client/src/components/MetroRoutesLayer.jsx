import { useEffect, useMemo, useState } from 'react';
import { Marker, Pane, Polyline, Popup, Tooltip, useMap } from 'react-leaflet';
import L from 'leaflet';
import './MetroRoutesLayer.css';

const ROUTES = [
  {
    id: 'orange',
    relationId: 9571557,
    name: 'Orange Line',
    terminals: 'Khapri ↔ Automotive Square',
    color: '#f97316',
  },
  {
    id: 'aqua',
    relationId: 10659365,
    name: 'Aqua Line',
    terminals: 'Prajapati Nagar ↔ Lokmanya Nagar',
    color: '#0891b2',
  },
];

const OVERPASS_ENDPOINTS = [
  'https://overpass-api.de/api/interpreter',
  'https://overpass.kumi.systems/api/interpreter',
];

function toPoint(item) {
  if (Array.isArray(item?.center) && item.center.length >= 2) {
    const p = [Number(item.center[0]), Number(item.center[1])];
    return isValidPoint(p) ? p : null;
  }

  const lat = Number(item?.lat ?? item?.latitude);
  const lng = Number(item?.lng ?? item?.lon ?? item?.longitude);
  const p = [lat, lng];
  return isValidPoint(p) ? p : null;
}

function isValidPoint(p) {
  return Array.isArray(p) && p.length === 2 &&
    Number.isFinite(p[0]) && Number.isFinite(p[1]) &&
    Math.abs(p[0]) <= 90 && Math.abs(p[1]) <= 180;
}

function makeStationIcon(isInterchange = false) {
  return L.divIcon({
    className: 'metro-station-icon-wrap',
    html: `<span class="metro-station-dot${isInterchange ? ' is-interchange' : ''}"></span>`,
    iconSize: [16, 16],
    iconAnchor: [8, 8],
  });
}

function getRouteSegments(osmData) {
  const relations = new Map((osmData?.elements || [])
    .filter((element) => element.type === 'relation')
    .map((element) => [element.id, element]));

  return ROUTES.map((route) => {
    const relation = relations.get(route.relationId);
    const segments = (relation?.members || [])
      .filter((member) => member.type === 'way' && Array.isArray(member.geometry))
      .map((member) => member.geometry
        .map((p) => [Number(p.lat), Number(p.lon)])
        .filter(isValidPoint))
      .filter((segment) => segment.length > 1);

    return { ...route, segments };
  });
}

async function fetchWithTimeout(url, query, timeoutMs = 18000) {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8' },
      body: `data=${encodeURIComponent(query)}`,
      signal: controller.signal,
    });
    if (!response.ok) throw new Error(`Overpass returned HTTP ${response.status}`);
    return await response.json();
  } finally {
    window.clearTimeout(timer);
  }
}

async function loadMetroRoutes() {
  // Query both route relations as one union, and request geometry for every member way.
  const geometryQuery = `
    [out:json][timeout:25];
    (
      relation(9571557);
      relation(10659365);
    );
    out geom;
  `;
  let lastError;
  for (const endpoint of OVERPASS_ENDPOINTS) {
    try {
      const result = await fetchWithTimeout(endpoint, geometryQuery || query);
      const routes = getRouteSegments(result);
      if (routes.some((route) => route.segments.length > 0)) return routes;
      lastError = new Error('Metro route geometry was not returned by OpenStreetMap.');
    } catch (error) {
      lastError = error;
    }
  }
  throw lastError || new Error('Could not load metro route data.');
}

function FitMetroRoutes({ routes }) {
  const map = useMap();
  useEffect(() => {
    const points = routes.flatMap((route) => route.segments.flat());
    if (points.length > 1) {
      // Do not force a zoom change: the metro overlay should not disrupt the user's map view.
      map.invalidateSize();
    }
  }, [map, routes]);
  return null;
}

export default function MetroRoutesLayer({ stations = [], visible = true }) {
  const [routes, setRoutes] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [enabledLines, setEnabledLines] = useState({ orange: true, aqua: true });

  const validStations = useMemo(() => {
    const normalized = (Array.isArray(stations) ? stations : [])
      .map((station, index) => ({
        station,
        position: toPoint(station),
        key: station.id ?? station._id ?? `${station.name || 'station'}-${index}`,
      }))
      .filter((item) => item.position);
    return normalized;
  }, [stations]);

  useEffect(() => {
    if (!visible || routes.length) return undefined;
    let cancelled = false;
    setLoading(true);
    setError('');
    loadMetroRoutes()
      .then((data) => {
        if (!cancelled) setRoutes(data);
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err?.name === 'AbortError'
            ? 'Metro route request timed out. Check your connection and retry.'
            : 'Metro lines could not be loaded. OpenStreetMap/Overpass may be unavailable.');
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [visible, routes.length]);

  if (!visible) return null;

  const hasRouteLines = routes.some((route) => route.segments.length > 0);

  return (
    <>
      <Pane name="metro-route-casing" style={{ zIndex: 405 }}>
        {routes.filter((route) => enabledLines[route.id]).flatMap((route) =>
          route.segments.map((segment, index) => (
            <Polyline
              key={`${route.id}-casing-${index}`}
              positions={segment}
              pathOptions={{
                color: '#ffffff',
                weight: 9,
                opacity: 0.92,
                lineCap: 'round',
                lineJoin: 'round',
                interactive: false,
              }}
            />
          ))
        )}
      </Pane>

      <Pane name="metro-route-lines" style={{ zIndex: 410 }}>
        {routes.filter((route) => enabledLines[route.id]).flatMap((route) =>
          route.segments.map((segment, index) => (
            <Polyline
              key={`${route.id}-line-${index}`}
              positions={segment}
              pathOptions={{
                color: route.color,
                weight: 5,
                opacity: 0.96,
                lineCap: 'round',
                lineJoin: 'round',
              }}
            >
              <Tooltip sticky>{route.name}</Tooltip>
              <Popup>
                <strong>{route.name}</strong>
                <div>{route.terminals}</div>
              </Popup>
            </Polyline>
          ))
        )}
      </Pane>

      <Pane name="metro-station-markers" style={{ zIndex: 650 }}>
        {validStations.map(({ station, position, key }) => {
          const name = station.name || station.station_name || 'Metro station';
          const isInterchange = /sitabuldi/i.test(name);
          return (
            <Marker
              key={key}
              position={position}
              icon={makeStationIcon(isInterchange)}
              riseOnHover
            >
              <Tooltip direction="top" offset={[0, -7]}>{name}</Tooltip>
              <Popup>
                <div className="metro-popup">
                  <strong>{name}</strong>
                  {station.address && <small>{station.address}</small>}
                  <small>Nagpur Metro station</small>
                </div>
              </Popup>
            </Marker>
          );
        })}
      </Pane>

      <FitMetroRoutes routes={routes} />

      <div className="metro-map-control" role="group" aria-label="Metro route layers">
        <div className="metro-control-title">Nagpur Metro</div>
        {ROUTES.map((route) => (
          <label className="metro-line-toggle" key={route.id}>
            <input
              type="checkbox"
              checked={Boolean(enabledLines[route.id])}
              onChange={(event) => setEnabledLines((previous) => ({
                ...previous,
                [route.id]: event.target.checked,
              }))}
            />
            <span className="metro-line-swatch" style={{ backgroundColor: route.color }} />
            <span>{route.name}</span>
          </label>
        ))}
        <div className="metro-route-status" aria-live="polite">
          {loading && 'Loading route lines…'}
          {!loading && hasRouteLines && 'Route lines loaded'}
          {!loading && !hasRouteLines && error && error}
          {!loading && !hasRouteLines && !error && 'Route lines not available'}
        </div>
      </div>
    </>
  );
}
