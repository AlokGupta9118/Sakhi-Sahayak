
import { useEffect, useMemo, useState } from 'react';
import {
  Marker,
  Pane,
  Polyline,
  Popup,
  Tooltip,
  useMap,
} from 'react-leaflet';
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


const API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL ||
  'http://localhost:5001'
).replace(/\/+$/, '');

async function loadMetroRoutes() {
  const response = await fetch(`${API_BASE_URL}/api/metro-routes`);

  if (!response.ok) {
    throw new Error(`Metro route API returned HTTP ${response.status}`);
  }

  const osmData = await response.json();
  const routes = getRouteSegments(osmData);

  if (!routes.some((route) => route.segments.length > 0)) {
    throw new Error('Metro route geometry was not returned.');
  }

  return routes;
}

function isValidPoint(point) {
  return (
    Array.isArray(point) &&
    point.length === 2 &&
    Number.isFinite(point[0]) &&
    Number.isFinite(point[1]) &&
    Math.abs(point[0]) <= 90 &&
    Math.abs(point[1]) <= 180
  );
}

function toPoint(item) {
  if (Array.isArray(item?.center) && item.center.length >= 2) {
    const point = [
      Number(item.center[0]),
      Number(item.center[1]),
    ];

    return isValidPoint(point) ? point : null;
  }

  const lat = Number(item?.lat ?? item?.latitude);
  const lng = Number(
    item?.lng ?? item?.lon ?? item?.longitude
  );

  // Reject missing coordinates instead of converting null to zero.
  if (
    item?.lat == null && item?.latitude == null &&
    item?.lng == null && item?.lon == null &&
    item?.longitude == null
  ) {
    return null;
  }

  const point = [lat, lng];
  return isValidPoint(point) ? point : null;
}

function makeStationIcon(isInterchange = false) {
  return L.divIcon({
    className: 'metro-station-icon-wrap',
    html: `<span class="metro-station-dot${
      isInterchange ? ' is-interchange' : ''
    }"></span>`,
    iconSize: [16, 16],
    iconAnchor: [8, 8],
  });
}

function getRouteSegments(osmData) {
  const relations = new Map(
    (osmData?.elements || [])
      .filter((element) => element.type === 'relation')
      .map((element) => [element.id, element])
  );

  return ROUTES.map((route) => {
    const relation = relations.get(route.relationId);

    const segments = (relation?.members || [])
      .filter(
        (member) =>
          member.type === 'way' &&
          Array.isArray(member.geometry)
      )
      .map((member) =>
        member.geometry
          .map((point) => [
            Number(point.lat),
            Number(point.lon),
          ])
          .filter(isValidPoint)
      )
      .filter((segment) => segment.length > 1);

    return { ...route, segments };
  });
}


function FitMetroRoutes({ routes }) {
  const map = useMap();

  useEffect(() => {
    const points = routes.flatMap((route) =>
      route.segments.flat()
    );

    if (points.length > 1) {
      // Preserve the user's current map view.
      map.invalidateSize();
    }
  }, [map, routes]);

  return null;
}

export default function MetroRoutesLayer({
  stations = [],
  visible = true,
}) {
  const [routes, setRoutes] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [enabledLines, setEnabledLines] = useState({
    orange: true,
    aqua: true,
  });

  const validStations = useMemo(() => {
    return (Array.isArray(stations) ? stations : [])
      .map((station, index) => ({
        station,
        position: toPoint(station),
        key:
          station.id ??
          station._id ??
          `${station.name || 'station'}-${index}`,
      }))
      .filter((item) => item.position);
  }, [stations]);

  useEffect(() => {
    if (!visible || routes.length > 0) {
      return undefined;
    }

    const controller = new AbortController();
    let cancelled = false;

    async function fetchRoutes() {
      setLoading(true);
      setError('');

      try {
        const data = await loadMetroRoutes(controller.signal);

        if (!cancelled) {
          setRoutes(data);
        }
      } catch (err) {
        if (cancelled || err?.name === 'AbortError') {
          return;
        }

        console.error('Failed to load Nagpur Metro routes:', err);

        setError(
          'Metro lines are temporarily unavailable. Please try again later.'
        );
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    fetchRoutes();

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [visible, routes.length]);

  if (!visible) {
    return null;
  }

  const hasRouteLines = routes.some(
    (route) => route.segments.length > 0
  );

  return (
    <>
      <Pane
        name="metro-route-casing"
        style={{ zIndex: 405 }}
      >
        {routes
          .filter((route) => enabledLines[route.id])
          .flatMap((route) =>
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

      <Pane
        name="metro-route-lines"
        style={{ zIndex: 410 }}
      >
        {routes
          .filter((route) => enabledLines[route.id])
          .flatMap((route) =>
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

      <Pane
        name="metro-station-markers"
        style={{ zIndex: 650 }}
      >
        {validStations.map(({ station, position, key }) => {
          const name =
            station.name ||
            station.station_name ||
            'Metro station';

          const isInterchange = /sitabuldi/i.test(name);

          return (
            <Marker
              key={key}
              position={position}
              icon={makeStationIcon(isInterchange)}
              riseOnHover
            >
              <Tooltip direction="top" offset={[0, -7]}>
                {name}
              </Tooltip>

              <Popup>
                <div className="metro-popup">
                  <strong>{name}</strong>

                  {station.address && (
                    <small>{station.address}</small>
                  )}

                  <small>Nagpur Metro station</small>
                </div>
              </Popup>
            </Marker>
          );
        })}
      </Pane>

      <FitMetroRoutes routes={routes} />

      <div
        className="metro-map-control"
        role="group"
        aria-label="Metro route layers"
      >
        <div className="metro-control-title">
          Nagpur Metro
        </div>

        {ROUTES.map((route) => (
          <label
            className="metro-line-toggle"
            key={route.id}
          >
            <input
              type="checkbox"
              checked={Boolean(enabledLines[route.id])}
              onChange={(event) =>
                setEnabledLines((previous) => ({
                  ...previous,
                  [route.id]: event.target.checked,
                }))
              }
            />

            <span
              className="metro-line-swatch"
              style={{ backgroundColor: route.color }}
            />

            <span>{route.name}</span>
          </label>
        ))}

        <div
          className="metro-route-status"
          aria-live="polite"
        >
          {loading && 'Loading metro lines…'}

          {!loading && hasRouteLines && 'Route lines loaded'}

          {!loading && !hasRouteLines && error && error}

          {!loading && !hasRouteLines && !error &&
            'Route lines not available'}
        </div>
      </div>
    </>
  );
}
