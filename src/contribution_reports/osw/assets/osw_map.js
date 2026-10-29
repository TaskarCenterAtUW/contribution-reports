// We use Leaflet layers to render touched OSW geometry. The app draws ways as
// polylines, but it routes node edits through a canvas renderer to maintain
// responsiveness in city-scale workspaces.
(function () {
  function esc(s) { return typeof s === 'string' ? s.replace(/&/g,'&amp;').replace(/</g,'&lt;') : (s ?? ''); }

  var COLORS = {
    create: '#198754', geometry_only: '#0d6efd', tags_only: '#6f42c1',
    both: '#fd7e14', delete: '#dc3545', no_op: '#adb5bd', modify: '#0d6efd'
  };
  var KIND_LABELS = {
    create: 'Created', delete: 'Deleted', geometry_only: 'Geometry only',
    tags_only: 'Tags only', both: 'Geometry + tags', no_op: 'No-op edit'
  };

  // We use a shared backdrop element when maps expand, which mirrors the
  // implementation in the AVIV report's *map.js*.
  var mapBackdrop = document.createElement('div');
  mapBackdrop.className = 'map-backdrop';
  document.body.appendChild(mapBackdrop);

  document.querySelectorAll('.osw-map').forEach(function (el) {
    var geometry = JSON.parse(el.dataset.geometry || '[]');
    var bbox = JSON.parse(el.dataset.bbox || 'null');
    var map = L.map(el, { maxZoom: 22 });
    L.maplibreGL({
      style: 'https://tiles.openfreemap.org/styles/positron',
    }).addTo(map);

    var canvas = L.canvas({ padding: 0.5 });
    var layers = {};
    var bounds = [];

    geometry.forEach(function (item) {
      var color = COLORS[item.kind] || COLORS[item.action] || '#6c757d';
      var layer;
      if (item.coords.length > 1) {
        layer = L.polyline(item.coords, { color: color, weight: 2, opacity: 0.8 });
      } else if (item.coords.length === 1) {
        layer = L.circleMarker(item.coords[0], {
          renderer: canvas, radius: 3, color: color, fillColor: color,
          fillOpacity: 0.7, weight: 1
        });
      } else { return; }
      layer.bindPopup('<strong>' + esc(item.entity || item.type) + '</strong><br>' +
                      esc(item.action) + (item.kind !== item.action ? ' (' + esc(KIND_LABELS[item.kind] || item.kind) + ')' : '') +
                      '<br>' + esc(item.type) + '/' + esc(item.id));
      (layers[item.kind] = layers[item.kind] || L.layerGroup()).addLayer(layer);
      item.coords.forEach(function (c) { bounds.push(c); });
    });

    Object.keys(layers).forEach(function (kind) { layers[kind].addTo(map); });
    if (Object.keys(layers).length > 1) {
      var overlays = {};
      Object.keys(layers).forEach(function (kind) {
        overlays[KIND_LABELS[kind] || kind] = layers[kind];
      });
      L.control.layers(null, overlays, { position: 'bottomleft' }).addTo(map);
    }

    if (bbox) { map.fitBounds([[bbox[1], bbox[0]], [bbox[3], bbox[2]]]); }
    else if (bounds.length) { map.fitBounds(bounds); }
    else { map.setView([47.6, -122.3], 11); }

    // We create the button used to expand the map.
    var expandBtn = document.createElement('button');
    expandBtn.className = 'map-expand-btn';
    expandBtn.title = 'Expand map';
    expandBtn.innerHTML = '&#x26F6;';
    el.appendChild(expandBtn);

    function collapseMap() {
      el.classList.remove('map-expanded');
      mapBackdrop.classList.remove('active');
      expandBtn.title = 'Expand map';
      expandBtn.innerHTML = '&#x26F6;';
      setTimeout(function () { map.invalidateSize(); }, 0);
    }
    function expandMap() {
      el.classList.add('map-expanded');
      mapBackdrop.classList.add('active');
      expandBtn.title = 'Restore map';
      expandBtn.innerHTML = '&#x2715;';
      setTimeout(function () { map.invalidateSize(); }, 0);
    }
    expandBtn.addEventListener('click', function () {
      if (el.classList.contains('map-expanded')) { collapseMap(); } else { expandMap(); }
    });
    mapBackdrop.addEventListener('click', collapseMap);
  });

  // Methodology modal
  var modal = document.querySelector('.osw-modal');
  var backdrop = document.querySelector('.osw-modal-backdrop');

  function setModal(open) {
    if (!modal || !backdrop) { return; }
    modal.classList.toggle('open', open);
    backdrop.classList.toggle('open', open);
  }

  document.querySelectorAll('.osw-method-btn').forEach(function (btn) {
    btn.addEventListener('click', function () { setModal(true); });
  });
  if (backdrop) { backdrop.addEventListener('click', function () { setModal(false); }); }
  var closeBtn = document.querySelector('.osw-modal-close');
  if (closeBtn) { closeBtn.addEventListener('click', function () { setModal(false); }); }
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') { setModal(false); }
  });
})();
