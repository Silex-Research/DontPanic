// Integration tests for the Capability Center page.
//
// Strategy mirrors security-page.test.js: the page IIFE is a thin wrapper
// over `lib/capabilities-logic.js`. We render the same HTML directly into
// a constructed page container and assert on the resulting DOM. This also
// verifies that the page can degrade to its empty-state when the JSON
// envelope is absent or malformed.

import { describe, it, expect, beforeAll, beforeEach } from 'vitest';
import { setupDOM, setupFetchMock } from '../helpers/setup.js';
import { renderCapabilityCenterHTML } from '../../lib/capabilities-logic.js';
import fixture from '../fixtures/capabilities-status.json' with { type: 'json' };

function makePageEl() {
  const container = document.getElementById('page-container');
  const div = document.createElement('div');
  div.id = 'page-capabilities';
  div.className = 'page-view active';
  container.appendChild(div);
  return div;
}

function renderInto(el, raw) {
  el.innerHTML = renderCapabilityCenterHTML(raw);
}

beforeEach(() => {
  setupDOM();
});

// ── Empty state (acceptance #3) ─────────────────────────────────────────────

describe('capability center: missing state file', () => {
  it('renders the empty-state when the envelope is null', () => {
    const el = makePageEl();
    renderInto(el, null);
    expect(el.querySelector('.cap-empty-state')).not.toBeNull();
    expect(el.querySelector('.cap-cards')).toBeNull();
  });

  it('renders the empty-state when the envelope is undefined', () => {
    const el = makePageEl();
    renderInto(el, undefined);
    expect(el.querySelector('.cap-empty-state')).not.toBeNull();
  });

  it('renders the empty-state when capabilities[] is missing', () => {
    const el = makePageEl();
    renderInto(el, { schema_version: '1.0.0' });
    expect(el.querySelector('.cap-empty-state')).not.toBeNull();
  });

  it('directs operators to the local CLI, not Firebase', () => {
    const el = makePageEl();
    renderInto(el, null);
    const text = el.textContent;
    expect(text).toContain('dontpanic capabilities status');
    expect(text).toContain('capabilities-status.json');
    // Must NOT tell the operator they need Firebase / a hosted backend.
    expect(text.toLowerCase()).not.toContain('firestore');
    expect(text.toLowerCase()).not.toContain('firebase auth');
    expect(text.toLowerCase()).not.toMatch(/firebase\s+is\s+required/);
  });
});

// ── Populated render (acceptance #4) ────────────────────────────────────────

describe('capability center: populated render', () => {
  let pageEl;
  beforeEach(() => {
    pageEl = makePageEl();
    renderInto(pageEl, fixture);
  });

  it('renders one card per capability in the fixture', () => {
    const cards = pageEl.querySelectorAll('.cap-card');
    expect(cards.length).toBe(fixture.capabilities.length);
  });

  it('each fixture capability shows up as a card title', () => {
    const titles = [...pageEl.querySelectorAll('.cap-card-title')].map(el => el.textContent.trim());
    for (const cap of fixture.capabilities) {
      expect(titles).toContain(cap.capability_id);
    }
  });

  it('renders the four expected status badges', () => {
    const badges = [...pageEl.querySelectorAll('.cap-status-badge')].map(el => el.textContent.trim());
    expect(badges).toContain('READY');
    expect(badges).toContain('NEEDS SETUP');
    expect(badges).toContain('BLOCKED');
    expect(badges).toContain('NOT INSTALLED');
  });

  it('renders owner_boundary chips for every non-empty role bucket', () => {
    const fbCard = pageEl.querySelector('[data-capability-id="firebase-dashboard"]');
    expect(fbCard).not.toBeNull();
    const chipRoles = [...fbCard.querySelectorAll('.cap-owner-chip')]
      .map(c => c.className.match(/cap-owner-chip--(\w+)/)?.[1]);
    expect(chipRoles).toContain('dontpanic_core');
    expect(chipRoles).toContain('adapter');
    expect(chipRoles).toContain('operator');
  });

  it('renders Configured tokens when present', () => {
    const fbCard = pageEl.querySelector('[data-capability-id="firebase-dashboard"]');
    const configured = [...fbCard.querySelectorAll('.cap-list-configured li')].map(el => el.textContent);
    expect(configured).toContain('firebase');
    expect(configured).toContain('gcloud');
  });

  it('renders Missing tokens when present', () => {
    const fbCard = pageEl.querySelector('[data-capability-id="firebase-dashboard"]');
    const missing = [...fbCard.querySelectorAll('.cap-list-missing li')].map(el => el.textContent);
    expect(missing).toContain('DONTPANIC_FIREBASE_PROJECT');
    expect(missing).toContain('firebase login');
  });

  it('renders pending probes with name + reason', () => {
    const fbCard = pageEl.querySelector('[data-capability-id="firebase-dashboard"]');
    const probes = fbCard.querySelector('.cap-list-probes');
    expect(probes).not.toBeNull();
    expect(probes.textContent).toContain('firebase_dashboard_config');
    expect(probes.textContent).toContain('Awaiting deployed config');
  });

  it('partitions next actions into automatable and human-required groups', () => {
    const fbCard = pageEl.querySelector('[data-capability-id="firebase-dashboard"]');
    const autoGroup  = fbCard.querySelector('.cap-action-group--auto');
    const humanGroup = fbCard.querySelector('.cap-action-group--human');
    expect(autoGroup).not.toBeNull();
    expect(humanGroup).not.toBeNull();
    expect(autoGroup.textContent).toContain('Install the Firebase CLI');
    expect(humanGroup.textContent).toContain('interactive browser sign-in');
  });

  it('renders the human_required_reason on each human-required action', () => {
    const fbCard = pageEl.querySelector('[data-capability-id="firebase-dashboard"]');
    const reason = fbCard.querySelector('.cap-action-reason');
    expect(reason).not.toBeNull();
    expect(reason.textContent).toMatch(/interactive browser sign-in/i);
  });

  it('orders attention-needing capabilities ahead of ready ones', () => {
    const titles = [...pageEl.querySelectorAll('.cap-card-title')].map(el => el.textContent.trim());
    // agent-claude-cli (ready) is last; discord-notify (blocked) is first.
    expect(titles[titles.length - 1]).toBe('agent-claude-cli');
    expect(titles[0]).toBe('discord-notify');
  });

  it('renders summary counts that match the fixture', () => {
    const grid = pageEl.querySelector('#cap-summary-grid');
    expect(grid).not.toBeNull();
    const values = [...grid.querySelectorAll('.cap-summary-value')].map(el => el.textContent.trim());
    // 4 total, 1 ready, 1 needs_setup, 1 blocked, 1 not_installed, 0 optional
    expect(values).toEqual(['4', '1', '1', '1', '1', '0']);
  });

  it('renders top-level advisory notes from the envelope', () => {
    const advisories = pageEl.querySelectorAll('#cap-advisory-list .cap-advisory');
    expect(advisories.length).toBeGreaterThan(0);
  });

  it('renders the Discord blocked card with its red status modifier', () => {
    const card = pageEl.querySelector('[data-capability-id="discord-notify"]');
    expect(card).not.toBeNull();
    expect(card.classList.contains('cap-card--red')).toBe(true);
    expect(card.dataset.status).toBe('blocked');
  });
});

