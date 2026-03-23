import { describe, it, expect } from 'vitest';
import {
  getAgentMeta,
  normalizeStatus,
  computeTokenPct,
  buildMetricPoints,
} from '../../lib/command-center-logic.js';

// ── getAgentMeta ─────────────────────────────────────────────────────────────

describe('getAgentMeta', () => {
  it('returns correct metadata for claude', () => {
    const meta = getAgentMeta('claude');
    expect(meta.initials).toBe('CC');
    expect(meta.color).toBe('#3b82f6');
    expect(meta.badge).toBe('LEAD');
  });

  it('returns correct metadata for codex', () => {
    const meta = getAgentMeta('codex');
    expect(meta.initials).toBe('CX');
    expect(meta.color).toBe('#22c55e');
    expect(meta.badge).toBe('OAI');
  });

  it('returns correct metadata for gemini', () => {
    const meta = getAgentMeta('gemini');
    expect(meta.initials).toBe('GM');
    expect(meta.color).toBe('#f97316');
    expect(meta.badge).toBe('GGL');
  });

  it('returns correct metadata for grok', () => {
    const meta = getAgentMeta('grok');
    expect(meta.initials).toBe('GK');
    expect(meta.color).toBe('#a855f7');
    expect(meta.badge).toBe('XAI');
  });

  it('returns correct metadata for kimi', () => {
    const meta = getAgentMeta('kimi');
    expect(meta.initials).toBe('KM');
    expect(meta.color).toBe('#eab308');
    expect(meta.badge).toBe('MSH');
  });

  it('returns correct metadata for qwen', () => {
    const meta = getAgentMeta('qwen');
    expect(meta.initials).toBe('QW');
    expect(meta.color).toBe('#ef4444');
    expect(meta.badge).toBe('ALI');
  });

  it('returns fallback metadata for unknown agent id', () => {
    const meta = getAgentMeta('xyzbot');
    expect(meta.initials).toBe('XY');
    expect(meta.color).toBe('#64748b');
    expect(meta.badge).toBe('AGT');
  });

  it('returns ?? initials for null or empty id', () => {
    expect(getAgentMeta(null).initials).toBe('??');
    expect(getAgentMeta('').initials).toBe('??');
  });
});

// ── normalizeStatus ──────────────────────────────────────────────────────────

describe('normalizeStatus', () => {
  it('maps "todo" to "pending"', () => {
    expect(normalizeStatus('todo')).toBe('pending');
  });

  it('maps null to "pending"', () => {
    expect(normalizeStatus(null)).toBe('pending');
  });

  it('maps undefined to "pending"', () => {
    expect(normalizeStatus(undefined)).toBe('pending');
  });

  it('passes through "in_progress" unchanged', () => {
    expect(normalizeStatus('in_progress')).toBe('in_progress');
  });

  it('passes through "completed" unchanged', () => {
    expect(normalizeStatus('completed')).toBe('completed');
  });

  it('passes through "pending" unchanged', () => {
    expect(normalizeStatus('pending')).toBe('pending');
  });
});

// ── computeTokenPct ──────────────────────────────────────────────────────────

describe('computeTokenPct', () => {
  it('calculates correct percentage', () => {
    const result = computeTokenPct(50000, 100000);
    expect(result.pct).toBe(50);
  });

  it('rounds to nearest integer', () => {
    const result = computeTokenPct(1, 3);
    expect(result.pct).toBe(33);
  });

  it('caps at 100 when usage exceeds budget', () => {
    const result = computeTokenPct(150000, 100000);
    expect(result.pct).toBe(100);
  });

  it('returns red color when pct > 90', () => {
    const result = computeTokenPct(95000, 100000);
    expect(result.colorClass).toBe('red');
  });

  it('returns yellow color when pct > 70 and <= 90', () => {
    const result = computeTokenPct(75000, 100000);
    expect(result.colorClass).toBe('yellow');
  });

  it('returns accent color when pct <= 70', () => {
    const result = computeTokenPct(70000, 100000);
    expect(result.colorClass).toBe('accent');
  });

  it('returns pct 0 and accent when budget is 0', () => {
    const result = computeTokenPct(50000, 0);
    expect(result.pct).toBe(0);
    expect(result.colorClass).toBe('accent');
  });

  it('returns pct 0 when tokensUsed is 0', () => {
    const result = computeTokenPct(0, 100000);
    expect(result.pct).toBe(0);
    expect(result.colorClass).toBe('accent');
  });
});

// ── buildMetricPoints ────────────────────────────────────────────────────────

describe('buildMetricPoints', () => {
  it('returns empty array when activity is empty', () => {
    const state = { agents: [], activity: [] };
    expect(buildMetricPoints(state)).toEqual([]);
  });

  it('buckets activity events by calendar date', () => {
    const state = {
      agents: [],
      activity: [
        { timestamp: '2025-10-01T10:00:00Z' },
        { timestamp: '2025-10-01T14:00:00Z' },
        { timestamp: '2025-10-02T09:00:00Z' },
      ],
    };
    const points = buildMetricPoints(state);
    expect(points.length).toBe(2);
    // Days should have correct action counts
    const sorted = [...points].sort((a, b) => new Date(a.date) - new Date(b.date));
    // The point with 2 actions comes from Oct 1
    const twoActionDay = points.find(p => p.actions === 2);
    const oneActionDay = points.find(p => p.actions === 1);
    expect(twoActionDay).toBeDefined();
    expect(oneActionDay).toBeDefined();
  });

  it('spreads agent token totals evenly across dates', () => {
    const state = {
      agents: [
        { tokensUsed: 60000 },
        { tokensUsed: 40000 },
      ],
      activity: [
        { timestamp: '2025-10-01T10:00:00Z' },
        { timestamp: '2025-10-02T10:00:00Z' },
      ],
    };
    const points = buildMetricPoints(state);
    expect(points.every(p => p.tokensUsed === 50000)).toBe(true);
  });

  it('skips activity items with no timestamp', () => {
    const state = {
      agents: [],
      activity: [
        { timestamp: null },
        { timestamp: '2025-10-01T10:00:00Z' },
      ],
    };
    const points = buildMetricPoints(state);
    expect(points.length).toBe(1);
    expect(points[0].actions).toBe(1);
  });

  it('returns points sorted chronologically', () => {
    const state = {
      agents: [],
      activity: [
        { timestamp: '2025-10-03T10:00:00Z' },
        { timestamp: '2025-10-01T10:00:00Z' },
        { timestamp: '2025-10-02T10:00:00Z' },
      ],
    };
    const points = buildMetricPoints(state);
    expect(points.length).toBe(3);
    // Should be ordered — first point's date should parse earlier than last
    const first = new Date(points[0].date);
    const last  = new Date(points[points.length - 1].date);
    expect(first.getTime()).toBeLessThanOrEqual(last.getTime());
  });
});
