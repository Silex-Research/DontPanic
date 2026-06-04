// ── Config Inventory Logic — Unit Tests (plan 2026-05-30-001 F013) ──
//
// Proves the dashboard actually RENDERS the F008 inventory as Settings/Setup
// cards (not merely a state blob), covering F013 acceptance (5):
//   * cards render for >=10 providers
//   * active vs inactive dashboard-hint auto-detection
//   * exactly one response-level dashboard hint; cards reference it
//   * no build/start/serve command renders as an edit affordance

import { describe, it, expect, beforeEach } from 'vitest';
import { setupDOM } from '../helpers/setup.js';
import {
  renderConfigInventoryHTML,
  hasInventory,
  resolveConfigInventory,
  isMissingSelectedProjectInventory,
} from '../../lib/config-inventory-logic.js';
import fixture from '../fixtures/config-inventory.json' with { type: 'json' };

function renderToContainer(state) {
  const div = document.createElement('div');
  div.innerHTML = renderConfigInventoryHTML(state);
  return div;
}

beforeEach(() => {
  setupDOM();
});

// ── (1)+(5) cards render for >=10 providers ──────────────────────────────────

describe('config inventory: cards render for >=10 providers', () => {
  it('renders one card per inventory provider (>=10)', () => {
    const el = renderToContainer(fixture);
    const cards = el.querySelectorAll('.ci-card');
    const total = fixture.settings_cards.length + fixture.setup_cards.length;
    expect(total).toBeGreaterThanOrEqual(10);
    expect(cards.length).toBe(total);
  });

  it('renders a card per provider id the CLI inventory shows', () => {
    const el = renderToContainer(fixture);
    const renderedIds = [...el.querySelectorAll('.ci-card')].map(
      (c) => c.dataset.cardId,
    );
    const fixtureIds = [...fixture.settings_cards, ...fixture.setup_cards].map(
      (c) => c.id,
    );
    for (const id of fixtureIds) {
      expect(renderedIds).toContain(id);
    }
  });

  it('renders each card title + status badge (not a raw JSON blob)', () => {
    const el = renderToContainer(fixture);
    const all = [...fixture.settings_cards, ...fixture.setup_cards];
    for (const card of all) {
      const node = el.querySelector(`[data-card-id="${card.id}"]`);
      expect(node).not.toBeNull();
      expect(node.querySelector('.ci-card-title').textContent).toContain(card.title);
      expect(node.querySelector('.ci-status-badge')).not.toBeNull();
    }
  });

  it('splits incomplete surfaces into a Setup section, configured into Settings', () => {
    const el = renderToContainer(fixture);
    const setup = el.querySelector('.ci-section--setup');
    const settings = el.querySelector('.ci-section--settings');
    if (fixture.setup_cards.length) {
      expect(setup).not.toBeNull();
      expect(setup.querySelectorAll('.ci-card').length).toBe(fixture.setup_cards.length);
    }
    if (fixture.settings_cards.length) {
      expect(settings).not.toBeNull();
      expect(settings.querySelectorAll('.ci-card').length).toBe(
        fixture.settings_cards.length,
      );
    }
  });
});

// ── (2) active / inactive dashboard hint auto-detection ──────────────────────

describe('config inventory: dashboard hint auto-detection', () => {
  it('renders the active_url when a dashboard singleton is running', () => {
    const running = {
      ...fixture,
      dashboard_hint: {
        hint_id: 'config-inventory-dashboard',
        is_running: true,
        active_url: 'http://127.0.0.1:8732/',
        start_command: null,
        text: 'Dashboard is running — open http://127.0.0.1:8732/',
      },
    };
    const el = renderToContainer(running);
    const hint = el.querySelector('#ci-dashboard-hint');
    expect(hint).not.toBeNull();
    expect(hint.dataset.running).toBe('1');
    expect(hint.textContent).toContain('http://127.0.0.1:8732/');
    const link = hint.querySelector('.ci-hint-link');
    expect(link).not.toBeNull();
    expect(link.getAttribute('href')).toBe('http://127.0.0.1:8732/');
    // Falls-back start command must NOT be advertised while running.
    expect(hint.textContent).not.toContain('dontpanic dashboard serve');
  });

  it('falls back to the start command when no dashboard is running', () => {
    const el = renderToContainer(fixture); // fixture hint is is_running:false
    const hint = el.querySelector('#ci-dashboard-hint');
    expect(hint).not.toBeNull();
    expect(hint.dataset.running).toBe('0');
    expect(hint.textContent).toContain('dontpanic dashboard serve');
  });
});

