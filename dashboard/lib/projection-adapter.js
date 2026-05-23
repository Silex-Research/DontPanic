// ── Projection-to-view adapter (plan 2026-05-23-004 F002) ──
//
// Maps the canonical F001 state-snapshot envelope written by
// `dontpanic state export-dashboard` (and the per-stream JSON files it
// emits) into the dashboard's in-memory state object.
//
// The Capability Center page is intentionally NOT touched here — it
// reads `capabilities-status.json` directly through the existing loader
// path. Reusing that path is required by F002 acceptance #3 (no second
// capability UI).
//
// Two-layer output:
//   • canonical keys (plans, gates, inbox, supervisors, quota, decisions,
//     evidenceRefs, snapshotMeta) — what new pages should bind to.
//   • adapted legacy keys (tasks, agents, activity) — keeps the existing
//     mission-control and command-center pages rendering without a
//     rewrite.
//
// Pure — no DOM, no fetch. The loader in core.js handles I/O.

export const SUPPORTED_SCHEMA_VERSION = '1.0';

// Per-stream projection filenames written by
// `dontpanic state export-dashboard` (state_cli.py:_export_dashboard_main).
// Each file holds JUST that stream's array — no envelope. The list mirrors
// state_projection.ALL_STREAMS so the loader picks up new streams when the
// projection contract grows. Order is irrelevant — all fetches run in
// parallel and the merger keys on stream name.
export const PER_STREAM_FILES = Object.freeze([
  'plans',
  'gates',
  'inbox',
  'supervisors',
  'quota',
  'decisions',
  'evidence_refs',
]);

// plan_summary.status → mission-control kanban column.
// Mission Control's columns are: backlog, todo, in_progress, review, done.
const PLAN_STATUS_TO_COLUMN = Object.freeze({
  draft:            'backlog',
  active:           'in_progress',
  ready_for_audit:  'review',
  in_audit:         'review',
  completed:        'done',
  abandoned:        'done',
  blocked:          'todo',
});

/**
 * Returns true when `raw` is a recognisable F001 state-snapshot envelope.
 * Schema version is pinned per dashboard/README.md adapter contract.
 * @param {unknown} raw
 * @returns {boolean}
 */
export function isCanonicalSnapshot(raw) {
  if (raw == null || typeof raw !== 'object') return false;
  if (raw.schema_version !== SUPPORTED_SCHEMA_VERSION) return false;
  const streams = raw.streams;
  if (streams == null || typeof streams !== 'object') return false;
  // Required streams per state-snapshot.schema.json.
  for (const key of ['plans', 'gates', 'inbox', 'supervisors', 'quota', 'decisions', 'evidence_refs']) {
    if (!Array.isArray(streams[key])) return false;
  }
  return true;
}

function safeArray(value) {
  return Array.isArray(value) ? value : [];
}

function safeString(value) {
  return typeof value === 'string' ? value : '';
}

/**
 * Returns the canonical-key view (plans, gates, ...) from a snapshot.
 * The shapes here mirror the projection streams verbatim — adapters
 * downstream pin against the published schema, not against this module.
 * @param {object} snap a snapshot envelope already validated by isCanonicalSnapshot
 * @returns {object}
 */
export function extractStreams(snap) {
  const streams = snap.streams;
  return {
    plans:         safeArray(streams.plans),
    gates:         safeArray(streams.gates),
    inbox:         safeArray(streams.inbox),
    supervisors:   safeArray(streams.supervisors),
    quota:         safeArray(streams.quota),
    decisions:     safeArray(streams.decisions),
    evidenceRefs:  safeArray(streams.evidence_refs),
  };
}

/**
 * Build a Mission-Control-shaped `tasks` array from plan_summary entries.
 * Field mapping (legacy → projection):
 *   id        ← plan_id
 *   title     ← title (falls back to plan_id)
 *   project   ← type ("feat"/"fix"/... — used by mission-control's
 *               filter chips; unknown types fall through harmlessly)
 *   status    ← PLAN_STATUS_TO_COLUMN[status] ?? 'backlog'
 *   priority  ← "medium" (snapshot has no priority field in v0)
 *   agent     ← first agents_required[] entry, lowercased; null if empty
 *   created   ← date (YYYY-MM-DD) → ISO with 00:00:00Z suffix so the
 *               existing newest-first sort in mission-control sees a
 *               well-formed timestamp
 * @param {Array} plans
 * @returns {Array<object>}
 */
