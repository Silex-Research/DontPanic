/*
 * Theme + density controller for the redesign token layer (plan 2026-06-06-004 F002, spec §2/§8).
 *
 * The whole visual system is a `data-theme` / `data-density` swap on :root — no JS recolouring,
 * no second template. This module owns that swap and the canonical vocabulary the renderers and
 * tests share. The header chips (F004) call setTheme/setDensity; everything else is CSS.
 */

export const THEMES = Object.freeze(['dark', 'light']);
export const DENSITIES = Object.freeze(['comfort', 'dense']);

export const DEFAULT_THEME = 'dark';      // §2.3 — dark is the operator's default
export const DEFAULT_DENSITY = 'comfort'; // §2.4 — comfort (cards) by default

/* Closed vocabularies — kept in lockstep with operator-triage/v0 + the spec colour tables.
   tokens.test.js asserts each name has a CSS custom property in BOTH themes. */
export const BUCKETS = Object.freeze([
  'needs_auth', 'needs_decision', 'agent_runnable', 'auto_safe', 'uncertain', 'quiet',
]);
export const FRESHNESS = Object.freeze(['fresh', 'aging', 'stale', 'unproven']);
export const SCOPES = Object.freeze(['fleet', 'project', 'global']);
export const RUN_STATES = Object.freeze(['idle', 'running', 'waiting', 'conflicted', 'complete']);

/* operator_bucket value → CSS custom property carrying its colour. */
export function bucketToken(bucket) {
  return `--bucket-${String(bucket).replace(/_/g, '-')}`;
}

function root(doc) {
  return (doc || (typeof document !== 'undefined' ? document : null))?.documentElement ?? null;
}

export function setTheme(theme, doc) {
  if (!THEMES.includes(theme)) throw new Error(`unknown theme: ${theme}`);
  const el = root(doc);
  if (el) el.dataset.theme = theme;
  return theme;
}

export function setDensity(density, doc) {
  if (!DENSITIES.includes(density)) throw new Error(`unknown density: ${density}`);
  const el = root(doc);
  if (el) el.dataset.density = density;
  return density;
}

export function getTheme(doc) {
  return root(doc)?.dataset.theme || DEFAULT_THEME;
}

export function getDensity(doc) {
  return root(doc)?.dataset.density || DEFAULT_DENSITY;
}

export function toggleTheme(doc) {
  return setTheme(getTheme(doc) === 'dark' ? 'light' : 'dark', doc);
}

export function toggleDensity(doc) {
  return setDensity(getDensity(doc) === 'comfort' ? 'dense' : 'comfort', doc);
}

/* Establish the defaults on first paint (idempotent). Called by the shell before render so the
   token layer is always in a known state even before the user touches a chip. */
export function initThemeDefaults(doc) {
  const el = root(doc);
  if (!el) return;
  if (!THEMES.includes(el.dataset.theme)) el.dataset.theme = DEFAULT_THEME;
  if (!DENSITIES.includes(el.dataset.density)) el.dataset.density = DEFAULT_DENSITY;
}
