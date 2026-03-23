// ── cloud-costs-logic.js ──
// Pure logic extracted from the cloud-costs page IIFE.
// No DOM access — all functions are side-effect free and testable.

// ── Constants ──

export const BUDGET_MAP = {
  'Styln':         300,
  'Spin & Dine':   100,
  'QuantRE/Axiom': 25,
};

export const APP_COLORS = {
  'Styln':         '#3b82f6',
  'Spin & Dine':   '#22c55e',
  'QuantRE/Axiom': '#a855f7',
  'Admin':         '#64748b',
};

const MONTH_NAMES = [
  'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
];

// ── computeScorecardValues ──────────────────────────────────────────────────
// Returns { styln, spinDine, quantRe, total } as plain numbers.
// Accepts null/missing totals gracefully.

export function computeScorecardValues(totals) {
  if (!totals) {
    return { styln: 0, spinDine: 0, quantRe: 0, total: 0 };
  }

  const stylnVal   = _appValue(totals['Styln']);
  const sdVal      = _appValue(totals['Spin & Dine']);
  const qrVal      = _appValue(totals['QuantRE/Axiom']);

  // Use explicit Total field when present and non-zero, otherwise sum the three apps.
  let totalVal = typeof totals['Total'] === 'object'
    ? totals['Total']?.net_cost
    : totals['Total'];

  if (totalVal == null || totalVal === 0) {
    totalVal = stylnVal + sdVal + qrVal;
  }

  return {
    styln:    stylnVal,
    spinDine: sdVal,
    quantRe:  qrVal,
    total:    totalVal,
  };
}

function _appValue(field) {
  if (field == null) return 0;
  if (typeof field === 'object') return field?.net_cost ?? 0;
  return field || 0;
}

// ── computeNetCost ──────────────────────────────────────────────────────────
// Returns the net cost for a single breakdown row.
// Priority: netCost → net_cost → cost + credits → 0

export function computeNetCost(row) {
  if (!row) return 0;
  if (row.netCost  != null) return row.netCost;
  if (row.net_cost != null) return row.net_cost;
  const cost    = row.cost    || 0;
  const credits = row.credits || 0;
  return cost + credits;
}

// ── buildBreakdownDatasets ──────────────────────────────────────────────────
// Groups breakdown rows by service, sorts by total cost descending,
// caps at top 10, and returns { services, datasets } for Chart.js.
//
// datasets: [{ label: appName, data: number[], backgroundColor: string }]

export function buildBreakdownDatasets(breakdown) {
  if (!breakdown || breakdown.length === 0) {
    return { services: [], datasets: [] };
  }

  // Group rows by service, accumulate cost per app.
  const serviceMap = {};
  for (const row of breakdown) {
    const svc = row.service || 'Unknown';
    if (!serviceMap[svc]) serviceMap[svc] = {};
    serviceMap[svc][row.app] = (serviceMap[svc][row.app] || 0) + (row.cost || 0);
  }

  // Sort by total cost descending, take top 10.
  const sorted = Object.entries(serviceMap)
    .map(([svc, apps]) => ({
      svc,
      total: Object.values(apps).reduce((a, b) => a + b, 0),
      apps,
    }))
    .sort((a, b) => b.total - a.total)
    .slice(0, 10);

  const services = sorted.map(s => s.svc);
  const apps = [...new Set(breakdown.map(r => r.app))].filter(Boolean);

  const datasets = apps.map(app => ({
    label: app,
    data: sorted.map(s => s.apps[app] || 0),
    backgroundColor: APP_COLORS[app] || '#94a3b8',
  }));

  return { services, datasets };
}

// ── normalizeTrendData ──────────────────────────────────────────────────────
// Accepts two possible data shapes and returns a uniform
// [{ month, app, cost }] array with Admin rows filtered out.
//
// Jarvis shape: [{ month: "2025-10", Styln: 200, "Spin & Dine": 40, ... }]
// AXIOM shape:  [{ month: "202510",  app: "Styln", cost: 200 }]

const _TREND_APPS = Object.keys(APP_COLORS).filter(a => a !== 'Admin');

export function normalizeTrendData(trend) {
  if (!trend || trend.length === 0) return [];

  if (trend[0] && trend[0].app !== undefined) {
    // AXIOM row-per-app shape — filter out Admin and null app rows.
    return trend.filter(r => r.app && r.app !== 'Admin');
  }

  // Jarvis per-column shape — expand to row-per-app.
  const rows = [];
  for (const row of trend) {
    for (const app of _TREND_APPS) {
      if (row[app] != null) {
        rows.push({ month: row.month, app, cost: row[app] });
      }
    }
  }
  return rows;
}

// ── fmtLabel ────────────────────────────────────────────────────────────────
// Formats a YYYYMM or YYYY-MM month string into "Mon 'YY".
// e.g. "2025-10" → "Oct '25",  "202510" → "Oct '25"

export function fmtLabel(m) {
  const s = String(m).replace('-', '');
  if (s.length === 6) {
    const yr = s.slice(2, 4);
    const mo = parseInt(s.slice(4, 6), 10) - 1;
    return `${MONTH_NAMES[mo]} '${yr}`;
  }
  return m;
}
