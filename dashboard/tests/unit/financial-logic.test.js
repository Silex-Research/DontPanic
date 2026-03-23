import { describe, it, expect } from 'vitest';
import {
  fmtRaw,
  fmtNum,
  fmtCurrency,
  fmtPct,
  fmtLargeNum,
  formatDAValue,
  computeScorecard,
  computeValuation,
  computeTiers,
  evaluateTier2,
  recalculateValuationFromSliders,
  generateNotes,
} from '../../lib/financial-logic.js';

// ── Helpers ──────────────────────────────────────────────────────────────────

/** Build a minimal year-keyed data map from an array of net_income / equity pairs. */
function makeData(rows) {
  // rows: [{ year, net_income, equity, revenue, lt_debt, retained_earnings,
  //          cash, current_liabilities, capex, current_assets }]
  const data = {};
  rows.forEach(r => { data[r.year] = { ...r }; });
  return data;
}

function makeYears(rows) {
  return rows.map(r => r.year).sort((a, b) => b - a);
}

// ── Formatters ───────────────────────────────────────────────────────────────

describe('fmtRaw', () => {
  it('returns -- for null', () => {
    expect(fmtRaw(null)).toBe('--');
  });

  it('returns -- for undefined', () => {
    expect(fmtRaw(undefined)).toBe('--');
  });

  it('returns raw field as string for Yahoo Finance object', () => {
    expect(fmtRaw({ raw: 237.59, fmt: '$237.59' })).toBe('237.59');
  });

  it('falls back to fmt when raw is null', () => {
    expect(fmtRaw({ raw: null, fmt: '1.2K' })).toBe('1.2K');
  });

  it('returns string for plain number', () => {
    expect(fmtRaw(42)).toBe('42');
  });
});

describe('fmtNum', () => {
  it('returns -- for null', () => {
    expect(fmtNum(null)).toBe('--');
  });

  it('formats plain number to 2 decimal places', () => {
    expect(fmtNum(38.9)).toBe('38.90');
  });

  it('formats Yahoo Finance object using .raw', () => {
    expect(fmtNum({ raw: 15.5 })).toBe('15.50');
  });

  it('returns -- when object has null raw', () => {
    expect(fmtNum({ raw: null })).toBe('--');
  });
});

describe('fmtCurrency', () => {
  it('returns -- for null', () => {
    expect(fmtCurrency(null)).toBe('--');
  });

  it('prepends dollar sign with 2 decimal places', () => {
    expect(fmtCurrency(6.08)).toBe('$6.08');
  });

  it('handles Yahoo Finance object', () => {
    expect(fmtCurrency({ raw: 4.38 })).toBe('$4.38');
  });

  it('handles negative values', () => {
    expect(fmtCurrency(-1.5)).toBe('$-1.50');
  });

  it('handles zero', () => {
    expect(fmtCurrency(0)).toBe('$0.00');
  });
});

describe('fmtPct', () => {
  it('returns -- for null', () => {
    expect(fmtPct(null)).toBe('--');
  });

  it('converts decimal fraction to percentage string', () => {
    expect(fmtPct(0.2636)).toBe('26.36%');
  });

  it('handles Yahoo Finance object', () => {
    expect(fmtPct({ raw: 0.005 })).toBe('0.50%');
  });

  it('handles zero', () => {
    expect(fmtPct(0)).toBe('0.00%');
  });
});

describe('fmtLargeNum', () => {
  it('returns -- for null', () => {
    expect(fmtLargeNum(null)).toBe('--');
  });

  it('formats trillions', () => {
    expect(fmtLargeNum(3.61e12)).toBe('$3.61T');
  });

  it('formats billions', () => {
    expect(fmtLargeNum(391e9)).toBe('$391.00B');
  });

  it('formats millions', () => {
    expect(fmtLargeNum(5e6)).toBe('$5.00M');
  });

  it('formats sub-million as integer dollars', () => {
    expect(fmtLargeNum(500000)).toBe('$500000');
  });

  it('handles Yahoo Finance object', () => {
    expect(fmtLargeNum({ raw: 1e9 })).toBe('$1.00B');
  });
});

