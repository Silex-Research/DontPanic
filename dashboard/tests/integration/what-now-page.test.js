// Integration tests for the F004 What Now page.
//
// Drives the same render path the dashboard router would: render
// `renderWhatNowHTML` into a constructed page container and assert on
// the resulting DOM. Also exercises the real page-module IIFE through a
// minimal Jarvis shim — the registered page object is the one core.js
// invokes in the browser.

import { describe, it, expect, beforeAll, beforeEach, vi } from 'vitest';
import { setupDOM, setupFetchMock } from '../helpers/setup.js';
import { renderWhatNowHTML } from '../../lib/what-now-logic.js';
import fixture from '../fixtures/what-now.json' with { type: 'json' };

const fleetSummary = {
  worst_band: 'needs_action',
  projects: [
    {
      name: 'spindine',
      display_name: 'SpinDine',
      health_band: 'needs_action',
      warning_count: 1,
      required_capability_ids: ['linear'],
      referenced_adapter_categories: ['dashboard-realtime'],
    },
    {
      name: 'glam',
      display_name: 'Glam',
      health_band: 'advisory',
      warning_count: 0,
      required_capability_ids: [],
      referenced_adapter_categories: [],
    },
  ],
};

const fleetWhatNow = {
  schema_version: '1.0.0',
  captured_at: '2026-05-23T03:00:00Z',
  capability_categories: { 'firebase-dashboard': 'dashboard-realtime', linear: 'pm-tool' },
  items: [
    { id: 'gate:spin', source: 'gate', band: 'needs_action', title: 'Spin gate', project_name: 'spindine', automatable: false, human_required_reason: 'approval' },
    { id: 'arch:glam', source: 'architecture', band: 'advisory', title: 'Glam stale architecture', project_name: 'glam', automatable: true },
    { id: 'capability:linear', source: 'capability', band: 'needs_action', title: 'Linear missing', automatable: false, human_required_reason: 'setup' },
    { id: 'capability:firebase-dashboard', source: 'capability', band: 'advisory', title: 'Firebase missing', automatable: false, human_required_reason: 'setup' },
  ],
};

function makePageEl() {
  const container = document.getElementById('page-container');
  const div = document.createElement('div');
  div.id = 'page-what-now';
  div.className = 'page-view active';
  container.appendChild(div);
  return div;
}

function renderInto(el, raw) {
  el.innerHTML = renderWhatNowHTML(raw);
}

beforeEach(() => {
  setupDOM();
});

// ── Missing state (acceptance #4: non-alarming when cache is absent) ────

describe('what-now: missing cache', () => {
  it('renders the missing-cache empty state for null state', () => {
    const el = makePageEl();
    renderInto(el, null);
    expect(el.querySelector('[data-state="missing"]')).not.toBeNull();
    expect(el.querySelector('.wn-cards')).toBeNull();
    expect(el.textContent).toContain('dontpanic dashboard build');
  });

  it('does not surface the missing-cache state as a blocker', () => {
    const el = makePageEl();
    renderInto(el, null);
    const text = el.textContent.toLowerCase();
    expect(text).not.toContain('error');
    expect(text).not.toContain('blocked');
    expect(text).not.toContain('firebase');
  });
});

// ── Quiet state (acceptance #4: restrained when no action needed) ───────

describe('what-now: quiet state', () => {
  it('renders the quiet panel when the envelope has no items', () => {
    const el = makePageEl();
    renderInto(el, { schema_version: '1.0.0', captured_at: '2026-05-23T03:50:00Z', items: [] });
    expect(el.querySelector('[data-state="quiet"]')).not.toBeNull();
    expect(el.querySelector('.wn-cards')).toBeNull();
    expect(el.textContent).toContain('No action needed');
  });

  it('renders advisory/info-only envelopes as cards with visible commands (non-alarming)', () => {
    // F004 acceptance #3 + #4: advisory stale/missing items must surface
    // their exact commands as copyable cards. Restraint = band coloring,
    // not collapsing into the quiet panel.
    const el = makePageEl();
    renderInto(el, {
      schema_version: '1.0.0',
      captured_at: '2026-05-23T03:50:00Z',
      items: [
        {
          id: 'reconcile:missing_snapshot',
          source: 'reconcile',
          band: 'advisory',
          title: 'Install snapshot is missing',
          exact_command: 'dontpanic reconcile baseline --yes',
          automatable: false,
          human_required_reason: 'no baseline to compare against',
        },
        {
          id: 'sup:1',
          source: 'supervisor',
          band: 'info',
          title: 'Supervisor active',
          exact_command: 'dontpanic ps',
          automatable: true,
        },
      ],
    });
    expect(el.querySelector('[data-state="quiet"]')).toBeNull();
    const cards = el.querySelectorAll('.wn-card');
    expect(cards.length).toBe(2);
    expect(el.querySelector('[data-band="advisory"]')).not.toBeNull();
    expect(el.querySelector('[data-band="info"]')).not.toBeNull();
    expect(el.querySelector('[data-band="needs_action"]')).toBeNull();
    // Exact commands visible + a copy button present per command.
    const codes = [...el.querySelectorAll('.wn-cmd code')].map((c) => c.textContent);
    expect(codes).toContain('dontpanic reconcile baseline --yes');
    expect(codes).toContain('dontpanic ps');
    const copyCmds = [...el.querySelectorAll('.wn-copy-btn')].map((b) => b.dataset.command);
    expect(copyCmds).toContain('dontpanic reconcile baseline --yes');
    expect(copyCmds).toContain('dontpanic ps');
  });
});

