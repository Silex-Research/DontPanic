// ── Jarvis Dashboard — Financial Analysis Pure Logic ──
// All functions are pure (no DOM, no network, no module state).
// Extracted from pages/financial/financial.js for testability.

// ── Yahoo Finance value extractors ──

/**
 * Returns raw value as a string, preferring .raw over .fmt for Yahoo Finance
 * objects; passes through primitives.
 * @param {*} val
 * @returns {string}
 */
export function fmtRaw(val) {
  if (val == null) return '--';
  if (typeof val === 'object' && val.raw != null) return String(val.raw);
  if (typeof val === 'object' && val.fmt != null) return val.fmt;
  return String(val);
}

/**
 * Returns the numeric value formatted to 2 decimal places, or '--'.
 * Accepts bare numbers or Yahoo Finance objects with a .raw field.
 * @param {*} val
 * @returns {string}
 */
export function fmtNum(val) {
  if (val == null) return '--';
  const raw = typeof val === 'object' ? val.raw : val;
  if (raw == null) return '--';
  return parseFloat(raw).toFixed(2);
}

/**
 * Returns the numeric value formatted as a USD dollar amount, or '--'.
 * @param {*} val
 * @returns {string}
 */
export function fmtCurrency(val) {
  if (val == null) return '--';
  const raw = typeof val === 'object' ? val.raw : val;
  if (raw == null) return '--';
  return '$' + parseFloat(raw).toFixed(2);
}

/**
 * Returns the numeric value (treated as a decimal fraction) formatted as a
 * percentage string, or '--'.
 * @param {*} val
 * @returns {string}
 */
export function fmtPct(val) {
  if (val == null) return '--';
  const raw = typeof val === 'object' ? val.raw : val;
  if (raw == null) return '--';
  return (parseFloat(raw) * 100).toFixed(2) + '%';
}

/**
 * Returns large numbers abbreviated with T / B / M suffixes and a leading '$'.
 * Falls back to '--' for null/undefined.
 * @param {*} val
 * @returns {string}
 */
export function fmtLargeNum(val) {
  if (val == null) return '--';
  const raw = typeof val === 'object' ? val.raw : val;
  if (raw == null) return '--';
  const n = parseFloat(raw);
  if (n >= 1e12) return '$' + (n / 1e12).toFixed(2) + 'T';
  if (n >= 1e9)  return '$' + (n / 1e9).toFixed(2) + 'B';
  if (n >= 1e6)  return '$' + (n / 1e6).toFixed(2) + 'M';
  return '$' + n.toFixed(0);
}

/**
 * Formats a pre-scaled value (millions, percent, decimal) for the Deep
 * Analysis table.
 * @param {number|null} val
 * @param {'millions'|'pct'|'decimal'|string} format
 * @returns {string}
 */
export function formatDAValue(val, format) {
  if (val == null || isNaN(val)) return '--';
  switch (format) {
    case 'millions':
      return val >= 1000
        ? '$' + (val / 1000).toFixed(1) + 'B'
        : '$' + val.toLocaleString() + 'M';
    case 'pct':
      return (val * 100).toFixed(1) + '%';
    case 'decimal':
      return val.toFixed(2);
    default:
      return String(val);
  }
}

// ── Buffett-Munger Scorecard ──

/**
 * Computes the four-dimension Buffett-Munger scorecard from multi-year
 * financial data.
 *
 * @param {Record<number, object>} data  - Year-keyed financial rows.
 * @param {number[]}               years - Descending-sorted year list.
 * @returns {{ moat: number, management: number, roic: number, durability: number }}
 */