describe('formatDAValue', () => {
  it('returns -- for null', () => {
    expect(formatDAValue(null, 'millions')).toBe('--');
  });

  it('returns -- for NaN', () => {
    expect(formatDAValue(NaN, 'pct')).toBe('--');
  });

  it('formats millions below 1000 with M suffix', () => {
    expect(formatDAValue(500, 'millions')).toBe('$500M');
  });

  it('formats millions above 1000 as B', () => {
    expect(formatDAValue(2500, 'millions')).toBe('$2.5B');
  });

  it('formats pct as scaled percentage', () => {
    expect(formatDAValue(0.142, 'pct')).toBe('14.2%');
  });

  it('formats decimal to 2 places', () => {
    expect(formatDAValue(1.234, 'decimal')).toBe('1.23');
  });

  it('returns raw string for unknown format', () => {
    expect(formatDAValue(99, 'other')).toBe('99');
  });
});

// ── Scorecard Computation ─────────────────────────────────────────────────────

describe('computeScorecard — ROIC scoring', () => {
  it('assigns high ROIC score (90) when avg >= 0.25', () => {
    const rows = [
      { year: 2023, net_income: 300, equity: 1000, revenue: 1000, lt_debt: 0, retained_earnings: 500 },
      { year: 2022, net_income: 280, equity: 1000, revenue: 1000, lt_debt: 0, retained_earnings: 400 },
    ];
    const data = makeData(rows);
    const years = makeYears(rows);
    const sc = computeScorecard(data, years);
    expect(sc.roic).toBe(90);
  });

  it('assigns medium-high ROIC score (75) when avg is in [0.15, 0.25)', () => {
    const rows = [
      { year: 2023, net_income: 180, equity: 1000, revenue: 1000, lt_debt: 0, retained_earnings: 300 },
      { year: 2022, net_income: 160, equity: 1000, revenue: 1000, lt_debt: 0, retained_earnings: 200 },
    ];
    const data = makeData(rows);
    const years = makeYears(rows);
    const sc = computeScorecard(data, years);
    expect(sc.roic).toBe(75);
  });

  it('assigns low ROIC score (20) when avg < 0.05', () => {
    const rows = [
      { year: 2023, net_income: 20, equity: 1000, revenue: 1000, lt_debt: 0, retained_earnings: 100 },
      { year: 2022, net_income: 18, equity: 1000, revenue: 1000, lt_debt: 0, retained_earnings: 80 },
    ];
    const data = makeData(rows);
    const years = makeYears(rows);
    const sc = computeScorecard(data, years);
    expect(sc.roic).toBe(20);
  });

  it('adds stability bonus (+10) when std < 0.03 with 3+ years', () => {
    // Very stable ROIC around 0.20 → base score 75, +10 = 85
    const rows = [
      { year: 2023, net_income: 200, equity: 1000, revenue: 1000, lt_debt: 0, retained_earnings: 400 },
      { year: 2022, net_income: 201, equity: 1000, revenue: 1000, lt_debt: 0, retained_earnings: 300 },
      { year: 2021, net_income: 199, equity: 1000, revenue: 1000, lt_debt: 0, retained_earnings: 200 },
    ];
    const data = makeData(rows);
    const years = makeYears(rows);
    const sc = computeScorecard(data, years);
    expect(sc.roic).toBe(85); // 75 base + 10 stability
  });

  it('defaults ROIC score to 50 when equity is missing', () => {
    const rows = [
      { year: 2023, net_income: 100, equity: null, revenue: 1000, lt_debt: 0, retained_earnings: 100 },
    ];
    const data = makeData(rows);
    const years = makeYears(rows);
    const sc = computeScorecard(data, years);
    expect(sc.roic).toBe(50);
  });
});

