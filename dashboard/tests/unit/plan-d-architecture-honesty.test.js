// Plan D (2026-06-08-004) — architecture reconciler honesty surfaces.
//
// F001 coverage banner, F002 intent layer + diff badges, F003 baseline
// panel + architecture_missing warning + absent-state routing, F004
// confidence styling + legend. Field names mirror the producers:
// scripts/dontpanic_orchestrate/architecture_contract.py (coverage block,
// DIFF_TAXONOMY, node/edge evidence contract),
// scripts/dontpanic_orchestrate/architecture_baseline.py (EVIDENCE_TYPES,
// baseline coverage block, heuristic_import edges),
// scripts/dontpanic_orchestrate/architecture_intent.py (claims, diff
// entries), scripts/dontpanic_orchestrate/architecture_view_state.py
// (validation_warnings + the architecture_missing absence marker).

import { describe, it, expect } from 'vitest';
import {
  renderCoverageBannerHTML,
  renderBaselinePanelHTML,
  renderArchitectureMissingWarningHTML,
  renderIntentPanelHTML,
  renderArchitectureHTML,
  renderLegendHTML,
  layoutArchitectureGraph,
  renderArchitectureMapSVG,
  BASELINE_EVIDENCE_TYPE_ORDER,
} from '../../lib/architecture-logic.js';

// ─── Fixtures ────────────────────────────────────────────────────────

// Shape of architecture_contract.compute_coverage output.
const coverageBlock = (ceiling, over = {}) => ({
  contract_version: 'v0',
  confidence_ceiling: ceiling,
  extractors: [
    { extractor: 'python_import_crawler', evidence_kind: 'code', status: 'covered', node_count: 12 },
    { extractor: 'json_schema_scan', evidence_kind: 'code', status: 'not_found', node_count: 0 },
    { extractor: 'plan_index', evidence_kind: 'doc', status: 'covered', node_count: 4 },
    // Plan B appends the ADR extractor row via _apply_intent_layers.
    { extractor: 'adr_intent_extractor', evidence_kind: 'adr', status: 'covered', node_count: 2 },
  ],
  missing_extractors: ceiling === 'low'
    ? [
        { evidence_kind: 'swift', status: 'missing_extractor' },
        { evidence_kind: 'typescript', status: 'missing_extractor' },
      ]
    : [],
  note: 'Extractor coverage is the ceiling on the as-built model.',
  ...over,
});

// The 10 keys of architecture_baseline.EVIDENCE_TYPES (see
// scripts/dontpanic_orchestrate/architecture_baseline.py, EVIDENCE_TYPES).
// `runtime` is the reserved tier-3 entry — always not_found in C0.
const EVIDENCE_TYPES = [
  'filesystem',
  'code',
  'manifest',
  'build',
  'test',
  'config',
  'infra',
  'doc',
  'adr',
  'runtime',
];

const baselineBlock = (over = {}) => ({
  rollup: 'partial',
  per_language: {
    python: 'covered',
    swift: 'missing_extractor',
  },
  per_evidence_type: {
    filesystem: { status: 'covered', tier: 0, confidence_ceiling: 'medium' },
    code:       { status: 'partial', tier: 1, confidence_ceiling: 'low' },
    manifest:   { status: 'covered', tier: 0, confidence_ceiling: 'medium' },
    build:      { status: 'not_found', tier: 0, confidence_ceiling: 'medium' },
    test:       { status: 'covered', tier: 0, confidence_ceiling: 'medium' },
    config:     { status: 'covered', tier: 0, confidence_ceiling: 'medium' },
    infra:      { status: 'not_found', tier: 0, confidence_ceiling: 'medium' },
    doc:        { status: 'covered', tier: 0, confidence_ceiling: 'medium' },
    adr:        { status: 'covered', tier: 0, confidence_ceiling: 'medium' },
    runtime:    { status: 'not_found', tier: 3, reserved: true },
  },
  scan_truncated: false,
  notes: [
    'Dependency confidence is low. No Swift extractor installed.',
    'Language dependency extraction was not attempted for unrecognized file types.',
  ],
  unrecognized_extensions: ['.zig'],
  ...over,
});

// ─── F001 — coverage banner ──────────────────────────────────────────

