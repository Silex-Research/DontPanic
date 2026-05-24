// ── DontPanic — Health Page Module ──
// Honesty surface for install/setup/build health. Per copy-map.md §2.5
// every card must have a credible data source or a named missing-data
// state; never render an empty card as "OK".
//
// V0 (plan 2026-05-24-001 F003) composes capabilities, what-now,
// fleet-summary, and quota state into card-level Layer 1 messaging with
// Layer 2 source paths and fix commands. Fleet variant (D013) labels each
// card with its scope: global, project, or fleet.

import { renderHealthHTML } from '../../lib/health-logic.js';

(() => {
  let _el = null;

  function render(state) {
    if (!_el) return;
    _el.innerHTML = renderHealthHTML(state || {});
  }

  Jarvis.registerPage({
    id: 'health',
    label: 'Health',

    init(state) {
      _el = Jarvis.getPageEl('health');
      render(state);
    },

    onActivate(state) {
      render(state);
    },
  });
})();
