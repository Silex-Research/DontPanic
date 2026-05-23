// ── JARVIS — Capability Center Page Module ──
// Static review surface for the V0b `dontpanic capabilities status`
// envelope. Reads from Jarvis.state.capabilities, which core.js loads
// from `state/capabilities-status.json`. No Firebase dependency.
//
// All rendering logic lives in lib/capabilities-logic.js so it can be
// imported and tested directly without round-tripping through this IIFE.

import { renderCapabilityCenterHTML } from '../../lib/capabilities-logic.js';

(() => {
  let _el = null;

  function render(state) {
    if (!_el) return;
    _el.innerHTML = renderCapabilityCenterHTML(state ? state.capabilities : null);
  }

  Jarvis.registerPage({
    id: 'capabilities',
    label: 'Capability Center',

    init(state) {
      _el = Jarvis.getPageEl('capabilities');
      render(state);
    },

    onActivate(state) {
      render(state);
    },
  });
})();
