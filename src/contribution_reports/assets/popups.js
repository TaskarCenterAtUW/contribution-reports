// `makeIssuePopup()` writes to this evidence registry, which the evidence modal
// reads.
const _evidenceById = {};
let _evidenceSeq = 0;

function buildQuestPointPopup(p) {
  const wColor = divergingColor(p.weight);
  const wStr = (p.weight >= 0 ? '+' : '') + p.weight.toFixed(2);
  let html = '<div class="popup-body-md">';
  html += `<div class="popup-hdr" style="margin-bottom:6px">` +
    `<strong>Quest Answer</strong>` +
    `<span style="font-size:.78rem;font-variant-numeric:tabular-nums">` +
    `<span class="score-dot score-dot-md" style="background:${wColor}"></span>` +
    `${wStr}</span></div>`;
  const tags = p.tags || [];
  if (tags.length) {
    html += `<div style="max-height:200px;overflow-y:auto">`;
    html += `<table style="width:100%;border-collapse:collapse;font-size:.78rem">`;
    for (const t of tags) {
      const tw = t.weight != null ? t.weight : 0;
      const tc = divergingColor(tw);
      const ts = (tw >= 0 ? '+' : '') + tw.toFixed(2);
      html += `<tr>` +
        `<td style="padding:2px 6px 2px 0;color:#6c757d;font-family:monospace;font-size:.7rem;vertical-align:top;word-break:break-all">${esc(t.tag)}</td>` +
        `<td style="padding:2px 6px 2px 0;vertical-align:top;white-space:nowrap">${esc(t.value)}</td>` +
        `<td style="padding:2px 6px 2px 0;color:#495057;vertical-align:top">${esc(t.label || '')}</td>` +
        `<td style="padding:2px 0;white-space:nowrap;text-align:right;vertical-align:top">` +
        `<span class="score-dot score-dot-sm" style="background:${tc}"></span>` +
        `<span style="font-size:.75rem;font-variant-numeric:tabular-nums">${ts}</span></td>` +
        `</tr>`;
    }
    html += `</table></div>`;
  } else {
    html += `<p style="margin:0;color:#6c757d">${esc(p.label || '')}</p>`;
  }
  html += `</div>`;
  return html;
}

function buildNotePointPopup(p) {
  const wColor = divergingColor(p.weight);
  const wStr = (p.weight >= 0 ? '+' : '') + p.weight.toFixed(2);
  let html = '<div class="popup-body-sm">';
  html += `<div class="popup-hdr" style="margin-bottom:6px">` +
    `<strong>Surveyor Note</strong>` +
    `<span style="font-size:.78rem;font-variant-numeric:tabular-nums">` +
    `<span class="score-dot score-dot-md" style="background:${wColor}"></span>` +
    `${wStr}</span></div>`;
  if (p.text) html += `<p style="margin:0 0 4px;font-style:italic;color:#212529">"${esc(p.text)}"</p>`;
  if (p.label && p.label !== p.text) html += `<p style="margin:0;color:#6c757d;font-size:.8rem">${esc(p.label)}</p>`;
  html += `</div>`;
  return html;
}

function photoBtnHtml(photos) {
  return photos && photos.length
    ? `<button class="popup-photo-btn" data-photos="${JSON.stringify(photos).replace(/&/g,'&amp;').replace(/"/g, '&quot;')}" style="font-size:.8rem;padding:1px 5px;cursor:pointer;border:1px solid #dee2e6;border-radius:3px;background:#fff;flex-shrink:0">📷 ${photos.length}</button>`
    : '';
}

