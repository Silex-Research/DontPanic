/*
 * F006 (domain regroup) + F007 (freshness everywhere) — plan 2026-06-06-004, spec §1/§2.2/§6.
 * Pins: the 8 old tabs all resolve into Cockpit/Work/System; Repair dissolves into the queue;
 * Architecture moves under Work; and the freshness grammar keeps render-truth (filled dot only
 * for item_probe; plan-level/none stay hollow + desaturated regardless of age).
 */

import { describe, it, expect } from 'vitest';
import { DOMAINS, OLD_TO_NEW, resolveDomain, renderNav } from '../../components/nav-ia.js';
import { freshnessView, renderFreshnessDot, staleBanner, relativeAge, FRESHNESS_STATES } from '../../components/freshness.js';

describe('F006 — three-domain IA (§1.3)', () => {
  it('collapses to exactly Cockpit / Work / System', () => {
    expect(DOMAINS.map((d) => d.id)).toEqual(['cockpit', 'work', 'system']);
  });

  it('every one of the 8 old tabs resolves to a new home', () => {
    const old = ['operator-console', 'what-now', 'repair', 'mission-control', 'architecture', 'health', 'capabilities', 'settings'];
    for (const t of old) expect(resolveDomain(t), `${t} unmapped`).toBeTruthy();
    expect(Object.keys(OLD_TO_NEW).sort()).toEqual(old.sort());
  });

  it('Repair DISSOLVES into the cockpit queue (not its own tab)', () => {
    expect(resolveDomain('repair')).toEqual({ domain: 'cockpit', view: 'overview', disposition: 'dissolved' });
  });

  it('Architecture MOVES under Work', () => {
    expect(resolveDomain('architecture')).toEqual({ domain: 'work', view: 'architecture', disposition: 'moved' });
  });

  it('renders three domain buttons + the active domain\'s sub-nav', () => {
    const nav = renderNav('work', 'architecture');
    expect([...nav.querySelectorAll('.dp-nav-domain')].map((b) => b.dataset.domain)).toEqual(['cockpit', 'work', 'system']);
    expect(nav.querySelector('.dp-nav-domain--active').dataset.domain).toBe('work');
    expect([...nav.querySelectorAll('.dp-nav-sub')].map((b) => b.dataset.view)).toContain('architecture');
    expect(nav.querySelector('.dp-nav-sub--active').dataset.view).toBe('architecture');
  });
});

describe('F007 — freshness grammar render-truth (§2.2)', () => {
  const NOW = Date.parse('2026-06-06T12:00:00Z');

  it('plan-level / no basis → hollow + desaturated, regardless of how recent asserted_at is', () => {
    const recentButUnproven = { freshness_basis: 'live_supervisor_plan_match', asserted_at: '2026-06-06T11:59:00Z' };
    const v = freshnessView(recentButUnproven, NOW);
    expect(v.state).toBe('unproven');
    expect(v.filled).toBe(false);
    expect(v.desaturate).toBe(true);
  });

  it('item_probe → filled; age picks fresh / aging / stale', () => {
    const at = (iso) => ({ freshness_basis: 'item_probe', asserted_at: iso });
    expect(freshnessView(at('2026-06-06T11:40:00Z'), NOW).state).toBe('fresh');  // 20m
    expect(freshnessView(at('2026-06-06T06:00:00Z'), NOW).state).toBe('aging');  // 6h
    expect(freshnessView(at('2026-06-04T12:00:00Z'), NOW).state).toBe('stale');  // 2d
    expect(freshnessView(at('2026-06-04T12:00:00Z'), NOW).desaturate).toBe(true);
  });

  it('the dot keys filled/state off the view; unproven never claims a filled state', () => {
    const dot = renderFreshnessDot({ freshness_basis: 'live_supervisor_plan_match', asserted_at: '2026-06-06T11:59:00Z' }, NOW);
    expect(dot.dataset.filled).toBe('false');
    expect(dot.classList.contains('dp-freshness--unproven')).toBe(true);
    expect(dot.classList.contains('dp-desaturate')).toBe(true);
    const proven = renderFreshnessDot({ freshness_basis: 'item_probe', asserted_at: '2026-06-06T11:40:00Z' }, NOW);
    expect(proven.dataset.filled).toBe('true');
    expect(proven.classList.contains('dp-freshness--fresh')).toBe(true);
  });

  it('stale banner admits the age (§6), only past the aging threshold', () => {
    expect(staleBanner('2026-06-06T11:40:00Z', NOW)).toBeNull(); // 20m → fresh, no banner
    const b = staleBanner('2026-06-04T12:00:00Z', NOW);          // 2d → stale
    expect(b.textContent).toContain('2d old');
    expect(relativeAge(0)).toBe('just now');
    expect(FRESHNESS_STATES).toEqual(['fresh', 'aging', 'stale', 'unproven']);
  });
});
