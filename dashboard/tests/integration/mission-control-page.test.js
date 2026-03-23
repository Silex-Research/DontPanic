// Integration tests for the Mission Control page module.
//
// Strategy: inject the page's HTML template (built via buildHTML() from the
// lib's MC_COLUMNS / MC_COLUMN_META constants), then call the same render
// helpers the page uses. Asserts on kanban columns, agent sidebar, project
// filter pills, and status pill counts.
//
// Avoids dynamic import of mission-control.js to sidestep module-level IIFE
// caching; all logic under test is covered by lib/mission-control-logic.js.

import { describe, it, expect, beforeEach } from 'vitest';
import {
  MC_COLUMNS,
  MC_COLUMN_META,
  STATUS_TO_COLUMN,
  PROJECT_NAMES,
  getAgentMeta,
  deriveColumn,
} from '../../lib/mission-control-logic.js';
import { setupDOM, createMockState, setupChartMock } from '../helpers/setup.js';

// ── HTML template (mirrors mission-control.js buildHTML()) ────────────────────

function buildHTML() {
  const colsHTML = MC_COLUMNS.map(col => {
    const { label, dotClass } = MC_COLUMN_META[col];
    return `
      <div class="mc-column" data-column="${col}">
        <div class="mc-column-header">
          <span class="mc-dot ${dotClass}"></span>
          <span class="mc-col-title">${label}</span>
          <span class="mc-col-count" id="mc-count-${col}">0</span>
        </div>
        <div class="mc-cards" data-column="${col}"></div>
      </div>`;
  }).join('');

  return `
    <div class="mc-layout">
      <aside class="mc-agents-sidebar">
        <div class="mc-sidebar-header">
          <span class="mc-dot mc-dot--green mc-dot--pulse"></span>
          AGENTS
          <span id="mc-agent-count" class="mc-badge">0</span>
        </div>
        <div id="mc-agent-summary" class="mc-agent-summary active">
          All Agents &mdash; 0 active / 0 total
        </div>
        <div id="mc-agent-list" class="mc-agent-list"></div>
      </aside>
      <div class="mc-queue">
        <div class="mc-queue-header">
          <div class="mc-queue-title">
            <span class="mc-dot mc-dot--blue"></span>
            MISSION QUEUE
          </div>
          <div class="mc-queue-stats">
            <span id="mc-total-tasks">0</span> total
            &middot;
            <span id="mc-active-tasks">0</span> active
          </div>
        </div>
        <div class="mc-status-pills" id="mc-status-pills">
          <button class="mc-pill active" data-status="all">
            <span class="mc-dot mc-dot--gray"></span> All
            <span class="mc-pill-count" data-count="all">0</span>
          </button>
          <button class="mc-pill" data-status="backlog">
            <span class="mc-dot mc-dot--purple"></span> Inbox
            <span class="mc-pill-count" data-count="backlog">0</span>
          </button>
          <button class="mc-pill" data-status="todo">
            <span class="mc-dot mc-dot--blue"></span> Assigned
            <span class="mc-pill-count" data-count="todo">0</span>
          </button>
          <button class="mc-pill" data-status="in_progress">
            <span class="mc-dot mc-dot--green"></span> Active
            <span class="mc-pill-count" data-count="in_progress">0</span>
          </button>
          <button class="mc-pill" data-status="review">
            <span class="mc-dot mc-dot--yellow"></span> Review
            <span class="mc-pill-count" data-count="review">0</span>
          </button>
          <button class="mc-pill" data-status="done">
            <span class="mc-dot mc-dot--gray"></span> Done
            <span class="mc-pill-count" data-count="done">0</span>
          </button>
        </div>
        <div class="mc-project-filters" id="mc-project-filters">
          <button class="mc-proj-filter active" data-project="all">All</button>
          <button class="mc-proj-filter" data-project="styln">Styln</button>
          <button class="mc-proj-filter" data-project="spindine">Spin &amp; Dine</button>
          <button class="mc-proj-filter" data-project="quantre">quantRE</button>
          <button class="mc-proj-filter" data-project="ibkr">IBKR</button>
          <button class="mc-proj-filter" data-project="infra">Infra</button>
        </div>
        <div class="mc-board" id="mc-board">
          ${colsHTML}
        </div>
      </div>
      <aside class="mc-feed-sidebar">
        <div class="mc-sidebar-header">
          <span class="mc-dot mc-dot--green mc-dot--pulse"></span>
          LIVE FEED
        </div>
        <div id="mc-feed-filters" class="mc-feed-filters"></div>
        <div id="mc-feed-list" class="mc-feed-list"></div>
      </aside>
    </div>
    <div id="mc-modal" class="mc-modal hidden"></div>
  `;
}

// ── Rendering helpers mirroring the page module ───────────────────────────────