export function adaptPlansToTasks(plans) {
  return safeArray(plans).map((p) => {
    const plan = (p && typeof p === 'object') ? p : {};
    const planId = safeString(plan.plan_id);
    const agents = safeArray(plan.agents_required);
    const firstAgent = agents.find((a) => typeof a === 'string' && a.length > 0);
    const date = safeString(plan.date);
    return {
      id:       planId,
      title:    safeString(plan.title) || planId,
      project:  safeString(plan.type),
      status:   PLAN_STATUS_TO_COLUMN[plan.status] ?? 'backlog',
      priority: 'medium',
      agent:    firstAgent ? firstAgent.toLowerCase() : null,
      created:  date ? `${date}T00:00:00Z` : '',
    };
  });
}

/**
 * Build a command-center / mission-control-shaped `agents` array from
 * the supervisors stream. Each active supervisor surfaces as an online
 * agent currently working on its plan_id; tokensUsed/tokenBudget are
 * left at 0 because the snapshot intentionally does not surface
 * per-supervisor token spend (quota is reported per-vendor, not
 * per-process). A snapshot with no supervisors yields an empty list.
 * @param {Array} supervisors
 * @returns {Array<object>}
 */
export function adaptSupervisorsToAgents(supervisors) {
  return safeArray(supervisors).map((s) => {
    const sup = (s && typeof s === 'object') ? s : {};
    const impl = safeString(sup.implementer_agent);
    const planId = safeString(sup.plan_id);
    const agentId = impl ? impl.toLowerCase() : safeString(sup.supervisor_id);
    return {
      id:           agentId,
      name:         impl || agentId,
      role:         'Supervised',
      status:       'busy',
      currentTask:  planId || null,
      lastSeen:     safeString(sup.started_at),
      tokensUsed:   0,
      tokenBudget:  0,
    };
  });
}

/**
 * Build a command-center / mission-control-shaped `activity` array from
 * the inbox stream. We render every inbox event as one activity row;
 * the existing feed UI already filters by `type`/`agent` so we map the
 * event kind through a small typed bucket and surface the plan_id as
 * the activity text prefix.
 * @param {Array} inbox
 * @returns {Array<object>}
 */
export function adaptInboxToActivity(inbox) {
  return safeArray(inbox).map((e) => {
    const evt = (e && typeof e === 'object') ? e : {};
    const kind = safeString(evt.event);
    const planId = safeString(evt.plan_id);
    const featureId = safeString(evt.feature_id);
    const tagged = featureId ? `${planId} ${featureId}` : planId;
    return {
      type:      mapInboxEventToActivityType(kind),
      text:      tagged ? `${tagged}: ${kind || 'event'}` : (kind || 'event'),
      agent:     null,
      timestamp: safeString(evt.captured_at),
    };
  });
}

function mapInboxEventToActivityType(eventName) {
  if (!eventName) return 'info';
  if (eventName.startsWith('breaker_')) return 'alert';
  if (eventName.startsWith('gate_')) return 'alert';
  if (eventName === 'signoff') return 'task';
  if (eventName === 'volley_start' || eventName === 'volley_terminal') return 'sync';
  if (eventName === 'verdict_mismatch') return 'alert';
  return 'info';
}

/**
 * Build a snapshot-meta block surfaced to pages that want to show the
 * provenance of the projection (schema version, capture timestamp,
 * redact level). Returns null when the snapshot is missing the
 * top-level metadata; the dashboard treats null as "no snapshot".
 * @param {object} snap
 * @returns {null|{schema_version: string, captured_at: string, redact_level: string, dontpanic_version: string|null}}
 */
export function extractSnapshotMeta(snap) {
  if (snap == null || typeof snap !== 'object') return null;
  return {
    schema_version:   safeString(snap.schema_version) || SUPPORTED_SCHEMA_VERSION,
    captured_at:      safeString(snap.captured_at),
    redact_level:     safeString(snap.redact_level),
    dontpanic_version: typeof snap.dontpanic_version === 'string' ? snap.dontpanic_version : null,
  };
}

/**
 * Top-level adapter. Validates the input, extracts the canonical
 * streams, and synthesises legacy-shaped fields so existing pages keep
 * rendering. Returns `null` when the input is not a canonical snapshot —
 * the loader treats that as "no projection available, fall back to
 * legacy state files" rather than as a hard error (acceptance #4).
 * @param {unknown} raw
 * @returns {null|object}
 */
