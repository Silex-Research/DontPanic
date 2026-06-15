// ── JARVIS — Operator Channels Page Module (plan 2026-06-14-001 F010) ──
// Renders the Operator Channels panel from the channel-view model (F009
// producer, dashboard/state/operator-channels.json). Read-only. All rendering
// lives in lib/operator-channels-panel.js, which consumes the F009 LOCKED rule
// matrix (deriveBuckets) — this IIFE only wires DOM lifecycle.

import { renderOperatorChannelsPanelHTML } from '../../lib/operator-channels-panel.js';

(() => {
  let _el = null;

  function render(state) {
    if (!_el) return;
    const channelView = state ? state.operatorChannels : null;
    // `now` for the active/stale boundary is the live wall clock; the locked
    // threshold + precedence live in operator-channels-logic.js, not here.
    _el.innerHTML = renderOperatorChannelsPanelHTML(channelView, { now: Date.now() });
  }

  Jarvis.registerPage({
    id: 'operator-channels',
    label: 'Operator Channels',

    init(state) {
      _el = Jarvis.getPageEl('operator-channels');
      if (!_el) return;
      render(state);
    },

    onActivate(state) {
      render(state);
    },
  });
})();
