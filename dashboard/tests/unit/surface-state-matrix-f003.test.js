// Plan 2026-06-07-003 (operator-console 008) F003 — surface-state matrix.
// One classifier + render contract across the five honest states, exercised for
// several key surfaces. Render-truth: stale is demoted (never shown as fresh),
// error keeps last-good + offers retry, ready yields to the caller's content.
import { describe, it, expect } from 'vitest';
import {
  SURFACE_STATES,
  DEFAULT_STALE_AFTER_MS,
  classifySurfaceState,
  renderSurfaceChrome,
} from '../../lib/surface-state.js';
import { classifyCockpitState } from '../../lib/cockpit-state.js';

const NOW = 1_700_000_000_000;
const fresh = NOW - 60_000;
const old = NOW - (DEFAULT_STALE_AFTER_MS + 60_000);

describe('classifySurfaceState (008 F003)', () => {
  it('returns each of the five states from the right inputs', () => {
    expect(classifySurfaceState({ loading: true, present: false })).toBe('loading');
    expect(classifySurfaceState({ errored: true, present: true })).toBe('error');
    expect(classifySurfaceState({ present: false })).toBe('missing');
    expect(classifySurfaceState({ present: true, generatedAt: old, now: NOW })).toBe('stale');
    expect(classifySurfaceState({ present: true, generatedAt: fresh, now: NOW })).toBe('ready');
  });

  it('precedence: error wins over lingering stale content; loading needs empty', () => {
    expect(classifySurfaceState({ present: true, errored: true, generatedAt: old, now: NOW })).toBe('error');
    // a load in flight but content already present is NOT loading (no flash).
    expect(classifySurfaceState({ present: true, loading: true, generatedAt: fresh, now: NOW })).toBe('ready');
  });

  it('is the same matrix the cockpit uses (states align)', () => {
    expect(SURFACE_STATES).toEqual(['loading', 'error', 'missing', 'stale', 'ready']);
    // cockpit classifier (its specialization) agrees on the shared cases.
    expect(classifyCockpitState({ loading: true })).toBe('loading');
    expect(classifyCockpitState({ model: { items: [] }, errored: true })).toBe('error');
    expect(classifyCockpitState({ model: null })).toBe('missing');
  });
});

describe('renderSurfaceChrome (008 F003) — one renderer, every surface', () => {
  const surfaces = ['cockpit', 'what-now', 'architecture', 'capabilities', 'health'];

  it('renders the right chrome for every non-ready state across key surfaces', () => {
    for (const label of surfaces) {
      const loading = renderSurfaceChrome('loading', { label });
      expect(loading.dataset.surfaceState).toBe('loading');
      expect(loading.getAttribute('aria-busy')).toBe('true');

      const missing = renderSurfaceChrome('missing', { label });
      expect(missing.dataset.surfaceState).toBe('missing');
      expect(missing.textContent).toContain('build');

      const stale = renderSurfaceChrome('stale', { label, generatedAt: old, now: NOW });
      expect(stale.dataset.surfaceState).toBe('stale');
      expect(stale.querySelector('.dp-surface-stale-banner').textContent).toMatch(/out of date/i);

      const error = renderSurfaceChrome('error', { label });
      expect(error.dataset.surfaceState).toBe('error');
      expect(error.querySelector('[data-action="retry"]')).not.toBeNull();
      expect(error.querySelector('[role="alert"]')).not.toBeNull();
    }
  });

  it('ready yields to the caller (no chrome node)', () => {
    expect(renderSurfaceChrome('ready', { label: 'cockpit' })).toBeNull();
  });

  it('stale chrome never claims freshness, and chrome carries no raw hex', () => {
    const stale = renderSurfaceChrome('stale', { label: 'health', generatedAt: old, now: NOW });
    // It must ADMIT staleness rather than imply currency ("up to date"/"current now").
    expect(stale.textContent.toLowerCase()).toMatch(/out of date/);
    expect(stale.textContent.toLowerCase()).not.toMatch(/up to date|current/);
    for (const s of SURFACE_STATES.filter((x) => x !== 'ready')) {
      expect(renderSurfaceChrome(s, { label: 'x' }).outerHTML).not.toMatch(/#[0-9a-fA-F]{3,6}\b/);
    }
  });

  it('rejects an unknown state (no silent mis-render)', () => {
    expect(() => renderSurfaceChrome('bogus', {})).toThrow();
  });

  // audit 2026-06-08 B2#2: present content with NO trustworthy timestamp must be
  // demoted to `stale`, never shown as fresh `ready` (the fake-fresh failure).
  it('present + null/unparseable generatedAt classifies as stale, not ready', () => {
    expect(classifySurfaceState({ present: true, generatedAt: null })).toBe('stale');
    expect(classifySurfaceState({ present: true, generatedAt: 'not-a-date' })).toBe('stale');
    const now = Date.parse('2026-06-08T12:00:00Z');
    expect(classifySurfaceState({ present: true, generatedAt: now, now })).toBe('ready');
  });
});
