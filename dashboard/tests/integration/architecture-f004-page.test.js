// F004 integration tests for the Architecture page module.
//
// Verifies:
//   - When state has architectureViewStateByProject populated, "All
//     Projects" selection renders the fleet card grid (not a merged
//     single-repo graph).
//   - Per-project selection still renders the F003 explorer plus the
//     new F004 summary cards and insights panel.
//   - Clicking a fleet card's "Open map" button switches the selector
//     via the shell's setSelectedProject helper (or a state fallback)
//     and re-renders the page.
//   - Missing project architecture renders the empty card with the
//     regen instructions for that repo.

import { describe, it, expect, beforeAll, beforeEach } from 'vitest';
import { setupDOM } from '../helpers/setup.js';
import fixture from '../fixtures/architecture-view-state-f004.json' with { type: 'json' };

const jarvisShim = {
  pages: [],
  state: { architectureViewState: null, selectedProject: 'all' },
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
  setSelectedProject(name) {
    this._lastSetSelection = name;
    this.state.selectedProject = name;
    const active = this.pages.find((p) => p.id === 'architecture');
    if (active && active.onActivate) active.onActivate(this.state);
  },
};
let page;

beforeAll(async () => {
  setupDOM();
  globalThis.Jarvis = jarvisShim;
  window.Jarvis = jarvisShim;
  await import('../../pages/architecture/architecture.js');
  page = jarvisShim.pages[0];
});

beforeEach(() => {
  setupDOM();
  globalThis.Jarvis = jarvisShim;
  window.Jarvis = jarvisShim;
});

const projectA = {
  ...fixture,
  project: { name: 'projecta', display_name: 'Project A', label: 'Project A' },
};
const projectB = {
  ...fixture,
  project: { name: 'projectb', display_name: 'Project B', label: 'Project B' },
};

describe('architecture page — F004 summary cards + insights', () => {
  it('renders summary cards and insights panel in the populated state', () => {
    page.init({
      architectureViewState: fixture,
      selectedProject: 'all',
      architectureViewStateByProject: {},
      fleetSummary: null,
    });
    const el = jarvisShim.getPageEl('architecture');
    expect(el.querySelector('[data-summary="1"]')).not.toBeNull();
    expect(el.querySelector('[data-card="modules"]')).not.toBeNull();
    expect(el.querySelector('[data-card="freshness"]')).not.toBeNull();
    expect(el.querySelector('[data-insights-detail="1"]')).not.toBeNull();
    expect(el.querySelector('[data-insight="high-fan-out"]')).not.toBeNull();
    expect(el.querySelector('[data-project-context="1"]')).not.toBeNull();
  });
});

describe('architecture page — All Projects fleet view (F004)', () => {
  it('routes to fleet cards when byProject is populated under All Projects', () => {
    page.init({
      architectureViewState: null,
      architectureViewStateByProject: { projecta: projectA, projectb: projectB },
      fleetSummary: {
        projects: [
          { name: 'projecta', display_name: 'Project A', active: true },
          { name: 'projectb', display_name: 'Project B', active: true },
        ],
      },
      selectedProject: 'all',
    });
    const el = jarvisShim.getPageEl('architecture');
    expect(el.querySelector('[data-fleet="1"]')).not.toBeNull();
    expect(el.querySelectorAll('[data-fleet-card]').length).toBe(2);
    // No merged canvas in the fleet view.
    expect(el.querySelector('[data-canvas]')).toBeNull();
    expect(el.querySelector('[data-explorer="1"]')).toBeNull();
  });

  it('renders missing-project card when an entry has no architecture artifact', () => {
    page.init({
      architectureViewState: null,
      architectureViewStateByProject: { projecta: projectA },
      fleetSummary: {
        projects: [
          { name: 'projecta', display_name: 'Project A', active: true },
          { name: 'unbuilt', display_name: 'Unbuilt repo', active: true },
        ],
      },
      selectedProject: 'all',
    });
    const el = jarvisShim.getPageEl('architecture');
    const emptyCard = el.querySelector('[data-fleet-card="unbuilt"]');
    expect(emptyCard).not.toBeNull();
    expect(emptyCard.classList.contains('arch-fleet-card--empty')).toBe(true);
    expect(emptyCard.textContent).toContain('dontpanic architecture regen');
    expect(emptyCard.textContent).toContain('dontpanic dashboard build --project unbuilt');
  });

  it('clicking "Open map" delegates to Jarvis.setSelectedProject', () => {
    jarvisShim.state = {
      architectureViewState: null,
      architectureViewStateByProject: { projecta: projectA },
      fleetSummary: { projects: [{ name: 'projecta', display_name: 'Project A', active: true }] },
      selectedProject: 'all',
    };
    page.init(jarvisShim.state);
    jarvisShim._lastSetSelection = null;
    const el = jarvisShim.getPageEl('architecture');
    const btn = el.querySelector('[data-arch-open-project="projecta"]');
    expect(btn).not.toBeNull();
    btn.click();
    expect(jarvisShim._lastSetSelection).toBe('projecta');
    // After setSelectedProject fires onActivate, the page should now
    // render the populated single-project view for projecta.
    expect(el.querySelector('[data-fleet="1"]')).toBeNull();
    expect(el.querySelector('[data-explorer="1"]')).not.toBeNull();
  });

  it('falls back to single-project explorer when All Projects is selected with no per-project caches', () => {
    page.init({
      architectureViewState: fixture,
      architectureViewStateByProject: {},
      fleetSummary: null,
      selectedProject: 'all',
    });
    const el = jarvisShim.getPageEl('architecture');
    expect(el.querySelector('[data-fleet="1"]')).toBeNull();
    expect(el.querySelector('[data-explorer="1"]')).not.toBeNull();
  });
});

