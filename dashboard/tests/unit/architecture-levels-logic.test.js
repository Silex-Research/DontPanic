// Plan 2026-06-06-007 F002 — pure logic for the interactive component map:
// dependency-walk highlight + directory breadcrumb / cluster drill-down.

import { describe, it, expect } from 'vitest';
import {
  normalizeEnvelope,
  computeDependencyHighlight,
  buildBreadcrumbPath,
  getClusterChildren,
  getClusterMembers,
  rootClusterId,
  renderClusterBarHTML,
} from '../../lib/architecture-logic.js';

// A → B → C linear chain plus an unrelated node D, across a directory tree:
//   pkg/a.js, pkg/b.js, pkg/sub/c.js, other/d.js
function envelope() {
  return normalizeEnvelope({
    schema_version: '1.0',
    freshness: { state: 'fresh' },
    lanes: [{ id: 'lane:x', title: 'X', order: 0 }],
    nodes: [
      { id: 'module:pkg/a.js', type: 'module', lane_id: 'lane:x', title: 'a', source_path: 'pkg/a.js' },
      { id: 'module:pkg/b.js', type: 'module', lane_id: 'lane:x', title: 'b', source_path: 'pkg/b.js' },
      { id: 'module:pkg/sub/c.js', type: 'module', lane_id: 'lane:x', title: 'c', source_path: 'pkg/sub/c.js' },
      { id: 'module:other/d.js', type: 'module', lane_id: 'lane:x', title: 'd', source_path: 'other/d.js' },
    ],
    edges: [
      { id: 'e:ab', type: 'import', from: 'module:pkg/a.js', to: 'module:pkg/b.js' },
      { id: 'e:bc', type: 'import', from: 'module:pkg/b.js', to: 'module:pkg/sub/c.js' },
    ],
    clusters: [
      { id: 'cluster:', key: '', title: 'System', level: 0, parent_id: null, node_ids: [], child_cluster_ids: ['cluster:other', 'cluster:pkg'] },
      { id: 'cluster:other', key: 'other', title: 'other', level: 1, parent_id: 'cluster:', node_ids: ['module:other/d.js'], child_cluster_ids: [] },
      { id: 'cluster:pkg', key: 'pkg', title: 'pkg', level: 1, parent_id: 'cluster:', node_ids: ['module:pkg/a.js', 'module:pkg/b.js'], child_cluster_ids: ['cluster:pkg/sub'] },
      { id: 'cluster:pkg/sub', key: 'pkg/sub', title: 'sub', level: 2, parent_id: 'cluster:pkg', node_ids: ['module:pkg/sub/c.js'], child_cluster_ids: [] },
    ],
    levels: [
      { id: 'level:0', level: 0, title: 'L0', cluster_ids: ['cluster:'] },
      { id: 'level:1', level: 1, title: 'L1', cluster_ids: ['cluster:other', 'cluster:pkg'] },
      { id: 'level:2', level: 2, title: 'L2', cluster_ids: ['cluster:pkg/sub'] },
    ],
  });
}

describe('normalizeEnvelope carries clusters + levels', () => {
  it('preserves the graph model the component map drills through', () => {
    const env = envelope();
    expect(env.clusters.length).toBe(4);
    expect(env.levels.length).toBe(3);
  });

  it('defaults missing clusters/levels to empty arrays (back-compat)', () => {
    const env = normalizeEnvelope({ lanes: [], nodes: [], freshness: { state: 'fresh' } });
    expect(env.clusters).toEqual([]);
    expect(env.levels).toEqual([]);
  });
});

describe('computeDependencyHighlight', () => {
  it('walks downstream transitively from the focus node', () => {
    const r = computeDependencyHighlight(envelope(), 'module:pkg/a.js');
    expect(r.focus).toBe('module:pkg/a.js');
    expect([...r.downstream].sort()).toEqual(['module:pkg/b.js', 'module:pkg/sub/c.js']);
    expect(r.upstream.size).toBe(0);
  });

  it('walks upstream transitively from the focus node', () => {
    const r = computeDependencyHighlight(envelope(), 'module:pkg/sub/c.js');
    expect([...r.upstream].sort()).toEqual(['module:pkg/a.js', 'module:pkg/b.js']);
    expect(r.downstream.size).toBe(0);
  });

  it('related excludes unrelated nodes and includes the connecting edges', () => {
    const r = computeDependencyHighlight(envelope(), 'module:pkg/b.js');
    expect(r.related.has('module:other/d.js')).toBe(false);
    expect(r.related.has('module:pkg/b.js')).toBe(true);
    expect([...r.edgeIds].sort()).toEqual(['e:ab', 'e:bc']);
  });

  it('returns an empty result for an unknown / missing node', () => {
    expect(computeDependencyHighlight(envelope(), 'nope').related.size).toBe(0);
    expect(computeDependencyHighlight(null, 'x').related.size).toBe(0);
  });
});

describe('breadcrumb + cluster navigation', () => {
  it('rootClusterId resolves the level-0 System cluster', () => {
    expect(rootClusterId(envelope())).toBe('cluster:');
  });

  it('buildBreadcrumbPath returns the ordered System→cluster ancestry', () => {
    const path = buildBreadcrumbPath(envelope(), 'cluster:pkg/sub');
    expect(path.map((c) => c.title)).toEqual(['System', 'pkg', 'sub']);
    expect(path[0].id).toBe('cluster:');
  });

  it('getClusterChildren returns the immediate child clusters', () => {
    const kids = getClusterChildren(envelope(), 'cluster:pkg');
    expect(kids.map((c) => c.id)).toEqual(['cluster:pkg/sub']);
  });

  it('getClusterMembers includes descendant cluster nodes (drill scope)', () => {
    const members = getClusterMembers(envelope(), 'cluster:pkg');
    expect([...members].sort()).toEqual([
      'module:pkg/a.js',
      'module:pkg/b.js',
      'module:pkg/sub/c.js',
    ]);
  });
});

describe('renderClusterBarHTML', () => {
  it('renders breadcrumb crumbs + drill chips for the current cluster', () => {
    const html = renderClusterBarHTML(envelope(), 'cluster:pkg');
    expect(html).toContain('data-arch-crumb="cluster:"');
    expect(html).toContain('data-arch-crumb="cluster:pkg"');
    // pkg's child cluster is offered as a drill chip.
    expect(html).toContain('data-arch-cluster="cluster:pkg/sub"');
  });

  it('returns empty string when the envelope has no clusters', () => {
    const env = normalizeEnvelope({ lanes: [], nodes: [], freshness: { state: 'fresh' } });
    expect(renderClusterBarHTML(env, 'cluster:')).toBe('');
  });
});
