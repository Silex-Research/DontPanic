// ── Mission Control Logic — Unit Tests ──

import { describe, it, expect } from 'vitest';
import {
  MC_COLUMNS,
  MC_COLUMN_META,
  STATUS_TO_COLUMN,
  PROJECT_NAMES,
  AGENT_META,
  deriveColumn,
  getAgentMeta,
} from '../../lib/mission-control-logic.js';

// ── Constants exported correctly ──

describe('MC_COLUMNS', () => {
  it('is an array with the five expected columns in order', () => {
    expect(MC_COLUMNS).toEqual(['backlog', 'todo', 'in_progress', 'review', 'done']);
  });
});

describe('MC_COLUMN_META', () => {
  it('has an entry for every column in MC_COLUMNS', () => {
    for (const col of MC_COLUMNS) {
      expect(MC_COLUMN_META).toHaveProperty(col);
      expect(MC_COLUMN_META[col]).toHaveProperty('label');
      expect(MC_COLUMN_META[col]).toHaveProperty('dotClass');
    }
  });
});

describe('STATUS_TO_COLUMN', () => {
  it('maps backlog → backlog', () => {
    expect(STATUS_TO_COLUMN.backlog).toBe('backlog');
  });

  it('maps inbox → backlog', () => {
    expect(STATUS_TO_COLUMN.inbox).toBe('backlog');
  });

  it('maps pending → backlog', () => {
    expect(STATUS_TO_COLUMN.pending).toBe('backlog');
  });

  it('maps todo → todo', () => {
    expect(STATUS_TO_COLUMN.todo).toBe('todo');
  });

  it('maps assigned → todo', () => {
    expect(STATUS_TO_COLUMN.assigned).toBe('todo');
  });

  it('maps in_progress → in_progress', () => {
    expect(STATUS_TO_COLUMN.in_progress).toBe('in_progress');
  });

  it('maps active → in_progress', () => {
    expect(STATUS_TO_COLUMN.active).toBe('in_progress');
  });

  it('maps review → review', () => {
    expect(STATUS_TO_COLUMN.review).toBe('review');
  });

  it('maps done → done', () => {
    expect(STATUS_TO_COLUMN.done).toBe('done');
  });

  it('maps completed → done', () => {
    expect(STATUS_TO_COLUMN.completed).toBe('done');
  });
});

describe('PROJECT_NAMES', () => {
  it('exports a PROJECT_NAMES map with known projects', () => {
    expect(PROJECT_NAMES).toMatchObject({
      spindine: 'Spin & Dine',
      styln: 'Styln',
      quantre: 'quantRE',
      ibkr: 'IBKR',
      infra: 'Infra',
    });
  });
});

// ── deriveColumn ──

describe('deriveColumn', () => {
  it('returns task.column directly when it is a valid column', () => {
    expect(deriveColumn({ column: 'review', status: 'done' })).toBe('review');
  });

  it('ignores task.column when it is not in MC_COLUMNS', () => {
    expect(deriveColumn({ column: 'unknown_col', status: 'done' })).toBe('done');
  });

  it('maps status backlog → backlog column', () => {
    expect(deriveColumn({ status: 'backlog' })).toBe('backlog');
  });

  it('maps status inbox → backlog column', () => {
    expect(deriveColumn({ status: 'inbox' })).toBe('backlog');
  });

  it('maps status pending → backlog column', () => {
    expect(deriveColumn({ status: 'pending' })).toBe('backlog');
  });

  it('maps status todo → todo column', () => {
    expect(deriveColumn({ status: 'todo' })).toBe('todo');
  });

  it('maps status assigned → todo column', () => {
    expect(deriveColumn({ status: 'assigned' })).toBe('todo');
  });

  it('maps status in_progress → in_progress column', () => {
    expect(deriveColumn({ status: 'in_progress' })).toBe('in_progress');
  });

  it('maps status active → in_progress column', () => {
    expect(deriveColumn({ status: 'active' })).toBe('in_progress');
  });

  it('maps status done → done column', () => {
    expect(deriveColumn({ status: 'done' })).toBe('done');
  });

  it('maps status completed → done column', () => {
    expect(deriveColumn({ status: 'completed' })).toBe('done');
  });

  it('falls back to backlog for an unknown status', () => {
    expect(deriveColumn({ status: 'weird_unknown_status' })).toBe('backlog');
  });

  it('falls back to backlog when status is undefined', () => {
    expect(deriveColumn({})).toBe('backlog');
  });
});

// ── getAgentMeta ──

describe('getAgentMeta', () => {
  it('returns known agent metadata for claude', () => {
    const meta = getAgentMeta('claude');
    expect(meta.initials).toBe('CC');
    expect(meta.badge).toBe('LEAD');
  });

  it('returns default metadata for an unknown agent id', () => {
    const meta = getAgentMeta('mystery-agent');
    expect(meta.color).toBe('#64748b');
    expect(meta.badge).toBe('AGT');
    expect(meta.initials).toBe('MY');
  });

  it('handles null/undefined agent id gracefully', () => {
    const meta = getAgentMeta(null);
    expect(meta.initials).toBe('??');
  });
});