function makeVersionHtml(mType, mKind, v, pagerHtml) {
  pagerHtml = pagerHtml || '';
  const kindBadge = mKind === 'create' ? ' <em style="font-size:.8em;color:#6c757d">(created)</em>' : '';
  const userSpan = `<span style="color:#6c757d;font-size:.85em">${esc(v.user)}</span>`;
  const rawTable = renderTagTable(v.tags);
  const photoIcon = photoBtnHtml(v.photos);
  if (v.readable) {
    const readableTable = renderTagTable(v.readable);
    const toggleBtn = `<button class="popup-toggle" style="font-size:.7rem;padding:1px 5px;cursor:pointer;border:1px solid #dee2e6;border-radius:3px;background:#fff;flex-shrink:0">Tags</button>`;
    const header = `<div class="popup-hdr">` +
      `<span><b>${esc(mType)}</b>${kindBadge}</span>` +
      `<span style="display:flex;gap:4px;align-items:center">${pagerHtml}${photoIcon}${toggleBtn}</span>` +
      `</div>${userSpan}`;
    return header +
      `<div class="popup-raw" style="display:none;max-height:200px;overflow-y:auto">${rawTable}</div>` +
      `<div class="popup-readable" style="max-height:200px;overflow-y:auto">${readableTable}</div>`;
  }
  const header = `<div class="popup-hdr">` +
    `<span><b>${esc(mType)}</b>${kindBadge}</span>` +
    `<span style="display:flex;gap:4px;align-items:center">${pagerHtml}${photoIcon}</span>` +
    `</div>${userSpan}`;
  return header + `<div style="max-height:200px;overflow-y:auto">${rawTable}</div>`;
}

function makeNotePopup(m) {
  const userSpan = m.user ? `<span style="color:#6c757d;font-size:.85em">${esc(m.user)}</span>` : '';
  const header = `<div class="popup-hdr">` +
    `<span><b>Note</b></span>` +
    `<span style="display:flex;gap:4px;align-items:center">${photoBtnHtml(m.photos)}</span>` +
    `</div>${userSpan}`;
  const body = m.text
    ? `<div style="max-height:200px;overflow-y:auto;margin-top:4px;white-space:pre-line"><em>${esc(m.text)}</em></div>`
    : '';
  return header + body;
}

function makePopup(m) {
  if (m.kind === 'note') return makeNotePopup(m);
  // Markers that are created store photos, users, and tags on m instead of
  // using a versions array.
  if (!m.versions) {
    return makeVersionHtml(m.type, m.kind, m);
  }
  const versions = m.versions;
  if (versions.length === 1) {
    return makeVersionHtml(m.type, m.kind, versions[0]);
  }
  // We order versions so that page 1 is the oldest entry and page N is the
  // latest, then we load the last page by default.
  const n = versions.length;
  function pagerFor(i) {
    const prevDis = i === 0 ? ' disabled' : '';
    const nextDis = i === n - 1 ? ' disabled' : '';
    return `<div class="popup-pager">` +
      `<button class="popup-prev"${prevDis}>&#8249;</button>` +
      `<span class="popup-pager-lbl">${i + 1} / ${n}</span>` +
      `<button class="popup-next"${nextDis}>&#8250;</button>` +
      `</div>`;
  }
  const pages = versions.map((v, i) =>
    `<div class="popup-page"${i < n - 1 ? ' style="display:none"' : ''}>${makeVersionHtml(m.type, m.kind, v, pagerFor(i))}</div>`
  ).join('');
  return `<div class="popup-versioned">${pages}</div>`;
}

function moveCloseBtnIntoHeader(popupEl) {
  const closeBtn = popupEl.querySelector('a.leaflet-popup-close-button');
  if (!closeBtn) return;
  const content = popupEl.querySelector('.leaflet-popup-content');
  if (!content) return;
  const allPages = [...content.querySelectorAll('.popup-page')];
  const page = allPages.find(p => p.style.display !== 'none') ?? content;
  const btnGroup = page.querySelector(':scope > div > span[style*="flex"]');
  if (!btnGroup) return;
  // We hide the actual Leaflet close button inside the wrapper. Instead, we
  // place a proxy in the header, which Leaflet removes automatically when it
  // resets content.
  closeBtn.style.display = 'none';
  content.querySelectorAll('.popup-fake-close').forEach(el => el.remove());
  const fake = document.createElement('button');
  fake.className = 'popup-fake-close';
  fake.style.cssText = 'background:none;border:none;cursor:pointer;font-size:1.25rem;color:#adb5bd;padding:1px 5px;margin-top:-0.25rem;line-height:1;flex-shrink:0';
  fake.textContent = '×';
  fake.onclick = () => closeBtn.click();
  btnGroup.appendChild(fake);
}