// ── (3) exactly one response-level hint; items reference it ───────────────────

describe('config inventory: single dashboard hint, referenced not repeated', () => {
  it('renders exactly one response-level dashboard hint element', () => {
    const el = renderToContainer(fixture);
    expect(el.querySelectorAll('#ci-dashboard-hint').length).toBe(1);
    expect(el.querySelectorAll('.ci-dashboard-hint').length).toBe(1);
  });

  it('human-required cards reference the hint id; never repeat the hint text', () => {
    const el = renderToContainer(fixture);
    const hintText = fixture.dashboard_hint.text;
    const humanCards = [...fixture.settings_cards, ...fixture.setup_cards].filter(
      (c) => c.human_required,
    );
    expect(humanCards.length).toBeGreaterThan(0);
    for (const card of humanCards) {
      const node = el.querySelector(`[data-card-id="${card.id}"]`);
      const ref = node.querySelector('.ci-hint-ref');
      expect(ref).not.toBeNull();
      expect(ref.dataset.hintRef).toBe(card.dashboard_hint_ref);
      // The card must NOT embed the full response-level hint text.
      expect(node.textContent).not.toContain(hintText);
    }
    // The full hint text appears exactly once across the whole render.
    const occurrences = el.textContent.split(hintText).length - 1;
    expect(occurrences).toBe(1);
  });
});

// ── (4) edit affordance vs run-action distinction ────────────────────────────

describe('config inventory: edit affordance vs run-action', () => {
  const RUN_VERBS = ['build', 'serve', 'open', 'start'];
  const isRunAction = (cmd) =>
    !!cmd && cmd.split(/\s+/).some((tok) => RUN_VERBS.includes(tok));

  it('never renders a build/start/serve command as an edit affordance', () => {
    const el = renderToContainer(fixture);
    const editCmds = [...el.querySelectorAll('.ci-edit-command')].map((n) =>
      n.textContent.trim(),
    );
    for (const cmd of editCmds) {
      expect(isRunAction(cmd)).toBe(false);
    }
  });

  it('renders build/serve surfaces distinctly under run-action, not edit', () => {
    const el = renderToContainer(fixture);
    const dash = el.querySelector('[data-card-id="dashboard"]');
    expect(dash).not.toBeNull();
    // No edit command on a run-action-only surface.
    expect(dash.querySelector('.ci-edit-command')).toBeNull();
    const dashRun = dash.querySelector('.ci-run-action');
    expect(dashRun).not.toBeNull();
    expect(dashRun.textContent).toContain('dontpanic dashboard build');

    const mcp = el.querySelector('[data-card-id="mcp"]');
    expect(mcp).not.toBeNull();
    expect(mcp.querySelector('.ci-edit-command')).toBeNull();
    expect(mcp.querySelector('.ci-run-action').textContent).toContain(
      'dontpanic mcp serve',
    );
  });

  it('every rendered run-action command IS a run-action verb', () => {
    const el = renderToContainer(fixture);
    const runCmds = [...el.querySelectorAll('.ci-run-action')].map((n) =>
      n.textContent.trim(),
    );
    expect(runCmds.length).toBeGreaterThan(0);
    for (const cmd of runCmds) {
      expect(isRunAction(cmd)).toBe(true);
    }
  });
});

// ── empty state + guards ─────────────────────────────────────────────────────