export function computeScorecard(data, years) {
  // ROIC quality
  let roicScore = 50;
  const roicVals = years.map(y => {
    const d = data[y];
    return d.net_income && d.equity && d.equity > 0 ? d.net_income / d.equity : null;
  }).filter(v => v != null);
  if (roicVals.length) {
    const avg = roicVals.reduce((s, v) => s + v, 0) / roicVals.length;
    roicScore = avg >= 0.25 ? 90 : avg >= 0.15 ? 75 : avg >= 0.10 ? 60 : avg >= 0.05 ? 40 : 20;
    if (roicVals.length >= 3) {
      const mean = roicVals.reduce((s, v) => s + v, 0) / roicVals.length;
      const std = Math.sqrt(roicVals.reduce((s, v) => s + (v - mean) ** 2, 0) / roicVals.length);
      if (std < 0.03) roicScore = Math.min(100, roicScore + 10);
    }
  }

  // Economic moat (margins + capital efficiency)
  let moatScore = 50;
  const margins = years.map(y => {
    const d = data[y];
    return d.net_income != null && d.revenue && d.revenue > 0
      ? d.net_income / d.revenue
      : null;
  }).filter(v => v != null);
  if (margins.length) {
    const avg = margins.reduce((s, v) => s + v, 0) / margins.length;
    moatScore = avg >= 0.20 ? 85 : avg >= 0.12 ? 70 : avg >= 0.06 ? 55 : 35;
    const latest = data[years[0]];
    if (latest.capex && latest.revenue && latest.revenue > 0 && latest.capex / latest.revenue > 0.15) {
      moatScore = Math.max(0, moatScore - 10);
    }
  }

  // Management quality (debt discipline + retained earnings growth)
  let mgmtScore = 50;
  const latestD = data[years[0]] || {};
  const eq = latestD.equity;
  const ltd = latestD.lt_debt || 0;
  if (eq && eq > 0) {
    const deRatio = ltd / eq;
    mgmtScore = deRatio <= 0.3 ? 80 : deRatio <= 0.8 ? 65 : deRatio <= 1.5 ? 50 : 30;
  }
  const reVals = years.map(y => data[y]?.retained_earnings).filter(v => v != null);
  if (reVals.length >= 2 && reVals[reVals.length - 1] && reVals[reVals.length - 1] > 0) {
    const reGrowth = (reVals[0] - reVals[reVals.length - 1]) / Math.abs(reVals[reVals.length - 1]);
    if (reGrowth > 0.5)       mgmtScore = Math.min(100, mgmtScore + 15);
    else if (reGrowth > 0.2)  mgmtScore = Math.min(100, mgmtScore + 5);
  }

  // Earnings durability (stability over time)
  let durScore = 50;
  const niVals = years.map(y => data[y]?.net_income).filter(v => v != null);
  if (niVals.length >= 3) {
    const declines = niVals.slice(0, -1).filter((v, i) => v < niVals[i + 1]).length;
    const declinePct = declines / (niVals.length - 1);
    durScore = declinePct === 0 ? 90 : declinePct <= 0.2 ? 75 : declinePct <= 0.4 ? 55 : 35;
    if (niVals[0] && niVals[niVals.length - 1] > 0 && niVals[0] / niVals[niVals.length - 1] >= 2) {
      durScore = Math.min(100, durScore + 10);
    }
  }

  return {
    moat:       Math.max(0, Math.min(100, moatScore)),
    management: Math.max(0, Math.min(100, mgmtScore)),
    roic:       Math.max(0, Math.min(100, roicScore)),
    durability: Math.max(0, Math.min(100, durScore)),
  };
}

// ── Intrinsic Value Computation ──

/**
 * Computes bull / base / bear intrinsic value estimates and margin of safety.
 *
 * @param {Record<number, object>} data  - Year-keyed financial rows.
 * @param {number[]}               years - Descending-sorted year list.
 * @param {{ currentPrice: number, trailingPE: number, trailingEps: number,
 *           marketCap: number }} info   - Current price/market metadata.
 * @returns {object}
 */
export function computeValuation(data, years, info) {
  const currentPrice = info.currentPrice;
  if (!currentPrice || !years.length) return {};

  const latest = data[years[0]];
  const ni = latest?.net_income;
  const rev = latest?.revenue;
  if (!ni || ni <= 0 || !rev) {
    return {
      bull: { price: 0, prob: 25, annualReturn: 0 },
      base: { price: 0, prob: 50, annualReturn: 0 },
      bear: { price: 0, prob: 25, annualReturn: 0 },
      currentPrice: Math.round(currentPrice * 100) / 100,
      marginOfSafety: 0, buyBelow: 0,
    };
  }

  const niVals = years.map(y => data[y]?.net_income).filter(v => v != null);
  let cagr = 0.05;
  if (niVals.length >= 2 && niVals[niVals.length - 1] > 0) {
    cagr = (niVals[0] / niVals[niVals.length - 1]) ** (1 / (niVals.length - 1)) - 1;
  }

  const trailingPE = info.trailingPE || 15;
  let eps = info.trailingEps;
  if (!eps && info.marketCap && currentPrice) {
    const shares = info.marketCap / currentPrice;
    eps = (ni * 1e6) / shares;
  }
  if (!eps || eps <= 0) eps = currentPrice / trailingPE;

  const bullG = Math.max(cagr * 1.3, cagr + 0.03);
  const baseG = cagr;
  const bearG = Math.min(cagr * 0.5, cagr - 0.03);

  const bullEps = eps * (1 + bullG) ** 5;
  const baseEps = eps * (1 + baseG) ** 5;
  const bearEps = eps * (1 + bearG) ** 5;

  const bullPE = Math.min(trailingPE * 1.2, 35);
  const basePE = trailingPE * 0.9;
  const bearPE = Math.max(trailingPE * 0.6, 10);

  const bullPrice = Math.round(bullEps * bullPE);
  const basePrice = Math.round(baseEps * basePE);
  const bearPrice = Math.round(bearEps * bearPE);

  const annRet = (future) =>
    currentPrice > 0 ? Math.round(((future / currentPrice) ** 0.2 - 1) * 1000) / 10 : 0;
  const mos = basePrice > 0
    ? Math.round(((basePrice - currentPrice) / basePrice) * 1000) / 10
    : 0;

  return {
    bull:           { price: bullPrice, prob: 25, annualReturn: annRet(bullPrice) },
    base:           { price: basePrice, prob: 50, annualReturn: annRet(basePrice) },
    bear:           { price: bearPrice, prob: 25, annualReturn: annRet(bearPrice) },
    intrinsicRange: [bearPrice, bullPrice],
    currentPrice:   Math.round(currentPrice * 100) / 100,
    marginOfSafety: mos,
    buyBelow:       Math.round(basePrice * 0.75),
  };
}

