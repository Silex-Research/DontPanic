// ── Mission Control Logic — Pure, DOM-free business logic ──
// Extracted from pages/mission-control/mission-control.js for testability.

import { renderProvenanceFooterHTML } from './provenance.js';

export const MC_COLUMNS = ['backlog', 'todo', 'in_progress', 'review', 'done'];

// V0 lifecycle labels per copy-map.md §2.3. Primary labels speak value
// ("Planned", "Ready to run", "Running", "Waiting on approval", "Done")
// instead of kanban-internal vocabulary. Plan/feature ids and gate names
// stay visible as Layer 2 metadata on each card and in the detail modal.
export const MC_COLUMN_META = {
  backlog:     { label: 'PLANNED',            dotClass: 'mc-dot--purple' },
  todo:        { label: 'READY TO RUN',       dotClass: 'mc-dot--blue'   },
  in_progress: { label: 'RUNNING',            dotClass: 'mc-dot--green'  },
  review:      { label: 'WAITING ON APPROVAL', dotClass: 'mc-dot--yellow' },
  done:        { label: 'DONE',               dotClass: 'mc-dot--gray'   },
};

// One-sentence value-first impact line per lifecycle column. Rendered
// under the column header so non-technical reviewers can answer
// "what does this state mean?" without learning the internal vocabulary.
export const MC_COLUMN_IMPACT = {
  backlog:     'Planned work not yet ready to start.',
  todo:        'Ready for an agent or operator to pick up.',
  in_progress: 'An agent or operator is actively working on this.',
  review:      'Waiting for human approval before it can move on.',
  done:        'Completed work, kept for reference.',
};

// Status field on task → kanban column
export const STATUS_TO_COLUMN = {
  backlog:     'backlog',
  inbox:       'backlog',
  pending:     'backlog',
  todo:        'todo',
  assigned:    'todo',
  in_progress: 'in_progress',
  active:      'in_progress',
  review:      'review',
  done:        'done',
  completed:   'done',
};

export const PROJECT_NAMES = {
  spindine: 'Spin & Dine',
  styln:    'Styln',
  quantre:  'quantRE',
  ibkr:     'IBKR',
  infra:    'Infra',
};

// Agent identity palette — keyed by agent id from state
export const AGENT_META = {
  claude:  { color: '#f97316', initials: 'CC', badge: 'LEAD',  badgeClass: 'lead' },
  codex:   { color: '#3b82f6', initials: 'CX', badge: 'INT',   badgeClass: 'int'  },
  gemini:  { color: '#22c55e', initials: 'GM', badge: 'SPC',   badgeClass: 'spc'  },
  grok:    { color: '#a855f7', initials: 'GK', badge: 'INT',   badgeClass: 'int'  },
  kimi:    { color: '#06b6d4', initials: 'KM', badge: 'SPC',   badgeClass: 'spc'  },
  qwen:    { color: '#eab308', initials: 'QW', badge: 'OPS',   badgeClass: 'ops'  },
};

/**
 * Returns the agent metadata for the given id, falling back to a generic
 * object for unknown ids.
 * @param {string|null|undefined} agentId
 * @returns {{ color: string, initials: string, badge: string, badgeClass: string }}
 */
export function getAgentMeta(agentId) {
  return AGENT_META[agentId] || {
    color:     '#64748b',
    initials:  (agentId || '??').slice(0, 2).toUpperCase(),
    badge:     'AGT',
    badgeClass: 'int',
  };
}

/**
 * Derives the kanban column for a task.
 * Explicit `task.column` (when valid) takes precedence over `task.status`.
 * Falls back to 'backlog' for unknown/missing values.
 * @param {{ column?: string, status?: string }} task
 * @returns {string}
 */
export function deriveColumn(task) {
  if (task.column && MC_COLUMNS.includes(task.column)) return task.column;
  return STATUS_TO_COLUMN[task.status] || 'backlog';
}

