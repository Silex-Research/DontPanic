// Unit tests for project-selector-logic.js — the pure transformation
// layer behind the F003 project selector and scope labels.

import { describe, it, expect } from 'vitest';
import {
  ALL_PROJECTS_VALUE,
  SCOPES,
  SCOPE_LABELS,
  STORAGE_KEY,
  URL_PARAM,
  buildSelectionURL,
  formatAddProjectCommand,
  formatBuildFleetCommand,
  getProjectOptions,
  isMissingFleetSummary,
  normalizeFleetSummary,
  renderAddProjectHTML,
  renderHeaderStripHTML,
  renderMissingSummaryHTML,
  renderScopeBadgeHTML,
  renderSelectorHTML,
  resolveSelection,
} from '../../lib/project-selector-logic.js';

import fixture from '../fixtures/fleet-summary.json' with { type: 'json' };

// ── Constants ──────────────────────────────────────────────────────────

describe('project-selector: constants', () => {
  it('exposes the All Projects sentinel as `all`', () => {
    expect(ALL_PROJECTS_VALUE).toBe('all');
  });

  it('exposes the three scope keys', () => {
    expect(SCOPES).toEqual(['global', 'project', 'fleet']);
    for (const s of SCOPES) {
      expect(SCOPE_LABELS[s]).toBeTruthy();
    }
  });

  it('exposes URL_PARAM and STORAGE_KEY stable identifiers', () => {
    expect(URL_PARAM).toBe('project');
    expect(STORAGE_KEY).toBe('dontpanic.dashboard.selectedProject');
  });
});

// ── isMissingFleetSummary ──────────────────────────────────────────────

describe('project-selector: isMissingFleetSummary', () => {
  it('treats null/undefined as missing', () => {
    expect(isMissingFleetSummary(null)).toBe(true);
    expect(isMissingFleetSummary(undefined)).toBe(true);
  });

  it('treats objects without a projects array as missing', () => {
    expect(isMissingFleetSummary({})).toBe(true);
    expect(isMissingFleetSummary({ projects: 'nope' })).toBe(true);
  });

  it('treats a valid envelope as present', () => {
    expect(isMissingFleetSummary({ projects: [] })).toBe(false);
    expect(isMissingFleetSummary(fixture)).toBe(false);
  });
});

// ── normalizeFleetSummary ──────────────────────────────────────────────

describe('project-selector: normalizeFleetSummary', () => {
  it('returns null for non-envelope inputs', () => {
    expect(normalizeFleetSummary(null)).toBeNull();
    expect(normalizeFleetSummary({})).toBeNull();
  });

  it('passes through schema_version, captured_at, and dontpanic_version', () => {
    const env = normalizeFleetSummary(fixture);
    expect(env.schema_version).toBe('1.0.0');
    expect(env.captured_at).toBe('2026-05-23T03:50:00Z');
    expect(env.dontpanic_version).toBe('0.4.0');
  });

  it('drops project entries with no stable name', () => {
    const env = normalizeFleetSummary({
      projects: [
        { name: 'ok' },
        { name: '' },
        { display_name: 'no-name' },
        null,
      ],
    });
    expect(env.projects).toHaveLength(1);
    expect(env.projects[0].name).toBe('ok');
  });

  it('falls back display_name → name when display_name is empty', () => {
    const env = normalizeFleetSummary({
      projects: [{ name: 'spindine', display_name: '' }],
    });
    expect(env.projects[0].display_name).toBe('spindine');
  });

  it('preserves inactive flag and skipped reason', () => {
    const env = normalizeFleetSummary(fixture);
    const archived = env.projects.find((p) => p.name === 'archived');
    expect(archived).toBeDefined();
    expect(archived.active).toBe(false);
    expect(archived.skipped).toBe(true);
    expect(archived.skipped_reason).toBe('project marked inactive');
  });
});

// ── getProjectOptions ──────────────────────────────────────────────────

