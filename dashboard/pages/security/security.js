// ── JARVIS — Security Page Module ──
// Renders: Security Overview stats, Decision Audit Log (tabbed),
// Agent Security Profile (table + stacked bar chart), and Hook Activity.
//
// Data source: Jarvis.state.security — array of:
//   { action, category, agent, timestamp, details, severity }
//
// Actions:  "block" | "require_approval" | "log" | "allow"
// Severity: "high" | "medium" | "low"
//
// No approval queue — single-user system; approvals happen in terminal.

(() => {
  // ── Constants ──

  const ACTION_COLORS = {
    block:            'red',
    require_approval: 'yellow',
    log:              'accent',
    allow:            'green',
  };

  const ACTION_LABELS = {
    block:            'BLOCK',
    require_approval: 'APPROVAL',
    log:              'LOG',
    allow:            'ALLOW',
  };

  const SEVERITY_COLORS = {
    high:   'red',
    medium: 'yellow',
    low:    'accent',
  };

  // Known Claude hooks that appear in state entries as agent/category fields
  const HOOK_DEFS = [
    {
      id:          'security-gate',
      label:       'security-gate.sh',
      description: 'Pre-tool call gate — blocks destructive operations',
      categories:  ['file_write', 'file_delete', 'shell_exec'],
    },
    {
      id:          'git-safety',
      label:       'git-safety.sh',
      description: 'Git operation guard — prevents force-push, branch deletion',
      categories:  ['git_push', 'git_branch', 'git_rebase'],
    },
    {
      id:          'api-audit',
      label:       'api-audit.sh',
      description: 'Outbound API call auditor — logs external requests',
      categories:  ['api_call', 'network_request'],
    },
  ];

  // ── Module state ──

  let _el           = null;
  let _activeFilter = 'all';
  let _decisions    = [];
  let _agentChart   = null;

  // ── Utilities ──

  function esc(str) {
    if (str == null) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function emptyState(msg) {
    return `<div class="empty-state">
      <div class="empty-icon">&#9675;</div>
      <div class="empty-text">${esc(msg)}</div>
    </div>`;
  }

  // ── Page Template ──

  function buildTemplate() {
    return `
      <div class="sec-layout">

        <!-- Security Overview Stats -->
        <section class="panel sec-stats-panel">
          <h2>Security Overview</h2>
          <div class="sec-stats-grid" id="sec-stats-grid"></div>
        </section>

        <!-- Hook Activity -->
        <section class="panel sec-hooks-panel">
          <h2>Hook Activity</h2>
          <div class="sec-hooks-list" id="sec-hooks-list"></div>
        </section>

        <!-- Decision Audit Log (full width) -->
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

        <!-- Agent Security Profile (full width) -->
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

  // ── Render: Stats ──

  function renderStats(decisions) {
    const grid = _el.querySelector('#sec-stats-grid');
    if (!grid) return;

    const total     = decisions.length;
    const blocks    = decisions.filter(d => d.action === 'block').length;
    const approvals = decisions.filter(d => d.action === 'require_approval').length;
    const logged    = decisions.filter(d => d.action === 'log').length;

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

  // ── Render: Hook Activity ──

  function renderHookActivity(decisions) {
    const list = _el.querySelector('#sec-hooks-list');
    if (!list) return;

    list.innerHTML = HOOK_DEFS.map(hook => {
      // Count decisions whose category matches this hook's known categories
      const fired = decisions.filter(d =>
        hook.categories.includes(d.category)
      );
      const count     = fired.length;
      const lastFired = fired.reduce((latest, d) => {
        if (!d.timestamp) return latest;
        return (!latest || d.timestamp > latest) ? d.timestamp : latest;
      }, null);
      const blocks = fired.filter(d => d.action === 'block').length;

      const statusClass  = count > 0 ? 'sec-hook--active' : 'sec-hook--idle';
      const statusLabel  = count > 0 ? 'active' : 'idle';
      const statusColor  = count > 0 ? 'green'  : 'muted';

      return `
        <div class="sec-hook-row ${statusClass}">
          <div class="sec-hook-dot sec-hook-dot--${statusColor}"></div>
          <div class="sec-hook-info">
            <div class="sec-hook-name">${esc(hook.label)}</div>
            <div class="sec-hook-desc">${esc(hook.description)}</div>
          </div>
          <div class="sec-hook-stats">
            <span class="sec-hook-stat sec-hook-stat--count">${count} fired</span>
            ${blocks > 0 ? `<span class="sec-hook-stat sec-hook-stat--blocks">${blocks} blocked</span>` : ''}
            <span class="sec-hook-stat sec-hook-stat--time">${lastFired ? Jarvis.timeAgo(lastFired) : 'never'}</span>
          </div>
          <span class="sec-hook-badge sec-hook-badge--${statusColor}">${statusLabel}</span>
        </div>
      `;
    }).join('');
  }

  // ── Render: Decision Audit Log ──

  function renderDecisionLog(decisions) {
    const list = _el.querySelector('#sec-decision-list');
    if (!list) return;

    let filtered = decisions;
    if (_activeFilter !== 'all') {
      filtered = decisions.filter(d => d.action === _activeFilter);
    }

    // Update tab counts
    updateTabCounts(decisions);

    if (!filtered.length) {
      list.innerHTML = emptyState('No decisions recorded');
      return;
    }

    // Sort newest first
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
              <span>&#8226; ${Jarvis.timeAgo(d.timestamp)}</span>
              ${d.severity ? `<span class="sec-sev-chip sec-sev-chip--${sevColor}">${esc(d.severity)}</span>` : ''}
            </div>
          </div>
        </div>
      `;
    }).join('');
  }

  function updateTabCounts(decisions) {
    const tabs = _el.querySelector('#sec-decision-tabs');
    if (!tabs) return;

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
      // Preserve existing label text, append count badge
      const baseLabel = ACTION_LABELS[filter] || (filter === 'all' ? 'All' : esc(filter));
      tab.innerHTML = `${baseLabel} <span class="sec-tab-count">${count}</span>`;
    });
  }

  // ── Render: Agent Security Table ──

  function renderAgentTable(decisions) {
    const table = _el.querySelector('#sec-agent-table');
    if (!table) return;

    // Aggregate per-agent
    const agents = {};
    for (const d of decisions) {
      const name = d.agent || 'unknown';
      if (!agents[name]) {
        agents[name] = { total: 0, blocks: 0, approvals: 0, logged: 0, allowed: 0, last: null };
      }
      agents[name].total++;
      if (d.action === 'block')            agents[name].blocks++;
      else if (d.action === 'require_approval') agents[name].approvals++;
      else if (d.action === 'log')         agents[name].logged++;
      else if (d.action === 'allow')       agents[name].allowed++;
      if (d.timestamp && (!agents[name].last || d.timestamp > agents[name].last)) {
        agents[name].last = d.timestamp;
      }
    }

    const agentNames = Object.keys(agents).sort();

    if (!agentNames.length) {
      table.innerHTML = emptyState('No agent data');
      return;
    }

    table.innerHTML = `
      <div class="sec-table-header">
        <div>Agent</div>
        <div>Total</div>
        <div>Blocks</div>
        <div>Approvals</div>
        <div>Logged</div>
        <div>Last Event</div>
      </div>
      ${agentNames.map(name => {
        const a = agents[name];
        return `
          <div class="sec-table-row">
            <div class="sec-td--agent">${esc(name)}</div>
            <div>${a.total}</div>
            <div class="sec-td--red">${a.blocks}</div>
            <div class="sec-td--yellow">${a.approvals}</div>
            <div class="sec-td--accent">${a.logged}</div>
            <div class="sec-td--muted">${Jarvis.timeAgo(a.last)}</div>
          </div>
        `;
      }).join('')}
    `;
  }

  // ── Render: Agent Chart ──

  function renderAgentChart(decisions) {
    const canvas = _el.querySelector('#sec-agent-chart');
    if (!canvas) return;

    // Aggregate per-agent
    const agents = {};
    for (const d of decisions) {
      const name = d.agent || 'unknown';
      if (!agents[name]) agents[name] = { blocks: 0, approvals: 0, logged: 0 };
      if (d.action === 'block')            agents[name].blocks++;
      else if (d.action === 'require_approval') agents[name].approvals++;
      else if (d.action === 'log')         agents[name].logged++;
    }

    const names = Object.keys(agents).sort();

    if (_agentChart) {
      _agentChart.destroy();
      _agentChart = null;
    }

    if (!names.length) return;

    _agentChart = new Chart(canvas, {
      type: 'bar',
      data: {
        labels: names,
        datasets: [
          {
            label: 'Blocks',
            data: names.map(n => agents[n].blocks),
            backgroundColor: 'rgba(239, 68, 68, 0.7)',
            borderColor: '#ef4444',
            borderWidth: 1,
            borderRadius: 4,
          },
          {
            label: 'Approvals',
            data: names.map(n => agents[n].approvals),
            backgroundColor: 'rgba(234, 179, 8, 0.7)',
            borderColor: '#eab308',
            borderWidth: 1,
            borderRadius: 4,
          },
          {
            label: 'Logged',
            data: names.map(n => agents[n].logged),
            backgroundColor: 'rgba(59, 130, 246, 0.7)',
            borderColor: '#3b82f6',
            borderWidth: 1,
            borderRadius: 4,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 400 },
        scales: {
          x: {
            stacked: true,
            ticks: { color: '#64748b', font: { size: 10 } },
            grid:  { color: 'rgba(42, 58, 78, 0.5)' },
          },
          y: {
            stacked: true,
            ticks: { color: '#64748b', font: { size: 10 }, stepSize: 1 },
            grid:  { color: 'rgba(42, 58, 78, 0.5)' },
            beginAtZero: true,
          },
        },
        plugins: {
          legend: {
            display: true,
            labels: { color: '#94a3b8', font: { size: 10 }, boxWidth: 12 },
          },
          title: {
            display: true,
            text: 'Decisions by Agent',
            color: '#94a3b8',
            font: { size: 11 },
            padding: { bottom: 8 },
          },
        },
      },
    });
  }

  // ── Tab wiring ──

  function setupTabs() {
    _el.querySelector('#sec-decision-tabs').addEventListener('click', e => {
      const tab = e.target.closest('.sec-tab');
      if (!tab) return;

      _el.querySelectorAll('.sec-tab').forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      _activeFilter = tab.dataset.filter;
      renderDecisionLog(_decisions);
    });
  }

  // ── Full render pass ──

  function renderAll(state) {
    _decisions = state.security || [];
    renderStats(_decisions);
    renderHookActivity(_decisions);
    renderDecisionLog(_decisions);
    renderAgentTable(_decisions);
    renderAgentChart(_decisions);
  }

  // ── Jarvis Page Registration ──

  Jarvis.registerPage({
    id: 'security',
    label: 'Security',

    init(state) {
      _el = Jarvis.getPageEl('security');
      if (!_el) return;

      _el.innerHTML = buildTemplate();
      setupTabs();
      renderAll(state);
    },

    onActivate(state) {
      if (!_el) return;
      // Re-render chart on activate — canvas may have been hidden
      renderAll(state);
    },

    onDeactivate() {
      if (_agentChart) {
        _agentChart.destroy();
        _agentChart = null;
      }
    },
  });
})();
