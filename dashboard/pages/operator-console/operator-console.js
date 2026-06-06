// ── DontPanic — Operator Console (plan 2026-06-06-001 F006-F009) ──
// The operator-console workbench, rendered from the F001 triage MODEL
// (state.operatorTriage — the same operator_triage serialization the CLI
// `dontpanic operator brief` reads; one model, many renderers). Read-only.
//   • Left pane (F006): status bar + the needs-you queue + collapsed handled line.
//   • Right pane (F007): the decision drawer + the why-hidden inspector.
//   • Affordances (F008): per-bucket copy/handoff — never execute (D018).
//   • Lifecycle (F009): Observer↔Operator mode, mark-as-run overlay, and a
//     refresh that detects producer change via the model's state_revision.
// Clicking a queue row populates the drawer. When the model is absent it renders
// an honest empty state.

import {
  deriveConsoleView,
  renderConsoleDefaultHTML,
  deriveInspectView,
  renderInspectHTML,
  deriveWhyHidden,
  renderWhyHiddenHTML,
  renderActivityStripHTML,
  renderModeToggleHTML,
  renderRefreshHTML,
  revisionChanged,
  reconcileMarkedRun,
  deriveParallelOps,
  renderParallelOpsBannerHTML,
  OBSERVER,
  OPERATOR,
} from '../../lib/operator-console-logic.js';

(() => {
  let _el = null;
  let _model = null;
  let _selectedId = null;
  let _mode = OPERATOR;            // workbench defaults to the actionable view
  let _markedRun = new Set();      // local mark-as-run overlay (GUI never executes)
  let _shownRevision = null;       // the model fingerprint currently displayed
  let _clickBound = false;

  function eventsFor(state) {
    const ev = state && state.eventActions;
    return ev && Array.isArray(ev.items) ? ev.items : [];
  }

  function renderInspectPane() {
    const pane = _el && _el.querySelector('#console-inspect-pane');
    if (pane) {
      pane.innerHTML = renderInspectHTML(
        deriveInspectView(_model, _selectedId),
        { mode: _mode, markedRun: [..._markedRun] },
      );
    }
  }

  function renderFromModel(model, opts = {}) {
    if (!_el) return;
    if (!model || !Array.isArray(model.items)) {
      _el.innerHTML =
        '<div class="console-empty">No triage model yet. Build it: ' +
        '<code>dontpanic dashboard build --project all</code></div>';
      return;
    }
    _model = model;
    const controls =
      '<div class="console-controls">' +
        renderModeToggleHTML(_mode) +
        renderRefreshHTML({ revisionChanged: !!opts.revisionChanged }) +
      '</div>';
    _el.innerHTML =
      controls +
      renderParallelOpsBannerHTML(deriveParallelOps(model)) +
      '<div class="console-workbench">' +
        '<div class="console-left">' + renderConsoleDefaultHTML(deriveConsoleView(model)) + '</div>' +
        '<div class="console-right">' +
          '<div id="console-inspect-pane">' +
            renderInspectHTML(deriveInspectView(model, _selectedId), { mode: _mode, markedRun: [..._markedRun] }) +
          '</div>' +
          '<details class="console-why-hidden"><summary>Why the rest is hidden</summary>' +
            renderWhyHiddenHTML(deriveWhyHidden(model)) + '</details>' +
        '</div>' +
      '</div>' +
      renderActivityStripHTML(model, _lastEvents);
    markSelectedRow();
    attachSelectHandler();
    _shownRevision = model.state_revision || null;
  }

  let _lastEvents = [];
  function render(state) {
    _lastEvents = eventsFor(state);
    renderFromModel(state && state.operatorTriage, { revisionChanged: false });
  }

  function markSelectedRow() {
    if (!_el || !_selectedId) return;
    const row = _el.querySelector(`.console-item-select[data-item-id="${CSS && CSS.escape ? CSS.escape(_selectedId) : _selectedId}"]`);
    if (row) row.classList.add('is-selected');
  }

  // Copying writes to the clipboard — it NEVER runs anything (D018). Same
  // read-only contract as the Repair page.
  function handleCopy(btn) {
    const text = btn.dataset.copy || '';
    const feedback = btn.parentElement ? btn.parentElement.querySelector('.copy-cmd-feedback') : null;
    const set = (state, msg) => { btn.dataset.copied = state; if (feedback) feedback.textContent = msg; };
    const nav = typeof navigator !== 'undefined' ? navigator : null;
    if (nav && nav.clipboard && typeof nav.clipboard.writeText === 'function') {
      nav.clipboard.writeText(text).then(() => set('1', 'Copied ✓')).catch(() => set('denied', 'Copy blocked — select and copy manually'));
    } else {
      set('unsupported', 'Clipboard unavailable — copy manually');
    }
  }

  // Refresh re-pulls the model and flags whether the producer state moved (by
  // state_revision); reconciles the mark-as-run overlay against the fresh model.
  function doRefresh() {
    const f = typeof fetch === 'function' ? fetch : null;
    if (!f) return;
    f('state/operator-triage.json')
      .then((resp) => (resp && resp.ok ? resp.json() : null))
      .then((fresh) => {
        if (!fresh) return;
        const changed = revisionChanged(fresh, _shownRevision);
        const recon = reconcileMarkedRun([..._markedRun], fresh);
        _markedRun = new Set(recon.stillPresent); // drop marks the producer cleared
        renderFromModel(fresh, { revisionChanged: changed });
      })
      .catch(() => {});
  }

  function attachSelectHandler() {
    if (!_el || _clickBound) return;
    _el.addEventListener('click', (ev) => {
      const t = ev.target;
      if (!t || !t.closest) return;

      const copyBtn = t.closest('.copy-cmd-btn');
      if (copyBtn) { handleCopy(copyBtn); return; }

      const modeBtn = t.closest('.mode-toggle-btn');
      if (modeBtn) {
        _mode = modeBtn.dataset.mode === OBSERVER ? OBSERVER : OPERATOR;
        renderFromModel(_model, { revisionChanged: false });
        return;
      }

      const markBtn = t.closest('.mark-run-btn');
      if (markBtn) {
        if (markBtn.dataset.markRun) _markedRun.add(markBtn.dataset.markRun);
        renderInspectPane();
        return;
      }

      if (t.closest('.refresh-btn')) { doRefresh(); return; }

      const row = t.closest('.console-item-select');
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
