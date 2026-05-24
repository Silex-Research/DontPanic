// Unit tests for the F002 Architecture shell logic.
//
// Covers acceptance: shell nav-visible (renderArchitectureHTML returns
// non-empty HTML even for missing state), value-first labels (no
// "module" / "fingerprint" in Layer 1 headlines), missing/stale state
// rendering, regen command emission, flow validation warnings.

import { describe, it, expect } from 'vitest';
import {
  FRESHNESS_HEADLINES,
  FRESHNESS_IMPACT,
  collectFlowWarnings,
  isMissingState,
  normalizeEnvelope,
  renderArchitectureHTML,
  renderErrorStateHTML,
  renderMissingStateHTML,
  renderNodeProvenanceHTML,
  resolveArchitectureEnvelope,
} from '../../lib/architecture-logic.js';
import fixture from '../fixtures/architecture-view-state.json' with { type: 'json' };

describe('isMissingState', () => {
  it('treats null / non-objects / shape-mismatch as missing', () => {
    expect(isMissingState(null)).toBe(true);
    expect(isMissingState(undefined)).toBe(true);
    expect(isMissingState('')).toBe(true);
    expect(isMissingState(123)).toBe(true);
    expect(isMissingState({})).toBe(true);
    expect(isMissingState({ lanes: [] })).toBe(true); // missing nodes
    expect(isMissingState({ nodes: [] })).toBe(true); // missing lanes
  });

  it('accepts the F001 view-state shape', () => {
    expect(isMissingState({ lanes: [], nodes: [] })).toBe(false);
    expect(isMissingState(fixture)).toBe(false);
  });
});

describe('normalizeEnvelope', () => {
  it('returns null for missing/invalid input', () => {
    expect(normalizeEnvelope(null)).toBeNull();
    expect(normalizeEnvelope({})).toBeNull();
  });

  it('preserves nodes / edges / flows / freshness fields', () => {
    const env = normalizeEnvelope(fixture);
    expect(env).not.toBeNull();
    expect(env.lanes).toHaveLength(fixture.lanes.length);
    expect(env.nodes).toHaveLength(fixture.nodes.length);
    expect(env.flows).toHaveLength(fixture.flows.length);
    expect(env.freshness.state).toBe('stale');
    expect(env.freshness.regen_command).toBe('dontpanic architecture regen --with-html');
  });

  it('falls back to a default regen command when missing', () => {
    const env = normalizeEnvelope({
      lanes: [],
      nodes: [],
      freshness: { state: 'stale' },
    });
    expect(env.freshness.regen_command).toBe('dontpanic architecture regen --with-html');
  });

  it('clamps unknown freshness state to "absent" (F001 canonical)', () => {
    const env = normalizeEnvelope({
      lanes: [],
      nodes: [],
      freshness: { state: 'bogus' },
    });
    expect(env.freshness.state).toBe('absent');
  });

  it('accepts all four F001 freshness states', () => {
    for (const state of ['fresh', 'stale', 'absent', 'error']) {
      const env = normalizeEnvelope({
        lanes: [],
        nodes: [],
        freshness: { state },
      });
      expect(env.freshness.state).toBe(state);
    }
  });

  it('normalizes legacy "missing" alias to F001 "absent"', () => {
    const env = normalizeEnvelope({
      lanes: [],
      nodes: [],
      freshness: { state: 'missing' },
    });
    expect(env.freshness.state).toBe('absent');
  });
});

describe('collectFlowWarnings', () => {
  it('walks step-level warnings on every flow', () => {
    const warnings = collectFlowWarnings(normalizeEnvelope(fixture));
    expect(warnings.length).toBeGreaterThan(0);
    const messages = warnings.map((w) => w.message);
    expect(messages.some((m) => m.includes('node_ref'))).toBe(true);
    expect(warnings.some((w) => w.flow_id === 'flow:authored-broken')).toBe(true);
  });

  it('returns [] when the envelope is null', () => {
    expect(collectFlowWarnings(null)).toEqual([]);
  });

  it('accepts string warnings as well as object warnings', () => {
    const env = normalizeEnvelope({
      lanes: [],
      nodes: [],
      flows: [
        {
          id: 'flow:str',
          steps: [{ id: 'step:1', warnings: ['plain string warning'] }],
          warnings: ['flow-level string warning'],
        },
      ],
      validation_warnings: ['envelope-level warning'],
    });
    const warnings = collectFlowWarnings(env);
    const messages = warnings.map((w) => w.message).sort();
    expect(messages).toContain('plain string warning');
    expect(messages).toContain('flow-level string warning');
    expect(messages).toContain('envelope-level warning');
  });
});

