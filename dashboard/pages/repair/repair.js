// ── DontPanic — Repair Page Module (plan 2026-06-04-006 F006) ──
// Two operator surfaces over the 005 render-gate output, both scope-aware:
//   • "Repair automatically" — copies the `repair apply --safe-derived-state`
//     command for the selected scope (derived-state batch ONLY; the stronger
//     --safe --confirm tier is never offered here).
//   • "Copy agent repair plan" — copies the F003 agent-handoff bundle JSON.
//
// The page is read-only. Like the What Now page it does NOT mutate state or run
// commands; the copy buttons write a command / bundle to the clipboard so the
// operator (or their agent) runs it. All rendering + classification lives in
// `lib/repair-logic.js`; this IIFE only wires DOM lifecycle + the copy handler.

import {
  deriveRepairView,
  renderRepairPageHTML,
} from '../../lib/repair-logic.js';
import { ALL_PROJECTS_VALUE } from '../../lib/project-selector-logic.js';

(() => {
  let _el = null;
  let _boundEl = null;
  let _clickHandler = null;

  function itemsFor(state, selected) {
    // Prefer the fleet what-now envelope when present; fall back to the
    // single-repo whatNow payload. Filter by the selected project unless
    // All Projects is active (fleet/global aggregate shows everything).
    const env = (state && state.fleetWhatNow) || (state && state.whatNow) || null;
    const items = env && Array.isArray(env.items) ? env.items : [];
    if (selected === ALL_PROJECTS_VALUE) return items;
    return items.filter((it) => (it && it.project_name) === selected);
  }

  function render(state) {
    if (!_el) return;
    const selected =
      state && typeof state.selectedProject === 'string'
        ? state.selectedProject
        : ALL_PROJECTS_VALUE;
    const scope =
      selected === ALL_PROJECTS_VALUE ? 'fleet' : `project:${selected}`;
    // The repair surface is derived from the same fixture inputs the loader hands us:
    //  env present? + a preserved load/parse error? (Plan 2026-06-05-003 F003.)
    const env = (state && state.fleetWhatNow) || (state && state.whatNow) || null;
    const errored = !!(env && env.error);
    const view = deriveRepairView({
      items: itemsFor(state, selected),
      envPresent: !!env,
      errored,
      scope,
    });
    _el.innerHTML = renderRepairPageHTML(view);
  }

  function attachCopyHandler() {
    if (!_el) return;
    if (_clickHandler && _boundEl === _el) return;
    _clickHandler = (ev) => {
      const target = ev.target;
      if (!target || target.classList == null) return;
      // F003 — the component CopyCommand button (.copy-cmd-btn). Legacy
      // .repair-copy-btn kept for safety during the migration.
      if (
        !target.classList.contains('copy-cmd-btn') &&
        !target.classList.contains('repair-copy-btn')
      ) {
        return;
      }
      const text = target.dataset.copy || '';
      // Read-only contract: copying a command never mutates dashboard state.
      // Feedback lands in the aria-live sibling (the F001 .copy-cmd-feedback span)
      // when present, otherwise on the button itself (legacy control).
      const feedback = target.parentElement
        ? target.parentElement.querySelector('.copy-cmd-feedback')
        : null;
      const setFeedback = (copiedState, msg) => {
        target.dataset.copied = copiedState;
        if (feedback) feedback.textContent = msg;
      };
      const nav = typeof navigator !== 'undefined' ? navigator : null;
      if (nav && nav.clipboard && typeof nav.clipboard.writeText === 'function') {
        nav.clipboard
          .writeText(text)
          .then(() => {
            setFeedback('1', 'Copied ✓');
            setTimeout(() => {
              target.dataset.copied = '';
              if (feedback) feedback.textContent = '';
            }, 1500);
          })
          .catch(() => {
            setFeedback('denied', 'Copy blocked — select and copy manually');
          });
      } else {
        setFeedback('unsupported', 'Clipboard unavailable — copy manually');
      }
    };
    _el.addEventListener('click', _clickHandler);
    _boundEl = _el;
  }

  Jarvis.registerPage({
    id: 'repair',
    label: 'Repair',

    init(state) {
      _el = Jarvis.getPageEl('repair');
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
