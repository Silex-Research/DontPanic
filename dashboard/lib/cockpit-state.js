// ── Cockpit state matrix (plan 2026-06-06-005 F004) ──
// Pure classifier for the Cockpit's honest render states. The Cockpit must never show
// a blank, and never render stale/errored state as if it were fresh — each input maps
// to exactly one distinct, honest surface.
//
//   loading — a load is in flight and we have nothing to show yet → skeleton.
//   error   — the last load/refresh failed → show last-good (if any) under an error banner + retry,
//             never a blank and never a fabricated-fresh render.
//   missing — no triage model exists yet (never built) → the "run dashboard build" empty state.
//   stale   — the model exists but was generated long enough ago to distrust → render it UNDER a
//             stale banner that admits its age (render-truth: visibly demoted, not hidden).
//   ready   — a fresh model with items.

// Aligned to freshness.js AGING_MAX (the staleBanner threshold): a model older than 24h is
// demoted to 'stale' so the classifier and the rendered banner never disagree.
export const STALE_AFTER_MS = 24 * 60 * 60 * 1000;

export const COCKPIT_STATES = Object.freeze(['loading', 'error', 'missing', 'stale', 'ready']);

function hasItems(model) {
  return !!model && Array.isArray(model.items);
}

function ageMs(generatedAt, now) {
  if (!generatedAt) return null;
  const t = typeof generatedAt === 'number' ? generatedAt : Date.parse(generatedAt);
  return Number.isFinite(t) ? now - t : null;
}

/**
 * Classify the Cockpit render state. Precedence is deliberate: an in-flight load shows the
 * skeleton; a failed load is surfaced as error (over last-good) even if a stale model lingers;
 * absence is "missing"; otherwise staleness demotes a present model before it counts as ready.
 */
export function classifyCockpitState({ model, loading = false, errored = false, now = Date.now() } = {}) {
  if (loading && !hasItems(model)) return 'loading';
  if (errored) return 'error';
  if (!hasItems(model)) return 'missing';
  const age = ageMs(model.generated_at, now);
  if (age != null && age >= STALE_AFTER_MS) return 'stale';
  return 'ready';
}