describe('config inventory: empty / missing state', () => {
  it('hasInventory is false for null / non-inventory / empty', () => {
    expect(hasInventory(null)).toBe(false);
    expect(hasInventory(undefined)).toBe(false);
    expect(hasInventory({ kind: 'something_else' })).toBe(false);
    expect(hasInventory({ kind: 'config_inventory', settings_cards: [], setup_cards: [] })).toBe(false);
  });

  it('renders an actionable empty state when the projection is absent', () => {
    const el = renderToContainer(null);
    expect(el.querySelector('.ci-empty-state')).not.toBeNull();
    expect(el.textContent).toContain('dontpanic dashboard build');
    expect(el.textContent).toContain('config-inventory.json');
    expect(el.querySelector('.ci-card')).toBeNull();
  });
});

// ── XSS resistance — card strings are injected via innerHTML ──────────────────

describe('config inventory: HTML escape resistance', () => {
  it('escapes special chars in card fields', () => {
    const malicious = {
      kind: 'config_inventory',
      project_name: null,
      project_path: null,
      dashboard_hint: null,
      settings_cards: [
        {
          id: 'safe-id',
          title: '<script>alert(1)</script>',
          scope: 'machine',
          status: 'ok',
          optional: false,
          editable: true,
          human_required: false,
          summary: '<img onerror=1>',
          owner: 'owner',
          edit: { command: null, command_template: null },
          run_action: null,
          safe_command: null,
          dashboard_hint_ref: null,
          detail: null,
        },
      ],
      setup_cards: [],
    };
    const el = renderToContainer(malicious);
    // Payloads live in text-rendered fields (title/summary) — no live nodes,
    // but the escaped text still appears.
    expect(el.querySelector('script')).toBeNull();
    expect(el.querySelector('img')).toBeNull();
    expect(el.textContent).toContain('<script>alert(1)</script>');
    expect(el.textContent).toContain('<img onerror=1>');
  });
});

// ── (codex i1) per-project envelope resolution ───────────────────────────────
//
// Project + fleet builds mirror each project's inventory under
// `state/projects/<name>/config-inventory.json`. When a concrete project is
// selected, Settings must render THAT project's inventory — not the top-level
// (machine-scope) blob.

describe('config inventory: per-project resolution', () => {
  const alpha = { ...fixture, project_name: 'alpha' };
  const beta = { ...fixture, project_name: 'beta' };

  it('uses the top-level inventory when "all" (fleet) is selected', () => {
    const single = { ...fixture, project_name: null };
    const resolved = resolveConfigInventory({
      selectedProject: 'all',
      single,
      byProject: { alpha, beta },
    });
    expect(resolved).toBe(single);
  });

  it('returns the per-project inventory when a concrete project is selected', () => {
    const resolved = resolveConfigInventory({
      selectedProject: 'alpha',
      single: { ...fixture, project_name: null },
      byProject: { alpha, beta },
    });
    expect(resolved).toBe(alpha);
    expect(resolved.project_name).toBe('alpha');
  });

  it('does NOT fall back to top-level when the selected project is missing from the cache', () => {
    const single = { ...fixture, project_name: null };
    const resolved = resolveConfigInventory({
      selectedProject: 'gamma',
      single,
      byProject: { alpha, beta },
    });
    // Returning null (not `single`) prevents rendering machine-scope as if it
    // were gamma's inventory.
    expect(resolved).toBeNull();
    expect(isMissingSelectedProjectInventory({
      selectedProject: 'gamma',
      byProject: { alpha, beta },
    })).toBe(true);
  });

  it('falls back to top-level when no per-project cache exists yet', () => {
    const single = { ...fixture, project_name: null };
    const resolved = resolveConfigInventory({
      selectedProject: 'alpha',
      single,
      byProject: {},
    });
    expect(resolved).toBe(single);
    expect(isMissingSelectedProjectInventory({
      selectedProject: 'alpha',
      byProject: {},
    })).toBe(false);
  });

  it('renders the selected project cards through the full resolve→render path', () => {
    const resolved = resolveConfigInventory({
      selectedProject: 'alpha',
      single: { ...fixture, project_name: null },
      byProject: { alpha },
    });
    const el = renderToContainer(resolved);
    const total = alpha.settings_cards.length + alpha.setup_cards.length;
    expect(total).toBeGreaterThanOrEqual(10);
    expect(el.querySelectorAll('.ci-card').length).toBe(total);
    expect(el.querySelector('.ci-scope-label').textContent).toContain('alpha');
  });
});
