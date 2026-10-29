// We match the Python ELEMENT_TYPE_COLORS palette here.
//
// Hotspot beacon markers reserve #dc3545 (Bootstrap red). We cannot assign this
// color to any element or quest type because it would confuse them with
// hotspots.
const ETYPE_COLORS = {
  "Sidewalks":     "#0d6efd",
  "Crossings":     "#fd7e14",
  "Bus Stops":     "#198754",
  "Curbs":         "#e83e8c",   // pink instead of red (#dc3545) to prevent hotspot confusion
  "Intersections": "#6f42c1",
  "Street Lamps":  "#ffc107",
};

const FALLBACK = ["#20c997","#d63384","#6610f2","#0dcaf0"];
const _colorCache = {};

function etypeColor(t) {
  if (ETYPE_COLORS[t]) return ETYPE_COLORS[t];
  if (!_colorCache[t]) _colorCache[t] = FALLBACK[Object.keys(_colorCache).length % FALLBACK.length];
  return _colorCache[t];
}

// We mirror the Python constants.SEVERITY_RAMP exactly. This diverging severity
// ramp maps a score of -1 to red, 0 to yellow, and +1 to green.
const SEVERITY_RAMP = [
  [-1.0, [220, 53,  69]],
  [-0.5, [253, 126, 20]],
  [ 0.0, [255, 193,  7]],
  [ 0.5, [100, 173, 80]],
  [ 1.0, [ 25, 135, 84]],
];

function divergingColor(score) {
  score = Math.max(-1, Math.min(1, score));

  for (let i = 0; i < SEVERITY_RAMP.length - 1; i++) {
    const [loS, loRgb] = SEVERITY_RAMP[i];
    const [hiS, hiRgb] = SEVERITY_RAMP[i + 1];

    if (score <= hiS) {
      const t = (score - loS) / (hiS - loS);
      const r = Math.round(loRgb[0] + (hiRgb[0] - loRgb[0]) * t);
      const g = Math.round(loRgb[1] + (hiRgb[1] - loRgb[1]) * t);
      const b = Math.round(loRgb[2] + (hiRgb[2] - loRgb[2]) * t);

      return `rgb(${r},${g},${b})`;
    }
  }

  const [, last] = SEVERITY_RAMP[SEVERITY_RAMP.length - 1];

  return `rgb(${last[0]},${last[1]},${last[2]})`;
}