// ── Populated needs-action render (acceptance #1, #2, #3, #5) ───────────

describe('what-now: populated render', () => {
  let pageEl;
  beforeEach(() => {
    pageEl = makePageEl();
    renderInto(pageEl, fixture);
  });

  it('renders one card per ActionItem in the fixture', () => {
    const cards = pageEl.querySelectorAll('.wn-card');
    expect(cards.length).toBe(fixture.items.length);
  });

  it('covers gates, capabilities, reconcile, and supervisors as ActionItems', () => {
    // Acceptance #2: all four sources can appear.
    const sources = [...pageEl.querySelectorAll('.wn-card')]
      .map((c) => c.dataset.source);
    expect(sources).toContain('gate');
    expect(sources).toContain('capability');
    expect(sources).toContain('reconcile');
    expect(sources).toContain('supervisor');
    expect(sources).toContain('architecture');
  });

  it('renders exact commands inside a pre/code block (acceptance #3)', () => {
    const codes = [...pageEl.querySelectorAll('.wn-cmd code')].map((c) => c.textContent);
    expect(codes).toContain('dontpanic approve 2026-05-23-004-feat-operator-console-v0 pre_merge');
    expect(codes).toContain('dontpanic reconcile baseline --yes');
  });

  it('renders a copy button per command with the raw command payload', () => {
    const btns = [...pageEl.querySelectorAll('.wn-copy-btn')];
    // Five items in fixture all have exact_command set.
    expect(btns.length).toBe(fixture.items.length);
    const cmds = btns.map((b) => b.dataset.command);
    expect(cmds).toContain('dontpanic ps');
    expect(cmds).toContain('dontpanic architecture regen');
  });

  it('renders automatable vs human-required labels', () => {
    expect(pageEl.querySelector('.wn-role-chip--auto')).not.toBeNull();
    expect(pageEl.querySelector('.wn-role-chip--human')).not.toBeNull();
  });

  it('renders evidence URIs when present', () => {
    const evidence = [...pageEl.querySelectorAll('.wn-evidence-uri')].map((el) => el.textContent);
    expect(evidence.some((u) => u.includes('audit/gate-state.json'))).toBe(true);
  });

  it('places the gate card before the capability card within needs_action (acceptance #1: gates first)', () => {
    const needsAction = pageEl.querySelector('[data-band="needs_action"]');
    const sources = [...needsAction.querySelectorAll('.wn-card')].map((c) => c.dataset.source);
    expect(sources[0]).toBe('gate');
    expect(sources.indexOf('reconcile')).toBeLessThan(sources.indexOf('capability'));
  });

  it('does NOT render drag/drop, kanban, or mutation affordances (acceptance #5)', () => {
    expect(pageEl.querySelector('[draggable="true"]')).toBeNull();
    const html = pageEl.innerHTML.toLowerCase();
    expect(html).not.toContain('kanban');
    expect(html).not.toContain('drop-zone');
    expect(html).not.toContain('drag-handle');
  });

  it('renders a summary strip with band counts', () => {
    const chips = [...pageEl.querySelectorAll('.wn-summary-chip')];
    expect(chips.length).toBe(4);
    const text = pageEl.querySelector('.wn-summary-strip').textContent;
    // 3 needs_action / 1 advisory / 1 info / 0 ready in the fixture.
    expect(text).toMatch(/3\s*Needs action/i);
    expect(text).toMatch(/1\s*Advisory/i);
    expect(text).toMatch(/1\s*Info/i);
    expect(text).toMatch(/0\s*Ready/i);
  });
});

