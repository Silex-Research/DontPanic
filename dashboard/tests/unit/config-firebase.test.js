// Unit tests for the Firebase realtime adapter (dashboard/config-firebase.js).
// Verifies the path shape, the dependency-injected attach core, and the
// loader-side opt-in behavior. Real Firestore is never reached.

import { describe, it, expect, vi } from 'vitest';
import {
  STREAMS,
  FIREBASE_REQUIRED_KEYS,
  buildStreamPath,
  loadFirebaseConfig,
  attachFirestoreRealtime,
  initFirebaseRealtime,
  projectF001ToLegacy,
  JARVIS_A6EE1_CONFIG_TEMPLATE,
} from '../../config-firebase.js';
import { createFirestoreStub } from '../helpers/firestore-stub.js';
import fixture from '../fixtures/firestore-mock.json' with { type: 'json' };

function makeJarvis() {
  return {
    state: {
      plans: [],
      gates: [],
      inbox: [],
      supervisors: [],
      quota: [],
      decisions: [],
      evidence_refs: [],
      tasks: [],
      agents: [],
      activity: [],
    },
    pages: [],
    currentPage: null,
    setSyncStatus: vi.fn(),
    updateLastSync: vi.fn(),
  };
}

const VALID_CONFIG = Object.freeze({
  projectId: '<firebase-project-id>',
  authDomain: '<firebase-project-id>.firebaseapp.com',
  storageBucket: '<firebase-project-id>.appspot.com',
  apiKey: 'AIzaSy-not-a-real-key',
  appId: '1:1234567890:web:abc123',
  messagingSenderId: '1234567890',
});

describe('STREAMS', () => {
  it('lists the seven F001 state-projection streams', () => {
    expect(STREAMS).toEqual([
      'plans',
      'gates',
      'inbox',
      'supervisors',
      'quota',
      'decisions',
      'evidence_refs',
    ]);
  });

  it('is frozen so adapters cannot mutate it', () => {
    expect(Object.isFrozen(STREAMS)).toBe(true);
  });
});

describe('buildStreamPath', () => {
  it('returns the single-tenant projects/{pid}/{stream} shape', () => {
    expect(buildStreamPath('<firebase-project-id>', 'plans')).toBe(
      'projects/<firebase-project-id>/plans',
    );
  });

  it('rejects unknown streams', () => {
    expect(() => buildStreamPath('<firebase-project-id>', 'tenants')).toThrow();
    expect(() => buildStreamPath('<firebase-project-id>', 'tasks')).toThrow();
  });

  it('rejects empty projectId — no multi-tenant fallback', () => {
    expect(() => buildStreamPath('', 'plans')).toThrow();
    expect(() => buildStreamPath(undefined, 'plans')).toThrow();
  });
});

describe('JARVIS_A6EE1_CONFIG_TEMPLATE', () => {
  it('targets the <firebase-project-id> Firebase project (plan D009)', () => {
    expect(JARVIS_A6EE1_CONFIG_TEMPLATE.projectId).toBe('<firebase-project-id>');
    expect(JARVIS_A6EE1_CONFIG_TEMPLATE.authDomain).toBe(
      '<firebase-project-id>.firebaseapp.com',
    );
    expect(JARVIS_A6EE1_CONFIG_TEMPLATE.storageBucket).toBe(
      '<firebase-project-id>.appspot.com',
    );
  });

  it('keeps credential fields as placeholders until F003+ reactivates', () => {
    expect(JARVIS_A6EE1_CONFIG_TEMPLATE.apiKey).toMatch(/^REPLACE_/);
    expect(JARVIS_A6EE1_CONFIG_TEMPLATE.appId).toMatch(/^REPLACE_/);
    expect(JARVIS_A6EE1_CONFIG_TEMPLATE.messagingSenderId).toMatch(/^REPLACE_/);
  });
});

