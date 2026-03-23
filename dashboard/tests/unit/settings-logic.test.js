// ── Settings Logic — Unit Tests ──

import { describe, it, expect } from 'vitest';
import {
  HARNESSES,
  STALE_THRESHOLD_MS,
  deriveSyncStatus,
} from '../../lib/settings-logic.js';

// ── HARNESSES constant ──

describe('HARNESSES', () => {
  it('is an array', () => {
    expect(Array.isArray(HARNESSES)).toBe(true);
  });

  it('contains claude, codex, gemini, and cursor harnesses', () => {
    const ids = HARNESSES.map(h => h.id);
    expect(ids).toContain('claude');
    expect(ids).toContain('codex');
    expect(ids).toContain('gemini');
    expect(ids).toContain('cursor');
  });

  it('each harness has id, label, badge, path, and desc', () => {
    for (const h of HARNESSES) {
      expect(typeof h.id).toBe('string');
      expect(typeof h.label).toBe('string');
      expect(typeof h.badge).toBe('string');
      expect(typeof h.path).toBe('string');
      expect(typeof h.desc).toBe('string');
    }
  });
});

// ── STALE_THRESHOLD_MS ──

describe('STALE_THRESHOLD_MS', () => {
  it('equals 1 hour in milliseconds', () => {
    expect(STALE_THRESHOLD_MS).toBe(3600 * 1000);
  });
});

// ── deriveSyncStatus ──

describe('deriveSyncStatus', () => {
  it('returns "in-sync" when agent is found and lastSeen is recent', () => {
    const agents = [
      { id: 'claude', lastSeen: new Date(Date.now() - 60_000).toISOString() },
    ];
    expect(deriveSyncStatus('claude', agents)).toBe('in-sync');
  });

  it('returns "stale" when agent is found but lastSeen is older than 1 hour', () => {
    const agents = [
      { id: 'claude', lastSeen: new Date(Date.now() - 3700_000).toISOString() },
    ];
    expect(deriveSyncStatus('claude', agents)).toBe('stale');
  });

  it('returns "in-sync" for lastSeen exactly at the threshold boundary (just under 1hr)', () => {
    const agents = [
      { id: 'claude', lastSeen: new Date(Date.now() - 3599_000).toISOString() },
    ];
    expect(deriveSyncStatus('claude', agents)).toBe('in-sync');
  });

  it('returns "missing" when agent id is not in the agents list', () => {
    const agents = [
      { id: 'codex', lastSeen: new Date().toISOString() },
    ];
    expect(deriveSyncStatus('claude', agents)).toBe('missing');
  });

  it('returns "missing" for an empty agents array', () => {
    expect(deriveSyncStatus('claude', [])).toBe('missing');
  });

  it('returns "stale" when agent is found but lastSeen is null', () => {
    const agents = [{ id: 'claude', lastSeen: null }];
    expect(deriveSyncStatus('claude', agents)).toBe('stale');
  });

  it('is case-insensitive for agent id comparison', () => {
    const agents = [
      { id: 'CLAUDE', lastSeen: new Date(Date.now() - 60_000).toISOString() },
    ];
    expect(deriveSyncStatus('claude', agents)).toBe('in-sync');
  });

  it('returns "missing" when agents is null or undefined', () => {
    expect(deriveSyncStatus('claude', null)).toBe('missing');
    expect(deriveSyncStatus('claude', undefined)).toBe('missing');
  });
});
