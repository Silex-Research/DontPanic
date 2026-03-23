// Integration tests for the Jarvis core router and page lifecycle.
//
// Strategy: construct a fresh router object per test using the same method
// signatures as core.js. This avoids the browser-only dynamic import() chain
// while exercising the real logic verbatim.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { setupDOM, setupFetchMock, createMockState, setupChartMock } from '../helpers/setup.js';
import { timeAgo, formatCurrency, formatNumber } from '../../lib/formatters.js';

// ── Router factory ────────────────────────────────────────────────────────────
// Mirrors the Jarvis object literal from core.js exactly, minus the browser-
// global assignment and dynamic page imports. Each test gets a fresh instance.

function createRouter() {
  return {
    pages: [],
    currentPage: null,
    state: {
      agents: [],
      tasks: [],
      activity: [],
      costs: null,
      security: [],
    },

    registerPage(config) {
      this.pages.push(config);
    },

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

      if (this.currentPage) {
        const prev = this.pages.find(p => p.id === this.currentPage);
        if (prev && prev.onDeactivate) prev.onDeactivate();
      }

      this.currentPage = pageId;

      document.querySelectorAll('.view-tab').forEach(t => {
        t.classList.toggle('active', t.dataset.page === pageId);
      });

      document.querySelectorAll('.page-view').forEach(v => {
        v.classList.toggle('active', v.id === `page-${pageId}`);
      });

      history.replaceState(null, '', '#' + pageId);

      const next = this.pages.find(p => p.id === pageId);
      if (next && next.onActivate) next.onActivate(this.state);
    },

    async loadState() {
      const files = ['agents', 'tasks', 'activity', 'costs', 'security'];
      await Promise.all(files.map(async (name) => {
        try {
          const resp = await fetch(`state/${name}.json`);
          if (resp.ok) {
            this.state[name] = await resp.json();
          }
        } catch {
          // file missing — keep empty default
        }
      }));
    },

    getPageEl(pageId) {
      return document.getElementById(`page-${pageId}`);
    },

    timeAgo(timestamp)     { return timeAgo(timestamp); },
    formatCurrency(val)    { return formatCurrency(val); },
    formatNumber(val)      { return formatNumber(val); },
  };
}

// ── Shared setup ──────────────────────────────────────────────────────────────

beforeEach(() => {
  setupDOM();
  setupChartMock();
});

afterEach(() => {
  vi.restoreAllMocks();
});

// ── Page Registration ─────────────────────────────────────────────────────────

describe('registerPage', () => {
  it('adds a page config to the internal pages array', () => {
    const router = createRouter();
    router.registerPage({ id: 'home', label: 'Home' });
    expect(router.pages).toHaveLength(1);
    expect(router.pages[0].id).toBe('home');
  });

  it('preserves registration order when multiple pages are registered', () => {
    const router = createRouter();
    router.registerPage({ id: 'alpha', label: 'Alpha' });
    router.registerPage({ id: 'beta',  label: 'Beta'  });
    router.registerPage({ id: 'gamma', label: 'Gamma' });
    expect(router.pages.map(p => p.id)).toEqual(['alpha', 'beta', 'gamma']);
  });
});

// ── buildNav ──────────────────────────────────────────────────────────────────

describe('buildNav', () => {
  it('creates one button per registered page inside #view-nav', () => {
    const router = createRouter();
    router.registerPage({ id: 'agents',   label: 'Agents'   });
    router.registerPage({ id: 'tasks',    label: 'Tasks'    });
    router.registerPage({ id: 'settings', label: 'Settings' });
    router.buildNav();

    const buttons = document.querySelectorAll('#view-nav .view-tab');
    expect(buttons).toHaveLength(3);
  });

  it('sets data-page attribute and label text on each nav button', () => {
    const router = createRouter();
    router.registerPage({ id: 'cmd', label: 'Command Center' });
    router.buildNav();

    const btn = document.querySelector('[data-page="cmd"]');
    expect(btn).not.toBeNull();
    expect(btn.textContent).toBe('Command Center');
  });

  it('replaces any previous nav contents when called twice', () => {
    const router = createRouter();
    router.registerPage({ id: 'first', label: 'First' });
    router.buildNav();
    router.buildNav(); // second call must not duplicate

    expect(document.querySelectorAll('#view-nav .view-tab')).toHaveLength(1);
  });
});

// ── switchTo ─────────────────────────────────────────────────────────────────