describe('project-selector: getProjectOptions', () => {
  it('starts with All Projects when envelope is null', () => {
    const opts = getProjectOptions(null);
    expect(opts).toEqual([{ value: 'all', label: 'All Projects' }]);
  });

  it('lists All Projects then each registered project in order', () => {
    const env = normalizeFleetSummary(fixture);
    const opts = getProjectOptions(env);
    expect(opts.map((o) => o.value)).toEqual(['all', 'spindine', 'dontpanic', 'archived']);
  });

  it('marks inactive projects with an "(inactive)" suffix on the label', () => {
    const env = normalizeFleetSummary(fixture);
    const opts = getProjectOptions(env);
    const archived = opts.find((o) => o.value === 'archived');
    expect(archived.label).toBe('Old App (inactive)');
  });

  it('uses display_name in the label', () => {
    const env = normalizeFleetSummary(fixture);
    const opts = getProjectOptions(env);
    const sd = opts.find((o) => o.value === 'spindine');
    expect(sd.label).toBe('Spin & Dine');
  });
});

// ── resolveSelection ───────────────────────────────────────────────────

describe('project-selector: resolveSelection', () => {
  const options = [
    { value: 'all', label: 'All Projects' },
    { value: 'spindine', label: 'Spin & Dine' },
    { value: 'dontpanic', label: 'DontPanic' },
  ];

  it('returns the URL value when it points at a known project', () => {
    const out = resolveSelection({ urlValue: 'spindine', storageValue: null, options });
    expect(out).toEqual({ value: 'spindine', source: 'url' });
  });

  it('falls back to localStorage when the URL is missing', () => {
    const out = resolveSelection({ urlValue: null, storageValue: 'dontpanic', options });
    expect(out).toEqual({ value: 'dontpanic', source: 'storage' });
  });

  it('falls back to default `all` when neither URL nor storage is valid', () => {
    const out = resolveSelection({ urlValue: null, storageValue: null, options });
    expect(out).toEqual({ value: 'all', source: 'default' });
  });

  it('drops a stale URL value that no longer matches the served fleet', () => {
    const out = resolveSelection({ urlValue: 'ghost', storageValue: 'spindine', options });
    expect(out).toEqual({ value: 'spindine', source: 'storage' });
  });

  it('drops a stale storage value when no URL value is present', () => {
    const out = resolveSelection({ urlValue: null, storageValue: 'ghost', options });
    expect(out).toEqual({ value: 'all', source: 'default' });
  });

  it('URL wins over localStorage when both are valid', () => {
    const out = resolveSelection({ urlValue: 'spindine', storageValue: 'dontpanic', options });
    expect(out).toEqual({ value: 'spindine', source: 'url' });
  });
});

// ── buildSelectionURL ──────────────────────────────────────────────────

describe('project-selector: buildSelectionURL', () => {
  it('sets the project search-param when given a project name', () => {
    const url = buildSelectionURL('http://localhost:8000/#what-now', 'spindine');
    expect(url).toBe('http://localhost:8000/?project=spindine#what-now');
  });

  it('removes the project search-param when the value is `all`', () => {
    const url = buildSelectionURL('http://localhost:8000/?project=spindine#what-now', 'all');
    expect(url).toBe('http://localhost:8000/#what-now');
  });

  it('preserves the active page hash verbatim', () => {
    const url = new URL(buildSelectionURL('http://localhost:8000/?x=1#capabilities', 'dontpanic'));
    expect(url.hash).toBe('#capabilities');
    expect(url.searchParams.get('project')).toBe('dontpanic');
    expect(url.searchParams.get('x')).toBe('1');
  });
});

// ── command formatters ─────────────────────────────────────────────────

describe('project-selector: command formatters', () => {
  it('formatAddProjectCommand emits the exact registry command shape', () => {
    expect(formatAddProjectCommand()).toBe('dontpanic projects add <name> <path>');
  });

  it('formatAddProjectCommand accepts explicit name + path', () => {
    expect(formatAddProjectCommand('spindine', '/repo')).toBe(
      'dontpanic projects add spindine /repo'
    );
  });

  it('formatBuildFleetCommand emits the fleet build command', () => {
    expect(formatBuildFleetCommand()).toBe('dontpanic dashboard build --project all');
  });
});