// ── Setup vs not-installed visual distinction (acceptance #5) ───────────────

describe('capability center: firebase-dashboard vs linear distinction', () => {
  let pageEl;
  beforeEach(() => {
    pageEl = makePageEl();
    renderInto(pageEl, fixture);
  });

  it('firebase-dashboard is rendered as needs_setup (yellow)', () => {
    const card = pageEl.querySelector('[data-capability-id="firebase-dashboard"]');
    expect(card.dataset.status).toBe('needs_setup');
    expect(card.classList.contains('cap-card--yellow')).toBe(true);
    const badge = card.querySelector('.cap-status-badge');
    expect(badge.textContent.trim()).toBe('NEEDS SETUP');
    expect(badge.classList.contains('cap-status-badge--yellow')).toBe(true);
  });

  it('linear is rendered as not_installed (muted), distinct from firebase-dashboard', () => {
    const card = pageEl.querySelector('[data-capability-id="linear"]');
    expect(card.dataset.status).toBe('not_installed');
    expect(card.classList.contains('cap-card--muted')).toBe(true);
    const badge = card.querySelector('.cap-status-badge');
    expect(badge.textContent.trim()).toBe('NOT INSTALLED');
    expect(badge.classList.contains('cap-status-badge--muted')).toBe(true);
  });

  it('the two cards use different status modifier classes', () => {
    const fb     = pageEl.querySelector('[data-capability-id="firebase-dashboard"]');
    const linear = pageEl.querySelector('[data-capability-id="linear"]');
    expect(fb.dataset.status).not.toBe(linear.dataset.status);
    expect(fb.className).not.toBe(linear.className);
  });
});

// ── Page-module registration smoke (acceptance #1, #2) ──────────────────────
//
// These tests exercise the real `pages/capabilities/capabilities.js` IIFE
// (not just the pure renderer). The module's top-level IIFE calls
// `Jarvis.registerPage(...)` at import-evaluation time, so we install a
// minimal Jarvis shim that mirrors core.js's contract (registerPage,
// getPageEl, state) BEFORE the dynamic import, then drive the registered
// page object's lifecycle directly. This is the same registration path
// core.js uses in the browser.
//
// We also drive an aliased-fetch loader so the same flow that core.js uses
// to populate `state.capabilities` from `state/capabilities-status.json` is
// covered end-to-end (fetch → state key → page render).

