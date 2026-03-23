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
