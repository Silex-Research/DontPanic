// ── DontPanic — Cockpit (plan 2026-06-06-005 F002 + F004) ──
// The DEFAULT landing surface. Mounts the redesign components (renderQueue +
// renderInspectPanel) over the LIVE fleet triage model (state.operatorTriage — the
// F001 operator-triage/v0 model). Read-only: clicking a queue card opens the
// inspect-why panel; no resolution executes here (the gate/armed-terminal flow is 008).
//
// F004 — honest state matrix. The Cockpit never shows a blank and never renders
// stale/errored state as fresh:
//   loading → skeleton; missing → "run dashboard build"; stale → a banner that admits
//   the age OVER the (demoted) queue; error → last-good UNDER an error banner + retry;
//   ready → the queue. classifyCockpitState (lib/cockpit-state.js) is the pure decision.
//
// Mounting only — the existing tabs stay registered (the IA regroup is plan 006).

import { renderQueue, renderInspectPanel } from '../../components/cockpit.js';
import { staleBanner } from '../../components/freshness.js';
import { classifyCockpitState } from '../../lib/cockpit-state.js';

(() => {
  let _el = null;
  let _lastGood = null;       // the last non-null model we successfully rendered
  let _selectedId = null;
  let _resolved = false;      // has a load resolved (model present OR explicitly null)?
  let _errored = false;       // did the last refresh fail?
  let _clickBound = false;

  function el(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  function modelItems(model) {
    return model && Array.isArray(model.items) ? model.items : [];
  }

  function findItem(model, id) {
    return modelItems(model).find((i) => String(i.id) === String(id)) || null;
  }

  // The shared two-pane workbench: an optional banner, the triage queue, and the
  // inspect-why pane. Re-used by ready/stale/error-with-last-good.
  function renderWorkbench(model, banner) {
    const wrap = el('div', 'dp-cockpit-wrap');
    if (banner) wrap.appendChild(banner);
    const layout = el('div', 'dp-cockpit-layout');
    const queue = renderQueue(model);
    queue.classList.add('dp-cockpit-queue');
    const pane = el('div', 'dp-cockpit-inspect');
    layout.appendChild(queue);
    layout.appendChild(pane);
    wrap.appendChild(layout);
    return { wrap, pane };
  }

  function renderInspectInto(pane, model) {
    if (!pane) return;
    const item = _selectedId != null ? findItem(model, _selectedId) : null;
    pane.replaceChildren(item ? renderInspectPanel(item) : el('div', 'dp-inspect-hint', 'Select an item to inspect why it needs you.'));
  }

  function paintSkeleton() {
    const sk = el('div', 'dp-cockpit-skeleton');
    sk.setAttribute('aria-busy', 'true');
    sk.appendChild(el('div', 'dp-skeleton-line dp-skeleton-hero'));
    for (let i = 0; i < 4; i += 1) sk.appendChild(el('div', 'dp-skeleton-line'));
    _el.replaceChildren(sk);
  }

  function paintMissing() {
    const empty = el('div', 'dp-cockpit-empty');
    empty.innerHTML = 'No triage model yet. Build it: <code>dontpanic dashboard build --project all</code>';
    _el.replaceChildren(empty);
  }

  function errorBanner() {
    const b = el('div', 'dp-error-banner');
    b.setAttribute('role', 'alert');
    b.appendChild(el('span', 'dp-error-text', _lastGood
      ? "Couldn't refresh the triage state — showing the last good copy."
      : "Couldn't load the triage state."));
    const retry = el('button', 'dp-cockpit-retry', 'Retry');
    retry.type = 'button';
    b.appendChild(retry);
    return b;
  }

  function paintError() {
    if (_lastGood) {
      const { wrap, pane } = renderWorkbench(_lastGood, errorBanner());
      _el.replaceChildren(wrap);
      if (_selectedId != null && !findItem(_lastGood, _selectedId)) _selectedId = null;
      renderInspectInto(pane, _lastGood);
    } else {
      const box = el('div', 'dp-cockpit-error');
      box.appendChild(errorBanner());
      _el.replaceChildren(box);
    }
  }

  function paintModel(model, { stale } = {}) {
    const banner = stale ? staleBanner(model.generated_at) : null;
    const { wrap, pane } = renderWorkbench(model, banner);
    _el.replaceChildren(wrap);
    if (_selectedId != null && !findItem(model, _selectedId)) _selectedId = null;
    renderInspectInto(pane, model);
  }

  // The single render entry point — classify, then paint the one honest surface.
  function paint(model) {
    if (!_el) return;
    attachClick(); // delegated handler on _el — bind once, before any surface (retry needs it)
    const status = classifyCockpitState({ model, loading: !_resolved, errored: _errored });
    if (status === 'loading') return paintSkeleton();
    if (status === 'error') return paintError();
    if (status === 'missing') return paintMissing();
    paintModel(model, { stale: status === 'stale' });
  }

  function render(state) {
    if (!_el) return;
    // A call with the operatorTriage key present (value or null) means a load resolved.
    _resolved = !!state && Object.prototype.hasOwnProperty.call(state, 'operatorTriage');
    const model = state && state.operatorTriage;
    if (model && Array.isArray(model.items)) { _lastGood = model; _errored = false; }
    paint(model);
  }

  // The Cockpit's own refresh — re-pulls the model and surfaces a failed fetch/parse as
  // the error state (over last-good), instead of silently holding a stale render.
  function doRefresh() {
    const f = typeof fetch === 'function' ? fetch : null;
    if (!f) return Promise.resolve();
    _resolved = true;
    return f('state/operator-triage.json')
      .then((resp) => (resp && resp.ok ? resp.json() : Promise.reject(new Error('not ok'))))
      .then((fresh) => {
        if (fresh && Array.isArray(fresh.items)) { _lastGood = fresh; _errored = false; paint(fresh); }
        else { _errored = true; paint(null); }
      })
      .catch(() => { _errored = true; paint(null); });
  }

  function attachClick() {
    if (!_el || _clickBound) return;
    _el.addEventListener('click', (ev) => {
      const t = ev.target;
      if (!t || !t.closest) return;
      if (t.closest('.dp-cockpit-retry')) { doRefresh(); return; }
      const card = t.closest('[data-item-id]');
      if (!card) return;
      _selectedId = card.dataset.itemId || null;
      renderInspectInto(_el.querySelector('.dp-cockpit-inspect'), _lastGood);
    });
    _clickBound = true;
  }

  Jarvis.registerPage({
    id: 'cockpit',
    label: 'Cockpit',
    init(state) {
      _el = Jarvis.getPageEl('cockpit');
      if (!_el) return;
      render(state);
    },
    onActivate(state) {
      render(state);
    },
    // F004 — a refresh that surfaces a failed fetch as the error state (over last-good),
    // not a silent stale hold. Returns the promise so callers can await the outcome.
    refresh() {
      return doRefresh();
    },
  });
})();
