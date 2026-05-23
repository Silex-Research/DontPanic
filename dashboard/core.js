// ── JARVIS Dashboard — Core Router & State Manager ──
// Local-first: reads state from JSON files, no Firebase dependency.
// Pages register themselves via Jarvis.registerPage().

import { timeAgo, formatCurrency, formatNumber } from './lib/formatters.js';
import {
  mergeSnapshotIntoState,
  mergePerStreamIntoState,
  PER_STREAM_FILES,
} from './lib/projection-adapter.js';
import {
  ALL_PROJECTS_VALUE,
  STORAGE_KEY as PROJECT_STORAGE_KEY,
  URL_PARAM as PROJECT_URL_PARAM,
  buildSelectionURL,
  getProjectOptions,
  normalizeFleetSummary,
  renderHeaderStripHTML,
  resolveSelection,
} from './lib/project-selector-logic.js';

/**
 * Construct a fresh Jarvis shell object. Exported so integration tests
 * can exercise the real loader / resolver / refresh logic without
 * triggering the page-module import chain or the window.Jarvis
 * assignment at the bottom of this file.
 */
export function createJarvis() {
  return JARVIS_LITERAL();
}

function JARVIS_LITERAL() { return {
  pages: [],
  currentPage: null,
  state: {
    agents: [],
    tasks: [],
    activity: [],
    costs: null,
    security: [],
    // `capabilities` stays null when capabilities-status.json is absent —
    // the Capability Center page uses null as the missing-state sentinel.
    capabilities: null,
    // Canonical F001 projection streams. Populated by the projection
    // adapter when `state-snapshot.json` is present in dashboard/state;
    // remain empty / null when only the legacy demo files exist.
    plans: [],
    gates: [],
    inbox: [],
    supervisors: [],
    quota: [],
    decisions: [],
    evidenceRefs: [],
    snapshotMeta: null,
    // F004 What Now cache (operator_console.render_envelope shape).
    // Stays null when `dashboard/state/what-now.json` is absent — the
    // page renders a non-alarming missing-cache state in that case.
    whatNow: null,
    // F003 fleet summary (plan 2026-05-23-005). Populated by the loader
    // when `dashboard/state/fleet-summary.json` is present; stays null
    // when only single-repo state is on disk. The shell renders an
    // actionable build command in the missing case.
    fleetSummary: null,
    // F003 currently-selected project name or the `all` sentinel. The
    // shell resolves this from URL → localStorage → default on init
    // and re-resolves whenever the selector is mutated.
    selectedProject: ALL_PROJECTS_VALUE,
  },

  // ── Page Registration ──
  // Each page module calls this to register itself
  registerPage(config) {
    // config: { id, label, init, onActivate?, onDeactivate? }
    this.pages.push(config);
  },

  // ── Bootstrap ──
  async init() {
    this.startClock();
    await this.loadState();
    this.resolveProjectSelection();
    this.buildNav();
    this.buildPageContainers();
    this.renderProjectSelector();

    // Initialize all pages
    for (const page of this.pages) {
      if (page.init) page.init(this.state);
    }

    // Route to hash or first page
    const hash = location.hash.slice(1);
    const target = this.pages.find(p => p.id === hash) || this.pages[0];
    if (target) this.switchTo(target.id);

    // Hash routing
    window.addEventListener('hashchange', () => {
      const h = location.hash.slice(1);
      if (this.pages.find(p => p.id === h)) {
        this.switchTo(h);
      }
    });

    this.setSyncStatus('online', 'Ready');
    this.updateLastSync();

    // Auto-refresh state every 30 seconds
    setInterval(() => this.refreshState(), 30000);
  },

  // ── F003 project selection ──
  // Resolve the selected project from URL → localStorage → default
  // and store it on `state.selectedProject`. The resolver also drops
  // stale selections that no longer match the served fleet summary,
  // so a renamed project does not strand the operator on a phantom
  // option (acceptance #6).
  resolveProjectSelection() {
    const envelope = normalizeFleetSummary(this.state.fleetSummary);
    const options = getProjectOptions(envelope);
    const urlValue = this._readSelectionFromURL();
    const storageValue = this._readSelectionFromStorage();
    const resolved = resolveSelection({ urlValue, storageValue, options });
    this.state.selectedProject = resolved.value;
    // Mirror the resolved value back into URL + localStorage so a
    // fresh-loaded page bookmarks the current selection even when the
    // operator never touched the selector.
    this._writeSelection(resolved.value, { writeUrl: resolved.source !== 'default' });
    return resolved;
  },

  setSelectedProject(value) {
    const envelope = normalizeFleetSummary(this.state.fleetSummary);
    const options = getProjectOptions(envelope);
    const valid = new Set(options.map((o) => o.value));
    const next = valid.has(value) ? value : ALL_PROJECTS_VALUE;
    this.state.selectedProject = next;
    this._writeSelection(next, { writeUrl: true });
    // The selector header carries its own scope badge, so changing the
    // selection must refresh both the active page and the selector chrome.
    this.renderProjectSelector();
    // Re-render the active page so scope-aware views can refresh.
    const active = this.pages.find(p => p.id === this.currentPage);
    if (active && active.onActivate) active.onActivate(this.state);
    return next;
  },

  renderProjectSelector() {
    const el = document.getElementById('project-selector-container');
    if (!el) return;
    const envelope = normalizeFleetSummary(this.state.fleetSummary);
    el.innerHTML = renderHeaderStripHTML({
      envelope,
      selected: this.state.selectedProject,
    });
    const select = el.querySelector('[data-project-selector="1"]');
    if (select) {
      select.addEventListener('change', (ev) => {
        const value = ev.target && typeof ev.target.value === 'string'
          ? ev.target.value
          : ALL_PROJECTS_VALUE;
        this.setSelectedProject(value);
      });
    }
  },

  _readSelectionFromURL() {
    try {
      const url = new URL(window.location.href);
      const v = url.searchParams.get(PROJECT_URL_PARAM);
      return typeof v === 'string' && v.length > 0 ? v : null;
    } catch {
      return null;
    }
  },

  _readSelectionFromStorage() {
    try {
      const v = window.localStorage.getItem(PROJECT_STORAGE_KEY);
      return typeof v === 'string' && v.length > 0 ? v : null;
    } catch {
      return null;
    }
  },

  _writeSelection(value, { writeUrl }) {
    try {
      window.localStorage.setItem(PROJECT_STORAGE_KEY, value);
    } catch {
      // Private mode / quota exhaustion: storage fallback is best-effort.
    }
    if (writeUrl) {
      try {
        const next = buildSelectionURL(window.location.href, value);
        window.history.replaceState(null, '', next);
      } catch {
        // history.replaceState is unavailable in some embeddings — the
        // selector still works through localStorage in that case.
      }
    }
  },

  // ── State Loading ──
  async loadState() {
    // Most state files are loaded by `state/<key>.json` convention.
    const simpleFiles = ['agents', 'tasks', 'activity', 'costs', 'security'];
    // Files whose on-disk name differs from the state key. The
    // Capability Center page reads `capabilities-status.json` directly
    // and is intentionally not part of the F002 projection adapter —
    // plan 2026-05-23-004 F002 acceptance #3 (Capability Center reused,
    // not duplicated).
    const aliasedFiles = [
      { key: 'capabilities', file: 'capabilities-status.json' },
      // F004 What Now cache — operator_console envelope. Loader treats
      // a missing file as `null`; the page renders the missing-cache
      // empty state in that case.
      { key: 'whatNow',      file: 'what-now.json',      nullableMissing: true },
      // F003 fleet summary — loader treats missing as null; the shell
      // surfaces a build command instead of an empty selector. Reset to
      // null on non-OK / fetch failure so a present→missing refresh
      // (operator deletes the cache file) actually surfaces the missing
      // banner instead of holding stale registry rows.
      { key: 'fleetSummary', file: 'fleet-summary.json', nullableMissing: true },
    ];
    const loaders = [
      ...simpleFiles.map(name => ({ key: name, file: `${name}.json` })),
      ...aliasedFiles,
    ];
    await Promise.all(loaders.map(async ({ key, file, nullableMissing }) => {
      try {
        const resp = await fetch(`state/${file}`);
        if (resp.ok) {
          this.state[key] = await resp.json();
        } else if (nullableMissing) {
          this.state[key] = null;
        }
      } catch {
        // File doesn't exist yet — keep the default value (empty list / null).
        // For nullable aliased files, reset to null so a transient fetch
        // error after a successful load surfaces the missing banner.
        if (nullableMissing) {
          this.state[key] = null;
        }
      }
    }));

    // Projection load order (F002 acceptance #1, post-audit i0):
    //   1. state-snapshot.json envelope — preferred, carries metadata.
    //   2. per-stream files (plans.json / gates.json / ...) — written
    //      alongside the envelope by `dontpanic state export-dashboard`
    //      and served alone when a consumer hand-stages just the streams.
    //   3. legacy demo files — already loaded above; they stay rendering
    //      when neither projection input is present (acceptance #2).
    // Missing files at every layer = quiet empty state (acceptance #4).
    let snapshotApplied = false;
    try {
      const snapResp = await fetch('state/state-snapshot.json');
      if (snapResp.ok) {
        const snap = await snapResp.json();
        snapshotApplied = mergeSnapshotIntoState(this.state, snap);
      }
    } catch {
      // Missing or malformed envelope — fall through to per-stream.
    }

    if (!snapshotApplied) {
      const collected = {};
      await Promise.all(PER_STREAM_FILES.map(async (name) => {
        try {
          const resp = await fetch(`state/${name}.json`);
          if (resp.ok) {
            const data = await resp.json();
            if (Array.isArray(data)) collected[name] = data;
          }
        } catch {
          // Missing per-stream file — adapter treats absent streams as
          // empty arrays. No bootstrap failure.
        }
      }));
      mergePerStreamIntoState(this.state, collected);
    }
  },

  async refreshState() {
    const prevFingerprint = this._fleetFingerprint();
    await this.loadState();
    // Re-resolve the selection after the fleet summary refreshes so a
    // registry change (project added / removed) updates the selector
    // options and drops a stale selection that points at a project that
    // no longer exists (acceptance #6).
    this.resolveProjectSelection();
    if (this._fleetFingerprint() !== prevFingerprint) {
      this.renderProjectSelector();
    }
    // Notify active page of state change
    const activePage = this.pages.find(p => p.id === this.currentPage);
    if (activePage && activePage.onActivate) {
      activePage.onActivate(this.state);
    }
    this.updateLastSync();
  },

  _fleetFingerprint() {
    const envelope = normalizeFleetSummary(this.state.fleetSummary);
    if (envelope == null) return 'missing';
    // Fingerprint covers selector-relevant identity and labels only —
    // the per-project health band changes every poll and is not
    // selector-relevant. Display names are included because they render
    // directly in the option labels.
    return envelope.projects
      .map((p) => `${p.name}:${p.display_name}:${p.active ? '1' : '0'}`)
      .join('|');
  },

  // ── Navigation ──
  buildNav() {
    const nav = document.getElementById('view-nav');
    nav.innerHTML = '';
    for (const page of this.pages) {
      const btn = document.createElement('button');
      btn.className = 'view-tab';
      btn.dataset.page = page.id;
      btn.textContent = page.label;
      btn.addEventListener('click', () => this.switchTo(page.id));
      nav.appendChild(btn);
    }
  },

  buildPageContainers() {
    const container = document.getElementById('page-container');
    for (const page of this.pages) {
      const div = document.createElement('div');
      div.id = `page-${page.id}`;
      div.className = 'page-view';
      container.appendChild(div);
    }
  },

  switchTo(pageId) {
    if (pageId === this.currentPage) return;

    // Deactivate current
    if (this.currentPage) {
      const prev = this.pages.find(p => p.id === this.currentPage);
      if (prev && prev.onDeactivate) prev.onDeactivate();
    }

    this.currentPage = pageId;

    // Update tab styling
    document.querySelectorAll('.view-tab').forEach(t => {
      t.classList.toggle('active', t.dataset.page === pageId);
    });

    // Show/hide pages
    document.querySelectorAll('.page-view').forEach(v => {
      v.classList.toggle('active', v.id === `page-${pageId}`);
    });

    // Update URL hash
    history.replaceState(null, '', '#' + pageId);

    // Activate new page
    const next = this.pages.find(p => p.id === pageId);
    if (next && next.onActivate) next.onActivate(this.state);
  },

  // ── Utilities ──
  startClock() {
    const el = document.getElementById('clock');
    const tick = () => {
      const now = new Date();
      el.textContent = now.toLocaleTimeString('en-US', {
        hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false
      });
    };
    tick();
    setInterval(tick, 1000);
  },

  setSyncStatus(status, label) {
    const el = document.getElementById('sync-status');
    if (!el) return;
    el.className = `status-badge ${status}`;
    el.textContent = label;
  },

  updateLastSync() {
    const el = document.getElementById('last-sync');
    if (el) {
      el.textContent = `Last sync: ${new Date().toLocaleTimeString()}`;
    }
  },

  // ── Helper: format relative time ──
  timeAgo(timestamp) {
    return timeAgo(timestamp);
  },

  // ── Helper: get page container element ──
  getPageEl(pageId) {
    return document.getElementById(`page-${pageId}`);
  },

  // ── Helper: format currency ──
  formatCurrency(val) {
    return formatCurrency(val);
  },

  // ── Helper: format large numbers ──
  formatNumber(val) {
    return formatNumber(val);
  }
}; }

