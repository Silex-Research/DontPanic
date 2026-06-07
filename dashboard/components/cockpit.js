/*
 * Cockpit — the action surface (plan 2026-06-06-004 F004, spec §1.2/§5.1/§5.2).
 * Folds Overview + Needs-Attention into one workflow: the triaged "what needs you" queue
 * (ranked, grouped by bucket; quiet/auto-safe collapsed to counts) + the inspect-why panel
 * (five fixed sections) + a terminal-dock slot. Pure functions over the operator-triage model.
 */

import { renderItem, renderEmptyState, BUCKET_LABELS, RESOLUTION_LABELS } from './action-item.js';

// Buckets that mean "a human or agent must act now" — the hero "N need you" count (§5.1: 2+4+8=14).
export const NEED_YOU = Object.freeze(['needs_auth', 'needs_decision', 'agent_runnable']);
// Expanded into feeds by default; quiet + auto_safe collapse to a count (never a feed).
export const EXPANDED = Object.freeze(['needs_auth', 'needs_decision', 'agent_runnable', 'uncertain']);
export const COLLAPSED = Object.freeze(['auto_safe', 'quiet']);
const ORDER = Object.freeze([...EXPANDED.slice(0, 3), 'auto_safe', 'uncertain', 'quiet']);

const items = (model) => (model && Array.isArray(model.items) ? model.items : []);

/** Group items by bucket, in severity order, with per-group counts. */
export function groupByBucket(model) {
  const buckets = {};
  for (const it of items(model)) (buckets[it.operator_bucket] ||= []).push(it);
  return ORDER.filter((b) => buckets[b]?.length).map((bucket) => ({
    bucket,
    label: BUCKET_LABELS[bucket],
    count: buckets[bucket].length,
    items: buckets[bucket],
    collapsed: COLLAPSED.includes(bucket),
  }));
}

/** The hero count: how many items actually need the operator now. */
export function needYouCount(model) {
  return items(model).filter((i) => NEED_YOU.includes(i.operator_bucket)).length;
}

function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
}

/**
 * The triage queue. When nothing needs the operator, collapses to the "you're clear" payoff
 * (§2.5) — emptiness is the product working, not a broken page.
 */
export function renderQueue(model, opts = {}) {
  const root = el('section', 'dp-cockpit');
  const need = needYouCount(model);

  if (need === 0) {
    root.appendChild(renderEmptyState({
      signals: items(model).length,
      projects: opts.projects ?? new Set(items(model).map((i) => i.project_name).filter(Boolean)).size,
      lastRefresh: opts.lastRefresh,
    }));
    return root;
  }

  const hero = el('div', 'dp-hero');
  hero.appendChild(el('div', 'dp-hero-count', String(need)));
  hero.appendChild(el('div', 'dp-hero-label', 'need you'));
  root.appendChild(hero);

  for (const g of groupByBucket(model)) {
    const group = el('div', `dp-group dp-group--${g.bucket}${g.collapsed ? ' dp-group--collapsed' : ''}`);
    group.dataset.bucket = g.bucket;
    const head = el('button', 'dp-group-head');
    head.type = 'button';
    head.appendChild(el('span', 'dp-group-label', g.label));
    head.appendChild(el('span', 'dp-group-count', String(g.count)));
    group.appendChild(head);
    if (!g.collapsed) {
      const feed = el('div', 'dp-group-feed');
      for (const it of g.items) feed.appendChild(renderItem(it, { density: opts.density, showScope: opts.showScope }));
      group.appendChild(feed);
    }
    root.appendChild(group);
  }
  return root;
}

// The five fixed inspect sections, always in this order (§5.2). Each maps to a field.
const INSPECT_SECTIONS = Object.freeze([
  { key: 'what', label: 'WHAT', field: 'title' },
  { key: 'why', label: 'WHY NOW', field: 'why_now' },
  { key: 'evidence', label: 'EVIDENCE', field: 'evidence_uri' },
  { key: 'provenance', label: 'PROVENANCE', field: 'provenance_source' },
  { key: 'resolution', label: 'RESOLUTION', field: 'resolution' },
]);

export { INSPECT_SECTIONS };

/**
 * Inspect-why panel (§5.2) — a right-side panel (not a modal: operators compare). Everything
 * required to trust or distrust on sight, nothing extra. Render-truth is visible: the freshness
 * basis is stated, never implied.
 */
export function renderInspectPanel(item) {
  const root = el('aside', 'dp-inspect');
  root.dataset.itemId = item.id ?? '';
  root.appendChild(el('h2', 'dp-inspect-title', item.title || '(untitled)'));

  for (const s of INSPECT_SECTIONS) {
    const sec = el('section', `dp-inspect-section dp-inspect-${s.key}`);
    sec.dataset.section = s.key;
    sec.appendChild(el('h3', 'dp-inspect-label', s.label));
    if (s.key === 'resolution') {
      const opts = Array.isArray(item.resolution) ? item.resolution : [];
      const bar = el('div', 'dp-inspect-resolutions');
      for (const intent of opts) {
        // human label on the face; the raw intent stays on the dataset for the action layer
        const b = el('button', 'dp-affordance', RESOLUTION_LABELS[intent] || intent);
        b.type = 'button'; b.dataset.resolution = intent; bar.appendChild(b);
      }
      sec.appendChild(bar);
    } else if (s.key === 'provenance') {
      // the producer line comes from actor_label (display); provenance_source is the machine id
      sec.appendChild(el('div', 'dp-inspect-actor', `Producer · ${item.actor_label || item.provenance_source || 'unknown'}`));
      if (item.provenance_source) sec.appendChild(el('div', 'dp-inspect-value', item.provenance_source));
      // render-truth: the basis is shown plainly, never dressed up as item-level proof
      const basis = item.freshness_basis || 'no basis';
      sec.appendChild(el('div', 'dp-inspect-basis', `freshness basis · ${basis}`));
      if (item.asserted_at) sec.appendChild(el('div', 'dp-inspect-asserted', `asserted · ${item.asserted_at}`));
    } else {
      sec.appendChild(el('div', 'dp-inspect-value', item[s.field] || '—'));
    }
    root.appendChild(sec);
  }
  return root;
}
