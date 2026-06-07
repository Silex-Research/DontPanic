/*
 * Cockpit state classifier — plan 2026-06-06-005 F004.
 * The pure decision behind the Cockpit's honest state matrix: loading / error / missing /
 * stale / ready, with deliberate precedence (loading needs no model; a failed load is error
 * even over a lingering stale model; absence is missing; staleness demotes a present model).
 */

import { describe, it, expect } from 'vitest';
import { classifyCockpitState, STALE_AFTER_MS, COCKPIT_STATES } from '../../lib/cockpit-state.js';

const NOW = 1_000_000_000_000;
const fresh = (extra = {}) => ({ items: [{ id: 'x' }], generated_at: new Date(NOW - 60_000).toISOString(), ...extra });
const stale = (extra = {}) => ({ items: [{ id: 'x' }], generated_at: new Date(NOW - STALE_AFTER_MS - 60_000).toISOString(), ...extra });

describe('classifyCockpitState', () => {
  it('loading when a load is in flight and there is nothing to show', () => {
    expect(classifyCockpitState({ loading: true, model: null, now: NOW })).toBe('loading');
    // …but a model already in hand is shown, not hidden behind a skeleton
    expect(classifyCockpitState({ loading: true, model: fresh(), now: NOW })).toBe('ready');
  });

  it('error whenever the last load failed — even over a stale model (never fake-fresh)', () => {
    expect(classifyCockpitState({ errored: true, model: null, now: NOW })).toBe('error');
    expect(classifyCockpitState({ errored: true, model: stale(), now: NOW })).toBe('error');
  });

  it('missing when no triage model exists yet', () => {
    expect(classifyCockpitState({ model: null, now: NOW })).toBe('missing');
    expect(classifyCockpitState({ model: undefined, now: NOW })).toBe('missing');
    expect(classifyCockpitState({ model: { items: 'nope' }, now: NOW })).toBe('missing');
  });

  it('stale when the model was generated past the staleness window', () => {
    expect(classifyCockpitState({ model: stale(), now: NOW })).toBe('stale');
  });

  it('ready for a fresh model; a model with no generated_at is not treated as stale', () => {
    expect(classifyCockpitState({ model: fresh(), now: NOW })).toBe('ready');
    expect(classifyCockpitState({ model: { items: [{ id: 'x' }] }, now: NOW })).toBe('ready');
  });

  it('exposes the closed set of states', () => {
    expect(COCKPIT_STATES).toEqual(['loading', 'error', 'missing', 'stale', 'ready']);
  });
});
