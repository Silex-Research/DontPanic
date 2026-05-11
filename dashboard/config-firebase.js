// ── JARVIS Dashboard — OPTIONAL Firebase realtime adapter ──
//
// LAYERS Firestore `onSnapshot` listeners on top of the static state loader
// in core.js. Static fallback is unchanged when Firebase isn't configured:
// the operator must explicitly opt in by either
//   (a) loading dashboard/index-firebase.html (which imports this module), or
//   (b) setting window.__JARVIS_FIREBASE_CONFIG__ before this module runs.
//
// Path shape: single-tenant `projects/{project_id}/{stream}` — multi-tenant
// `tenants/{tenantId}/...` is archived per plan 2026-05-03-002 D002.
//
// Mutations DO NOT go through this adapter — state changes call DontPanic MCP
// (approve_gate, dispatch, resume) via Cloud Functions (see plan 2026-05-09-004 F003).
// The Firestore documents this adapter reads are written by the sync daemon
// in scripts/firebase_adapter/ (plan 2026-05-09-004 F002).

// The seven F001 state-projection streams (see claude/shared/schemas/v1.0/state-snapshot.schema.json).
export const STREAMS = Object.freeze([
  'plans',
  'gates',
  'inbox',
  'supervisors',
  'quota',
  'decisions',
  'evidence_refs',
]);

// Placeholder firebaseConfig targeting jarvis-a6ee1 (per plan 2026-05-03-002 D009).
// Real apiKey/appId/messagingSenderId land when credentials reactivate
// per plan 2026-05-09-004 D007 — F003+ credential gate.
export const JARVIS_A6EE1_CONFIG_TEMPLATE = Object.freeze({
  projectId: 'jarvis-a6ee1',
  authDomain: 'jarvis-a6ee1.firebaseapp.com',
  storageBucket: 'jarvis-a6ee1.appspot.com',
  apiKey: 'REPLACE_WITH_OPERATOR_API_KEY',
  appId: 'REPLACE_WITH_OPERATOR_APP_ID',
  messagingSenderId: 'REPLACE_WITH_OPERATOR_SENDER_ID',
});

export function buildStreamPath(projectId, stream) {
  if (!projectId) throw new Error('projectId is required');
  if (!STREAMS.includes(stream)) throw new Error(`unknown stream: ${stream}`);
  return `projects/${projectId}/${stream}`;
}

// Required keys for a usable Firebase web SDK config. Adapter rejects the
// config if any required field is missing or still bearing a REPLACE_* sentinel
// — operators copying config-firebase.example.js must fill every value, not
// just the projectId, before the adapter attaches.
export const FIREBASE_REQUIRED_KEYS = Object.freeze([
  'projectId',
  'authDomain',
  'storageBucket',
  'apiKey',
  'appId',
  'messagingSenderId',
]);

function isPlaceholderValue(v) {
  return typeof v === 'string' && v.startsWith('REPLACE_');
}

export function loadFirebaseConfig(globalKey = '__JARVIS_FIREBASE_CONFIG__') {
  if (typeof globalThis === 'undefined') return null;
  const raw = globalThis[globalKey];
  if (!raw || typeof raw !== 'object') return null;
  for (const key of FIREBASE_REQUIRED_KEYS) {
    const v = raw[key];
    if (typeof v !== 'string' || v.length === 0) return null;
    if (isPlaceholderValue(v)) return null;
  }
  return raw;
}

// Project F001 envelope streams (plans, inbox) into the Mission Control–shaped
// legacy keys (tasks, activity) that the page modules already render. Keeps the
// F001 documents intact on `state.plans` etc. for future pages that consume the
// new shape directly. Static legacy keys not derivable from F001 (agents) are
// left untouched so the bundled static dashboard's UX stays intact when only
// projections fire.
export function projectF001ToLegacy(state) {
  if (!state || typeof state !== 'object') return state;

  if (Array.isArray(state.plans)) {
    state.tasks = state.plans.map((p) => ({
      id: p.plan_id,
      title: p.title || p.plan_id,
      project: deriveProjectKey(p),
      status: derivePlanStatus(p.status),
      priority: 'medium',
      agent: Array.isArray(p.agents_required) ? p.agents_required[0] : null,
      created: p.date ? new Date(p.date).toISOString() : null,
    }));
  }

  if (Array.isArray(state.inbox)) {
    state.activity = state.inbox.map((e) => ({
      type: deriveEventType(e.event),
      text: e.body || e.event || '',
      agent: (e.headers && e.headers.impl) || 'System',
      timestamp: e.captured_at || null,
    }));
  }

  return state;
}

function derivePlanStatus(s) {
  if (s === 'active') return 'in_progress';
  if (s === 'done' || s === 'completed') return 'done';
  if (s === 'review') return 'review';
  return 'backlog';
}