describe('renderCoverageBannerHTML (F001)', () => {
  it('low ceiling renders the explicit incompleteness statement', () => {
    const html = renderCoverageBannerHTML(coverageBlock('low'));
    expect(html).toContain('data-testid="arch-coverage-banner"');
    expect(html).toContain('data-ceiling="low"');
    expect(html).toContain('This map is incomplete, not wrong');
    expect(html.toLowerCase()).toContain('incomplete');
    expect(html).toContain('confidence ceiling: low');
  });

  it('medium ceiling ALSO renders the incompleteness statement (recorded obligation — never regresses to neutral copy)', () => {
    const html = renderCoverageBannerHTML(coverageBlock('medium'));
    expect(html).toContain('data-ceiling="medium"');
    expect(html).toContain('This map is incomplete, not wrong');
    expect(html).toContain('confidence ceiling: medium');
  });

  it('high ceiling does NOT render the incompleteness statement', () => {
    const html = renderCoverageBannerHTML(coverageBlock('high'));
    expect(html).toContain('data-ceiling="high"');
    expect(html.toLowerCase()).not.toContain('incomplete');
    expect(html).not.toContain('data-testid="arch-coverage-incomplete"');
  });

  it('renders one row per extractor including the adr_intent_extractor row', () => {
    const html = renderCoverageBannerHTML(coverageBlock('low'));
    const rows = html.match(/data-testid="arch-coverage-extractor-row"/g) || [];
    expect(rows).toHaveLength(4);
    expect(html).toContain('adr_intent_extractor');
    expect(html).toContain('python_import_crawler');
    expect(html).toContain('json_schema_scan');
    expect(html).toContain('not_found');
    expect(html).toContain('covered');
  });

  it('renders every missing_extractors kind', () => {
    const html = renderCoverageBannerHTML(coverageBlock('low'));
    expect(html).toContain('swift');
    expect(html).toContain('typescript');
    const missing = html.match(/data-testid="arch-coverage-missing-kind"/g) || [];
    expect(missing).toHaveLength(2);
  });

  it('is driven only by the coverage block — null coverage renders nothing', () => {
    expect(renderCoverageBannerHTML(null)).toBe('');
    expect(renderCoverageBannerHTML(undefined)).toBe('');
  });
});

// ─── F003 — baseline panel ───────────────────────────────────────────

describe('renderBaselinePanelHTML (F003)', () => {
  it('mirrors the real EVIDENCE_TYPES key list from architecture_baseline.py', () => {
    // Drift guard: the JS ordering constant and this test's literal must
    // both match the producer's 10 keys.
    expect([...BASELINE_EVIDENCE_TYPE_ORDER]).toEqual(EVIDENCE_TYPES);
  });

  it('renders rollup verbatim with partial framed as incompleteness', () => {
    const html = renderBaselinePanelHTML({ baseline: baselineBlock() });
    expect(html).toContain('data-testid="arch-baseline-panel"');
    expect(html).toContain('data-rollup="partial"');
    expect(html).toContain('partial');
    expect(html).toContain('incomplete, not wrong');
  });

  it('frames limited as incompleteness; covered gets no incompleteness framing', () => {
    const limited = renderBaselinePanelHTML({ baseline: baselineBlock({ rollup: 'limited' }) });
    expect(limited).toContain('data-testid="arch-baseline-incomplete"');
    expect(limited).toContain('limited');
    const covered = renderBaselinePanelHTML({ baseline: baselineBlock({ rollup: 'covered' }) });
    expect(covered).toContain('covered');
    expect(covered).not.toContain('data-testid="arch-baseline-incomplete"');
  });

  it('renders one row per detected language only', () => {
    const html = renderBaselinePanelHTML({ baseline: baselineBlock() });
    const rows = html.match(/data-testid="arch-baseline-lang-row"/g) || [];
    expect(rows).toHaveLength(2);
    expect(html).toContain('data-language="python"');
    expect(html).toContain('data-language="swift"');
    expect(html).toContain('missing_extractor');
  });

  it('renders all 10 evidence-type rows including the reserved runtime tier-3 row', () => {
    const html = renderBaselinePanelHTML({ baseline: baselineBlock() });
    const rows = html.match(/data-testid="arch-baseline-evidence-row"/g) || [];
    expect(rows).toHaveLength(10);
    for (const key of EVIDENCE_TYPES) {
      expect(html).toContain(`data-evidence-type="${key}"`);
    }
    // The reserved runtime row renders as reserved/not_found, never omitted.
    expect(html).toMatch(/data-evidence-type="runtime"[\s\S]*?not_found[\s\S]*?\(reserved\)[\s\S]*?tier 3/);
  });

  it('shows a visible truncation warning when scan_truncated is true', () => {
    const html = renderBaselinePanelHTML({ baseline: baselineBlock({ scan_truncated: true }) });
    expect(html).toContain('data-testid="arch-baseline-truncated"');
    expect(html).toContain('Scan truncated');
  });

  it('shows NO truncation warning when scan_truncated is false', () => {
    const html = renderBaselinePanelHTML({ baseline: baselineBlock({ scan_truncated: false }) });
    expect(html).not.toContain('data-testid="arch-baseline-truncated"');
  });

  it('renders every notes string verbatim', () => {
    const html = renderBaselinePanelHTML({ baseline: baselineBlock() });
    expect(html).toContain('Dependency confidence is low. No Swift extractor installed.');
    expect(html).toContain(
      'Language dependency extraction was not attempted for unrecognized file types.',
    );
  });

  it('absent baseline renders an honest empty state and fabricates nothing', () => {
    const html = renderBaselinePanelHTML({ confidence_ceiling: 'high' });
    expect(html).toContain('data-testid="arch-baseline-panel"');
    expect(html).toContain('data-testid="arch-baseline-empty"');
    expect(html).not.toContain('data-testid="arch-baseline-evidence-row"');
    expect(html).not.toContain('data-testid="arch-baseline-lang-row"');
    const nullHtml = renderBaselinePanelHTML(null);
    expect(nullHtml).toContain('data-testid="arch-baseline-empty"');
  });
});

