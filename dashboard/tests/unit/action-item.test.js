/*
 * F003 — the ActionItem atom (plan 2026-06-06-004, spec §2.4/§3). Pins agent parity (every
 * visual element ← a real operator-triage/v0 field), card/row field-sameness, resolution
 * affordances replacing copy-command-as-primary, and the "you're clear" payoff.
 */

import { describe, it, expect } from 'vitest';
import {
  renderCard, renderRow, renderItem, renderEmptyState, freshnessState,
  BUCKET_LABELS, RESOLUTION_LABELS,
} from '../../components/action-item.js';

const ITEM = Object.freeze({
  id: 'gate:2026-06-06-001-feat-x',
  title: 'Security audit paused',
  operator_bucket: 'needs_decision',
  scope: 'project',
  project_name: 'mercury',
  run_state: 'running',
  actor_label: 'Claude Auditor',
  why_now: 'Cross-model audit disagreed on input validation.',
  evidence_uri: 'docs/plans/x/audit.json#17',
  exact_command: 'dontpanic approve …',
  resolution: ['approve', 'request_changes', 'reject'],
  asserted_at: '2026-06-06T12:00:00Z',
  freshness_basis: 'live_supervisor_plan_match',
  provenance_source: 'claude-auditor',
  duplicate_count: 3,
});

describe('agent parity — every visual element maps to a field', () => {
  it('card carries bucket / scope / run_state / id as data-attrs (machine-readable)', () => {
    const c = renderCard(ITEM);
    expect(c.dataset.bucket).toBe('needs_decision');
    expect(c.dataset.scope).toBe('project');
    expect(c.dataset.runState).toBe('running');
    expect(c.dataset.itemId).toBe(ITEM.id);
  });

  it('title comes from item.title; why-now from item.why_now', () => {
    const c = renderCard(ITEM);
    expect(c.querySelector('.dp-item-title').textContent).toBe('Security audit paused');
    expect(c.querySelector('.dp-item-why').textContent).toContain('input validation');
  });

  it('resolution buttons map 1:1 to resolution[] (button ⟵ intent)', () => {
    const c = renderCard(ITEM);
    const btns = [...c.querySelectorAll('.dp-affordance')];
    expect(btns.map((b) => b.dataset.resolution)).toEqual(['approve', 'request_changes', 'reject']);
    expect(btns.map((b) => b.textContent)).toEqual(['Approve', 'Request changes', 'Reject']);
  });

  it('shows the actor + duplicate_count, and the freshness dot', () => {
    const c = renderCard(ITEM);
    expect(c.querySelector('.dp-actor').textContent).toBe('Claude Auditor');
    expect(c.querySelector('.dp-dupes').textContent).toBe('asserted by 3');
    expect(c.querySelector('.dp-freshness')).toBeTruthy();
  });
});

describe('resolution replaces copy-command-as-primary (§3.3)', () => {
  it('the literal exact_command never appears on the card face', () => {
    const c = renderCard(ITEM);
    expect(c.textContent).not.toContain('dontpanic approve');
  });

  it('agent_runnable with a command → a single Run affordance', () => {
    const c = renderCard({ id: 'a', title: 'X', operator_bucket: 'agent_runnable', resolution: ['run'] });
    const btns = [...c.querySelectorAll('.dp-affordance')];
    expect(btns).toHaveLength(1);
    expect(btns[0].dataset.resolution).toBe('run');
  });

  it('quiet items carry no affordances', () => {
    const c = renderCard({ id: 'q', title: 'fyi', operator_bucket: 'quiet', resolution: [] });
    expect(c.querySelectorAll('.dp-affordance')).toHaveLength(0);
  });
});

describe('render-truth dot (§2.2)', () => {
  it('plan-level / null freshness → hollow (unproven); only item_probe → proven', () => {
    expect(freshnessState({ freshness_basis: 'live_supervisor_plan_match' })).toBe('unproven');
    expect(freshnessState({ freshness_basis: null })).toBe('unproven');
    expect(freshnessState({ freshness_basis: 'item_probe' })).toBe('proven');
    const c = renderCard(ITEM); // plan-level → hollow
    expect(c.querySelector('.dp-freshness').dataset.freshness).toBe('unproven');
  });
});

describe('card vs row — same fields, two densities (§2.4/§8)', () => {
  const fields = (node) => ({
    bucket: node.dataset.bucket, scope: node.dataset.scope, run: node.dataset.runState,
    title: node.querySelector('.dp-item-title').textContent,
    resolutions: [...node.querySelectorAll('.dp-affordance')].map((b) => b.dataset.resolution),
  });
  it('the row renders the same load-bearing fields as the card', () => {
    expect(fields(renderRow(ITEM))).toEqual(fields(renderCard(ITEM)));
  });
  it('renderItem switches on density', () => {
    expect(renderItem(ITEM, { density: 'dense' }).classList.contains('dp-item--row')).toBe(true);
    expect(renderItem(ITEM, { density: 'comfort' }).classList.contains('dp-item--card')).toBe(true);
  });
  it('scope chip is suppressed when showScope=false (single-project frame, §4)', () => {
    expect(renderCard(ITEM, { showScope: false }).querySelector('.dp-scope-chip')).toBeNull();
  });
  it('a project chip names the real project_name (§4 parity — fleet items distinguishable)', () => {
    expect(renderCard(ITEM).querySelector('.dp-scope-chip').textContent).toBe('mercury');
    const g = renderCard({ id: 'g', title: 'X', operator_bucket: 'quiet', scope: 'global', resolution: [] });
    expect(g.querySelector('.dp-scope-chip').textContent).toBe('Install-level');
  });
});

describe('"you\'re clear" payoff (§2.5)', () => {
  it('reads as the product working, not a broken/empty page', () => {
    const e = renderEmptyState({ signals: 412, projects: 7, lastRefresh: '2m ago' });
    expect(e.querySelector('.dp-clear-head').textContent).toBe("You're clear.");
    expect(e.querySelector('.dp-clear-proof').textContent).toContain('412 monitored signals across 7');
    expect(e.textContent).not.toMatch(/no items/i);
    expect(e.querySelector('.dp-freshness--proven')).toBeTruthy(); // a full refresh is proven
  });
});

describe('label vocabularies stay closed', () => {
  it('every bucket + resolution intent has a human label', () => {
    for (const b of ['needs_auth', 'needs_decision', 'agent_runnable', 'auto_safe', 'uncertain', 'quiet'])
      expect(BUCKET_LABELS[b]).toBeTruthy();
    for (const r of ['approve', 'request_changes', 'reject', 'run', 'apply_fix', 'guided_setup', 'inspect'])
      expect(RESOLUTION_LABELS[r]).toBeTruthy();
  });
});
