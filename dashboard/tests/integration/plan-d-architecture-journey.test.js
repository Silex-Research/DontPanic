// Plan D (2026-06-08-004) F006 — REAL-SHELL journeys for the architecture
// honesty surfaces. Boots createJarvis().init() on PRODUCER-GENERATED
// view-state fixtures (written by the real build_view_state via
// scripts/dontpanic_orchestrate/tests/test_plan_d_journey_fixtures_f006.py,
// whose contract test regenerates them so drift FAILS instead of pre-baking
// shapes), switches to the Architecture tab, and asserts the rendered DOM by
// selector/data-testid — never raw JSON.
//
// Journey 1: architecture.json PRESENT (+ADR) — banner, baseline panel at row
//            detail, F004 legend + all three confidence hooks, declared
//            intent claim, diff badges, incompleteness wording, no JSON leak.
// Journey 2: architecture.json ABSENT — baseline graph + panel render instead
//            of an empty surface, banner from the absent-branch coverage
//            block, architecture_missing warning, legend + hooks, no leak.
// Journey 3: NO ADRs — honest "No ADR claims found" empty state, zero
//            fabricated claims, zero diff badges.

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { setupDOM, setupChartMock, setupFetchMock } from '../helpers/setup.js';
import present from '../fixtures/plan-d-view-state-present.json' with { type: 'json' };
import absent from '../fixtures/plan-d-view-state-absent.json' with { type: 'json' };
import noadrs from '../fixtures/plan-d-view-state-noadrs.json' with { type: 'json' };

async function boot(viewState) {
  setupDOM();
  setupChartMock();
  // core.js loadState fetches `state/architecture-view-state.json`; the mock
  // keys on the filename minus `.json`.
  setupFetchMock({ 'architecture-view-state': viewState });
  const { createJarvis } = await import('../../core.js');
  const J = createJarvis();
  globalThis.Jarvis = J; // the page IIFE registers into the real shell
  await import('../../pages/architecture/architecture.js' + `?j=${Math.random().toString(36).slice(2)}`);
  await J.init();
  J.switchTo('architecture');
  return J.getPageEl('architecture');
}

const NO_RAW_JSON = (html) => {
  expect(html).not.toContain('"taxonomy"');
  expect(html).not.toContain('"per_evidence_type"');
  expect(html).not.toContain('[{');
};

