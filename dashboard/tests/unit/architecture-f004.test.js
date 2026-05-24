// F004 unit tests — architecture insights, project/fleet context,
// All Projects fleet view, missing project state, and responsive layout
// sanity. These verify the pure renderers introduced in F004 against
// the F004 fixture; DOM-side interactions land in the integration
// test sibling.
//
// Acceptance covered:
//   1. Summary and insight panels render from real architecture data.
//   2. Insights are evidence-backed and do not fabricate scores.
//   3. Project / fleet context is visible.
//   4. All Projects behavior is explicit and does not merge unrelated
//      repo maps into one canvas.
//   5. Missing project architecture is handled clearly.
//   6. Responsive behavior survives narrow widths without text overlap.

import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import {
  collectPlanTouchpoints,
  isMissingSelectedProject,
  normalizeEnvelope,
  renderArchitectureHTML,
  renderFleetArchitectureHTML,
  renderInsightsPanelHTML,
  renderMissingProjectStateHTML,
  renderProjectContextHTML,
  renderSummaryCardsHTML,
  resolveArchitectureEnvelope,
} from '../../lib/architecture-logic.js';
import fixture from '../fixtures/architecture-view-state-f004.json' with { type: 'json' };
import fixtureLegacy from '../fixtures/architecture-view-state.json' with { type: 'json' };

const env = normalizeEnvelope(fixture);
const envLegacy = normalizeEnvelope(fixtureLegacy);

describe('renderSummaryCardsHTML — F004 acceptance #1', () => {
  it('renders module/plan/schema/freshness/generated/fingerprint/files cards from real fields', () => {
    const html = renderSummaryCardsHTML(env);
    expect(html).toContain('data-summary="1"');
    expect(html).toContain('data-card="modules"');
    expect(html).toContain('data-card="plans"');
    expect(html).toContain('data-card="schemas"');
    expect(html).toContain('data-card="freshness"');
    expect(html).toContain('data-card="generated-at"');
    expect(html).toContain('data-card="fingerprint"');
    expect(html).toContain('data-card="files-count"');
    // Real counts from the fixture appear verbatim (no fabricated
    // percentages or risk scores).
    expect(html).toContain('102');
    expect(html).toContain('66');
    expect(html).toContain('7');
    expect(html).toContain('402');
    // Fingerprint truncated to 12 — the same convention the header uses.
    expect(html).toContain('abcdef012345');
    // Generated timestamp from the snapshot.
    expect(html).toContain('2026-05-24T19:00:00Z');
    // Freshness badge surfaces the state token from the snapshot.
    expect(html).toContain('STALE');
  });

  it('omits cards whose backing field is absent (no fabricated values)', () => {
    const sparse = normalizeEnvelope({
      lanes: [], nodes: [], edges: [], flows: [],
      freshness: { state: 'fresh' },
      insights: [],
    });
    const html = renderSummaryCardsHTML(sparse);
    expect(html).not.toContain('data-card="modules"');
    expect(html).not.toContain('data-card="plans"');
    expect(html).not.toContain('data-card="schemas"');
    expect(html).not.toContain('data-card="generated-at"');
    expect(html).not.toContain('data-card="fingerprint"');
    expect(html).not.toContain('data-card="files-count"');
    // Freshness card always renders so the state is at least visible.
    expect(html).toContain('data-card="freshness"');
    expect(html).toContain('FRESH');
  });

  it('returns empty string when given a null envelope', () => {
    expect(renderSummaryCardsHTML(null)).toBe('');
  });
});

describe('renderInsightsPanelHTML — F004 acceptance #2 (evidence-backed)', () => {
  it('renders the high-coupling section sourced from insights[].high-fan-out', () => {
    const html = renderInsightsPanelHTML(env);
    expect(html).toContain('data-insights-detail="1"');
    expect(html).toContain('data-insight="high-fan-out"');
    expect(html).toContain('High-coupling areas');
    expect(html).toContain('module:scripts/dontpanic_orchestrate/cli.py');
    expect(html).toContain('18');
    expect(html).toContain('imports');
    // The hint disclaims interpretation as a risk score.
    expect(html).toMatch(/qualitatively/);
  });

  it('renders the plans-touching section from real plan↔module edges', () => {
    const html = renderInsightsPanelHTML(env);
    expect(html).toContain('data-insight="plans-touching"');
    expect(html).toContain('plan:2026-05-24-002-arch-explorer');
    expect(html).toContain('Plans touching selected modules');
  });

  it('shows an honest "No data" tag when insight inputs are missing', () => {
    const sparse = normalizeEnvelope({
      lanes: [],
      nodes: [],
      edges: [],
      flows: [],
      freshness: { state: 'fresh' },
      insights: [],
    });
    const html = renderInsightsPanelHTML(sparse);
    // Both sections render the empty card with the No data tag, not a
    // fabricated score.
    expect(html).toContain('data-insight="high-fan-out"');
    expect(html).toContain('No data');
    expect(html).toContain('data-insight="plans-touching"');
    // No invented numbers in either empty card.
    expect(html).not.toMatch(/severity|risk score|score:/i);
  });

  it('does not introduce severity scores beyond available data (acceptance #2)', () => {
    const html = renderInsightsPanelHTML(env);
    // The insights panel never invents words like "severity" or
    // "score" — language stays qualitative.
    expect(html.toLowerCase()).not.toContain('severity');
    expect(html.toLowerCase()).not.toContain('risk score');
  });
});

