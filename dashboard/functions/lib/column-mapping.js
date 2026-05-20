// ── Kanban column → DontPanic MCP request mapping ──
// Plan 2026-05-09-004 F003. The mission-control board uses the columns
// declared in dashboard/lib/mission-control-logic.js. Most plan-status
// transitions in DontPanic happen via `dispatch` / `approve_gate`, not
// arbitrary status flips. The local MCP server (scripts/dontpanic_orchestrate/
// mcp_server.py) exposes a closed 8-tool surface — there is NO
// `set_plan_status` tool, and adding one would mean editing DontPanic core
// which the plan's forbidden_decisions explicitly disallows.
//
// v0 therefore restricts kanban drag-flips to the single transition that
// maps cleanly onto an existing supported MCP tool — `todo → in_progress`
// kicks off `dispatch` for the plan's first feature. Every other drag is
// rejected with `transition-not-supported-v0`; the dashboard surfaces that
// as a "use Approve / Dispatch buttons or the CLI" hint. This addresses
// audit-i0 finding 2 (kanbanMove calling unknown set_plan_status).

export const KANBAN_COLUMNS = Object.freeze([
  'backlog',
  'todo',
  'in_progress',
  'review',
  'done',
]);

// Column → plan-status string. Kept around so consumers that need to
// translate a column into a status field (e.g. the projection layer) can
// share one source of truth with the mutation layer.
export const COLUMN_TO_STATUS = Object.freeze({
  backlog: 'draft',
  todo: 'todo',
  in_progress: 'active',
  review: 'review',
  done: 'done',
});

// Per-transition mapper. Each entry returns a structured MCP request the
// bridge will issue. Anything NOT listed here is rejected with
// `transition-not-supported-v0` — callers must use the modal's Approve /
// Dispatch buttons (or the CLI) for arbitrary status changes.
//
// v0 surface (existing MCP tools only):
//   - todo → in_progress: `dispatch` with confirm:true. featureId defaults
//     to the plan's F001 unless the dashboard knows a more specific one.
const TRANSITIONS = Object.freeze({
  'todo->in_progress': ({ planId, featureId }) => ({
    tool: 'dispatch',
    arguments: {
      plan: planId,
      feature: typeof featureId === 'string' && featureId.length > 0
        ? featureId
        : 'F001',
      confirm: true,
    },
  }),
});

export class ColumnMappingError extends Error {
  constructor(code, message, details = null) {
    super(message);
    this.name = 'ColumnMappingError';
    this.code = code;
    this.details = details;
  }
}

export function resolveKanbanMove({ planId, currentColumn, newColumn, featureId }) {
  if (typeof planId !== 'string' || planId.length === 0) {
    throw new ColumnMappingError('invalid-plan-id', 'planId is required');
  }
  if (!KANBAN_COLUMNS.includes(newColumn)) {
    throw new ColumnMappingError(
      'invalid-column',
      `newColumn must be one of ${KANBAN_COLUMNS.join(',')}`,
    );
  }
  if (!currentColumn) {
    // We cannot map a drag to an MCP tool without knowing where it came
    // from — the supported transitions are direction-sensitive. The
    // dashboard always knows the source column (it's the column the card
    // currently lives under), so this branch is a contract violation.
    throw new ColumnMappingError(
      'current-column-required',
      'currentColumn is required to resolve a kanban drag to an MCP request',
    );
  }
  if (!KANBAN_COLUMNS.includes(currentColumn)) {
    throw new ColumnMappingError(
      'invalid-current-column',
      `currentColumn must be one of ${KANBAN_COLUMNS.join(',')}`,
    );
  }
  if (currentColumn === newColumn) {
    throw new ColumnMappingError('no-op', `column unchanged: ${newColumn}`);
  }
  const key = `${currentColumn}->${newColumn}`;
  const mapper = TRANSITIONS[key];
  if (!mapper) {
    throw new ColumnMappingError(
      'transition-not-supported-v0',
      (
        `kanban drag ${key} is not supported in v0 — only todo→in_progress ` +
        'maps to an MCP tool (dispatch). Use the Approve / Dispatch buttons ' +
        'or the dontpanic CLI for other status changes.'
      ),
      { transition: key, supported: Object.keys(TRANSITIONS) },
    );
  }
  return mapper({ planId, featureId });
}