/**
 * Pure resolver for a kanban drag — given the task being dragged and the
 * column it landed on, decide whether to call the kanbanMove callable and
 * with what args, or surface a structured local rejection. Used by both
 * the mission-control page's drop handler and the realtime-actions
 * integration test (plan 2026-05-09-004 F003 audit-i1).
 *
 * Returns one of:
 *   - { action: 'noop', reason: 'same-column' | 'unknown-column' | … }
 *   - { action: 'reject-local', code, message } — surface to UI, do NOT
 *     hit the callable. Used to short-circuit drags that are
 *     definitely-unsupported in v0 so users see the message immediately.
 *   - { action: 'invoke', planId, currentColumn, newColumn, featureId? }
 *     — the dashboard should call realtimeActions.kanbanMove(...) and
 *     react to the result.
 *
 * The list of "definitely unsupported" transitions is kept in sync with
 * `dashboard/functions/lib/column-mapping.js` — the source of truth is on
 * the Cloud Function side so we can't drift, but pre-flighting here makes
 * the UX snappy and gives us a unit-test seam.
 *
 * @param {{ taskId: string, sourceColumn: string, targetColumn: string }} args
 * @returns {object}
 */
export function resolveDragIntent({ taskId, sourceColumn, targetColumn }) {
  if (!taskId || typeof taskId !== 'string') {
    return { action: 'noop', reason: 'no-task-id' };
  }
  if (!MC_COLUMNS.includes(targetColumn)) {
    return { action: 'noop', reason: 'unknown-target-column' };
  }
  if (sourceColumn && !MC_COLUMNS.includes(sourceColumn)) {
    return { action: 'noop', reason: 'unknown-source-column' };
  }
  if (sourceColumn === targetColumn) {
    return { action: 'noop', reason: 'same-column' };
  }
  // v0: only todo → in_progress is wired to an MCP tool (dispatch). Every
  // other drop must be rejected at the local layer so the user sees the
  // hint instead of waiting on a Cloud Function round-trip.
  if (sourceColumn === 'todo' && targetColumn === 'in_progress') {
    return {
      action: 'invoke',
      planId: taskId,
      currentColumn: sourceColumn,
      newColumn: targetColumn,
    };
  }
  return {
    action: 'reject-local',
    code: 'transition-not-supported-v0',
    message: (
      `Kanban drag ${sourceColumn || '?'} → ${targetColumn} is not wired to an ` +
      'MCP tool in v0. Use the modal\'s Approve / Dispatch buttons or the CLI ' +
      'for other status changes.'
    ),
  };
}

// ── F004: Work-page provenance footer ──
// The Work page reads three state files written together by
// `dontpanic dashboard build`; we summarise them as one source line and
// derive the freshest task / activity / agent timestamp as "updated".

/**
 * Pick the freshest ISO-8601 timestamp across the Work page's three
 * input arrays. Returns null when no candidate carries a string
 * timestamp — the provenance footer renders "—" in that case.
 *
 * @param {object} [state]
 * @param {Array<object>} [state.tasks]
 * @param {Array<object>} [state.agents]
 * @param {Array<object>} [state.activity]
 * @returns {string|null}
 */
export function deriveWorkLastUpdated({ tasks, agents, activity } = {}) {
  let best = '';
  const consider = (ts) => {
    if (typeof ts !== 'string' || ts.length === 0) return;
    if (ts > best) best = ts;
  };
  if (Array.isArray(tasks)) {
    for (const t of tasks) {
      consider(t && t.updated_at);
      consider(t && t.created);
    }
  }
  if (Array.isArray(activity)) {
    for (const a of activity) consider(a && a.timestamp);
  }
  if (Array.isArray(agents)) {
    for (const ag of agents) consider(ag && ag.lastSeen);
  }
  return best.length > 0 ? best : null;
}

/**
 * Render the Work-page provenance footer. Pure: returns the canonical
 * pv-footer HTML; the page module simply pipes it into the
 * #mc-queue-source slot. Matches the shared per-page treatment so the
 * F004 evidence test ("every V0 page renders a provenance footer")
 * passes for Work.
 *
 * @param {object} [state]
 * @returns {string}
 */
export function renderWorkProvenanceHTML(state = {}) {
  return renderProvenanceFooterHTML({
    source: 'dashboard/state/tasks.json + agents.json + activity.json',
    lastUpdated: deriveWorkLastUpdated(state),
    refreshCommand: 'dontpanic dashboard build',
    note: 'Work is read-only — cards reflect what the local cache already knows.',
  });
}
