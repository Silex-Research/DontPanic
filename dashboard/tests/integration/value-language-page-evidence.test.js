// F004 evidence tests — value-language labels, provenance footers,
// optional-chip handling, and missing-data states across every V0 page.
//
// Plan: 2026-05-24-001-feat-dashboard-value-language-ia-v0 (F004).
//
// Each test renders a page's logic into a DOM container and asserts that:
//   1. Layer 1 / first-read text uses value-first labels (no forbidden tokens).
//   2. A standardized provenance footer is present (data-provenance="1").
//   3. The four-band status taxonomy is preserved; `optional` renders as a
//      relevance chip rather than a fifth status color.
//   4. Missing-data states render honestly — they name the absent file and
//      do NOT collapse into a healthy "all clear" message.

import { describe, it, expect, beforeEach } from 'vitest';
import { setupDOM } from '../helpers/setup.js';

import { renderWhatNowHTML } from '../../lib/what-now-logic.js';
import { renderCapabilityCenterHTML } from '../../lib/capabilities-logic.js';
import { renderHealthHTML } from '../../lib/health-logic.js';
import { renderProvenanceFooterHTML, hasProvenanceFooter } from '../../lib/provenance.js';
import { renderWorkProvenanceHTML, deriveWorkLastUpdated } from '../../lib/mission-control-logic.js';
import {
  FORBIDDEN_FIRST_READ_TOKENS,
  scanForFirstReadViolations,
} from '../../lib/value-language-static-checks.js';

import whatNowFixture from '../fixtures/what-now.json' with { type: 'json' };
import capabilitiesFixture from '../fixtures/capabilities-status.json' with { type: 'json' };
import tasksFixture from '../fixtures/tasks.json' with { type: 'json' };
import agentsFixture from '../fixtures/agents.json' with { type: 'json' };
import activityFixture from '../fixtures/activity.json' with { type: 'json' };

function renderInto(html) {
  const container = document.createElement('div');
  container.innerHTML = html;
  return container;
}

// Layer 1 is the first-read region: page titles, value-first kind labels,
// and band/status badges. Impact/subtitle text and footers are Layer 2 —
// they may legitimately reference upstream provider titles (e.g. "Gate
// pre_merge needs approval") and state-file paths (e.g. quota.json) as
// part of the deliberate value→technical disclosure ordering.
function extractLayer1Text(root) {
  const layer1Selectors = [
    'h1', 'h2', 'h3',
    '.wn-card-kind', '.wn-empty-title', '.wn-quiet-title',
    '.wn-band-badge', '.wn-summary-chip-label',
    '.cap-card-kind', '.cap-empty-title',
    '.cap-relevance-chip',
    '.hlth-card-kind',
    '.scope-badge-value',
  ];
  const chunks = [];
  for (const sel of layer1Selectors) {
    for (const el of root.querySelectorAll(sel)) {
      chunks.push(el.textContent);
    }
  }
  return chunks.join('\n');
}

beforeEach(() => {
  setupDOM();
});

// ─────────────────────────────────────────────────────────────────────────
// Needs Attention (what-now)
// ─────────────────────────────────────────────────────────────────────────

describe('F004: Needs Attention page', () => {
  it('renders a provenance footer in the missing-cache state', () => {
    const root = renderInto(renderWhatNowHTML(null));
    expect(root.querySelector('[data-provenance="1"]')).not.toBeNull();
    expect(root.textContent).toContain('dashboard/state/what-now.json');
    expect(root.textContent).toContain('dontpanic dashboard build');
  });

  it('renders a provenance footer when populated', () => {
    const root = renderInto(renderWhatNowHTML(whatNowFixture));
    expect(root.querySelector('[data-provenance="1"]')).not.toBeNull();
    // The populated provenance footer must surface the captured_at value
    // so the operator can see "how fresh is this cache?"
    expect(root.textContent).toContain('2026-05-23');
  });

  it('exposes value-first headlines and no forbidden first-read tokens on the populated state', () => {
    const root = renderInto(renderWhatNowHTML(whatNowFixture));
    // Spot-check the F003 value-first kind labels.
    const kindText = [...root.querySelectorAll('.wn-card-kind')]
      .map((el) => el.textContent.trim());
    expect(kindText).toContain('Approval needed');
    expect(kindText.some((t) => t.startsWith('Setup'))).toBe(true);
    // No forbidden first-read tokens in Layer 1 text. The impact line is
    // Layer 2 (it surfaces the upstream provider's exact title verbatim,
    // e.g. "Gate pre_merge needs approval") and is intentionally excluded
    // here — see the module-level extractLayer1Text comment.
    const layer1 = [...root.querySelectorAll('.wn-card-kind, h2, .wn-summary-chip-label')]
      .map((el) => el.textContent).join('\n');
    const violations = scanForFirstReadViolations(layer1);
    expect(
      violations,
      `forbidden tokens in Needs Attention Layer 1: ${JSON.stringify(violations)}`,
    ).toEqual([]);
  });

  it('preserves exact CLI commands as Layer-2 disclosure', () => {
    const root = renderInto(renderWhatNowHTML(whatNowFixture));
    const codes = [...root.querySelectorAll('.wn-cmd code')].map((c) => c.textContent);
    // The fixture's gate command must survive into a copyable code block.
    expect(codes).toContain('dontpanic approve 2026-05-23-004-feat-operator-console-v0 pre_merge');
    // And every command must have a copy button with the raw command payload.
    const copyCmds = [...root.querySelectorAll('.wn-copy-btn')].map((b) => b.dataset.command);
    expect(copyCmds).toContain('dontpanic approve 2026-05-23-004-feat-operator-console-v0 pre_merge');
  });

  it('missing-cache state does not collapse into a healthy "all clear"', () => {
    const root = renderInto(renderWhatNowHTML(null));
    const text = root.textContent.toLowerCase();
    expect(text).not.toContain('all clear');
    expect(text).not.toContain('no action needed');
    expect(text).toContain('no what-now cache yet');
  });
});

