// We use this shared element as a backdrop when we expand maps.
const mapBackdrop = document.createElement('div');
mapBackdrop.className = 'map-backdrop';
document.body.appendChild(mapBackdrop);

document.querySelectorAll('.map-view[data-markers]').forEach(el => {
  const markers = JSON.parse(el.dataset.markers);
  const issueData = el.dataset.issues ? JSON.parse(el.dataset.issues) : [];
  const hotspotData = el.dataset.hotspots ? JSON.parse(el.dataset.hotspots) : [];
  const popupWidth = Math.max(260, Math.min(380, (el.offsetWidth || window.innerWidth) - 48));
  const map = L.map(el, {zoomControl: true, maxZoom: 22});
  L.maplibreGL({
    style: 'https://tiles.openfreemap.org/styles/positron',
  }).addTo(map);

  // We need a custom pane for issue layers to keep them below quest and note
  // markers. Because Leaflet's default `overlayPane` uses z-index 400, we set
  // the issues just below that value.
  map.createPane('issuesPane');
  map.getPane('issuesPane').style.zIndex = '390';
  // We place the `highlightPane` below the `issuesPane` so the selection halo
  // appears behind the segment.
  map.createPane('highlightPane');
  map.getPane('highlightPane').style.zIndex = '389';
  // We need these beacons to remain visible at all times, so we set their
  // z-index higher than markers (which use a `markerPane` value of 600).
  map.createPane('hotspotPane');
  map.getPane('hotspotPane').style.zIndex = '650';

  const _issueLayerData = new Map();     // Leaflet layer -> issue data object
  const _issueLayerByUid = {};           // `seg_uid` -> Leaflet layer (row->map linking)
  const _hotspotLayerData = new Map();   // Leaflet layer -> hotspot data object
  const activeEvidenceGroup = L.featureGroup();
  let _activeHighlight = null;           // halo polyline while segment selected
  let _savedVisibility = null;           // {q, n, hs} booleans before evidence mode
  let _inEvidenceMode = false;           // true while segment evidence shows
  let _restoreTimer = null;              // `setTimeout` cleanup handle

  // We populate the issues layer first so it renders beneath notes and quests.
  const issuesGroup = L.featureGroup();
  const goodIssueLayers = [];
  // We use parallel arrays to support dimension-recoloring, so each element
  // shares an index with `issueData`.
  const issueLayers = [];

  let activeDim = 'combined';  // 'combined' | 'trav' | 'conn' | 'safety'

  function _dimScore(m, dim) {
    if (dim === 'trav')   return m.trav_score;
    if (dim === 'conn')   return m.conn_score;
    if (dim === 'safety') return m.safety_score;
    return m.score;   // 'combined'
  }

  // We shift polylines laterally by mOffset meters so north/south or east/west
  // pairs on one road don't overlap during rendering.
  function _offsetGeom(latlngs, side, mOffset) {
    if (!latlngs || latlngs.length < 2 || !side || side === 'nearby') return latlngs;
    const n = latlngs.length;
    const midLat = latlngs[Math.floor(n / 2)][0] * Math.PI / 180;
    const cosLat = Math.cos(midLat) || 1;
    // We calculate the average geographic direction vector for the road.
    let dE = 0, dN = 0;
    for (let i = 0; i < n - 1; i++) {
      dN += latlngs[i + 1][0] - latlngs[i][0];
      dE += (latlngs[i + 1][1] - latlngs[i][1]) * cosLat;
    }
    const glen = Math.sqrt(dE * dE + dN * dN) || 1;
    const eE = dE / glen, eN = dN / glen;  // unit road direction (East, North)
    // We find the left perpendicular by rotating 90° CCW, which gives us (-eN,
    // eE) for East and North.
    const pE = -eN, pN = eE;
    // We scale the results to mOffset meters by converting the coordinates to
    // Δlat and Δlon.
    const DEG = mOffset / 111320;
    const dLat = pN * DEG;
    const dLon = pE * DEG / cosLat;
    // We'll determine the sign based on which side qualifies as left for the
    // current road bearing.
    const bearing = Math.atan2(eE, eN) * 180 / Math.PI;
    let leftSide;
    if      (bearing >=  45 && bearing <  135) leftSide = 'north';
    else if (bearing >= 135 || bearing < -135) leftSide = 'east';
    else if (bearing >= -135 && bearing < -45) leftSide = 'south';
    else                                        leftSide = 'west';
    const sign = side === leftSide ? 1 : -1;
    return latlngs.map(([lat, lon]) => [lat + sign * dLat, lon + sign * dLon]);
  }

  function _recolorIssueLayers() {
    issueData.forEach((m, i) => {
      const layer = issueLayers[i];
      if (!layer) return;
      const val = _dimScore(m, activeDim);
      const color = val != null ? divergingColor(val) : '#adb5bd';
      const conf = m.confidence != null ? m.confidence : 1.0;
      const opacity = val != null ? (0.35 + 0.55 * conf) : 0.2;
      if (layer.setStyle) layer.setStyle({color, opacity, fillColor: color, fillOpacity: opacity});
    });
  }

  issueData.forEach((m, idx) => {
    const color = divergingColor(m.score || 0);
    const popup = makeIssuePopup(m);
    // We use confidence to determine opacity, while color indicates the
    // magnitude and direction of the score.
    const conf = m.confidence != null ? m.confidence : 1.0;
    const opacity = 0.35 + 0.55 * conf;
    // We use a dashed line for derived issues so we can distinguish them from
    // other types.
    const dashArray = m.derived ? '14 8' : undefined;
    let layer;
    if (m.segment_geom && m.segment_geom.length >= 2) {
      // We shift north/south (and east/west) pairs sideways to prevent overlap.
      const geom = _offsetGeom(m.segment_geom, m.segment_side, 6);
      m._displayGeom = geom;  // we store this to reuse it during highlighting
      layer = L.polyline(geom, {
        color, weight: 7, opacity, pane: 'issuesPane',
        ...(dashArray ? {dashArray} : {}),
      }).bindPopup(popup, {maxWidth: popupWidth, minWidth: 220});
    } else {
      m._displayGeom = null;
      // We use a small circle as a fallback when road geometry doesn't exist.
      layer = L.circleMarker([m.lat, m.lon], {
        radius: 8, fillColor: color, color: '#fff', weight: 1.5,
        fillOpacity: opacity, pane: 'issuesPane',
      }).bindPopup(popup, {maxWidth: popupWidth, minWidth: 220});
    }
    _issueLayerData.set(layer, m);
    if (m.seg_uid != null) _issueLayerByUid[m.seg_uid] = layer;
    issueLayers.push(layer);
    layer.addTo(issuesGroup);
    if (m.sign === 'good') goodIssueLayers.push(layer);
  });

  // Hotspot beacons layer emerges from consensus problem clusters.
  const hotspotsGroup = L.featureGroup();
  const _hotspotLayerByUid = {};   // `hs_uid` -> Leaflet layer (row->map linking)

  hotspotData.forEach(h => {
    const icon = hotspotIcon(h);
    const popup = buildHotspotPopup(h);
    const layer = L.marker([h.lat, h.lon], {icon, pane: 'hotspotPane'})
      .bindPopup(popup, {maxWidth: 320, minWidth: 200});
    if (h.hs_uid != null) _hotspotLayerByUid[h.hs_uid] = layer;
    _hotspotLayerData.set(layer, h);
    layer.addTo(hotspotsGroup);
  });

  // Quests layer contains markers for quest answers and diamonds for created
  // features.
  const questsGroup = L.featureGroup();
  // Notes layer contains markers for surveyor notes.
  const notesGroup = L.featureGroup();

  markers.forEach(m => {
    const popup = makePopup(m);
    if (m.kind === 'note') {
      L.circleMarker([m.lat, m.lon], {
        radius: 5, fillColor: '#6c757d',
        color: '#343a40', weight: 1.5, fillOpacity: 0.8
      }).bindPopup(popup, {maxWidth: popupWidth, minWidth: 260}).addTo(notesGroup);
    } else if (m.kind === 'create') {
      L.marker([m.lat, m.lon], {icon: diamondIcon(etypeColor(m.type))})
        .bindPopup(popup, {maxWidth: popupWidth, minWidth: 260}).addTo(questsGroup);
    } else {
      const qm = L.circleMarker([m.lat, m.lon], {
        radius: 7, fillColor: etypeColor(m.type),
        color: '#fff', weight: 1.5, fillOpacity: 0.85
      }).bindPopup(popup, {maxWidth: popupWidth, minWidth: 260}).addTo(questsGroup);
      if (m.geom) {
        let line = null;
        qm.on('popupopen', () => {
          line = L.polyline(m.geom, {
            color: etypeColor(m.type), weight: 4, opacity: 0.85,
          }).addTo(map);
        });
        qm.on('popupclose', () => {
          if (line) { map.removeLayer(line); line = null; }
        });
      }
    }
  });

  const hasIssues = issueData.length > 0;
  const hasGoodIssues = goodIssueLayers.length > 0;
  const hasHotspots = hotspotData.length > 0;

  // We add all layers to the map, starting with issues and ending with hotspots
  // so that hotspots maintain the highest z-order.
  if (hasIssues) issuesGroup.addTo(map);
  questsGroup.addTo(map);
  notesGroup.addTo(map);
  if (hasHotspots) hotspotsGroup.addTo(map);

  function _exitEvidenceMode() {
    _inEvidenceMode = false;
    if (_savedVisibility) {
      if (_savedVisibility.q) questsGroup.addTo(map);
      if (_savedVisibility.n) notesGroup.addTo(map);
      if (_savedVisibility.hs) hotspotsGroup.addTo(map);
      _savedVisibility = null;
    }
    if (_activeHighlight) { map.removeLayer(_activeHighlight); _activeHighlight = null; }
    map.removeLayer(activeEvidenceGroup);
    activeEvidenceGroup.clearLayers();
  }

  function _enterEvidenceMode(m, hideHotspots) {
    _inEvidenceMode = true;
    // We'll save visibility only on the first call so layers stay hidden when
    // we open evidence popups or switch segments.
    if (!_savedVisibility) {
      _savedVisibility = { q: questsOn, n: notesOn, hs: !!(hideHotspots && hotspotsOn) };
      if (questsOn) map.removeLayer(questsGroup);
      if (notesOn) map.removeLayer(notesGroup);
      if (hideHotspots && hotspotsOn) map.removeLayer(hotspotsGroup);
    }
    // We'll swap the halo for the geometry of the current segment.
    if (_activeHighlight) { map.removeLayer(_activeHighlight); _activeHighlight = null; }
    const hlGeom = m._displayGeom || m.segment_geom;
    if (hlGeom && hlGeom.length >= 2) {
      _activeHighlight = L.polyline(hlGeom, {
        color: '#0d6efd', weight: 13, opacity: 0.7,
        pane: 'highlightPane', interactive: false,
      }).addTo(map);
    }
    // We replace the evidence markers with points from the current segment.
    // When we click a marker, we open a modal instead of a Leaflet popup, which
    // means the parent segment popup remains visible while we view details.
    activeEvidenceGroup.clearLayers();
    const pts = m.evidence_points || [];
    pts.forEach(p => {
      const ptColor = divergingColor(p.weight);
      const isNote = p.kind === 'note';
      L.circleMarker([p.lat, p.lon], {
        radius: isNote ? 6 : 7,
        fillColor: ptColor,
        color: isNote ? '#fff' : ptColor,
        weight: isNote ? 2 : 1,
        fillOpacity: isNote ? 0.75 : 0.9,
      }).on('click', () => showPointModal(p)).addTo(activeEvidenceGroup);
    });
    if (pts.length) activeEvidenceGroup.addTo(map);
  }

  map.on('popupopen', e => {
    moveCloseBtnIntoHeader(e.popup.getElement());
    // We need to cancel pending deferred cleanup when a new popup opens before
    // the timer fires.
    if (_restoreTimer) { clearTimeout(_restoreTimer); _restoreTimer = null; }
    // We enter or refresh evidence mode when a popup opens for a hotspot beacon
    // or an issue segment.
    //
    // Because they represent separate concerns, issue segments hide hotspot
    // beacons. Hotspot beacons don't hide other hotspot markers since the
    // selected beacon is itself a hotspot.
    if (_issueLayerData.has(e.popup._source)) {
      _enterEvidenceMode(_issueLayerData.get(e.popup._source), true);
    } else if (_hotspotLayerData.has(e.popup._source)) {
      _enterEvidenceMode(_hotspotLayerData.get(e.popup._source), false);
    }
  });

  map.on('popupclose', e => {
    if (!_inEvidenceMode) return;
    // We defer cleanup because clicking an evidence marker may open a new popup
    // on the next tick. The `popupopen` handler cancels this timer when that
    // happens, so evidence mode stays active.
    _restoreTimer = setTimeout(() => { _restoreTimer = null; _exitEvidenceMode(); }, 0);
  });

  // We establish the initial map bounds using all visible layers.
  const allForBounds = L.featureGroup([
    ...questsGroup.getLayers(),
    ...notesGroup.getLayers(),
    ...(hasIssues ? issuesGroup.getLayers() : []),
    ...(hasHotspots ? hotspotsGroup.getLayers() : []),
  ]);
  if (allForBounds.getLayers().length) map.fitBounds(allForBounds.getBounds().pad(0.15));
  else map.setView([0, 0], 2);

  // We create a button to expand the map.
  const expandBtn = document.createElement('button');
  expandBtn.className = 'map-expand-btn';
  expandBtn.title = 'Expand map';
  expandBtn.innerHTML = '&#x26F6;';
  el.appendChild(expandBtn);

  function collapseMap() {
    el.classList.remove('map-expanded');
    mapBackdrop.classList.remove('active');
    expandBtn.title = 'Expand map';
    expandBtn.innerHTML = '&#x26F6;';
    setTimeout(() => map.invalidateSize(), 0);
  }
  function expandMap() {
    el.classList.add('map-expanded');
    mapBackdrop.classList.add('active');
    expandBtn.title = 'Restore map';
    expandBtn.innerHTML = '&#x2715;';
    setTimeout(() => map.invalidateSize(), 0);
  }
  expandBtn.addEventListener('click', () => {
    if (el.classList.contains('map-expanded')) collapseMap(); else expandMap();
  });
  mapBackdrop.addEventListener('click', collapseMap);

  // We create a flex row in the bottom-left for layer toggle buttons.
  const controls = document.createElement('div');
  controls.className = 'map-layer-controls';
  el.appendChild(controls);

  function makeLayerBtn(label) {
    const btn = document.createElement('button');
    btn.className = 'map-layer-btn';
    btn.textContent = label;
    controls.appendChild(btn);
    return btn;
  }

  function wireToggle(btn, featureGroup, getOn, setOn) {
    btn.addEventListener('click', () => {
      const on = !getOn();
      setOn(on);
      // We add the layer to the top of the stack when we turn it on, and we
      // remove it when we turn it off.
      if (on) featureGroup.addTo(map); else map.removeLayer(featureGroup);
      btn.classList.toggle('off', !on);
    });
  }

  let questsOn = true, notesOn = true, issuesOn = hasIssues, hotspotsOn = hasHotspots;

  const questsBtn = makeLayerBtn('🗺️ Quests');
  wireToggle(questsBtn, questsGroup, () => questsOn, v => { questsOn = v; });

  const notesBtn = makeLayerBtn('📝 Notes');
  wireToggle(notesBtn, notesGroup, () => notesOn, v => { notesOn = v; });

  if (hasHotspots) {
    const hotspotsBtn = makeLayerBtn('🚨 Hotspots');
    wireToggle(hotspotsBtn, hotspotsGroup, () => hotspotsOn, v => { hotspotsOn = v; });
  }

  if (hasIssues) {
    let goodBtn = null;
    const issuesBtn = makeLayerBtn('⚠️ Issues');
    wireToggle(issuesBtn, issuesGroup, () => issuesOn, v => {
      issuesOn = v;
      if (goodBtn) goodBtn.style.display = v ? '' : 'none';
    });

    if (hasGoodIssues) {
      let showGood = true;
      goodBtn = makeLayerBtn('✅ Good');
      goodBtn.title = 'Hide well-surveyed segments';
      goodBtn.addEventListener('click', () => {
        showGood = !showGood;
        goodIssueLayers.forEach(layer => {
          if (showGood) layer.addTo(issuesGroup); else issuesGroup.removeLayer(layer);
        });
        goodBtn.classList.toggle('off', !showGood);
        goodBtn.title = showGood ? 'Hide well-surveyed segments' : 'Show well-surveyed segments';
      });
    }

    // We only show the dimension score selector when issue data contains
    // dimension scores.
    const hasTrav   = issueData.some(m => m.trav_score   != null);
    const hasConn   = issueData.some(m => m.conn_score   != null);
    const hasSafety = issueData.some(m => m.safety_score != null);
    const hasDims   = hasTrav || hasConn || hasSafety;

    if (hasDims) {
      const spacer = document.createElement('span');
      spacer.className = 'layer-sep';
      controls.appendChild(spacer);

      const dimOptions = [
        { key: 'combined', label: '⊕ Combined' },
        ...(hasTrav   ? [{ key: 'trav',   label: 'Trav' }]   : []),
        ...(hasConn   ? [{ key: 'conn',   label: 'Conn' }]   : []),
        ...(hasSafety ? [{ key: 'safety', label: 'Safety' }] : []),
      ];

      const dimBtns = dimOptions.map(opt => {
        const btn = document.createElement('button');
        btn.className = 'map-layer-btn';
        btn.textContent = opt.label;
        btn.title = `Color issues by ${opt.label} score`;
        btn.style.fontWeight = opt.key === 'combined' ? '600' : '';
        if (opt.key === 'combined') btn.style.outline = '2px solid #0d6efd';
        controls.appendChild(btn);
        btn.addEventListener('click', () => {
          activeDim = opt.key;
          dimBtns.forEach((b, i) => {
            const active = dimOptions[i].key === opt.key;
            b.style.outline = active ? '2px solid #0d6efd' : '';
            b.style.fontWeight = active ? '600' : '';
          });
          _recolorIssueLayers();
        });
        return btn;
      });
    }
  }

  // When we click an issues-table row inside the same <section>, the map pans
  // to that segment and opens its popup. This action triggers evidence mode
  // through the existing popupopen handler.
  if (hasIssues) {
    const section = el.closest('section');
    if (section) {
      section.querySelectorAll('tr.issue-row[data-issue-uid]').forEach(row => {
        row.addEventListener('click', e => {
          // We ignore clicks that originate inside buttons (for instance, an
          // evidence button).
          if (e.target.closest('button')) return;
          const uid = row.dataset.issueUid;
          const layer = _issueLayerByUid[uid];
          if (!layer) return;

          // We re-enable the issues layer when the user has toggled it off.
          if (!issuesOn) {
            issuesOn = true;
            issuesGroup.addTo(map);
          }

          // We scroll the map into view so we can see the popup.
          el.scrollIntoView({behavior: 'smooth', block: 'nearest'});

          // We fit the bounds for polylines or pan to the center as a fallback
          // for circles.
          if (layer.getBounds) {
            map.fitBounds(layer.getBounds().pad(0.4));
          } else if (layer.getLatLng) {
            map.setView(layer.getLatLng(), Math.max(map.getZoom(), 16));
          }
          layer.openPopup();
        });
      });
    }
  }

  // When we click a row in the hotspot table, we fly to its beacon.
  if (hasHotspots) {
    const section = el.closest('section');
    if (section) {
      section.querySelectorAll('tr.hotspot-row[data-hotspot-uid]').forEach(row => {
        row.addEventListener('click', () => {
          const uid = row.dataset.hotspotUid;
          const layer = _hotspotLayerByUid[uid];
          if (!layer) return;

          // We need to re-enable the hotspots layer when the user toggles it
          // off.
          if (!hotspotsOn) {
            hotspotsOn = true;
            hotspotsGroup.addTo(map);
          }

          el.scrollIntoView({behavior: 'smooth', block: 'nearest'});
          map.setView(layer.getLatLng(), Math.max(map.getZoom(), 17));
          layer.openPopup();
        });
      });
    }
  }
});
