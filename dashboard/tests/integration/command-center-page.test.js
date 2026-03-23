// Integration tests for the Command Center page module.
//
// Strategy: reconstruct the page's init() rendering logic using the same lib
// functions it imports, plus the same HTML template string it injects, then
// call each render helper against that DOM and assert on the output.
// This matches the approach used in core-router.test.js and avoids IIFE import
// caching issues that arise when dynamically importing page modules in tests.

import { describe, it, expect, beforeEach } from 'vitest';
import {
  getAgentMeta,
  normalizeStatus,
  computeTokenPct,
} from '../../lib/command-center-logic.js';
import { setupDOM, createMockState, setupChartMock } from '../helpers/setup.js';

// ── Helpers mirroring the page's private functions ────────────────────────────

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

function activityIcon(type) {
  const icons = { task: '&#10003;', deploy: '&#8593;', alert: '&#9888;', sync: '&#8635;', info: '&#8505;' };
  return icons[type] || icons.info;
}

// ── Page template ─────────────────────────────────────────────────────────────

function buildTemplate() {
  return `
    <div class="cc-layout">
      <div class="grid-2col">
        <div class="panel">
          <h2>Agent Status</h2>
          <div class="cc-agents-grid" id="cc-agents-grid"></div>
        </div>
        <div class="panel">
          <h2>Token Budget</h2>
          <div id="cc-token-budget"></div>
        </div>
      </div>
      <div class="grid-2col">
        <div class="panel">
          <h2>Task Queue</h2>
          <div class="task-tabs">
            <button class="tab" data-tab="pending">Pending <span class="count" id="cc-pending-count">0</span></button>
            <button class="tab active" data-tab="in_progress">In Progress <span class="count" id="cc-progress-count">0</span></button>
            <button class="tab" data-tab="completed">Done <span class="count" id="cc-done-count">0</span></button>
          </div>
          <div class="task-list" id="cc-task-list"></div>
        </div>
        <div class="panel">
          <h2>Activity Feed</h2>
          <div class="activity-feed" id="cc-activity-feed"></div>
        </div>
      </div>
      <div class="panel grid-full">
        <h2>Metrics</h2>
        <div class="charts-grid">
          <div class="chart-container"><canvas id="cc-activity-chart"></canvas></div>
          <div class="chart-container"><canvas id="cc-tokens-chart"></canvas></div>
        </div>
      </div>
    </div>
  `;
}

// ── Render helpers mirroring the page module ──────────────────────────────────

function renderAgents(el, agents, jarvis) {
  const grid = el.querySelector('#cc-agents-grid');
  if (!agents || !agents.length) {
    grid.innerHTML = emptyState('No agents reporting');
    return;
  }
  grid.innerHTML = agents.map(a => {
    const meta = getAgentMeta(a.id);
    const { pct: tokenPct, colorClass: tokenColor } = computeTokenPct(a.tokensUsed || 0, a.tokenBudget || 0);
    return `
      <div class="agent-card">
        <div class="cc-agent-header">
          <div class="cc-agent-avatar" style="--agent-color: ${meta.color}">${meta.initials}</div>
          <div class="cc-agent-info">
            <div class="agent-name">${esc(a.name || a.id)}</div>
            <div class="agent-role">${esc(a.role || 'Agent')}</div>
          </div>
          <span class="status-badge ${esc(a.status || 'offline')}">${esc(a.status || 'offline')}</span>
        </div>
        ${a.currentTask ? `<div class="agent-task">${esc(a.currentTask)}</div>` : ''}
        ${a.tokenBudget ? `
        <div class="cc-agent-tokens">
          <div class="meter-bar" style="margin-top: 8px;">
            <div class="meter-fill ${tokenColor}" style="width: ${tokenPct}%"></div>
          </div>
          <div class="cc-agent-token-label">
            <span>${jarvis.formatNumber(a.tokensUsed || 0)} tokens used</span>
            <span>${tokenPct}%</span>
          </div>
        </div>` : ''}
        ${a.lastSeen ? `<div class="cc-agent-last-seen">Last seen ${jarvis.timeAgo(a.lastSeen)}</div>` : ''}
      </div>
    `;
  }).join('');
}

function renderTokenBudget(el, agents, jarvis) {
  const container = el.querySelector('#cc-token-budget');
  const totalBudget = agents.reduce((sum, a) => sum + (a.tokenBudget || 0), 0);
  if (!totalBudget) {
    container.innerHTML = emptyState('No token budget configured');
    return;
  }
  container.innerHTML = agents
    .filter(a => a.tokenBudget)
    .map(a => {
      const { pct, colorClass } = computeTokenPct(a.tokensUsed || 0, a.tokenBudget);
      return `
        <div class="token-meter">
          <div class="meter-header">
            <span class="meter-label">${esc(a.name || a.id)}</span>
            <span class="meter-value">${jarvis.formatNumber(a.tokensUsed || 0)} / ${jarvis.formatNumber(a.tokenBudget)}</span>
          </div>
          <div class="meter-bar"><div class="meter-fill ${colorClass}" style="width: ${pct}%"></div></div>
        </div>
      `;
    }).join('') + '<div class="token-summary"></div>';
}