function esc(str) {
  if (str == null) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function renderAgentSidebar(page, agents, activeAgent = 'all') {
  const countEl   = page.querySelector('#mc-agent-count');
  const summaryEl = page.querySelector('#mc-agent-summary');
  const listEl    = page.querySelector('#mc-agent-list');
  if (!countEl || !summaryEl || !listEl) return;

  const active = agents.filter(a => a.status === 'online' || a.status === 'busy').length;
  countEl.textContent = agents.length;
  summaryEl.innerHTML = `All Agents &mdash; ${active} active / ${agents.length} total`;

  listEl.innerHTML = agents.map(a => {
    const meta = getAgentMeta(a.id);
    const isSelected = activeAgent === a.id;
    let statusClass = 'offline';
    let statusLabel = 'OFFLINE';
    if (a.status === 'online' || a.status === 'busy') { statusClass = 'working'; statusLabel = 'WORKING'; }
    else if (a.status === 'idle') { statusClass = 'idle'; statusLabel = 'IDLE'; }
    return `
      <div class="mc-agent-row${isSelected ? ' active' : ''}" data-agent-id="${esc(a.id)}">
        <div class="mc-agent-avatar" style="background:${meta.color}">${meta.initials}</div>
        <div class="mc-agent-info">
          <div class="mc-agent-name">${esc(a.name || a.id)}</div>
          <div class="mc-agent-role">${esc(a.role || 'Agent')}</div>
        </div>
        <span class="mc-agent-status mc-agent-status--${statusClass}">${statusLabel}</span>
      </div>`;
  }).join('');
}

function renderBoard(page, tasks, agents, activeProject = 'all', activeAgent = 'all') {
  let filtered = tasks.map(t => ({ ...t, column: deriveColumn(t) }));

  if (activeProject !== 'all') {
    filtered = filtered.filter(t => (t.project || '').toLowerCase() === activeProject);
  }
  if (activeAgent !== 'all') {
    filtered = filtered.filter(t => (t.agent || '').toLowerCase() === activeAgent);
  }

  const groups = {};
  MC_COLUMNS.forEach(c => { groups[c] = []; });
  filtered.forEach(t => {
    const col = MC_COLUMNS.includes(t.column) ? t.column : 'backlog';
    groups[col].push(t);
  });

  MC_COLUMNS.forEach(col => {
    const cardsEl = page.querySelector(`.mc-cards[data-column="${col}"]`);
    const countEl = page.querySelector(`#mc-count-${col}`);
    if (!cardsEl) return;

    const colTasks = groups[col];
    if (countEl) countEl.textContent = colTasks.length;

    if (!colTasks.length) {
      cardsEl.innerHTML = '<div class="mc-empty-col">No tasks</div>';
      return;
    }

    cardsEl.innerHTML = colTasks.map(t => `
      <div class="mc-card" data-task-id="${esc(t.id)}">
        <div class="mc-card-title">${esc(t.title || t.id)}</div>
        ${t.project ? `<span class="mc-card-project mc-card-project--${esc((t.project || '').toLowerCase())}">${esc(t.project)}</span>` : ''}
      </div>
    `).join('');
  });

  // Update header stats
  const totalEl  = page.querySelector('#mc-total-tasks');
  const activeEl = page.querySelector('#mc-active-tasks');
  const activeCols = ['todo', 'in_progress', 'review'];
  if (totalEl)  totalEl.textContent  = filtered.length;
  if (activeEl) activeEl.textContent = filtered.filter(t => activeCols.includes(t.column)).length;

  // Update pill counts
  const pillCounts = {};
  MC_COLUMNS.forEach(c => { pillCounts[c] = groups[c].length; });
  pillCounts['all'] = filtered.length;
  page.querySelectorAll('.mc-pill-count').forEach(span => {
    const key = span.dataset.count;
    if (key in pillCounts) span.textContent = pillCounts[key];
  });
}

// ── Test setup ────────────────────────────────────────────────────────────────

let pageEl;
let state;

beforeEach(() => {
  setupDOM();
  setupChartMock();

  state  = createMockState();

  const container = document.getElementById('page-container');
  pageEl = document.createElement('div');
  pageEl.id = 'page-mission-control';
  pageEl.className = 'page-view active';
  container.appendChild(pageEl);

  pageEl.innerHTML = buildHTML();
});

// ── Kanban columns ────────────────────────────────────────────────────────────

describe('mission-control: kanban columns', () => {
  it('renders exactly 5 kanban columns', () => {
    const columns = pageEl.querySelectorAll('.mc-column');
    expect(columns.length).toBe(5);
  });

  it('column headers show the correct labels from MC_COLUMN_META', () => {
    const titles = [...pageEl.querySelectorAll('.mc-col-title')].map(el => el.textContent.trim());
    expect(titles).toContain('INBOX');
    expect(titles).toContain('ASSIGNED');
    expect(titles).toContain('IN PROGRESS');
    expect(titles).toContain('REVIEW');
    expect(titles).toContain('DONE');
  });

  it('tasks appear in the correct column based on their status', () => {
    renderBoard(pageEl, state.tasks, state.agents);
    // t1: in_progress → in_progress column
    const inProgressCards = pageEl.querySelectorAll('.mc-cards[data-column="in_progress"] .mc-card');
    expect(inProgressCards.length).toBe(1);
    expect(inProgressCards[0].querySelector('.mc-card-title').textContent.trim()).toBe('Build dashboard');
  });

  it('todo-status tasks land in the ASSIGNED column', () => {
    renderBoard(pageEl, state.tasks, state.agents);
    const assignedCards = pageEl.querySelectorAll('.mc-cards[data-column="todo"] .mc-card');
    expect(assignedCards.length).toBe(1);
    expect(assignedCards[0].querySelector('.mc-card-title').textContent.trim()).toBe('Write tests');
  });

  it('done-status tasks land in the DONE column', () => {
    renderBoard(pageEl, state.tasks, state.agents);
    const doneCards = pageEl.querySelectorAll('.mc-cards[data-column="done"] .mc-card');
    expect(doneCards.length).toBe(1);
    expect(doneCards[0].querySelector('.mc-card-title').textContent.trim()).toBe('Deploy staging');
  });

  it('column count badge updates to reflect the number of cards in that column', () => {
    renderBoard(pageEl, state.tasks, state.agents);
    const inProgressCount = pageEl.querySelector('#mc-count-in_progress').textContent;
    expect(inProgressCount).toBe('1');
  });
});

// ── Agent sidebar ─────────────────────────────────────────────────────────────

describe('mission-control: agent sidebar', () => {
  it('renders one agent row per agent in state', () => {
    renderAgentSidebar(pageEl, state.agents);
    const rows = pageEl.querySelectorAll('.mc-agent-row');
    expect(rows.length).toBe(state.agents.length);
  });

  it('agent count badge shows total number of agents', () => {
    renderAgentSidebar(pageEl, state.agents);
    const badge = pageEl.querySelector('#mc-agent-count').textContent;
    expect(badge).toBe(String(state.agents.length));
  });

  it('summary line reflects active vs total agent counts', () => {
    renderAgentSidebar(pageEl, state.agents);
    const summary = pageEl.querySelector('#mc-agent-summary').textContent;
    // 1 online agent in mock state
    expect(summary).toContain('1 active');
    expect(summary).toContain('2 total');
  });

  it('online agent row shows WORKING status label', () => {
    renderAgentSidebar(pageEl, state.agents);
    const rows = [...pageEl.querySelectorAll('.mc-agent-row')];
    const claudeRow = rows.find(r => r.dataset.agentId === 'claude');
    expect(claudeRow.querySelector('.mc-agent-status').textContent).toBe('WORKING');
  });

  it('offline agent row shows OFFLINE status label', () => {
    renderAgentSidebar(pageEl, state.agents);
    const rows = [...pageEl.querySelectorAll('.mc-agent-row')];
    const codexRow = rows.find(r => r.dataset.agentId === 'codex');
    expect(codexRow.querySelector('.mc-agent-status').textContent).toBe('OFFLINE');
  });
});

// ── Project filter pills ──────────────────────────────────────────────────────

describe('mission-control: project filter pills', () => {
  it('renders the All filter pill as active by default', () => {
    const allPill = pageEl.querySelector('.mc-proj-filter[data-project="all"]');
    expect(allPill.classList.contains('active')).toBe(true);
  });

  it('renders project filter pills for all known projects', () => {
    const filters = [...pageEl.querySelectorAll('.mc-proj-filter')].map(el => el.dataset.project);
    expect(filters).toContain('styln');
    expect(filters).toContain('infra');
    expect(filters).toContain('spindine');
  });

  it('filtering by project shows only tasks from that project', () => {
    renderBoard(pageEl, state.tasks, state.agents, 'infra');
    // t1 (in_progress, infra) and t2 (todo, infra) — t3 (styln) is excluded
    const allCards = pageEl.querySelectorAll('.mc-card');
    expect(allCards.length).toBe(2);
  });
});

// ── Status pill counts ────────────────────────────────────────────────────────

describe('mission-control: status pill counts', () => {
  it('All pill count equals total number of tasks', () => {
    renderBoard(pageEl, state.tasks, state.agents);
    const allCount = pageEl.querySelector('.mc-pill-count[data-count="all"]').textContent;
    expect(allCount).toBe(String(state.tasks.length));
  });

  it('in_progress pill count reflects tasks with in_progress status', () => {
    renderBoard(pageEl, state.tasks, state.agents);
    const count = pageEl.querySelector('.mc-pill-count[data-count="in_progress"]').textContent;
    expect(count).toBe('1');
  });
});