// ── renderScopeBadgeHTML ───────────────────────────────────────────────

describe('project-selector: renderScopeBadgeHTML', () => {
  it('renders a Global badge', () => {
    const html = renderScopeBadgeHTML('global');
    expect(html).toContain('scope-badge--global');
    expect(html).toContain('Scope:');
    expect(html).toContain('Global');
    expect(html).toContain('data-scope="global"');
  });

  it('renders a Project badge', () => {
    const html = renderScopeBadgeHTML('project');
    expect(html).toContain('scope-badge--project');
    expect(html).toContain('Project');
  });

  it('renders a Fleet badge', () => {
    const html = renderScopeBadgeHTML('fleet');
    expect(html).toContain('scope-badge--fleet');
    expect(html).toContain('Fleet');
  });

  it('falls back to project for an unknown scope', () => {
    const html = renderScopeBadgeHTML('weird');
    expect(html).toContain('scope-badge--project');
  });
});

// ── renderSelectorHTML / renderHeaderStripHTML ─────────────────────────

describe('project-selector: renderSelectorHTML', () => {
  it('emits a labeled select with All Projects + every registered project', () => {
    const env = normalizeFleetSummary(fixture);
    const html = renderSelectorHTML(env, 'all');
    expect(html).toContain('data-project-selector="1"');
    expect(html).toContain('<option value="all" selected>All Projects</option>');
    expect(html).toContain('value="spindine"');
    expect(html).toContain('value="dontpanic"');
    expect(html).toContain('value="archived"');
  });

  it('marks the resolved selection as <option selected>', () => {
    const env = normalizeFleetSummary(fixture);
    const html = renderSelectorHTML(env, 'spindine');
    expect(html).toMatch(/value="spindine" selected>Spin/);
  });

  it('shows a Fleet scope badge when All Projects is selected', () => {
    const env = normalizeFleetSummary(fixture);
    const html = renderSelectorHTML(env, 'all');
    expect(html).toContain('scope-badge--fleet');
  });

  it('shows a Project scope badge when a registered project is selected', () => {
    const env = normalizeFleetSummary(fixture);
    const html = renderSelectorHTML(env, 'dontpanic');
    expect(html).toContain('scope-badge--project');
  });

  it('always renders the Add Project command-emission row', () => {
    const env = normalizeFleetSummary(fixture);
    const html = renderSelectorHTML(env, 'all');
    expect(html).toContain('data-add-project="1"');
    expect(html).toContain('dontpanic projects add &lt;name&gt; &lt;path&gt;');
  });
});

describe('project-selector: renderAddProjectHTML', () => {
  it('embeds the registration command shape', () => {
    expect(renderAddProjectHTML()).toContain('dontpanic projects add &lt;name&gt; &lt;path&gt;');
  });

  it('does not include any input or form element (no inline mutation)', () => {
    const html = renderAddProjectHTML();
    expect(html).not.toMatch(/<input/i);
    expect(html).not.toMatch(/<form/i);
    expect(html).not.toMatch(/<button/i);
  });
});

describe('project-selector: renderMissingSummaryHTML', () => {
  it('surfaces the exact fleet-build command', () => {
    const html = renderMissingSummaryHTML();
    expect(html).toContain('dontpanic dashboard build --project all');
    expect(html).toContain('data-state="missing"');
  });
});

describe('project-selector: renderHeaderStripHTML', () => {
  it('returns the missing-summary block when envelope is null', () => {
    const html = renderHeaderStripHTML({ envelope: null, selected: 'all' });
    expect(html).toContain('data-state="missing"');
    expect(html).toContain('dontpanic dashboard build --project all');
  });

  it('returns the selector when an envelope is present', () => {
    const env = normalizeFleetSummary(fixture);
    const html = renderHeaderStripHTML({ envelope: env, selected: 'all' });
    expect(html).toContain('data-project-selector="1"');
  });
});
