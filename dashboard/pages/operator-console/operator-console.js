// ── DontPanic — Operator Console (plan 2026-06-06-001 F006 + F007) ──
// The operator-console workbench, rendered from the F001 triage MODEL
// (state.operatorTriage — the same operator_triage serialization the CLI
// `dontpanic operator brief` reads; one model, many renderers). Read-only.
//   • Left pane (F006): status bar + the needs-you queue + collapsed handled line.
//   • Right pane (F007): the decision drawer (decide from evidence in place) +
//     the why-hidden inspector (audit the compression).
//   • Activity strip (F007): the raw→unique→need-you pipeline + recent actions.
// Clicking a queue row populates the drawer. F007 is inspect-only; F008 adds the
// copy/open affordances. When the model is absent it renders an honest empty state.

import {
  deriveConsoleView,
  renderConsoleDefaultHTML,
  deriveInspectView,
  renderInspectHTML,
  deriveWhyHidden,
  renderWhyHiddenHTML,
  renderActivityStripHTML,
} from '../../lib/operator-console-logic.js';

(() => {
  let _el = null;
  let _model = null;
  let _selectedId = null;
  let _clickBound = false;

  // Recent-action feed for the activity strip comes from the event-actions sidecar
  // when the loader has it; absent → just the pipeline line. Read-only.
  function eventsFor(state) {
    const ev = state && state.eventActions;
    return ev && Array.isArray(ev.items) ? ev.items : [];
  }

  function renderInspectPane() {
    const pane = _el && _el.querySelector('#console-inspect-pane');
    if (pane) pane.innerHTML = renderInspectHTML(deriveInspectView(_model, _selectedId));
  }

  function render(state) {
    if (!_el) return;
    const model = state && state.operatorTriage;
    if (!model || !Array.isArray(model.items)) {
      _el.innerHTML =
        '<div class="console-empty">No triage model yet. Build it: ' +
        '<code>dontpanic dashboard build --project all</code></div>';
      return;
    }
    _model = model;
    _el.innerHTML =
      '<div class="console-workbench">' +
        '<div class="console-left">' + renderConsoleDefaultHTML(deriveConsoleView(model)) + '</div>' +
        '<div class="console-right">' +
          '<div id="console-inspect-pane">' + renderInspectHTML(deriveInspectView(model, _selectedId)) + '</div>' +
          '<details class="console-why-hidden"><summary>Why the rest is hidden</summary>' +
            renderWhyHiddenHTML(deriveWhyHidden(model)) + '</details>' +
        '</div>' +
      '</div>' +
      renderActivityStripHTML(model, eventsFor(state));
    attachSelectHandler();
  }

  // Clicking a needs-you row populates the inspect pane — no navigation, no
  // mutation; F007 is inspect-only (F008 adds the copy/open affordances).
  function attachSelectHandler() {
    if (!_el || _clickBound) return;
    _el.addEventListener('click', (ev) => {
      const row = ev.target && ev.target.closest ? ev.target.closest('.console-item-select') : null;
      if (!row) return;
      _selectedId = row.dataset.itemId || null;
      _el.querySelectorAll('.console-item-select.is-selected').forEach((n) => n.classList.remove('is-selected'));
      row.classList.add('is-selected');
      renderInspectPane();
    });
    _clickBound = true;
  }

  Jarvis.registerPage({
    id: 'operator-console',
    label: 'Operator',

    init(state) {
      _el = Jarvis.getPageEl('operator-console');
      if (!_el) return;
      render(state);
    },

    onActivate(state) {
      render(state);
    },
  });
})();
