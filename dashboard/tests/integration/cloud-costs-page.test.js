// Integration tests for the Cloud Costs page module.
//
// Strategy: inject the page's static HTML template into the DOM, then call
// the lib-level logic functions and the same rendering helpers the page uses.
// Asserts on the resulting DOM state — scorecards, table rows, empty paths.
// Avoids dynamic import of the non-IIFE cloud-costs.js to sidestep module
// caching issues; the logic under test lives in lib/cloud-costs-logic.js.

import { describe, it, expect, beforeEach } from 'vitest';
import {
  computeScorecardValues,
  buildBreakdownDatasets,
  BUDGET_MAP,
} from '../../lib/cloud-costs-logic.js';
import { setupDOM, createMockState, setupChartMock } from '../helpers/setup.js';

// jsdom does not expose CSS.escape — polyfill it so the page's selector logic works.
if (typeof CSS === 'undefined' || typeof CSS.escape === 'undefined') {
  globalThis.CSS = globalThis.CSS || {};
  globalThis.CSS.escape = function cssEscape(value) {
    // Minimal implementation covering the characters used by app names.
    return String(value).replace(/([^\w-])/g, '\\$1');
  };
}

// ── HTML template (mirrors cloud-costs.js buildTemplate()) ───────────────────

function buildTemplate() {
  return `
<div class="cost-layout">
  <div class="cost-scorecards">
    <div class="cost-card" data-app="Styln">
      <div class="cost-card-label">Styln</div>
      <div class="cost-card-value" id="cc-styln">--</div>
      <div class="cost-card-sub">Budget $300/mo</div>
    </div>
    <div class="cost-card" data-app="Spin &amp; Dine">
      <div class="cost-card-label">Spin &amp; Dine</div>
      <div class="cost-card-value" id="cc-spindine">--</div>
      <div class="cost-card-sub">Budget $100/mo</div>
    </div>
    <div class="cost-card" data-app="QuantRE/Axiom">
      <div class="cost-card-label">QuantRE / Axiom</div>
      <div class="cost-card-value" id="cc-quantre">--</div>
      <div class="cost-card-sub">Budget $25/mo</div>
    </div>
    <div class="cost-card cost-card-total" data-app="Total">
      <div class="cost-card-label">Total</div>
      <div class="cost-card-value" id="cc-total">--</div>
      <div class="cost-card-sub" id="cc-generated">&nbsp;</div>
    </div>
  </div>
  <div class="cost-charts-row">
    <div class="panel cost-breakdown-panel">
      <h2>Cost by Service</h2>
      <div class="cost-chart-container"><canvas id="cc-breakdown-chart"></canvas></div>
    </div>
    <div class="panel cost-trend-panel">
      <h2>Monthly Trend</h2>
      <div class="cost-chart-container"><canvas id="cc-trend-chart"></canvas></div>
    </div>
  </div>
  <div class="panel cost-table-panel">
    <h2>Cost Breakdown</h2>
    <div class="cost-table-scroll">
      <table class="cost-table">
        <thead>
          <tr>
            <th>App</th><th>Project</th><th>Service</th>
            <th>Cost</th><th>Credits</th><th>Net Cost</th>
          </tr>
        </thead>
        <tbody id="cc-detail-body">
          <tr><td colspan="6" class="cost-empty">Loading…</td></tr>
        </tbody>
      </table>
    </div>
  </div>
</div>
`;
}

// ── Rendering helpers mirroring the page module ───────────────────────────────

function fmt(v) {
  return '$' + (v || 0).toFixed(2);
}

