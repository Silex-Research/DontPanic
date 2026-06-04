// Integration tests for the F013 config-inventory rendering in the Settings
// page (plan 2026-05-30-001).
//
// Strategy mirrors capabilities-page.test.js: drive the REAL
// `pages/settings/settings.js` IIFE through a minimal Jarvis shim that mirrors
// core.js's contract (registerPage / getPageEl / state), then exercise the
// fetch(state/config-inventory.json) → state.configInventory → page render
// path end-to-end. This is the loader/page coverage the F013 audit asked for:
// proof the cards actually render in the dashboard UI, not just in Python JSON.

import { describe, it, expect, beforeAll, beforeEach } from 'vitest';
import { setupDOM, setupFetchMock, setupLocalStorageMock } from '../helpers/setup.js';
import fixture from '../fixtures/config-inventory.json' with { type: 'json' };

describe('settings page: config inventory rendering', () => {
  const jarvisShim = {
    pages: [],
    state: { configInventory: null },
    registerPage(config) { this.pages.push(config); },
    getPageEl(pageId) {
      let el = document.getElementById(`page-${pageId}`);
      if (!el) {
        el = document.createElement('div');
        el.id = `page-${pageId}`;
        el.className = 'page-view';
        document.getElementById('page-container').appendChild(el);
      }
      return el;
    },
  };
  let registeredPage;

  beforeAll(async () => {
    setupDOM();
    setupLocalStorageMock();
    globalThis.Jarvis = jarvisShim;
    window.Jarvis = jarvisShim;
    await import('../../pages/settings/settings.js');
    registeredPage = jarvisShim.pages[0];
  });

  beforeEach(() => {
    setupDOM();
    setupLocalStorageMock();
    globalThis.Jarvis = jarvisShim;
    window.Jarvis = jarvisShim;
  });

  it('registers the Preferences page with the router', () => {
    expect(registeredPage.id).toBe('settings');
    expect(typeof registeredPage.init).toBe('function');
    expect(typeof registeredPage.onActivate).toBe('function');
  });

  it('renders the actionable empty state when no inventory is loaded', () => {
    registeredPage.init({ configInventory: null });
    const pageEl = jarvisShim.getPageEl('settings');
    const host = pageEl.querySelector('#stg-config-inventory');
    expect(host).not.toBeNull();
    expect(host.querySelector('.ci-empty-state')).not.toBeNull();
    expect(host.textContent).toContain('dontpanic dashboard build');
    expect(host.querySelector('.ci-card')).toBeNull();
  });

  it('flows fetch(state/config-inventory.json) → state.configInventory → cards', async () => {
    setupFetchMock({ 'config-inventory': fixture });

    // Mirror core.js's aliased-loader for just this key.
    const resp = await fetch('state/config-inventory.json');
    expect(resp.ok).toBe(true);
    jarvisShim.state.configInventory = await resp.json();

    registeredPage.init(jarvisShim.state);

    const pageEl = jarvisShim.getPageEl('settings');
    const host = pageEl.querySelector('#stg-config-inventory');
    // Empty-state must NOT show when the projection is present.
    expect(host.querySelector('.ci-empty-state')).toBeNull();
    // Every provider renders as a card (>=10).
    const total = fixture.settings_cards.length + fixture.setup_cards.length;
    expect(total).toBeGreaterThanOrEqual(10);
    expect(host.querySelectorAll('.ci-card').length).toBe(total);
    // Exactly one response-level dashboard hint.
    expect(host.querySelectorAll('#ci-dashboard-hint').length).toBe(1);
  });

  it('preserves the browser Preferences section alongside the inventory', () => {
    registeredPage.init({ configInventory: fixture });
    const pageEl = jarvisShim.getPageEl('settings');
    // F013 augments the page — it does not remove the existing localStorage
    // preferences surface.
    expect(pageEl.querySelector('.stg-config-section')).not.toBeNull();
    expect(pageEl.querySelector('#stg-theme-select')).not.toBeNull();
    expect(pageEl.querySelector('.ci-card')).not.toBeNull();
  });

  it('onActivate re-renders the inventory when state arrives after init', () => {
    registeredPage.init({ configInventory: null });
    const pageEl = jarvisShim.getPageEl('settings');
    expect(pageEl.querySelector('#stg-config-inventory .ci-empty-state')).not.toBeNull();

    registeredPage.onActivate({ configInventory: fixture });
    const host = pageEl.querySelector('#stg-config-inventory');
    expect(host.querySelector('.ci-empty-state')).toBeNull();
    const total = fixture.settings_cards.length + fixture.setup_cards.length;
    expect(host.querySelectorAll('.ci-card').length).toBe(total);
  });

  // codex i1 (high): project/fleet serves mirror each project's inventory under
  // state/projects/<name>/config-inventory.json — loaded into
  // state.configInventoryByProject. With a concrete project selected, Settings
  // must render THAT project's cards (and keep its active-url hint), not the
  // top-level machine-scope blob.
  it('renders the selected project inventory from configInventoryByProject', async () => {
    const alphaFixture = {
      ...fixture,
      project_name: 'alpha',
      dashboard_hint: {
        ...fixture.dashboard_hint,
        is_running: true,
        active_url: 'http://127.0.0.1:8732/',
        start_command: null,
      },
    };
    // The per-project mirror is fetched from state/projects/<name>/. The mock
    // keys by basename, so 'config-inventory' covers the per-project path.
    setupFetchMock({ 'config-inventory': alphaFixture });
    const resp = await fetch('state/projects/alpha/config-inventory.json');
    expect(resp.ok).toBe(true);
    jarvisShim.state.configInventoryByProject = { alpha: await resp.json() };
    jarvisShim.state.configInventory = { ...fixture, project_name: null };
    jarvisShim.state.selectedProject = 'alpha';

    registeredPage.init(jarvisShim.state);

    const pageEl = jarvisShim.getPageEl('settings');
    const host = pageEl.querySelector('#stg-config-inventory');
    // The focused project's scope label and cards render.
    expect(host.querySelector('.ci-scope-label').textContent).toContain('alpha');
    const total = alphaFixture.settings_cards.length + alphaFixture.setup_cards.length;
    expect(host.querySelectorAll('.ci-card').length).toBe(total);
    // Active-url detection survives on the per-project path.
    const hint = host.querySelector('#ci-dashboard-hint');
    expect(hint).not.toBeNull();
    expect(hint.dataset.running).toBe('1');
    expect(host.textContent).toContain('http://127.0.0.1:8732/');

    // Reset shared shim state so later tests aren't polluted.
    jarvisShim.state.configInventoryByProject = {};
    jarvisShim.state.selectedProject = undefined;
    jarvisShim.state.configInventory = null;
  });
});
