// We listen for the Escape key to close all modals and collapse any expanded
// map.
document.addEventListener('keydown', e => {
  if (e.key !== 'Escape') return;
  const gallMod = document.getElementById('gallery-modal');
  if (gallMod) gallMod.setAttribute('hidden', '');
  const evMod = document.getElementById('evidence-modal');
  if (evMod) evMod.setAttribute('hidden', '');
  const methMod = document.getElementById('methodology-modal');
  if (methMod) methMod.setAttribute('hidden', '');
  const expandedMap = document.querySelector('.map-view.map-expanded');
  if (expandedMap) {
    expandedMap.classList.remove('map-expanded');
    document.querySelector('.map-backdrop').classList.remove('active');
    const btn = expandedMap.querySelector('.map-expand-btn');
    if (btn) { btn.title = 'Expand map'; btn.innerHTML = '&#x26F6;'; }
  }
});

// Quest answer accordion
document.querySelectorAll('tr.q-row').forEach(row => {
  row.addEventListener('click', () => {
    const isOpen = row.classList.toggle('open');
    document.querySelectorAll(`tr.q-val-row[data-group="${row.dataset.group}"]`)
      .forEach(r => r.classList.toggle('open', isOpen));
  });
});

// We use this click listener to toggle between raw tag views and readable quest
// views in the popup.
document.addEventListener('click', e => {
  const btn = e.target.closest('.popup-toggle');
  if (!btn) return;
  const scope = btn.closest('.popup-page') ?? btn.closest('.leaflet-popup-content') ?? btn.parentElement;
  const raw = scope.querySelector('.popup-raw');
  const readable = scope.querySelector('.popup-readable');
  if (!raw || !readable) return;
  const showingReadable = readable.style.display !== 'none';
  raw.style.display = showingReadable ? '' : 'none';
  readable.style.display = showingReadable ? 'none' : '';
  btn.textContent = showingReadable ? 'Quest' : 'Tags';
});

// Popup version pagination
document.addEventListener('click', e => {
  const btn = e.target.closest('.popup-prev, .popup-next');
  if (!btn) return;
  const container = btn.closest('.popup-versioned');
  if (!container) return;
  const pages = [...container.querySelectorAll(':scope > .popup-page')];
  const cur = pages.findIndex(p => p.style.display !== 'none');
  const next = cur + (btn.classList.contains('popup-next') ? 1 : -1);
  if (next < 0 || next >= pages.length) return;
  // We need to preserve whether the user is viewing Tags or Quests when we
  // switch pages.
  const curRaw = pages[cur].querySelector('.popup-raw');
  const showingRaw = curRaw ? curRaw.style.display !== 'none' : false;
  pages[cur].style.display = 'none';
  pages[next].style.display = '';
  const popupEl = container.closest('.leaflet-popup');
  if (popupEl) moveCloseBtnIntoHeader(popupEl);
  const nextRaw = pages[next].querySelector('.popup-raw');
  const nextReadable = pages[next].querySelector('.popup-readable');
  const nextToggle = pages[next].querySelector('.popup-toggle');
  if (nextRaw && nextReadable) {
    nextRaw.style.display = showingRaw ? '' : 'none';
    nextReadable.style.display = showingRaw ? 'none' : '';
    if (nextToggle) nextToggle.textContent = showingRaw ? 'Quest' : 'Tags';
  }
});