describe('loadFirebaseConfig', () => {
  it('returns null when no global config is set — static fallback path', () => {
    delete globalThis.__JARVIS_FIREBASE_CONFIG__;
    expect(loadFirebaseConfig()).toBeNull();
  });

  it('returns null when projectId is still a placeholder', () => {
    globalThis.__JARVIS_FIREBASE_CONFIG__ = {
      ...VALID_CONFIG,
      projectId: 'REPLACE_WITH_OPERATOR_PROJECT_ID',
    };
    expect(loadFirebaseConfig()).toBeNull();
    delete globalThis.__JARVIS_FIREBASE_CONFIG__;
  });

  it('rejects the unfilled config template — every REPLACE_* field counts', () => {
    globalThis.__JARVIS_FIREBASE_CONFIG__ = { ...JARVIS_A6EE1_CONFIG_TEMPLATE };
    expect(loadFirebaseConfig()).toBeNull();
    delete globalThis.__JARVIS_FIREBASE_CONFIG__;
  });

  it('rejects placeholder credential fields one-by-one', () => {
    for (const key of ['apiKey', 'appId', 'messagingSenderId', 'authDomain', 'storageBucket']) {
      globalThis.__JARVIS_FIREBASE_CONFIG__ = { ...VALID_CONFIG, [key]: 'REPLACE_ME' };
      expect(loadFirebaseConfig(), `placeholder ${key} should reject`).toBeNull();
      delete globalThis.__JARVIS_FIREBASE_CONFIG__;
    }
  });

  it('rejects missing required fields', () => {
    for (const key of FIREBASE_REQUIRED_KEYS) {
      const cfg = { ...VALID_CONFIG };
      delete cfg[key];
      globalThis.__JARVIS_FIREBASE_CONFIG__ = cfg;
      expect(loadFirebaseConfig(), `missing ${key} should reject`).toBeNull();
      delete globalThis.__JARVIS_FIREBASE_CONFIG__;
    }
  });

  it('returns the config object when every required field is filled with a real value', () => {
    globalThis.__JARVIS_FIREBASE_CONFIG__ = { ...VALID_CONFIG };
    const cfg = loadFirebaseConfig();
    expect(cfg).toEqual(VALID_CONFIG);
    delete globalThis.__JARVIS_FIREBASE_CONFIG__;
  });
});

describe('projectF001ToLegacy', () => {
  it('maps plans → tasks with the kanban shape Mission Control renders', () => {
    const state = {
      plans: [
        {
          plan_id: '2026-05-09-004-feat-firebase-dashboard-adapter-v0',
          title: 'Firebase dashboard adapter v0',
          status: 'active',
          surfaces: ['infra', 'web'],
          agents_required: ['claude', 'codex'],
          date: '2026-05-09',
        },
      ],
    };
    projectF001ToLegacy(state);
    expect(state.tasks).toHaveLength(1);
    expect(state.tasks[0]).toMatchObject({
      id: '2026-05-09-004-feat-firebase-dashboard-adapter-v0',
      title: 'Firebase dashboard adapter v0',
      project: 'infra',
      status: 'in_progress',
      agent: 'claude',
    });
  });

  it('maps inbox → activity feed entries with @mention-friendly text', () => {
    const state = {
      inbox: [
        {
          event: 'volley_start',
          body: 'Volley begins: claude (impl) + codex (aud)',
          captured_at: '2026-05-11T21:52:22Z',
          headers: { impl: 'claude', aud: 'codex' },
        },
      ],
    };
    projectF001ToLegacy(state);
    expect(state.activity).toHaveLength(1);
    expect(state.activity[0]).toMatchObject({
      agent: 'claude',
      text: 'Volley begins: claude (impl) + codex (aud)',
      timestamp: '2026-05-11T21:52:22Z',
    });
  });

  it('does NOT overwrite state.agents — preserves the static loader output', () => {
    const state = {
      agents: [{ id: 'claude', name: 'Claude Code', status: 'online' }],
      supervisors: [{ implementer_agent: 'gemini', auditor_agent: 'qwen' }],
    };
    projectF001ToLegacy(state);
    expect(state.agents).toEqual([{ id: 'claude', name: 'Claude Code', status: 'online' }]);
  });

  it('is a no-op on falsy / non-object input', () => {
    expect(projectF001ToLegacy(null)).toBe(null);
    expect(projectF001ToLegacy(undefined)).toBe(undefined);
  });
});

