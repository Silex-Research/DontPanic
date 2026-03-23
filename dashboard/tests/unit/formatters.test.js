import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { timeAgo, formatCurrency, formatNumber } from '../../lib/formatters.js';

// ── timeAgo ──────────────────────────────────────────────────────────────────

describe('timeAgo', () => {
  let now;

  beforeEach(() => {
    now = Date.now();
    vi.spyOn(Date, 'now').mockReturnValue(now);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('returns "--" for null', () => {
    expect(timeAgo(null)).toBe('--');
  });

  it('returns "--" for undefined', () => {
    expect(timeAgo(undefined)).toBe('--');
  });

  it('returns seconds ago for timestamps less than 60 seconds old', () => {
    const ts = now - 30 * 1000;
    expect(timeAgo(ts)).toBe('30s ago');
  });

  it('returns "0s ago" for a timestamp equal to now', () => {
    expect(timeAgo(now)).toBe('0s ago');
  });

  it('returns minutes ago for timestamps between 60s and 1 hour old', () => {
    const ts = now - 5 * 60 * 1000;
    expect(timeAgo(ts)).toBe('5m ago');
  });

  it('returns hours ago for timestamps between 1 hour and 24 hours old', () => {
    const ts = now - 3 * 3600 * 1000;
    expect(timeAgo(ts)).toBe('3h ago');
  });

  it('returns days ago for timestamps older than 24 hours', () => {
    const ts = now - 2 * 86400 * 1000;
    expect(timeAgo(ts)).toBe('2d ago');
  });

  it('accepts an ISO string timestamp', () => {
    const isoString = new Date(now - 10 * 1000).toISOString();
    expect(timeAgo(isoString)).toBe('10s ago');
  });

  it('accepts a non-ISO date string parseable by Date', () => {
    const dateStr = new Date(now - 90 * 1000).toString();
    expect(timeAgo(dateStr)).toBe('1m ago');
  });

  it('handles a numeric timestamp at exactly 59 seconds (still seconds)', () => {
    const ts = now - 59 * 1000;
    expect(timeAgo(ts)).toBe('59s ago');
  });

  it('handles a numeric timestamp at exactly 60 seconds (switches to minutes)', () => {
    const ts = now - 60 * 1000;
    expect(timeAgo(ts)).toBe('1m ago');
  });

  it('handles future timestamps gracefully (diff is negative, shows 0s ago or negative)', () => {
    const futureTs = now + 5 * 1000;
    // diff will be -5 — implementation floors to -5s ago; we just assert it does not throw
    const result = timeAgo(futureTs);
    expect(typeof result).toBe('string');
  });
});

// ── formatCurrency ────────────────────────────────────────────────────────────

describe('formatCurrency', () => {
  it('returns "--" for null', () => {
    expect(formatCurrency(null)).toBe('--');
  });

  it('returns "--" for undefined', () => {
    expect(formatCurrency(undefined)).toBe('--');
  });

  it('formats zero as "$0.00"', () => {
    expect(formatCurrency(0)).toBe('$0.00');
  });

  it('formats a whole number with two decimal places', () => {
    expect(formatCurrency(5)).toBe('$5.00');
  });

  it('formats a decimal value correctly', () => {
    expect(formatCurrency(3.14159)).toBe('$3.14');
  });

  it('formats a negative value with leading minus sign', () => {
    expect(formatCurrency(-12.5)).toBe('$-12.50');
  });

  it('formats large values without K/M shorthand', () => {
    expect(formatCurrency(1234567.89)).toBe('$1234567.89');
  });
});

// ── formatNumber ──────────────────────────────────────────────────────────────

describe('formatNumber', () => {
  it('returns "--" for null', () => {
    expect(formatNumber(null)).toBe('--');
  });

  it('returns "--" for undefined', () => {
    expect(formatNumber(undefined)).toBe('--');
  });

  it('formats millions with one decimal and "M" suffix', () => {
    expect(formatNumber(2500000)).toBe('2.5M');
  });

  it('formats exactly 1M correctly', () => {
    expect(formatNumber(1000000)).toBe('1.0M');
  });

  it('formats thousands with one decimal and "K" suffix', () => {
    expect(formatNumber(4500)).toBe('4.5K');
  });

  it('formats exactly 1K correctly', () => {
    expect(formatNumber(1000)).toBe('1.0K');
  });

  it('passes through small numbers as strings without suffix', () => {
    expect(formatNumber(42)).toBe('42');
  });

  it('passes through zero as "0"', () => {
    expect(formatNumber(0)).toBe('0');
  });
});
