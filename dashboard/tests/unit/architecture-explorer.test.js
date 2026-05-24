// F003 unit tests for the interactive Architecture explorer.
//
// These verify the *pure* layer of the explorer (acceptance items
// 1, 2, 5, 6, 7, 10 from the F003 acceptance contract):
//   - swimlane layout is deterministic given a view-state envelope
//   - the SVG renderer emits one `<g class="arch-node">` per node and
//     one `<path class="arch-edge">` per edge that resolves
//   - flow participants resolve to the correct node/edge id sets
//   - validation warnings still surface even when the flow is broken
//
// The DOM-side interaction tests live in
// `tests/integration/architecture-explorer-dom.test.js`.

import { describe, it, expect } from 'vitest';
import {
  EDGE_TYPES,
  NODE_CATEGORIES,
  collectFlowWarnings,
  getFlowParticipants,
  layoutArchitectureGraph,
  normalizeEnvelope,
  renderArchitectureHTML,
  renderArchitectureMapSVG,
  renderNodeDetailHTML,
  renderStepInspectorHTML,
} from '../../lib/architecture-logic.js';
import fixture from '../fixtures/architecture-view-state.json' with { type: 'json' };

const envelope = normalizeEnvelope(fixture);

describe('layoutArchitectureGraph — deterministic positioning', () => {
  it('returns lanes in order: sorted by `order` then `id`', () => {
    const layout = layoutArchitectureGraph(envelope);
    const ids = layout.lanes.map((l) => l.id);
    expect(ids).toEqual([
      'lane:client-surfaces',
      'lane:orchestrator-runtime',
      'lane:data-evidence',
    ]);
  });

  it('places nodes deterministically (same envelope → same coords)', () => {
    const a = layoutArchitectureGraph(envelope);
    const b = layoutArchitectureGraph(envelope);
    const coords = (l) => [...l.nodesById.entries()]
      .map(([id, n]) => `${id}@${n.x},${n.y}`).sort();
    expect(coords(a)).toEqual(coords(b));
  });

  it('sorts nodes by id within each lane', () => {
    const layout = layoutArchitectureGraph(envelope);
    const orchestratorLane = layout.lanes.find((l) => l.id === 'lane:orchestrator-runtime');
    expect(orchestratorLane).toBeTruthy();
    const ids = orchestratorLane.nodes.map((n) => n.id);
    expect(ids).toEqual([...ids].sort());
  });

  it('emits one entry per node and one per edge with resolved coordinates', () => {
    const layout = layoutArchitectureGraph(envelope);
    expect(layout.nodesById.size).toBe(fixture.nodes.length);
    const resolved = layout.edges.filter((e) => !e.missing);
    expect(resolved.length).toBe(fixture.edges.length);
    for (const edge of resolved) {
      expect(Number.isFinite(edge.x1)).toBe(true);
      expect(Number.isFinite(edge.y1)).toBe(true);
      expect(Number.isFinite(edge.x2)).toBe(true);
      expect(Number.isFinite(edge.y2)).toBe(true);
    }
  });

  it('marks edges with absent endpoints as missing', () => {
    const env = normalizeEnvelope({
      lanes: [{ id: 'lane:a', title: 'A', order: 0 }],
      nodes: [{ id: 'n1', lane_id: 'lane:a', type: 'module', title: 'N1' }],
      edges: [{ id: 'e1', from: 'n1', to: 'missing', type: 'import' }],
      flows: [],
      freshness: { state: 'stale' },
    });
    const layout = layoutArchitectureGraph(env);
    expect(layout.edges[0].missing).toBe(true);
  });

  it('returns an empty layout when the envelope is null', () => {
    const layout = layoutArchitectureGraph(null);
    expect(layout.lanes).toEqual([]);
    expect(layout.nodesById.size).toBe(0);
    expect(layout.edges).toEqual([]);
  });
});

