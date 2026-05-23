// Integration tests for the F003 project selector shell wiring.
//
// These exercise the real `createJarvis()` factory from `dashboard/core.js`
// (not a hand-rolled mirror) so that loader / refresh / resolver defects
// in core.js fail the suite. The factory is exported specifically to make
// this possible — see core.js for the IS_VITEST guard around its
// auto-bootstrap block.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { setupDOM, setupFetchMock, setupLocalStorageMock } from '../helpers/setup.js';
import { createJarvis } from '../../core.js';
import { STORAGE_KEY } from '../../lib/project-selector-logic.js';

import fleetFixture from '../fixtures/fleet-summary.json' with { type: 'json' };

function mountSelectorContainer() {
  const div = document.createElement('div');
  div.id = 'project-selector-container';
  document.body.appendChild(div);
}

beforeEach(() => {
  setupDOM();
  mountSelectorContainer();
  // Reset the URL between tests so a prior test's ?project= cannot leak.
  // vitest.config.js pins jsdom's base URL to http://localhost/.
  window.history.replaceState(null, '', 'http://localhost/');
});

afterEach(() => {
  vi.restoreAllMocks();
});

// ── load + render selector ────────────────────────────────────────────

describe('F003 shell: selector renders from served fleet-summary.json', () => {
  it('renders All Projects + every registered project after loadState()', async () => {
    setupLocalStorageMock();
    setupFetchMock({ 'fleet-summary': fleetFixture });

    const shell = createJarvis();
    await shell.loadState();
    shell.resolveProjectSelection();
    shell.renderProjectSelector();

    const select = document.querySelector('[data-project-selector="1"]');
    expect(select).not.toBeNull();
    const values = Array.from(select.options).map((o) => o.value);
    expect(values).toEqual(['all', 'spindine', 'dontpanic', 'archived']);
    // Default selection is All Projects when neither URL nor storage hint.
    expect(select.value).toBe('all');
  });

  it('falls back to a build-fleet-summary command when the file is absent (acceptance #5)', async () => {
    setupLocalStorageMock();
    setupFetchMock({}); // every fetch 404s

    const shell = createJarvis();
    await shell.loadState();
    shell.resolveProjectSelection();
    shell.renderProjectSelector();

    const container = document.getElementById('project-selector-container');
    expect(container.innerHTML).toContain('dontpanic dashboard build --project all');
    expect(container.querySelector('[data-state="missing"]')).not.toBeNull();
    expect(container.querySelector('[data-project-selector="1"]')).toBeNull();
  });

  it('still surfaces Add Project command-emission in the missing-summary state', async () => {
    setupLocalStorageMock();
    setupFetchMock({}); // no fleet-summary on disk

    const shell = createJarvis();
    await shell.loadState();
    shell.resolveProjectSelection();
    shell.renderProjectSelector();

    const container = document.getElementById('project-selector-container');
    expect(container.querySelector('[data-add-project="1"]')).not.toBeNull();
    expect(container.innerHTML).toContain('dontpanic projects add &lt;name&gt; &lt;path&gt;');
  });
});

// ── URL persistence + localStorage fallback (acceptance #2) ───────────

