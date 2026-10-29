function esc(s) { return typeof s === 'string' ? s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;') : (s ?? ''); }

// We need to convert count values from the cache into finite numbers before we
// interpolate them into popup HTML.
//
// Non-numeric strings--including any injected markup--become 0, which prevents
// cache-sourced values from reaching innerHTML via count fields.
function _asCount(v) {
  const n = Number(v);
  return Number.isFinite(n) ? n : 0;
}

function diamondIcon(color) {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14"><polygon points="7,1 13,7 7,13 1,7" fill="${color}" stroke="white" stroke-width="1.5"/></svg>`;
  return L.divIcon({ className: '', html: svg, iconSize: [14,14], iconAnchor: [7,7], popupAnchor: [0,-7] });
}

// We create pulsing beacon marker icons for consensus hotspots. We use
// box-shadow animations so the pulse ring maintains a fixed-pixel size instead
// of scaling with zoom, and because box-shadows don't affect pointer events,
// the ring never intercepts map clicks.
//
// We set `iconSize` to match the solid core so that only the dot acts as the
// Leaflet click target.
function hotspotIcon(h) {
  const count = h.count || 1;
  // We base the core diameter on report count, starting at 14px when count is 3
  // and capping at 24px for 10 or more reports.
  const coreSize = Math.round(Math.min(24, 14 + (count - 3) * 1.2));
  const half = Math.round(coreSize / 2);
  const html = `<div class="hotspot-core" style="width:${coreSize}px;height:${coreSize}px"></div>`;
  return L.divIcon({
    className: '',
    html,
    iconSize: [coreSize, coreSize],
    iconAnchor: [half, half],
    popupAnchor: [0, -half],
  });
}

function renderTagTable(tags) {
  if (!tags || !Object.keys(tags).length) return '';
  // We use semi-transparent semantic colors over the stripe to let the <tr>
  // background show through. We apply these colors to each <td> instead of the
  // <tr> to ensure opacity compositing works correctly.
  const RGBA = { add: 'rgba(208,246,240,0.65)', mod: 'rgba(253,239,211,0.65)', del: 'rgba(245,207,214,0.65)' };
  const STRIPE = '#e9ecef';
  let rows = '', ri = 0;
  for (const [k, vals] of Object.entries(tags)) {
    let semiBg = '', cell = '';
    if (!vals.old && vals.new != null) {
      semiBg = RGBA.add;
      cell = esc(vals.new);
    } else if (vals.old != null && !vals.new) {
      semiBg = RGBA.del;
      cell = esc(vals.old);
    } else if (vals.old !== vals.new) {
      semiBg = RGBA.mod;
      cell = `<span style="text-decoration:line-through;opacity:.55">${esc(vals.old)}</span> → ${esc(vals.new)}`;
    } else {
      cell = esc(vals.new);
    }
    const trStyle = ri % 2 === 1 ? `background:${STRIPE}` : '';
    const tdBg = `background:${semiBg || 'rgba(255,255,255,0.65)'};`;
    ri++;
    rows += `<tr style="${trStyle}">` +
      `<td style="${tdBg}color:#495057;padding-right:8px;vertical-align:top;word-break:break-word;width:50%">${esc(k)}</td>` +
      `<td style="${tdBg}word-break:break-word;overflow-wrap:break-word;width:50%">${cell}</td></tr>`;
  }
  return `<table style="font-size:.7rem;margin-top:4px;border-collapse:collapse;width:100%">${rows}</table>`;
}