let _activeTab = 'in_progress';
let _allTasks = [];

function renderTasks(el, tasks) {
  _allTasks = tasks || [];
  const pending  = el.querySelector('#cc-pending-count');
  const progress = el.querySelector('#cc-progress-count');
  const done     = el.querySelector('#cc-done-count');
  if (pending)  pending.textContent  = _allTasks.filter(t => normalizeStatus(t.status) === 'pending').length;
  if (progress) progress.textContent = _allTasks.filter(t => normalizeStatus(t.status) === 'in_progress').length;
  if (done)     done.textContent     = _allTasks.filter(t => normalizeStatus(t.status) === 'completed').length;

  const list = el.querySelector('#cc-task-list');
  const filtered = _allTasks.filter(t => normalizeStatus(t.status) === _activeTab);
  if (!filtered.length) {
    list.innerHTML = emptyState(`No ${_activeTab.replace('_', ' ')} tasks`);
    return;
  }
  list.innerHTML = filtered.map(t => `
    <div class="task-item">
      <div class="task-priority ${esc(t.priority || 'medium')}"></div>
      <div class="task-title">${esc(t.title || t.id)}</div>
      ${t.project ? `<span class="task-project">${esc(t.project)}</span>` : ''}
      ${t.agent ? `<span class="task-agent">${esc(t.agent)}</span>` : ''}
    </div>
  `).join('');
}

function renderFilteredTasks(el, tab) {
  const list = el.querySelector('#cc-task-list');
  const filtered = _allTasks.filter(t => normalizeStatus(t.status) === tab);
  if (!filtered.length) {
    list.innerHTML = emptyState(`No ${tab.replace('_', ' ')} tasks`);
    return;
  }
  list.innerHTML = filtered.map(t => `
    <div class="task-item">
      <div class="task-priority ${esc(t.priority || 'medium')}"></div>
      <div class="task-title">${esc(t.title || t.id)}</div>
      ${t.project ? `<span class="task-project">${esc(t.project)}</span>` : ''}
      ${t.agent ? `<span class="task-agent">${esc(t.agent)}</span>` : ''}
    </div>
  `).join('');
}

function renderActivity(el, items, jarvis) {
  const feed = el.querySelector('#cc-activity-feed');
  if (!items || !items.length) {
    feed.innerHTML = emptyState('No activity yet');
    return;
  }
  feed.innerHTML = items.map(a => `
    <div class="activity-item">
      <div class="activity-icon ${esc(a.type || 'info')}">${activityIcon(a.type)}</div>
      <div class="activity-text"><strong>${esc(a.agent || 'System')}</strong> ${esc(a.text || '')}</div>
      <div class="activity-time">${jarvis.timeAgo(a.timestamp)}</div>
    </div>
  `).join('');
}

// ── Test setup ────────────────────────────────────────────────────────────────

function makeJarvis(state) {
  return {
    timeAgo:        ts  => ts ? 'just now' : '--',
    formatCurrency: v   => v != null ? `$${Number(v).toFixed(2)}` : '--',
    formatNumber:   v   => v != null ? String(v) : '--',
    state,
  };
}

let pageEl;
let jarvis;
let state;

beforeEach(() => {
  setupDOM();
  setupChartMock();

  // Reset per-test tab state
  _activeTab = 'in_progress';
  _allTasks  = [];

  state  = createMockState();
  jarvis = makeJarvis(state);

  const container = document.getElementById('page-container');
  pageEl = document.createElement('div');
  pageEl.id = 'page-command-center';
  pageEl.className = 'page-view active';
  container.appendChild(pageEl);

  // Inject template (mirrors what init() does before calling renderAll)
  pageEl.innerHTML = buildTemplate();
});

// ── Agent Status Grid ─────────────────────────────────────────────────────────

describe('command-center: agent status grid', () => {
  it('renders one agent card per agent in state', () => {
    renderAgents(pageEl, state.agents, jarvis);
    const cards = pageEl.querySelectorAll('.agent-card');
    expect(cards.length).toBe(state.agents.length);
  });

  it('displays the correct agent name inside each card', () => {
    renderAgents(pageEl, state.agents, jarvis);
    const names = [...pageEl.querySelectorAll('.agent-name')].map(el => el.textContent.trim());
    expect(names).toContain('Claude Code');
    expect(names).toContain('Codex CLI');
  });

  it('shows status badge with the agent status text', () => {
    renderAgents(pageEl, state.agents, jarvis);
    const badges = [...pageEl.querySelectorAll('.status-badge')].map(el => el.textContent.trim());
    expect(badges).toContain('online');
    expect(badges).toContain('offline');
  });

  it('renders the current task text when agent has an active task', () => {
    renderAgents(pageEl, state.agents, jarvis);
    const taskDivs = pageEl.querySelectorAll('.agent-task');
    // Only the online agent (claude) has a currentTask in mock state
    expect(taskDivs.length).toBe(1);
    expect(taskDivs[0].textContent.trim()).toBe('Building tests');
  });

  it('shows empty state message when agents array is empty', () => {
    renderAgents(pageEl, [], jarvis);
    const empty = pageEl.querySelector('.empty-state');
    expect(empty).not.toBeNull();
    expect(empty.textContent).toContain('No agents reporting');
  });
});