describe('capability center: real page module registration', () => {
  // Module-scoped Jarvis shim — the page IIFE only runs once at first
  // import (vitest module cache), so we set it up once and re-drive the
  // registered page lifecycle from each test.
  const jarvisShim = {
    pages: [],
    state: { capabilities: null },
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
    // jsdom is global across tests, so make sure the DOM container the
    // page IIFE will look up exists before the module evaluates.
    setupDOM();
    globalThis.Jarvis = jarvisShim;
    window.Jarvis = jarvisShim;
    await import('../../pages/capabilities/capabilities.js');
    registeredPage = jarvisShim.pages[0];
  });

  beforeEach(() => {
    // Fresh DOM per test (other suites mutate it). The page module's
    // closure caches its DOM element on init(), so re-init below to
    // re-bind to the fresh container.
    setupDOM();
    // Keep the same Jarvis shim object — replacing it would orphan the
    // page IIFE's `Jarvis.registerPage` reference.
    globalThis.Jarvis = jarvisShim;
    window.Jarvis = jarvisShim;
  });

  it('registers a single Capability Center page with the router', () => {
    expect(jarvisShim.pages).toHaveLength(1);
    const page = registeredPage;
    expect(page.id).toBe('capabilities');
    // Acceptance #1: nav label must say "Capability Center", not "Capabilities".
    expect(page.label).toBe('Capability Center');
    expect(typeof page.init).toBe('function');
    expect(typeof page.onActivate).toBe('function');
  });

  it('nav label "Capability Center" renders into the DOM via buildNav', () => {
    // Mirror core.js buildNav() against the registered pages.
    const nav = document.getElementById('view-nav');
    for (const page of jarvisShim.pages) {
      const btn = document.createElement('button');
      btn.className = 'view-tab';
      btn.dataset.page = page.id;
      btn.textContent = page.label;
      nav.appendChild(btn);
    }

    const tab = nav.querySelector('[data-page="capabilities"]');
    expect(tab).not.toBeNull();
    expect(tab.textContent).toBe('Capability Center');
  });

  it('init() renders the empty-state when state.capabilities is null', () => {
    registeredPage.init({ capabilities: null });

    const pageEl = jarvisShim.getPageEl('capabilities');
    expect(pageEl.querySelector('.cap-empty-state')).not.toBeNull();
    expect(pageEl.textContent).toContain('dontpanic capabilities status');
  });

  // Acceptance #2 end-to-end: a real fetch against state/capabilities-status.json
  // (mocked by setupFetchMock) flows through into the page's render output via
  // the same alias mapping that core.js uses.
  it('flows fetch(state/capabilities-status.json) → state.capabilities → page render', async () => {
    setupFetchMock({ 'capabilities-status': fixture });

    // Mirror core.js's aliased-loader for just this key.
    const resp = await fetch('state/capabilities-status.json');
    expect(resp.ok).toBe(true);
    jarvisShim.state.capabilities = await resp.json();

    registeredPage.init(jarvisShim.state);

    const pageEl = jarvisShim.getPageEl('capabilities');
    // Empty-state must NOT be shown when the envelope is present.
    expect(pageEl.querySelector('.cap-empty-state')).toBeNull();
    // Every fixture capability must render as a card.
    const cards = pageEl.querySelectorAll('.cap-card');
    expect(cards.length).toBe(fixture.capabilities.length);
    // Spot-check the firebase-dashboard card is reachable through this path.
    expect(pageEl.querySelector('[data-capability-id="firebase-dashboard"]')).not.toBeNull();
  });

  it('onActivate() re-renders when state.capabilities updates after init', () => {
    registeredPage.init({ capabilities: null });
    const pageEl = jarvisShim.getPageEl('capabilities');
    expect(pageEl.querySelector('.cap-empty-state')).not.toBeNull();

    registeredPage.onActivate({ capabilities: fixture });
    expect(pageEl.querySelector('.cap-empty-state')).toBeNull();
    expect(pageEl.querySelectorAll('.cap-card').length).toBe(fixture.capabilities.length);
  });
});

// ── XSS resistance — important because we render token strings via innerHTML ─

describe('capability center: HTML escape resistance', () => {
  it('escapes special chars in capability_id and tokens', () => {
    const malicious = {
      schema_version: '1.0.0',
      generated_at: '2026-05-22T00:00:00Z',
      advisory_notes: [],
      capabilities: [{
        capability_id: '<script>alert(1)</script>',
        status: 'ready',
        owner_boundary: { dontpanic_core: ['<img onerror=1>'], adapter: [], operator: [] },
        configured: ['<b>x</b>'],
        missing: [],
        automatable: [],
        human_required: [],
        pending_probes: [],
        next_actions: [],
        advisory_notes: [],
      }],
    };
    const el = makePageEl();
    renderInto(el, malicious);
    // No script tag should have been injected.
    expect(el.querySelector('script')).toBeNull();
    expect(el.querySelector('img')).toBeNull();
    // Escaped content still appears textually.
    expect(el.textContent).toContain('<script>alert(1)</script>');
    expect(el.textContent).toContain('<b>x</b>');
  });
});