// ─────────────────────────────────────────────────────────────────────────
// Tools & Setup (capabilities)
// ─────────────────────────────────────────────────────────────────────────

describe('F004: Tools & Setup page', () => {
  it('renders a provenance footer in the missing-snapshot state', () => {
    const root = renderInto(renderCapabilityCenterHTML(null));
    expect(root.querySelector('[data-provenance="1"]')).not.toBeNull();
    expect(root.textContent).toContain('dashboard/state/capabilities-status.json');
  });

  it('renders a provenance footer when populated', () => {
    const root = renderInto(renderCapabilityCenterHTML(capabilitiesFixture));
    expect(root.querySelector('[data-provenance="1"]')).not.toBeNull();
  });

  it('renders value-first headlines for every status (incl. optional as relevance chip)', () => {
    // Synthetic envelope spanning every status the page renders, including
    // the `optional` status which must render as a relevance chip, NOT a
    // fifth status pill (preserves the four-band taxonomy).
    const env = {
      schema_version: '1.0.0',
      generated_at: '2026-05-23T04:00:00Z',
      advisory_notes: [],
      capabilities: [
        { capability_id: 'git', status: 'ready' },
        { capability_id: 'firebase-dashboard', status: 'needs_setup' },
        { capability_id: 'linear', status: 'blocked' },
        { capability_id: 'discord', status: 'not_installed' },
        { capability_id: 'optional-tool', status: 'optional' },
      ],
    };
    const root = renderInto(renderCapabilityCenterHTML(env));
    const kindText = [...root.querySelectorAll('.cap-card-kind')]
      .map((el) => el.textContent.trim());
    expect(kindText).toContain('Connected');
    expect(kindText).toContain('Setup required');
    expect(kindText).toContain('Blocked');
    expect(kindText).toContain('Not installed');
    expect(kindText).toContain('Optional for this project');
    // optional renders as a relevance chip, not a status badge.
    const relevanceChips = root.querySelectorAll('.cap-relevance-chip');
    expect(relevanceChips.length).toBe(1);
    expect(relevanceChips[0].textContent).toContain('Optional for this project');
    // The card for `optional-tool` must NOT carry a status-badge pill.
    const optionalCard = root.querySelector('[data-capability-id="optional-tool"]');
    expect(optionalCard).not.toBeNull();
    expect(optionalCard.querySelector('.cap-status-badge')).toBeNull();
  });

  it('has no forbidden first-read tokens in Layer 1 text', () => {
    const root = renderInto(renderCapabilityCenterHTML(capabilitiesFixture));
    const layer1 = extractLayer1Text(root);
    const violations = scanForFirstReadViolations(layer1, FORBIDDEN_FIRST_READ_TOKENS);
    expect(
      violations,
      `forbidden tokens in Tools & Setup Layer 1: ${JSON.stringify(violations)}`,
    ).toEqual([]);
  });
});

// ─────────────────────────────────────────────────────────────────────────
// Health (empty state + provenance)
// ─────────────────────────────────────────────────────────────────────────

