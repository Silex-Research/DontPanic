// Integration tests for the Jarvis core router and page lifecycle.
//
// Strategy: construct a fresh router object per test using the same method
// signatures as core.js. This avoids the browser-only dynamic import() chain
// while exercising the real logic verbatim.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { setupDOM, setupFetchMock, createMockState, setupChartMock } from '../helpers/setup.js';
import { timeAgo, formatCurrency, formatNumber } from '../../lib/formatters.js';
import { createJarvis } from '../../core.js';
import {
  mergeSnapshotIntoState,
  mergePerStreamIntoState,
  PER_STREAM_FILES,
} from '../../lib/projection-adapter.js';
import { ALL_PROJECTS_VALUE } from '../../lib/project-selector-logic.js';

import snapshotFixture from '../fixtures/state-snapshot.json' with { type: 'json' };

// ── Router factory ────────────────────────────────────────────────────────────
// Mirrors the Jarvis object literal from core.js exactly, minus the browser-
// global assignment and dynamic page imports. Each test gets a fresh instance.

// Plan 2026-06-05-002 F002 — de-drifted: exercise the REAL shell via createJarvis()
// instead of a hand-maintained copy of the Jarvis literal (which had drifted on the
// loadState file-set). createJarvis() returns the same object the running dashboard
// uses, so every router-mechanics + loadState test now runs the real logic.
const createRouter = createJarvis;

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
    // Plan 2026-06-05-002 F002 — the REAL loader (createJarvis) treats security as
    // nullableMissing: a missing file resets it to null so Health renders "no data
    // yet". The old copied router loaded security as a plain file (default []) — the
    // exact stale-loader drift this de-drift removes.
    expect(router.state.security).toBeNull();
    // capabilities-status.json absent — capabilities stays null so the
    // Capability Center page can render its empty-state.
    expect(router.state.capabilities).toBeNull();
  });

  it('silently keeps the default value for any file whose fetch throws', async () => {
    globalThis.fetch = vi.fn().mockRejectedValue(new Error('network error'));

    const router = createRouter();
    await expect(router.loadState()).resolves.not.toThrow();
    expect(router.state.agents).toEqual([]);
    expect(router.state.capabilities).toBeNull();
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

  // Acceptance #2: Capability Center reads from the aliased filename
  // `capabilities-status.json`, not `capabilities.json`. The router must
  // therefore fetch the aliased path AND surface the result under the
  // `capabilities` state key.
  it('loads the aliased capabilities-status.json into state.capabilities', async () => {
    const envelope = {
      schema_version: '1.0.0',
      generated_at:   '2026-05-22T12:00:00Z',
      advisory_notes: [],
      capabilities: [
        { capability_id: 'agent-claude-cli', status: 'ready',
          owner_boundary: { dontpanic_core: [], adapter: [], operator: [] },
          configured: [], missing: [], automatable: [], human_required: [],
          pending_probes: [], next_actions: [], advisory_notes: [] },
      ],
    };
    // setupFetchMock keys by `<basename without .json>`, so the alias
    // `capabilities-status.json` resolves to the `capabilities-status` key.
    setupFetchMock({ 'capabilities-status': envelope });

    const router = createRouter();
    await router.loadState();

    expect(router.state.capabilities).toEqual(envelope);
  });

  it('loads the aliased fleet-what-now.json into state.fleetWhatNow', async () => {
    const envelope = {
      schema_version: '1.0.0',
      captured_at: '2026-05-23T03:00:00Z',
      items: [
        { id: 'gate:spin', source: 'gate', band: 'needs_action', title: 'Spin gate' },
      ],
    };
    setupFetchMock({ 'fleet-what-now': envelope });

    const router = createRouter();
    await router.loadState();

    expect(router.state.fleetWhatNow).toEqual(envelope);
  });

  it('uses the aliased URL — not state/capabilities.json', async () => {
    const fetchSpy = setupFetchMock({});
    const router = createRouter();
    await router.loadState();

    const urls = fetchSpy.mock.calls.map(call => call[0]);
    expect(urls).toContain('state/capabilities-status.json');
    expect(urls).toContain('state/fleet-what-now.json');
    expect(urls).not.toContain('state/capabilities.json');
    // Plan 2026-06-05-002 F002 — drift sentinel: the REAL loader must fetch the
    // files the stale copy was missing (architecture-view-state / config-inventory /
    // skill-recommendations) + the state-snapshot path. If core.js's loader file-set
    // shrinks, this fails instead of the test quietly certifying a smaller load.
    expect(urls).toContain('state/architecture-view-state.json');
    expect(urls).toContain('state/config-inventory.json');
    expect(urls).toContain('state/skill-recommendations.json');
    expect(urls).toContain('state/state-snapshot.json');
  });

  // ── F002: projection-to-view adapter ──────────────────────────────────────

  // Acceptance #1: V0 dashboard data loading accepts canonical
  // state-snapshot.json and surfaces the projection streams under the
  // canonical state keys (plans, gates, inbox, supervisors, ...).
  it('F002 #1: populates canonical projection keys from state-snapshot.json', async () => {
    setupFetchMock({ 'state-snapshot': snapshotFixture });

    const router = createRouter();
    await router.loadState();

    expect(router.state.plans).toHaveLength(2);
    expect(router.state.gates).toHaveLength(1);
    expect(router.state.inbox).toHaveLength(2);
    expect(router.state.supervisors).toHaveLength(1);
    expect(router.state.quota).toHaveLength(1);
    expect(router.state.decisions).toHaveLength(1);
    expect(router.state.evidenceRefs).toHaveLength(1);
    expect(router.state.snapshotMeta).toMatchObject({
      schema_version: '1.0',
      captured_at:    '2026-05-23T03:15:00Z',
      redact_level:   'operator',
    });
  });

  // Acceptance #1 (continued): The adapter also reshapes the projection
  // into the legacy task / agent / activity shapes the existing
  // mission-control and command-center pages consume, so they keep
  // rendering without a per-page rewrite.
  it('F002 #1: adapts snapshot into legacy tasks / agents / activity shapes', async () => {
    setupFetchMock({ 'state-snapshot': snapshotFixture });

    const router = createRouter();
    await router.loadState();

    // Snapshot has two plans → two tasks; mission-control reads from tasks.
    expect(router.state.tasks).toHaveLength(2);
    expect(router.state.tasks[0]).toMatchObject({
      id:     '2026-05-23-004-feat-operator-console-v0',
      title:  'Operator console v0',
      status: 'in_progress',
      agent:  'claude',
    });
    // Snapshot has one supervisor → one agent row.
    expect(router.state.agents).toHaveLength(1);
    expect(router.state.agents[0]).toMatchObject({ id: 'claude', status: 'busy' });
    // Snapshot has two inbox events → two activity entries.
    expect(router.state.activity).toHaveLength(2);
  });

  // Acceptance #1 (continued): When both legacy fixtures and the
  // snapshot are present, the projection wins.
  it('F002 #1: snapshot overrides legacy demo files when both are present', async () => {
    const mockState = createMockState();
    setupFetchMock({
      agents:           mockState.agents,
      tasks:            mockState.tasks,
      activity:         mockState.activity,
      'state-snapshot': snapshotFixture,
    });

    const router = createRouter();
    await router.loadState();

    expect(router.state.tasks.find(t => t.id === 't1')).toBeUndefined();
    expect(router.state.tasks.find(t => t.id === '2026-05-23-004-feat-operator-console-v0'))
      .toBeTruthy();
  });

  // Acceptance #2: Legacy dashboard/state demo files still render when
  // no state-snapshot.json is on disk — the static showcase path stays
  // working.
  it('F002 #2: legacy demo files still render when state-snapshot.json is absent', async () => {
    const mockState = createMockState();
    setupFetchMock({
      agents:   mockState.agents,
      tasks:    mockState.tasks,
      activity: mockState.activity,
    });

    const router = createRouter();
    await router.loadState();

    expect(router.state.tasks).toEqual(mockState.tasks);
    expect(router.state.agents).toEqual(mockState.agents);
    expect(router.state.activity).toEqual(mockState.activity);
    // No snapshot → canonical keys stay at their empty defaults.
    expect(router.state.plans).toEqual([]);
    expect(router.state.gates).toEqual([]);
    expect(router.state.snapshotMeta).toBeNull();
  });

  // Acceptance #3: Capability Center reuse — loading a snapshot must
  // not touch the capabilities envelope path; the page keeps reading
  // capabilities-status.json through the existing aliased loader.
  it('F002 #3: snapshot loading does not overwrite the capabilities envelope', async () => {
    const capEnvelope = {
      schema_version: '1.0.0',
      generated_at:   '2026-05-22T12:00:00Z',
      advisory_notes: [],
      capabilities: [
        { capability_id: 'agent-claude-cli', status: 'ready',
          owner_boundary: { dontpanic_core: [], adapter: [], operator: [] },
          configured: [], missing: [], automatable: [], human_required: [],
          pending_probes: [], next_actions: [], advisory_notes: [] },
      ],
    };
    setupFetchMock({
      'capabilities-status': capEnvelope,
      'state-snapshot':      snapshotFixture,
    });

    const router = createRouter();
    await router.loadState();

    expect(router.state.capabilities).toEqual(capEnvelope);
    // And the snapshot was still consumed.
    expect(router.state.plans).toHaveLength(2);
  });

  // Acceptance #4: Missing projection files must produce a quiet empty
  // state, never a bootstrap failure.
  it('F002 #4: missing state-snapshot.json leaves canonical keys empty (no bootstrap failure)', async () => {
    setupFetchMock({}); // every URL 404s, including state-snapshot.json

    const router = createRouter();
    await expect(router.loadState()).resolves.not.toThrow();
    expect(router.state.plans).toEqual([]);
    expect(router.state.snapshotMeta).toBeNull();
  });

  it('F002 #4: malformed state-snapshot.json is ignored (quiet, not crashing)', async () => {
    setupFetchMock({ 'state-snapshot': { schema_version: '0.9', streams: 'not-an-object' } });

    const router = createRouter();
    await expect(router.loadState()).resolves.not.toThrow();
    expect(router.state.plans).toEqual([]);
    expect(router.state.snapshotMeta).toBeNull();
  });

  // ── F002 i1 audit follow-up: per-stream projection fallback ───────────
  //
  // `dontpanic state export-dashboard` writes both `state-snapshot.json`
  // (envelope) AND seven per-stream files: plans.json, gates.json,
  // inbox.json, supervisors.json, quota.json, decisions.json,
  // evidence_refs.json. If a consumer hand-stages only the per-stream
  // files (no envelope), the dashboard must still populate canonical +
  // legacy keys from them. Auditor i0 high-severity finding.

  it('F002 #1: per-stream files populate canonical keys when snapshot is absent', async () => {
    const s = snapshotFixture.streams;
    setupFetchMock({
      // Each per-stream file is JUST that stream's array — no envelope.
      plans:         s.plans,
      gates:         s.gates,
      inbox:         s.inbox,
      supervisors:   s.supervisors,
      quota:         s.quota,
      decisions:     s.decisions,
      evidence_refs: s.evidence_refs,
      // Note: no 'state-snapshot' key → envelope fetch returns 404.
    });

    const router = createRouter();
    await router.loadState();

    expect(router.state.plans).toHaveLength(2);
    expect(router.state.gates).toHaveLength(1);
    expect(router.state.inbox).toHaveLength(2);
    expect(router.state.supervisors).toHaveLength(1);
    expect(router.state.quota).toHaveLength(1);
    expect(router.state.decisions).toHaveLength(1);
    expect(router.state.evidenceRefs).toHaveLength(1);
    // No envelope → no capture-time metadata.
    expect(router.state.snapshotMeta).toBeNull();
  });

  it('F002 #1: per-stream files populate adapted legacy tasks/agents/activity', async () => {
    const s = snapshotFixture.streams;
    setupFetchMock({
      plans:         s.plans,
      gates:         s.gates,
      inbox:         s.inbox,
      supervisors:   s.supervisors,
      quota:         s.quota,
      decisions:     s.decisions,
      evidence_refs: s.evidence_refs,
    });

    const router = createRouter();
    await router.loadState();

    expect(router.state.tasks).toHaveLength(2);
    expect(router.state.tasks[0]).toMatchObject({
      id:     '2026-05-23-004-feat-operator-console-v0',
      title:  'Operator console v0',
      status: 'in_progress',
      agent:  'claude',
    });
    expect(router.state.agents).toHaveLength(1);
    expect(router.state.agents[0]).toMatchObject({ id: 'claude', status: 'busy' });
    expect(router.state.activity).toHaveLength(2);
  });

  it('F002 #1: per-stream projection overrides legacy demo files', async () => {
    const mockState = createMockState();
    const s = snapshotFixture.streams;
    setupFetchMock({
      agents:        mockState.agents,
      tasks:         mockState.tasks,
      activity:      mockState.activity,
      plans:         s.plans,
      supervisors:   s.supervisors,
      inbox:         s.inbox,
      gates:         s.gates,
      quota:         s.quota,
      decisions:     s.decisions,
      evidence_refs: s.evidence_refs,
    });

    const router = createRouter();
    await router.loadState();

    // Legacy fixtures are stomped by the per-stream adapter.
    expect(router.state.tasks.find(t => t.id === 't1')).toBeUndefined();
    expect(router.state.tasks.find(t => t.id === '2026-05-23-004-feat-operator-console-v0'))
      .toBeTruthy();
  });

  it('F002 #1: state-snapshot.json wins over per-stream files when both are present', async () => {
    // Snapshot envelope must take precedence so the dashboard surfaces
    // capture-time metadata even when per-stream files are also on disk
    // (which is the normal `dontpanic state export-dashboard` output).
    const s = snapshotFixture.streams;
    setupFetchMock({
      'state-snapshot': snapshotFixture,
      plans:            [], // deliberately empty to detect if per-stream stomped envelope
      gates:            [],
      inbox:            [],
      supervisors:      [],
      quota:            [],
      decisions:        [],
      evidence_refs:    [],
    });
    // Reference s to keep the fixture import meaningful for readers.
    expect(s.plans).toHaveLength(2);

    const router = createRouter();
    await router.loadState();

    expect(router.state.plans).toHaveLength(2);
    expect(router.state.snapshotMeta).not.toBeNull();
  });

  it('F002 #1: a partial per-stream input (only plans.json) still surfaces the projection', async () => {
    setupFetchMock({ plans: snapshotFixture.streams.plans });

    const router = createRouter();
    await router.loadState();

    expect(router.state.plans).toHaveLength(2);
    expect(router.state.tasks).toHaveLength(2);
    // Streams without files stay at empty defaults.
    expect(router.state.gates).toEqual([]);
    expect(router.state.supervisors).toEqual([]);
    expect(router.state.snapshotMeta).toBeNull();
  });

  it('F002 #3: per-stream loading does not overwrite the capabilities envelope', async () => {
    const capEnvelope = {
      schema_version: '1.0.0',
      generated_at:   '2026-05-22T12:00:00Z',
      advisory_notes: [],
      capabilities: [
        { capability_id: 'agent-claude-cli', status: 'ready',
          owner_boundary: { dontpanic_core: [], adapter: [], operator: [] },
          configured: [], missing: [], automatable: [], human_required: [],
          pending_probes: [], next_actions: [], advisory_notes: [] },
      ],
    };
    const s = snapshotFixture.streams;
    setupFetchMock({
      'capabilities-status': capEnvelope,
      plans:                 s.plans,
      supervisors:           s.supervisors,
      inbox:                 s.inbox,
    });

    const router = createRouter();
    await router.loadState();

    expect(router.state.capabilities).toEqual(capEnvelope);
    expect(router.state.plans).toHaveLength(2);
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