// ── Token Budget Meters ───────────────────────────────────────────────────────

describe('command-center: token budget meters', () => {
  it('renders a meter row for each agent that has a tokenBudget', () => {
    renderTokenBudget(pageEl, state.agents, jarvis);
    // Both mock agents have tokenBudget set
    const meters = pageEl.querySelectorAll('.token-meter');
    const agentsWithBudget = state.agents.filter(a => a.tokenBudget > 0);
    expect(meters.length).toBe(agentsWithBudget.length);
  });

  it('shows empty state when no agents have a token budget', () => {
    const agentsNoBudget = state.agents.map(a => ({ ...a, tokenBudget: 0 }));
    renderTokenBudget(pageEl, agentsNoBudget, jarvis);
    const empty = pageEl.querySelector('.empty-state');
    expect(empty).not.toBeNull();
    expect(empty.textContent).toContain('No token budget configured');
  });

  it('meter label contains the agent name', () => {
    renderTokenBudget(pageEl, state.agents, jarvis);
    const labels = [...pageEl.querySelectorAll('.meter-label')].map(el => el.textContent.trim());
    expect(labels).toContain('Claude Code');
  });
});

// ── Task Queue ────────────────────────────────────────────────────────────────

describe('command-center: task queue', () => {
  it('shows the correct pending count in the tab badge', () => {
    renderTasks(pageEl, state.tasks);
    // Mock state has 1 todo task → normalizeStatus('todo') = 'pending'
    const count = pageEl.querySelector('#cc-pending-count').textContent;
    expect(count).toBe('1');
  });

  it('shows the correct in-progress count in the tab badge', () => {
    renderTasks(pageEl, state.tasks);
    const count = pageEl.querySelector('#cc-progress-count').textContent;
    expect(count).toBe('1');
  });

  it('default active tab (in_progress) renders the in-progress task', () => {
    _activeTab = 'in_progress';
    renderTasks(pageEl, state.tasks);
    const items = pageEl.querySelectorAll('.task-item');
    expect(items.length).toBe(1);
    expect(items[0].querySelector('.task-title').textContent.trim()).toBe('Build dashboard');
  });

  it('switching to pending tab renders only pending tasks', () => {
    _activeTab = 'in_progress';
    renderTasks(pageEl, state.tasks);
    // Simulate tab switch
    renderFilteredTasks(pageEl, 'pending');
    const items = pageEl.querySelectorAll('.task-item');
    expect(items.length).toBe(1);
    expect(items[0].querySelector('.task-title').textContent.trim()).toBe('Write tests');
  });

  it('switching to completed tab shows empty state when no done tasks are present', () => {
    const tasksNoDone = state.tasks.filter(t => t.status !== 'done');
    _allTasks = [];
    renderTasks(pageEl, tasksNoDone);
    renderFilteredTasks(pageEl, 'completed');
    const empty = pageEl.querySelector('.empty-state');
    expect(empty).not.toBeNull();
    expect(empty.textContent).toContain('No completed tasks');
  });
});

// ── Activity Feed ─────────────────────────────────────────────────────────────

describe('command-center: activity feed', () => {
  it('renders one activity item per entry in state.activity', () => {
    renderActivity(pageEl, state.activity, jarvis);
    const items = pageEl.querySelectorAll('.activity-item');
    expect(items.length).toBe(state.activity.length);
  });

  it('task-type activity item carries the task icon class', () => {
    renderActivity(pageEl, state.activity, jarvis);
    const icons = pageEl.querySelectorAll('.activity-icon.task');
    expect(icons.length).toBeGreaterThanOrEqual(1);
  });

  it('deploy-type activity item carries the deploy icon class', () => {
    renderActivity(pageEl, state.activity, jarvis);
    const icons = pageEl.querySelectorAll('.activity-icon.deploy');
    expect(icons.length).toBeGreaterThanOrEqual(1);
  });

  it('shows the activity text from state inside each item', () => {
    renderActivity(pageEl, state.activity, jarvis);
    const texts = [...pageEl.querySelectorAll('.activity-text')].map(el => el.textContent);
    expect(texts.some(t => t.includes('Dashboard created'))).toBe(true);
  });

  it('shows empty state message when activity array is empty', () => {
    renderActivity(pageEl, [], jarvis);
    const empty = pageEl.querySelector('.empty-state');
    expect(empty).not.toBeNull();
    expect(empty.textContent).toContain('No activity yet');
  });
});
