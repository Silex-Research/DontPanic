// Integration tests for the F002 Architecture page module.
//
// Verifies that:
//   - The page module registers itself as `architecture` with the
//     value-first nav label "Architecture".
//   - init() and onActivate() render through the shared
//     `renderArchitectureHTML` against `state.architectureViewState`.
//   - The missing-state empty card is produced when the cache is absent.
//   - The copy-button click handler writes the regen command to
//     navigator.clipboard (the dashboard never runs the command itself).

import { describe, it, expect, beforeAll, beforeEach, vi } from 'vitest';
import { setupDOM, setupFetchMock } from '../helpers/setup.js';
import { renderArchitectureHTML } from '../../lib/architecture-logic.js';
import fixture from '../fixtures/architecture-view-state.json' with { type: 'json' };

function makePageEl() {
  const container = document.getElementById('page-container');
  const div = document.createElement('div');
  div.id = 'page-architecture';
  div.className = 'page-view active';
  container.appendChild(div);
  return div;
}

beforeEach(() => {
  setupDOM();
});

describe('architecture: direct renderer', () => {
  it('renders the missing-state empty card when state.architectureViewState is null', () => {
    const el = makePageEl();
    el.innerHTML = renderArchitectureHTML(null);
    expect(el.querySelector('[data-empty-state="missing"]')).not.toBeNull();
    expect(el.textContent).toContain('dontpanic architecture regen --with-html');
    expect(el.textContent).toContain('dontpanic dashboard build');
  });

  it('renders the populated shell with the stale fixture', () => {
    const el = makePageEl();
    el.innerHTML = renderArchitectureHTML(fixture);
    expect(el.querySelector('[data-state="stale"]')).not.toBeNull();
    expect(el.querySelector('[data-freshness="stale"]')).not.toBeNull();
    expect(el.querySelector('.arch-title').textContent).toBe('Architecture');
    // F002 acceptance #6: validation warnings render as a visible panel
    // without crashing the page.
    expect(el.querySelector('[data-warnings="1"]')).not.toBeNull();
    expect(el.textContent).toContain('flow:authored-broken');
  });

  it('emits exactly one regen command + copy button in the stale banner', () => {
    const el = makePageEl();
    el.innerHTML = renderArchitectureHTML(fixture);
    const banner = el.querySelector('[data-freshness="stale"]');
    expect(banner).not.toBeNull();
    const cmds = [...banner.querySelectorAll('.arch-cmd code')].map((c) => c.textContent);
    expect(cmds).toContain('dontpanic architecture regen --with-html');
    const btns = [...banner.querySelectorAll('.arch-copy-btn')];
    expect(btns.length).toBe(1);
    expect(btns[0].dataset.command).toBe('dontpanic architecture regen --with-html');
  });

  it('uses value-first nav-style copy ("Architecture", "System Map") in Layer 1', () => {
    const el = makePageEl();
    el.innerHTML = renderArchitectureHTML(fixture);
    expect(el.textContent).toContain('Architecture');
    expect(el.textContent).toContain('System Map');
    // Operator question is value-first, not capability-id-first.
    expect(el.textContent).toContain('How is this system put together');
  });
});

// ── Real page-module registration + clipboard wiring ────────────────────

