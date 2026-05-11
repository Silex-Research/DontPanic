// ── JARVIS Dashboard — Core Router & State Manager ──
// Local-first: reads state from JSON files, no Firebase dependency.
// Pages register themselves via Jarvis.registerPage().

import { timeAgo, formatCurrency, formatNumber } from './lib/formatters.js';

const Jarvis = {
  pages: [],
  currentPage: null,
  state: {
    agents: [],
    tasks: [],
    activity: [],
    costs: null,
    security: [],
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
    const files = ['agents', 'tasks', 'activity', 'costs', 'security'];
    await Promise.all(files.map(async (name) => {
      try {
        const resp = await fetch(`state/${name}.json`);
        if (resp.ok) {
          this.state[name] = await resp.json();
        }
      } catch {
        // File doesn't exist yet — use empty default
      }
    }));
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
  'pages/command-center/command-center.js',
  'pages/cloud-costs/cloud-costs.js',
  'pages/financial/financial.js',
  'pages/mission-control/mission-control.js',
  'pages/security/security.js',
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