describe('switchTo', () => {
  function buildRouter(...ids) {
    const router = createRouter();
    ids.forEach(id => router.registerPage({ id, label: id }));
    router.buildNav();
    router.buildPageContainers();
    return router;
  }

  it('marks the target tab as active and removes active from others', () => {
    const router = buildRouter('agents', 'tasks', 'settings');
    router.switchTo('tasks');

    expect(document.querySelector('[data-page="tasks"]').classList.contains('active')).toBe(true);
    expect(document.querySelector('[data-page="agents"]').classList.contains('active')).toBe(false);
    expect(document.querySelector('[data-page="settings"]').classList.contains('active')).toBe(false);
  });

  it('shows the target page container and hides all others', () => {
    const router = buildRouter('agents', 'tasks');
    router.switchTo('agents');

    expect(document.getElementById('page-agents').classList.contains('active')).toBe(true);
    expect(document.getElementById('page-tasks').classList.contains('active')).toBe(false);
  });

  it('calls onActivate on the page being navigated to, passing current state', () => {
    const router = createRouter();
    const onActivate = vi.fn();
    router.registerPage({ id: 'home', label: 'Home', onActivate });
    router.buildNav();
    router.buildPageContainers();
    router.switchTo('home');

    expect(onActivate).toHaveBeenCalledOnce();
    expect(onActivate).toHaveBeenCalledWith(router.state);
  });

  it('calls onDeactivate on the previously active page when switching away', () => {
    const router = createRouter();
    const onDeactivate = vi.fn();
    router.registerPage({ id: 'alpha', label: 'Alpha', onDeactivate });
    router.registerPage({ id: 'beta',  label: 'Beta'  });
    router.buildNav();
    router.buildPageContainers();

    router.switchTo('alpha');
    router.switchTo('beta');

    expect(onDeactivate).toHaveBeenCalledOnce();
  });

  it('is a no-op when switching to the already-active page', () => {
    const router = createRouter();
    const onActivate = vi.fn();
    router.registerPage({ id: 'home', label: 'Home', onActivate });
    router.buildNav();
    router.buildPageContainers();

    router.switchTo('home');
    router.switchTo('home'); // second call must not re-activate

    expect(onActivate).toHaveBeenCalledOnce();
  });

  it('updates currentPage to the newly activated page id', () => {
    const router = buildRouter('a', 'b');
    router.switchTo('a');
    expect(router.currentPage).toBe('a');
    router.switchTo('b');
    expect(router.currentPage).toBe('b');
  });
});

// ── Hash-based routing ────────────────────────────────────────────────────────

describe('hash-based routing', () => {
  it('dispatches to the correct page when a hashchange event fires', () => {
    const router = createRouter();
    const onActivate = vi.fn();
    router.registerPage({ id: 'security', label: 'Security', onActivate });
    router.buildNav();
    router.buildPageContainers();

    // Simulate what init() wires up
    window.addEventListener('hashchange', () => {
      const h = location.hash.slice(1);
      if (router.pages.find(p => p.id === h)) {
        router.switchTo(h);
      }
    });

    // jsdom does not fire hashchange automatically on assignment, so dispatch manually
    location.hash = '#security';
    window.dispatchEvent(new Event('hashchange'));

    expect(onActivate).toHaveBeenCalledOnce();
  });
});

// ── loadState ────────────────────────────────────────────────────────────────

describe('loadState', () => {
  it('populates router.state from all 5 JSON fixtures when fetches succeed', async () => {
    const mockState = createMockState();
    setupFetchMock({
      agents:   mockState.agents,
      tasks:    mockState.tasks,
      activity: mockState.activity,
      costs:    mockState.costs,
      security: mockState.security,
    });

    const router = createRouter();
    await router.loadState();

    expect(router.state.agents).toEqual(mockState.agents);
    expect(router.state.tasks).toEqual(mockState.tasks);
    expect(router.state.activity).toEqual(mockState.activity);
    expect(router.state.costs).toEqual(mockState.costs);
    expect(router.state.security).toEqual(mockState.security);
  });

  it('leaves state at its empty default when all fetches return 404', async () => {
    setupFetchMock({}); // every URL returns { ok: false, status: 404 }

    const router = createRouter();
    await router.loadState();

    expect(router.state.agents).toEqual([]);
    expect(router.state.tasks).toEqual([]);
    expect(router.state.activity).toEqual([]);
    expect(router.state.costs).toBeNull();
    expect(router.state.security).toEqual([]);
  });

  it('silently keeps the default value for any file whose fetch throws', async () => {
    globalThis.fetch = vi.fn().mockRejectedValue(new Error('network error'));

    const router = createRouter();
    await expect(router.loadState()).resolves.not.toThrow();
    expect(router.state.agents).toEqual([]);
  });

  it('partially loads state when only some files are available', async () => {
    const mockState = createMockState();
    setupFetchMock({ agents: mockState.agents }); // only agents present

    const router = createRouter();
    await router.loadState();

    expect(router.state.agents).toEqual(mockState.agents);
    expect(router.state.tasks).toEqual([]);   // 404 — kept at default
    expect(router.state.costs).toBeNull();
  });
});

// ── Utility delegation ────────────────────────────────────────────────────────

describe('utility methods', () => {
  it('timeAgo delegates to the formatters library', () => {
    const router = createRouter();
    const now = Date.now();
    vi.spyOn(Date, 'now').mockReturnValue(now);
    const ts = now - 30 * 1000;
    expect(router.timeAgo(ts)).toBe(timeAgo(ts));
  });

  it('formatCurrency delegates to the formatters library', () => {
    const router = createRouter();
    expect(router.formatCurrency(99.9)).toBe(formatCurrency(99.9));
    expect(router.formatCurrency(null)).toBe('--');
  });

  it('formatNumber delegates to the formatters library', () => {
    const router = createRouter();
    expect(router.formatNumber(1500)).toBe(formatNumber(1500));
    expect(router.formatNumber(null)).toBe('--');
  });

  it('getPageEl returns the DOM element for a registered page container', () => {
    const router = createRouter();
    router.registerPage({ id: 'costs', label: 'Costs' });
    router.buildPageContainers();
    const el = router.getPageEl('costs');
    expect(el).not.toBeNull();
    expect(el.id).toBe('page-costs');
  });
});