describe('collectPlanTouchpoints', () => {
  it('extracts plan↔node touches and sorts by plan_id', () => {
    const touches = collectPlanTouchpoints(env);
    expect(touches.length).toBe(1);
    expect(touches[0].plan_id).toBe('plan:2026-05-24-002-arch-explorer');
    expect(touches[0].touches.length).toBe(1);
    expect(touches[0].touches[0].node_id).toContain('architecture_view_state.py');
  });

  it('returns [] for envelopes with no plan↔node edges', () => {
    expect(collectPlanTouchpoints(envLegacy).length).toBe(0);
    expect(collectPlanTouchpoints(null)).toEqual([]);
  });
});

describe('renderProjectContextHTML — F004 acceptance #3', () => {
  it('shows the project label, project_id, and source path', () => {
    const html = renderProjectContextHTML(env, 'project');
    expect(html).toContain('data-project-context="1"');
    expect(html).toContain('data-scope="project"');
    expect(html).toContain('DontPanic');
    expect(html).toContain('dontpanic');
    expect(html).toContain('docs/architecture/architecture.json');
    expect(html).toContain('Architecture data is scoped to this project');
  });

  it('renders "(none)" honestly when the snapshot has no project block', () => {
    const noProject = normalizeEnvelope({
      lanes: [], nodes: [], edges: [], flows: [],
      project: {},
      source_path: 'docs/architecture/architecture.json',
      freshness: { state: 'fresh' },
    });
    const html = renderProjectContextHTML(noProject, 'project');
    expect(html).toContain('(none)');
  });

  it('uses fleet-scoped narrative when scope === "fleet"', () => {
    const html = renderProjectContextHTML(env, 'fleet');
    expect(html).toContain('data-scope="fleet"');
    expect(html).toMatch(/single-repo state/);
  });
});

describe('renderFleetArchitectureHTML — F004 acceptance #4', () => {
  const projectA = {
    ...fixture,
    project: { name: 'projecta', display_name: 'Project A', label: 'Project A' },
  };
  const projectB = {
    ...fixture,
    project: { name: 'projectb', display_name: 'Project B', label: 'Project B' },
    freshness: { ...fixture.freshness, state: 'fresh' },
  };

  it('renders one project card per registered project (sorted by name)', () => {
    const html = renderFleetArchitectureHTML({
      byProject: { projecta: projectA, projectb: projectB },
      fleetSummary: { projects: [
        { name: 'projecta', display_name: 'Project A', active: true },
        { name: 'projectb', display_name: 'Project B', active: true },
      ] },
    });
    expect(html).toContain('data-fleet="1"');
    expect(html).toContain('Project A');
    expect(html).toContain('Project B');
    expect(html).toContain('data-fleet-card="projecta"');
    expect(html).toContain('data-fleet-card="projectb"');
    // Each card surfaces an "Open map" affordance.
    expect(html).toContain('data-arch-open-project="projecta"');
    expect(html).toContain('data-arch-open-project="projectb"');
    // Fleet view never embeds the SVG canvas — no merged graph.
    expect(html).not.toContain('<svg class="arch-canvas"');
    expect(html).not.toContain('data-explorer="1"');
  });

  it('renders an empty card with regen instructions for projects without an architecture artifact (acceptance #5)', () => {
    const html = renderFleetArchitectureHTML({
      byProject: { projecta: projectA },
      fleetSummary: { projects: [
        { name: 'projecta', display_name: 'Project A', active: true },
        { name: 'unbuilt', display_name: 'Unbuilt repo', active: true },
      ] },
    });
    expect(html).toContain('data-fleet-card="unbuilt"');
    expect(html).toContain('arch-fleet-card--empty');
    expect(html).toContain('No architecture snapshot for this project yet');
    expect(html).toContain('dontpanic architecture regen --with-html');
    expect(html).toContain('dontpanic dashboard build --project unbuilt');
  });

  it('handles a zero-project fleet without crashing', () => {
    const html = renderFleetArchitectureHTML({ byProject: {}, fleetSummary: { projects: [] } });
    expect(html).toContain('data-fleet-empty="1"');
    expect(html).toContain('No registered projects yet');
    expect(html).toContain('dontpanic projects add');
  });

  it('does NOT merge unrelated repo graphs (acceptance #4)', () => {
    // Both projects have nodes — if the fleet view merged them it
    // would render the combined graph. Instead we expect per-project
    // cards only.
    const html = renderFleetArchitectureHTML({
      byProject: { projecta: projectA, projectb: projectB },
      fleetSummary: null,
    });
    // The architecture canvas SVG and the explorer panel are markers
    // of the single-project populated render path.
    expect(html).not.toContain('arch-canvas');
    expect(html).not.toContain('arch-explorer-panel');
    // Two distinct cards instead of one merged graph.
    expect(html).toContain('data-fleet-card="projecta"');
    expect(html).toContain('data-fleet-card="projectb"');
  });
});

