// ── Mission Control Page — Jarvis Dashboard ──
// Kanban-style project management with agent sidebar and live feed.
// Reads from Jarvis.state.tasks, .agents, .activity — no Firestore dependency.

import {
  MC_COLUMNS,
  MC_COLUMN_META,
  STATUS_TO_COLUMN,
  PROJECT_NAMES,
  AGENT_META,
  getAgentMeta,
  deriveColumn,
  resolveDragIntent,
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

      <!-- ── Mission Queue (Center) ── -->
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

    // Bind card click → modal; drag start → carry task id + source column.
    container.querySelectorAll('.mc-card').forEach(card => {
      card.addEventListener('click', () => openTaskModal(card.dataset.taskId));
      card.addEventListener('dragstart', (ev) => {
        if (!ev.dataTransfer) return;
        ev.dataTransfer.effectAllowed = 'move';
        ev.dataTransfer.setData('text/plain', JSON.stringify({
          taskId: card.dataset.taskId,
          sourceColumn: card.dataset.currentColumn,
        }));
      });
    });

    bindColumnDropTarget(container, col);
  });
}

function bindColumnDropTarget(container, targetColumn) {
  // dragover: must preventDefault so the drop event fires.
  container.addEventListener('dragover', (ev) => {
    ev.preventDefault();
    if (ev.dataTransfer) ev.dataTransfer.dropEffect = 'move';
  });
  container.addEventListener('drop', async (ev) => {
    ev.preventDefault();
    let payload;
    try {
      payload = JSON.parse(ev.dataTransfer?.getData('text/plain') || '{}');
    } catch {
      return;
    }
    const { taskId, sourceColumn } = payload;
    const intent = resolveDragIntent({ taskId, sourceColumn, targetColumn });
    if (intent.action === 'noop') return;
    if (intent.action === 'reject-local') {
      reportRealtimeError('kanbanMove', { code: intent.code, message: intent.message });
      return;
    }
    if (intent.action !== 'invoke') return;
    const actions = getRealtimeActions();
    if (!actions) {
      reportRealtimeError('kanbanMove', {
        code: 'realtime-actions-unavailable',
        message:
          'Realtime actions are not configured — load index-firebase.html with Firebase + Cloud Functions configured to enable kanban drag flips.',
      });
      return;
    }
    const result = await actions.kanbanMove({
      planId: intent.planId,
      currentColumn: intent.currentColumn,
      newColumn: intent.newColumn,
    });
    if (!result.ok) {
      reportRealtimeError('kanbanMove', result);
    }
  });
}

function getRealtimeActions() {
  if (typeof window === 'undefined') return null;
  const jarvis = window.Jarvis;
  return (jarvis && jarvis.realtimeActions) || null;
}

function reportRealtimeError(action, result) {
  if (typeof console !== 'undefined') {
    console.warn(`[Jarvis mission-control] ${action} failed:`, result);
  }
  if (typeof window === 'undefined') return;
  const jarvis = window.Jarvis;
  if (jarvis && typeof jarvis.setSyncStatus === 'function') {
    jarvis.setSyncStatus('error', `${action}: ${result.code || 'error'}`);
  }
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

  // draggable=true exposes HTML5 DnD; the drop handler resolves the
  // landed column and fires the kanbanMove callable (plan F003 audit-i1).
  return `
    <div class="mc-card" data-task-id="${esc(task.id)}" data-current-column="${esc(currentColumn)}" draggable="true">
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
    </div>
    <div class="mc-modal-actions" data-task-id="${esc(task.id)}">
      <button class="mc-action-btn mc-action-btn--dispatch" data-action="dispatch" data-feature-id="F001">
        Dispatch F001
      </button>
      <button class="mc-action-btn mc-action-btn--approve" data-action="approve" data-gate-name="pre_merge">
        Approve pre_merge gate
      </button>
      <div class="mc-action-status" data-action-status></div>
    </div>`;

  modal.classList.remove('hidden');
  modal.querySelector('.mc-modal-close').focus();
  bindModalActionButtons(task.id);
}

function bindModalActionButtons(planId) {
  const root = document.querySelector('.mc-modal-actions');
  if (!root) return;
  const statusEl = root.querySelector('[data-action-status]');
  root.querySelectorAll('.mc-action-btn').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const actions = getRealtimeActions();
      if (!actions) {
        if (statusEl) {
          statusEl.textContent =
            'Realtime actions unavailable — open index-firebase.html with Firebase configured to enable mutations.';
        }
        return;
      }
      btn.disabled = true;
      if (statusEl) statusEl.textContent = `${btn.dataset.action}…`;
      let result;
      try {
        if (btn.dataset.action === 'dispatch') {
          result = await actions.triggerDispatch({
            planId,
            featureId: btn.dataset.featureId || 'F001',
          });
        } else if (btn.dataset.action === 'approve') {
          result = await actions.approveGate({
            planId,
            gateName: btn.dataset.gateName || 'pre_merge',
          });
        } else {
          result = { ok: false, code: 'unknown-action', message: `unknown action ${btn.dataset.action}` };
        }
      } finally {
        btn.disabled = false;
      }
      if (statusEl) {
        statusEl.textContent = result.ok
          ? `${btn.dataset.action} ok`
          : `${btn.dataset.action} failed: ${result.code} — ${result.message}`;
      }
      if (!result.ok) reportRealtimeError(btn.dataset.action, result);
    });
  });
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
  label: 'Mission Control',

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
