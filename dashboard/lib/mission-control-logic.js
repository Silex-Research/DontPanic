// ── Mission Control Logic — Pure, DOM-free business logic ──
// Extracted from pages/mission-control/mission-control.js for testability.

export const MC_COLUMNS = ['backlog', 'todo', 'in_progress', 'review', 'done'];

export const MC_COLUMN_META = {
  backlog:     { label: 'INBOX',       dotClass: 'mc-dot--purple' },
  todo:        { label: 'ASSIGNED',    dotClass: 'mc-dot--blue'   },
  in_progress: { label: 'IN PROGRESS', dotClass: 'mc-dot--green'  },
  review:      { label: 'REVIEW',      dotClass: 'mc-dot--yellow' },
  done:        { label: 'DONE',        dotClass: 'mc-dot--gray'   },
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