describe('renderArchitectureHTML — fleet routing (F004 wiring)', () => {
  it('routes to the fleet card grid when All Projects + byProject has entries', () => {
    const html = renderArchitectureHTML(fixture, {
      selectedProject: 'all',
      byProject: { projecta: fixture },
      fleetSummary: { projects: [{ name: 'projecta', display_name: 'Project A', active: true }] },
    });
    expect(html).toContain('data-fleet="1"');
    expect(html).toContain('arch-fleet-card');
    // Single-project explorer is suppressed when fleet view fires.
    expect(html).not.toContain('data-explorer="1"');
  });

  it('falls back to the single-project populated render when no per-project cache exists', () => {
    const html = renderArchitectureHTML(fixture, {
      selectedProject: 'all',
      byProject: {},
      fleetSummary: null,
    });
    // Single-project populated branch renders the explorer panel.
    expect(html).toContain('data-explorer="1"');
    expect(html).not.toContain('data-fleet="1"');
  });

  it('stays on the single-project explorer when selectedProject !== "all"', () => {
    const html = renderArchitectureHTML(fixture, {
      selectedProject: 'projecta',
      byProject: { projecta: fixture },
      fleetSummary: { projects: [{ name: 'projecta', display_name: 'Project A', active: true }] },
    });
    expect(html).toContain('data-explorer="1"');
    expect(html).not.toContain('data-fleet="1"');
  });
});

describe('Selected-project-missing state — F004 i1 finding #1 + #3', () => {
  it('resolveArchitectureEnvelope returns null when selected project is absent from byProject', () => {
    const out = resolveArchitectureEnvelope({
      selectedProject: 'unbuilt',
      single: fixture,
      byProject: { projecta: fixture },
    });
    expect(out).toBeNull();
  });

  it('resolveArchitectureEnvelope still falls back to single under "all" selection', () => {
    const out = resolveArchitectureEnvelope({
      selectedProject: 'all',
      single: fixture,
      byProject: {},
    });
    expect(out).toBe(fixture);
  });

  it('isMissingSelectedProject only fires when a concrete project is absent', () => {
    expect(isMissingSelectedProject({
      selectedProject: 'unbuilt',
      byProject: { projecta: fixture },
    })).toBe(true);
    expect(isMissingSelectedProject({
      selectedProject: 'projecta',
      byProject: { projecta: fixture },
    })).toBe(false);
    expect(isMissingSelectedProject({
      selectedProject: 'all',
      byProject: { projecta: fixture },
    })).toBe(false);
    // No byProject map at all — single-envelope mode, not missing.
    expect(isMissingSelectedProject({
      selectedProject: 'projecta',
      byProject: null,
    })).toBe(false);
  });

  it('renderMissingProjectStateHTML names the project and provides project-scoped regen steps', () => {
    const html = renderMissingProjectStateHTML('unbuilt', {
      projects: [{ name: 'unbuilt', display_name: 'Unbuilt repo', active: true }],
    });
    expect(html).toContain('data-empty-state="missing-project"');
    expect(html).toContain('data-missing-project="unbuilt"');
    expect(html).toContain('No architecture snapshot for Unbuilt repo');
    expect(html).toContain('not falling back to another project');
    expect(html).toContain('dontpanic architecture regen --with-html');
    expect(html).toContain('dontpanic dashboard build --project unbuilt');
  });

  it('renderArchitectureHTML renders missing-project card when byProject lacks the selected project', () => {
    const html = renderArchitectureHTML(fixture, {
      selectedProject: 'unbuilt',
      single: fixture, // would otherwise pollute the page with another repo's map
      byProject: { projecta: fixture },
      fleetSummary: {
        projects: [
          { name: 'projecta', display_name: 'Project A', active: true },
          { name: 'unbuilt', display_name: 'Unbuilt repo', active: true },
        ],
      },
    });
    expect(html).toContain('data-empty-state="missing-project"');
    expect(html).toContain('Unbuilt repo');
    // Crucially: no explorer canvas + no insights for the wrong project.
    expect(html).not.toContain('data-explorer="1"');
    expect(html).not.toContain('data-insights-detail="1"');
    expect(html).not.toContain('data-fleet="1"');
  });

  it('does NOT trigger missing-project when byProject is absent entirely', () => {
    // Single-envelope callers (legacy) still render through the single
    // path when there's no per-project map.
    const html = renderArchitectureHTML(fixture, {
      selectedProject: 'projecta',
      single: fixture,
      byProject: null,
    });
    expect(html).toContain('data-explorer="1"');
    expect(html).not.toContain('data-empty-state="missing-project"');
  });
});