function _buildSegChips(m) {
  // We generate compact chip HTML when `seg_ref` exists, otherwise we fall back
  // to a prose label.
  const ref = m.seg_ref;
  const color = divergingColor(m.score || 0);
  if (ref && ref.road) {
    let html = `<span class="road-name">${esc(ref.road)}</span>`;
    if (ref.side_letter) {
      const fg = _textOnColor(color);
      html += ` <span class="side-chip" style="background:${color};color:${fg}" title="${esc(ref.side)} side">${esc(ref.side_letter)}</span>`;
    }
    if (ref.cross_range) {
      html += ` <span class="cross-range">${esc(ref.cross_range)}</span>`;
    }
    return html;
  }
  return `<b>${esc(m.segment_label || m.segment_name || 'Unknown location')}</b>`;
}

// We determine whether black or white text provides better contrast against a
// hex background. This logic matches the `text_on_color()` function in the
// Python *constants.py* file.
function _textOnColor(hex) {
  const h = hex.replace('#', '');
  const r = parseInt(h.slice(0, 2), 16);
  const g = parseInt(h.slice(2, 4), 16);
  const b = parseInt(h.slice(4, 6), 16);
  function lin(c) { const s = c / 255; return s <= 0.04045 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4); }
  const lum = 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
  return lum < 0.35 ? '#fff' : '#212529';
}

function buildHotspotPopup(h) {
  const count = _asCount(h.count);
  const voices = _asCount(h.voices);
  const conf = h.confidence != null ? h.confidence : 0;
  const confPct = Math.round(conf * 100);
  const confColor = divergingColor(-0.5 * conf - 0.5);   // red spectrum, darker = more confident
  let html = `<div style="min-width:200px;max-width:300px">`;
  html += `<div style="display:flex;align-items:center;gap:6px;margin-bottom:4px">`;
  html += `<span style="font-size:1.1rem">🚨</span>`;
  html += `<span style="font-weight:600">${count} problem report${count !== 1 ? 's' : ''}` +
    ` from ${voices} surveyor${voices !== 1 ? 's' : ''}</span>`;
  html += `</div>`;
  const parts = [];
  const hq = _asCount(h.quest_count);
  if (hq) parts.push(`${hq} quest answer${hq !== 1 ? 's' : ''}`);
  const hn = _asCount(h.note_count);
  if (hn) parts.push(`${hn} note${hn !== 1 ? 's' : ''}`);
  if (parts.length) html += `<p style="margin:0 0 4px;font-size:.78rem;color:#6c757d">${parts.join(', ')}</p>`;
  html += `<div style="margin:6px 0;font-size:.75rem;display:flex;align-items:center;gap:6px">`;
  html += `<span style="color:#6c757d">Confidence:</span>`;
  html += `<span style="display:inline-block;width:48px;height:5px;background:#e9ecef;border-radius:3px;overflow:hidden">` +
    `<span style="display:block;width:${confPct}%;height:100%;background:#dc3545;border-radius:3px"></span></span>`;
  html += `<span style="color:#6c757d;font-variant-numeric:tabular-nums">${confPct}%</span>`;
  html += `</div>`;
  const pts = h.evidence_points || [];
  if (pts.length) {
    const row = (wc, inner) =>
      `<div style="display:flex;align-items:baseline;gap:4px;padding:2px 0;` +
      `border-bottom:1px solid #f1f3f5;font-size:.78rem">` +
      `<span class="score-dot score-dot-sm" style="background:${wc};flex-shrink:0"></span>` +
      inner + `</div>`;
    html += `<div style="margin-top:6px;max-height:140px;overflow-y:auto">`;
    for (const p of pts) {
      if (p.kind === 'note') {
        html += row(divergingColor(p.weight),
          `<span style="font-style:italic;color:#495057;flex:1">${esc(p.text || p.label || '')}</span>` +
          photoBtnHtml(p.photos));
      } else {
        // We need to list all problem answers recorded by this surveyor instead
        // of just a single entry.
        for (const t of (p.tags || [])) {
          html += row(divergingColor(t.weight),
            `<span style="color:#495057">${esc(t.label || t.value || '')}</span>`);
        }
      }
    }
    html += `</div>`;
  }
  html += `</div>`;
  return html;
}

