// Gallery modal
//
// We use the `gallery-modal` element for the modal and the `gallery-grid`
// element for the grid of images.

const _galleryModal  = document.getElementById('gallery-modal');
const _galleryGrid   = document.getElementById('gallery-grid');
const _galleryTitle  = document.getElementById('gallery-title');
const _galleryClose  = document.getElementById('gallery-close');

function openGallery(label, urls) {
  _galleryTitle.textContent = label + ' — ' + urls.length + ' photo' + (urls.length !== 1 ? 's' : '');
  _galleryGrid.innerHTML = urls.length
    ? urls.map(u => `<img src="${esc(u)}" loading="lazy" title="Open full size" data-url="${esc(u)}">`).join('')
    : '<p class="gallery-empty">No photos available.</p>';
  _galleryModal.removeAttribute('hidden');
}

window.openGallery = openGallery;

document.addEventListener('click', e => {
  const btn = e.target.closest('.popup-photo-btn');
  if (btn) {
    const urls = JSON.parse(btn.dataset.photos);
    openGallery('Photos', urls);
  }
});

document.querySelectorAll('.photo-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    const urls = JSON.parse(btn.dataset.photos);
    openGallery(btn.dataset.title, urls);
  });
});

_galleryGrid.addEventListener('click', e => {
  const img = e.target.closest('img[data-url]');
  if (img) window.open(img.dataset.url, '_blank');
});
_galleryClose.addEventListener('click', () => _galleryModal.setAttribute('hidden', ''));
_galleryModal.addEventListener('click', e => { if (e.target === _galleryModal) _galleryModal.setAttribute('hidden', ''); });

// Shared dimension helpers.

const _dimAbbr      = {traversability: 'T', connectivity: 'C', safety_comfort: 'S'};
const _dimTitle     = {traversability: 'Traversability', connectivity: 'Connectivity', safety_comfort: 'Safety & Comfort'};
const _dimChipLabel = {traversability: 'Trav', connectivity: 'Conn', safety_comfort: 'Safety'};
const _dimOrder     = ['traversability', 'connectivity', 'safety_comfort'];

function _dimPills(dims) {
  if (!Array.isArray(dims) || !dims.length) return '';
  return dims.map(d =>
    `<span class="dim-pill" title="${esc(_dimTitle[d] || d)}">${esc(_dimAbbr[d] || d[0].toUpperCase())}</span>`
  ).join('');
}

function _fmtScore(v) { return (v >= 0 ? '+' : '') + v.toFixed(2); }

function _scoreChip(label, val) {
  const c = divergingColor(val);
  return `<span class="score-chip">` +
    `<span class="score-dot score-dot-lg" style="background:${c};margin-right:0"></span>` +
    `<span style="color:#6c757d">${label}:</span> <strong>${_fmtScore(val)}</strong></span>`;
}

// Evidence modal.
//
// We can get or create the evidence modal by calling
// `getOrCreateEvidenceModal()`, which checks for an element with the ID
// `evidence-modal`.

function getOrCreateEvidenceModal() {
  let el = document.getElementById('evidence-modal');
  if (!el) {
    el = document.createElement('div');
    el.className = 'modal-overlay';
    el.id = 'evidence-modal';
    el.setAttribute('hidden', '');
    el.innerHTML =
      '<div class="modal-box" style="max-width:700px">' +
        '<div class="modal-header">' +
          '<span class="modal-title" id="evidence-modal-title">Evidence Details</span>' +
          '<button class="modal-close" id="evidence-modal-close">×</button>' +
        '</div>' +
        '<div id="evidence-modal-body" class="modal-scroll-body"></div>' +
      '</div>';
    document.body.appendChild(el);
    el.querySelector('#evidence-modal-close').addEventListener('click', () => el.setAttribute('hidden', ''));
    el.addEventListener('click', e => { if (e.target === el) el.setAttribute('hidden', ''); });
  }
  return el;
}