describe('F003 shell: selection persistence', () => {
  it('reads ?project=<name> from the URL on init', async () => {
    setupLocalStorageMock();
    setupFetchMock({ 'fleet-summary': fleetFixture });
    window.history.replaceState(null, '', 'http://localhost/?project=spindine');

    const shell = createJarvis();
    await shell.loadState();
    const resolved = shell.resolveProjectSelection();

    expect(resolved).toEqual({ value: 'spindine', source: 'url' });
    expect(shell.state.selectedProject).toBe('spindine');
  });

  it('falls back to localStorage when no URL hint is present', async () => {
    const storage = setupLocalStorageMock();
    storage.setItem(STORAGE_KEY, 'dontpanic');
    setupFetchMock({ 'fleet-summary': fleetFixture });

    const shell = createJarvis();
    await shell.loadState();
    const resolved = shell.resolveProjectSelection();

    expect(resolved).toEqual({ value: 'dontpanic', source: 'storage' });
  });

  it('persists a selector change into URL + localStorage', async () => {
    const storage = setupLocalStorageMock();
    setupFetchMock({ 'fleet-summary': fleetFixture });

    const shell = createJarvis();
    await shell.loadState();
    shell.resolveProjectSelection();
    shell.renderProjectSelector();

    const select = document.querySelector('[data-project-selector="1"]');
    select.value = 'spindine';
    select.dispatchEvent(new Event('change'));

    expect(storage.setItem).toHaveBeenCalledWith(STORAGE_KEY, 'spindine');
    expect(new URL(window.location.href).searchParams.get('project')).toBe('spindine');
    expect(shell.state.selectedProject).toBe('spindine');
    expect(document.querySelector('[data-scope="project"]')).not.toBeNull();
    expect(document.querySelector('[data-scope="fleet"]')).toBeNull();
  });

  it('clears the URL search-param when switching back to All Projects', async () => {
    setupLocalStorageMock();
    setupFetchMock({ 'fleet-summary': fleetFixture });
    window.history.replaceState(null, '', 'http://localhost/?project=spindine');

    const shell = createJarvis();
    await shell.loadState();
    shell.resolveProjectSelection();
    shell.renderProjectSelector();

    const select = document.querySelector('[data-project-selector="1"]');
    select.value = 'all';
    select.dispatchEvent(new Event('change'));

    expect(new URL(window.location.href).searchParams.has('project')).toBe(false);
  });
});

// ── governed-state invariant (acceptance #2) ───────────────────────────

describe('F003 shell: selector does not mutate governed state', () => {
  it('never POSTs / PUTs against the registry — only reads fleet-summary.json', async () => {
    const fetchSpy = setupFetchMock({ 'fleet-summary': fleetFixture });
    setupLocalStorageMock();

    const shell = createJarvis();
    await shell.loadState();
    shell.resolveProjectSelection();
    shell.renderProjectSelector();
    const select = document.querySelector('[data-project-selector="1"]');
    select.value = 'spindine';
    select.dispatchEvent(new Event('change'));

    // The selector must remain read-only against the governed registry.
    // Any registry mutation lives in the CLI; the shell only ever fetches.
    for (const call of fetchSpy.mock.calls) {
      const opts = call[1] || {};
      const method = (opts.method || 'GET').toUpperCase();
      expect(['GET', 'HEAD']).toContain(method);
    }
  });
});

// ── registry refresh (acceptance #6) ────────────────────────────────────

