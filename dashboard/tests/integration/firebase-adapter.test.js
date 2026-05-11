// Integration tests: verify the Firebase realtime adapter LAYERS on top of the
// static state loader, satisfying plan 2026-05-09-004 F001 acceptance:
//   (1) `dashboard/` continues to work standalone (no Firebase config).
//   (2) When Firebase config is provided, dashboard adds realtime overlay
//       layered on the static base — static loader is still used for first paint.
//   (3) Firestore paths use projects/{project_id}/... shape.
//   (4) Adapter renders against the local fixture.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  attachFirestoreRealtime,
  initFirebaseRealtime,
  projectF001ToLegacy,
  STREAMS,
} from '../../config-firebase.js';
import { createFirestoreStub } from '../helpers/firestore-stub.js';
import { setupDOM, setupChartMock, setupFetchMock, createMockState } from '../helpers/setup.js';
import { MC_COLUMNS, MC_COLUMN_META, deriveColumn } from '../../lib/mission-control-logic.js';
import fixture from '../fixtures/firestore-mock.json' with { type: 'json' };

// Re-use the same Jarvis shape as the core router so the adapter is exercised
// against a realistic harness (matches createRouter() in core-router.test.js).
function createRouter() {
  return {
    pages: [],
    currentPage: null,
    state: {
      agents: [],
      tasks: [],
      activity: [],
      costs: null,
      security: [],
      plans: [],
      gates: [],
      inbox: [],
      supervisors: [],
      quota: [],
      decisions: [],
      evidence_refs: [],
    },
    registerPage(config) { this.pages.push(config); },
    setSyncStatus: vi.fn(),
    updateLastSync: vi.fn(),
    async loadState() {
      const files = ['agents', 'tasks', 'activity', 'costs', 'security'];
      await Promise.all(files.map(async (name) => {
        try {
          const resp = await fetch(`state/${name}.json`);
          if (resp.ok) this.state[name] = await resp.json();
        } catch { /* keep default */ }
      }));
    },
  };
}

beforeEach(() => {
  setupDOM();
  setupChartMock();
});

afterEach(() => {
  vi.restoreAllMocks();
  delete globalThis.__JARVIS_FIREBASE_CONFIG__;
});

describe('static-first contract (acceptance 1, 2)', () => {
  it('loads legacy state from JSON when no Firebase config is present', async () => {
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

    const result = await initFirebaseRealtime({ jarvis: router });
    expect(result).toBeNull();

    // Static state intact — Firebase did not touch the legacy streams.
    expect(router.state.agents).toEqual(mockState.agents);
    expect(router.state.tasks).toEqual(mockState.tasks);
    // F001 streams stay at their defaults — no Firestore subscription happened.
    expect(router.state.plans).toEqual([]);
    expect(router.state.gates).toEqual([]);
  });

  it('layers Firestore onSnapshot on top of static loader without disturbing it', async () => {
    const mockState = createMockState();
    setupFetchMock({
      agents: mockState.agents,
      tasks:  mockState.tasks,
    });

    const router = createRouter();
    await router.loadState();

    // Snapshot the static-loaded legacy state for later equality check.
    const staticAgents = JSON.parse(JSON.stringify(router.state.agents));

    const stub = createFirestoreStub(fixture);
    const handle = attachFirestoreRealtime({
      firestore: stub,
      jarvis: router,
      projectId: 'jarvis-a6ee1',
    });

    expect(handle.attached).toBe(true);
    // Static (legacy) state unchanged after Firebase overlay attaches.
    expect(router.state.agents).toEqual(staticAgents);
    // F001 streams hydrated from the fixture's Firestore docs.
    expect(router.state.plans).toHaveLength(1);
    expect(router.state.inbox[0].event).toBe('volley_start');
  });
});

describe('Firestore document shape (acceptance 3)', () => {
  it('subscribes to projects/jarvis-a6ee1/{stream} — never tenants/{tenantId}/...', () => {
    const stub = createFirestoreStub(fixture);
    const router = createRouter();
    attachFirestoreRealtime({
      firestore: stub,
      jarvis: router,
      projectId: 'jarvis-a6ee1',
    });
    for (const stream of STREAMS) {
      expect(stub._hasPath(`projects/jarvis-a6ee1/${stream}`)).toBe(true);
      expect(stub._hasPath(`tenants/jarvis-a6ee1/${stream}`)).toBe(false);
    }
  });
});

