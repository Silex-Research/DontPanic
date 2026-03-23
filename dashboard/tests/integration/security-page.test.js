// Integration tests for the Security page module.
//
// Strategy: inject the page's static HTML template into the DOM, then call
// the same rendering helpers the page IIFE uses (backed by lib/security-logic.js).
// Asserts on stats cards, decision log entries, filter tab behaviour, and
// the empty/zero-state rendering paths.
//
// Avoids dynamic import of the IIFE-wrapped security.js to sidestep module
// caching issues; all logic under test lives in lib/security-logic.js.

import { describe, it, expect, beforeEach } from 'vitest';
import {
  ACTION_COLORS,
  ACTION_LABELS,
  SEVERITY_COLORS,
  HOOK_DEFS,
  aggregateStats,
  aggregatePerAgent,
  matchHookDecisions,
} from '../../lib/security-logic.js';
import { setupDOM, createMockState, setupChartMock } from '../helpers/setup.js';

// ── HTML template (mirrors security.js buildTemplate()) ──────────────────────

function buildTemplate() {
  return `
    <div class="sec-layout">
      <section class="panel sec-stats-panel">
        <h2>Security Overview</h2>
        <div class="sec-stats-grid" id="sec-stats-grid"></div>
      </section>
      <section class="panel sec-hooks-panel">
        <h2>Hook Activity</h2>
        <div class="sec-hooks-list" id="sec-hooks-list"></div>
      </section>
      <section class="panel sec-decisions-panel">
        <h2>Decision Audit Log</h2>
        <div class="sec-decision-tabs" id="sec-decision-tabs">
          <button class="sec-tab active" data-filter="all">All</button>
          <button class="sec-tab" data-filter="block">Blocks</button>
          <button class="sec-tab" data-filter="require_approval">Approvals</button>
          <button class="sec-tab" data-filter="log">Logged</button>
          <button class="sec-tab" data-filter="allow">Allowed</button>
        </div>
        <div class="sec-decision-list" id="sec-decision-list"></div>
      </section>
      <section class="panel sec-agent-overview-panel">
        <h2>Agent Security Profile</h2>
        <div class="sec-agent-overview-grid">
          <div class="sec-agent-table" id="sec-agent-table"></div>
          <div class="sec-agent-chart-container">
            <canvas id="sec-agent-chart"></canvas>
          </div>
        </div>
      </section>
    </div>
  `;
}

// ── Rendering helpers mirroring the page IIFE ─────────────────────────────────

