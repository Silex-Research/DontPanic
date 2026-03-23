import { describe, it, expect } from 'vitest';
import {
  computeScorecardValues,
  computeNetCost,
  buildBreakdownDatasets,
  normalizeTrendData,
  fmtLabel,
  BUDGET_MAP,
  APP_COLORS,
} from '../../lib/cloud-costs-logic.js';

// ── computeScorecardValues ──────────────────────────────────────────────────

describe('computeScorecardValues', () => {
  it('returns net_cost when totals fields are objects', () => {
    const totals = {
      'Styln':         { net_cost: 120.5 },
      'Spin & Dine':   { net_cost: 40.0 },
      'QuantRE/Axiom': { net_cost: 10.0 },
    };
    const result = computeScorecardValues(totals);
    expect(result.styln).toBe(120.5);
    expect(result.spinDine).toBe(40.0);
    expect(result.quantRe).toBe(10.0);
  });

  it('returns number directly when totals fields are numbers', () => {
    const totals = {
      'Styln':         200,
      'Spin & Dine':   55,
      'QuantRE/Axiom': 18,
    };
    const result = computeScorecardValues(totals);
    expect(result.styln).toBe(200);
    expect(result.spinDine).toBe(55);
    expect(result.quantRe).toBe(18);
  });

  it('returns 0 for null or missing fields', () => {
    const result = computeScorecardValues({});
    expect(result.styln).toBe(0);
    expect(result.spinDine).toBe(0);
    expect(result.quantRe).toBe(0);
  });

  it('uses explicit Total object field when present and non-zero', () => {
    const totals = {
      'Styln':         { net_cost: 100 },
      'Spin & Dine':   { net_cost: 50 },
      'QuantRE/Axiom': { net_cost: 25 },
      'Total':         { net_cost: 999 },
    };
    const result = computeScorecardValues(totals);
    expect(result.total).toBe(999);
  });

  it('uses explicit Total number field when present and non-zero', () => {
    const totals = {
      'Styln': 100,
      'Spin & Dine': 50,
      'QuantRE/Axiom': 25,
      'Total': 300,
    };
    const result = computeScorecardValues(totals);
    expect(result.total).toBe(300);
  });

  it('falls back to summing three apps when Total is null', () => {
    const totals = {
      'Styln':         { net_cost: 100 },
      'Spin & Dine':   { net_cost: 50 },
      'QuantRE/Axiom': { net_cost: 25 },
      'Total':         null,
    };
    const result = computeScorecardValues(totals);
    expect(result.total).toBe(175);
  });

  it('falls back to summing three apps when Total is 0', () => {
    const totals = {
      'Styln':         100,
      'Spin & Dine':   50,
      'QuantRE/Axiom': 25,
      'Total':         0,
    };
    const result = computeScorecardValues(totals);
    expect(result.total).toBe(175);
  });

  it('returns 0 for total when all app values are missing', () => {
    const result = computeScorecardValues(null);
    expect(result.styln).toBe(0);
    expect(result.spinDine).toBe(0);
    expect(result.quantRe).toBe(0);
    expect(result.total).toBe(0);
  });
});

// ── computeNetCost ──────────────────────────────────────────────────────────

describe('computeNetCost', () => {
  it('returns netCost field when present', () => {
    expect(computeNetCost({ netCost: 42.5, net_cost: 99, cost: 50, credits: -5 })).toBe(42.5);
  });

  it('returns net_cost field when netCost is absent', () => {
    expect(computeNetCost({ net_cost: 30.0, cost: 50, credits: -5 })).toBe(30.0);
  });

  it('falls back to cost + credits when both net fields are absent', () => {
    expect(computeNetCost({ cost: 50, credits: -8 })).toBe(42);
  });

  it('treats missing credits as 0 in fallback', () => {
    expect(computeNetCost({ cost: 75 })).toBe(75);
  });

  it('returns 0 when all fields are null or absent', () => {
    expect(computeNetCost({})).toBe(0);
  });

  it('returns 0 for null row', () => {
    expect(computeNetCost(null)).toBe(0);
  });
});

// ── buildBreakdownDatasets ──────────────────────────────────────────────────

