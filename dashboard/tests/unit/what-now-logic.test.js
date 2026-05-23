// Unit tests for what-now-logic.js — the pure transformation layer
// behind the F004 What Now operator view.

import { describe, it, expect } from 'vitest';
import {
  BANDS,
  BAND_LABELS,
  BAND_COLORS,
  SOURCES,
  SOURCE_LABELS,
  getBandBadge,
  getSourceLabel,
  groupByBand,
  hasNeedsAction,
  isMissingState,
  normalizeEnvelope,
  renderMissingStateHTML,
  renderQuietStateHTML,
  renderWhatNowHTML,
  sortItems,
  summarizeByBand,
} from '../../lib/what-now-logic.js';

import fixture from '../fixtures/what-now.json' with { type: 'json' };

// ── Constants ──

describe('what-now: constants', () => {
  it('exposes the four bands in display order', () => {
    expect(BANDS).toEqual(['needs_action', 'advisory', 'info', 'ready']);
  });

  it('has a label and color for every band', () => {
    for (const band of BANDS) {
      expect(BAND_LABELS[band]).toBeTruthy();
      expect(BAND_COLORS[band]).toBeTruthy();
    }
  });

  it('exposes the five V0 sources with labels', () => {
    expect(SOURCES).toEqual(['gate', 'capability', 'reconcile', 'supervisor', 'architecture']);
    for (const s of SOURCES) {
      expect(SOURCE_LABELS[s]).toBeTruthy();
    }
  });
});

// ── isMissingState ──

describe('what-now: isMissingState', () => {
  it('treats null as missing', () => {
    expect(isMissingState(null)).toBe(true);
  });
  it('treats undefined as missing', () => {
    expect(isMissingState(undefined)).toBe(true);
  });
  it('treats non-objects as missing', () => {
    expect(isMissingState('nope')).toBe(true);
    expect(isMissingState(7)).toBe(true);
  });
  it('treats an object without items array as missing', () => {
    expect(isMissingState({})).toBe(true);
    expect(isMissingState({ items: 'nope' })).toBe(true);
  });
  it('treats a valid envelope as present', () => {
    expect(isMissingState({ items: [] })).toBe(false);
    expect(isMissingState(fixture)).toBe(false);
  });
});

// ── normalizeEnvelope ──

describe('what-now: normalizeEnvelope', () => {
  it('returns null for non-envelope inputs', () => {
    expect(normalizeEnvelope(null)).toBeNull();
    expect(normalizeEnvelope(undefined)).toBeNull();
    expect(normalizeEnvelope({})).toBeNull();
    expect(normalizeEnvelope({ items: 'nope' })).toBeNull();
  });

  it('preserves all envelope-level fields from the fixture', () => {
    const env = normalizeEnvelope(fixture);
    expect(env.schema_version).toBe('1.0.0');
    expect(env.captured_at).toMatch(/^2026-/);
    expect(env.items.length).toBe(fixture.items.length);
  });

  it('coerces unknown band values to "info"', () => {
    const env = normalizeEnvelope({
      items: [{ id: 'x', source: 'gate', band: 'mystery', title: 'x', automatable: true }],
    });
    expect(env.items[0].band).toBe('info');
  });

  it('coerces unknown source values to "capability"', () => {
    const env = normalizeEnvelope({
      items: [{ id: 'x', source: 'bogus', band: 'needs_action', title: 'x', automatable: false, human_required_reason: 'r' }],
    });
    expect(env.items[0].source).toBe('capability');
  });

  it('fills missing optional fields with safe defaults', () => {
    const env = normalizeEnvelope({
      items: [{ id: 'x', source: 'gate', band: 'needs_action', title: 't', automatable: false, human_required_reason: 'r' }],
    });
    const it = env.items[0];
    expect(it.detail).toBeNull();
    expect(it.exact_command).toBeNull();
    expect(it.evidence_uri).toBeNull();
    expect(it.updated_at).toBe('');
  });

  it('drops items that are not objects', () => {
    const env = normalizeEnvelope({ items: [null, 'string', { id: 'a', source: 'gate', band: 'info', title: 't', automatable: true }] });
    expect(env.items.length).toBe(1);
    expect(env.items[0].id).toBe('a');
  });
});