// ── Tier Evaluation ──

/**
 * Evaluates pass / review / fail status for tiers 1-5.
 *
 * @param {Record<number, object>} data       - Year-keyed financial rows.
 * @param {number[]}               years      - Descending-sorted year list.
 * @param {object}                 scorecard  - Output of computeScorecard().
 * @param {object}                 valuation  - Output of computeValuation().
 * @returns {{ tier1: string, tier2: string, tier3: string, tier4: string, tier5: string }}
 */
export function computeTiers(data, years, scorecard, valuation) {
  const tiers = {};
  const latest = years.length ? (data[years[0]] || {}) : {};

  tiers.tier1 = latest.revenue && latest.revenue > 0 ? 'pass' : 'fail';

  const niVals = years.map(y => data[y]?.net_income).filter(v => v != null);
  if (niVals.length >= 2) {
    const hasDoubled = niVals[niVals.length - 1] > 0 && niVals[0] >= niVals[niVals.length - 1] * 2;
    let maxDecline = 0;
    for (let i = 1; i < niVals.length; i++) {
      if (niVals[i] > 0) {
        const decline = (niVals[i] - niVals[i - 1]) / niVals[i];
        maxDecline = Math.max(maxDecline, decline);
      }
    }
    tiers.tier2 = hasDoubled && maxDecline <= 0.05
      ? 'pass'
      : maxDecline <= 0.15
        ? 'review'
        : 'fail';
  } else {
    tiers.tier2 = 'review';
  }

  const acid = latest.cash && latest.current_liabilities > 0
    ? latest.cash / latest.current_liabilities
    : null;
  const de = latest.equity && latest.equity > 0
    ? (latest.lt_debt || 0) / latest.equity
    : null;
  if (acid != null && de != null) {
    tiers.tier3 = acid >= 1.0 && de <= 0.5
      ? 'pass'
      : acid >= 0.5 && de <= 1.5
        ? 'review'
        : 'fail';
  } else {
    tiers.tier3 = 'review';
  }

  const avgScore = Object.values(scorecard).reduce((s, v) => s + v, 0) / 4;
  tiers.tier4 = avgScore >= 70 ? 'pass' : avgScore >= 50 ? 'review' : 'fail';

  const mos = valuation.marginOfSafety || 0;
  tiers.tier5 = mos >= 20 ? 'pass' : mos >= 5 ? 'review' : 'fail';

  return tiers;
}

// ── Tier 2 Detailed Evaluation ──

/**
 * Evaluates whether earnings have doubled and calculates the maximum YoY
 * decline fraction for Tier 2 display in the calculated metrics panel.
 *
 * @param {{ years: number[], data: Record<number, object> }} analysisData
 * @returns {{ earningsDoubled: boolean, earningsStable: boolean, maxDecline: number }}
 */