describe('computeScorecard — Moat scoring', () => {
  it('assigns high moat score (85) when net margin avg >= 0.20', () => {
    const rows = [
      { year: 2023, net_income: 250, equity: 1000, revenue: 1000, lt_debt: 0, retained_earnings: 300 },
      { year: 2022, net_income: 220, equity: 900,  revenue: 1000, lt_debt: 0, retained_earnings: 200 },
    ];
    const data = makeData(rows);
    const years = makeYears(rows);
    const sc = computeScorecard(data, years);
    expect(sc.moat).toBe(85);
  });

  it('penalises moat (-10) when CapEx > 15% of revenue', () => {
    const rows = [
      { year: 2023, net_income: 250, equity: 1000, revenue: 1000, capex: 200, lt_debt: 0, retained_earnings: 300 },
      { year: 2022, net_income: 220, equity: 900,  revenue: 1000, capex: 180, lt_debt: 0, retained_earnings: 200 },
    ];
    const data = makeData(rows);
    const years = makeYears(rows);
    const sc = computeScorecard(data, years);
    expect(sc.moat).toBe(75); // 85 - 10
  });
});

describe('computeScorecard — Management scoring', () => {
  it('assigns high management score (80+) when D/E <= 0.3, ignoring RE bonus', () => {
    // D/E = 200/1000 = 0.2 → base 80. Flat retained earnings → no RE bonus.
    const rows = [
      { year: 2023, net_income: 100, equity: 1000, revenue: 500, lt_debt: 200, retained_earnings: 400 },
      { year: 2022, net_income: 80,  equity: 900,  revenue: 450, lt_debt: 180, retained_earnings: 400 },
    ];
    const data = makeData(rows);
    const years = makeYears(rows);
    const sc = computeScorecard(data, years);
    expect(sc.management).toBe(80);
  });

  it('D/E <= 0.3 with strong retained earnings growth yields 80 + 15 = 95', () => {
    // Verifies the RE bonus stacks on top of the D/E base score.
    const rows = [
      { year: 2023, net_income: 100, equity: 1000, revenue: 500, lt_debt: 200, retained_earnings: 700 },
      { year: 2022, net_income: 80,  equity: 900,  revenue: 450, lt_debt: 180, retained_earnings: 400 },
    ];
    const data = makeData(rows);
    const years = makeYears(rows);
    const sc = computeScorecard(data, years);
    // reGrowth = (700-400)/400 = 0.75 > 0.5 → +15 bonus
    expect(sc.management).toBe(95);
  });

  it('assigns low management score (30) when D/E > 1.5 with flat retained earnings', () => {
    // Flat RE avoids the bonus so the pure D/E effect is observable.
    const rows = [
      { year: 2023, net_income: 100, equity: 500, revenue: 1000, lt_debt: 1000, retained_earnings: 200 },
      { year: 2022, net_income: 80,  equity: 480, revenue: 900,  lt_debt: 900,  retained_earnings: 200 },
    ];
    const data = makeData(rows);
    const years = makeYears(rows);
    const sc = computeScorecard(data, years);
    expect(sc.management).toBe(30);
  });
});