function showEvidenceModal(m) {
  const el = getOrCreateEvidenceModal();
  document.getElementById('evidence-modal-title').textContent =
    m.segment_label || m.segment_name || 'Evidence Details';

  const qev = m.quest_evidence || [];
  const nev = m.note_evidence || [];
  let html = '';

  // We'll use this section to build the summary bar for cluster scores.
  {
    const combined = m.score != null ? m.score : null;
    const qScore   = m.quest_score != null ? m.quest_score : null;
    const nScore   = m.note_score  != null ? m.note_score  : null;
    if (combined != null) {
      html += '<div class="score-chip-row">';
      html += _scoreChip('Combined', combined);
      if (qScore != null) html += _scoreChip('Quest', qScore);
      if (nScore != null) html += _scoreChip('Notes', nScore);
      const _dimScoreKey = {traversability: 'trav_score', connectivity: 'conn_score', safety_comfort: 'safety_score'};
      for (const d of _dimOrder) {
        if (m[_dimScoreKey[d]] != null) html += _scoreChip(_dimChipLabel[d], m[_dimScoreKey[d]]);
      }
      html += `<span style="font-size:.75rem;color:#adb5bd;margin-left:auto">${_asCount(m.quest_count)}Q &nbsp;${_asCount(m.note_count)}N</span>`;
      html += '</div>';
    }
    const conf = m.confidence != null ? m.confidence : null;
    if (conf != null) {
      const pct = Math.round(conf * 100);
      const confColor = conf >= 0.7 ? '#198754' : conf >= 0.4 ? '#ffc107' : '#dc3545';
      const subFmt = v => v != null ? Math.round(v * 100) + '%' : '?';
      html += '<div class="conf-detail">';
      html += `<div class="conf-detail-bar">` +
        `<span style="font-weight:600;color:#495057">Confidence</span>` +
        `<div style="flex:1;height:7px;background:#e9ecef;border-radius:4px;overflow:hidden">` +
          `<div style="width:${pct}%;height:100%;background:${confColor};border-radius:4px"></div>` +
        `</div>` +
        `<span style="font-weight:600;color:${confColor};min-width:36px;text-align:right">${pct}%</span>` +
        `</div>`;
      html += `<div class="conf-detail-subs">` +
        `<span title="Saturates at 10 evidence points">Quantity: ${subFmt(m.conf_quantity)}</span>` +
        `<span title="Low variance across evidence weights">Agreement: ${subFmt(m.conf_agreement)}</span>` +
        `<span title="Quest + note sources aligned">Corroboration: ${subFmt(m.conf_corroboration)}</span>` +
        `</div>`;
      html += '</div>';
    }
  }

  if (m.derived && m.derived_from && (qev.length || nev.length)) {
    html += `<div class="inferred-notice">` +
      `<strong>Inferred issue</strong> — evidence below was collected at the ` +
      `${esc(m.derived_from)}. This block face has no direct survey data; the ` +
      `connectivity score is propagated from that barrier.` +
      `</div>`;
  }

  if (qev.length) {
    html += '<h4 class="evidence-head">Quest Answers</h4>';
    html += '<table class="modal-table" style="margin-bottom:16px">';
    html += '<thead><tr>' +
      '<th style="width:30%">Tag</th>' +
      '<th style="width:12%">Answer</th>' +
      '<th>Interpretation</th>' +
      '<th style="white-space:nowrap">Dims</th>' +
      '<th style="text-align:right;white-space:nowrap;width:64px">Score</th>' +
      '<th style="text-align:right;white-space:nowrap;width:40px">×N</th>' +
      '</tr></thead><tbody>';
    for (const q of qev) {
      const w = q.weight != null ? q.weight : null;
      const wColor = w != null ? divergingColor(w) : '#adb5bd';
      const wStr   = w != null ? (w >= 0 ? '+' : '') + w.toFixed(2) : '—';
      const dimHtml = _dimPills(q.dimensions);
      const cStr = q.count != null ? _asCount(q.count) : '';
      html += '<tr>' +
        `<td style="font-family:monospace;font-size:.72rem;color:#6c757d;vertical-align:top;word-break:break-all">${esc(q.tag)}</td>` +
        `<td style="vertical-align:top">${esc(q.value)}</td>` +
        `<td style="color:#495057;vertical-align:top">${esc(q.label || '—')}</td>` +
        `<td style="vertical-align:top;white-space:nowrap">${dimHtml}</td>` +
        `<td style="text-align:right;white-space:nowrap;vertical-align:top">` +
          `<span class="score-dot score-dot-md" style="background:${wColor}"></span>` +
          `<span style="font-size:.78rem;font-variant-numeric:tabular-nums">${wStr}</span>` +
        `</td>` +
        `<td style="text-align:right;color:#adb5bd;font-size:.78rem;vertical-align:top;padding-right:0">${cStr}</td>` +
        '</tr>';
    }
    html += '</tbody></table>';
  }

  if (nev.length) {
    html += '<h4 class="evidence-head">Surveyor Notes</h4>';
    for (const n of nev) {
      const scoreStr = (n.score >= 0 ? '+' : '') + (n.score || 0).toFixed(2);
      const scoreColor = divergingColor(n.score || 0);
      const nDimHtml = _dimPills(n.dimensions);
      html += '<div class="note-card">';
      html += `<div class="note-card-hdr">` +
        `<span style="font-size:.75rem;color:#6c757d">Surveyor note${nDimHtml ? '&nbsp;' + nDimHtml : ''}</span>` +
        `<span style="font-size:.8rem;font-variant-numeric:tabular-nums">` +
          `<span class="score-dot score-dot-md" style="background:${scoreColor}"></span>` +
          `${scoreStr}</span>` +
        '</div>';
      if (n.text) html += `<p style="margin:0 0 4px;font-size:.85rem"><em>"${esc(n.text)}"</em></p>`;
      if (n.label && n.label !== n.text) html += `<p style="margin:0;font-size:.8rem;color:#6c757d">${esc(n.label)}</p>`;
      if (n.photos && n.photos.length) html += `<div style="margin-top:4px">${photoBtnHtml(n.photos)}</div>`;
      html += '</div>';
    }
  }

  if (!html) {
    html = '<p style="color:#6c757d;font-size:.85rem">No evidence details available. Re-run <code>--infer-issues</code> to populate evidence.</p>';
  }

  document.getElementById('evidence-modal-body').innerHTML = html;
  el.removeAttribute('hidden');
}

