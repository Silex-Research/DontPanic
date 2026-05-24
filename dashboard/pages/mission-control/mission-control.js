// ── Work Page — DontPanic Dashboard ──
// Read-only kanban viewer of plan/feature lifecycle with agent sidebar and
// live feed. Reads from Jarvis.state.tasks, .agents, .activity — no
// Firestore dependency. Per plan 2026-05-24-001 F002 + D010, V0 Work is
// read-only: no drag-to-mutate, no inline dispatch/approve. Future plans
// may add drag-to-command as a non-mutating command-preview pattern.

import {
  MC_COLUMNS,
  MC_COLUMN_META,
  STATUS_TO_COLUMN,
  PROJECT_NAMES,
  AGENT_META,
  getAgentMeta,
  deriveColumn,
} from '../../lib/mission-control-logic.js';

const FEED_ICONS = {
  deploy: '▲',
  task:   '✓',
  alert:  '⚠',
  sync:   '↻',
  info:   '●',
};

// ── Module State ──

let mcTasks = [];
let mcAgents = [];
let mcActivity = [];

let mcActiveAgent  = 'all';
let mcActiveStatus = 'all';
let mcActiveProject = 'all';
let mcFeedAgent    = 'all';

// ── HTML Template ──

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

      <!-- ── Agent Sidebar (Left) ── -->
      <aside class="mc-agents-sidebar">
        <div class="mc-sidebar-header">
          <span class="mc-dot mc-dot--green mc-dot--pulse"></span>
          AGENTS
          <span id="mc-agent-count" class="mc-badge">0</span>
        </div>
        <div id="mc-agent-summary" class="mc-agent-summary active">
          All Agents &mdash; 0 active / 0 total
        </div>
        <div id="mc-agent-list" class="mc-agent-list">
          <!-- Populated by JS -->
        </div>
      </aside>

      <!-- ── Work Queue (Center) ── -->
      <div class="mc-queue">
        <div class="mc-queue-header">
          <div class="mc-queue-title">
            <span class="mc-dot mc-dot--blue"></span>
            WORK QUEUE
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

      <!-- ── Live Feed Sidebar (Right) ── -->
      <aside class="mc-feed-sidebar">
        <div class="mc-sidebar-header">
          <span class="mc-dot mc-dot--green mc-dot--pulse"></span>
          LIVE FEED
        </div>
        <div id="mc-feed-filters" class="mc-feed-filters">
          <!-- Populated by JS -->
        </div>
        <div id="mc-feed-list" class="mc-feed-list">
          <!-- Populated by JS -->
        </div>
      </aside>

    </div>

    <!-- ── Task Detail Modal ── -->
    <div id="mc-modal" class="mc-modal hidden" role="dialog" aria-modal="true" aria-labelledby="mc-modal-title">
      <div class="mc-modal-backdrop"></div>
      <div class="mc-modal-panel">
        <button class="mc-modal-close" aria-label="Close">&times;</button>
        <div id="mc-modal-body" class="mc-modal-body"></div>
      </div>
    </div>
  `;
}

// ── Sanitization ──

function esc(str) {
  if (str == null) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

// ── Render: Agent Sidebar ──

function renderAgentSidebar() {
  const page = Jarvis.getPageEl('mission-control');
  const countEl    = page.querySelector('#mc-agent-count');
  const summaryEl  = page.querySelector('#mc-agent-summary');
  const listEl     = page.querySelector('#mc-agent-list');
  if (!countEl || !summaryEl || !listEl) return;

  const active = mcAgents.filter(a => a.status === 'online' || a.status === 'busy').length;
  countEl.textContent = mcAgents.length;

  summaryEl.textContent = '';
  summaryEl.innerHTML   = `All Agents &mdash; ${active} active / ${mcAgents.length} total`;
  summaryEl.className   = 'mc-agent-summary' + (mcActiveAgent === 'all' ? ' active' : '');

  listEl.innerHTML = mcAgents.map(a => {
    const meta = getAgentMeta(a.id);
    const isSelected = mcActiveAgent === a.id;

    let statusClass = 'offline';
    let statusLabel = 'OFFLINE';
    if (a.status === 'online' || a.status === 'busy') {
      statusClass = 'working'; statusLabel = 'WORKING';
    } else if (a.status === 'idle') {
      statusClass = 'idle'; statusLabel = 'IDLE';
    }

    return `
      <div class="mc-agent-row${isSelected ? ' active' : ''}" data-agent-id="${esc(a.id)}">
        <div class="mc-agent-avatar" style="background:${meta.color}">${meta.initials}</div>
        <div class="mc-agent-info">
          <div class="mc-agent-name">
            ${esc(a.name || a.id)}
            <span class="mc-role-badge ${meta.badgeClass}">${meta.badge}</span>
          </div>
          <div class="mc-agent-role">${esc(a.role || 'Agent')}</div>
        </div>
        <span class="mc-agent-status mc-agent-status--${statusClass}">${statusLabel}</span>
      </div>`;
  }).join('');

  // Bind click on "All Agents" summary row
  summaryEl.onclick = () => {
    mcActiveAgent = 'all';
    renderAgentSidebar();
    renderBoard();
  };

  // Bind click on individual agent rows
  listEl.querySelectorAll('.mc-agent-row').forEach(row => {
    row.addEventListener('click', () => {
      mcActiveAgent = row.dataset.agentId;
      renderAgentSidebar();
      renderBoard();
    });
  });
}

// ── Render: Kanban Board ──

function renderBoard() {
  const page = Jarvis.getPageEl('mission-control');

  // Apply filters
  let filtered = mcTasks.map(t => ({ ...t, column: deriveColumn(t) }));

  if (mcActiveProject !== 'all') {
    filtered = filtered.filter(t => (t.project || '').toLowerCase() === mcActiveProject);
  }

  if (mcActiveAgent !== 'all') {
    filtered = filtered.filter(t => {
      const taskAgent = (t.agent || '').toLowerCase();
      return taskAgent === mcActiveAgent;
    });
  }

  // Group by column
  const groups = {};
  MC_COLUMNS.forEach(c => { groups[c] = []; });
  filtered.forEach(t => {
    const col = MC_COLUMNS.includes(t.column) ? t.column : 'backlog';
    groups[col].push(t);
  });

  // Sort by created date within each column (newest first)
  MC_COLUMNS.forEach(col => {
    groups[col].sort((a, b) => {
      const ta = a.created ? new Date(a.created).getTime() : 0;
      const tb = b.created ? new Date(b.created).getTime() : 0;
      return tb - ta;
    });
  });

  // Update header stats
  const totalEl  = page.querySelector('#mc-total-tasks');
  const activeEl = page.querySelector('#mc-active-tasks');
  if (totalEl)  totalEl.textContent  = filtered.length;
  if (activeEl) activeEl.textContent = groups.in_progress.length;

  // Update pill counts
  page.querySelectorAll('.mc-pill-count').forEach(el => {
    const key = el.dataset.count;
    el.textContent = key === 'all' ? filtered.length : (groups[key]?.length ?? 0);
  });

  // Show/hide columns based on status filter
  const board = page.querySelector('#mc-board');
  if (!board) return;

  const visibleCols = mcActiveStatus === 'all' ? MC_COLUMNS : [mcActiveStatus];
  board.style.gridTemplateColumns = mcActiveStatus === 'all' ? 'repeat(5, 1fr)' : '1fr';

  MC_COLUMNS.forEach(col => {
    const colEl = board.querySelector(`.mc-column[data-column="${col}"]`);
    if (!colEl) return;
    colEl.style.display = visibleCols.includes(col) ? '' : 'none';
  });

  // Render each column's cards
  MC_COLUMNS.forEach(col => {
    const container = board.querySelector(`.mc-cards[data-column="${col}"]`);
    const countEl   = page.querySelector(`#mc-count-${col}`);
    if (!container || !countEl) return;

    countEl.textContent = groups[col].length;

    if (!groups[col].length) {
      container.innerHTML = '<div class="mc-empty">No tasks</div>';
      bindColumnDropTarget(container, col);
      return;
    }

    container.innerHTML = groups[col].map(t => renderCard(t)).join('');

    // Bind card click → modal. V0 Work is read-only — no drag handlers,
    // no drop targets, no state mutation. (F002 + D010.)
    container.querySelectorAll('.mc-card').forEach(card => {
      card.addEventListener('click', () => openTaskModal(card.dataset.taskId));
    });
  });
}

