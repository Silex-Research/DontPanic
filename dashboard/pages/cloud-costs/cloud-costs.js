// ── Cloud Costs Page Module ──
// Renders GCP billing data from state/costs.json.
// No Firebase/Cloud Function calls — data is written by an external bq CLI
// cron job directly to state/costs.json, which core.js loads at startup.
//
// Pure logic lives in lib/cloud-costs-logic.js (imported below).
import {
  computeScorecardValues,
  computeNetCost,
  buildBreakdownDatasets,
  normalizeTrendData,
  fmtLabel,
  BUDGET_MAP,
  APP_COLORS,
} from '../../lib/cloud-costs-logic.js';

// Inject page stylesheet once
(function injectStyles() {
  const id = 'cloud-costs-css';
  if (document.getElementById(id)) return;
  const link = document.createElement('link');
  link.id = id;
  link.rel = 'stylesheet';
  link.href = 'pages/cloud-costs/cloud-costs.css';
  document.head.appendChild(link);
})();

// ── Local constants ──
// (BUDGET_MAP, APP_COLORS imported from lib/cloud-costs-logic.js above)

const MONTH_NAMES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                     'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

// ── Module state ──

let breakdownChart = null;
let trendChart = null;

// ── HTML Template ──

function buildTemplate() {
  return `
<div class="cost-layout">

  <!-- Scorecards -->
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

  <!-- Charts row -->
  <div class="cost-charts-row">
    <div class="panel cost-breakdown-panel">
      <div class="cost-panel-header">
        <h2>Cost by Service</h2>
      </div>
      <div class="cost-chart-container">
        <canvas id="cc-breakdown-chart"></canvas>
      </div>
    </div>
    <div class="panel cost-trend-panel">
      <div class="cost-panel-header">
        <h2>Monthly Trend</h2>
      </div>
      <div class="cost-chart-container">
        <canvas id="cc-trend-chart"></canvas>
      </div>
    </div>
  </div>

  <!-- Detail table -->
  <div class="panel cost-table-panel">
    <div class="cost-panel-header">
      <h2>Cost Breakdown</h2>
    </div>
    <div class="cost-table-scroll">
      <table class="cost-table">
        <thead>
          <tr>
            <th>App</th>
            <th>Project</th>
            <th>Service</th>
            <th>Cost</th>
            <th>Credits</th>
            <th>Net Cost</th>
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

// ── Rendering helpers ──

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

// ── Scorecards ──

function renderScorecards(totals) {
  if (!totals) return;

  const { styln: stylnVal, spinDine: sdVal, quantRe: qrVal, total: totalVal } =
    computeScorecardValues(totals);

  const el = (id) => document.getElementById(id);
  if (el('cc-styln'))    el('cc-styln').textContent    = fmt(stylnVal);
  if (el('cc-spindine')) el('cc-spindine').textContent = fmt(sdVal);
  if (el('cc-quantre'))  el('cc-quantre').textContent  = fmt(qrVal);
  if (el('cc-total'))    el('cc-total').textContent    = fmt(totalVal);

  // Budget threshold coloring
  const appValues = {
    'Styln':         stylnVal,
    'Spin & Dine':   sdVal,
    'QuantRE/Axiom': qrVal,
  };

  for (const [app, budget] of Object.entries(BUDGET_MAP)) {
    const net = appValues[app] || 0;
    const pct = budget > 0 ? net / budget : 0;
    const card = document.querySelector(`.cost-card[data-app="${CSS.escape(app)}"]`);
    if (!card) continue;
    card.classList.remove('cost-card-warn', 'cost-card-danger');
    if (pct > 0.9) {
      card.classList.add('cost-card-danger');
    } else if (pct > 0.7) {
      card.classList.add('cost-card-warn');
    }
  }
}

// ── Breakdown chart (horizontal stacked bar by service) ──

function renderBreakdownChart(breakdown) {
  if (breakdownChart) {
    breakdownChart.destroy();
    breakdownChart = null;
  }

  const canvas = document.getElementById('cc-breakdown-chart');
  if (!canvas) return;

  if (!breakdown || breakdown.length === 0) {
    renderChartEmpty(canvas, 'No breakdown data');
    return;
  }

  const { services: svcList, datasets } = buildBreakdownDatasets(breakdown);
  const labels = svcList;

  breakdownChart = new Chart(canvas, {
    type: 'bar',
    data: { labels, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      indexAxis: 'y',
      plugins: {
        legend: {
          position: 'top',
          labels: { color: '#94a3b8', font: { size: 11 } },
        },
        tooltip: {
          callbacks: {
            label: (ctx) => `${ctx.dataset.label}: $${ctx.raw.toFixed(2)}`,
          },
        },
      },
      scales: {
        x: {
          stacked: true,
          ticks: {
            color: '#64748b',
            callback: (v) => `$${v}`,
          },
          grid: { color: 'rgba(42,58,78,0.3)' },
        },
        y: {
          stacked: true,
          ticks: {
            color: '#94a3b8',
            font: { size: 11 },
          },
          grid: { display: false },
        },
      },
    },
  });
}

// ── Trend chart (line, 6-month rolling) ──

function renderTrendChart(trend) {
  if (trendChart) {
    trendChart.destroy();
    trendChart = null;
  }

  const canvas = document.getElementById('cc-trend-chart');
  if (!canvas) return;

  if (!trend || trend.length === 0) {
    renderChartEmpty(canvas, 'No trend data');
    return;
  }

  // Normalise: accept Jarvis per-column shape or AXIOM row-per-app shape.
  // See lib/cloud-costs-logic.js for details.
  const normalised = normalizeTrendData(trend);

  // Collect and sort unique months
  const months = [...new Set(normalised.map(r => r.month))].sort();

  const apps = [...new Set(normalised.map(r => r.app))];

  const datasets = apps.map(app => ({
    label: app,
    data: months.map(m => {
      const row = normalised.find(r => r.month === m && r.app === app);
      return row ? row.cost : 0;
    }),
    borderColor: APP_COLORS[app] || '#94a3b8',
    backgroundColor: (APP_COLORS[app] || '#94a3b8') + '33',
    fill: true,
    tension: 0.3,
    pointRadius: 3,
    pointHoverRadius: 5,
  }));

  trendChart = new Chart(canvas, {
    type: 'line',
    data: { labels: months.map(fmtLabel), datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          position: 'top',
          labels: { color: '#94a3b8', font: { size: 11 } },
        },
        tooltip: {
          callbacks: {
            label: (ctx) => `${ctx.dataset.label}: $${ctx.raw.toFixed(2)}`,
          },
        },
      },
      scales: {
        x: {
          ticks: { color: '#64748b' },
          grid: { color: 'rgba(42,58,78,0.3)' },
        },
        y: {
          ticks: {
            color: '#64748b',
            callback: (v) => `$${v}`,
          },
          grid: { color: 'rgba(42,58,78,0.3)' },
          beginAtZero: true,
        },
      },
    },
  });
}

// ── Detail table ──

function renderTable(breakdown) {
  const tbody = document.getElementById('cc-detail-body');
  if (!tbody) return;

  if (!breakdown || breakdown.length === 0) {
    tbody.innerHTML = '<tr><td colspan="6" class="cost-empty">No data available</td></tr>';
    return;
  }

  const sorted = [...breakdown].sort((a, b) => (b.cost || 0) - (a.cost || 0));

  tbody.innerHTML = sorted.map(row => {
    const cost    = row.cost    || 0;
    const credits = row.credits || 0;
    const netCost = computeNetCost(row);

    // Credits are typically stored as negative numbers (discount).
    // Display as "-$X.XX" when negative, "$X.XX" when positive.
    const creditsDisplay = credits < 0
      ? `<span class="cost-credit-positive">-$${Math.abs(credits).toFixed(2)}</span>`
      : `$${credits.toFixed(2)}`;

    return `
      <tr>
        <td>${esc(row.app)}</td>
        <td>${esc(row.project)}</td>
        <td>${esc(row.service)}</td>
        <td>$${cost.toFixed(2)}</td>
        <td>${creditsDisplay}</td>
        <td>$${netCost.toFixed(2)}</td>
      </tr>`;
  }).join('');
}

// ── Generated timestamp ──

function renderTimestamp(generated) {
  const el = document.getElementById('cc-generated');
  if (!el) return;
  if (!generated) {
    el.textContent = 'No data loaded';
    return;
  }
  const d = new Date(generated);
  el.textContent = `Updated: ${d.toLocaleString()}`;
}

// ── Placeholder for empty charts ──

function renderChartEmpty(canvas, message) {
  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = '#64748b';
  ctx.font = '13px monospace';
  ctx.textAlign = 'center';
  ctx.fillText(message, canvas.width / 2, canvas.height / 2);
}

// ── Full dashboard render ──

function renderDashboard(costs) {
  if (!costs) {
    renderError('State not loaded — run the bq cost sync script to populate state/costs.json');
    return;
  }

  renderScorecards(costs.totals || {});
  renderBreakdownChart(costs.breakdown || []);
  renderTrendChart(costs.trend || []);
  renderTable(costs.breakdown || []);
  renderTimestamp(costs.generated || costs.generatedAt || null);
}

function renderError(msg) {
  const tbody = document.getElementById('cc-detail-body');
  if (tbody) {
    tbody.innerHTML = `<tr><td colspan="6" class="cost-empty">Error: ${esc(msg)}</td></tr>`;
  }
}

// ── Teardown ──

function destroyCharts() {
  if (breakdownChart) { breakdownChart.destroy(); breakdownChart = null; }
  if (trendChart)     { trendChart.destroy();     trendChart = null; }
}

// ── Page Registration ──

Jarvis.registerPage({
  id: 'cloud-costs',
  label: 'Cloud Costs',

  init(state) {
    const el = Jarvis.getPageEl('cloud-costs');
    if (!el) return;
    el.innerHTML = buildTemplate();
  },

  onActivate(state) {
    renderDashboard(state.costs);
  },

  onDeactivate() {
    destroyCharts();
  },
});