// ── sortItems ──

describe('what-now: sortItems', () => {
  it('orders needs_action before advisory before info before ready', () => {
    const sorted = sortItems([
      { id: 'a', source: 'capability', band: 'ready' },
      { id: 'b', source: 'capability', band: 'needs_action' },
      { id: 'c', source: 'capability', band: 'info' },
      { id: 'd', source: 'capability', band: 'advisory' },
    ]);
    expect(sorted.map((it) => it.band)).toEqual(['needs_action', 'advisory', 'info', 'ready']);
  });

  it('orders gate before reconcile before capability before supervisor before architecture within a band', () => {
    const sorted = sortItems([
      { id: 'arch1', source: 'architecture', band: 'needs_action' },
      { id: 'sup1',  source: 'supervisor',   band: 'needs_action' },
      { id: 'cap1',  source: 'capability',   band: 'needs_action' },
      { id: 'rec1',  source: 'reconcile',    band: 'needs_action' },
      { id: 'gat1',  source: 'gate',         band: 'needs_action' },
    ]);
    expect(sorted.map((it) => it.source)).toEqual(['gate', 'reconcile', 'capability', 'supervisor', 'architecture']);
  });

  it('breaks ties by id ascending', () => {
    const sorted = sortItems([
      { id: 'z', source: 'gate', band: 'needs_action' },
      { id: 'a', source: 'gate', band: 'needs_action' },
      { id: 'm', source: 'gate', band: 'needs_action' },
    ]);
    expect(sorted.map((it) => it.id)).toEqual(['a', 'm', 'z']);
  });

  it('does not mutate the input array', () => {
    const input = [
      { id: 'z', source: 'gate', band: 'ready' },
      { id: 'a', source: 'gate', band: 'needs_action' },
    ];
    const snapshot = JSON.stringify(input);
    sortItems(input);
    expect(JSON.stringify(input)).toBe(snapshot);
  });
});

// ── groupByBand ──

describe('what-now: groupByBand', () => {
  it('omits bands with no items', () => {
    const groups = groupByBand([
      { id: 'a', source: 'gate', band: 'needs_action' },
      { id: 'b', source: 'gate', band: 'advisory' },
    ]);
    expect(groups.map((g) => g.band)).toEqual(['needs_action', 'advisory']);
  });

  it('returns an empty array for missing items', () => {
    expect(groupByBand(null)).toEqual([]);
    expect(groupByBand(undefined)).toEqual([]);
  });

  it('returns groups in the four-band display order', () => {
    const env = normalizeEnvelope(fixture);
    const groups = groupByBand(env.items);
    expect(groups.map((g) => g.band)).toEqual(['needs_action', 'advisory', 'info']);
  });

  it('sorts items within each band deterministically', () => {
    const env = normalizeEnvelope(fixture);
    const groups = groupByBand(env.items);
    const needsAction = groups.find((g) => g.band === 'needs_action');
    // gate < reconcile < capability ordering must hold for needs_action band.
    expect(needsAction.items.map((it) => it.source)).toEqual(['gate', 'reconcile', 'capability']);
  });
});

// ── summarizeByBand + hasNeedsAction ──

describe('what-now: summarizeByBand', () => {
  it('counts each band across the fixture', () => {
    const env = normalizeEnvelope(fixture);
    const s = summarizeByBand(env.items);
    expect(s.total).toBe(5);
    expect(s.needs_action).toBe(3);
    expect(s.advisory).toBe(1);
    expect(s.info).toBe(1);
    expect(s.ready).toBe(0);
  });

  it('returns zeros for non-array input', () => {
    const s = summarizeByBand(null);
    expect(s).toEqual({ needs_action: 0, advisory: 0, info: 0, ready: 0, total: 0 });
  });
});

describe('what-now: hasNeedsAction', () => {
  it('is true when at least one item is in needs_action', () => {
    expect(hasNeedsAction([{ band: 'needs_action' }])).toBe(true);
  });
  it('is false when no items are needs_action', () => {
    expect(hasNeedsAction([{ band: 'advisory' }, { band: 'info' }])).toBe(false);
  });
  it('is false for non-arrays', () => {
    expect(hasNeedsAction(null)).toBe(false);
  });
});