// ══════════════════════════════════════════════
// ── Page Imports ──
// Each page module registers itself via Jarvis.registerPage()
// ══════════════════════════════════════════════

// Dynamically load all page modules
const pageModules = [
  // First-viewport operating surface for V0 — must register first so it
  // is the default tab and answers "what needs action now?" on load.
  'pages/what-now/what-now.js',
  'pages/command-center/command-center.js',
  'pages/cloud-costs/cloud-costs.js',
  'pages/financial/financial.js',
  'pages/mission-control/mission-control.js',
  'pages/security/security.js',
  'pages/capabilities/capabilities.js',
  'pages/settings/settings.js',
];

// Expose globally for page modules and kick off the dynamic page-import
// chain. Vitest imports `createJarvis` directly and drives lifecycle from
// its own fixture, so we skip the auto-bootstrap in that environment to
// avoid clobbering globals or chasing relative page-module imports.
const IS_VITEST =
  typeof globalThis !== 'undefined' &&
  typeof globalThis.process !== 'undefined' &&
  globalThis.process.env &&
  globalThis.process.env.VITEST;
if (!IS_VITEST) {
  const Jarvis = createJarvis();
  // The realtime adapter awaits Jarvis.ready to ensure static first paint
  // completes before Firestore listeners attach.
  window.Jarvis = Jarvis;
  Jarvis.ready = Promise.all(
    pageModules.map(src => import(`./${src}`).catch(err => {
      console.warn(`[Jarvis] Page module not found: ${src}`, err.message);
    }))
  ).then(() => Jarvis.init());
}
