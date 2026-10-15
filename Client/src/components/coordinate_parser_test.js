import { parseCoordinates } from "./lib/routeCoordinates";

console.assert(
  JSON.stringify(parseCoordinates("20.949411, 79.029834")) ===
  JSON.stringify({ lat: 20.949411, lng: 79.029834 }),
  "Decimal coordinates should parse locally"
);
console.assert(
  JSON.stringify(parseCoordinates("20.949411 79.029834")) ===
  JSON.stringify({ lat: 20.949411, lng: 79.029834 }),
  "Space-separated coordinates should parse locally"
);
console.log("Coordinate parser checks passed.");