// ── getBandBadge / getSourceLabel ──

describe('what-now: getBandBadge', () => {
  it('returns label and color for every band', () => {
    for (const band of BANDS) {
      const b = getBandBadge(band);
      expect(b.label).toBe(BAND_LABELS[band]);
      expect(b.color).toBe(BAND_COLORS[band]);
    }
  });
  it('falls back to UPPERCASE label and accent color for unknown bands', () => {
    const b = getBandBadge('mystery');
    expect(b.label).toBe('MYSTERY');
    expect(b.color).toBe('accent');
  });
});

describe('what-now: getSourceLabel', () => {
  it('returns the configured label for every source', () => {
    for (const s of SOURCES) {
      expect(getSourceLabel(s)).toBe(SOURCE_LABELS[s]);
    }
  });
  it('falls back to the raw source string for unknown sources', () => {
    expect(getSourceLabel('mystery')).toBe('mystery');
  });
});

// ── renderWhatNowHTML — missing state ──

describe('what-now: renderMissingStateHTML', () => {
  it('renders the missing-cache empty state for null input', () => {
    const html = renderWhatNowHTML(null);
    expect(html).toContain('data-state="missing"');
    expect(html).toContain('dontpanic dashboard build');
    expect(html).toContain('No what-now cache yet');
  });

  it('does NOT alarm the operator (no "BLOCKED" or "ERROR" wording)', () => {
    // Acceptance #4: stale/missing optional data must not render as a blocker.
    const html = renderMissingStateHTML();
    const lower = html.toLowerCase();
    expect(lower).not.toContain('error');
    expect(lower).not.toContain('blocked');
    expect(lower).not.toContain('firebase');
  });
});

// ── renderWhatNowHTML — quiet state ──

describe('what-now: renderQuietStateHTML', () => {
  it('renders the quiet state when the envelope is present but has no items', () => {
    const html = renderWhatNowHTML({ schema_version: '1.0.0', captured_at: '2026-05-23T03:50:00Z', items: [] });
    expect(html).toContain('data-state="quiet"');
    expect(html).toContain('No action needed');
  });

  it('renders advisory + info items as non-alarming cards with visible/copyable commands', () => {
    // F004 acceptance #3 + #4: even when no needs_action items are present,
    // advisory/info items must surface their exact commands so operators
    // can copy them. Restraint comes from band colors (yellow/accent), not
    // collapsing the cards into a quiet panel.
    const html = renderWhatNowHTML({
      schema_version: '1.0.0',
      captured_at: '2026-05-23T03:50:00Z',
      items: [
        {
          id: 'reconcile:missing_snapshot',
          source: 'reconcile',
          band: 'advisory',
          title: 'Install snapshot is missing',
          exact_command: 'dontpanic reconcile baseline --yes',
          automatable: false,
          human_required_reason: 'no baseline to compare against',
        },
        {
          id: 'sup:1',
          source: 'supervisor',
          band: 'info',
          title: 'Supervisor active',
          exact_command: 'dontpanic ps',
          automatable: true,
        },
      ],
    });
    expect(html).not.toContain('data-state="quiet"');
    // Advisory card surfaces title + exact command + copy affordance.
    expect(html).toContain('Install snapshot is missing');
    expect(html).toContain('dontpanic reconcile baseline --yes');
    expect(html).toContain('data-command="dontpanic reconcile baseline --yes"');
    expect(html).toContain('wn-copy-btn');
    // Info card likewise.
    expect(html).toContain('Supervisor active');
    expect(html).toContain('data-command="dontpanic ps"');
    // Band sections present for advisory + info; needs_action absent.
    expect(html).toContain('data-band="advisory"');
    expect(html).toContain('data-band="info"');
    expect(html).not.toContain('data-band="needs_action"');
    // Non-alarming: no red wording / no needs-action band styling.
    const lower = html.toLowerCase();
    expect(lower).not.toContain('blocked');
    expect(lower).not.toContain('error');
    expect(html).not.toContain('wn-band-panel--red');
  });
});

// ── renderWhatNowHTML — populated ──