describe('F003 shell: selector refreshes after a registry change', () => {
  it('adds a new project option when the fleet summary picks up an added entry', async () => {
    setupLocalStorageMock();
    const fetchSpy = setupFetchMock({ 'fleet-summary': fleetFixture });

    const shell = createJarvis();
    await shell.loadState();
    shell.resolveProjectSelection();
    shell.renderProjectSelector();

    let select = document.querySelector('[data-project-selector="1"]');
    expect(Array.from(select.options).map((o) => o.value)).toEqual([
      'all', 'spindine', 'dontpanic', 'archived',
    ]);

    // Operator runs `dontpanic projects add new-app /path` in their terminal.
    // The next refresh tick of the dashboard sees a fresh fleet summary.
    const updatedFleet = {
      ...fleetFixture,
      projects: [
        ...fleetFixture.projects,
        {
          name: 'newapp', display_name: 'New App', profile: 'app',
          active: true, dontpanic_version: '0.4.0', last_used_at: null,
          repo_root: '/repo', plans_root: '/repo/docs/plans',
          architecture_path: '/repo/docs/architecture.md',
          dashboard_cache_path: '/cache/newapp',
          state_snapshot_path: '/cache/newapp/state-snapshot.json',
          what_now_path: '/cache/newapp/what-now.json',
          build_warnings_path: '/cache/newapp/build-warnings.json',
          data_age_seconds: 1.0, warning_count: 0,
          skipped: false, skipped_reason: null, health_band: 'ready',
        },
      ],
    };
    // Swap the fetch mock to surface the new fleet summary.
    fetchSpy.mockImplementation(async (url) => {
      if (String(url).endsWith('fleet-summary.json')) {
        return { ok: true, json: async () => updatedFleet };
      }
      return { ok: false, status: 404 };
    });

    await shell.loadState();
    shell.resolveProjectSelection();
    shell.renderProjectSelector();

    select = document.querySelector('[data-project-selector="1"]');
    expect(Array.from(select.options).map((o) => o.value)).toEqual([
      'all', 'spindine', 'dontpanic', 'archived', 'newapp',
    ]);
  });

  it('drops a stale selection when the project is removed from the registry', async () => {
    const storage = setupLocalStorageMock();
    storage.setItem(STORAGE_KEY, 'spindine');
    const fetchSpy = setupFetchMock({ 'fleet-summary': fleetFixture });

    const shell = createJarvis();
    await shell.loadState();
    shell.resolveProjectSelection();
    expect(shell.state.selectedProject).toBe('spindine');

    // Operator removes spindine from the registry; refresh picks up.
    const reduced = {
      ...fleetFixture,
      projects: fleetFixture.projects.filter((p) => p.name !== 'spindine'),
    };
    fetchSpy.mockImplementation(async (url) => {
      if (String(url).endsWith('fleet-summary.json')) {
        return { ok: true, json: async () => reduced };
      }
      return { ok: false, status: 404 };
    });

    await shell.loadState();
    shell.resolveProjectSelection();

    expect(shell.state.selectedProject).toBe('all');
  });

  it('present→missing refresh surfaces the missing banner (auditor i0 finding)', async () => {
    // First load succeeds with a populated fleet summary — the selector
    // renders with rows. Second load returns 404 (operator deleted the
    // cache file). The loader MUST reset state.fleetSummary to null so
    // the next renderProjectSelector swap surfaces the missing banner
    // instead of holding stale rows.
    setupLocalStorageMock();
    const fetchSpy = setupFetchMock({ 'fleet-summary': fleetFixture });

    const shell = createJarvis();
    await shell.loadState();
    expect(shell.state.fleetSummary).not.toBeNull();

    // Simulate a refresh tick after the cache file disappears.
    fetchSpy.mockImplementation(async () => ({ ok: false, status: 404 }));
    await shell.loadState();

    expect(shell.state.fleetSummary).toBeNull();

    shell.resolveProjectSelection();
    shell.renderProjectSelector();
    const container = document.getElementById('project-selector-container');
    expect(container.querySelector('[data-state="missing"]')).not.toBeNull();
    expect(container.querySelector('[data-project-selector="1"]')).toBeNull();
    expect(container.querySelector('[data-add-project="1"]')).not.toBeNull();
  });

  it('refreshState() rerenders the selector when the fleet fingerprint changes', async () => {
    // End-to-end refresh: install pages so refreshState's onActivate fan-out
    // exercises the lifecycle path too. Initial render shows three rows.
    // A registry change adds a fourth — refreshState must rebuild the
    // selector so the new row is visible.
    setupLocalStorageMock();
    const fetchSpy = setupFetchMock({ 'fleet-summary': fleetFixture });

    const shell = createJarvis();
    await shell.loadState();
    shell.resolveProjectSelection();
    shell.renderProjectSelector();
    expect(Array.from(
      document.querySelector('[data-project-selector="1"]').options
    ).map((o) => o.value)).toHaveLength(4);

    const updatedFleet = {
      ...fleetFixture,
      projects: [
        ...fleetFixture.projects,
        { name: 'newapp', display_name: 'New App', active: true, health_band: 'ready' },
      ],
    };
    fetchSpy.mockImplementation(async (url) => {
      if (String(url).endsWith('fleet-summary.json')) {
        return { ok: true, json: async () => updatedFleet };
      }
      return { ok: false, status: 404 };
    });

    await shell.refreshState();

    const select = document.querySelector('[data-project-selector="1"]');
    expect(Array.from(select.options).map((o) => o.value)).toContain('newapp');
  });

  it('refreshState() rerenders selector labels when display_name changes', async () => {
    setupLocalStorageMock();
    const fetchSpy = setupFetchMock({ 'fleet-summary': fleetFixture });

    const shell = createJarvis();
    await shell.loadState();
    shell.resolveProjectSelection();
    shell.renderProjectSelector();

    let select = document.querySelector('[data-project-selector="1"]');
    expect(Array.from(select.options).map((o) => o.textContent)).toContain('Spin & Dine');

    const renamedFleet = {
      ...fleetFixture,
      projects: fleetFixture.projects.map((p) => (
        p.name === 'spindine' ? { ...p, display_name: 'SpinDine' } : p
      )),
    };
    fetchSpy.mockImplementation(async (url) => {
      if (String(url).endsWith('fleet-summary.json')) {
        return { ok: true, json: async () => renamedFleet };
      }
      return { ok: false, status: 404 };
    });

    await shell.refreshState();

    select = document.querySelector('[data-project-selector="1"]');
    const labels = Array.from(select.options).map((o) => o.textContent);
    expect(labels).toContain('SpinDine');
    expect(labels).not.toContain('Spin & Dine');
  });
});

