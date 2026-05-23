// ── JARVIS Dashboard — Core Router & State Manager ──
// Local-first: reads state from JSON files, no Firebase dependency.
// Pages register themselves via Jarvis.registerPage().

import { timeAgo, formatCurrency, formatNumber } from './lib/formatters.js';
import {
  mergeSnapshotIntoState,
  mergePerStreamIntoState,
  PER_STREAM_FILES,
} from './lib/projection-adapter.js';

const Jarvis = {
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
    this.buildNav();
    this.buildPageContainers();

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
      { key: 'whatNow',      file: 'what-now.json' },
    ];
    const loaders = [
      ...simpleFiles.map(name => ({ key: name, file: `${name}.json` })),
      ...aliasedFiles,
    ];
    await Promise.all(loaders.map(async ({ key, file }) => {
      try {
        const resp = await fetch(`state/${file}`);
        if (resp.ok) {
          this.state[key] = await resp.json();
        }
      } catch {
        // File doesn't exist yet — keep the default value (empty list / null).
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
    await this.loadState();
    // Notify active page of state change
    const activePage = this.pages.find(p => p.id === this.currentPage);
    if (activePage && activePage.onActivate) {
      activePage.onActivate(this.state);
    }
    this.updateLastSync();
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
};

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

// Expose globally for page modules. The realtime adapter awaits Jarvis.ready
// to ensure static first paint completes before Firestore listeners attach.
window.Jarvis = Jarvis;

Jarvis.ready = Promise.all(
  pageModules.map(src => import(`./${src}`).catch(err => {
    console.warn(`[Jarvis] Page module not found: ${src}`, err.message);
  }))
).then(() => Jarvis.init());