describe('F004: Health page', () => {
  it('renders the page-level provenance footer in the all-missing state', () => {
    const html = renderHealthHTML({
      capabilities: null, whatNow: null, security: null, quota: null,
      fleetSummary: null, selectedProject: 'all',
    });
    expect(hasProvenanceFooter(html)).toBe(true);
    expect(html).toContain('dashboard/state/*.json');
  });

  it('renders per-card missing-data states honestly (no "all clear" without data)', () => {
    const root = renderInto(renderHealthHTML({
      capabilities: null, whatNow: null, security: null, quota: null,
      fleetSummary: null, selectedProject: 'all',
    }));
    const text = root.textContent;
    expect(text).toContain('Install readiness — no data yet');
    expect(text).toContain('Setup drift — no data yet');
    expect(text).toContain('Security hooks — no data yet');
    expect(text).toContain('Budget guardrail — no data yet');
    expect(text).toContain('Fleet warnings — no data yet');
    // Must not falsely declare health when data is absent.
    expect(text.toLowerCase()).not.toContain('install is healthy');
    expect(text.toLowerCase()).not.toContain('budget guardrail clear');
  });

  it('has no forbidden first-read tokens in Layer 1 text', () => {
    const root = renderInto(renderHealthHTML({
      capabilities: null, whatNow: null, security: null, quota: null,
      fleetSummary: null, selectedProject: 'all',
    }));
    const layer1 = extractLayer1Text(root);
    const violations = scanForFirstReadViolations(layer1, FORBIDDEN_FIRST_READ_TOKENS);
    expect(
      violations,
      `forbidden tokens in Health Layer 1: ${JSON.stringify(violations)}`,
    ).toEqual([]);
  });
});

// ─────────────────────────────────────────────────────────────────────────
// Page-level provenance footer contract (every V0 surface)
// ─────────────────────────────────────────────────────────────────────────

describe('F004: every V0 page renders a provenance footer', () => {
  it('Needs Attention populated state', () => {
    expect(hasProvenanceFooter(renderWhatNowHTML(whatNowFixture))).toBe(true);
  });
  it('Needs Attention missing-cache state', () => {
    expect(hasProvenanceFooter(renderWhatNowHTML(null))).toBe(true);
  });
  it('Tools & Setup populated state', () => {
    expect(hasProvenanceFooter(renderCapabilityCenterHTML(capabilitiesFixture))).toBe(true);
  });
  it('Tools & Setup missing-snapshot state', () => {
    expect(hasProvenanceFooter(renderCapabilityCenterHTML(null))).toBe(true);
  });
  it('Health page', () => {
    expect(hasProvenanceFooter(renderHealthHTML({}))).toBe(true);
  });
  it('Work page populated state', () => {
    expect(hasProvenanceFooter(renderWorkProvenanceHTML({
      tasks: tasksFixture,
      agents: agentsFixture,
      activity: activityFixture,
    }))).toBe(true);
  });
  it('Work page empty state', () => {
    expect(hasProvenanceFooter(renderWorkProvenanceHTML({
      tasks: [], agents: [], activity: [],
    }))).toBe(true);
  });
  it('the Preferences page registers its own provenance footer via the helper', () => {
    // The settings page renders an `stg-source-footer` div above the
    // helper-rendered pv-footer. We don't rerun the IIFE here (page tests
    // do); instead we pin the helper contract that Preferences uses.
    const html = renderProvenanceFooterHTML({
      source: 'localStorage (this browser only)',
      lastUpdated: null,
      note: 'Preferences are browser-local.',
    });
    expect(hasProvenanceFooter(html)).toBe(true);
    expect(html).toContain('localStorage');
  });
});

// ─────────────────────────────────────────────────────────────────────────
// Work (mission-control) provenance
// ─────────────────────────────────────────────────────────────────────────

describe('F004: Work page provenance', () => {
  it('names the three Work state files and the refresh command', () => {
    const html = renderWorkProvenanceHTML({
      tasks: tasksFixture,
      agents: agentsFixture,
      activity: activityFixture,
    });
    expect(html).toContain('data-provenance="1"');
    expect(html).toContain('tasks.json');
    expect(html).toContain('agents.json');
    expect(html).toContain('activity.json');
    expect(html).toContain('dontpanic dashboard build');
  });

  it('surfaces the freshest task/activity timestamp as Updated', () => {
    const html = renderWorkProvenanceHTML({
      tasks: [{ id: 't1', created: '2026-03-22T20:00:00Z' }],
      agents: [],
      activity: [{ type: 'task', text: 'x', timestamp: '2026-03-22T22:00:00Z' }],
    });
    expect(html).toContain('2026-03-22T22:00:00Z');
  });

  it('falls back to "—" when no input carries a timestamp', () => {
    expect(deriveWorkLastUpdated({ tasks: [], agents: [], activity: [] })).toBeNull();
    const html = renderWorkProvenanceHTML({
      tasks: [{ id: 't1' }],
      agents: [{ id: 'claude' }],
      activity: [],
    });
    expect(html).toMatch(/Updated[\s\S]*—/);
  });

  it('honours the read-only note so reviewers know Work cannot mutate', () => {
    const html = renderWorkProvenanceHTML({
      tasks: tasksFixture, agents: agentsFixture, activity: activityFixture,
    });
    expect(html.toLowerCase()).toContain('read-only');
  });
});