function renderCard(task) {
  const meta       = getAgentMeta((task.agent || '').toLowerCase());
  const agentName  = task.agent
    ? (mcAgents.find(a => a.id === task.agent)?.name || task.agent)
    : 'Unassigned';
  const projectKey = (task.project || '').toLowerCase();
  const projectLabel = PROJECT_NAMES[projectKey] || task.project || 'Unknown';
  const priority   = task.priority || 'medium';
  const timeAgo    = Jarvis.timeAgo(task.created);
  const currentColumn = deriveColumn(task);

  // V0 Work is read-only — no `draggable` attribute. Drag-to-mutate is
  // forbidden until a future plan ships drag-to-command as a non-mutating
  // command-preview pattern (plan 2026-05-24-001 D010).
  return `
    <div class="mc-card" data-task-id="${esc(task.id)}" data-current-column="${esc(currentColumn)}">
      <div class="mc-card-header-row">
        <span class="mc-card-project mc-card-project--${esc(projectKey)}">${esc(projectLabel)}</span>
        <span class="mc-priority-dot mc-priority-dot--${esc(priority)}" title="${esc(priority)} priority"></span>
      </div>
      <div class="mc-card-title">${esc(task.title || task.id)}</div>
      <div class="mc-card-footer">
        <div class="mc-card-avatar" style="background:${meta.color}">${meta.initials}</div>
        <span class="mc-card-assignee">${esc(agentName)}</span>
        <span class="mc-card-time">${esc(timeAgo)}</span>
      </div>
    </div>`;
}