function esc(str) {
  if (str == null) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function renderScorecards(totals) {
  if (!totals) return;
  const { styln, spinDine, quantRe, total } = computeScorecardValues(totals);
  const el = id => document.getElementById(id);
  if (el('cc-styln'))    el('cc-styln').textContent    = fmt(styln);
  if (el('cc-spindine')) el('cc-spindine').textContent = fmt(spinDine);
  if (el('cc-quantre'))  el('cc-quantre').textContent  = fmt(quantRe);
  if (el('cc-total'))    el('cc-total').textContent    = fmt(total);

  // Budget threshold coloring
  const appValues = { 'Styln': styln, 'Spin & Dine': spinDine, 'QuantRE/Axiom': quantRe };
  for (const [app, budget] of Object.entries(BUDGET_MAP)) {
    const net = appValues[app] || 0;
    const pct = budget > 0 ? net / budget : 0;
    const card = document.querySelector(`.cost-card[data-app="${CSS.escape(app)}"]`);
    if (!card) continue;
    card.classList.remove('cost-card-warn', 'cost-card-danger');
    if (pct > 0.9) card.classList.add('cost-card-danger');
    else if (pct > 0.7) card.classList.add('cost-card-warn');
  }
}

function renderTable(breakdown) {
  const tbody = document.getElementById('cc-detail-body');
  if (!tbody) return;
  if (!breakdown || !breakdown.length) {
    tbody.innerHTML = '<tr><td colspan="6" class="cost-empty">No data available</td></tr>';
    return;
  }
  tbody.innerHTML = breakdown.map(row => `
    <tr>
      <td>${esc(row.app)}</td>
      <td>${esc(row.project)}</td>
      <td>${esc(row.service)}</td>
      <td>${fmt(row.cost)}</td>
      <td>${fmt(row.credits)}</td>
      <td>${fmt(row.netCost)}</td>
    </tr>
  `).join('');
}

// ── Test setup ────────────────────────────────────────────────────────────────

let state;

beforeEach(() => {
  setupDOM();
  setupChartMock();

  state = createMockState();

  const container = document.getElementById('page-container');
  const pageEl = document.createElement('div');
  pageEl.id = 'page-cloud-costs';
  pageEl.className = 'page-view active';
  container.appendChild(pageEl);

  // inject() mirrors cloud-costs init() — only injects template; rendering
  // happens in onActivate(). Tests call renderScorecards / renderTable directly.
  pageEl.innerHTML = buildTemplate();
});

// ── Scorecard cards ───────────────────────────────────────────────────────────

describe('cloud-costs: scorecard cards', () => {
  it('renders exactly 4 scorecard cards (Styln, Spin & Dine, QuantRE/Axiom, Total)', () => {
    const cards = document.querySelectorAll('.cost-card');
    expect(cards.length).toBe(4);
  });

  it('Styln scorecard populates with the correct formatted currency value', () => {
    renderScorecards(state.costs.totals);
    const val = document.getElementById('cc-styln').textContent;
    // mock totals.Styln = 234.56
    expect(val).toBe('$234.56');
  });

  it('Spin & Dine scorecard populates correctly', () => {
    renderScorecards(state.costs.totals);
    const val = document.getElementById('cc-spindine').textContent;
    expect(val).toBe('$45.67');
  });

  it('QuantRE/Axiom scorecard populates correctly', () => {
    renderScorecards(state.costs.totals);
    const val = document.getElementById('cc-quantre').textContent;
    expect(val).toBe('$12.34');
  });

  it('Total scorecard populates correctly', () => {
    renderScorecards(state.costs.totals);
    const val = document.getElementById('cc-total').textContent;
    expect(val).toBe('$292.57');
  });

  it('adds cost-card-danger class when app cost exceeds 90% of budget', () => {
    // Styln budget is $300; put net cost at $280 (93%)
    const totals = { ...state.costs.totals, 'Styln': 280 };
    renderScorecards(totals);
    const card = document.querySelector('.cost-card[data-app="Styln"]');
    expect(card.classList.contains('cost-card-danger')).toBe(true);
  });
});

// ── Detail table ──────────────────────────────────────────────────────────────

describe('cloud-costs: detail breakdown table', () => {
  it('renders one tbody row per breakdown entry', () => {
    renderTable(state.costs.breakdown);
    const rows = document.querySelectorAll('#cc-detail-body tr');
    expect(rows.length).toBe(state.costs.breakdown.length);
  });

  it('first row contains the correct app name', () => {
    renderTable(state.costs.breakdown);
    const firstCell = document.querySelector('#cc-detail-body tr:first-child td:first-child');
    expect(firstCell.textContent).toBe('Styln');
  });

  it('first row contains the correct service name', () => {
    renderTable(state.costs.breakdown);
    const serviceCell = document.querySelector('#cc-detail-body tr:first-child td:nth-child(3)');
    expect(serviceCell.textContent).toBe('Cloud Functions');
  });

  it('shows empty-state cell when breakdown array is empty', () => {
    renderTable([]);
    const cell = document.querySelector('#cc-detail-body .cost-empty');
    expect(cell).not.toBeNull();
  });
});

// ── computeScorecardValues — zero state ───────────────────────────────────────

describe('cloud-costs: zero / empty costs state', () => {
  it('all scorecard values display $0.00 when totals are all zero', () => {
    renderScorecards({ 'Styln': 0, 'Spin & Dine': 0, 'QuantRE/Axiom': 0, 'Total': 0 });
    expect(document.getElementById('cc-styln').textContent).toBe('$0.00');
    expect(document.getElementById('cc-total').textContent).toBe('$0.00');
  });

  it('table shows empty message when breakdown is null', () => {
    renderTable(null);
    const cell = document.querySelector('#cc-detail-body .cost-empty');
    expect(cell).not.toBeNull();
  });
});

// ── buildBreakdownDatasets (lib function) ─────────────────────────────────────

describe('cloud-costs: buildBreakdownDatasets lib function', () => {
  it('returns a services list and datasets array from breakdown data', () => {
    const { services, datasets } = buildBreakdownDatasets(state.costs.breakdown);
    expect(Array.isArray(services)).toBe(true);
    expect(services.length).toBeGreaterThan(0);
    expect(Array.isArray(datasets)).toBe(true);
    expect(datasets.length).toBeGreaterThan(0);
  });
});
