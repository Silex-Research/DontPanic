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
  buildBundleFromItems,
  renderRepairControlsHTML,
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
    const items = itemsFor(state, selected);
    const bundle = buildBundleFromItems(items, scope);
    _el.innerHTML = renderRepairControlsHTML(bundle, scope);
  }

  function attachCopyHandler() {
    if (!_el) return;
    if (_clickHandler && _boundEl === _el) return;
    _clickHandler = (ev) => {
      const target = ev.target;
      if (!target || target.classList == null) return;
      if (!target.classList.contains('repair-copy-btn')) return;
      const text = target.dataset.copy || '';
      // Read-only contract: copying a command never mutates dashboard state.
      const nav = typeof navigator !== 'undefined' ? navigator : null;
      if (nav && nav.clipboard && typeof nav.clipboard.writeText === 'function') {
        nav.clipboard
          .writeText(text)
          .then(() => {
            const original = target.textContent;
            target.dataset.copied = '1';
            target.textContent = 'copied';
            setTimeout(() => {
              target.dataset.copied = '';
              target.textContent = original;
            }, 1500);
          })
          .catch(() => {
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