describe('what-now: renderWhatNowHTML populated', () => {
  it('renders one card per item from the fixture', () => {
    const html = renderWhatNowHTML(fixture);
    for (const item of fixture.items) {
      expect(html).toContain(`data-action-id="${item.id}"`);
    }
  });

  it('groups items into band sections', () => {
    const html = renderWhatNowHTML(fixture);
    expect(html).toContain('data-band="needs_action"');
    expect(html).toContain('data-band="advisory"');
    expect(html).toContain('data-band="info"');
  });

  it('renders the exact_command verbatim inside a pre/code block', () => {
    const html = renderWhatNowHTML(fixture);
    for (const item of fixture.items) {
      if (item.exact_command) {
        // Each exact command appears in the page (the click-handler reads
        // data-command, which is also escaped but byte-identical for ASCII).
        expect(html).toContain(item.exact_command);
      }
    }
  });

  it('renders a copy button with the command payload', () => {
    const html = renderWhatNowHTML(fixture);
    expect(html).toContain('class="wn-copy-btn"');
    expect(html).toContain('data-command="dontpanic approve 2026-05-23-004-feat-operator-console-v0 pre_merge"');
  });

  it('renders the automatable label for items where automatable=true', () => {
    const html = renderWhatNowHTML(fixture);
    expect(html).toContain('wn-role-chip--auto');
    expect(html).toContain('automatable');
  });

  it('renders human-required + the reason on items where automatable=false', () => {
    const html = renderWhatNowHTML(fixture);
    expect(html).toContain('wn-role-chip--human');
    expect(html).toContain('gate approval');
    expect(html).toContain('capability setup incomplete');
  });

  it('renders evidence_uri when present', () => {
    const html = renderWhatNowHTML(fixture);
    expect(html).toContain('docs/plans/2026-05-23-004-feat-operator-console-v0/audit/gate-state.json');
    expect(html).toContain('wn-evidence-uri');
  });

  it('does NOT render an evidence block when evidence_uri is null', () => {
    const html = renderWhatNowHTML({
      schema_version: '1.0.0',
      captured_at: '2026-05-23T03:50:00Z',
      items: [
        { id: 'gate:x:pre_impl', source: 'gate', band: 'needs_action', title: 't', exact_command: 'cmd', automatable: false, human_required_reason: 'r', evidence_uri: null },
      ],
    });
    expect(html).not.toContain('wn-card-evidence');
  });

  it('does NOT expose drag/drop or kanban affordances (read-only contract)', () => {
    // Acceptance #5: view is read-only.
    const html = renderWhatNowHTML(fixture);
    const lower = html.toLowerCase();
    expect(lower).not.toContain('draggable');
    expect(lower).not.toContain('drag-handle');
    expect(lower).not.toContain('kanban');
    expect(lower).not.toContain('drop-zone');
  });

  it('does not render exact_command when missing on an item', () => {
    const html = renderWhatNowHTML({
      schema_version: '1.0.0',
      captured_at: '2026-05-23T03:50:00Z',
      items: [
        { id: 'arch:stale', source: 'architecture', band: 'advisory', title: 't', exact_command: null, automatable: true },
      ],
    });
    expect(html).not.toContain('wn-card-command');
    expect(html).not.toContain('wn-copy-btn');
  });
});

// ── XSS resistance ──

describe('what-now: HTML escape resistance', () => {
  it('escapes special chars in title, command, evidence, and id', () => {
    const malicious = {
      schema_version: '1.0.0',
      captured_at: '2026-05-23T00:00:00Z',
      items: [{
        id: '<script>alert(1)</script>',
        source: 'gate',
        band: 'needs_action',
        title: '<img onerror=1>',
        detail: '<b>oops</b>',
        exact_command: '"><script>x</script>',
        automatable: false,
        human_required_reason: '<i>r</i>',
        evidence_uri: '"><a>',
        updated_at: '2026-05-23T00:00:00Z',
      }],
    };
    const html = renderWhatNowHTML(malicious);
    // No script tag should have been injected.
    expect(html).not.toMatch(/<script>/);
    expect(html).not.toMatch(/<img onerror=1>/);
    // Escaped content should still appear textually.
    expect(html).toContain('&lt;script&gt;alert(1)&lt;/script&gt;');
    expect(html).toContain('&quot;&gt;&lt;script&gt;x&lt;/script&gt;');
  });
});
