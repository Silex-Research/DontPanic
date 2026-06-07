/*
 * Freshness grammar — render-truth made visible everywhere (plan 2026-06-06-004 F007, spec §2.2/§6).
 * The filled dot is reserved for item-level proof (freshness_basis === "item_probe"); a plan-level
 * basis or none renders as the hollow "unverified" ring. Among PROVEN items, age (asserted_at vs now)
 * picks fresh / aging / stale; stale + unproven desaturate so they recede until refreshed.
 *
 * This is the shared helper every surface uses; the F003 atom seeds the same filled-vs-hollow rule.
 */

const HOUR = 3600_000;
const FRESH_MAX = HOUR;        // < 1h  → fresh
const AGING_MAX = 24 * HOUR;   // < 24h → aging; ≥ 24h → stale

export const FRESHNESS_STATES = Object.freeze(['fresh', 'aging', 'stale', 'unproven']);

function ageMs(asserted_at, now) {
  if (!asserted_at) return Infinity;
  const t = Date.parse(asserted_at);
  return Number.isNaN(t) ? Infinity : Math.max(0, now - t);
}

/**
 * The full freshness view for an item. RENDER-TRUTH: `filled` is true ONLY for item-level
 * proof — plan-level liveness and "no basis" are honestly unproven (hollow), never confident.
 */
export function freshnessView(item, now = Date.now()) {
  const proven = item && item.freshness_basis === 'item_probe';
  if (!proven) {
    return { state: 'unproven', filled: false, desaturate: true, label: 'unverified', ageText: '' };
  }
  const ms = ageMs(item.asserted_at, now);
  const state = ms < FRESH_MAX ? 'fresh' : ms < AGING_MAX ? 'aging' : 'stale';
  return {
    state,
    filled: true,
    desaturate: state === 'stale',
    label: state,
    ageText: relativeAge(ms),
  };
}

export function relativeAge(ms) {
  if (!Number.isFinite(ms)) return '';
  const m = Math.floor(ms / 60000);
  if (m < 1) return 'just now';
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d old`;
}

function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
}

/** A freshness dot keyed entirely off the view: filled state class + desaturation + honest title. */
export function renderFreshnessDot(item, now = Date.now()) {
  const v = freshnessView(item, now);
  const dot = el('span', `dp-freshness dp-freshness--${v.filled ? v.state : 'unproven'}${v.desaturate ? ' dp-desaturate' : ''}`);
  dot.dataset.freshness = v.state;
  dot.dataset.filled = String(v.filled);
  dot.title = v.filled ? `${v.label} · ${v.ageText}` : 'unverified — asserted, not proven live';
  dot.setAttribute('aria-label', dot.title);
  return dot;
}

/** Stale-state banner for a surface (§6) — admits "this is N old", never renders it as fresh. */
export function staleBanner(generatedAt, now = Date.now()) {
  const ms = ageMs(generatedAt, now);
  if (ms < AGING_MAX) return null;
  const b = el('div', 'dp-stale-banner');
  b.setAttribute('role', 'status');
  b.textContent = `State may be outdated · generated ${relativeAge(ms)} · regenerating`;
  return b;
}
