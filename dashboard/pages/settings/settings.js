// ── DontPanic — Preferences Page Module ──
// UI-local preferences for this dashboard instance: appearance, refresh
// cadence, and read-only pointers to where state files live on disk.
//
// Single-user, local-first. This page never edits DontPanic config,
// secrets, or capability state — those live in `~/.dontpanic/` and are
// surfaced through the Tools & Setup page when capability-backed.

import { renderProvenanceFooterHTML } from '../../lib/provenance.js';
import {
  renderConfigInventoryHTML,
  resolveConfigInventory,
} from '../../lib/config-inventory-logic.js';

(() => {

  // ── Refresh interval options ──

  const REFRESH_OPTIONS = [
    { value: '10',  label: '10 seconds' },
    { value: '30',  label: '30 seconds' },
    { value: '60',  label: '1 minute'   },
    { value: '120', label: '2 minutes'  },
    { value: '300', label: '5 minutes'  },
  ];

  // ── Module state ──

  let _el = null;

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
  //
  // The `jarvis_*` storage keys are intentionally retained for cache
  // compatibility — older dashboards stored preferences under these
  // names. The key prefix never appears in user-visible copy.

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

        <!-- F013 config inventory — Settings/Setup cards rendered from the
             same F008 inventory the CLI \`dontpanic config inventory\` shows.
             Populated from state.configInventory; renders an honest empty
             state when the projection is absent. -->
        <div id="stg-config-inventory" class="stg-config-inventory"></div>

        <!-- Dashboard Preferences -->
        <section class="panel stg-section stg-config-section">
          <h2>Preferences</h2>
          <p class="stg-section-desc">
            How this dashboard behaves for you. These preferences live in
            your browser's localStorage only — they do not edit DontPanic
            configuration, secrets, or capability state. Anything under
            <code>~/.dontpanic/</code> is managed through
            <code>dontpanic</code> CLI commands surfaced in Tools &amp; Setup.
          </p>
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
                <span class="stg-field-hint">Written by <code>dontpanic dashboard build</code>; read-only in dashboard</span>
              </div>
            </div>

          </div>

          <div class="stg-save-row">
            <button class="stg-save-btn" id="stg-save-btn">Save preferences</button>
            <span class="stg-save-feedback" id="stg-save-feedback"></span>
          </div>

          <div class="stg-source-footer">
            Source: <code>localStorage</code> (this browser only) ·
            DontPanic config edits use the <code>dontpanic</code> CLI surfaced under Tools &amp; Setup.
          </div>
          ${renderProvenanceFooterHTML({
            source: 'localStorage (this browser only)',
            lastUpdated: null,
            note: 'Preferences are browser-local. DontPanic config edits live under ~/.dontpanic/ and are managed via the dontpanic CLI from Tools & Setup.',
          })}
        </section>

      </div>
    `;
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

  // ── Config inventory (F013) render ──
  //
  // Renders the F008 configuration inventory as Settings/Setup cards. The
  // effective inventory is resolved for the selected project: project and
  // fleet builds mirror each project's inventory under
  // `state/projects/<name>/config-inventory.json` (loaded into
  // `state.configInventoryByProject`), and the top-level
  // `state.config-inventory.json` (`state.configInventory`) is the single-repo
  // / focused fallback. Re-rendered on every state change so a fresh
  // `dashboard build`/`serve` (which rewrites the projection — including the
  // auto-detected dashboard hint) and a project-selector switch both surface
  // without a page reload.

  function renderConfigInventory(state) {
    const host = _el && _el.querySelector('#stg-config-inventory');
    if (!host) return;
    const resolved = resolveConfigInventory({
      selectedProject: state ? state.selectedProject : null,
      single: state ? state.configInventory : null,
      byProject: state ? state.configInventoryByProject : null,
    });
    host.innerHTML = renderConfigInventoryHTML(resolved);
  }

  // ── Page Registration ──

  Jarvis.registerPage({
    id: 'settings',
    label: 'Preferences',

    init(state) {
      _el = Jarvis.getPageEl('settings');
      if (!_el) return;

      _el.innerHTML = buildTemplate();
      setupConfigForm();
      renderConfigInventory(state);

      // Apply saved theme on load
      applyTheme(getTheme());
    },

    onActivate(state) {
      // Preferences chrome is UI-local, but the config inventory is
      // server-state — re-render it so build/serve refreshes surface.
      renderConfigInventory(state);
    },
  });
})();