// Point modal opens when we click a single evidence point in evidence mode.

function showPointModal(p) {
  const el = getOrCreateEvidenceModal();
  const isNote = p.kind === 'note';
  document.getElementById('evidence-modal-title').textContent =
    isNote ? 'Surveyor Note' : 'Quest Answer';

  const wColor = divergingColor(p.weight || 0);

  // We derive per-dimension score breakdowns from note dimensions or tag
  // weights (quest).
  const dimChips = [];
  if (isNote) {
    for (const d of _dimOrder) {
      if ((p.dimensions || []).includes(d)) dimChips.push(_scoreChip(_dimChipLabel[d], p.weight || 0));
    }
  } else {
    const dimSum = {}, dimCount = {};
    for (const t of (p.tags || [])) {
      const tw = t.weight != null ? t.weight : 0;
      for (const d of (t.dimensions || [])) {
        dimSum[d] = (dimSum[d] || 0) + tw;
        dimCount[d] = (dimCount[d] || 0) + 1;
      }
    }
    for (const d of _dimOrder) {
      if (dimCount[d]) dimChips.push(_scoreChip(_dimChipLabel[d], dimSum[d] / dimCount[d]));
    }
  }

  let html = '<div class="score-chip-row">';
  html += _scoreChip('Score', p.weight || 0);
  html += dimChips.join('');
  html += '</div>';

  if (isNote) {
    const text = p.text || '';
    const noteDimHtml = _dimPills(p.dimensions);
    if (text || (p.photos && p.photos.length)) {
      html += `<div class="note-card">` +
        `<div class="note-card-hdr">` +
          `<span style="font-size:.75rem;color:#6c757d">Surveyor note${noteDimHtml ? '&nbsp;' + noteDimHtml : ''}</span>` +
          photoBtnHtml(p.photos) +
        `</div>` +
        (text ? `<p style="margin:0;font-size:.9rem"><em>"${esc(text)}"</em></p>` : '') +
        `</div>`;
    }
    if (p.label && p.label !== text) {
      html += `<p style="margin:8px 0 0;font-size:.85rem;color:#6c757d">${esc(p.label)}</p>`;
    }
  } else {
    const tags = p.tags || [];
    if (tags.length) {
      html += '<table class="modal-table"><thead><tr>' +
        '<th style="width:34%">Tag</th>' +
        '<th style="width:20%">Answer</th>' +
        '<th>Interpretation</th>' +
        '<th style="white-space:nowrap">Dims</th>' +
        '<th style="text-align:right;white-space:nowrap;width:64px">Score</th>' +
        '</tr></thead><tbody>';
      for (const t of tags) {
        const tw = t.weight != null ? t.weight : 0;
        const tc = divergingColor(tw);
        const ts = (tw >= 0 ? '+' : '') + tw.toFixed(2);
        html += '<tr>' +
          `<td style="font-family:monospace;font-size:.72rem;color:#6c757d;` +
            `word-break:break-all;vertical-align:top">${esc(t.tag)}</td>` +
          `<td style="vertical-align:top">${esc(t.value)}</td>` +
          `<td style="color:#495057;vertical-align:top">${esc(t.label || '')}</td>` +
          `<td style="vertical-align:top;white-space:nowrap">${_dimPills(t.dimensions)}</td>` +
          `<td style="text-align:right;white-space:nowrap;vertical-align:top">` +
            `<span class="score-dot score-dot-md" style="background:${tc}"></span>` +
            `<span style="font-size:.78rem;font-variant-numeric:tabular-nums">${ts}</span>` +
          `</td></tr>`;
      }
      html += '</tbody></table>';
    } else {
      html += `<p style="color:#495057">${esc(p.label || 'No detail available.')}</p>`;
    }
  }

  document.getElementById('evidence-modal-body').innerHTML = html;
  el.removeAttribute('hidden');
}

