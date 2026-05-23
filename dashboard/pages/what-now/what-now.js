// ── JARVIS — What Now Page Module (plan 2026-05-23-004 F004) ──
// First-viewport operating surface for the operator-in-the-loop:
// gates needing approval, blocking/needs-setup capabilities, reconcile
// drift, active supervisors, and architecture staleness — each rendered
// as a single ActionItem card with an exact command and a copy control.
//
// The page is read-only. It does NOT mutate plan state, run commands,
// or expose drag/drop. Copy buttons write the raw command string to the
// clipboard so the operator runs it themselves.
//
// All rendering lives in `lib/what-now-logic.js`; this IIFE only wires
// DOM lifecycle + the copy-button click handler.

import { renderWhatNowHTML } from '../../lib/what-now-logic.js';

(() => {
  let _el = null;
  let _boundEl = null;
  let _clickHandler = null;

  function render(state) {
    if (!_el) return;
    _el.innerHTML = renderWhatNowHTML(state ? state.whatNow : null, {
      selectedProject: state ? state.selectedProject : undefined,
    });
  }

  function attachCopyHandler() {
    if (!_el) return;
    // If the IIFE's cached element was replaced (e.g. the page container
    // was rebuilt by a test resetting jsdom), drop the stale listener
    // reference and re-attach against the live element.
    if (_clickHandler && _boundEl === _el) return;
    _clickHandler = (ev) => {
      const target = ev.target;
      if (!target || target.classList == null) return;
      if (!target.classList.contains('wn-copy-btn')) return;
      const cmd = target.dataset.command || '';
      // navigator.clipboard is async; the read-only contract is preserved
      // because nothing here triggers a state change in the dashboard.
      const nav = (typeof navigator !== 'undefined') ? navigator : null;
      if (nav && nav.clipboard && typeof nav.clipboard.writeText === 'function') {
        nav.clipboard.writeText(cmd).then(() => {
          target.dataset.copied = '1';
          target.textContent = 'copied';
          setTimeout(() => {
            target.dataset.copied = '';
            target.textContent = 'copy';
          }, 1500);
        }).catch(() => {
          // Clipboard denied (sandbox / permissions): leave the visible
          // command intact so the operator can hand-select it.
          target.dataset.copied = 'denied';
        });
      } else {
        target.dataset.copied = 'unsupported';
      }
    };
    _el.addEventListener('click', _clickHandler);
    _boundEl = _el;
  }

  Jarvis.registerPage({
    id: 'what-now',
    label: 'What Now',

    init(state) {
      _el = Jarvis.getPageEl('what-now');
      if (!_el) return;
      render(state);
      attachCopyHandler();
    },

    onActivate(state) {
      render(state);
      attachCopyHandler();
    },
  });
})();