function esc(str) {
  if (str == null) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function emptyState(msg) {
  return `<div class="empty-state"><div class="empty-icon">&#9675;</div><div class="empty-text">${esc(msg)}</div></div>`;
}

function renderStats(el, decisions) {
  const grid = el.querySelector('#sec-stats-grid');
  if (!grid) return;
  const { total, blocks, approvals, logged } = aggregateStats(decisions);
  grid.innerHTML = `
    <div class="sec-stat-card">
      <div class="sec-stat-icon sec-stat-icon--accent">&#8801;</div>
      <div class="sec-stat-content">
        <div class="sec-stat-value">${total}</div>
        <div class="sec-stat-label">Total Decisions</div>
      </div>
    </div>
    <div class="sec-stat-card">
      <div class="sec-stat-icon sec-stat-icon--red">&#10006;</div>
      <div class="sec-stat-content">
        <div class="sec-stat-value">${blocks}</div>
        <div class="sec-stat-label">Blocked</div>
      </div>
    </div>
    <div class="sec-stat-card">
      <div class="sec-stat-icon sec-stat-icon--yellow">&#9873;</div>
      <div class="sec-stat-content">
        <div class="sec-stat-value">${approvals}</div>
        <div class="sec-stat-label">Approvals Req.</div>
      </div>
    </div>
    <div class="sec-stat-card">
      <div class="sec-stat-icon sec-stat-icon--accent">&#9998;</div>
      <div class="sec-stat-content">
        <div class="sec-stat-value">${logged}</div>
        <div class="sec-stat-label">Logged</div>
      </div>
    </div>
  `;
}

const jarvis = { timeAgo: ts => ts ? 'just now' : '--' };

function renderDecisionLog(el, decisions, activeFilter = 'all') {
  const list = el.querySelector('#sec-decision-list');
  if (!list) return;

  let filtered = activeFilter === 'all'
    ? decisions
    : decisions.filter(d => d.action === activeFilter);

  // Update tab counts
  const tabs = el.querySelector('#sec-decision-tabs');
  if (tabs) {
    const counts = {
      all:              decisions.length,
      block:            decisions.filter(d => d.action === 'block').length,
      require_approval: decisions.filter(d => d.action === 'require_approval').length,
      log:              decisions.filter(d => d.action === 'log').length,
      allow:            decisions.filter(d => d.action === 'allow').length,
    };
    tabs.querySelectorAll('.sec-tab').forEach(tab => {
      const filter = tab.dataset.filter;
      const count  = counts[filter] ?? 0;
      const baseLabel = ACTION_LABELS[filter] || (filter === 'all' ? 'All' : esc(filter));
      tab.innerHTML = `${baseLabel} <span class="sec-tab-count">${count}</span>`;
    });
  }

  if (!filtered.length) {
    list.innerHTML = emptyState('No decisions recorded');
    return;
  }

  const sorted = [...filtered].sort((a, b) => {
    const ta = a.timestamp ? new Date(a.timestamp).getTime() : 0;
    const tb = b.timestamp ? new Date(b.timestamp).getTime() : 0;
    return tb - ta;
  });

  list.innerHTML = sorted.map(d => {
    const actionColor = ACTION_COLORS[d.action] || 'accent';
    const actionLabel = ACTION_LABELS[d.action] || esc(d.action || 'UNKNOWN');
    const sevColor    = SEVERITY_COLORS[d.severity] || 'accent';
    return `
      <div class="sec-decision-item">
        <span class="sec-action-badge sec-action-badge--${actionColor}">${actionLabel}</span>
        <div class="sec-decision-body">
          <div class="sec-decision-reason">${esc(d.details || 'No details provided')}</div>
          <div class="sec-decision-meta">
            <span>&#8226; ${esc(d.agent || 'unknown')}</span>
            <span>&#8226; ${esc(d.category || '--')}</span>
            <span>&#8226; ${jarvis.timeAgo(d.timestamp)}</span>
            ${d.severity ? `<span class="sec-sev-chip sec-sev-chip--${sevColor}">${esc(d.severity)}</span>` : ''}
          </div>
        </div>
      </div>
    `;
  }).join('');
}

// ── Test setup ────────────────────────────────────────────────────────────────

let pageEl;
let state;

beforeEach(() => {
  setupDOM();
  setupChartMock();

  state = createMockState();

  const container = document.getElementById('page-container');
  pageEl = document.createElement('div');
  pageEl.id = 'page-security';
  pageEl.className = 'page-view active';
  container.appendChild(pageEl);

  pageEl.innerHTML = buildTemplate();
});

// ── Security stats ────────────────────────────────────────────────────────────

describe('security: stats cards', () => {
  it('renders exactly 4 stat cards', () => {
    renderStats(pageEl, state.security);
    const cards = pageEl.querySelectorAll('.sec-stat-card');
    expect(cards.length).toBe(4);
  });

  it('Total Decisions stat displays the correct count', () => {
    renderStats(pageEl, state.security);
    const values = [...pageEl.querySelectorAll('.sec-stat-value')];
    const totalCard = values.find(el =>
      el.nextElementSibling?.textContent.includes('Total')
    );
    expect(totalCard).not.toBeUndefined();
    expect(Number(totalCard.textContent)).toBe(state.security.length);
  });

  it('Blocked stat displays correct block count', () => {
    renderStats(pageEl, state.security);
    const { blocks } = aggregateStats(state.security);
    const values = [...pageEl.querySelectorAll('.sec-stat-value')].map(el => el.textContent);
    expect(values).toContain(String(blocks));
  });

  it('Approvals Req. stat shows the correct count', () => {
    renderStats(pageEl, state.security);
    const { approvals } = aggregateStats(state.security);
    const values = [...pageEl.querySelectorAll('.sec-stat-value')].map(el => el.textContent);
    expect(values).toContain(String(approvals));
  });

  it('Logged stat shows the correct count', () => {
    renderStats(pageEl, state.security);
    const { logged } = aggregateStats(state.security);
    const values = [...pageEl.querySelectorAll('.sec-stat-value')].map(el => el.textContent);
    expect(values).toContain(String(logged));
  });

  it('all stats show 0 when security array is empty', () => {
    renderStats(pageEl, []);
    const values = [...pageEl.querySelectorAll('.sec-stat-value')].map(el => Number(el.textContent));
    expect(values.every(v => v === 0)).toBe(true);
  });
});

// ── Decision audit log ────────────────────────────────────────────────────────

describe('security: decision audit log', () => {
  it('renders one decision item per entry in state.security', () => {
    renderDecisionLog(pageEl, state.security);
    const items = pageEl.querySelectorAll('.sec-decision-item');
    expect(items.length).toBe(state.security.length);
  });

  it('block decision item has the correct action badge label', () => {
    renderDecisionLog(pageEl, state.security);
    const badges = [...pageEl.querySelectorAll('.sec-action-badge')].map(el => el.textContent.trim());
    expect(badges).toContain('BLOCK');
  });

  it('log decision item has the correct action badge label', () => {
    renderDecisionLog(pageEl, state.security);
    const badges = [...pageEl.querySelectorAll('.sec-action-badge')].map(el => el.textContent.trim());
    expect(badges).toContain('LOG');
  });

  it('decision detail text is rendered inside each item', () => {
    renderDecisionLog(pageEl, state.security);
    const reasons = [...pageEl.querySelectorAll('.sec-decision-reason')].map(el => el.textContent);
    expect(reasons.some(t => t.includes('Blocked rm -rf /'))).toBe(true);
  });

  it('shows empty state when no decisions are present', () => {
    renderDecisionLog(pageEl, []);
    const empty = pageEl.querySelector('.empty-state');
    expect(empty).not.toBeNull();
    expect(empty.textContent).toContain('No decisions recorded');
  });
});

// ── Filter tabs ───────────────────────────────────────────────────────────────

describe('security: filter tabs', () => {
  it('All tab shows all decisions by default', () => {
    renderDecisionLog(pageEl, state.security, 'all');
    const items = pageEl.querySelectorAll('.sec-decision-item');
    expect(items.length).toBe(state.security.length);
  });

  it('Blocks tab filters to show only block-action decisions', () => {
    renderDecisionLog(pageEl, state.security, 'block');
    const items = pageEl.querySelectorAll('.sec-decision-item');
    const blockCount = state.security.filter(d => d.action === 'block').length;
    expect(items.length).toBe(blockCount);
  });

  it('Approvals tab filters to show only require_approval decisions', () => {
    renderDecisionLog(pageEl, state.security, 'require_approval');
    const items = pageEl.querySelectorAll('.sec-decision-item');
    const approvalCount = state.security.filter(d => d.action === 'require_approval').length;
    expect(items.length).toBe(approvalCount);
  });

  it('Logged tab filters to show only log decisions', () => {
    renderDecisionLog(pageEl, state.security, 'log');
    const items = pageEl.querySelectorAll('.sec-decision-item');
    const logCount = state.security.filter(d => d.action === 'log').length;
    expect(items.length).toBe(logCount);
  });

  it('tab count badges update to show per-action totals', () => {
    renderDecisionLog(pageEl, state.security);
    const blockTab = pageEl.querySelector('.sec-tab[data-filter="block"]');
    const countSpan = blockTab.querySelector('.sec-tab-count');
    const blockCount = state.security.filter(d => d.action === 'block').length;
    expect(Number(countSpan.textContent)).toBe(blockCount);
  });

  it('filtering on an action with no matches shows empty state', () => {
    // No 'allow' decisions in mock state
    renderDecisionLog(pageEl, state.security, 'allow');
    const empty = pageEl.querySelector('.empty-state');
    expect(empty).not.toBeNull();
  });
});

// ── aggregateStats (lib function) — boundary cases ───────────────────────────

describe('security: aggregateStats lib function', () => {
  it('returns zero counts for an empty decisions array', () => {
    const stats = aggregateStats([]);
    expect(stats.total).toBe(0);
    expect(stats.blocks).toBe(0);
    expect(stats.approvals).toBe(0);
    expect(stats.logged).toBe(0);
  });

  it('counts correctly across multiple action types', () => {
    const stats = aggregateStats(state.security);
    expect(stats.total).toBe(3);
    expect(stats.blocks).toBe(1);
    expect(stats.approvals).toBe(1);
    expect(stats.logged).toBe(1);
  });
});