describe('Responsive layout sanity — F004 acceptance #6', () => {
  // We can't measure render geometry inside jsdom, but we can verify
  // the markup carries the structural hooks the CSS uses to stack
  // panels at narrow widths and prevent text overlap.
  it('summary cards expose card containers that can stack via the responsive grid', () => {
    const html = renderSummaryCardsHTML(env);
    expect(html).toContain('class="arch-summary-grid"');
    expect(html).toContain('arch-summary-card');
  });

  it('insights detail grid wraps each section in a stackable container', () => {
    const html = renderInsightsPanelHTML(env);
    expect(html).toContain('class="arch-insights-detail-grid"');
    expect(html).toContain('class="arch-insight-section"');
  });

  it('fleet grid wraps each project card in a stackable container', () => {
    const html = renderFleetArchitectureHTML({
      byProject: { projecta: fixture },
      fleetSummary: { projects: [{ name: 'projecta', display_name: 'Project A', active: true }] },
    });
    expect(html).toContain('class="arch-fleet-grid"');
    expect(html).toContain('class="arch-fleet-card"');
  });

  it('renders the snapshot-freshness insight section (F004 i1 finding #2)', () => {
    const html = renderInsightsPanelHTML(env);
    expect(html).toContain('data-insight="snapshot-freshness"');
    expect(html).toContain('Snapshot freshness');
    // The fixture is stale with stored != current — both fingerprints
    // should appear truncated to 12 chars (no fabricated drift score).
    expect(html).toContain('abcdef012345');
    expect(html).toContain('1234567890ab');
    expect(html).toContain('STALE');
    // The hint must stay qualitative — no severity numbers.
    expect(html.toLowerCase()).not.toContain('severity');
  });

  it('renders the recently-changed-files section with No data when absent (F004 i1 finding #2)', () => {
    const html = renderInsightsPanelHTML(env);
    expect(html).toContain('data-insight="recently-changed"');
    expect(html).toContain('Recently changed files');
    // The default fixture does not carry insight:recently-changed, so
    // the section must render the No-data tag — never invent a count.
    expect(html).toContain('No data');
  });

  it('renders recently-changed rows when the view-state supplies an insight:recently-changed insight', () => {
    const withChanges = normalizeEnvelope({
      ...fixture,
      insights: [
        ...fixture.insights,
        {
          id: 'insight:recently-changed',
          title: 'Recently changed',
          kind: 'files',
          value: [
            { path: 'scripts/dontpanic_orchestrate/cli.py', change: 'modified' },
            { path: 'docs/architecture/architecture.json', change: 'modified' },
          ],
        },
      ],
    });
    const html = renderInsightsPanelHTML(withChanges);
    expect(html).toContain('data-insight="recently-changed"');
    expect(html).toContain('scripts/dontpanic_orchestrate/cli.py');
    expect(html).toContain('docs/architecture/architecture.json');
    expect(html).toContain('modified');
    expect(html).toContain('2 files');
  });

  it('CSS file declares the narrow-width stacking rules used by F004 panels', () => {
    // The responsive contract is in CSS; we verify the rule names are
    // present so a refactor cannot silently drop the breakpoint.
    const css = readFileSync(
      path.resolve(process.cwd(), 'pages/architecture/architecture.css'),
      'utf8',
    );
    expect(css).toMatch(/@media \(max-width: 900px\)/);
    expect(css).toMatch(/\.arch-fleet-grid \{[\s\S]*?grid-template-columns: 1fr;[\s\S]*?\}/);
    expect(css).toMatch(/\.arch-insights-detail-grid \{[\s\S]*?grid-template-columns: 1fr;[\s\S]*?\}/);
    expect(css).toContain('overflow-wrap: anywhere');
  });
});
