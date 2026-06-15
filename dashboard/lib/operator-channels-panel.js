// ── Operator Channels Panel — pure render (plan 2026-06-14-001 F010) ──
// Renders the "Operator Channels" panel from the channel-view emitted by the
// F009 producer (dashboard/state/operator-channels.json). It CONSUMES the F009
// locked rule matrix (deriveBuckets / deriveOperatorRoleMatrix) — it does NOT
// re-derive thresholds or precedence, so producer and renderer cannot diverge.
//
// Read-only. All active + needs-attention members render UNCAPPED. Surface
// labels are display aliases of the canonical ids (F001); canonical ids stay
// machine-side. All exports are pure (same input → same string).

import { esc } from './html-escape.js';
import {
  BUCKET_IDS,
  BUCKET_LABELS,
  deriveBuckets,
  deriveOperatorRoleMatrix,
  CHANNELS_SOURCE,
  CHANNELS_REFRESH,
} from './operator-channels-logic.js';
import { renderProvenanceFooterHTML } from './provenance.js';

/** operator_surface canonical id → display alias (F001 labels are aliases only). */
export const SURFACE_LABELS = Object.freeze({
  terminal: 'Terminal',
  codex_app: 'Codex (app)',
  claude_desktop: 'Claude Desktop',
  claude_dispatch: 'Claude (dispatch)',
  antigravity: 'Antigravity',
  cursor: 'Cursor',
  github_agent_hq: 'GitHub Agent HQ',
  remote_vm: 'Remote VM',
  github_vm: 'GitHub VM',
  unknown_surface: 'Unknown surface',
});

function surfaceLabel(id) {
  return SURFACE_LABELS[id] || id || '—';
}

function renderRecordRowHTML(rec) {
  const surface = surfaceLabel(rec.operator_surface);
  const where = esc(rec.locality || 'unknown_locality');
  const ctx = [rec.branch, rec.plan].filter(Boolean).map(esc).join(' · ');
  return (
    `<li class="channel-row" data-runtime="${esc(rec.agent_runtime || '')}">`
    + `<span class="channel-surface">${esc(surface)}</span>`
    + `<span class="channel-runtime">${esc(rec.agent_runtime || '—')}</span>`
    + `<span class="channel-where">${where}</span>`
    + (ctx ? `<span class="channel-ctx">${ctx}</span>` : '')
    + `</li>`
  );
}

function renderBindingRowHTML(b) {
  return `<li class="channel-row channel-binding"><span class="channel-where">${esc(b.path_display || '')}</span>`
    + `<span class="channel-health">${b.healthy === false ? 'unhealthy' : 'healthy'}</span></li>`;
}

function renderRuntimeRowHTML(rt) {
  return `<li class="channel-row channel-runtime-row"><span class="channel-runtime">${esc(rt.id)}</span>`
    + `<span class="channel-dispatch">${rt.supports_dispatch ? 'dispatchable' : 'not dispatchable'}</span></li>`;
}

function renderMemberHTML(bucketId, member) {
  if (bucketId === 'unhealthy_worktree_binding') return renderBindingRowHTML(member);
  if (bucketId === 'operator_only_runtime_not_dispatchable') return renderRuntimeRowHTML(member);
  return renderRecordRowHTML(member);
}

function renderBucketSectionHTML(bucketId, members) {
  const label = BUCKET_LABELS[bucketId] || bucketId;
  // UNCAPPED — every member renders (no top-N truncation).
  const rows = members.map((m) => renderMemberHTML(bucketId, m)).join('');
  return (
    `<section class="channel-bucket" data-bucket="${esc(bucketId)}">`
    + `<h3 class="channel-bucket-title">${esc(label)} <span class="channel-count">${members.length}</span></h3>`
    + (members.length ? `<ul class="channel-list">${rows}</ul>` : '<p class="channel-empty">none</p>')
    + `</section>`
  );
}

function renderOperatorRoleMatrixHTML(channelView) {
  const matrix = deriveOperatorRoleMatrix(channelView);
  const section = matrix && matrix.operator_roles;
  const entries = (section && section.entries) || [];
  const rows = entries
    .map((e) => `<li class="channel-role-row"><span class="channel-role">${esc(e.role)}</span>`
      + `<span class="channel-role-value">${esc(e.value)}</span>`
      + `<span class="channel-role-scope">${esc(e.scope)}</span></li>`)
    .join('');
  return (
    '<section class="channel-role-matrix" data-section="operator-role-matrix">'
    + '<h3 class="channel-bucket-title">Operator-role preferences <span class="channel-intent">intent only</span></h3>'
    + (entries.length ? `<ul class="channel-list">${rows}</ul>` : '<p class="channel-empty">none</p>')
    + '</section>'
  );
}

/**
 * Render the whole Operator Channels panel. PURE: derives buckets via the F009
 * locked rule matrix and renders them uncapped, plus the operator-role matrix.
 * @param {object} channelView - producer output (operator-channels.json).
 * @param {{now:number}} opts - `now` epoch-ms for the active/stale boundary.
 */
export function renderOperatorChannelsPanelHTML(channelView, { now } = {}) {
  if (!channelView || typeof channelView !== 'object') {
    return '<div class="channel-panel channel-empty">No operator-channels state. Run <code>dontpanic dashboard build</code>.</div>';
  }
  const buckets = deriveBuckets(channelView, { now });
  const sections = BUCKET_IDS.map((id) => renderBucketSectionHTML(id, buckets[id])).join('');
  const provenance = renderProvenanceFooterHTML({
    source: CHANNELS_SOURCE,
    lastUpdated: typeof channelView.generated_at === 'string' ? channelView.generated_at : null,
    refreshCommand: CHANNELS_REFRESH,
  });
  return (
    '<div class="channel-panel" data-panel="operator-channels">'
    + sections
    + renderOperatorRoleMatrixHTML(channelView)
    + provenance
    + '</div>'
  );
}
