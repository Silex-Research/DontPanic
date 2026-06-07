// ── DontPanic — Cockpit (plan 2026-06-06-005 F002) ──
// The DEFAULT landing surface. Mounts the redesign components (renderQueue +
// renderInspectPanel from components/cockpit.js) over the LIVE fleet triage model
// (state.operatorTriage — the F001 operator-triage/v0 model; one model, many
// renderers). Read-only: clicking a queue card opens the inspect-why panel; no
// resolution executes here (the gate/armed-terminal flow is plan 008). When the
// model is absent it renders an honest empty state, never a fabricated queue.
//
// Mounting only — the existing tabs (Operator, What Now, Repair, …) stay registered
// and navigable. This page leads pageModules so it is the landing surface; the
// 3-domain IA regroup (nav-ia.js) is a separate feature (plan 006).

import { renderQueue, renderInspectPanel } from '../../components/cockpit.js';

(() => {
  let _el = null;
  let _model = null;
  let _selectedId = null;
  let _clickBound = false;

  function modelItems() {
    return _model && Array.isArray(_model.items) ? _model.items : [];
  }

  function findItem(id) {
    return modelItems().find((i) => String(i.id) === String(id)) || null;
  }

  function inspectPane() {
    return _el && _el.querySelector('.dp-cockpit-inspect');
  }

  function renderInspect() {
    const pane = inspectPane();
    if (!pane) return;
    const item = _selectedId != null ? findItem(_selectedId) : null;
    if (item) {
      pane.replaceChildren(renderInspectPanel(item));
    } else {
      const hint = document.createElement('div');
      hint.className = 'dp-inspect-hint';
      hint.textContent = 'Select an item to inspect why it needs you.';
      pane.replaceChildren(hint);
    }
  }

  function render(state) {
    if (!_el) return;
    _model = state && state.operatorTriage;

    // Honest empty/missing-state — the model is the source of truth; never invent a queue.
    if (!_model || !Array.isArray(_model.items)) {
      const empty = document.createElement('div');
      empty.className = 'dp-cockpit-empty';
      empty.innerHTML =
        'No triage model yet. Build it: ' +
        '<code>dontpanic dashboard build --project all</code>';
      _el.replaceChildren(empty);
      return;
    }

    const layout = document.createElement('div');
    layout.className = 'dp-cockpit-layout';

    const queue = renderQueue(_model);
    queue.classList.add('dp-cockpit-queue');

    const pane = document.createElement('div');
    pane.className = 'dp-cockpit-inspect';

    layout.appendChild(queue);
    layout.appendChild(pane);
    _el.replaceChildren(layout);

    // keep the selection across re-renders if the item is still present
    if (_selectedId != null && !findItem(_selectedId)) _selectedId = null;
    renderInspect();
    attachClick();
  }

  // Read-only: clicking a card surfaces its inspect-why panel. Resolution
  // affordances carry their intent on the dataset for the future action layer
  // (plan 008) but execute nothing here.
  function attachClick() {
    if (!_el || _clickBound) return;
    _el.addEventListener('click', (ev) => {
      const t = ev.target;
      if (!t || !t.closest) return;
      const card = t.closest('[data-item-id]');
      if (!card) return;
      _selectedId = card.dataset.itemId || null;
      renderInspect();
    });
    _clickBound = true;
  }

  Jarvis.registerPage({
    id: 'cockpit',
    label: 'Cockpit',
    init(state) {
      _el = Jarvis.getPageEl('cockpit');
      if (!_el) return;
      render(state);
    },
    onActivate(state) {
      render(state);
    },
  });
})();