describe('Plan D F006 — architecture honesty journeys through the real shell', () => {
  beforeEach(() => { vi.useFakeTimers(); });
  afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); delete globalThis.Jarvis; });

  it('journey 1 (present): coverage banner + baseline rows + legend/hooks + intent + diff badges, no raw JSON', async () => {
    const el = await boot(present);
    const html = el.innerHTML;

    // — coverage banner, driven by the producer's coverage block —
    const banner = el.querySelector('[data-testid="arch-coverage-banner"]');
    expect(banner).toBeTruthy();
    expect(banner.dataset.ceiling).toBe(present.coverage.confidence_ceiling);
    // the fixture repo carries Swift without an extractor → low/medium
    // ceiling → the incompleteness statement is on the surface, unsoftened.
    expect(['low', 'medium']).toContain(present.coverage.confidence_ceiling);
    expect(banner.textContent).toContain('This map is incomplete, not wrong');
    // every extractor row, including the ADR intent extractor
    for (const ex of present.coverage.extractors) {
      expect(banner.querySelector(`[data-extractor="${ex.extractor}"]`)).toBeTruthy();
    }
    expect(banner.textContent).toContain('adr_intent_extractor');
    for (const m of present.coverage.missing_extractors) {
      expect(banner.textContent).toContain(m.evidence_kind);
    }

    // — baseline panel AT ROW DETAIL, driven by the fixture's actual block —
    const panel = el.querySelector('[data-testid="arch-baseline-panel"]');
    expect(panel).toBeTruthy();
    const baseline = present.coverage.baseline;
    // per-language rows with their statuses
    const langEntries = Object.entries(baseline.per_language);
    expect(langEntries.length).toBeGreaterThan(0);
    for (const [lang, status] of langEntries) {
      const row = panel.querySelector(`[data-testid="arch-baseline-lang-row"][data-language="${lang}"]`);
      expect(row).toBeTruthy();
      expect(row.textContent).toContain(status);
    }
    // the COMPLETE per-evidence-type table: one row per producer entry,
    // including the reserved runtime tier-3 row.
    const typeKeys = Object.keys(baseline.per_evidence_type);
    const typeRows = panel.querySelectorAll('[data-testid="arch-baseline-evidence-row"]');
    expect(typeRows).toHaveLength(typeKeys.length);
    expect(typeKeys.length).toBe(10); // EVIDENCE_TYPES (architecture_baseline.py)
    for (const key of typeKeys) {
      const row = panel.querySelector(`[data-testid="arch-baseline-evidence-row"][data-evidence-type="${key}"]`);
      expect(row).toBeTruthy();
      expect(row.textContent).toContain(baseline.per_evidence_type[key].status);
    }
    const runtimeRow = panel.querySelector('[data-evidence-type="runtime"]');
    expect(runtimeRow.textContent).toContain('not_found');
    expect(runtimeRow.textContent).toContain('(reserved)');
    // honest truncation rendering for the fixture's ACTUAL flag
    const truncated = panel.querySelector('[data-testid="arch-baseline-truncated"]');
    if (baseline.scan_truncated) expect(truncated).toBeTruthy();
    else expect(truncated).toBeFalsy();
    // every producer note rendered verbatim
    expect(baseline.notes.length).toBeGreaterThan(0);
    for (const note of baseline.notes) {
      expect(panel.textContent).toContain(note);
    }

    // — F004 legend + confidence hooks, BY SELECTOR (all three; recorded
    //   implementation obligation) —
    expect(el.querySelector('[data-legend-evidence="heuristic"]')).toBeTruthy();
    expect(el.querySelector('[data-legend-evidence="unresolved"]')).toBeTruthy();
    expect(el.querySelector('[data-legend-evidence="filesystem"]')).toBeTruthy();
    expect(el.querySelector('svg .arch-edge--heuristic')).toBeTruthy();
    expect(el.querySelector('svg .arch-edge--unresolved')).toBeTruthy();
    expect(el.querySelector('svg .arch-node--unresolved')).toBeTruthy();
    expect(el.querySelector('svg .arch-node--filesystem')).toBeTruthy();

    // — declared intent + diff badges —
    const claims = el.querySelectorAll('[data-testid="arch-intent-claim"]');
    expect(claims.length).toBeGreaterThan(0);
    expect(el.querySelector('[data-testid="arch-intent-panel"]').textContent.toLowerCase())
      .toContain('declared');
    const badges = el.querySelectorAll('[data-testid="arch-diff-badge"]');
    expect(badges.length).toBe(present.layers.diff.length);
    expect(badges.length).toBeGreaterThan(0);
    expect(el.querySelector('.arch-diff-badge--aligned')).toBeTruthy();
    expect(el.querySelector('.arch-diff-badge--documented_unimplemented')).toBeTruthy();

    // — no raw JSON leaks into the rendered surface —
    NO_RAW_JSON(html);
  });

  it('journey 2 (absent): baseline surface renders instead of an empty card, with the architecture_missing warning', async () => {
    const el = await boot(absent);
    const html = el.innerHTML;

    // the producer marks absence in validation_warnings BY CODE — the
    // fixture really carries it, and the page renders it visibly.
    expect(absent.freshness.state).toBe('absent');
    expect(absent.validation_warnings.some((w) => w.code === 'architecture_missing')).toBe(true);
    expect(el.querySelector('[data-testid="arch-missing-warning"]')).toBeTruthy();

    // NOT the empty surface: the baseline graph + panel + banner render.
    expect(el.querySelector('[data-empty-state="missing"]')).toBeFalsy();
    expect(el.querySelector('[data-testid="arch-baseline-panel"]')).toBeTruthy();
    expect(el.querySelectorAll('[data-testid="arch-baseline-evidence-row"]')).toHaveLength(
      Object.keys(absent.coverage.baseline.per_evidence_type).length,
    );
    expect(el.querySelector('svg .arch-node')).toBeTruthy(); // the baseline graph is on the canvas

    // coverage banner from the absent-branch coverage block, with the
    // unsoftened incompleteness statement (low/medium ceiling).
    const banner = el.querySelector('[data-testid="arch-coverage-banner"]');
    expect(banner).toBeTruthy();
    expect(banner.dataset.ceiling).toBe(absent.coverage.confidence_ceiling);
    expect(['low', 'medium']).toContain(absent.coverage.confidence_ceiling);
    expect(banner.textContent).toContain('This map is incomplete, not wrong');

    // F004 legend + confidence hooks survive the absent route too.
    expect(el.querySelector('[data-legend-evidence="heuristic"]')).toBeTruthy();
    expect(el.querySelector('[data-legend-evidence="unresolved"]')).toBeTruthy();
    expect(el.querySelector('[data-legend-evidence="filesystem"]')).toBeTruthy();
    expect(el.querySelector('svg .arch-edge--heuristic')).toBeTruthy();
    expect(el.querySelector('svg .arch-node--filesystem')).toBeTruthy();

    NO_RAW_JSON(html);
  });

  it('journey 3 (no ADRs): honest empty intent state, zero fabricated claims, zero diff badges', async () => {
    const el = await boot(noadrs);

    expect(noadrs.layers.intent.populated).toBe(false);
    const empty = el.querySelector('[data-testid="arch-intent-empty"]');
    expect(empty).toBeTruthy();
    expect(empty.textContent).toContain('No ADR claims found');
    expect(el.querySelectorAll('[data-testid="arch-intent-claim"]')).toHaveLength(0);
    expect(el.querySelectorAll('[data-testid="arch-diff-badge"]')).toHaveLength(0);

    NO_RAW_JSON(el.innerHTML);
  });
});
