// ── DontPanic — Operator Console (plan 2026-06-06-001 F006) ──
// The default view of the operator-console workbench: the left-pane triage queue
// + top status bar, rendered from the F001 triage MODEL (state.operatorTriage,
// the same operator_triage serialization the CLI `dontpanic operator brief`
// reads — one model, many renderers). Read-only; shows the ALL unique live
// human items with non-human buckets collapsed to counts. No raw JSON; no cap.
//
// When the model state file is absent (no `dashboard build`), it renders an
// honest empty state pointing at the command, like the other surfaces.

import {
  deriveConsoleView,
  renderConsoleDefaultHTML,
} from '../../lib/operator-console-logic.js';

(() => {
  let _el = null;

  function render(state) {
    if (!_el) return;
    const model = state && state.operatorTriage;
    if (!model || !Array.isArray(model.items)) {
      _el.innerHTML =
        '<div class="console-empty">No triage model yet. Build it: ' +
        '<code>dontpanic dashboard build --project all</code></div>';
      return;
    }
    _el.innerHTML = renderConsoleDefaultHTML(deriveConsoleView(model));
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