describe('buildBreakdownDatasets', () => {
  it('returns empty arrays for empty input', () => {
    const result = buildBreakdownDatasets([]);
    expect(result.services).toEqual([]);
    expect(result.datasets).toEqual([]);
  });

  it('groups rows by service and accumulates cost per app', () => {
    const rows = [
      { service: 'Compute', app: 'Styln',       cost: 100 },
      { service: 'Compute', app: 'Spin & Dine', cost: 40 },
      { service: 'Storage', app: 'Styln',       cost: 20 },
    ];
    const result = buildBreakdownDatasets(rows);
    expect(result.services).toContain('Compute');
    expect(result.services).toContain('Storage');

    const computeIdx = result.services.indexOf('Compute');
    const stylnDataset = result.datasets.find(d => d.label === 'Styln');
    expect(stylnDataset.data[computeIdx]).toBe(100);
  });

  it('sorts services by total cost descending', () => {
    const rows = [
      { service: 'Cheap',     app: 'Styln', cost: 10 },
      { service: 'Expensive', app: 'Styln', cost: 500 },
      { service: 'Mid',       app: 'Styln', cost: 100 },
    ];
    const result = buildBreakdownDatasets(rows);
    expect(result.services[0]).toBe('Expensive');
    expect(result.services[1]).toBe('Mid');
    expect(result.services[2]).toBe('Cheap');
  });

  it('caps at top 10 services', () => {
    const rows = Array.from({ length: 15 }, (_, i) => ({
      service: `Service${i}`,
      app: 'Styln',
      cost: i + 1,
    }));
    const result = buildBreakdownDatasets(rows);
    expect(result.services.length).toBe(10);
  });

  it('uses Unknown for missing service field', () => {
    const rows = [{ app: 'Styln', cost: 50 }];
    const result = buildBreakdownDatasets(rows);
    expect(result.services).toContain('Unknown');
  });

  it('uses 0 for missing cost field', () => {
    const rows = [{ service: 'Compute', app: 'Styln' }];
    const result = buildBreakdownDatasets(rows);
    expect(result.services).toContain('Compute');
  });
});

// ── normalizeTrendData ──────────────────────────────────────────────────────

describe('normalizeTrendData', () => {
  it('returns empty array for empty input', () => {
    expect(normalizeTrendData([])).toEqual([]);
  });

  it('passes through AXIOM row-per-app shape unchanged (minus Admin)', () => {
    const trend = [
      { month: '202510', app: 'Styln',       cost: 200 },
      { month: '202510', app: 'Spin & Dine', cost: 40  },
      { month: '202510', app: 'Admin',        cost: 5   },
    ];
    const result = normalizeTrendData(trend);
    expect(result.length).toBe(2);
    expect(result.some(r => r.app === 'Admin')).toBe(false);
    expect(result.some(r => r.app === 'Styln')).toBe(true);
  });

  it('expands Jarvis per-column shape to row-per-app', () => {
    const trend = [
      { month: '2025-10', 'Styln': 200, 'Spin & Dine': 40 },
      { month: '2025-11', 'Styln': 210 },
    ];
    const result = normalizeTrendData(trend);
    expect(result.some(r => r.app === 'Styln'   && r.month === '2025-10' && r.cost === 200)).toBe(true);
    expect(result.some(r => r.app === 'Spin & Dine' && r.month === '2025-10' && r.cost === 40)).toBe(true);
    expect(result.some(r => r.app === 'Styln'   && r.month === '2025-11' && r.cost === 210)).toBe(true);
  });

  it('filters rows with no app value in AXIOM shape', () => {
    const trend = [
      { month: '202510', app: null,    cost: 10 },
      { month: '202510', app: 'Styln', cost: 200 },
    ];
    const result = normalizeTrendData(trend);
    expect(result.length).toBe(1);
  });

  it('filters Admin from AXIOM shape', () => {
    const trend = [
      { month: '202510', app: 'Admin', cost: 50 },
    ];
    const result = normalizeTrendData(trend);
    expect(result.length).toBe(0);
  });
});

// ── fmtLabel ────────────────────────────────────────────────────────────────

describe('fmtLabel', () => {
  it('formats "2025-10" as "Oct \'25"', () => {
    expect(fmtLabel('2025-10')).toBe("Oct '25");
  });

  it('formats "202510" (no dash) as "Oct \'25"', () => {
    expect(fmtLabel('202510')).toBe("Oct '25");
  });

  it('formats "2025-01" as "Jan \'25"', () => {
    expect(fmtLabel('2025-01')).toBe("Jan '25");
  });

  it('formats "2025-12" as "Dec \'25"', () => {
    expect(fmtLabel('2025-12')).toBe("Dec '25");
  });

  it('returns original value for unrecognized format', () => {
    expect(fmtLabel('bad')).toBe('bad');
  });
});

// ── Constants ───────────────────────────────────────────────────────────────

describe('BUDGET_MAP', () => {
  it('exports correct budget values', () => {
    expect(BUDGET_MAP['Styln']).toBe(300);
    expect(BUDGET_MAP['Spin & Dine']).toBe(100);
    expect(BUDGET_MAP['QuantRE/Axiom']).toBe(25);
  });
});

describe('APP_COLORS', () => {
  it('exports color for each known app', () => {
    expect(APP_COLORS['Styln']).toBe('#3b82f6');
    expect(APP_COLORS['Spin & Dine']).toBe('#22c55e');
    expect(APP_COLORS['QuantRE/Axiom']).toBe('#a855f7');
    expect(APP_COLORS['Admin']).toBe('#64748b');
  });
});