// ─────────────────────────────────────────────────────────────────────────
// Real shell + Preferences render (proves the page modules actually
// emit the provenance footer in the loaded DOM, not just that the
// helper exists). Avoids dynamic-import side-effects by using the
// settings page module's exported helper contract.
// ─────────────────────────────────────────────────────────────────────────

describe('F004: real Preferences page render emits a provenance footer', () => {
  it('the page module wires the renderProvenanceFooterHTML helper into its template', async () => {
    // The Preferences module is an IIFE keyed off `Jarvis`. Stand up a
    // minimal shim so importing the file registers a page without
    // throwing, then drive init() and inspect the rendered DOM.
    setupDOM();
    const page = document.createElement('div');
    page.id = 'page-settings';
    document.getElementById('page-container').appendChild(page);

    // localStorage shim — jsdom provides one, but be defensive.
    if (!('localStorage' in globalThis)) {
      const store = {};
      globalThis.localStorage = {
        getItem: (k) => store[k] ?? null,
        setItem: (k, v) => { store[k] = String(v); },
        removeItem: (k) => { delete store[k]; },
        clear: () => { for (const k of Object.keys(store)) delete store[k]; },
      };
    }

    let registered = null;
    globalThis.Jarvis = {
      registerPage(cfg) { registered = cfg; },
      getPageEl(id) { return document.getElementById(`page-${id}`); },
    };

    await import('../../pages/settings/settings.js');
    expect(registered).not.toBeNull();
    expect(registered.label).toBe('Preferences');

    registered.init();

    const root = document.getElementById('page-settings');
    expect(root.querySelector('[data-provenance="1"]')).not.toBeNull();
    // Source row must name localStorage, not the misleading "*.json" path.
    expect(root.textContent).toContain('localStorage');
    // The Layer-2 honesty note must survive into the rendered DOM.
    expect(root.textContent.toLowerCase()).toContain('browser-local');
    // The four V0 tabs the shell registers — Financial / Cloud Costs must
    // not silently sneak back in as Preferences siblings. Preferences is
    // self-contained, so just assert nothing has hijacked the slot.
    expect(root.querySelector('.stg-layout')).not.toBeNull();
  });
});

// ─────────────────────────────────────────────────────────────────────────
// Real shell (core.js + nav) — proves the V0 nav surface matches the
// plan's surface table and that demo/noise tabs (Financial, Cloud Costs)
// stay out of the visible nav. The core module exposes createJarvis()
// for exactly this purpose.
// ─────────────────────────────────────────────────────────────────────────

describe('F004: real dashboard shell renders V0 nav only', () => {
  it('createJarvis() with the V0 page modules registers Needs Attention/Work/Tools & Setup/Health/Preferences', async () => {
    setupDOM();
    // Stub fetch so loadState's missing-file paths resolve quickly.
    globalThis.fetch = async () => ({ ok: false, status: 404, json: async () => null });

    const { createJarvis } = await import('../../core.js');
    const J = createJarvis();
    // Register every V0 page module's label by stubbing Jarvis and
    // importing each. We do this in declaration order to mirror core.js.
    const labels = [];
    globalThis.Jarvis = {
      registerPage(cfg) { labels.push(cfg.label); J.registerPage(cfg); },
      getPageEl(id) { return document.getElementById(`page-${id}`); },
    };

    // Reset module cache for the page modules so each IIFE re-registers
    // into this run's Jarvis stub. Vitest's vi.resetModules() would do
    // this globally; here we import via a fresh URL query suffix.
    const suffix = `?test=${Date.now()}`;
    await import('../../pages/what-now/what-now.js' + suffix);
    await import('../../pages/mission-control/mission-control.js' + suffix);
    await import('../../pages/capabilities/capabilities.js' + suffix);
    await import('../../pages/health/health.js' + suffix);
    await import('../../pages/settings/settings.js' + suffix);

    // V0 surface table (plan 2026-05-24-001 F002): exactly these five.
    expect(labels).toEqual([
      'Needs Attention',
      'Work',
      'Tools & Setup',
      'Health',
      'Preferences',
    ]);
    // Financial / Cloud Costs / Security must not register as core tabs.
    expect(labels).not.toContain('Financial');
    expect(labels).not.toContain('Cloud Costs');
    expect(labels).not.toContain('Security');
  });
});