// ── Render: Live Feed ──

function renderFeed() {
  const page    = Jarvis.getPageEl('mission-control');
  const listEl  = page.querySelector('#mc-feed-list');
  if (!listEl) return;

  let items = mcActivity;
  if (mcFeedAgent !== 'all') {
    items = mcActivity.filter(a => (a.agent || 'System') === mcFeedAgent);
  }

  if (!items.length) {
    listEl.innerHTML = '<div class="mc-empty mc-empty--feed">No activity</div>';
    return;
  }

  listEl.innerHTML = items.map(a => {
    const icon    = FEED_ICONS[a.type] || FEED_ICONS.info;
    const timeStr = Jarvis.timeAgo(a.timestamp);
    const textRaw = esc(a.text || a.message || '');
    // Highlight @mentions
    const textHtml = textRaw.replace(/@([\w-]+)/g, '<span class="mc-mention">@$1</span>');
    const agentLabel = esc(a.agent || 'System');

    return `
      <div class="mc-feed-item">
        <div class="mc-feed-icon ${esc(a.type || 'info')}">${icon}</div>
        <div class="mc-feed-body">
          <div class="mc-feed-text">${textHtml}</div>
          <div class="mc-feed-meta">${agentLabel} &middot; ${esc(timeStr)}</div>
        </div>
      </div>`;
  }).join('');
}

function renderFeedFilters() {
  const page      = Jarvis.getPageEl('mission-control');
  const filtersEl = page.querySelector('#mc-feed-filters');
  if (!filtersEl) return;

  // Count events per agent name
  const counts = {};
  mcActivity.forEach(a => {
    const name = a.agent || 'System';
    counts[name] = (counts[name] || 0) + 1;
  });

  let html = `<button class="mc-feed-pill${mcFeedAgent === 'all' ? ' active' : ''}" data-agent="all">All</button>`;

  mcAgents.forEach(a => {
    const name  = a.name || a.id;
    const count = counts[name] || counts[a.id] || 0;
    const label = count ? `${esc(name)} (${count})` : esc(name);
    html += `<button class="mc-feed-pill${mcFeedAgent === name ? ' active' : ''}" data-agent="${esc(name)}">${label}</button>`;
  });

  if (counts['System']) {
    html += `<button class="mc-feed-pill${mcFeedAgent === 'System' ? ' active' : ''}" data-agent="System">System (${counts['System']})</button>`;
  }

  filtersEl.innerHTML = html;

  filtersEl.querySelectorAll('.mc-feed-pill').forEach(btn => {
    btn.addEventListener('click', () => {
      mcFeedAgent = btn.dataset.agent;
      renderFeedFilters();
      renderFeed();
    });
  });
}