function deriveProjectKey(plan) {
  if (Array.isArray(plan.surfaces) && plan.surfaces.includes('infra')) return 'infra';
  if (typeof plan.target_project === 'string' && plan.target_project) {
    return plan.target_project.toLowerCase();
  }
  return 'infra';
}

function deriveEventType(event) {
  if (!event || typeof event !== 'string') return 'info';
  if (event.includes('deploy')) return 'deploy';
  if (event.includes('alert') || event.includes('error') || event.includes('fail')) return 'alert';
  if (event.includes('sync')) return 'sync';
  return 'task';
}

// Dependency-injected core. `firestore` is a minimal adapter:
//   firestore.collection(path) → { onSnapshot(onNext, onError) → unsubscribe }
// In the browser this wraps the Firebase Web SDK; in tests this is a stub.
export function attachFirestoreRealtime({
  firestore,
  jarvis,
  projectId,
  streams = STREAMS,
  onError,
}) {
  if (!firestore || !jarvis || !projectId) {
    return { detach: () => {}, attached: false };
  }

  const unsubs = [];
  for (const stream of streams) {
    if (!STREAMS.includes(stream)) continue;
    const ref = firestore.collection(buildStreamPath(projectId, stream));
    const unsub = ref.onSnapshot(
      (snap) => {
        const docs = [];
        snap.forEach((doc) => {
          const data = typeof doc.data === 'function' ? doc.data() : doc;
          docs.push(data);
        });
        jarvis.state[stream] = docs;
        projectF001ToLegacy(jarvis.state);
        if (typeof jarvis.refreshUiFromState === 'function') {
          jarvis.refreshUiFromState(stream);
        } else if (jarvis.currentPage && Array.isArray(jarvis.pages)) {
          const active = jarvis.pages.find((p) => p.id === jarvis.currentPage);
          if (active && typeof active.onActivate === 'function') {
            active.onActivate(jarvis.state);
          }
        }
        if (typeof jarvis.updateLastSync === 'function') jarvis.updateLastSync();
        if (typeof jarvis.setSyncStatus === 'function') {
          jarvis.setSyncStatus('online', 'Realtime');
        }
      },
      (err) => {
        if (typeof onError === 'function') onError(stream, err);
        if (typeof jarvis.setSyncStatus === 'function') {
          jarvis.setSyncStatus('error', `Firestore: ${stream}`);
        }
      },
    );
    unsubs.push(unsub);
  }

  return {
    attached: true,
    detach() {
      while (unsubs.length) {
        const u = unsubs.pop();
        try {
          if (typeof u === 'function') u();
        } catch {
          // best-effort detach
        }
      }
    },
  };
}

// Browser bootstrap. Lazy-loads the Firebase Web SDK from gstatic CDN and
// returns the attach handle. Returns null when no config is wired up — the
// static loader in core.js stays authoritative for first paint and offline.
//
// Waits for `jarvis.ready` (if exposed) so the static loader's first paint
// completes BEFORE the realtime overlay attaches — guarantees the user always
// sees the static base, even if Firestore is fast or fails.
export async function initFirebaseRealtime({
  jarvis,
  config = loadFirebaseConfig(),
  sdkLoader,
} = {}) {
  if (!jarvis) return null;
  if (!config || !config.projectId) {
    if (typeof console !== 'undefined') {
      console.info(
        '[Jarvis] Firebase realtime not configured — static state loader only.',
      );
    }
    return null;
  }

  if (jarvis.ready && typeof jarvis.ready.then === 'function') {
    try { await jarvis.ready; } catch { /* proceed; static loader is best-effort */ }
  }

  const loader = sdkLoader || defaultSdkLoader;
  let firestore;
  try {
    firestore = await loader(config);
  } catch (err) {
    if (typeof console !== 'undefined') {
      console.warn(
        '[Jarvis] Firebase SDK load failed — falling back to static state.',
        err,
      );
    }
    return null;
  }

  return attachFirestoreRealtime({
    firestore,
    jarvis,
    projectId: config.projectId,
  });
}

// Default CDN loader — uses Firebase v10 modular ESM bundles from gstatic.
// Operators can override via `sdkLoader` (e.g. point at the Firebase emulator
// or a self-hosted SDK copy).
async function defaultSdkLoader(config) {
  const appMod = await import(
    'https://www.gstatic.com/firebasejs/10.14.0/firebase-app.js'
  );
  const fsMod = await import(
    'https://www.gstatic.com/firebasejs/10.14.0/firebase-firestore.js'
  );
  const app = appMod.initializeApp(config);
  const db = fsMod.getFirestore(app);
  return {
    collection(path) {
      const colRef = fsMod.collection(db, path);
      return {
        onSnapshot(onNext, onErr) {
          return fsMod.onSnapshot(colRef, onNext, onErr);
        },
      };
    },
  };
}