document.addEventListener('click', e => {
  const btn = e.target.closest('.evidence-btn');
  if (!btn) return;
  const m = _evidenceById[btn.dataset.eid];
  if (m) showEvidenceModal(m);
});

document.addEventListener('click', e => {
  const btn = e.target.closest('.evidence-table-btn');
  if (!btn) return;
  try {
    const m = JSON.parse(btn.dataset.m);
    showEvidenceModal(m);
  } catch (_) {}
});

// Methodology modal.
//
// We can access the methodology modal through `getOrCreateMethodologyModal()`,
// which checks for an element with the ID `methodology-modal` before creating
// it.

function getOrCreateMethodologyModal() {
  let el = document.getElementById('methodology-modal');
  if (!el) {
    el = document.createElement('div');
    el.className = 'modal-overlay';
    el.id = 'methodology-modal';
    el.setAttribute('hidden', '');

    const eg = (html) =>
      `<div class="methodology-eg"><span class="methodology-eg-lbl">Example &nbsp;</span>${html}</div>`;

    const body = `
<div class="modal-box" style="max-width:740px">
  <div class="modal-header">
    <span class="modal-title">How Infrastructure Scores Work</span>
    <button class="modal-close" id="methodology-modal-close">×</button>
  </div>
  <div class="modal-body-text">

    <h4 class="methodology-head">Score (−1 to +1)</h4>
    <p style="margin:0 0 8px">Each road segment receives a <strong>signed severity score</strong> on a −1 to +1 scale. Negative scores (red) indicate infrastructure problems; positive scores (green) indicate accessible, well-surveyed conditions; scores near zero (yellow) are neutral or mixed.</p>
    <p style="margin:0 0 8px">The Combined score is the <strong>dimension-weighted mean</strong> of the per-dimension scores below (Safety &amp; Comfort counts half) — <em>not</em> a flat average of every answer, and <em>not</em> deflated for low evidence counts. That uncertainty is captured separately in the Confidence metric.</p>
    ${eg(`A crossing where surveyors found <em>no curb ramps</em> (weight −0.90), <em>no marked crosswalk</em>
      (−0.80), and <em>no pedestrian signal</em> (−0.60) — all Connectivity answers — would score <strong>−0.77</strong> — shown in
      deep red. A crossing with all three present might score <strong>+0.73</strong> — shown in green.
      A surface type that is paved but not exceptional scores near <strong>0.00</strong> — yellow.`)}

    <h4 class="methodology-head">Dimensions</h4>
    <p style="margin:0 0 8px">Each segment is scored along up to three independent dimensions, in addition to a single <strong>Combined</strong> roll-up score.</p>
    <table class="modal-table">
      <thead><tr>
        <th style="width:28%">Dimension</th>
        <th>What it captures</th>
        <th style="text-align:right;white-space:nowrap;width:80px">Roll-up wt.</th>
      </tr></thead>
      <tbody>
        <tr>
          <td><strong>Traversability</strong></td>
          <td style="color:#495057">Surface quality, obstacles, clear width, steps, incline — whether the path can be physically used.</td>
          <td style="text-align:right;color:#6c757d;padding-right:0">1.0×</td>
        </tr>
        <tr>
          <td><strong>Connectivity</strong></td>
          <td style="color:#495057">Curb ramps, crossing markings, pedestrian signals, network continuity — whether the path is reachable and connects to the broader network.</td>
          <td style="text-align:right;color:#6c757d;padding-right:0">1.0×</td>
        </tr>
        <tr>
          <td><strong>Safety &amp; Comfort</strong></td>
          <td style="color:#495057">Lighting, handrails, shade, shelter, traffic buffering — conditions that affect how safe and comfortable the path feels to use.</td>
          <td style="text-align:right;color:#6c757d;padding-right:0">0.5×</td>
        </tr>
      </tbody>
    </table>
    <p style="margin:0 0 8px;font-size:.82rem;color:#6c757d">The Combined score is the weighted mean across whichever dimensions have evidence. Safety &amp; Comfort is weighted at half the others because it describes quality of experience rather than basic access — important for planning but less urgent than a missing curb ramp.</p>
    <p style="margin:0 0 8px;font-size:.82rem;color:#6c757d">If the survey's quest definition doesn't include questions for a dimension, that dimension is marked <strong>Not assessed</strong> and its column is hidden rather than showing a misleading zero.</p>
    <p style="margin:0 0 14px;font-size:.82rem;color:#6c757d">Use the <strong>dimension toggle buttons</strong> above the map to recolour segments by Traversability, Connectivity, or Safety &amp; Comfort instead of the Combined score.</p>

    <h4 class="methodology-head">Evidence Sources</h4>
    <table class="modal-table">
      <thead><tr>
        <th style="width:14%">Badge</th>
        <th style="width:24%">Source</th>
        <th>How scored</th>
      </tr></thead>
      <tbody>
        <tr>
          <td><span class="badge">Q</span></td>
          <td><strong>Quest answers</strong></td>
          <td style="color:#495057">Surveyors tap structured answers on their phones. An AI model reads the survey design once and assigns a severity weight (and dimension) to each possible answer. Each answer is also attributed to the specific named block-face side where it was collected.</td>
        </tr>
        <tr>
          <td><span class="badge">N</span></td>
          <td><strong>Surveyor notes</strong></td>
          <td style="color:#495057">Surveyors type free-text observations. An AI model reads each note, rates it from −1 (serious problem) to +1 (excellent condition), classifies it into one or more dimensions, and filters out non-infrastructure entries like "Driveway" or "Test".</td>
        </tr>
      </tbody>
    </table>
    ${eg(`A surveyor taps <em>"No"</em> when asked whether curb ramps are present → quest weight −0.90 (Connectivity).
      A different surveyor at the same corner writes <em>"Wheelchair users have no way to cross here"</em> → note score −0.85 (Connectivity).
      Connectivity score: average of −0.90 and −0.85 = <strong>−0.88</strong>.`)}
    <p style="margin:-6px 0 14px;font-size:.82rem;color:#6c757d">Evidence is grouped by the specific block-face side (e.g. <em>east side of F Street between 28th &amp; 29th</em>) so that opposite sidewalks on the same road are scored independently.</p>

    <h4 class="methodology-head">Inferred Issues</h4>
    <p style="margin:0 0 8px">Connectivity is a network property: a missing curb ramp at an intersection doesn't just affect the crossing itself — it also cuts off the sidewalk blocks that lead to it. When a connectivity barrier is detected, a decayed penalty (<strong>×0.5</strong>) is automatically propagated one hop to adjacent block faces that have no direct evidence of their own.</p>
    <p style="margin:0 0 14px;font-size:.82rem;color:#6c757d">Inferred segments are shown with a <strong>dashed line</strong> on the map and an <strong>inferred</strong> badge in the table. Their confidence is capped at 25% — treat them as leads to verify in the field, not confirmed findings.</p>

    <h4 class="methodology-head">Confidence (0 – 100%)</h4>
    <p style="margin:0 0 8px">A raw score tells you <em>what</em> was found; confidence tells you <em>how sure we are</em>. It combines three factors (weighted 40 / 40 / 20):</p>
    <table class="modal-table">
      <thead><tr>
        <th style="width:26%">Factor</th>
        <th style="width:8%">Wt.</th>
        <th>What it measures</th>
      </tr></thead>
      <tbody>
        <tr>
          <td><strong>Quantity</strong></td>
          <td style="color:#6c757d">40%</td>
          <td style="color:#495057">How many <em>independent surveyors</em> reported here — counted by person, not by tap, so one surveyor answering the same question repeatedly still counts once. Reaches full score at 3 or more (a thorough block survey rarely fields more). <span style="color:#6c757d">1 voice → 58% · 2 → 82% · 3+ → 100%.</span></td>
        </tr>
        <tr>
          <td><strong>Agreement</strong></td>
          <td style="color:#6c757d">40%</td>
          <td style="color:#495057">How consistently the evidence points the same way, measured <em>within each dimension</em> so a real problem on one dimension next to good conditions on another isn't mistaken for disagreement. Needs at least two independent surveyors — a lone observation has nothing to agree with, so its agreement is 0.</td>
        </tr>
        <tr>
          <td><strong>Corroboration</strong></td>
          <td style="color:#6c757d">20%</td>
          <td style="color:#495057">Whether the two independent data types (quest answers and surveyor notes) tell the same story. <span style="color:#6c757d">Both agree → 100% · one type only → 60% · they conflict → 20%.</span></td>
        </tr>
      </tbody>
    </table>
    ${eg(`<strong>High confidence (98%):</strong> 3 surveyors all independently tapped "No curb ramps" at the same corner,
      and a note agreed. Full quantity, everyone agreed, and both source types corroborate.<br>
      <strong>Low confidence (35%):</strong> only 1 surveyor visited. A single observation has no independent
      corroboration, so agreement contributes nothing.
      This location is a <em>lead worth verifying in the field</em> — not a confirmed finding.`)}
    <p style="margin:-6px 0 14px;font-size:.82rem;color:#6c757d">Confidence below ~40% is shown in red in the Evidence Details panel. Treat those segments as leads, not conclusions.</p>

    <h4 class="methodology-head">Ranking</h4>
    <p style="margin:0 0 8px">Segments are ranked by combining severity and confidence: <strong>|score| × confidence</strong>. This means a moderately bad location with strong evidence can outrank a seemingly worse location that only one person visited.</p>
    ${eg(`<strong>Corner A</strong> — score −0.90 (serious), but only 1 surveyor visited → confidence 35%
      → effective rank value 0.32.<br>
      <strong>Corner B</strong> — score −0.65 (moderately serious), 3 surveyors all agreed → confidence 92%
      → effective rank value 0.60.<br>
      Corner B ranks first. We know the problem at B is real. Corner A is flagged but needs a follow-up visit before action is taken.`)}

    <h4 class="methodology-head">Map Display</h4>
    <p style="margin:0 0 6px">Segment line <strong>colour</strong> reflects the active score dimension — red for problems, yellow for neutral, green for good conditions. Line <strong>opacity</strong> reflects confidence — a bold, solid line means the finding is well-evidenced; a faint, semi-transparent line means fewer surveyors visited or their observations were inconsistent. <strong>Dashed lines</strong> are inferred issues propagated from a nearby connectivity barrier.</p>
    <p style="margin:0 0 6px">Use the <strong>Combined / Trav / Conn / Safety</strong> buttons in the layer controls to recolour all segments by a specific dimension. Segments with no data for the selected dimension appear grey.</p>
    <p style="margin:0">Click any segment on the map to see the full Evidence Details: dimension scores, individual answer weights and their dimension tags, and the original surveyor note text.</p>

  </div>
</div>`;

    el.innerHTML = body;
    document.body.appendChild(el);
    el.querySelector('#methodology-modal-close').addEventListener('click', () => el.setAttribute('hidden', ''));
    el.addEventListener('click', e => { if (e.target === el) el.setAttribute('hidden', ''); });
  }
  return el;
}

document.addEventListener('click', e => {
  if (!e.target.closest('.method-info-btn')) return;
  getOrCreateMethodologyModal().removeAttribute('hidden');
});