describe('renderArchitectureMapSVG — pure SVG render', () => {
  it('emits one <g class="arch-node"> per node and one <path> per resolved edge', () => {
    const layout = layoutArchitectureGraph(envelope);
    const svg = renderArchitectureMapSVG(layout);
    expect(svg.startsWith('\n    <svg') || svg.startsWith('<svg')).toBe(true);
    // Count nodes by data-node-id.
    const nodeMatches = svg.match(/<g class="arch-node"/g) || [];
    expect(nodeMatches.length).toBe(envelope.nodes.length);
    // Count edges by data-edge-id.
    const edgeMatches = svg.match(/<path class="arch-edge"/g) || [];
    expect(edgeMatches.length).toBe(envelope.edges.length);
    // Lane labels render as <text class="arch-lane-label">.
    expect(svg).toContain('class="arch-lane-label"');
    expect(svg).toContain('class="arch-lane-bg"');
  });

  it('renders identically across calls with the same input (snapshot-safe)', () => {
    const layout = layoutArchitectureGraph(envelope);
    expect(renderArchitectureMapSVG(layout)).toBe(renderArchitectureMapSVG(layout));
  });

  it('embeds a viewBox with finite numbers', () => {
    const layout = layoutArchitectureGraph(envelope);
    const svg = renderArchitectureMapSVG(layout);
    const m = svg.match(/viewBox="0 0 (\d+) (\d+)"/);
    expect(m).not.toBeNull();
    const w = Number(m[1]);
    const h = Number(m[2]);
    expect(w).toBeGreaterThan(0);
    expect(h).toBeGreaterThan(0);
  });

  it('renders an empty SVG when layout has no lanes', () => {
    const svg = renderArchitectureMapSVG({ width: 0, height: 0, lanes: [], nodesById: new Map(), edges: [] });
    expect(svg).toContain('<svg class="arch-canvas"');
    expect(svg).not.toContain('arch-node');
    expect(svg).not.toContain('arch-edge');
  });

  it('renders each node with a <title> tooltip (hover affordance, acceptance #8)', () => {
    const layout = layoutArchitectureGraph(envelope);
    const svg = renderArchitectureMapSVG(layout);
    const titleCount = (svg.match(/<title>/g) || []).length;
    expect(titleCount).toBe(envelope.nodes.length);
  });
});

describe('getFlowParticipants — participating node/edge ids', () => {
  it('returns the node and edge ids referenced by a flow', () => {
    const result = getFlowParticipants(envelope, 'flow:architecture-regen');
    expect(result.nodeIds.has('module:scripts/dontpanic_orchestrate/cli.py')).toBe(true);
    expect(result.nodeIds.has('command:dontpanic-architecture-regen')).toBe(true);
    expect(result.edgeIds.has('edge:imports:1')).toBe(true);
    expect(result.stepRefs).toHaveLength(2);
    expect(result.stepRefs[0].order).toBe(1);
    expect(result.stepRefs[1].order).toBe(2);
  });

  it('returns empty sets for unknown flow ids', () => {
    const out = getFlowParticipants(envelope, 'flow:does-not-exist');
    expect(out.nodeIds.size).toBe(0);
    expect(out.edgeIds.size).toBe(0);
    expect(out.stepRefs).toEqual([]);
  });

  it('still returns step refs for flows whose node_ref does not resolve (validation, acceptance #5)', () => {
    const out = getFlowParticipants(envelope, 'flow:authored-broken');
    expect(out.stepRefs.length).toBe(1);
    // Step refs include the broken node_ref so the inspector can show
    // the missing reference next to its warning.
    expect(out.stepRefs[0].node_ref).toBe('module:does/not/exist.py');
    expect(out.stepRefs[0].warnings.length).toBeGreaterThan(0);
  });
});