function makeIssuePopup(m) {
  const sign = m.sign || 'neutral';
  const signIcon = sign === 'problem' ? '⚠️' : sign === 'good' ? '✅' : 'ℹ️';
  const scoreStr = (m.score >= 0 ? '+' : '') + (m.score || 0).toFixed(2);
  const color = divergingColor(m.score || 0);
  let html = `<div style="min-width:200px">`;
  html += `<div style="display:flex;align-items:center;gap:6px;margin-bottom:4px">`;
  html += `<span class="score-dot score-dot-xxl" style="background:${color};flex-shrink:0"></span>`;
  html += `<span style="flex:1">${_buildSegChips(m)}</span>`;
  html += `<span style="font-size:.8rem;color:#6c757d">${scoreStr}</span>`;
  html += `</div>`;
  if (m.label) {
    html += `<p style="margin:4px 0;font-size:.85rem">${signIcon} ${esc(m.label)}</p>`;
  }
  if (m.derived) {
    html += `<p style="margin:4px 0;font-size:.75rem;color:#856404;background:#fff3cd;padding:3px 6px;border-radius:4px">` +
      `⚠ Inferred${m.derived_from ? ': ' + esc(m.derived_from) : ''}` +
      `</p>`;
  }
  const dimRows = [
    ['Trav', m.trav_score],
    ['Conn', m.conn_score],
    ['Safety', m.safety_score],
  ].filter(([, v]) => v != null);
  if (dimRows.length) {
    html += `<p style="margin:4px 0;font-size:.75rem;display:flex;gap:8px">`;
    for (const [label, val] of dimRows) {
      const dc = divergingColor(val);
      const vs = (val >= 0 ? '+' : '') + val.toFixed(2);
      html += `<span style="white-space:nowrap">` +
        `<span class="score-dot score-dot-sm" style="background:${dc}"></span>` +
        `<span style="color:#6c757d">${label}:</span> ${vs}` +
        `</span>`;
    }
    html += `</p>`;
  }
  const parts = [];
  const mq = _asCount(m.quest_count);
  if (mq) parts.push(`${mq} quest answer${mq !== 1 ? 's' : ''}`);
  const mn = _asCount(m.note_count);
  if (mn) parts.push(`${mn} note${mn !== 1 ? 's' : ''}`);
  if (parts.length) {
    const hasEvidence = (m.quest_evidence && m.quest_evidence.length) ||
                        (m.note_evidence && m.note_evidence.length);
    if (hasEvidence) {
      const eid = 'evi-' + (++_evidenceSeq);
      _evidenceById[eid] = m;
      html += `<p style="margin:4px 0;font-size:.75rem">` +
        `<button class="evidence-btn" data-eid="${eid}">Evidence: ${parts.join(', ')}</button></p>`;
    } else {
      html += `<p style="margin:4px 0;font-size:.75rem;color:#6c757d">Evidence: ${parts.join(', ')}</p>`;
    }
  }
  html += `</div>`;
  return html;
}