// ─── F003 — architecture_missing warning ─────────────────────────────

describe('renderArchitectureMissingWarningHTML (F003)', () => {
  it('renders the warning when validation_warnings carries code === "architecture_missing"', () => {
    // Assert the producer field BY NAME: the absence marker lives in the
    // envelope's `validation_warnings` list (architecture_view_state.py),
    // never inferred from a missing architecture block.
    const envelope = {
      validation_warnings: [
        {
          code: 'architecture_missing',
          message: 'architecture.json was not found. Run `dontpanic architecture regen --with-html` to generate it.',
        },
      ],
    };
    expect(Object.keys(envelope)).toContain('validation_warnings');
    const html = renderArchitectureMissingWarningHTML(envelope);
    expect(html).toContain('data-testid="arch-missing-warning"');
    expect(html).toContain('architecture.json was not found');
  });

  it('returns "" when no architecture_missing warning exists', () => {
    expect(renderArchitectureMissingWarningHTML({ validation_warnings: [] })).toBe('');
    expect(renderArchitectureMissingWarningHTML({
      validation_warnings: [{ code: 'other_warning', message: 'x' }],
    })).toBe('');
    expect(renderArchitectureMissingWarningHTML(null)).toBe('');
  });

  it('is keyed on the code field, not on an absent architecture block', () => {
    // An envelope with NO nodes/coverage but also no marker → no warning.
    expect(renderArchitectureMissingWarningHTML({})).toBe('');
  });
});

// ─── F002 — intent panel + diff badges ───────────────────────────────