describe('attachFirestoreRealtime', () => {
  it('is a no-op when firestore is missing — static loader stays authoritative', () => {
    const jarvis = makeJarvis();
    const handle = attachFirestoreRealtime({
      firestore: null,
      jarvis,
      projectId: '<firebase-project-id>',
    });
    expect(handle.attached).toBe(false);
    expect(jarvis.state.plans).toEqual([]);
  });

  it('is a no-op when projectId is missing', () => {
    const handle = attachFirestoreRealtime({
      firestore: createFirestoreStub({}),
      jarvis: makeJarvis(),
      projectId: '',
    });
    expect(handle.attached).toBe(false);
  });

  it('subscribes to all seven streams under projects/{pid}/...', () => {
    const stub = createFirestoreStub(fixture);
    const jarvis = makeJarvis();
    attachFirestoreRealtime({ firestore: stub, jarvis, projectId: '<firebase-project-id>' });
    for (const stream of STREAMS) {
      expect(stub._hasPath(`projects/<firebase-project-id>/${stream}`)).toBe(true);
    }
    expect(stub._listenerCount()).toBe(STREAMS.length);
  });

  it('hydrates jarvis.state from the initial Firestore snapshot', () => {
    const stub = createFirestoreStub(fixture);
    const jarvis = makeJarvis();
    attachFirestoreRealtime({ firestore: stub, jarvis, projectId: '<firebase-project-id>' });
    expect(jarvis.state.plans).toHaveLength(1);
    expect(jarvis.state.plans[0].plan_id).toBe(
      '2026-05-09-004-feat-firebase-dashboard-adapter-v0',
    );
    expect(jarvis.state.gates[0].gate_name).toBe('pre_merge');
    expect(jarvis.state.inbox[0].event).toBe('volley_start');
    expect(jarvis.state.quota[0].vendor).toBe('claude');
  });

  it('re-fires the active page onActivate when a stream updates', () => {
    const stub = createFirestoreStub(fixture);
    const jarvis = makeJarvis();
    const onActivate = vi.fn();
    jarvis.pages = [{ id: 'mission-control', onActivate }];
    jarvis.currentPage = 'mission-control';

    attachFirestoreRealtime({ firestore: stub, jarvis, projectId: '<firebase-project-id>' });
    // Each of the 7 streams emits once on subscribe.
    expect(onActivate).toHaveBeenCalledTimes(STREAMS.length);
    expect(onActivate).toHaveBeenLastCalledWith(jarvis.state);
  });

  it('forwards stream-scoped updates after subscription', () => {
    const stub = createFirestoreStub(fixture);
    const jarvis = makeJarvis();
    attachFirestoreRealtime({ firestore: stub, jarvis, projectId: '<firebase-project-id>' });

    stub._emit('projects/<firebase-project-id>/plans', [
      { plan_id: 'new-plan', status: 'draft', title: 'fresh' },
    ]);
    expect(jarvis.state.plans).toEqual([
      { plan_id: 'new-plan', status: 'draft', title: 'fresh' },
    ]);
  });

  it('routes Firestore errors through onError and the sync-status badge', () => {
    const stub = createFirestoreStub(fixture);
    const jarvis = makeJarvis();
    const onError = vi.fn();
    attachFirestoreRealtime({
      firestore: stub,
      jarvis,
      projectId: '<firebase-project-id>',
      onError,
    });

    const err = new Error('permission-denied');
    stub._emitError('projects/<firebase-project-id>/gates', err);
    expect(onError).toHaveBeenCalledWith('gates', err);
    expect(jarvis.setSyncStatus).toHaveBeenCalledWith('error', 'Firestore: gates');
  });

  it('detach() unsubscribes every listener', () => {
    const stub = createFirestoreStub(fixture);
    const jarvis = makeJarvis();
    const handle = attachFirestoreRealtime({
      firestore: stub,
      jarvis,
      projectId: '<firebase-project-id>',
    });
    expect(stub._listenerCount()).toBe(STREAMS.length);
    handle.detach();
    expect(stub._listenerCount()).toBe(0);
  });

  it('honors a custom streams[] filter — heavy stream skipping per acceptance', () => {
    const stub = createFirestoreStub(fixture);
    const jarvis = makeJarvis();
    attachFirestoreRealtime({
      firestore: stub,
      jarvis,
      projectId: '<firebase-project-id>',
      streams: ['plans', 'gates'],
    });
    expect(stub._listenerCount()).toBe(2);
    expect(stub._hasPath('projects/<firebase-project-id>/plans')).toBe(true);
    expect(stub._hasPath('projects/<firebase-project-id>/inbox')).toBe(false);
  });

  it('rejects multi-tenant tenants/{tenantId}/... paths — archived per D002', () => {
    // Smoke check that any caller asking for a tenant-shaped stream gets refused
    // by buildStreamPath rather than silently rewritten.
    expect(() => buildStreamPath('<firebase-project-id>', 'tenants')).toThrow();
  });
});

describe('initFirebaseRealtime', () => {
  it('returns null when no config is wired up — static fallback preserved', async () => {
    delete globalThis.__JARVIS_FIREBASE_CONFIG__;
    const jarvis = makeJarvis();
    const result = await initFirebaseRealtime({ jarvis });
    expect(result).toBeNull();
  });

  it('returns null when sdkLoader rejects (offline / SDK fetch failed)', async () => {
    const jarvis = makeJarvis();
    const sdkLoader = vi.fn().mockRejectedValue(new Error('offline'));
    const result = await initFirebaseRealtime({
      jarvis,
      config: { projectId: '<firebase-project-id>' },
      sdkLoader,
    });
    expect(result).toBeNull();
    expect(sdkLoader).toHaveBeenCalledOnce();
  });

  it('wires the adapter when a config + sdkLoader resolve to a Firestore client', async () => {
    const jarvis = makeJarvis();
    const stub = createFirestoreStub(fixture);
    const result = await initFirebaseRealtime({
      jarvis,
      config: { projectId: '<firebase-project-id>' },
      sdkLoader: async () => stub,
    });
    expect(result).not.toBeNull();
    expect(result.attached).toBe(true);
    expect(jarvis.state.plans).toHaveLength(1);
  });
});