// ── Real page-module registration smoke + copy-command behavior ────────
//
// The page-module IIFE evaluates once per Vitest module-cache lifetime, so
// the registration smoke and the copy-button click test share the same
// `jarvisShim` — replacing it mid-suite would orphan the registered page.

describe('what-now: real page module registration', () => {
  const jarvisShim = {
    pages: [],
    state: { whatNow: null },
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
    await import('../../pages/what-now/what-now.js');
    registeredPage = jarvisShim.pages[0];
  });

  beforeEach(() => {
    setupDOM();
    globalThis.Jarvis = jarvisShim;
    window.Jarvis = jarvisShim;
  });

  it('registers a single What Now page with the router', () => {
    expect(jarvisShim.pages).toHaveLength(1);
    expect(registeredPage.id).toBe('what-now');
    expect(registeredPage.label).toBe('What Now');
    expect(typeof registeredPage.init).toBe('function');
    expect(typeof registeredPage.onActivate).toBe('function');
  });

  it('init() renders the missing-cache empty state when state.whatNow is null', () => {
    registeredPage.init({ whatNow: null });
    const el = jarvisShim.getPageEl('what-now');
    expect(el.querySelector('[data-state="missing"]')).not.toBeNull();
    expect(el.textContent).toContain('dontpanic dashboard build');
  });

  it('flows fetch(state/what-now.json) → state.whatNow → page render', async () => {
    setupFetchMock({ 'what-now': fixture });
    const resp = await fetch('state/what-now.json');
    expect(resp.ok).toBe(true);
    jarvisShim.state.whatNow = await resp.json();

    registeredPage.init(jarvisShim.state);

    const el = jarvisShim.getPageEl('what-now');
    expect(el.querySelector('[data-state="missing"]')).toBeNull();
    const cards = el.querySelectorAll('.wn-card');
    expect(cards.length).toBe(fixture.items.length);
  });

  it('onActivate() re-renders when state.whatNow updates after init', () => {
    registeredPage.init({ whatNow: null });
    const el = jarvisShim.getPageEl('what-now');
    expect(el.querySelector('[data-state="missing"]')).not.toBeNull();

    registeredPage.onActivate({ whatNow: fixture });
    expect(el.querySelector('[data-state="missing"]')).toBeNull();
    expect(el.querySelectorAll('.wn-card').length).toBe(fixture.items.length);
  });

  it('renders the F004 fleet view when fleetWhatNow is present and All Projects is selected', () => {
    registeredPage.init({
      whatNow: fixture,
      fleetWhatNow,
      fleetSummary,
      selectedProject: 'all',
    });
    const el = jarvisShim.getPageEl('what-now');
    expect(el.querySelector('[data-status-header="1"]')).not.toBeNull();
    expect(el.textContent).toContain('What Now — All Projects');
    expect(el.querySelector('[data-project="spindine"]')).not.toBeNull();
    expect(el.querySelector('[data-project="glam"]')).not.toBeNull();
  });

  it('renders the F004 project-filtered view when a project is selected', () => {
    registeredPage.init({
      whatNow: fixture,
      fleetWhatNow,
      fleetSummary,
      selectedProject: 'spindine',
    });
    const el = jarvisShim.getPageEl('what-now');
    expect(el.querySelector('[data-status-header="1"]')).not.toBeNull();
    expect(el.querySelector('[data-action-id="gate:spin"]')).not.toBeNull();
    expect(el.querySelector('[data-action-id="capability:linear"]')).not.toBeNull();
    expect(el.querySelector('[data-action-id="capability:firebase-dashboard"]')).not.toBeNull();
    expect(el.querySelector('[data-action-id="arch:glam"]')).toBeNull();
  });

  // ── Copy-command behavior — runs against the same shared page so the
  //    IIFE-registered handler attaches against the live `_el` closure.

  it('writes the raw command string to navigator.clipboard on copy-button click', () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(globalThis.navigator, 'clipboard', {
      value: { writeText },
      configurable: true,
    });

    registeredPage.init({ whatNow: fixture });
    const el = jarvisShim.getPageEl('what-now');
    const firstBtn = el.querySelector('.wn-copy-btn');
    expect(firstBtn).not.toBeNull();
    const expectedCmd = firstBtn.dataset.command;
    expect(expectedCmd).toBeTruthy();

    firstBtn.click();
    expect(writeText).toHaveBeenCalledWith(expectedCmd);
  });
});
