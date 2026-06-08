// ── Surface state matrix (plan 2026-06-07-003 / operator-console 008 F003) ──
// One honest five-state classifier + render contract, reusable by EVERY key
// surface (cockpit, what-now, architecture, capabilities, health). Generalized
// from cockpit-state.js (005 F004) so the matrix is defined once and rendered
// many times — the render-truth posture the cockpit already proved:
//
//   loading — a load is in flight and there is nothing to show yet → skeleton.
//   error   — the last load/refresh failed → show last-good (if any) under an
//             error banner + retry; never blank, never a fabricated-fresh render.
//   missing — the surface has never been built → an explicit empty state.
//   stale   — content exists but is old enough to distrust → render it UNDER a
//             stale banner that admits its age (visibly demoted, not hidden).
//   ready   — fresh, present content.
//
// Threshold aligned to freshness.js AGING_MAX so the classifier and the rendered
// banner never disagree.

export const SURFACE_STATES = Object.freeze(['loading', 'error', 'missing', 'stale', 'ready']);
export const DEFAULT_STALE_AFTER_MS = 24 * 60 * 60 * 1000;

function ageMs(generatedAt, now) {
  if (generatedAt == null) return null;
  const t = typeof generatedAt === 'number' ? generatedAt : Date.parse(generatedAt);
  return Number.isFinite(t) ? now - t : null;
}

/**
 * Classify any surface's render state. Surface-agnostic: the caller says whether
 * renderable content is `present` and (optionally) when it was `generatedAt`.
 * Precedence is deliberate and identical to the cockpit: in-flight-with-nothing →
 * loading; a failed load → error (over last-good) even if stale content lingers;
 * absence → missing; otherwise staleness demotes present content before ready.
 */
export function classifySurfaceState({
  present = false,
  loading = false,
  errored = false,
  generatedAt = null,
  now = Date.now(),
  staleAfterMs = DEFAULT_STALE_AFTER_MS,
} = {}) {
  if (loading && !present) return 'loading';
  if (errored) return 'error';
  if (!present) return 'missing';
  const age = ageMs(generatedAt, now);
  // Render-truth (audit 2026-06-08 B2#2): present content with NO trustworthy
  // timestamp (null / unparseable generatedAt) must be demoted to `stale`, never
  // shown as fresh `ready`. Only a parseable, in-window timestamp earns `ready`.
  if (age == null) return 'stale';
  if (age >= staleAfterMs) return 'stale';
  return 'ready';
}

function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
}

/**
 * Render the chrome for a non-ready surface state, or `null` for `ready` (the
 * caller renders its own content for ready). One renderer, every surface — the
 * returned node carries `data-surface-state` so a journey test (and the operator)
 * can see which honest state a surface is in. Token-classed, no raw colour.
 *
 * opts: { label, generatedAt, now } — label names the surface in copy.
 */
export function renderSurfaceChrome(state, opts = {}) {
  const label = opts.label || 'This surface';
  if (!SURFACE_STATES.includes(state)) {
    throw new Error(`renderSurfaceChrome: unknown surface state ${state}`);
  }
  if (state === 'ready') return null;

  const root = el('div', `dp-surface-state dp-surface-state--${state}`);
  root.dataset.surfaceState = state;

  if (state === 'loading') {
    root.setAttribute('aria-busy', 'true');
    root.appendChild(el('div', 'dp-surface-skeleton', `Loading ${label}…`));
    return root;
  }
  if (state === 'missing') {
    root.appendChild(el('div', 'dp-surface-empty-title', `${label} has not been built yet`));
    root.appendChild(
      el('div', 'dp-surface-empty-hint', 'Run `dontpanic dashboard build` to populate it.')
    );
    return root;
  }
  if (state === 'stale') {
    const banner = el('div', 'dp-surface-stale-banner');
    banner.setAttribute('role', 'status');
    const age = ageMs(opts.generatedAt, opts.now || Date.now());
    const hrs = age != null ? Math.floor(age / (60 * 60 * 1000)) : null;
    banner.textContent =
      hrs != null
        ? `Showing ${label} from ${hrs}h ago — may be out of date. Rebuild to refresh.`
        : `Showing a stale ${label} — may be out of date. Rebuild to refresh.`;
    root.appendChild(banner);
    return root;
  }
  // error — last-good shown by the caller; this is the banner + retry affordance.
  const banner = el('div', 'dp-surface-error-banner');
  banner.setAttribute('role', 'alert');
  banner.textContent = `Couldn't refresh ${label}. Showing the last good copy if available.`;
  const retry = el('button', 'dp-surface-retry', 'Retry');
  retry.type = 'button';
  retry.dataset.action = 'retry';
  root.appendChild(banner);
  root.appendChild(retry);
  return root;
}