describe('local fixture rendering (acceptance 4)', () => {
  it('hydrates the full F001 envelope from the local fixture', () => {
    const stub = createFirestoreStub(fixture);
    const router = createRouter();
    attachFirestoreRealtime({
      firestore: stub,
      jarvis: router,
      projectId: 'jarvis-a6ee1',
    });

    expect(router.state.plans[0].title).toBe('Firebase dashboard adapter v0');
    expect(router.state.gates[0].kind).toBe('pre_merge');
    expect(router.state.supervisors[0].implementer_agent).toBe('claude');
    expect(router.state.quota[0].status).toBe('ok');
    expect(router.state.decisions[0].decision_id).toBe('D007');
    expect(router.state.evidence_refs[0].type).toBe('log');
  });

  it('streams subsequent updates to active page on each emit', () => {
    const stub = createFirestoreStub(fixture);
    const router = createRouter();
    const missionControl = { id: 'mission-control', onActivate: vi.fn() };
    router.registerPage(missionControl);
    router.currentPage = 'mission-control';

    attachFirestoreRealtime({
      firestore: stub,
      jarvis: router,
      projectId: 'jarvis-a6ee1',
    });

    missionControl.onActivate.mockClear();
    stub._emit('projects/jarvis-a6ee1/gates', [
      {
        plan_id: 'p1',
        gate_name: 'pre_impl',
        kind: 'pre_impl',
        paused_at: '2026-05-11T22:00:00Z',
      },
    ]);
    expect(missionControl.onActivate).toHaveBeenCalledOnce();
    expect(router.state.gates).toHaveLength(1);
    expect(router.state.gates[0].gate_name).toBe('pre_impl');
  });
});

// ── F001 projection → Mission Control DOM smoke (auditor finding #1) ──
//
// Mounts a minimal Mission Control kanban into JSDOM, hydrates the adapter
// from the local Firestore fixture, and asserts the fixture's plan title +
// inbox event surface in rendered HTML — addressing the auditor's
// `{ total: '0', titleRendered: false }` evidence.

function buildMcKanbanHTML() {
  const cols = MC_COLUMNS.map((col) => `
    <div class="mc-column" data-column="${col}">
      <div class="mc-col-title">${MC_COLUMN_META[col].label}</div>
      <span class="mc-col-count" id="mc-count-${col}">0</span>
      <div class="mc-cards" data-column="${col}"></div>
    </div>
  `).join('');
  return `
    <div class="mc-queue">
      <div id="mc-total-tasks">0</div>
      <div id="mc-board">${cols}</div>
    </div>
    <div id="mc-feed-list"></div>
  `;
}

function renderMcFromState(host, state) {
  const tasks = (state.tasks || []).map((t) => ({ ...t, column: deriveColumn(t) }));
  for (const col of MC_COLUMNS) {
    const cardsEl = host.querySelector(`.mc-cards[data-column="${col}"]`);
    const countEl = host.querySelector(`#mc-count-${col}`);
    const colTasks = tasks.filter((t) => t.column === col);
    if (countEl) countEl.textContent = String(colTasks.length);
    if (cardsEl) {
      cardsEl.innerHTML = colTasks.map((t) => `
        <div class="mc-card" data-task-id="${t.id}">
          <div class="mc-card-title">${t.title || t.id}</div>
        </div>
      `).join('');
    }
  }
  const totalEl = host.querySelector('#mc-total-tasks');
  if (totalEl) totalEl.textContent = String(tasks.length);

  const feed = host.querySelector('#mc-feed-list');
  if (feed) {
    feed.innerHTML = (state.activity || []).map((a) => `
      <div class="mc-feed-item">
        <div class="mc-feed-text">${a.text || ''}</div>
        <div class="mc-feed-meta">${a.agent || 'System'}</div>
      </div>
    `).join('');
  }
}

describe('Mission Control DOM smoke (auditor render-fix)', () => {
  it('renders the fixture plan title into the kanban after Firestore attach', () => {
    const host = document.createElement('div');
    host.id = 'page-mission-control';
    host.innerHTML = buildMcKanbanHTML();
    document.getElementById('page-container').appendChild(host);

    const router = createRouter();
    const missionControl = {
      id: 'mission-control',
      onActivate(state) { renderMcFromState(host, state); },
    };
    router.registerPage(missionControl);
    router.currentPage = 'mission-control';

    const stub = createFirestoreStub(fixture);
    attachFirestoreRealtime({
      firestore: stub,
      jarvis: router,
      projectId: 'jarvis-a6ee1',
    });

    const total = host.querySelector('#mc-total-tasks').textContent;
    const titles = [...host.querySelectorAll('.mc-card-title')].map((el) => el.textContent.trim());
    expect(total).toBe('1');
    expect(titles).toContain('Firebase dashboard adapter v0');

    // plan.status === 'active' → in_progress column
    const inProgressTitles = [...host.querySelectorAll('.mc-cards[data-column="in_progress"] .mc-card-title')]
      .map((el) => el.textContent.trim());
    expect(inProgressTitles).toContain('Firebase dashboard adapter v0');

    // inbox event surfaces in the live feed.
    const feedTexts = [...host.querySelectorAll('#mc-feed-list .mc-feed-text')].map((el) => el.textContent.trim());
    expect(feedTexts.some((t) => t.includes('Volley begins'))).toBe(true);
  });

  it('projection alone (no Firebase) renders fixture plans into the kanban', () => {
    const host = document.createElement('div');
    host.id = 'page-mission-control';
    host.innerHTML = buildMcKanbanHTML();
    document.getElementById('page-container').appendChild(host);

    const state = {
      plans: [...fixture.plans],
      inbox: [...fixture.inbox],
      tasks: [],
      activity: [],
    };
    projectF001ToLegacy(state);
    renderMcFromState(host, state);

    const titles = [...host.querySelectorAll('.mc-card-title')].map((el) => el.textContent.trim());
    expect(titles).toContain('Firebase dashboard adapter v0');
  });
});