describe('renderIntentPanelHTML (F002)', () => {
  const claims = [
    {
      id: 'ADR-001',
      title: 'Worktree isolation',
      status: 'accepted',
      source_path: 'docs/adr/ADR-001-worktree-isolation.md',
      source_kind: 'adr',
      evidence_basis: 'declared',
      references: ['worktree_registry.py'],
    },
  ];
  const liveDiff = [
    { taxonomy: 'aligned', claim_id: 'ADR-001', symbol: 'worktree_registry.py', detail: 'resolves to an as-built node.' },
    { taxonomy: 'documented_unimplemented', claim_id: 'ADR-001', symbol: 'ghost_module.py', detail: 'has no as-built evidence.' },
    { taxonomy: 'stale_adr', claim_id: 'ADR-002', symbol: null, detail: 'ADR-002 is superseded; its intent may no longer hold.' },
  ];

  it('labels claims as declared, never as as-built fact', () => {
    const html = renderIntentPanelHTML({ intent: { populated: true, claims }, diff: [] });
    expect(html).toContain('data-testid="arch-intent-panel"');
    expect(html.toLowerCase()).toContain('declared');
    expect(html).toContain('ADR-001');
    expect(html).toContain('docs/adr/ADR-001-worktree-isolation.md');
  });

  it('the three live taxonomy values get three DISTINCT classes', () => {
    const html = renderIntentPanelHTML({ intent: { populated: true, claims }, diff: liveDiff });
    expect(html).toContain('arch-diff-badge--aligned');
    expect(html).toContain('arch-diff-badge--documented_unimplemented');
    expect(html).toContain('arch-diff-badge--stale_adr');
    const badges = html.match(/data-testid="arch-diff-badge"/g) || [];
    expect(badges).toHaveLength(3);
  });

  it.each([
    'drift',
    'implemented_undocumented',
    'conflicting_dependency',
    'unknown_confidence',
    'totally_unknown_value',
  ])('reserved/unknown taxonomy "%s" gets the safe fallback class through the real badge renderer', (taxonomy) => {
    // Renderer-unit fallback proof (recorded obligation): each of the four
    // reserved DIFF_TAXONOMY values AND an unknown string go through the
    // real renderer — no crash, fallback class, raw taxonomy text, and
    // never a live-style class.
    const html = renderIntentPanelHTML({
      intent: { populated: true, claims },
      diff: [{ taxonomy, claim_id: 'ADR-009', symbol: 'x', detail: 'reserved entry' }],
    });
    expect(html).toContain('arch-diff-badge--reserved');
    expect(html).toContain(taxonomy);
    expect(html).not.toContain('arch-diff-badge--aligned');
    expect(html).not.toContain('arch-diff-badge--documented_unimplemented');
    expect(html).not.toContain('arch-diff-badge--stale_adr');
    expect(html).not.toContain(`arch-diff-badge--${taxonomy}`);
  });

  it('populated:false renders the honest empty state with zero badges', () => {
    const html = renderIntentPanelHTML({
      intent: { populated: false, claims: [] },
      // Even a stray diff entry must not render badges when unpopulated.
      diff: [{ taxonomy: 'aligned', claim_id: 'X', symbol: 'y', detail: '' }],
    });
    expect(html).toContain('data-testid="arch-intent-empty"');
    expect(html).toContain('No ADR claims found');
    expect(html).not.toContain('data-testid="arch-diff-badge"');
  });

  it('null layers renders the empty state without crashing', () => {
    const html = renderIntentPanelHTML(null);
    expect(html).toContain('data-testid="arch-intent-empty"');
    expect(html).toContain('No ADR claims found');
  });
});

// ─── F004 — confidence styling + legend ──────────────────────────────

describe('confidence styling survives layout into the SVG (F004)', () => {
  // Mirrors architecture_baseline.build_baseline_graph emission: a tier-0
  // filesystem node, a tier-1 source file, an unresolved heuristic target
  // (evidence_basis=unresolved), and a heuristic_import edge with
  // resolved=false / evidence_basis=unresolved.
  const envelope = {
    lanes: [{ id: 'lane:orchestrator-runtime', title: 'Runtime', kind: 'runtime', order: 1 }],
    nodes: [
      {
        id: 'fs:.', type: 'fs_dir', title: 'repo', lane_id: 'lane:orchestrator-runtime',
        source_kind: 'filesystem', evidence_basis: 'declared', source_path: '.',
      },
      {
        id: 'fs:App.swift', type: 'fs_source', title: 'App.swift', lane_id: 'lane:orchestrator-runtime',
        source_kind: 'code', evidence_basis: 'declared', source_path: 'App.swift',
      },
      {
        id: 'heuristic:swift:UIKit', type: 'heuristic_target', title: 'UIKit',
        lane_id: 'lane:orchestrator-runtime',
        source_kind: 'unknown', evidence_basis: 'unresolved',
      },
    ],
    edges: [
      {
        id: 'edge:himport:fs:App.swift->heuristic:swift:UIKit',
        type: 'heuristic_import',
        from: 'fs:App.swift',
        to: 'heuristic:swift:UIKit',
        source_kind: 'code',
        evidence_basis: 'unresolved',
        resolved: false,
      },
    ],
  };

  it('evidence fields survive layoutArchitectureGraph', () => {
    const layout = layoutArchitectureGraph(envelope);
    const fsNode = layout.nodesById.get('fs:.');
    expect(fsNode.source_kind).toBe('filesystem');
    const target = layout.nodesById.get('heuristic:swift:UIKit');
    expect(target.evidence_basis).toBe('unresolved');
    const edge = layout.edges.find((e) => e.type === 'heuristic_import');
    expect(edge).toBeDefined();
    expect(edge.missing).toBe(false);
    expect(edge.resolved).toBe(false);
    expect(edge.evidence_basis).toBe('unresolved');
  });

  it('SVG carries arch-edge--heuristic + arch-edge--unresolved on the heuristic edge', () => {
    const svg = renderArchitectureMapSVG(layoutArchitectureGraph(envelope));
    expect(svg).toContain('data-edge-id="edge:himport:fs:App.swift-&gt;heuristic:swift:UIKit"');
    expect(svg).toMatch(/class="arch-edge arch-edge--heuristic arch-edge--unresolved"/);
    // Base class is still present (no existing rendering removed).
    expect(svg).toContain('arch-edge');
  });

  it('SVG carries arch-node--unresolved and arch-node--filesystem on the right nodes', () => {
    const svg = renderArchitectureMapSVG(layoutArchitectureGraph(envelope));
    expect(svg).toMatch(/class="arch-node arch-node--unresolved"[^>]*data-node-id="heuristic:swift:UIKit"/);
    expect(svg).toMatch(/class="arch-node arch-node--filesystem"[^>]*data-node-id="fs:\."/);
    // The plain code node keeps the unmodified class.
    expect(svg).toMatch(/class="arch-node"[^>]*data-node-id="fs:App\.swift"/);
  });

  it('legend names all three evidence levels with data-legend-evidence hooks', () => {
    const html = renderLegendHTML(envelope);
    expect(html).toContain('data-legend-evidence="heuristic"');
    expect(html).toContain('Heuristic import (low confidence)');
    expect(html).toContain('data-legend-evidence="unresolved"');
    expect(html).toContain('Unresolved target');
    expect(html).toContain('data-legend-evidence="filesystem"');
    expect(html).toContain('Filesystem-only (tier 0)');
  });
});

