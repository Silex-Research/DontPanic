// ── Security Logic — Unit Tests ──

import { describe, it, expect } from 'vitest';
import {
  ACTION_COLORS,
  ACTION_LABELS,
  HOOK_DEFS,
  aggregateStats,
  aggregatePerAgent,
  matchHookDecisions,
} from '../../lib/security-logic.js';

// ── Constants exported correctly ──

describe('ACTION_COLORS', () => {
  it('exports a color for each known action', () => {
    expect(ACTION_COLORS.block).toBe('red');
    expect(ACTION_COLORS.require_approval).toBe('yellow');
    expect(ACTION_COLORS.log).toBe('accent');
    expect(ACTION_COLORS.allow).toBe('green');
  });
});

describe('ACTION_LABELS', () => {
  it('exports a label for each known action', () => {
    expect(ACTION_LABELS.block).toBe('BLOCK');
    expect(ACTION_LABELS.require_approval).toBe('APPROVAL');
    expect(ACTION_LABELS.log).toBe('LOG');
    expect(ACTION_LABELS.allow).toBe('ALLOW');
  });
});

describe('HOOK_DEFS', () => {
  it('is an array of hook definitions', () => {
    expect(Array.isArray(HOOK_DEFS)).toBe(true);
    expect(HOOK_DEFS.length).toBeGreaterThan(0);
  });

  it('each hook has id, label, description, and categories array', () => {
    for (const hook of HOOK_DEFS) {
      expect(typeof hook.id).toBe('string');
      expect(typeof hook.label).toBe('string');
      expect(typeof hook.description).toBe('string');
      expect(Array.isArray(hook.categories)).toBe(true);
    }
  });

  it('contains the security-gate, git-safety, and api-audit hooks', () => {
    const ids = HOOK_DEFS.map(h => h.id);
    expect(ids).toContain('security-gate');
    expect(ids).toContain('git-safety');
    expect(ids).toContain('api-audit');
  });
});

// ── aggregateStats ──

describe('aggregateStats', () => {
  it('returns zeros for an empty decisions array', () => {
    const result = aggregateStats([]);
    expect(result).toEqual({ total: 0, blocks: 0, approvals: 0, logged: 0 });
  });

  it('counts total correctly', () => {
    const decisions = [
      { action: 'block' },
      { action: 'log' },
      { action: 'allow' },
    ];
    expect(aggregateStats(decisions).total).toBe(3);
  });

  it('counts blocks correctly', () => {
    const decisions = [
      { action: 'block' },
      { action: 'block' },
      { action: 'allow' },
    ];
    expect(aggregateStats(decisions).blocks).toBe(2);
  });

  it('counts require_approval correctly', () => {
    const decisions = [
      { action: 'require_approval' },
      { action: 'log' },
    ];
    expect(aggregateStats(decisions).approvals).toBe(1);
  });

  it('counts logged correctly', () => {
    const decisions = [
      { action: 'log' },
      { action: 'log' },
      { action: 'log' },
    ];
    expect(aggregateStats(decisions).logged).toBe(3);
  });

  it('handles mixed actions in a single pass', () => {
    const decisions = [
      { action: 'block' },
      { action: 'require_approval' },
      { action: 'log' },
      { action: 'allow' },
      { action: 'block' },
    ];
    const result = aggregateStats(decisions);
    expect(result.total).toBe(5);
    expect(result.blocks).toBe(2);
    expect(result.approvals).toBe(1);
    expect(result.logged).toBe(1);
  });
});

// ── aggregatePerAgent ──

describe('aggregatePerAgent', () => {
  it('returns an empty object for an empty array', () => {
    expect(aggregatePerAgent([])).toEqual({});
  });

  it('groups decisions by agent name', () => {
    const decisions = [
      { agent: 'claude', action: 'block',   timestamp: '2026-01-01T10:00:00Z' },
      { agent: 'claude', action: 'log',     timestamp: '2026-01-01T11:00:00Z' },
      { agent: 'codex',  action: 'allow',   timestamp: '2026-01-01T09:00:00Z' },
    ];
    const result = aggregatePerAgent(decisions);
    expect(Object.keys(result)).toContain('claude');
    expect(Object.keys(result)).toContain('codex');
    expect(result.claude.total).toBe(2);
    expect(result.codex.total).toBe(1);
  });

  it('counts each action type per agent', () => {
    const decisions = [
      { agent: 'claude', action: 'block' },
      { agent: 'claude', action: 'block' },
      { agent: 'claude', action: 'require_approval' },
      { agent: 'claude', action: 'log' },
      { agent: 'claude', action: 'allow' },
    ];
    const result = aggregatePerAgent(decisions);
    expect(result.claude.blocks).toBe(2);
    expect(result.claude.approvals).toBe(1);
    expect(result.claude.logged).toBe(1);
    expect(result.claude.allowed).toBe(1);
  });

  it('tracks the most recent timestamp per agent', () => {
    const decisions = [
      { agent: 'claude', action: 'log', timestamp: '2026-01-01T08:00:00Z' },
      { agent: 'claude', action: 'log', timestamp: '2026-01-01T12:00:00Z' },
      { agent: 'claude', action: 'log', timestamp: '2026-01-01T06:00:00Z' },
    ];
    const result = aggregatePerAgent(decisions);
    expect(result.claude.last).toBe('2026-01-01T12:00:00Z');
  });

  it('falls back to "unknown" for decisions with no agent field', () => {
    const decisions = [{ action: 'block' }];
    const result = aggregatePerAgent(decisions);
    expect(result.unknown.total).toBe(1);
  });
});

// ── matchHookDecisions ──

describe('matchHookDecisions', () => {
  it('returns count 0 and no lastFired for a hook with no matching decisions', () => {
    const hook = HOOK_DEFS.find(h => h.id === 'security-gate');
    const result = matchHookDecisions(hook, []);
    expect(result.count).toBe(0);
    expect(result.blocks).toBe(0);
    expect(result.lastFired).toBeNull();
  });

  it('matches decisions whose category is in hook.categories', () => {
    const hook = HOOK_DEFS.find(h => h.id === 'security-gate');
    const decisions = [
      { category: 'file_write', action: 'block', timestamp: '2026-01-01T10:00:00Z' },
      { category: 'api_call',   action: 'log',   timestamp: '2026-01-01T10:00:00Z' },
    ];
    const result = matchHookDecisions(hook, decisions);
    expect(result.count).toBe(1);
  });

  it('counts blocks within matched decisions', () => {
    const hook = HOOK_DEFS.find(h => h.id === 'git-safety');
    const decisions = [
      { category: 'git_push', action: 'block', timestamp: '2026-01-01T10:00:00Z' },
      { category: 'git_push', action: 'log',   timestamp: '2026-01-01T11:00:00Z' },
      { category: 'git_push', action: 'block', timestamp: '2026-01-01T12:00:00Z' },
    ];
    const result = matchHookDecisions(hook, decisions);
    expect(result.blocks).toBe(2);
  });

  it('returns the latest timestamp of matched decisions', () => {
    const hook = HOOK_DEFS.find(h => h.id === 'api-audit');
    const decisions = [
      { category: 'api_call', action: 'log', timestamp: '2026-01-01T09:00:00Z' },
      { category: 'api_call', action: 'log', timestamp: '2026-01-01T15:00:00Z' },
      { category: 'api_call', action: 'log', timestamp: '2026-01-01T12:00:00Z' },
    ];
    const result = matchHookDecisions(hook, decisions);
    expect(result.lastFired).toBe('2026-01-01T15:00:00Z');
  });
});
