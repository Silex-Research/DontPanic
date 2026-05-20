// Plan 2026-05-09-004 F003 — kanban column-mapping unit tests.
//
// Addresses audit-i0 finding 2: kanban moves no longer emit the unknown
// `set_plan_status` MCP tool. Only transitions that map onto an existing
// dontpanic MCP tool are allowed in v0; everything else is rejected with
// `transition-not-supported-v0`.

import { describe, it, expect } from 'vitest';
import {
  resolveKanbanMove,
  COLUMN_TO_STATUS,
  KANBAN_COLUMNS,
  ColumnMappingError,
} from '../lib/column-mapping.js';

describe('COLUMN_TO_STATUS', () => {
  it('covers every kanban column', () => {
    for (const col of KANBAN_COLUMNS) {
      expect(typeof COLUMN_TO_STATUS[col]).toBe('string');
    }
  });
});

describe('resolveKanbanMove — supported v0 transitions', () => {
  it('todo → in_progress maps to MCP dispatch with confirm:true (default F001)', () => {
    const out = resolveKanbanMove({
      planId: '2026-05-09-004',
      currentColumn: 'todo',
      newColumn: 'in_progress',
    });
    expect(out.tool).toBe('dispatch');
    expect(out.arguments).toEqual({
      plan: '2026-05-09-004',
      feature: 'F001',
      confirm: true,
    });
  });

  it('threads explicit featureId when caller knows it', () => {
    const out = resolveKanbanMove({
      planId: 'plan-x',
      currentColumn: 'todo',
      newColumn: 'in_progress',
      featureId: 'F042',
    });
    expect(out.arguments.feature).toBe('F042');
  });
});

describe('resolveKanbanMove — rejected transitions', () => {
  it('rejects unknown newColumn', () => {
    expect(() =>
      resolveKanbanMove({ planId: 'p', currentColumn: 'todo', newColumn: 'wat' }),
    ).toThrowError(ColumnMappingError);
  });

  it('rejects same-column drops as no-op', () => {
    expect(() =>
      resolveKanbanMove({ planId: 'p', currentColumn: 'todo', newColumn: 'todo' }),
    ).toMatchErrorCode('no-op');
  });

  it('rejects backlog → done as transition-not-supported-v0', () => {
    expect(() =>
      resolveKanbanMove({ planId: 'p', currentColumn: 'backlog', newColumn: 'done' }),
    ).toMatchErrorCode('transition-not-supported-v0');
  });

  it('rejects review → done — there is no MCP tool for it in v0', () => {
    // Even though "close out" is a natural drag, the MCP server exposes
    // approve_gate/dispatch only — there is no set_plan_status, and the
    // plan forbids adding one. Caller must use the modal's Approve / CLI.
    expect(() =>
      resolveKanbanMove({ planId: 'p', currentColumn: 'review', newColumn: 'done' }),
    ).toMatchErrorCode('transition-not-supported-v0');
  });

  it('rejects backlog → in_progress (only todo → in_progress is mapped)', () => {
    expect(() =>
      resolveKanbanMove({ planId: 'p', currentColumn: 'backlog', newColumn: 'in_progress' }),
    ).toMatchErrorCode('transition-not-supported-v0');
  });

  it('rejects missing currentColumn (UI must know it)', () => {
    expect(() =>
      resolveKanbanMove({ planId: 'p', newColumn: 'in_progress' }),
    ).toMatchErrorCode('current-column-required');
  });

  it('rejects empty planId', () => {
    expect(() =>
      resolveKanbanMove({ planId: '', currentColumn: 'todo', newColumn: 'in_progress' }),
    ).toMatchErrorCode('invalid-plan-id');
  });

  it('includes a hint to supported transitions in the rejection details', () => {
    try {
      resolveKanbanMove({ planId: 'p', currentColumn: 'review', newColumn: 'in_progress' });
      throw new Error('expected throw');
    } catch (err) {
      expect(err).toBeInstanceOf(ColumnMappingError);
      expect(err.code).toBe('transition-not-supported-v0');
      expect(err.details.supported).toContain('todo->in_progress');
    }
  });
});

// Custom matcher: assert thrown error's .code property.
expect.extend({
  toMatchErrorCode(received, code) {
    try {
      received();
      return { pass: false, message: () => `expected to throw, but did not` };
    } catch (err) {
      if (err && err.code === code) {
        return { pass: true, message: () => `expected not to throw ${code}` };
      }
      return {
        pass: false,
        message: () => `expected code ${code}, got ${err && err.code}`,
      };
    }
  },
});
