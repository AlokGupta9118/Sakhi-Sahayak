// src/lib/routeCoordinates.js
// Robustly resolves either "latitude, longitude" or a place name.
// Coordinates are parsed locally and NEVER sent to a geocoder.
export function parseCoordinates(value) {
  const input = String(value ?? "").trim();
  if (!input) return null;

  // Accept commas, spaces, and optional parentheses.
  const cleaned = input.replace(/^\s*\(/, "").replace(/\)\s*$/, "").trim();
  const match = cleaned.match(
    /^\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*[, ]\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*$/
  );

  if (!match) return null;

  const lat = Number(match[1]);
  const lng = Number(match[2]);

  if (!Number.isFinite(lat) || !Number.isFinite(lng) ||
      lat < -90 || lat > 90 || lng < -180 || lng > 180) {
    throw new Error(
      "Invalid coordinates. Use latitude between -90 and 90 and longitude between -180 and 180."
    );
  }

  return { lat, lng };
}

export async function resolveCoords(value, { signal } = {}) {
  const input = String(value ?? "").trim();
  if (!input) throw new Error("Enter a place name or coordinates.");

  const coordinates = parseCoordinates(input);
  if (coordinates) return coordinates;

  // Place names only. Nominatim is a public service; avoid rapid repeated requests.
  const query = /nagpur|maharashtra/i.test(input)
    ? input
    : `${input}, Nagpur, Maharashtra, India`;

  const url = new URL("https://nominatim.openstreetmap.org/search");
  url.search = new URLSearchParams({
    format: "jsonv2",
    limit: "1",
    countrycodes: "in",
    q: query,
  }).toString();

  const response = await fetch(url.toString(), {
    headers: { Accept: "application/json" },
    signal,
  });

  if (!response.ok) {
    throw new Error(`Place lookup failed (HTTP ${response.status}). Enter coordinates or try again.`);
  }

  const results = await response.json();
  if (!Array.isArray(results) || results.length === 0) {
    throw new Error(`Could not find "${input}". Try a nearby landmark or enter latitude, longitude.`);
  }

  const lat = Number(results[0].lat);
  const lng = Number(results[0].lon);
  if (!Number.isFinite(lat) || !Number.isFinite(lng) ||
      lat < -90 || lat > 90 || lng < -180 || lng > 180) {
    throw new Error("Place lookup returned invalid coordinates.");
  }
  return { lat, lng };
}