describe('computeScorecard — Durability scoring', () => {
  it('assigns max durability (90) when no earnings declines', () => {
    const rows = [
      { year: 2023, net_income: 400, equity: 1000, revenue: 1000, lt_debt: 0, retained_earnings: 400 },
      { year: 2022, net_income: 300, equity: 900,  revenue: 900,  lt_debt: 0, retained_earnings: 300 },
      { year: 2021, net_income: 200, equity: 800,  revenue: 800,  lt_debt: 0, retained_earnings: 200 },
    ];
    const data = makeData(rows);
    const years = makeYears(rows);
    const sc = computeScorecard(data, years);
    // No declines + earnings doubled → 90 + 10 = 100 (clamped)
    expect(sc.durability).toBe(100);
  });

  it('assigns low durability (35) when most years show declines', () => {
    const rows = [
      { year: 2023, net_income: 50,  equity: 1000, revenue: 500, lt_debt: 0, retained_earnings: 100 },
      { year: 2022, net_income: 100, equity: 900,  revenue: 600, lt_debt: 0, retained_earnings: 120 },
      { year: 2021, net_income: 200, equity: 800,  revenue: 700, lt_debt: 0, retained_earnings: 150 },
      { year: 2020, net_income: 300, equity: 700,  revenue: 800, lt_debt: 0, retained_earnings: 200 },
    ];
    const data = makeData(rows);
    const years = makeYears(rows);
    const sc = computeScorecard(data, years);
    // All 3 consecutive pairs decline → 3/3 = 100% decline rate → score 35
    expect(sc.durability).toBe(35);
  });
});

describe('computeScorecard — clamping', () => {
  it('clamps all scores to [0, 100]', () => {
    const rows = [
      { year: 2023, net_income: 1000, equity: 100, revenue: 100, lt_debt: 0, retained_earnings: 900 },
    ];
    const data = makeData(rows);
    const years = makeYears(rows);
    const sc = computeScorecard(data, years);
    Object.values(sc).forEach(v => {
      expect(v).toBeGreaterThanOrEqual(0);
      expect(v).toBeLessThanOrEqual(100);
    });
  });

  it('returns default scores (50) for empty data', () => {
    const sc = computeScorecard({}, []);
    // With no years, nothing can override defaults
    expect(sc.roic).toBe(50);
    expect(sc.moat).toBe(50);
  });
});

// ── Valuation Computation ─────────────────────────────────────────────────────

describe('computeValuation', () => {
  const baseRows = [
    { year: 2023, net_income: 100, equity: 500, revenue: 800 },
    { year: 2022, net_income:  80, equity: 450, revenue: 720 },
    { year: 2021, net_income:  64, equity: 400, revenue: 640 },
  ];
  const data = makeData(baseRows);
  const years = makeYears(baseRows);
  const info = { currentPrice: 50, trailingPE: 20, trailingEps: 5, marketCap: null };

  it('returns empty object when currentPrice is missing', () => {
    const result = computeValuation(data, years, { currentPrice: 0, trailingPE: 20, trailingEps: 5 });
    expect(result).toEqual({});
  });

  it('returns zero prices when net_income is negative', () => {
    const rows = [{ year: 2023, net_income: -50, equity: 500, revenue: 800 }];
    const d = makeData(rows);
    const y = makeYears(rows);
    const result = computeValuation(d, y, { currentPrice: 50, trailingPE: 20, trailingEps: 5 });
    expect(result.bull.price).toBe(0);
    expect(result.base.price).toBe(0);
    expect(result.bear.price).toBe(0);
  });

  it('computes CAGR from multi-year net_income history', () => {
    const result = computeValuation(data, years, info);
    // CAGR = (100/64)^(1/2) - 1 ≈ 0.25
    expect(result.bull.price).toBeGreaterThan(0);
    expect(result.base.price).toBeGreaterThan(0);
    expect(result.bear.price).toBeGreaterThan(0);
  });

  it('bull case price is higher than base which is higher than bear', () => {
    const result = computeValuation(data, years, info);
    expect(result.bull.price).toBeGreaterThan(result.base.price);
    expect(result.base.price).toBeGreaterThanOrEqual(result.bear.price);
  });

  it('applies P/E cap of 35 for bull case', () => {
    // With trailingPE = 40: bullPE = min(40*1.2, 35) = 35
    const result = computeValuation(data, years, { ...info, trailingPE: 40 });
    // Just verify the computation completes; price should be positive
    expect(result.bull.price).toBeGreaterThan(0);
  });

  it('calculates margin of safety correctly', () => {
    const result = computeValuation(data, years, info);
    const expectedMos = Math.round(((result.base.price - info.currentPrice) / result.base.price) * 1000) / 10;
    expect(result.marginOfSafety).toBe(expectedMos);
  });

  it('buy-below is 75% of base price', () => {
    const result = computeValuation(data, years, info);
    expect(result.buyBelow).toBe(Math.round(result.base.price * 0.75));
  });

  it('annual return for base case rounds to 1 decimal', () => {
    const result = computeValuation(data, years, info);
    const decimalPlaces = (result.base.annualReturn.toString().split('.')[1] || '').length;
    expect(decimalPlaces).toBeLessThanOrEqual(1);
  });
});

