// ── Architecture Page Module ──
// Plan 2026-05-24-002 F002 — shell, value-language copy, empty states.
//
// The page registers itself with the dashboard router as `architecture`
// and reads `state.architectureViewState` (loaded by core.js from
// `dashboard/state/architecture-view-state.json` with a per-project
// fallback). Rendering lives in `lib/architecture-logic.js`; this IIFE
// only wires DOM lifecycle and the copy-command click handler.
//
// The page is read-only. Copy buttons write the raw command string to
// the clipboard so the operator runs `dontpanic architecture regen
// --with-html` themselves; the dashboard never auto-regenerates.

import {
  renderArchitectureHTML,
  resolveArchitectureEnvelope,
} from '../../lib/architecture-logic.js';
import { ALL_PROJECTS_VALUE } from '../../lib/project-selector-logic.js';

(() => {
  let _el = null;
  let _boundEl = null;
  let _clickHandler = null;

  function render(state) {
    if (!_el) return;
    const selected = state && typeof state.selectedProject === 'string'
      ? state.selectedProject
      : ALL_PROJECTS_VALUE;
    // F002 (post-i0): pick the project-scoped cache when the operator
    // has a specific project selected, fall back to the single-repo /
    // fleet-default envelope when no per-project cache exists. The page
    // renderer still owns the missing-state shell when both are absent.
    const envelope = resolveArchitectureEnvelope({
      selectedProject: selected,
      single: state ? state.architectureViewState : null,
      byProject: state ? state.architectureViewStateByProject : null,
    });
    _el.innerHTML = renderArchitectureHTML(envelope, { selectedProject: selected });
  }

  function attachCopyHandler() {
    if (!_el) return;
    if (_clickHandler && _boundEl === _el) return;
    _clickHandler = (ev) => {
      const target = ev.target;
      if (!target || target.classList == null) return;
      if (!target.classList.contains('arch-copy-btn')) return;
      const cmd = target.dataset.command || '';
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
    id: 'architecture',
    label: 'Architecture',

    init(state) {
      _el = Jarvis.getPageEl('architecture');
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