export function evaluateTier2(analysisData) {
  const years = analysisData.years || [];
  const data = analysisData.data || {};
  if (years.length < 2) return { earningsDoubled: false, earningsStable: true, maxDecline: 0 };

  const firstYear = data[years[years.length - 1]];
  const lastYear  = data[years[0]];
  const earningsDoubled = firstYear && lastYear
    ? lastYear.net_income >= firstYear.net_income * 2
    : false;

  let maxDecline = 0;
  for (let i = 1; i < years.length; i++) {
    const prev = data[years[i]];
    const curr = data[years[i - 1]];
    if (prev?.net_income > 0 && curr?.net_income != null) {
      const decline = (prev.net_income - curr.net_income) / prev.net_income;
      if (decline > maxDecline) maxDecline = decline;
    }
  }
  const earningsStable = maxDecline <= 0.05;

  return { earningsDoubled, earningsStable, maxDecline };
}

// ── Valuation Recalculation from Slider Params ──

/**
 * Adjusts a previously-computed valuation using Bayesian confidence slider
 * parameters and returns an updated valuation object suitable for display.
 *
 * @param {object} baseVal  - Output of computeValuation().
 * @param {{ earningsGrowth: number, moatDurability: number,
 *           disruptionRisk: number, multipleExpansion: number }} sliders
 * @returns {object}        - Adjusted valuation (same shape as computeValuation output).
 */
export function recalculateValuationFromSliders(baseVal, sliders) {
  const growthAdj    = (sliders.earningsGrowth  ?? 8)  / 8;
  const moatAdj      = (sliders.moatDurability  ?? 70) / 70;
  const riskDiscount = 1 - ((sliders.disruptionRisk ?? 25) - 25) / 200;
  const multAdj      = 1 + (sliders.multipleExpansion ?? 0) / 10;

  const factor = growthAdj * moatAdj * riskDiscount * multAdj;

  return {
    bull: { ...baseVal.bull, price: Math.round(baseVal.bull.price * factor) },
    base: { ...baseVal.base, price: Math.round(baseVal.base.price * factor) },
    bear: { ...baseVal.bear, price: Math.round(baseVal.bear.price * factor * 0.9) },
    marginOfSafety: Math.round(
      ((baseVal.base.price * factor - baseVal.currentPrice) / (baseVal.base.price * factor)) * 100
    ),
    buyBelow:     Math.round(baseVal.base.price * factor * 0.75),
    currentPrice: baseVal.currentPrice,
  };
}

// ── Analysis Notes Generation ──

/**
 * Generates a plain-text analysis narrative from scorecard and financial data.
 *
 * @param {string}                 symbol
 * @param {string}                 name
 * @param {Record<number, object>} data
 * @param {number[]}               years
 * @param {object}                 scorecard
 * @param {{ sector?: string, industry?: string }} info
 * @returns {string}
 */
export function generateNotes(symbol, name, data, years, scorecard, info) {
  if (!years.length) return 'No financial data available for ' + symbol + '.';
  const latest = data[years[0]];
  const lines = [(name || symbol) + ' (' + symbol + ') \u2014 ' + years.length + '-year financial analysis\n'];

  const niVals = years.map(y => data[y]?.net_income).filter(v => v != null);
  if (niVals.length >= 2) {
    if (niVals[0] > niVals[niVals.length - 1]) {
      const g = niVals[niVals.length - 1] > 0
        ? ((niVals[0] / niVals[niVals.length - 1]) ** (1 / (niVals.length - 1)) - 1) * 100
        : 0;
      lines.push('Earnings CAGR: ' + g.toFixed(1) + '% over ' + niVals.length + ' years.');
    } else {
      lines.push('Earnings have declined over the analysis period.');
    }
  }

  if (latest.net_income && latest.revenue && latest.revenue > 0) {
    lines.push('Current net margin: ' + (latest.net_income / latest.revenue * 100).toFixed(1) + '%.');
  }

  if (latest.lt_debt != null && latest.equity && latest.equity > 0) {
    const de = (latest.lt_debt || 0) / latest.equity;
    if (de <= 0.3)       lines.push('Very low debt levels \u2014 strong balance sheet.');
    else if (de <= 1.0)  lines.push('Moderate leverage (D/E: ' + de.toFixed(2) + ').');
    else                 lines.push('High leverage (D/E: ' + de.toFixed(2) + ') \u2014 warrants caution.');
  }

  const avg = Object.values(scorecard).reduce((s, v) => s + v, 0) / 4;
  lines.push('\nComposite Buffett-Munger score: ' + avg.toFixed(0) + '/100.');
  if (avg >= 70)      lines.push('Meets quality threshold for further analysis.');
  else if (avg >= 50) lines.push('Mixed quality signals \u2014 requires deeper investigation.');
  else                lines.push('Below quality threshold \u2014 significant concerns.');

  if (info.sector) {
    lines.push('\nSector: ' + info.sector + '. Industry: ' + (info.industry || '') + '.');
  }

  return lines.join('\n');
}
