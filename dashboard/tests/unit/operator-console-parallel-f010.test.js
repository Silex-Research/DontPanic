// F010 — parallel-ops awareness. The model already derives run_state
// (idle/running/conflicted) + actor_label by joining items to the live
// active-supervisors registry; F010 renders concurrency: who's working what, and
// where two actors race one plan (conflicted). Derived read-only.

import { describe, it, expect } from 'vitest';
import {
  renderRunChipHTML,
  deriveParallelOps,
  renderParallelOpsBannerHTML,
  deriveConsoleView,
  renderConsoleDefaultHTML,
} from '../../lib/operator-console-logic.js';

const MODEL = {
  items: [
    { id: 'a', operator_bucket: 'needs_decision', exact_command: 'x', run_state: 'running', actor_label: 'claude · sess1', scope: 'project', project_name: 'glam' },
    { id: 'b', operator_bucket: 'needs_auth', exact_command: 'y', run_state: 'conflicted', actor_label: 'codex · sess2', scope: 'project', project_name: 'spindineswift' },
    { id: 'c', operator_bucket: 'needs_decision', exact_command: 'z', run_state: 'idle', actor_label: null, scope: 'global' },
  ],
  data_quality: { input_count: 3, total: 3, counts: { needs_decision: 2, needs_auth: 1 } },
};

describe('renderRunChipHTML', () => {
  it('is empty for idle', () => {
    expect(renderRunChipHTML('idle', null)).toBe('');
    expect(renderRunChipHTML(null, null)).toBe('');
  });
  it('shows the state + actor for running/conflicted', () => {
    expect(renderRunChipHTML('running', 'claude · sess1')).toContain('running');
    expect(renderRunChipHTML('running', 'claude · sess1')).toContain('claude · sess1');
    expect(renderRunChipHTML('conflicted', 'codex')).toContain('run-state--conflicted');
  });
});

describe('deriveParallelOps', () => {
  it('splits running vs conflicted with actors; counts them', () => {
    const ops = deriveParallelOps(MODEL);
    expect(ops.counts).toEqual({ running: 1, conflicted: 1 });
    expect(ops.running[0]).toMatchObject({ id: 'a', actor: 'claude · sess1', scope: 'glam' });
    expect(ops.conflicted[0]).toMatchObject({ id: 'b', actor: 'codex · sess2' });
  });
  it('is empty when nothing is live', () => {
    const ops = deriveParallelOps({ items: [{ id: 'c', run_state: 'idle' }] });
    expect(ops.counts).toEqual({ running: 0, conflicted: 0 });
  });
});

describe('renderParallelOpsBannerHTML', () => {
  it('summarizes running + conflicted and warns on conflict', () => {
    const html = renderParallelOpsBannerHTML(deriveParallelOps(MODEL));
    expect(html).toContain('1 running');
    expect(html).toContain('1 conflicted');
    expect(html).toContain('parallel-ops--conflicted');
    expect(html).toContain('two actors on one plan');
    expect(html).toContain('codex · sess2');
  });
  it('is empty when the install is quiet (no false concurrency cues)', () => {
    expect(renderParallelOpsBannerHTML(deriveParallelOps({ items: [{ id: 'c', run_state: 'idle' }] }))).toBe('');
  });
});

describe('queue rows carry run chips + conflicted styling', () => {
  it('renders the actor on a running row and flags a conflicted one', () => {
    const html = renderConsoleDefaultHTML(deriveConsoleView(MODEL));
    expect(html).toContain('claude · sess1');     // running actor on the row
    expect(html).toContain('is-conflicted');      // the conflicted row is visually distinct
    expect(html).toContain('run-state--conflicted');
  });
});
