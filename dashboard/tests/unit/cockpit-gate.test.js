/*
 * F004 (cockpit merge + inspect-why) + F005 (gate flow + armed terminal) — plan 2026-06-06-004.
 * Pins: bucket grouping + the "N need you" hero count + collapsed quiet; the five fixed inspect
 * sections in order; the gate confirm names the run; approve resumes + leaves the queue; and the
 * armed terminal SHOUTS (hazard frame, scope, non-dismissible, disarm-only) — OFF by default.
 */

import { describe, it, expect } from 'vitest';
import {
  groupByBucket, needYouCount, renderQueue, renderInspectPanel, INSPECT_SECTIONS, NEED_YOU,
} from '../../components/cockpit.js';
import { resolveGate, applyResolution, runRef, APPROVAL_INTENTS } from '../../components/gate.js';
import { renderTerminalDock, isArmed } from '../../components/armed-terminal.js';

const mk = (id, bucket, extra = {}) => ({
  id, title: `${bucket} item ${id}`, operator_bucket: bucket, scope: 'project',
  project_name: 'mercury', run_state: 'idle', resolution: [], freshness_basis: null, ...extra,
});

const MODEL = {
  items: [
    mk('a1', 'needs_auth', { resolution: ['guided_setup'] }),
    mk('gate:2026-06-06-001-feat-x', 'needs_decision', { run_state: 'running', resolution: ['approve', 'request_changes', 'reject'], actor_label: 'Claude Auditor', provenance_source: 'claude-auditor' }),
    mk('d2', 'needs_decision', { resolution: ['approve', 'request_changes', 'reject'] }),
    mk('r1', 'agent_runnable', { resolution: ['run'] }),
    mk('r2', 'agent_runnable', { resolution: ['run'] }),
    mk('s1', 'auto_safe', { resolution: ['apply_fix'] }),
    mk('q1', 'quiet'), mk('q2', 'quiet'), mk('q3', 'quiet'),
  ],
};

describe('F004 — queue grouping + hero count', () => {
  it('hero "need you" = auth + decision + agent_runnable (not quiet/auto_safe)', () => {
    expect(needYouCount(MODEL)).toBe(1 + 2 + 2); // 5
  });

  it('groups in severity order; quiet + auto_safe are collapsed (counts, never feeds)', () => {
    const groups = groupByBucket(MODEL);
    expect(groups.map((g) => g.bucket)).toEqual(['needs_auth', 'needs_decision', 'agent_runnable', 'auto_safe', 'quiet']);
    expect(groups.find((g) => g.bucket === 'quiet').collapsed).toBe(true);
    expect(groups.find((g) => g.bucket === 'auto_safe').collapsed).toBe(true);
    expect(groups.find((g) => g.bucket === 'needs_decision').collapsed).toBe(false);
  });

  it('renders the hero, and collapsed groups emit a count but no feed', () => {
    const dom = renderQueue(MODEL);
    expect(dom.querySelector('.dp-hero-count').textContent).toBe('5');
    const quiet = dom.querySelector('.dp-group--quiet');
    expect(quiet.querySelector('.dp-group-count').textContent).toBe('3');
    expect(quiet.querySelector('.dp-group-feed')).toBeNull();
  });

  it('an all-quiet model collapses to the "you\'re clear" payoff, not a feed', () => {
    const dom = renderQueue({ items: [mk('q', 'quiet'), mk('q2', 'quiet')] });
    expect(dom.querySelector('.dp-clear-head').textContent).toBe("You're clear.");
    expect(dom.querySelector('.dp-hero')).toBeNull();
  });
});