// ── Filter Binding ──

function bindFilters() {
  const page = Jarvis.getPageEl('mission-control');

  // Status pills
  page.querySelectorAll('.mc-pill').forEach(btn => {
    btn.addEventListener('click', () => {
      page.querySelectorAll('.mc-pill').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      mcActiveStatus = btn.dataset.status;
      renderBoard();
    });
  });

  // Project filters
  page.querySelectorAll('.mc-proj-filter').forEach(btn => {
    btn.addEventListener('click', () => {
      page.querySelectorAll('.mc-proj-filter').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      mcActiveProject = btn.dataset.project;
      renderBoard();
    });
  });
}

// ── Task Detail Modal ──

function openTaskModal(taskId) {
  const task  = mcTasks.find(t => t.id === taskId);
  const modal = document.querySelector('#mc-modal');
  const body  = document.querySelector('#mc-modal-body');
  if (!task || !modal || !body) return;

  const projectKey   = (task.project || '').toLowerCase();
  const projectLabel = PROJECT_NAMES[projectKey] || task.project || '—';
  const priority     = task.priority || 'medium';
  const column       = deriveColumn(task);
  const columnLabel  = MC_COLUMN_META[column]?.label || column;
  const agentId      = (task.agent || '').toLowerCase();
  const agentName    = agentId
    ? (mcAgents.find(a => a.id === agentId)?.name || task.agent)
    : 'Unassigned';

  body.innerHTML = `
    <div class="mc-modal-title">${esc(task.title || task.id)}</div>
    <div class="mc-modal-fields">
      <div class="mc-modal-field">
        <div class="mc-modal-label">Project</div>
        <div class="mc-modal-value">
          <span class="mc-card-project mc-card-project--${esc(projectKey)}">${esc(projectLabel)}</span>
        </div>
      </div>
      <div class="mc-modal-field">
        <div class="mc-modal-label">Status</div>
        <div class="mc-modal-value">${esc(columnLabel)}</div>
      </div>
      <div class="mc-modal-field">
        <div class="mc-modal-label">Priority</div>
        <div class="mc-modal-value mc-modal-priority">
          <span class="mc-priority-dot mc-priority-dot--${esc(priority)}"></span>
          ${esc(priority)}
        </div>
      </div>
      <div class="mc-modal-field">
        <div class="mc-modal-label">Assigned To</div>
        <div class="mc-modal-value">${esc(agentName)}</div>
      </div>
      <div class="mc-modal-field">
        <div class="mc-modal-label">Created</div>
        <div class="mc-modal-value">${task.created ? new Date(task.created).toLocaleString() : '—'}</div>
      </div>
    </div>`;

  modal.classList.remove('hidden');
  modal.querySelector('.mc-modal-close').focus();
}

function closeTaskModal() {
  const modal = document.querySelector('#mc-modal');
  if (modal) modal.classList.add('hidden');
}

function bindModal() {
  // Close button
  document.addEventListener('click', e => {
    if (e.target.closest('.mc-modal-close') || e.target.classList.contains('mc-modal-backdrop')) {
      closeTaskModal();
    }
  });

  // Escape key
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') closeTaskModal();
  });
}

// ── Full Render Pass ──

function renderAll(state) {
  mcTasks    = (state.tasks    || []);
  mcAgents   = (state.agents   || []);
  mcActivity = (state.activity || []);

  renderAgentSidebar();
  renderBoard();
  renderFeedFilters();
  renderFeed();
}

// ── Page Registration ──

Jarvis.registerPage({
  id:    'mission-control',
  label: 'Work',

  init(state) {
    const el = Jarvis.getPageEl('mission-control');
    el.innerHTML = buildHTML();

    // Override default .page-view padding so mc-layout fills edge-to-edge
    el.style.padding    = '0';
    el.style.maxWidth   = 'none';
    el.style.marginLeft = '0';
    el.style.marginRight = '0';

    bindFilters();
    bindModal();
    renderAll(state);
  },

  onActivate(state) {
    renderAll(state);
  },
});