describe('architecture: page module registration', () => {
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
  };
  let registeredPage;

  beforeAll(async () => {
    setupDOM();
    globalThis.Jarvis = jarvisShim;
    window.Jarvis = jarvisShim;
    await import('../../pages/architecture/architecture.js');
    registeredPage = jarvisShim.pages[0];
  });

  beforeEach(() => {
    setupDOM();
    globalThis.Jarvis = jarvisShim;
    window.Jarvis = jarvisShim;
  });

  it('registers an Architecture page with the router (acceptance #1)', () => {
    expect(jarvisShim.pages).toHaveLength(1);
    expect(registeredPage.id).toBe('architecture');
    // F002 acceptance #2: primary nav label is value-first.
    expect(registeredPage.label).toBe('Architecture');
    expect(typeof registeredPage.init).toBe('function');
    expect(typeof registeredPage.onActivate).toBe('function');
  });

  it('init() renders the missing-state empty card when no view-state is loaded', () => {
    registeredPage.init({ architectureViewState: null, selectedProject: 'all' });
    const el = jarvisShim.getPageEl('architecture');
    expect(el.querySelector('[data-empty-state="missing"]')).not.toBeNull();
    expect(el.textContent).toContain('dontpanic architecture regen --with-html');
  });

  it('flows fetch(state/architecture-view-state.json) → state → render', async () => {
    setupFetchMock({ 'architecture-view-state': fixture });
    const resp = await fetch('state/architecture-view-state.json');
    expect(resp.ok).toBe(true);
    jarvisShim.state.architectureViewState = await resp.json();

    registeredPage.init(jarvisShim.state);

    const el = jarvisShim.getPageEl('architecture');
    expect(el.querySelector('[data-empty-state="missing"]')).toBeNull();
    expect(el.querySelector('[data-state="stale"]')).not.toBeNull();
  });

  it('onActivate() re-renders when state.architectureViewState updates', () => {
    registeredPage.init({ architectureViewState: null, selectedProject: 'all' });
    const el = jarvisShim.getPageEl('architecture');
    expect(el.querySelector('[data-empty-state="missing"]')).not.toBeNull();

    registeredPage.onActivate({ architectureViewState: fixture, selectedProject: 'all' });
    expect(el.querySelector('[data-empty-state="missing"]')).toBeNull();
    expect(el.querySelector('[data-state="stale"]')).not.toBeNull();
  });

  // ── Copy-command behavior — acceptance #4 (exact + copyable) ─────────

  it('writes the regen command to navigator.clipboard on copy-button click', () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(globalThis.navigator, 'clipboard', {
      value: { writeText },
      configurable: true,
    });

    registeredPage.init({ architectureViewState: fixture, selectedProject: 'all' });
    const el = jarvisShim.getPageEl('architecture');
    const firstBtn = el.querySelector('.arch-copy-btn');
    expect(firstBtn).not.toBeNull();
    expect(firstBtn.dataset.command).toBe('dontpanic architecture regen --with-html');

    firstBtn.click();
    expect(writeText).toHaveBeenCalledWith('dontpanic architecture regen --with-html');
  });

  it('does not expose drag/drop or run-command affordances (acceptance #5)', () => {
    registeredPage.init({ architectureViewState: fixture, selectedProject: 'all' });
    const el = jarvisShim.getPageEl('architecture');
    expect(el.querySelector('[draggable="true"]')).toBeNull();
    const html = el.innerHTML.toLowerCase();
    expect(html).not.toContain('kanban');
    expect(html).not.toContain('run-regen');
    expect(html).not.toContain('auto-regen');
  });

  // ── Per-project cache fallback (post-i0 finding #4) ─────────────────

  it('renders the per-project cache when selectedProject matches a project key', () => {
    const projectFixture = {
      ...fixture,
      project: { name: 'spindineswift', display_name: 'SpinDine', label: 'SpinDine' },
    };
    registeredPage.init({
      architectureViewState: null,
      architectureViewStateByProject: { spindineswift: projectFixture },
      selectedProject: 'spindineswift',
    });
    const el = jarvisShim.getPageEl('architecture');
    // The per-project envelope renders even though single-repo state is null;
    // missing-state card would have appeared if the resolver fell through.
    expect(el.querySelector('[data-empty-state="missing"]')).toBeNull();
    expect(el.querySelector('[data-state="stale"]')).not.toBeNull();
    expect(el.textContent).toContain('SpinDine');
  });

  it('falls back to single-repo envelope when no per-project cache exists', () => {
    registeredPage.init({
      architectureViewState: fixture,
      architectureViewStateByProject: {},
      selectedProject: 'unknownproject',
    });
    const el = jarvisShim.getPageEl('architecture');
    expect(el.querySelector('[data-state="stale"]')).not.toBeNull();
  });

  it('routes the F001 "absent" state to the missing-state card', () => {
    registeredPage.init({
      architectureViewState: {
        schema_version: '1.0',
        project: {},
        generated_at: '',
        source_path: 'docs/architecture/architecture.json',
        lanes: [],
        nodes: [],
        edges: [],
        flows: [],
        steps: [],
        filters: {},
        insights: [],
        validation_warnings: [],
        freshness: {
          state: 'absent',
          message: 'architecture.json was not found. Run the regen command to generate it.',
          regen_command: 'dontpanic architecture regen --with-html',
        },
      },
      selectedProject: 'all',
    });
    const el = jarvisShim.getPageEl('architecture');
    expect(el.querySelector('[data-freshness="absent"]')).not.toBeNull();
    expect(el.textContent).toContain('architecture.json was not found');
  });

  it('routes the F001 "error" state to the dedicated error card', () => {
    registeredPage.init({
      architectureViewState: {
        schema_version: '1.0',
        project: {},
        generated_at: '',
        source_path: 'docs/architecture/architecture.json',
        lanes: [],
        nodes: [],
        edges: [],
        flows: [],
        steps: [],
        filters: {},
        insights: [],
        validation_warnings: [],
        freshness: {
          state: 'error',
          message: 'architecture.json is unreadable: invalid JSON at byte 17',
          regen_command: 'dontpanic architecture regen --with-html',
        },
      },
      selectedProject: 'all',
    });
    const el = jarvisShim.getPageEl('architecture');
    expect(el.querySelector('[data-state="error"]')).not.toBeNull();
    expect(el.querySelector('[data-freshness="error"]')).not.toBeNull();
    expect(el.textContent).toContain('architecture.json is unreadable');
  });
});
