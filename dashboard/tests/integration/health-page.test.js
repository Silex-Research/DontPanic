// Integration tests for the F003 Health page module.
//
// Drives the real page-module IIFE through a minimal Jarvis shim, and
// asserts that the registered page object renders renderHealthHTML into
// the right container. Coverage focuses on:
//   - page registration smoke
//   - missing-data renders for every card kind
//   - security card composition from state.security
//   - fleet vs project scope re-render via onActivate

import { describe, it, expect, beforeAll, beforeEach } from 'vitest';
import { setupDOM } from '../helpers/setup.js';

describe('health: real page module registration', () => {
  const jarvisShim = {
    pages: [],
    state: {},
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
    globalThis.Jarvis = jarvisShim;
    window.Jarvis = jarvisShim;
    await import('../../pages/health/health.js');
    registeredPage = jarvisShim.pages.find(p => p.id === 'health');
  });

  beforeEach(() => {
    setupDOM();
    globalThis.Jarvis = jarvisShim;
    window.Jarvis = jarvisShim;
  });

  it('registers a single Health page with the router', () => {
    expect(registeredPage).toBeDefined();
    expect(registeredPage.id).toBe('health');
    expect(registeredPage.label).toBe('Health');
    expect(typeof registeredPage.init).toBe('function');
    expect(typeof registeredPage.onActivate).toBe('function');
  });

  it('init() renders the layout shell with missing-data cards for every source', () => {
    registeredPage.init({});
    const el = jarvisShim.getPageEl('health');
    expect(el.querySelector('.hlth-layout')).not.toBeNull();
    // Every credible-source card has a missing-data fallback. The page
    // must never silently drop one.
    for (const kind of ['install', 'reconcile', 'build_warnings', 'security', 'budget', 'fleet']) {
      expect(el.querySelector(`[data-kind="${kind}"]`)).not.toBeNull();
    }
  });

  it('init() surfaces the security source file in the missing-data card', () => {
    registeredPage.init({});
    const el = jarvisShim.getPageEl('health');
    const securityCard = el.querySelector('[data-kind="security"]');
    expect(securityCard).not.toBeNull();
    expect(securityCard.textContent).toContain('Security hooks — no data yet');
    expect(securityCard.textContent).toContain('dashboard/state/security.json');
  });

  it('init() with a populated state.security renders aggregated counts', () => {
    registeredPage.init({
      security: [
        { action: 'block',            category: 'file_write', agent: 'claude' },
        { action: 'require_approval', category: 'api_call',   agent: 'codex' },
        { action: 'log',              category: 'git_push',   agent: 'claude' },
      ],
    });
    const el = jarvisShim.getPageEl('health');
    const securityCard = el.querySelector('[data-kind="security"]');
    expect(securityCard).not.toBeNull();
    expect(securityCard.textContent).toContain('Security hooks blocked recent actions');
    expect(securityCard.classList.contains('hlth-card--red')).toBe(true);
  });

  it('init() with an empty state.security renders the quiet "no activity" card', () => {
    // Present-but-empty is the honest "no activity yet" signal. It must
    // NOT collapse into the missing-data card.
    registeredPage.init({ security: [] });
    const el = jarvisShim.getPageEl('health');
    const securityCard = el.querySelector('[data-kind="security"]');
    expect(securityCard.textContent).toContain('No security hook activity yet');
    expect(securityCard.textContent).not.toContain('no data yet');
  });

  it('switches scope from fleet to project via onActivate()', () => {
    registeredPage.init({});
    let el = jarvisShim.getPageEl('health');
    expect(el.querySelector('.hlth-layout').dataset.scope).toBe('fleet');

    registeredPage.onActivate({ selectedProject: 'styln' });
    el = jarvisShim.getPageEl('health');
    expect(el.querySelector('.hlth-layout').dataset.scope).toBe('project');
    expect(el.textContent).toContain('Health for project styln');
  });

  it('renders the fleet warnings card with per-project rows when fleetSummary is present', () => {
    registeredPage.init({
      fleetSummary: {
        projects: [
          { name: 'styln',    display_name: 'Styln',    warning_count: 2, health_band: 'advisory' },
          { name: 'spindine', display_name: 'SpinDine', warning_count: 0, health_band: 'ready' },
        ],
      },
    });
    const el = jarvisShim.getPageEl('health');
    const fleetCard = el.querySelector('[data-kind="fleet"]');
    expect(fleetCard).not.toBeNull();
    expect(fleetCard.textContent).toContain('Fleet has open warnings');
    expect(fleetCard.textContent).toContain('Styln');
    expect(fleetCard.textContent).toContain('SpinDine');
  });
});