describe('renderArchitectureHTML — missing state', () => {
  it('renders the missing-state empty card for null input', () => {
    const html = renderArchitectureHTML(null);
    expect(html).toContain('data-empty-state="missing"');
    expect(html).toContain(FRESHNESS_HEADLINES.missing);
    expect(html).toContain('dontpanic architecture regen --with-html');
    expect(html).toContain('dontpanic dashboard build');
  });

  it('renders the missing-state card when freshness.state is missing', () => {
    const html = renderArchitectureHTML({
      schema_version: '1.0',
      project: {},
      generated_at: '',
      source_path: 'docs/architecture/architecture.json',
      lanes: [],
      nodes: [],
      edges: [],
      flows: [],
      steps: [],
      filters: {},
      insights: [],
      validation_warnings: [],
      freshness: {
        state: 'missing',
        message: 'No architecture snapshot yet.',
        regen_command: 'dontpanic architecture regen --with-html',
      },
    });
    expect(html).toContain('data-empty-state="missing"');
    expect(html).toContain('dontpanic architecture regen --with-html');
  });

  it('does not present the missing state as a blocker', () => {
    const html = renderArchitectureHTML(null).toLowerCase();
    expect(html).not.toContain('error');
    expect(html).not.toContain('blocked');
    expect(html).not.toContain('firebase');
  });

  it('emits a copy button with the regen command as data-command', () => {
    const html = renderMissingStateHTML('project');
    expect(html).toMatch(/data-command="dontpanic architecture regen --with-html"/);
    expect(html).toContain('arch-copy-btn');
    expect(html).toContain('aria-label="Copy regen command to clipboard"');
  });
});

describe('renderArchitectureHTML — stale state', () => {
  it('renders the stale freshness banner with the regen command', () => {
    const html = renderArchitectureHTML(fixture);
    expect(html).toContain('data-state="stale"');
    expect(html).toContain('data-freshness="stale"');
    expect(html).toContain('System map is out of date');
    expect(html).toContain('arch-freshness-banner--yellow');
    expect(html).toMatch(/data-command="dontpanic architecture regen --with-html"/);
  });

  it('exposes source path and last-generated timestamp in the header', () => {
    const html = renderArchitectureHTML(fixture);
    expect(html).toContain('docs/architecture/architecture.json');
    expect(html).toContain('2026-05-24T06:08:41Z');
  });

  it('renders flow validation warnings without crashing the page', () => {
    const html = renderArchitectureHTML(fixture);
    expect(html).toContain('data-warnings="1"');
    expect(html).toContain('FLOW WARNINGS');
    expect(html).toContain('flow:authored-broken');
    expect(html).toContain('node_ref does not resolve');
  });

  it('keeps technical IDs available in the details / provenance layer', () => {
    const html = renderArchitectureHTML(fixture);
    // Module path and plan-fingerprint prefix remain visible in Layer 2.
    expect(html).toContain('49ac32b330bc'); // fingerprint truncated to 12
    expect(html).toContain('docs/architecture/architecture.json');
    expect(html).toContain('flow:architecture-regen');
    // Module source paths flow through the lane summary list.
    expect(html).toContain('lane:orchestrator-runtime');
  });

  it('renders insights derived from the snapshot', () => {
    const html = renderArchitectureHTML(fixture);
    expect(html).toContain('Modules');
    expect(html).toContain('102');
    expect(html).toContain('Plans');
    expect(html).toContain('66');
  });
});

describe('renderArchitectureHTML — fresh state stays quiet', () => {
  it('does not surface the regen command in the freshness banner when fresh', () => {
    const fresh = {
      ...fixture,
      freshness: {
        ...fixture.freshness,
        state: 'fresh',
        message: 'Snapshot matches the working tree.',
      },
    };
    const html = renderArchitectureHTML(fresh);
    expect(html).toContain('data-freshness="fresh"');
    expect(html).toContain('System map is up to date');
    // The fresh banner does not repeat the command — it stays available
    // through the provenance footer's "Refresh" line and through the
    // missing-state card if the cache disappears. The page itself never
    // emits the regen command in the populated-fresh banner.
    expect(html).not.toMatch(
      /arch-freshness-actions[\s\S]*data-command="dontpanic architecture regen/,
    );
  });
});

