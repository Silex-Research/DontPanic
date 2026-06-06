// F007 — operator console inspect surfaces: decision drawer (decide from evidence
// in place, H3), why-hidden inspector (audit the compression, H6), activity strip
// (one evidence source + pipeline line, H2). Verified on the real F001 model.

import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

import {
  deriveInspectView,
  renderInspectHTML,
  deriveWhyHidden,
  renderWhyHiddenHTML,
  renderActivityStripHTML,
} from '../../lib/operator-console-logic.js';

const _here = dirname(fileURLToPath(import.meta.url));
const MODEL = JSON.parse(readFileSync(join(_here, '../fixtures/operator-triage-model.json'), 'utf8'));

const firstHuman = MODEL.items.find((i) => i.operator_bucket === 'needs_decision' || i.operator_bucket === 'needs_auth');

describe('deriveInspectView (decision drawer)', () => {
  it('returns null when nothing is selected / unknown id', () => {
    expect(deriveInspectView(MODEL, undefined)).toBeNull();
    expect(deriveInspectView(MODEL, 'no-such-id')).toBeNull();
  });

  it('returns the selected human item with its move (command) and bucket', () => {
    const d = deriveInspectView(MODEL, firstHuman.id);
    expect(d.id).toBe(firstHuman.id);
    expect(['needs_decision', 'needs_auth']).toContain(d.bucket);
    expect(d.move).toBe(firstHuman.exact_command);
  });

  it('surfaces why_now + evidence when the model carries them (decide without reading source)', () => {
    const synthetic = {
      items: [{
        id: 'g1', operator_bucket: 'needs_decision', scope: 'project', project_name: 'spindineswift',
        title: 'Approval needed on plan-x', why_now: 'All features pass; merge gate waiting.',
        evidence_uri: 'docs/plans/plan-x/audit/gate-state.json',
        exact_command: 'dontpanic approve plan-x pre_merge', run_state: 'idle',
      }],
    };
    const d = deriveInspectView(synthetic, 'g1');
    expect(d.whyNow).toBe('All features pass; merge gate waiting.');
    expect(d.evidence).toBe('docs/plans/plan-x/audit/gate-state.json');
  });

  it('falls back to a bucket-derived why-now when the model has none', () => {
    const d = deriveInspectView({ items: [{ id: 'a', operator_bucket: 'needs_auth' }] }, 'a');
    expect(d.whyNow.toLowerCase()).toContain('credentials');
  });
});

describe('renderInspectHTML', () => {
  it('empty state prompts a selection', () => {
    expect(renderInspectHTML(null).toLowerCase()).toContain('select an item');
  });

  it('renders title, why-now, evidence and the move; no raw JSON', () => {
    const d = deriveInspectView({
      items: [{ id: 'g1', operator_bucket: 'needs_decision', title: 'Approval needed on plan-x',
        why_now: 'gate waiting', evidence_uri: 'a/b/gate-state.json', exact_command: 'dontpanic approve plan-x pre_merge' }],
    }, 'g1');
    const html = renderInspectHTML(d);
    expect(html).toContain('Approval needed on plan-x');
    expect(html).toContain('gate waiting');
    expect(html).toContain('a/b/gate-state.json');
    expect(html).toContain('dontpanic approve plan-x pre_merge');
    expect(html).not.toContain('"operator_bucket"');
  });
});

describe('deriveWhyHidden (audit the compression)', () => {
  it('groups every non-human bucket with a reason; never the human/uncertain buckets', () => {
    const groups = deriveWhyHidden(MODEL);
    const buckets = groups.map((g) => g.bucket);
    expect(buckets).toContain('agent_runnable');
    expect(buckets).toContain('quiet');
    expect(buckets).not.toContain('needs_auth');
    expect(buckets).not.toContain('needs_decision');
    groups.forEach((g) => { expect(g.reason).toBeTruthy(); expect(g.items.length).toBeGreaterThan(0); });
  });

  it('renders the buckets, counts and reasons', () => {
    const html = renderWhyHiddenHTML(deriveWhyHidden(MODEL));
    expect(html).toContain('agent_runnable');
    expect(html).toContain('an agent can run it');
    expect(html).toContain('100'); // the agent_runnable count
  });
});

describe('renderActivityStripHTML', () => {
  it('carries the raw -> unique -> need-you pipeline line', () => {
    expect(renderActivityStripHTML(MODEL, [])).toContain('313 → 182 unique → 14 need you');
  });

  it('renders recent agent/auto actions when present', () => {
    const html = renderActivityStripHTML(MODEL, [{ when: '12:04', summary: 'agent ran reconcile baseline' }]);
    expect(html).toContain('agent ran reconcile baseline');
  });
});