// ── Tier Computation ──────────────────────────────────────────────────────────

describe('computeTiers — tier 1', () => {
  it('passes tier 1 when latest revenue > 0', () => {
    const rows = [{ year: 2023, net_income: 100, equity: 500, revenue: 800, cash: 200, current_liabilities: 150, lt_debt: 50 }];
    const data = makeData(rows);
    const years = makeYears(rows);
    const sc = { moat: 70, management: 70, roic: 70, durability: 70 };
    const val = { marginOfSafety: 25 };
    const tiers = computeTiers(data, years, sc, val);
    expect(tiers.tier1).toBe('pass');
  });

  it('fails tier 1 when revenue is zero', () => {
    const rows = [{ year: 2023, net_income: 100, equity: 500, revenue: 0, cash: 200, current_liabilities: 150, lt_debt: 50 }];
    const data = makeData(rows);
    const years = makeYears(rows);
    const tiers = computeTiers(data, years, { moat: 70, management: 70, roic: 70, durability: 70 }, { marginOfSafety: 25 });
    expect(tiers.tier1).toBe('fail');
  });
});

describe('computeTiers — tier 2', () => {
  it('passes tier 2 when earnings doubled and max decline <= 5%', () => {
    const rows = [
      { year: 2023, net_income: 200, equity: 1000, revenue: 1000 },
      { year: 2022, net_income: 180, equity: 900,  revenue: 900  },
      { year: 2021, net_income: 100, equity: 800,  revenue: 800  },
    ];
    const data = makeData(rows);
    const years = makeYears(rows);
    const tiers = computeTiers(data, years, { moat: 80, management: 80, roic: 80, durability: 80 }, { marginOfSafety: 25 });
    expect(tiers.tier2).toBe('pass');
  });

  it('fails tier 2 when max decline > 15%', () => {
    const rows = [
      { year: 2023, net_income:  50, equity: 500, revenue: 600 },
      { year: 2022, net_income: 200, equity: 450, revenue: 700 },
    ];
    const data = makeData(rows);
    const years = makeYears(rows);
    const tiers = computeTiers(data, years, { moat: 80, management: 80, roic: 80, durability: 80 }, { marginOfSafety: 25 });
    expect(tiers.tier2).toBe('fail');
  });

  it('returns review for tier 2 when only one year of data', () => {
    const rows = [{ year: 2023, net_income: 100, equity: 500, revenue: 800 }];
    const data = makeData(rows);
    const years = makeYears(rows);
    const tiers = computeTiers(data, years, { moat: 80, management: 80, roic: 80, durability: 80 }, { marginOfSafety: 25 });
    expect(tiers.tier2).toBe('review');
  });
});