describe('F004 — inspect-why panel (§5.2)', () => {
  it('renders exactly the five fixed sections, in order', () => {
    const panel = renderInspectPanel(MODEL.items[1]);
    const secs = [...panel.querySelectorAll('.dp-inspect-section')].map((s) => s.dataset.section);
    expect(secs).toEqual(INSPECT_SECTIONS.map((s) => s.key));
    expect(secs).toEqual(['what', 'why', 'evidence', 'provenance', 'resolution']);
  });

  it('provenance section surfaces the producer (actor_label) + states the freshness basis plainly', () => {
    const item = MODEL.items[1]; // actor_label "Claude Auditor", freshness_basis null
    const panel = renderInspectPanel(item);
    expect(panel.querySelector('.dp-inspect-actor').textContent).toContain('Claude Auditor');
    expect(panel.querySelector('.dp-inspect-basis').textContent).toContain('no basis'); // render-truth
  });

  it('resolution section maps buttons 1:1 to resolution[] with HUMAN labels (not raw ids)', () => {
    const panel = renderInspectPanel(MODEL.items[1]);
    const btns = [...panel.querySelectorAll('.dp-inspect-resolutions .dp-affordance')];
    expect(btns.map((b) => b.dataset.resolution)).toEqual(['approve', 'request_changes', 'reject']);
    expect(btns.map((b) => b.textContent)).toEqual(['Approve', 'Request changes', 'Reject']);
  });
});

describe('F005 — gate flow (§5.3)', () => {
  const gate = MODEL.items[1]; // running needs_decision with approve/changes/reject

  it('the confirm names the run being unblocked (never a guessed number)', () => {
    expect(runRef(gate)).toBe('2026-06-06-001-feat-x on mercury');
    expect(resolveGate(gate, 'approve').confirm).toBe('This will resume 2026-06-06-001-feat-x on mercury.');
    expect(resolveGate(gate, 'approve').isLiveGate).toBe(true);
  });

  it('refuses an intent the item does not offer (buttons == resolution[])', () => {
    expect(() => resolveGate(gate, 'run')).toThrow();
    expect(() => applyResolution(gate, 'apply_fix')).toThrow();
  });

  it('approve resumes the run + signals removal via the RESULT (item stays parity-clean)', () => {
    const r = applyResolution(gate, 'approve');
    expect(r.item.run_state).toBe('running');
    expect(r.removed).toBe(true);
    expect(r.intent).toBe('approve');
    // no UI-only fields leak onto the item (agent parity)
    expect(r.item.removedFromQueue).toBeUndefined();
    expect(r.item.resolved_intent).toBeUndefined();
  });

  it('reject stops the run; APPROVAL_INTENTS is the closed set', () => {
    expect(applyResolution(gate, 'reject').item.run_state).toBe('idle');
    expect(APPROVAL_INTENTS).toEqual(['approve', 'request_changes', 'reject']);
  });
});

describe('F005 — armed terminal SHOUTS; OFF by default (§5.5)', () => {
  it('OFF by default: quiet bar + an explicit Arm control, no hazard frame', () => {
    const dock = renderTerminalDock();
    expect(isArmed({})).toBe(false);
    expect(dock.dataset.armed).toBe('false');
    expect(dock.querySelector('.dp-dock-arm')).toBeTruthy();
    expect(dock.querySelector('.dp-hazard-frame')).toBeNull();
    expect(dock.classList.contains('dp-hazard')).toBe(false);
  });

  it('ARMED: red hazard frame, scope shown, "no sandbox", disarm-only (no close control)', () => {
    const dock = renderTerminalDock({ armed: true, scope: 'DontPanic repo', sessionActive: true });
    expect(dock.dataset.armed).toBe('true');
    expect(dock.classList.contains('dp-hazard')).toBe(true);
    const frame = dock.querySelector('.dp-hazard-frame');
    expect(frame.getAttribute('role')).toBe('alert'); // shouts to AT too
    expect(frame.querySelector('.dp-hazard-title').textContent).toContain('UNRESTRICTED LOCAL SHELL');
    expect(frame.querySelector('.dp-hazard-scope').textContent).toContain('DontPanic repo');
    expect(frame.querySelector('.dp-hazard-warn').textContent).toContain('No sandbox');
    // disarm is the only exit — no arm/close affordance while armed
    expect(dock.querySelector('.dp-dock-disarm')).toBeTruthy();
    expect(dock.querySelector('.dp-dock-arm')).toBeNull();
  });
});