// ─── F003 — absent-state routing ─────────────────────────────────────

describe('renderArchitectureHTML routing for absent state (F003)', () => {
  const absentEnvelope = {
    schema_version: '1.0',
    project: { name: 'demo', display_name: 'Demo' },
    generated_at: '2026-06-10T00:00:00Z',
    source_path: 'docs/architecture/architecture.json',
    freshness: { state: 'absent', message: 'architecture.json was not found.' },
    lanes: [{ id: 'lane:orchestrator-runtime', title: 'Runtime', kind: 'runtime', order: 1 }],
    nodes: [
      {
        id: 'fs:.', type: 'fs_dir', title: 'repo', lane_id: 'lane:orchestrator-runtime',
        source_kind: 'filesystem', evidence_basis: 'declared', source_path: '.',
      },
    ],
    edges: [],
    clusters: [],
    levels: [],
    flows: [],
    steps: [],
    filters: {},
    insights: [],
    coverage: { ...coverageBlock('low'), baseline: baselineBlock() },
    layers: {
      as_built: { node_count: 1, edge_count: 0, is_current: true },
      intent: { claims: [], populated: false },
      diff: [],
    },
    validation_warnings: [
      { code: 'architecture_missing', message: 'architecture.json was not found.' },
    ],
  };

  it('absent state WITH baseline nodes/coverage renders the populated surface', () => {
    const html = renderArchitectureHTML(absentEnvelope);
    expect(html).toContain('data-testid="arch-coverage-banner"');
    expect(html).toContain('data-testid="arch-baseline-panel"');
    expect(html).toContain('data-testid="arch-missing-warning"');
    expect(html).not.toContain('data-empty-state="missing"');
  });

  it('the missing-warning sits ABOVE the baseline panel in the composition', () => {
    const html = renderArchitectureHTML(absentEnvelope);
    const warningIdx = html.indexOf('data-testid="arch-missing-warning"');
    const panelIdx = html.indexOf('data-testid="arch-baseline-panel"');
    expect(warningIdx).toBeGreaterThan(-1);
    expect(panelIdx).toBeGreaterThan(-1);
    expect(warningIdx).toBeLessThan(panelIdx);
  });

  it('null envelope still renders the missing state', () => {
    const html = renderArchitectureHTML(null);
    expect(html).toContain('data-empty-state="missing"');
    expect(html).not.toContain('data-testid="arch-coverage-banner"');
  });

  it('truly empty absent payload (no nodes, no baseline) keeps the missing state', () => {
    const html = renderArchitectureHTML({
      ...absentEnvelope,
      nodes: [],
      coverage: coverageBlock('low'), // no baseline key
      validation_warnings: [],
    });
    expect(html).toContain('data-empty-state="missing"');
  });
});
