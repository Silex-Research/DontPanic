// F008 — per-bucket handoff affordances. COPY/OPEN/HANDOFF only; never execute
// (D018). Bucket-aware labels; the command is the model's exact_command verbatim;
// a paste-into-agent handoff block; read-only contract (.copy-cmd-btn).

import { describe, it, expect } from 'vitest';
import {
  deriveInspectView,
  deriveAffordances,
  renderAffordancesHTML,
  renderInspectHTML,
} from '../../lib/operator-console-logic.js';

const detailFor = (bucket, over = {}) =>
  deriveInspectView({
    items: [{
      id: 'x', operator_bucket: bucket, title: 'Item X',
      why_now: 'because reasons', evidence_uri: 'a/b/gate-state.json',
      exact_command: 'dontpanic do-the-thing', ...over,
    }],
  }, 'x');

describe('deriveAffordances', () => {
  it('labels the primary copy action per bucket; command is the verbatim move', () => {
    expect(deriveAffordances(detailFor('needs_auth')).primary.label).toBe('Copy setup command');
    expect(deriveAffordances(detailFor('needs_decision')).primary.label).toBe('Copy approve command');
    expect(deriveAffordances(detailFor('agent_runnable')).primary.label).toBe('Copy command for an agent');
    expect(deriveAffordances(detailFor('auto_safe')).primary.label).toBe('Copy safe-apply command');
    expect(deriveAffordances(detailFor('needs_decision')).primary.command).toBe('dontpanic do-the-thing');
  });

  it('builds a paste-into-agent handoff with the full context', () => {
    const aff = deriveAffordances(detailFor('needs_decision'));
    expect(aff.handoff.text).toContain('Item X');
    expect(aff.handoff.text).toContain('Why: because reasons');
    expect(aff.handoff.text).toContain('Evidence: a/b/gate-state.json');
    expect(aff.handoff.text).toContain('Run: dontpanic do-the-thing');
  });

  it('offers an evidence-path copy only when evidence is present', () => {
    expect(deriveAffordances(detailFor('needs_auth')).evidence.command).toBe('a/b/gate-state.json');
    expect(deriveAffordances(detailFor('needs_auth', { evidence_uri: null })).evidence).toBeNull();
  });

  it('null detail yields no affordances', () => {
    const aff = deriveAffordances(null);
    expect(aff.primary).toBeNull();
    expect(aff.handoff).toBeNull();
  });
});

describe('renderAffordancesHTML', () => {
  it('renders read-only copy buttons (never an execute control) + the no-run note', () => {
    const html = renderAffordancesHTML(deriveAffordances(detailFor('needs_decision')));
    // copy buttons carry the command in data-copy — the read-only contract
    expect(html).toContain('copy-cmd-btn');
    expect(html).toContain('data-copy="dontpanic do-the-thing"');
    expect(html).toContain('Copy approve command');
    expect(html).toContain('Copy handoff for an agent');
    // explicit no-execute promise
    expect(html).toContain('Copying never runs anything');
    // there is NO run/execute/apply-now button — copy only
    expect(html).not.toContain('execute');
    expect(html.toLowerCase()).not.toContain('>run<');
  });

  it('empty when there is nothing to copy', () => {
    expect(renderAffordancesHTML({ primary: null, handoff: null })).toBe('');
  });

  it('the inspect drawer embeds the affordances for a selected item', () => {
    const html = renderInspectHTML(detailFor('needs_auth'));
    expect(html).toContain('console-affordances');
    expect(html).toContain('Copy setup command');
  });
});