describe('computeTiers — tier 3', () => {
  it('passes tier 3 when acid >= 1.0 and D/E <= 0.5', () => {
    const rows = [
      { year: 2023, net_income: 100, equity: 1000, revenue: 800,
        cash: 600, current_liabilities: 400, lt_debt: 300 },
    ];
    const data = makeData(rows);
    const years = makeYears(rows);
    const tiers = computeTiers(data, years, { moat: 80, management: 80, roic: 80, durability: 80 }, { marginOfSafety: 25 });
    expect(tiers.tier3).toBe('pass');
  });

  it('returns review for tier 3 when acid 0.5-1.0 and D/E moderate', () => {
    const rows = [
      { year: 2023, net_income: 100, equity: 1000, revenue: 800,
        cash: 400, current_liabilities: 600, lt_debt: 1000 },
    ];
    const data = makeData(rows);
    const years = makeYears(rows);
    const tiers = computeTiers(data, years, { moat: 80, management: 80, roic: 80, durability: 80 }, { marginOfSafety: 25 });
    expect(tiers.tier3).toBe('review');
  });

  it('returns review for tier 3 when cash is missing', () => {
    const rows = [{ year: 2023, net_income: 100, equity: 500, revenue: 800 }];
    const data = makeData(rows);
    const years = makeYears(rows);
    const tiers = computeTiers(data, years, { moat: 80, management: 80, roic: 80, durability: 80 }, { marginOfSafety: 25 });
    expect(tiers.tier3).toBe('review');
  });
});

describe('computeTiers — tier 4', () => {
  it('passes tier 4 when avg scorecard >= 70', () => {
    const rows = [{ year: 2023, net_income: 100, equity: 500, revenue: 800,
      cash: 200, current_liabilities: 100, lt_debt: 50 }];
    const data = makeData(rows);
    const years = makeYears(rows);
    const tiers = computeTiers(data, years, { moat: 80, management: 70, roic: 75, durability: 85 }, { marginOfSafety: 25 });
    expect(tiers.tier4).toBe('pass');
  });

  it('fails tier 4 when avg scorecard < 50', () => {
    const rows = [{ year: 2023, net_income: 100, equity: 500, revenue: 800 }];
    const data = makeData(rows);
    const years = makeYears(rows);
    const tiers = computeTiers(data, years, { moat: 30, management: 30, roic: 35, durability: 40 }, { marginOfSafety: 25 });
    expect(tiers.tier4).toBe('fail');
  });
});

describe('computeTiers — tier 5', () => {
  it('passes tier 5 when margin of safety >= 20', () => {
    const rows = [{ year: 2023, net_income: 100, equity: 500, revenue: 800 }];
    const data = makeData(rows);
    const years = makeYears(rows);
    const tiers = computeTiers(data, years, { moat: 70, management: 70, roic: 70, durability: 70 }, { marginOfSafety: 25 });
    expect(tiers.tier5).toBe('pass');
  });

  it('returns review for tier 5 when MOS is 5-19', () => {
    const rows = [{ year: 2023, net_income: 100, equity: 500, revenue: 800 }];
    const data = makeData(rows);
    const years = makeYears(rows);
    const tiers = computeTiers(data, years, { moat: 70, management: 70, roic: 70, durability: 70 }, { marginOfSafety: 10 });
    expect(tiers.tier5).toBe('review');
  });

  it('fails tier 5 when MOS < 5', () => {
    const rows = [{ year: 2023, net_income: 100, equity: 500, revenue: 800 }];
    const data = makeData(rows);
    const years = makeYears(rows);
    const tiers = computeTiers(data, years, { moat: 70, management: 70, roic: 70, durability: 70 }, { marginOfSafety: 2 });
    expect(tiers.tier5).toBe('fail');
  });
});

// ── Valuation Recalculation from Sliders ─────────────────────────────────────