describe('value-first copy invariants', () => {
  it('uses value-first headlines in Layer 1, technical IDs only in details', () => {
    const html = renderArchitectureHTML(fixture);
    // Layer 1 headline strings.
    expect(html).toContain('Architecture');
    expect(html).toContain('System Map');
    expect(html).toContain('How is this system put together');
    // Layer 2 metadata persists (technical IDs are required for review).
    // F002 ships the shell — module-level IDs land in F003's interactive
    // map; the shell exposes lane IDs and flow IDs as the technical
    // surface so detail/provenance is non-empty even at the shell stage.
    expect(html).toContain('lane:orchestrator-runtime');
    expect(html).toContain('flow:architecture-regen');
  });

  it('label "Architecture" is the user-visible nav term, not "Capabilities"', () => {
    // F002 acceptance #1: Architecture tab loads as Architecture, not as
    // the older Capabilities / Jarvis labels.
    const html = renderArchitectureHTML(fixture);
    expect(html).toMatch(/<h2 class="arch-title">Architecture<\/h2>/);
  });
});

describe('FRESHNESS constants', () => {
  it('headline and impact strings are non-empty for all states (incl. absent / error)', () => {
    for (const state of ['fresh', 'stale', 'absent', 'error', 'missing']) {
      expect(FRESHNESS_HEADLINES[state].length).toBeGreaterThan(0);
      expect(FRESHNESS_IMPACT[state].length).toBeGreaterThan(0);
    }
  });
});

describe('renderArchitectureHTML — absent state (F001 canonical)', () => {
  it('renders the missing-state empty card for envelope.state="absent"', () => {
    const env = {
      schema_version: '1.0',
      project: {},
      generated_at: '',
      source_path: 'docs/architecture/architecture.json',
      lanes: [],
      nodes: [],
      edges: [],
      flows: [],
      steps: [],
      filters: {},
      insights: [],
      validation_warnings: [],
      freshness: {
        state: 'absent',
        message: 'architecture.json was not found. Run the regen command to generate it.',
        regen_command: 'dontpanic architecture regen --with-html',
      },
    };
    const html = renderArchitectureHTML(env);
    expect(html).toContain('data-empty-state="missing"');
    expect(html).toContain('data-freshness="absent"');
    // F001's actionable message reaches the operator instead of being dropped.
    expect(html).toContain('architecture.json was not found');
  });
});

describe('renderArchitectureHTML — error state (F001 canonical)', () => {
  it('routes envelope.state="error" to a distinct error card with the F001 message', () => {
    const env = {
      schema_version: '1.0',
      project: {},
      generated_at: '',
      source_path: 'docs/architecture/architecture.json',
      lanes: [],
      nodes: [],
      edges: [],
      flows: [],
      steps: [],
      filters: {},
      insights: [],
      validation_warnings: [],
      freshness: {
        state: 'error',
        message: 'architecture.json is unreadable: unexpected token at byte 14',
        regen_command: 'dontpanic architecture regen --with-html',
      },
    };
    const html = renderArchitectureHTML(env);
    expect(html).toContain('data-state="error"');
    expect(html).toContain('data-empty-state="error"');
    expect(html).toContain('data-freshness="error"');
    // F001 message surfaces verbatim — acceptance #3 (honest + actionable).
    expect(html).toContain('architecture.json is unreadable');
    expect(html).toContain('System map could not be read');
    expect(html).toMatch(/data-command="dontpanic architecture regen --with-html"/);
  });

  it('renderErrorStateHTML is exported and renders the source path + ERROR badge', () => {
    const html = renderErrorStateHTML('project', {
      source_path: 'docs/architecture/architecture.json',
      freshness: {
        state: 'error',
        message: 'parse failed at line 42',
        regen_command: 'dontpanic architecture regen --with-html',
        generated_at: '2026-05-24T00:00:00Z',
      },
    });
    expect(html).toContain('docs/architecture/architecture.json');
    expect(html).toContain('parse failed at line 42');
    expect(html).toContain('ERROR');
    expect(html).toContain('2026-05-24T00:00:00Z');
  });
});