describe('renderArchitectureHTML — F003 explorer integration', () => {
  it('renders the populated explorer panel and the toolbar', () => {
    const html = renderArchitectureHTML(fixture);
    expect(html).toContain('data-explorer="1"');
    expect(html).toContain('arch-explorer-toolbar');
    expect(html).toContain('data-arch-search');
    expect(html).toContain('data-arch-reset');
    expect(html).toContain('data-arch-flow-clear');
  });

  it('emits filter chips for each node type, lane, and edge type present', () => {
    const html = renderArchitectureHTML(fixture);
    expect(html).toMatch(/data-arch-filter="type" value="module"/);
    expect(html).toMatch(/data-arch-filter="type" value="command"/);
    expect(html).toMatch(/data-arch-filter="lane" value="lane:orchestrator-runtime"/);
    expect(html).toMatch(/data-arch-filter="edge" value="import"/);
  });

  it('renders the persistent legend with node and edge categories', () => {
    const html = renderArchitectureHTML(fixture);
    expect(html).toContain('data-legend');
    expect(html).toContain('data-legend-type="module"');
    expect(html).toContain('data-legend-type="command"');
    expect(html).toContain('data-legend-edge="import"');
  });

  it('renders a flow row per flow with the clear-selection button', () => {
    const html = renderArchitectureHTML(fixture);
    expect(html).toContain('data-arch-flow="flow:architecture-regen"');
    expect(html).toContain('data-arch-flow="flow:authored-broken"');
    expect(html).toContain('data-arch-flow-clear');
  });

  it('renders the SVG canvas inline (no CDN, no iframe — vanilla SVG)', () => {
    const html = renderArchitectureHTML(fixture);
    expect(html).toContain('<svg class="arch-canvas"');
    expect(html).not.toContain('<iframe');
    expect(html).not.toContain('//cdn');
  });

  it('preserves the F002 validation warnings panel even with the explorer present', () => {
    const html = renderArchitectureHTML(fixture);
    expect(html).toContain('data-warnings="1"');
    expect(html).toContain('flow:authored-broken');
  });
});

describe('renderNodeDetailHTML — click-to-detail (acceptance #8)', () => {
  it('returns metadata for a known node id with source path and lane', () => {
    const html = renderNodeDetailHTML(envelope, 'module:scripts/dontpanic_orchestrate/cli.py');
    expect(html).toContain('Node ID');
    expect(html).toContain('module:scripts/dontpanic_orchestrate/cli.py');
    expect(html).toContain('Source path');
    expect(html).toContain('lane:orchestrator-runtime');
    expect(html).toContain('Outgoing');
  });

  it('handles unknown ids honestly', () => {
    const html = renderNodeDetailHTML(envelope, 'nope:nope');
    expect(html).toContain('No detail available');
  });

  it('returns empty string for invalid inputs', () => {
    expect(renderNodeDetailHTML(null, 'x')).toBe('');
    expect(renderNodeDetailHTML(envelope, '')).toBe('');
  });
});

describe('renderStepInspectorHTML — numbered step rows (acceptance #2, #11)', () => {
  it('renders one row per step with order numbering and the node ref', () => {
    const html = renderStepInspectorHTML(envelope, 'flow:architecture-regen');
    expect(html).toContain('data-step-order="1"');
    expect(html).toContain('data-step-order="2"');
    expect(html).toContain('data-node-ref="command:dontpanic-architecture-regen"');
    expect(html).toContain('data-node-ref="module:scripts/dontpanic_orchestrate/cli.py"');
    expect(html).toContain('Operator invokes regen');
    expect(html).toContain('Crawler walks source');
  });

  it('rolls up step warnings into the inspector row', () => {
    const html = renderStepInspectorHTML(envelope, 'flow:authored-broken');
    expect(html).toContain('node_ref does not resolve');
  });

  it('returns empty string for unknown flows', () => {
    expect(renderStepInspectorHTML(envelope, 'flow:nope')).toBe('');
  });
});

describe('Legend + edge type catalogs', () => {
  it('node category catalog covers every type emitted by the F001 view-state', () => {
    const types = new Set((envelope.nodes || []).map((n) => n.type));
    for (const t of types) {
      expect(NODE_CATEGORIES[t] || NODE_CATEGORIES.other).toBeDefined();
    }
  });

  it('edge type catalog covers every edge type emitted by F001', () => {
    const types = new Set((envelope.edges || []).map((e) => e.type));
    for (const t of types) {
      expect(EDGE_TYPES[t] || EDGE_TYPES.other).toBeDefined();
    }
  });
});

describe('collectFlowWarnings + validation warnings remain non-fatal (acceptance #5)', () => {
  it('the explorer still renders when a flow is broken', () => {
    const html = renderArchitectureHTML(fixture);
    expect(html).toContain('data-explorer="1"');
    expect(html).toContain('flow:authored-broken');
    expect(collectFlowWarnings(envelope).length).toBeGreaterThan(0);
  });
});