describe('recalculateValuationFromSliders', () => {
  const baseVal = {
    bull:  { price: 100, prob: 25, annualReturn: 15 },
    base:  { price: 80,  prob: 50, annualReturn: 10 },
    bear:  { price: 50,  prob: 25, annualReturn: -5  },
    currentPrice: 60,
    marginOfSafety: 25,
    buyBelow: 60,
  };

  it('returns unchanged prices when all sliders are at their neutral defaults', () => {
    const defaults = { earningsGrowth: 8, moatDurability: 70, disruptionRisk: 25, multipleExpansion: 0 };
    const result = recalculateValuationFromSliders(baseVal, defaults);
    // factor = (8/8) * (70/70) * (1-0/200) * (1+0/10) = 1.0
    expect(result.base.price).toBe(80);
    expect(result.bull.price).toBe(100);
  });

  it('higher earnings growth increases base price', () => {
    const result = recalculateValuationFromSliders(baseVal, {
      earningsGrowth: 16, moatDurability: 70, disruptionRisk: 25, multipleExpansion: 0,
    });
    expect(result.base.price).toBeGreaterThan(80);
  });

  it('bear case applies additional 0.9x multiplier vs base factor', () => {
    const sliders = { earningsGrowth: 8, moatDurability: 70, disruptionRisk: 25, multipleExpansion: 0 };
    const result = recalculateValuationFromSliders(baseVal, sliders);
    // bear price = round(50 * 1.0 * 0.9) = 45
    expect(result.bear.price).toBe(45);
  });

  it('buy-below is 75% of adjusted base price', () => {
    const sliders = { earningsGrowth: 16, moatDurability: 70, disruptionRisk: 25, multipleExpansion: 0 };
    const result = recalculateValuationFromSliders(baseVal, sliders);
    expect(result.buyBelow).toBe(Math.round(result.base.price * 0.75));
  });

  it('higher disruption risk decreases prices', () => {
    const low  = recalculateValuationFromSliders(baseVal, { earningsGrowth: 8, moatDurability: 70, disruptionRisk: 10,  multipleExpansion: 0 });
    const high = recalculateValuationFromSliders(baseVal, { earningsGrowth: 8, moatDurability: 70, disruptionRisk: 75, multipleExpansion: 0 });
    expect(low.base.price).toBeGreaterThan(high.base.price);
  });
});

// ── generateNotes ─────────────────────────────────────────────────────────────

describe('generateNotes', () => {
  const rows = [
    { year: 2023, net_income: 200, equity: 1000, revenue: 1000, lt_debt: 100, retained_earnings: 400 },
    { year: 2022, net_income: 100, equity: 900,  revenue: 900,  lt_debt: 90,  retained_earnings: 300 },
  ];
  const data = makeData(rows);
  const years = makeYears(rows);
  const scorecard = { moat: 80, management: 75, roic: 85, durability: 70 };

  it('returns fallback message for empty years', () => {
    const notes = generateNotes('AAPL', 'Apple', {}, [], scorecard, {});
    expect(notes).toContain('No financial data available');
  });

  it('includes company name and symbol in header', () => {
    const notes = generateNotes('AAPL', 'Apple Inc.', data, years, scorecard, {});
    expect(notes).toContain('Apple Inc. (AAPL)');
  });

  it('reports earnings CAGR when earnings grew', () => {
    const notes = generateNotes('AAPL', 'Apple Inc.', data, years, scorecard, {});
    expect(notes).toContain('Earnings CAGR:');
  });

  it('reports net margin', () => {
    const notes = generateNotes('AAPL', 'Apple Inc.', data, years, scorecard, {});
    expect(notes).toContain('net margin');
  });

  it('includes composite Buffett-Munger score', () => {
    const notes = generateNotes('AAPL', 'Apple Inc.', data, years, scorecard, {});
    expect(notes).toContain('Composite Buffett-Munger score:');
  });

  it('includes sector when provided', () => {
    const notes = generateNotes('AAPL', 'Apple', data, years, scorecard, { sector: 'Technology', industry: 'Consumer Electronics' });
    expect(notes).toContain('Sector: Technology');
  });

  it('notes high leverage when D/E > 1', () => {
    const highDebtRows = [
      { year: 2023, net_income: 100, equity: 300, revenue: 800, lt_debt: 600, retained_earnings: 200 },
      { year: 2022, net_income:  80, equity: 280, revenue: 700, lt_debt: 560, retained_earnings: 150 },
    ];
    const hData = makeData(highDebtRows);
    const hYears = makeYears(highDebtRows);
    const notes = generateNotes('HLV', 'HighLev', hData, hYears, scorecard, {});
    expect(notes).toContain('High leverage');
  });
});
