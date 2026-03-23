// ── JARVIS — Command Center Page Module ──
// Renders: Agent Status grid, Token Budget meters, Task Queue (tabbed),
// Activity Feed, and Metrics Charts (Chart.js).
// Registers itself into the Jarvis core router — no direct DOM access
// outside of Jarvis.getPageEl('command-center').

(() => {
  // ── Agent metadata for Jarvis harnesses ──
  const AGENT_META = {
    claude:  { initials: 'CC', color: '#3b82f6', badge: 'LEAD' },
    codex:   { initials: 'CX', color: '#22c55e', badge: 'OAI'  },
    gemini:  { initials: 'GM', color: '#f97316', badge: 'GGL'  },
    grok:    { initials: 'GK', color: '#a855f7', badge: 'XAI'  },
    kimi:    { initials: 'KM', color: '#eab308', badge: 'MSH'  },
    qwen:    { initials: 'QW', color: '#ef4444', badge: 'ALI'  },
  };

  function getAgentMeta(id) {
    return AGENT_META[id] || {
      initials: (id || '??').slice(0, 2).toUpperCase(),
      color: '#64748b',
      badge: 'AGT',
    };
  }

  // ── HTML escaping ──
  function esc(str) {
    if (str == null) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  // ── Empty state helper ──
  function emptyState(msg) {
    return `<div class="empty-state">
      <div class="empty-icon">&#9675;</div>
      <div class="empty-text">${esc(msg)}</div>
    </div>`;
  }

  // ── Activity type → icon ──
  function activityIcon(type) {
    const icons = {
      task:   '&#10003;',
      deploy: '&#8593;',
      alert:  '&#9888;',
      sync:   '&#8635;',
      info:   '&#8505;',
    };
    return icons[type] || icons.info;
  }

  // ── Demo timeseries for charts when no metric data exists ──
  function generateDemoTimeseries() {
    const points = [];
    const now = new Date();
    for (let i = 13; i >= 0; i--) {
      const d = new Date(now);
      d.setDate(d.getDate() - i);
      points.push({
        date: d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }),
        actions: Math.floor(Math.random() * 40 + 5),
        tokensUsed: Math.floor(Math.random() * 80000 + 10000),
      });
    }
    return points;
  }

  // ── Module-scoped state ──
  let _el = null;
  let _activeTab = 'in_progress';
  let _allTasks = [];
  let _activityChart = null;
  let _tokensChart = null;

  // ── Page HTML template ──
  function buildTemplate() {
    return `
      <div class="cc-layout">

        <!-- Row 1: Agent Status + Token Budget -->
        <div class="grid-2col">

          <!-- Agent Status -->
          <div class="panel">
            <h2>Agent Status</h2>
            <div class="cc-agents-grid" id="cc-agents-grid"></div>
          </div>

          <!-- Token Budget -->
          <div class="panel">
            <h2>Token Budget</h2>
            <div id="cc-token-budget"></div>
          </div>

        </div>

        <!-- Row 2: Task Queue + Activity Feed -->
        <div class="grid-2col">

          <!-- Task Queue -->
          <div class="panel">
            <h2>Task Queue</h2>
            <div class="task-tabs">
              <button class="tab" data-tab="pending">
                Pending <span class="count" id="cc-pending-count">0</span>
              </button>
              <button class="tab active" data-tab="in_progress">
                In Progress <span class="count" id="cc-progress-count">0</span>
              </button>
              <button class="tab" data-tab="completed">
                Done <span class="count" id="cc-done-count">0</span>
              </button>
            </div>
            <div class="task-list" id="cc-task-list"></div>
          </div>

          <!-- Activity Feed -->
          <div class="panel">
            <h2>Activity Feed</h2>
            <div class="activity-feed" id="cc-activity-feed"></div>
          </div>

        </div>

        <!-- Row 3: Metrics Charts (full width) -->
        <div class="panel grid-full">
          <h2>Metrics</h2>
          <div class="charts-grid">
            <div class="chart-container">
              <canvas id="cc-activity-chart"></canvas>
            </div>
            <div class="chart-container">
              <canvas id="cc-tokens-chart"></canvas>
            </div>
          </div>
        </div>

      </div>
    `;
  }

  // ── Render: Agent Status Grid ──
  function renderAgents(agents) {
    const grid = _el.querySelector('#cc-agents-grid');
    if (!grid) return;

    if (!agents || !agents.length) {
      grid.innerHTML = emptyState('No agents reporting');
      return;
    }

    grid.innerHTML = agents.map(a => {
      const meta = getAgentMeta(a.id);
      const tokenPct = a.tokenBudget
        ? Math.min(Math.round((a.tokensUsed / a.tokenBudget) * 100), 100)
        : 0;
      const tokenColor = tokenPct > 90 ? 'red' : tokenPct > 70 ? 'yellow' : 'accent';
      return `
        <div class="agent-card">
          <div class="cc-agent-header">
            <div class="cc-agent-avatar" style="--agent-color: ${meta.color}">
              ${meta.initials}
            </div>
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
              <span>${Jarvis.formatNumber(a.tokensUsed || 0)} tokens used</span>
              <span>${tokenPct}%</span>
            </div>
          </div>` : ''}
          ${a.lastSeen ? `<div class="cc-agent-last-seen">Last seen ${Jarvis.timeAgo(a.lastSeen)}</div>` : ''}
        </div>
      `;
    }).join('');
  }

  // ── Render: Token Budget Meters ──
  function renderTokenBudget(agents) {
    const container = _el.querySelector('#cc-token-budget');
    if (!container) return;

    // Aggregate across all agents
    const totalUsed = agents.reduce((sum, a) => sum + (a.tokensUsed || 0), 0);
    const totalBudget = agents.reduce((sum, a) => sum + (a.tokenBudget || 0), 0);

    if (!totalBudget) {
      container.innerHTML = emptyState('No token budget configured');
      return;
    }

    // Per-agent meters
    const agentMeters = agents
      .filter(a => a.tokenBudget)
      .map(a => {
        const pct = Math.min(Math.round(((a.tokensUsed || 0) / a.tokenBudget) * 100), 100);
        const colorClass = pct > 90 ? 'red' : pct > 70 ? 'yellow' : 'accent';
        return `
          <div class="token-meter">
            <div class="meter-header">
              <span class="meter-label">${esc(a.name || a.id)}</span>
              <span class="meter-value">${Jarvis.formatNumber(a.tokensUsed || 0)} / ${Jarvis.formatNumber(a.tokenBudget)}</span>
            </div>
            <div class="meter-bar">
              <div class="meter-fill ${colorClass}" style="width: ${pct}%"></div>
            </div>
          </div>
        `;
      }).join('');

    // Summary row
    const totalPct = Math.min(Math.round((totalUsed / totalBudget) * 100), 100);
    const summaryHtml = `
      <div class="token-summary">
        <div class="token-stat">
          <div class="stat-value">${Jarvis.formatNumber(totalUsed)}</div>
          <div class="stat-label">Total Used</div>
        </div>
        <div class="token-stat">
          <div class="stat-value">${Jarvis.formatNumber(totalBudget)}</div>
          <div class="stat-label">Total Budget</div>
        </div>
        <div class="token-stat">
          <div class="stat-value">${totalPct}%</div>
          <div class="stat-label">Utilization</div>
        </div>
      </div>
    `;

    container.innerHTML = agentMeters + summaryHtml;
  }

  // ── Render: Task Queue ──
  function renderTasks(tasks) {
    _allTasks = tasks || [];
    updateTaskCounts();
    renderFilteredTasks();
  }

  // Normalize status: 'todo' is treated as 'pending' for display purposes.
  function normalizeStatus(status) {
    if (status === 'todo') return 'pending';
    return status || 'pending';
  }

  function updateTaskCounts() {
    const pending  = _el.querySelector('#cc-pending-count');
    const progress = _el.querySelector('#cc-progress-count');
    const done     = _el.querySelector('#cc-done-count');
    if (pending)  pending.textContent  = _allTasks.filter(t => normalizeStatus(t.status) === 'pending').length;
    if (progress) progress.textContent = _allTasks.filter(t => normalizeStatus(t.status) === 'in_progress').length;
    if (done)     done.textContent     = _allTasks.filter(t => normalizeStatus(t.status) === 'completed').length;
  }

  function renderFilteredTasks() {
    const list = _el.querySelector('#cc-task-list');
    if (!list) return;

    const filtered = _allTasks.filter(t => normalizeStatus(t.status) === _activeTab);
    if (!filtered.length) {
      const label = _activeTab.replace('_', ' ');
      list.innerHTML = emptyState(`No ${label} tasks`);
      return;
    }

    list.innerHTML = filtered.map(t => {
      const agent = t.agent ? getAgentMeta(t.agent) : null;
      return `
        <div class="task-item">
          <div class="task-priority ${esc(t.priority || 'medium')}"></div>
          <div class="task-title">${esc(t.title || t.id)}</div>
          ${t.project ? `<span class="task-project">${esc(t.project)}</span>` : ''}
          ${t.agent ? `<span class="task-agent">${esc(t.agent)}</span>` : ''}
        </div>
      `;
    }).join('');
  }

  // ── Render: Activity Feed ──
  function renderActivity(items) {
    const feed = _el.querySelector('#cc-activity-feed');
    if (!feed) return;

    if (!items || !items.length) {
      feed.innerHTML = emptyState('No activity yet');
      return;
    }

    feed.innerHTML = items.map(a => {
      const icon = activityIcon(a.type);
      return `
        <div class="activity-item">
          <div class="activity-icon ${esc(a.type || 'info')}">${icon}</div>
          <div class="activity-text">
            <strong>${esc(a.agent || 'System')}</strong> ${esc(a.text || '')}
          </div>
          <div class="activity-time">${Jarvis.timeAgo(a.timestamp)}</div>
        </div>
      `;
    }).join('');
  }

  // ── Render: Charts ──
  const CHART_DEFAULTS = {
    responsive: true,
    maintainAspectRatio: false,
    animation: { duration: 400 },
    scales: {
      x: {
        ticks: { color: '#64748b', font: { size: 10, family: 'inherit' } },
        grid: { color: 'rgba(42, 58, 78, 0.6)' },
      },
      y: {
        ticks: { color: '#64748b', font: { size: 10, family: 'inherit' } },
        grid: { color: 'rgba(42, 58, 78, 0.6)' },
        beginAtZero: true,
      },
    },
    plugins: {
      legend: { display: false },
    },
  };

  function renderCharts(state) {
    // Build metric points from activity timestamps or fall back to demo data
    let points = buildMetricPoints(state);
    if (!points.length) {
      points = generateDemoTimeseries();
    }

    const labels      = points.map(p => p.date);
    const activityData = points.map(p => p.actions);
    const tokenData    = points.map(p => p.tokensUsed);

    // Activity (bar)
    destroyChart('_activityChart');
    const actCanvas = _el.querySelector('#cc-activity-chart');
    if (actCanvas) {
      _activityChart = new Chart(actCanvas, {
        type: 'bar',
        data: {
          labels,
          datasets: [{
            label: 'Actions',
            data: activityData,
            backgroundColor: 'rgba(59, 130, 246, 0.55)',
            borderColor: '#3b82f6',
            borderWidth: 1,
            borderRadius: 4,
          }],
        },
        options: {
          ...CHART_DEFAULTS,
          plugins: {
            ...CHART_DEFAULTS.plugins,
            title: {
              display: true,
              text: 'Daily Actions',
              color: '#94a3b8',
              font: { size: 11 },
              padding: { bottom: 8 },
            },
          },
        },
      });
    }

    // Tokens (line)
    destroyChart('_tokensChart');
    const tokCanvas = _el.querySelector('#cc-tokens-chart');
    if (tokCanvas) {
      _tokensChart = new Chart(tokCanvas, {
        type: 'line',
        data: {
          labels,
          datasets: [{
            label: 'Tokens',
            data: tokenData,
            borderColor: '#a855f7',
            backgroundColor: 'rgba(168, 85, 247, 0.1)',
            fill: true,
            tension: 0.3,
            pointRadius: 3,
            pointBackgroundColor: '#a855f7',
            borderWidth: 2,
          }],
        },
        options: {
          ...CHART_DEFAULTS,
          plugins: {
            ...CHART_DEFAULTS.plugins,
            title: {
              display: true,
              text: 'Daily Token Usage',
              color: '#94a3b8',
              font: { size: 11 },
              padding: { bottom: 8 },
            },
          },
        },
      });
    }
  }

  function destroyChart(name) {
    if (name === '_activityChart' && _activityChart) {
      _activityChart.destroy();
      _activityChart = null;
    }
    if (name === '_tokensChart' && _tokensChart) {
      _tokensChart.destroy();
      _tokensChart = null;
    }
  }

  // Build per-day metric points from agent token usage and activity events.
  // This is additive — agents write their own tokens into state.agents.
  function buildMetricPoints(state) {
    const agents   = state.agents   || [];
    const activity = state.activity || [];

    if (!activity.length) return [];

    // Bucket activity events by calendar date
    const buckets = {};
    for (const item of activity) {
      if (!item.timestamp) continue;
      const d = new Date(item.timestamp).toLocaleDateString('en-US', {
        month: 'short', day: 'numeric',
      });
      if (!buckets[d]) buckets[d] = { date: d, actions: 0, tokensUsed: 0 };
      buckets[d].actions++;
    }

    // Spread agent token totals evenly across available dates as a heuristic;
    // when agents push per-session token data this can be replaced.
    const dates = Object.keys(buckets);
    if (dates.length > 0) {
      const totalTokens = agents.reduce((s, a) => s + (a.tokensUsed || 0), 0);
      const tokensPerDay = dates.length ? Math.floor(totalTokens / dates.length) : 0;
      for (const d of dates) {
        buckets[d].tokensUsed = tokensPerDay;
      }
    }

    return Object.values(buckets).sort((a, b) => new Date(a.date) - new Date(b.date));
  }

  // ── Tab wiring ──
  function setupTabs() {
    _el.querySelectorAll('.task-tabs .tab').forEach(tab => {
      tab.addEventListener('click', () => {
        _el.querySelectorAll('.task-tabs .tab').forEach(t => t.classList.remove('active'));
        tab.classList.add('active');
        _activeTab = tab.dataset.tab;
        renderFilteredTasks();
      });
    });
  }

  // ── Full render pass ──
  function renderAll(state) {
    renderAgents(state.agents || []);
    renderTokenBudget(state.agents || []);
    renderTasks(state.tasks || []);
    renderActivity(state.activity || []);
    renderCharts(state);
  }

  // ══════════════════════════════════════════════
  // ── Jarvis Page Registration ──
  // ══════════════════════════════════════════════

  Jarvis.registerPage({
    id: 'command-center',
    label: 'Command Center',

    init(state) {
      _el = Jarvis.getPageEl('command-center');
      if (!_el) return;

      _el.innerHTML = buildTemplate();
      setupTabs();
      renderAll(state);
    },

    onActivate(state) {
      if (!_el) return;
      renderAll(state);
    },

    onDeactivate() {
      destroyChart('_activityChart');
      destroyChart('_tokensChart');
    },
  });
})();