// ── scope labels (acceptance #3) ────────────────────────────────────────

describe('F003 shell: scope labels render across V0 sections', () => {
  it('What Now header carries Project scope for a registered selection', async () => {
    const { renderWhatNowHTML } = await import('../../lib/what-now-logic.js');
    const html = renderWhatNowHTML(
      { schema_version: '1.0.0', captured_at: '2026-05-23T03:00:00Z', items: [
        { id: 'x', source: 'gate', band: 'needs_action', title: 't' },
      ] },
      { selectedProject: 'spindine' }
    );
    expect(html).toContain('scope-badge--project');
    expect(html).not.toContain('scope-badge--fleet');
  });

  it('What Now header carries Fleet scope when All Projects is selected', async () => {
    const { renderWhatNowHTML } = await import('../../lib/what-now-logic.js');
    const html = renderWhatNowHTML(
      { schema_version: '1.0.0', captured_at: '2026-05-23T03:00:00Z', items: [
        { id: 'x', source: 'gate', band: 'needs_action', title: 't' },
      ] },
      { selectedProject: 'all' }
    );
    expect(html).toContain('scope-badge--fleet');
    expect(html).not.toContain('scope-badge--project');
  });

  it('What Now missing-state carries a scope badge', async () => {
    const { renderWhatNowHTML } = await import('../../lib/what-now-logic.js');
    const html = renderWhatNowHTML(null, { selectedProject: 'all' });
    expect(html).toContain('scope-badge--fleet');
  });

  it('What Now band panels carry a scope badge', async () => {
    // Auditor i0 finding: only the header and empty state carried scope
    // chips — individual band panels rendered without one. The plan
    // requires every visible surface to declare scope.
    const { renderWhatNowHTML } = await import('../../lib/what-now-logic.js');
    const html = renderWhatNowHTML(
      { schema_version: '1.0.0', captured_at: '2026-05-23T03:00:00Z', items: [
        { id: 'x', source: 'gate', band: 'needs_action', title: 't' },
      ] },
      { selectedProject: 'spindine' }
    );
    // Both the header and the band section render a scope badge — count
    // 2 occurrences (one per surface).
    const matches = html.match(/scope-badge--project/g) || [];
    expect(matches.length).toBeGreaterThanOrEqual(2);
    expect(html).toContain('wn-band-scope');
  });

  it('Capability Center surfaces a Global scope badge on every panel', async () => {
    // Auditor i0 finding: the summary panel had a chip but the cards
    // panel did not. Both must declare scope.
    const { renderCapabilityCenterHTML } = await import('../../lib/capabilities-logic.js');
    const envelope = {
      schema_version: '1.0.0',
      generated_at: '2026-05-22T12:00:00Z',
      advisory_notes: [],
      capabilities: [
        { capability_id: 'cap', status: 'ready',
          owner_boundary: { dontpanic_core: [], adapter: [], operator: [] },
          configured: [], missing: [], automatable: [], human_required: [],
          pending_probes: [], next_actions: [], advisory_notes: [] },
      ],
    };
    const html = renderCapabilityCenterHTML(envelope);
    const matches = html.match(/scope-badge--global/g) || [];
    expect(matches.length).toBeGreaterThanOrEqual(2);
    expect(html).toContain('cap-cards-scope');
  });

  it('Capability Center missing-state also surfaces a Global scope badge', async () => {
    const { renderCapabilityCenterHTML } = await import('../../lib/capabilities-logic.js');
    expect(renderCapabilityCenterHTML(null)).toContain('scope-badge--global');
  });
});