describe('architecture page — selected-project missing state (F004 i1 finding #1 + #3)', () => {
  it('renders missing-project card (not another project\'s map) when byProject lacks the selected entry', () => {
    page.init({
      // `single` is populated with projectA's data — the page must NOT
      // fall back to it when the selector points at "unbuilt".
      architectureViewState: projectA,
      architectureViewStateByProject: { projecta: projectA },
      fleetSummary: {
        projects: [
          { name: 'projecta', display_name: 'Project A', active: true },
          { name: 'unbuilt', display_name: 'Unbuilt repo', active: true },
        ],
      },
      selectedProject: 'unbuilt',
    });
    const el = jarvisShim.getPageEl('architecture');
    const card = el.querySelector('[data-empty-state="missing-project"]');
    expect(card).not.toBeNull();
    expect(card.dataset.missingProject).toBe('unbuilt');
    expect(card.textContent).toContain('Unbuilt repo');
    expect(card.textContent).toContain('dontpanic architecture regen');
    expect(card.textContent).toContain('dontpanic dashboard build --project unbuilt');
    // Critical: no explorer/canvas/insights borrowed from projectA.
    expect(el.querySelector('[data-explorer="1"]')).toBeNull();
    expect(el.querySelector('[data-canvas]')).toBeNull();
    expect(el.querySelector('[data-insights-detail="1"]')).toBeNull();
    expect(el.querySelector('[data-fleet="1"]')).toBeNull();
  });

  it('does not bleed projectA node IDs into the missing-project view', () => {
    page.init({
      architectureViewState: projectA,
      architectureViewStateByProject: { projecta: projectA },
      fleetSummary: {
        projects: [{ name: 'unbuilt', display_name: 'Unbuilt repo', active: true }],
      },
      selectedProject: 'unbuilt',
    });
    const el = jarvisShim.getPageEl('architecture');
    // ProjectA's fixture has this distinct node id — it must not leak.
    expect(el.textContent).not.toContain('dontpanic_orchestrate/cli.py');
  });
});

describe('architecture page — project context (F004 acceptance #3)', () => {
  it('shows the selected project context block above the freshness banner', () => {
    page.init({
      architectureViewState: projectA,
      architectureViewStateByProject: { projecta: projectA },
      fleetSummary: { projects: [{ name: 'projecta', display_name: 'Project A', active: true }] },
      selectedProject: 'projecta',
    });
    const el = jarvisShim.getPageEl('architecture');
    const ctx = el.querySelector('[data-project-context="1"]');
    expect(ctx).not.toBeNull();
    expect(ctx.dataset.scope).toBe('project');
    expect(ctx.textContent).toContain('Project A');
    expect(ctx.textContent).toContain('projecta');
  });
});