export function adaptSnapshot(raw) {
  if (!isCanonicalSnapshot(raw)) return null;
  const streams = extractStreams(raw);
  return {
    // Canonical projection keys — pin to these in new V0 pages.
    plans:         streams.plans,
    gates:         streams.gates,
    inbox:         streams.inbox,
    supervisors:   streams.supervisors,
    quota:         streams.quota,
    decisions:     streams.decisions,
    evidenceRefs:  streams.evidenceRefs,
    snapshotMeta:  extractSnapshotMeta(raw),
    // Legacy-shaped fallback so mission-control and command-center
    // render without per-page changes.
    tasks:         adaptPlansToTasks(streams.plans),
    agents:        adaptSupervisorsToAgents(streams.supervisors),
    activity:      adaptInboxToActivity(streams.inbox),
  };
}

/**
 * Merge a snapshot's adapted view into the dashboard state object. Used
 * by the core loader: legacy demo state files have already been merged
 * by the time this is called, so adapted fields overwrite legacy ones
 * (acceptance #1: V0 prefers canonical projection). Capabilities are
 * untouched (acceptance #3: Capability Center keeps its existing path).
 *
 * Returns `true` when the snapshot was applied, `false` when the input
 * was not a canonical envelope — the loader uses that to decide whether
 * to attempt the per-stream fallback (`mergePerStreamIntoState`).
 *
 * @param {object} state
 * @param {unknown} raw the raw state-snapshot.json payload (or null/undefined)
 * @returns {boolean} whether the snapshot was applied
 */
export function mergeSnapshotIntoState(state, raw) {
  const adapted = adaptSnapshot(raw);
  if (adapted == null) return false;
  state.plans         = adapted.plans;
  state.gates         = adapted.gates;
  state.inbox         = adapted.inbox;
  state.supervisors   = adapted.supervisors;
  state.quota         = adapted.quota;
  state.decisions     = adapted.decisions;
  state.evidenceRefs  = adapted.evidenceRefs;
  state.snapshotMeta  = adapted.snapshotMeta;
  state.tasks         = adapted.tasks;
  state.agents        = adapted.agents;
  state.activity      = adapted.activity;
  return true;
}

/**
 * Merge per-stream projection files into the dashboard state. The loader
 * uses this path when `state-snapshot.json` is absent but the seven
 * canonical per-stream files written by `dontpanic state export-dashboard`
 * are present (state_cli.py:_export_dashboard_main).
 *
 * `streams` is a partial map keyed by the on-disk stream name
 * (`plans`, `gates`, ..., `evidence_refs`). Each value must be an array.
 * Anything else is ignored — acceptance #4 (quiet empty state).
 *
 * Per-stream input has no envelope, so `snapshotMeta` stays null. If no
 * stream array contributes any entries, this is a no-op so legacy demo
 * files keep rendering (acceptance #2).
 *
 * @param {object} state
 * @param {object|null|undefined} streams
 * @returns {boolean} true if any stream was merged into state
 */
export function mergePerStreamIntoState(state, streams) {
  if (streams == null || typeof streams !== 'object') return false;
  const safe = {
    plans:        safeArray(streams.plans),
    gates:        safeArray(streams.gates),
    inbox:        safeArray(streams.inbox),
    supervisors:  safeArray(streams.supervisors),
    quota:        safeArray(streams.quota),
    decisions:    safeArray(streams.decisions),
    // evidence_refs (on-disk) → evidenceRefs (state key, JS-convention).
    evidenceRefs: safeArray(streams.evidence_refs),
  };
  const hasAny = Object.values(safe).some((arr) => arr.length > 0);
  if (!hasAny) return false;
  state.plans         = safe.plans;
  state.gates         = safe.gates;
  state.inbox         = safe.inbox;
  state.supervisors   = safe.supervisors;
  state.quota         = safe.quota;
  state.decisions     = safe.decisions;
  state.evidenceRefs  = safe.evidenceRefs;
  // No envelope → no metadata. Pages render the projection without a
  // capture-time line; UI treats snapshotMeta === null as "loaded from
  // per-stream files" the same way it treats "no projection at all".
  state.snapshotMeta  = null;
  state.tasks         = adaptPlansToTasks(safe.plans);
  state.agents        = adaptSupervisorsToAgents(safe.supervisors);
  state.activity      = adaptInboxToActivity(safe.inbox);
  return true;
}