describe('renderNodeProvenanceHTML — technical IDs in details/provenance', () => {
  it('surfaces module paths, plan IDs, capability IDs by type with source paths', () => {
    const html = renderNodeProvenanceHTML(normalizeEnvelope(fixture));
    // The fixture only carries module + command nodes. Module path,
    // module ID, and source path must all be visible. (Acceptance #2.)
    expect(html).toContain('Modules');
    expect(html).toContain('module:scripts/dontpanic_orchestrate/cli.py');
    expect(html).toContain('scripts/dontpanic_orchestrate/cli.py');
    expect(html).toContain('Module path');
    expect(html).toContain('Source path');
  });

  it('handles plan and capability node types with the right ID labels', () => {
    const env = normalizeEnvelope({
      lanes: [],
      nodes: [
        {
          id: 'plan:2026-04-19-001-infra-cross-agent-orchestration',
          type: 'plan',
          source_path: 'docs/plans/2026-04-19-001/plan.md',
          title: 'Cross-Agent Orchestration',
          lane_id: 'lane:data-evidence',
        },
        {
          id: 'capability:agent-claude-cli',
          type: 'capability',
          source_path: 'capabilities/agent-claude-cli.json',
          title: 'Claude CLI agent runtime',
          lane_id: 'lane:capabilities-adapters',
        },
      ],
      flows: [],
      freshness: { state: 'fresh' },
    });
    const html = renderNodeProvenanceHTML(env);
    expect(html).toContain('Plan ID');
    expect(html).toContain('plan:2026-04-19-001-infra-cross-agent-orchestration');
    expect(html).toContain('docs/plans/2026-04-19-001/plan.md');
    expect(html).toContain('Capability ID');
    expect(html).toContain('capability:agent-claude-cli');
    expect(html).toContain('capabilities/agent-claude-cli.json');
  });

  it('renders nothing when there are no nodes', () => {
    expect(renderNodeProvenanceHTML({ nodes: [] })).toBe('');
    expect(renderNodeProvenanceHTML({})).toBe('');
    expect(renderNodeProvenanceHTML(null)).toBe('');
  });

  it('populated render embeds the provenance panel (acceptance #2)', () => {
    const html = renderArchitectureHTML(fixture);
    expect(html).toContain('data-provenance="1"');
    expect(html).toContain('Details &amp; Provenance');
    expect(html).toContain('Module path');
    expect(html).toContain('module:scripts/dontpanic_orchestrate/cli.py');
  });
});

describe('resolveArchitectureEnvelope — project-scoped fallback', () => {
  it('returns the per-project envelope when selectedProject matches', () => {
    const projectEnv = { id: 'project-env', lanes: [], nodes: [] };
    const singleEnv = { id: 'single-env', lanes: [], nodes: [] };
    const out = resolveArchitectureEnvelope({
      selectedProject: 'spindineswift',
      single: singleEnv,
      byProject: { spindineswift: projectEnv },
    });
    expect(out).toBe(projectEnv);
  });

  it('falls back to single-repo envelope when no per-project cache exists', () => {
    const singleEnv = { id: 'single-env', lanes: [], nodes: [] };
    const out = resolveArchitectureEnvelope({
      selectedProject: 'spindineswift',
      single: singleEnv,
      byProject: {},
    });
    expect(out).toBe(singleEnv);
  });

  it('uses single-repo envelope when selectedProject === "all"', () => {
    const projectEnv = { id: 'project-env' };
    const singleEnv = { id: 'single-env' };
    const out = resolveArchitectureEnvelope({
      selectedProject: 'all',
      single: singleEnv,
      byProject: { spindineswift: projectEnv },
    });
    expect(out).toBe(singleEnv);
  });

  it('returns null when neither cache is available', () => {
    expect(resolveArchitectureEnvelope({
      selectedProject: 'spindineswift',
      single: null,
      byProject: null,
    })).toBeNull();
  });

  it('tolerates missing options (defaults to all + single)', () => {
    const singleEnv = { id: 'single-env' };
    expect(resolveArchitectureEnvelope({ single: singleEnv })).toBe(singleEnv);
    expect(resolveArchitectureEnvelope({})).toBeNull();
  });
});
