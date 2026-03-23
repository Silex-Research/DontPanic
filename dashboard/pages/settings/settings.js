// ── JARVIS — Settings Page Module ──
// Renders: Harness Sync Status, Active Projects, Dashboard Config.
//
// Single-user, local-first. No team management, no channel tokens.
// Harness sync reflects what `sync.sh status` would report by comparing
// known harness IDs against agents present in state.agents.

import { HARNESSES, deriveSyncStatus } from '../../lib/settings-logic.js';

(() => {

  // ── Active projects ──

  const PROJECTS = [
    {
      id:    'styln',
      label: 'Styln (Glam)',
      path:  '~/Documents/GitHub/Glam',
      stack: 'Swift / iOS',
      color: '#a855f7',
    },
    {
      id:    'spindine',
      label: 'SpinDine',
      path:  '~/Documents/GitHub/SpinDine',
      stack: 'TypeScript / Next.js',
      color: '#f97316',
    },
    {
      id:    'quantre',
      label: 'QuantRE',
      path:  '~/Documents/GitHub/QuantRE',
      stack: 'Python / FastAPI',
      color: '#22c55e',
    },
    {
      id:    'axiom',
      label: 'Axiom',
      path:  '~/Documents/GitHub/axiom-workspace',
      stack: 'Node.js / Firebase',
      color: '#3b82f6',
    },
    {
      id:    'jarvis',
      label: 'Jarvis',
      path:  '~/Documents/GitHub/Jarvis',
      stack: 'HTML / JS / Shell',
      color: '#eab308',
    },
  ];

  // ── Refresh interval options ──

  const REFRESH_OPTIONS = [
    { value: '10',  label: '10 seconds' },
    { value: '30',  label: '30 seconds' },
    { value: '60',  label: '1 minute'   },
    { value: '120', label: '2 minutes'  },
    { value: '300', label: '5 minutes'  },
  ];

  // ── Module state ──

  let _el    = null;
  let _state = null;

  // ── Utilities ──

  function esc(str) {
    if (str == null) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  // ── localStorage helpers ──

  function getTheme() {
    return localStorage.getItem('jarvis_theme') || 'dark';
  }

  function setTheme(theme) {
    localStorage.setItem('jarvis_theme', theme);
    applyTheme(theme);
  }

  function applyTheme(theme) {
    document.documentElement.dataset.theme = theme;
  }

  function getRefreshInterval() {
    return localStorage.getItem('jarvis_refresh_interval') || '30';
  }

  function setRefreshInterval(seconds) {
    localStorage.setItem('jarvis_refresh_interval', seconds);
    // Notify core if it exposes a way to update the interval.
    // For now we store the preference; core reads it on next boot.
  }

  // ── Page Template ──

  function buildTemplate() {
    const currentTheme    = getTheme();
    const currentInterval = getRefreshInterval();

    return `
      <div class="stg-layout">

        <!-- Harness Sync Status -->
        <section class="panel stg-section">
          <h2>Harness Sync Status</h2>
          <p class="stg-section-desc">
            Shows whether each agent harness config is present and tracked in state.
            Run <code>sync.sh status</code> in the Jarvis repo to force a refresh.
          </p>
          <div class="stg-harness-list" id="stg-harness-list"></div>
        </section>

        <!-- Active Projects -->
        <section class="panel stg-section">
          <h2>Active Projects</h2>
          <p class="stg-section-desc">Projects managed through the Jarvis harness.</p>
          <div class="stg-project-list" id="stg-project-list">
            ${PROJECTS.map(p => `
              <div class="stg-project-row">
                <div class="stg-project-dot" style="background: ${esc(p.color)}"></div>
                <div class="stg-project-info">
                  <div class="stg-project-label">${esc(p.label)}</div>
                  <div class="stg-project-path">${esc(p.path)}</div>
                </div>
                <span class="stg-project-stack">${esc(p.stack)}</span>
              </div>
            `).join('')}
          </div>
        </section>

        <!-- Dashboard Config -->
        <section class="panel stg-section stg-config-section">
          <h2>Dashboard Config</h2>
          <div class="stg-config-form">

            <!-- Theme toggle -->
            <div class="stg-field">
              <label class="stg-label" for="stg-theme-select">Appearance</label>
              <div class="stg-field-right">
                <select class="stg-select" id="stg-theme-select">
                  <option value="dark"  ${currentTheme === 'dark'  ? 'selected' : ''}>Dark</option>
                  <option value="light" ${currentTheme === 'light' ? 'selected' : ''}>Light</option>
                </select>
                <span class="stg-field-hint">Stored in localStorage</span>
              </div>
            </div>

            <!-- Refresh interval -->
            <div class="stg-field">
              <label class="stg-label" for="stg-refresh-select">Auto-refresh</label>
              <div class="stg-field-right">
                <select class="stg-select" id="stg-refresh-select">
                  ${REFRESH_OPTIONS.map(opt => `
                    <option value="${esc(opt.value)}" ${currentInterval === opt.value ? 'selected' : ''}>
                      ${esc(opt.label)}
                    </option>
                  `).join('')}
                </select>
                <span class="stg-field-hint">Takes effect on next page load</span>
              </div>
            </div>

            <!-- State files location (read-only info) -->
            <div class="stg-field">
              <label class="stg-label">State files</label>
              <div class="stg-field-right">
                <code class="stg-code">dashboard/state/*.json</code>
                <span class="stg-field-hint">Written by Jarvis agents; read-only in dashboard</span>
              </div>
            </div>

          </div>

          <div class="stg-save-row">
            <button class="stg-save-btn" id="stg-save-btn">Save Config</button>
            <span class="stg-save-feedback" id="stg-save-feedback"></span>
          </div>
        </section>

      </div>
    `;
  }

  // ── Render: Harness Sync Status ──

  function renderHarnesses(agents) {
    const list = _el.querySelector('#stg-harness-list');
    if (!list) return;

    list.innerHTML = HARNESSES.map(h => {
      const status = deriveSyncStatus(h.id, agents);

      let syncStatus, syncLabel, syncColor;
      if (status === 'in-sync') {
        syncStatus = 'in-sync';
        syncLabel  = 'in sync';
        syncColor  = 'green';
      } else if (status === 'stale') {
        syncStatus = 'out-of-sync';
        syncLabel  = 'stale';
        syncColor  = 'yellow';
      } else {
        syncStatus = 'missing';
        syncLabel  = 'missing';
        syncColor  = 'red';
      }

      const agent      = agents ? agents.find(a => (a.id || '').toLowerCase() === h.id) : null;
      const lastSeenEl = agent && agent.lastSeen
        ? `<span class="stg-harness-lastseen">Last seen ${esc(Jarvis.timeAgo(agent.lastSeen))}</span>`
        : '';

      return `
        <div class="stg-harness-row stg-harness-row--${syncStatus}">
          <div class="stg-harness-dot stg-harness-dot--${syncColor}"></div>
          <div class="stg-harness-info">
            <div class="stg-harness-header">
              <span class="stg-harness-label">${esc(h.label)}</span>
              <span class="stg-harness-badge">${esc(h.badge)}</span>
            </div>
            <div class="stg-harness-desc">${esc(h.desc)}</div>
            <div class="stg-harness-path">${esc(h.path)}</div>
          </div>
          <div class="stg-harness-right">
            <span class="stg-sync-badge stg-sync-badge--${syncColor}">${esc(syncLabel)}</span>
            ${lastSeenEl}
          </div>
        </div>
      `;
    }).join('');
  }

  // ── Wire config form events ──

  function setupConfigForm() {
    const themeSelect   = _el.querySelector('#stg-theme-select');
    const refreshSelect = _el.querySelector('#stg-refresh-select');
    const saveBtn       = _el.querySelector('#stg-save-btn');
    const feedback      = _el.querySelector('#stg-save-feedback');

    if (themeSelect) {
      themeSelect.addEventListener('change', () => {
        applyTheme(themeSelect.value);
      });
    }

    if (saveBtn) {
      saveBtn.addEventListener('click', () => {
        const theme    = themeSelect   ? themeSelect.value   : getTheme();
        const interval = refreshSelect ? refreshSelect.value : getRefreshInterval();

        setTheme(theme);
        setRefreshInterval(interval);

        // Brief success feedback
        if (feedback) {
          feedback.textContent = 'Saved.';
          feedback.classList.add('stg-save-feedback--visible');
          setTimeout(() => {
            feedback.classList.remove('stg-save-feedback--visible');
          }, 2000);
        }
      });
    }
  }

  // ── Full render pass ──

  function renderAll(state) {
    _state = state;
    renderHarnesses(state.agents || []);
  }

  // ── Jarvis Page Registration ──

  Jarvis.registerPage({
    id: 'settings',
    label: 'Settings',

    init(state) {
      _el = Jarvis.getPageEl('settings');
      if (!_el) return;

      _el.innerHTML = buildTemplate();
      setupConfigForm();

      // Apply saved theme on load
      applyTheme(getTheme());

      renderAll(state);
    },

    onActivate(state) {
      if (!_el) return;
      renderAll(state);
    },
  });
})();
