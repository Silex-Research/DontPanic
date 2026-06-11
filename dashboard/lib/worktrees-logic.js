// ── DontPanic — Active Worktrees rendering (Worktree Isolation v0 F007) ──
// Pure render logic for the worktree-status MODEL (state.activeWorktrees —
// the SAME model `dontpanic plan worktree list` and the operator brief
// render: one model, three renderers). Honest by construction:
//   • unhealthy bindings show their health reason with dirty/untracked as
//     "unknown" (the model carries explicit nulls — never fabricated false/0)
//   • branch drift shows BOTH the recorded branch and the current branch
//   • a corrupt registry renders a visible warning, never a silent empty list
//   • no bindings renders an honest empty state

function esc(value) {
  return String(value == null ? '' : value)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

export function deriveWorktreesView(model) {
  if (!model || typeof model !== 'object') {
    return { missing: true, registryCorrupt: false, rows: [] };
  }
  const rows = (Array.isArray(model.bindings) ? model.bindings : []).map((b) => ({
    planId: b.plan_id,
    branch: b.branch,
    currentBranch: b.current_branch,
    drifted: b.current_branch != null && b.current_branch !== b.branch,
    healthy: b.healthy === true,
    healthReason: b.health_reason || null,
    // explicit null = unknown (unhealthy binding) — render as "unknown",
    // never as a fabricated false/zero
    dirty: b.dirty,
    untrackedCount: b.untracked_count,
    ownerActor: b.owner_actor,
    worktreePath: b.worktree_path,
  }));
  return { missing: false, registryCorrupt: model.registry_corrupt === true, rows };
}

export function renderWorktreesHTML(model) {
  const view = deriveWorktreesView(model);
  const parts = ['<section class="active-worktrees" data-testid="active-worktrees">'];
  parts.push('<h3 class="aw-title">Active worktrees</h3>');
  if (view.missing) {
    parts.push(
      '<p class="aw-empty" data-testid="aw-missing">No worktree state — run ' +
      '<code>dontpanic dashboard build</code>.</p></section>'
    );
    return parts.join('');
  }
  if (view.registryCorrupt) {
    parts.push(
      '<p class="aw-warning" data-testid="aw-registry-corrupt">⚠ Worktree registry is ' +
      'CORRUPT — bindings below may be incomplete. Fix or remove the registry file.</p>'
    );
  }
  if (!view.rows.length) {
    if (!view.registryCorrupt) {
      parts.push('<p class="aw-empty" data-testid="aw-empty">No active worktrees.</p>');
    }
    parts.push('</section>');
    return parts.join('');
  }
  parts.push('<ul class="aw-list">');
  for (const r of view.rows) {
    const dirty = r.dirty == null ? 'unknown' : String(r.dirty);
    const untracked = r.untrackedCount == null ? 'unknown' : String(r.untrackedCount);
    const branch = r.drifted
      ? `${esc(r.branch)} <span class="aw-drift" data-testid="aw-drift">→ on ${esc(r.currentBranch)}</span>`
      : esc(r.branch);
    const health = r.healthy
      ? `<span class="aw-state">dirty=${esc(dirty)} · untracked=${esc(untracked)}</span>`
      : `<span class="aw-unhealthy" data-testid="aw-unhealthy">UNHEALTHY: ${esc(r.healthReason)}` +
        ` (dirty=${esc(dirty)} · untracked=${esc(untracked)})</span>`;
    parts.push(
      `<li class="aw-row" data-testid="aw-row" data-plan-id="${esc(r.planId)}">` +
      `<span class="aw-plan">${esc(r.planId)}</span> ` +
      `<span class="aw-branch">${branch}</span> ${health} ` +
      `<span class="aw-owner">${esc(r.ownerActor)}</span> ` +
      `<span class="aw-path">${esc(r.worktreePath)}</span></li>`
    );
  }
  parts.push('</ul></section>');
  return parts.join('');
}
