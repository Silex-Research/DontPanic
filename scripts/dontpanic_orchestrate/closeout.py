"""Plan 2026-05-11-002 v3 F004 — operator-resolved close-out workflow.

When a volley terminates ``stopped_no_progress`` and the operator judges
the audit finding as non-defect (e.g. ``spec_ambiguity`` from v3 F003),
the close-out path needs three artifacts the operator would otherwise
hand-author:

  1. ``evidence/closeout-memo.md`` — minimal markdown template recording
     ``status: operator_resolved``, the named class, and a summary lifted
     from the latest auditor envelope so the operator's edits start from
     real context.
  2. ``audit/gate-state.json`` clearance of ``breaker:no_progress`` via
     :func:`gate_pause.approve_gate`.
  3. ``audit/signoff-<plan_id>.json`` marking the feature
     ``operator_resolved`` (``signoff: true``, ``next_action: merge``,
     ``signoff_reason`` names the class).

Plus a passes-flip on ``features.json`` so the feature is not re-queued
on the next dispatch.

Transaction order (v3 F004 i1 audit fix): "stage-then-commit". Validation
+ payload construction happens in memory FIRST; nothing touches disk until
the signoff envelope is built and validated. Then on-disk commits run in
this order:

  1. ``evidence/closeout-memo.md``  (rollback: ``unlink`` on later failure)
  2. ``audit/signoff-<plan>.json``  (durable record of operator decision —
     committed BEFORE the breaker is cleared so a mid-transaction crash
     never leaves a cleared breaker without a signoff envelope)
  3. ``audit/gate-state.json``      (``approve_gate`` pops the breaker)
  4. ``features.json``               (passes flip + evidence_refs append)

Re-running ``close --operator-resolved`` on a partially-committed state is
idempotent end-to-end (memo + signoff overwrite, breaker pop is a no-op
when already cleared, features flip is no-op when passes already true).

Design notes:
  * No ``agent-conventions`` schema changes — the existing Signoff
    envelope shape is what we write. The operator-resolved semantics
    live in ``signoff_reason`` + ``next_action``.
  * The class string is validated against the v0 7-class taxonomy
    (the 6 v0 classes + ``spec_ambiguity`` from v3 F003) when supplied
    via the CLI. Other strings raise :class:`CloseoutError`.
  * Refuses to run when ``breaker:no_progress`` is not currently active
    on the plan — defends against operators close-ing a feature that
    didn't actually hit the no-progress terminal. Override path is to
    pop the breaker manually first.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dontpanic_orchestrate import circuit_breakers, gate_pause, signoff_writer

CLOSEOUT_MEMO_RELPATH = Path("evidence") / "closeout-memo.md"


def operator_resolution_path(plan_dir: Path, plan_id: str) -> Path:
    """v3 F004 i1 fix: side-car file recording operator-resolution metadata.

    The Signoff schema has ``extra='forbid'`` so we can't attach
    ``operator_resolution`` directly onto the validated payload. Same idiom
    as ``charter-compliance-{plan_id}.json`` (plan 2026-05-02-003 F002) and
    ``patch_completeness`` (plan 2026-05-01-004 F003) — keep extra blocks in
    sibling files so the canonical envelope stays schema-clean. Downstream
    consumers learn this layout from one place; the auditor's i1 finding
    flagged the original in-band attach as schema-invalid.
    """
    return plan_dir / "audit" / f"operator-resolution-{plan_id}.json"

# v0 7-class taxonomy (auditor_taxonomy.FindingClass). Kept duplicated as a
# frozenset rather than imported so a stray import-time cycle can't break the
# CLI surface; the taxonomy module imports nothing from this one.
KNOWN_CLOSEOUT_CLASSES: frozenset[str] = frozenset(
    {
        "implementation_defect",
        "environmental_reproduction_failure",
        "evidence_shape_disagreement",
        "scope_overreach",
        "spec_ambiguity",
        "unknown",
        # Catch-all for operator-supplied classes outside the v0 taxonomy.
        # Recorded verbatim in the signoff reason; allowed so the CLI
        # surface doesn't get in the operator's way when the volley terminal
        # has no classification at all (zero findings, classifier sidecar
        # missing). Operator types `--reason operator_judgment` and the
        # workflow proceeds.
        "operator_judgment",
    }
)


# Plan 2026-06-02-002 F002 — honest TERMINAL classes for the operator-finish
# close path. Distinct from KNOWN_CLOSEOUT_CLASSES (which are no-progress finding
# classes): these name WHAT terminal the operator is finishing, not a
# classification of an auditor finding. Each carries its own eligibility check
# (see run_operator_finish) so the close cannot be a relabel of an unresolved
# audit:
#   - signed_off_adjacent: auditor signed off but a downstream gate (e.g.
#     patch-completeness on untracked files) blocked the automated finalize.
#     ANTI-BYPASS: refuses unless the latest auditor verdict IS signed_off.
#   - staging_blocked: a recorded downstream-gate block (e.g. patch_completeness
#     fail) is its required evidence.
#   - operator_verified: operator ran their own verification; the rationale note
#     is required and recorded.
TERMINAL_FINISH_CLASSES: frozenset[str] = frozenset(
    {"signed_off_adjacent", "staging_blocked", "operator_verified"}
)


class CloseoutError(RuntimeError):
    """Raised when the close-out workflow cannot proceed safely."""


@dataclass(frozen=True)
class CloseoutResult:
    plan_id: str
    feature_id: str
    reason_class: str
    memo_path: Path
    signoff_path: Path
    breaker_cleared: bool
    features_json_path: Path
    features_passes_flipped: bool


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _audit_paths_for_feature(plan_dir: Path, feature_id: str) -> list[Path]:
    """Return the audit envelope paths for ``feature_id``, in append order
    (implementer-i0, auditor-i0, implementer-i1, auditor-i1, ...).

    Files in ``<plan_dir>/audit/`` follow the
    ``<vendor>-<role>-<feature_id>-i<N>.json`` convention written by
    :mod:`audit_writer`. Patches like ``patch-completeness-*.json`` and
    ``gate-state.json`` are skipped.
    """
    audit_dir = plan_dir / "audit"
    if not audit_dir.is_dir():
        return []
    matches: list[Path] = []
    for p in sorted(audit_dir.iterdir()):
        name = p.name
        if not name.endswith(".json"):
            continue
        if not p.is_file():
            continue
        # File naming: <vendor>-<role>-<feature_id>-i<N>.json. The
        # feature_id segment must match exactly so F001 doesn't pick up
        # F010 envelopes.
        parts = name[:-5].split("-")
        if len(parts) < 4:
            continue
        if feature_id not in parts:
            continue
        # Role must be implementer or auditor — skip patch-completeness etc.
        if not any(p_part in {"implementer", "auditor"} for p_part in parts):
            continue
        matches.append(p)

    # Sort by (iteration, role-precedence) so implementer-iN precedes auditor-iN.
    def _sort_key(path: Path) -> tuple[int, int]:
        stem = path.name[:-5]
        # iteration suffix: last segment is "i<N>".
        iter_seg = stem.rsplit("-", 1)[-1]
        iteration = int(iter_seg[1:]) if iter_seg.startswith("i") and iter_seg[1:].isdigit() else 0
        # implementer (0) before auditor (1).
        role_rank = 0 if "implementer" in stem else 1 if "auditor" in stem else 2
        return (iteration, role_rank)

    matches.sort(key=_sort_key)
    return matches


def _auditor_iteration_of(path: Path) -> int:
    """Parse the ``i<N>`` iteration suffix from an audit envelope filename.
    Returns 0 when the suffix is absent or malformed."""
    stem = path.name[:-5] if path.name.endswith(".json") else path.name
    iter_seg = stem.rsplit("-", 1)[-1]
    return int(iter_seg[1:]) if iter_seg.startswith("i") and iter_seg[1:].isdigit() else 0


def _latest_auditor_envelope(audit_paths: list[Path]) -> dict[str, Any] | None:
    """Return the parsed JSON of the freshest auditor envelope, or None when no
    auditor envelope is present.

    Plan 2026-05-30-002 F002 (D028 fix): rank by modification time (freshest
    wins), with the iteration index as the tie-break. Re-dispatching a feature
    reuses the ``<vendor>-auditor-<FNNN>-iN.json`` filename per iteration, so a
    superseded run with more iterations can leave a STALE higher-index envelope
    on disk. Selecting by iteration index alone (the old ``reversed()`` walk)
    let that stale ``i1 needs_changes`` outrank a fresh ``i0 signed_off``,
    mislabeling ``latest_audit_status`` and refusing a valid finalize.

    The common cases are unchanged: a single envelope returns itself; a
    monotonic run (i0,i1,i2 written in order, so mtime increases with the
    index) still resolves to the highest index. The iteration tie-break keeps
    same-mtime (coarse-filesystem / same-second) writes ranked by index, so a
    true monotonic run is never mis-ordered on a timestamp tie.
    """
    best: dict[str, Any] | None = None
    best_key: tuple[float, int] | None = None
    for path in audit_paths:
        if "auditor" not in path.name:
            continue
        try:
            mtime = path.stat().st_mtime
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        key = (mtime, _auditor_iteration_of(path))
        if best_key is None or key > best_key:
            best_key = key
            best = data
    return best


def _lift_auditor_summary(envelope: dict[str, Any] | None) -> str:
    """Pull a short summary string from the auditor envelope.

    Preference order: ``summary`` field (truncated to 800 chars), then a
    concatenation of finding ``issue`` excerpts, then a generic placeholder.
    """
    if isinstance(envelope, dict):
        summary = envelope.get("summary")
        if isinstance(summary, str) and summary.strip():
            text = summary.strip()
            if len(text) > 800:
                text = text[:797] + "..."
            return text
        findings = envelope.get("findings")
        if isinstance(findings, list) and findings:
            parts: list[str] = []
            for f in findings[:5]:
                if isinstance(f, dict):
                    issue = f.get("issue")
                    if isinstance(issue, str) and issue.strip():
                        parts.append(f"- {issue.strip()}")
            if parts:
                return "Latest auditor findings:\n" + "\n".join(parts)
    return "(no auditor envelope summary available — operator should fill in)"


def render_closeout_memo(
    *,
    plan_id: str,
    feature_id: str,
    reason_class: str,
    auditor_envelope: dict[str, Any] | None,
    captured_at: str | None = None,
    status_label: str = "operator_resolved",
    decision_paragraph: str | None = None,
) -> str:
    """Pure renderer — returns the closeout-memo template body. Used by
    :func:`run_close_out` and by tests that pin the template shape.

    ``decision_paragraph`` (Plan 2026-06-02-002 F002): when supplied, replaces
    the default ``## Operator decision`` paragraph. The default paragraph
    describes a ``stopped_no_progress`` review + ``breaker:no_progress``
    clearance; the operator-finish close path passes a terminal-class-specific
    paragraph so the memo records the ACTUAL terminal (signed_off_adjacent /
    staging_blocked / operator_verified) instead of a no-progress pretence.
    ``status_label`` overrides the frontmatter ``status:`` line for the same
    reason."""
    captured = captured_at or _now_iso()
    auditor_status = "unknown"
    auditor_path_hint = "(latest auditor envelope not located)"
    if isinstance(auditor_envelope, dict):
        status = auditor_envelope.get("audit_status")
        if isinstance(status, str):
            auditor_status = status
        # We don't carry the path through to here; keep the hint generic so
        # callers can attach the real path if they want.
    summary = _lift_auditor_summary(auditor_envelope)
    default_paragraph = (
        f"This feature was closed under class `{reason_class}` after operator "
        f"review of a `stopped_no_progress` terminal. The audit finding is "
        f"recorded as non-defect; the close-out workflow generated this "
        f"template, cleared `breaker:no_progress`, wrote the signoff "
        f"envelope, and flipped `features.json` `passes: true` for this "
        f"feature."
    )
    lines = [
        "---",
        f"status: {status_label}",
        f"reason_class: {reason_class}",
        f"plan_id: {plan_id}",
        f"feature_id: {feature_id}",
        f"closed_at: {captured}",
        f"latest_audit_status: {auditor_status}",
        "---",
        "",
        f"# Closeout memo — {plan_id} / {feature_id}",
        "",
        "## Operator decision",
        "",
        decision_paragraph or default_paragraph,
        "",
        "## Latest auditor envelope summary (lifted automatically)",
        "",
        summary,
        "",
        "## Rationale (operator — fill in)",
        "",
        "<!--",
        "Explain in 2-4 sentences:",
        "  - Why the finding does not warrant a re-dispatch.",
        "  - What spec/doc/convention change (if any) should follow to",
        "    prevent the same friction next time.",
        "  - Any follow-up tickets, plan IDs, or D-entries to file.",
        "-->",
        "",
        "## Evidence references",
        "",
        f"- `audit/signoff-{plan_id}.json`",
        f"- `{auditor_path_hint}`",
        "",
    ]
    return "\n".join(lines) + "\n"


def _flip_feature_passes(
    plan_dir: Path,
    feature_id: str,
    *,
    reason_class: str,
    memo_relpath: str,
    extra_refs: list[dict[str, Any]] | None = None,
) -> tuple[Path, bool]:
    """Set ``passes: true`` for the matching feature in ``features.json``.

    Returns (path, changed) so callers can report whether the file was
    actually mutated. Idempotent — re-running on an already-flipped feature
    is a no-op. Preserves any pre-existing ``evidence_refs`` and appends a
    new entry pointing at the closeout memo (de-duplicated by uri).

    ``extra_refs`` lets callers append additional evidence refs (each a dict
    with at least a ``uri``) alongside the memo ref — e.g. the no-paid
    finalizer cites the signed_off auditor envelope so the flip points at the
    artifact that authorized it (F007 AC9). De-duplicated by uri like the memo.
    """
    features_json = plan_dir / "features.json"
    if not features_json.is_file():
        raise CloseoutError(f"features.json not found at {features_json}")
    data = json.loads(features_json.read_text())
    features = data.get("features")
    if not isinstance(features, list):
        raise CloseoutError(f"features.json missing a `features` array: {features_json}")

    target_idx: int | None = None
    for i, f in enumerate(features):
        if isinstance(f, dict) and f.get("id") == feature_id:
            target_idx = i
            break
    if target_idx is None:
        raise CloseoutError(
            f"feature {feature_id!r} not found in {features_json} "
            f"(available: {[f.get('id') for f in features if isinstance(f, dict)]})"
        )

    feature = features[target_idx]
    changed = False
    if not feature.get("passes"):
        feature["passes"] = True
        changed = True

    # Append the closeout-memo evidence ref unless already present.
    refs = feature.get("evidence_refs") or []
    if not isinstance(refs, list):
        refs = []
    memo_uri = memo_relpath
    if not any(isinstance(r, dict) and r.get("uri") == memo_uri for r in refs):
        refs.append(
            {
                "type": "file",
                "uri": memo_uri,
                "note": f"operator_resolved close-out (class={reason_class})",
            }
        )
        feature["evidence_refs"] = refs
        changed = True
    elif feature.get("evidence_refs") is None:
        feature["evidence_refs"] = refs

    # Append any caller-supplied evidence refs (e.g. the signed_off auditor
    # envelope) unless an entry with the same uri already exists.
    for ref in extra_refs or []:
        if not isinstance(ref, dict) or not ref.get("uri"):
            continue
        if any(isinstance(r, dict) and r.get("uri") == ref["uri"] for r in refs):
            continue
        refs.append(ref)
        feature["evidence_refs"] = refs
        changed = True

    if not feature.get("verified_by"):
        feature["verified_by"] = ["operator"]
        changed = True
    elif "operator" not in feature["verified_by"]:
        feature["verified_by"].append("operator")
        changed = True
    if not feature.get("verified_at"):
        feature["verified_at"] = _now_iso()
        changed = True

    if changed:
        features_json.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n"
        )
    return features_json, changed


def _build_operator_signoff(
    *,
    plan_id: str,
    feature_id: str,
    reason_class: str,
    audit_paths: list[Path],
    plan_dir: Path,
    tier: str,
    agents_in_panel: list[str],
    iteration: int,
) -> dict[str, Any]:
    """Wrap :func:`signoff_writer.build_signoff_dict` with operator-resolved
    semantics: ``signoff: true`` (operator accepted the feature),
    ``next_action: merge``, and a ``signoff_reason`` that names the class so
    a downstream reader can tell apart operator close-out from auditor
    signoff at a glance."""
    if not audit_paths:
        # Synthesize a placeholder audit path so signoff schema validation
        # passes. We point at the closeout memo (relative URI), which the
        # schema accepts as a path-string.
        raise CloseoutError(
            "no audit envelopes found for feature — cannot write signoff "
            "envelope. Run at least one volley round first or hand-author."
        )

    signoff_reason = (
        f"operator_resolved (class={reason_class}): operator accepted the "
        f"stopped_no_progress terminal as non-defect after review. "
        f"See {CLOSEOUT_MEMO_RELPATH} for rationale."
    )
    # build_signoff_dict consults volley_status for the next_action mapping.
    # We pass "signed_off" so next_action resolves to "merge" — matches the
    # operator-resolved semantics (feature is accepted, ready to merge).
    payload = signoff_writer.build_signoff_dict(
        plan_id=plan_id,
        tier=tier,
        iteration=iteration,
        agents_in_panel=agents_in_panel,
        audit_paths=audit_paths,
        plan_dir=plan_dir,
        volley_status="signed_off",
        signoff_reason=signoff_reason,
    )
    return payload


def _build_operator_resolution_sidecar(
    *,
    plan_id: str,
    feature_id: str,
    reason_class: str,
) -> dict[str, Any]:
    """v3 F004 i1 fix: operator_resolution sidecar payload.

    Separate file so the Signoff envelope stays schema-clean (extra='forbid').
    Same pattern as charter-compliance-{plan_id}.json. Plan_id is implicit
    in the file path; feature_id + class + memo path are the only fields
    downstream consumers need to tell apart operator-resolved from auditor-
    signed-off close-out.
    """
    return {
        "plan_id": plan_id,
        "feature_id": feature_id,
        "class": reason_class,
        "memo": str(CLOSEOUT_MEMO_RELPATH),
        "resolved": True,
        "resolved_at": _now_iso(),
    }


def run_close_out(
    *,
    plan_dir: Path,
    plan_id: str,
    feature_id: str,
    reason_class: str,
    tier: str,
    agents_in_panel: list[str],
    require_active_breaker: bool = True,
) -> CloseoutResult:
    """Execute the close-out workflow end-to-end. Raises
    :class:`CloseoutError` on any safety check failure (unknown class,
    missing feature, no audit history, missing breaker — when
    ``require_active_breaker`` is True).

    Side effects, in order (stage-then-commit; see module docstring):
      1. Validate inputs (class, feature exists, audit history present).
      2. Build + validate the signoff payload in memory (pure — raises
         :class:`signoff_writer.SignoffWriteError` on validation drift
         without touching disk).
      3. Write ``evidence/closeout-memo.md`` template (mkdir as needed).
      4. Write the operator-resolved signoff envelope.
      5. Clear ``breaker:no_progress`` (idempotent — no-op if not active
         and ``require_active_breaker`` is False). Comes AFTER the signoff
         envelope is durable so a crash here never produces a
         cleared-breaker-without-signoff state (high finding from v3 F004
         i0 audit).
      6. Flip ``features.json`` ``passes: true`` + append a memo
         evidence ref.
    """
    if reason_class not in KNOWN_CLOSEOUT_CLASSES:
        raise CloseoutError(
            f"unknown reason class {reason_class!r}; valid classes: "
            f"{sorted(KNOWN_CLOSEOUT_CLASSES)}. Use the v0 7-class "
            f"taxonomy or 'operator_judgment' for free-form."
        )

    audit_paths = _audit_paths_for_feature(plan_dir, feature_id)
    if not audit_paths:
        raise CloseoutError(
            f"no audit envelopes found for feature {feature_id!r} in "
            f"{plan_dir / 'audit'}. The close-out workflow requires at "
            f"least one volley round so the signoff envelope can cite "
            f"audit history."
        )

    # Safety check: refuse to close-out a feature whose breaker isn't
    # currently active. Defends against operators close-ing a feature that
    # didn't actually hit no_progress.
    breaker_gate = circuit_breakers.gate_name(circuit_breakers.BreakerKind.NO_PROGRESS)
    active_breakers = set(gate_pause.active_breakers(plan_dir))
    breaker_active = breaker_gate in active_breakers
    if require_active_breaker and not breaker_active:
        raise CloseoutError(
            f"breaker {breaker_gate!r} is not currently active for {plan_id} "
            f"(active breakers: {sorted(active_breakers) or '[]'}). The "
            f"close-out workflow only runs when the no_progress breaker "
            f"tripped; manually clear the breaker first if you want to "
            f"close-out without the safety check."
        )

    auditor_envelope = _latest_auditor_envelope(audit_paths)

    # Step 2 — STAGE: build + validate the signoff payload in memory before
    # any side effect. _build_operator_signoff calls signoff_writer's
    # Pydantic validator; an invalid payload raises SignoffWriteError BEFORE
    # the memo or any state file is touched. (v3 F004 i0 high finding.)
    iteration = max(
        0,
        len([p for p in audit_paths if "auditor" in p.name]) - 1,
    )
    payload = _build_operator_signoff(
        plan_id=plan_id,
        feature_id=feature_id,
        reason_class=reason_class,
        audit_paths=audit_paths,
        plan_dir=plan_dir,
        tier=tier,
        agents_in_panel=agents_in_panel,
        iteration=iteration,
    )
    memo_body = render_closeout_memo(
        plan_id=plan_id,
        feature_id=feature_id,
        reason_class=reason_class,
        auditor_envelope=auditor_envelope,
    )
    signoff_path = signoff_writer.signoff_path(plan_dir, plan_id)
    memo_path = plan_dir / CLOSEOUT_MEMO_RELPATH
    resolution_path = operator_resolution_path(plan_dir, plan_id)
    resolution_payload = _build_operator_resolution_sidecar(
        plan_id=plan_id,
        feature_id=feature_id,
        reason_class=reason_class,
    )

    # Step 3 — COMMIT closeout memo. Cheapest to roll back if a later step
    # fails (a single unlink). Overwrite if present so re-runs get a fresh
    # template.
    memo_path.parent.mkdir(parents=True, exist_ok=True)
    memo_path.write_text(memo_body)

    # Step 4 — COMMIT signoff envelope. Durable record of the operator
    # decision; MUST land on disk before the breaker is cleared so a crash
    # between these two writes never leaves a cleared-breaker-without-
    # signoff state. On OSError, roll back the memo so the operator's next
    # invocation is not staring at a stale template with no signoff peer.
    signoff_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        signoff_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
        )
    except OSError:
        memo_path.unlink(missing_ok=True)
        raise

    # Step 4b — COMMIT operator_resolution sidecar (v3 F004 i1 fix). The
    # Signoff schema has extra='forbid' so this metadata cannot ride along
    # in the validated envelope; instead it lives in audit/operator-
    # resolution-{plan_id}.json (same idiom as charter-compliance-{plan_id}).
    # Rollback both signoff + memo on failure so the operator never sees a
    # half-written closeout state.
    try:
        resolution_path.write_text(
            json.dumps(resolution_payload, indent=2, ensure_ascii=False) + "\n"
        )
    except OSError:
        signoff_path.unlink(missing_ok=True)
        memo_path.unlink(missing_ok=True)
        raise

    # Step 5 — COMMIT breaker clearance. approve_gate returns False when the
    # breaker isn't active; treat that as a non-error (require_active_breaker
    # is False here when the safety check is disabled).
    breaker_cleared = False
    if breaker_active:
        try:
            breaker_cleared = gate_pause.approve_gate(
                plan_dir,
                breaker_gate,
                plan_id=plan_id,
                actor="operator",
            )
        except Exception:
            # Signoff is the durable artifact and is intentionally LEFT in
            # place — re-running close --operator-resolved is idempotent and
            # will re-attempt the breaker clear. We only roll back the memo
            # so the operator doesn't see a stale rationale section.
            raise

    # Step 6 — COMMIT features.json passes flip + evidence ref. Last in
    # the chain; a failure here leaves the breaker cleared + signoff
    # written. Re-run with --allow-missing-breaker recovers.
    features_json_path, features_changed = _flip_feature_passes(
        plan_dir,
        feature_id,
        reason_class=reason_class,
        memo_relpath=str(CLOSEOUT_MEMO_RELPATH),
    )

    return CloseoutResult(
        plan_id=plan_id,
        feature_id=feature_id,
        reason_class=reason_class,
        memo_path=memo_path,
        signoff_path=signoff_path,
        breaker_cleared=breaker_cleared,
        features_json_path=features_json_path,
        features_passes_flipped=features_changed,
    )


def _latest_auditor_verdict(audit_paths: list[Path]) -> str | None:
    """Return the latest auditor envelope's verdict string (``audit_status``),
    or None when no auditor envelope is present."""
    env = _latest_auditor_envelope(audit_paths)
    if not isinstance(env, dict):
        return None
    status = env.get("audit_status")
    return status if isinstance(status, str) else None


def _recorded_gate_block(plan_dir: Path) -> str | None:
    """Plan 2026-06-02-002 F002 — find a recorded downstream-gate block to use
    as staging_blocked evidence. Returns a short evidence descriptor (the
    artifact relpath) when a ``patch-completeness-*.json`` artifact reports a
    ``fail`` status, else None. This keeps staging_blocked honest: it cannot be
    claimed without an on-disk gate block."""
    audit_dir = plan_dir / "audit"
    if not audit_dir.is_dir():
        return None
    for p in sorted(audit_dir.glob("patch-completeness-*.json")):
        try:
            data = json.loads(p.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict) and data.get("status") == "fail":
            return f"audit/{p.name}"
    return None


def _operator_finish_signoff_reason(
    *, terminal_class: str, evidence: str | None, note: str | None
) -> str:
    """Honest signoff_reason naming the ACTUAL terminal class (F002 acceptance
    #4) — never a stopped_no_progress pretence."""
    memo = CLOSEOUT_MEMO_RELPATH
    if terminal_class == "signed_off_adjacent":
        return (
            "operator_finish (terminal=signed_off_adjacent): the auditor signed "
            "off; a downstream gate blocked the automated finalize. Operator "
            f"accepted the feature as merge-ready. See {memo}."
        )
    if terminal_class == "staging_blocked":
        return (
            "operator_finish (terminal=staging_blocked): blocked by a recorded "
            f"downstream gate ({evidence}). Operator accepted as ready-to-stage. "
            f"See {memo}."
        )
    # operator_verified
    return (
        "operator_finish (terminal=operator_verified): operator verified the "
        f"feature out-of-band — {note}. See {memo}."
    )


def _operator_finish_decision_paragraph(
    *, terminal_class: str, reason: str
) -> str:
    """Memo ## Operator decision paragraph naming the terminal class. Echoes the
    signoff_reason so the memo and envelope agree; explicitly avoids any
    no-progress / breaker:no_progress language (F002 acceptance #4)."""
    return (
        f"This feature was finished under terminal class `{terminal_class}` via "
        f"the operator-finish close path (no re-dispatch, no breaker required). "
        f"{reason} The close wrote the signoff envelope, recorded the terminal "
        f"class in the operator-resolution sidecar, and flipped `features.json` "
        f"`passes: true` for this feature."
    )


def run_operator_finish(
    *,
    plan_dir: Path,
    plan_id: str,
    feature_id: str,
    terminal_class: str,
    tier: str,
    agents_in_panel: list[str],
    note: str | None = None,
) -> CloseoutResult:
    """Plan 2026-06-02-002 F002 — first-class operator-finish close for honest
    terminal classes (signed_off_adjacent / staging_blocked / operator_verified).

    Unlike :func:`run_close_out` (which is bound to the stopped_no_progress
    terminal + ``breaker:no_progress``), this path:
      * does NOT require ``breaker:no_progress`` to be active;
      * applies a per-class eligibility gate so the close cannot be a relabel of
        an unresolved audit (anti-bypass);
      * writes a signoff_reason + memo naming the ACTUAL terminal class;
      * performs no paid agent dispatch (reads on-disk envelopes, writes files).

    Eligibility per class:
      * ``signed_off_adjacent`` — the latest auditor envelope's verdict must be
        ``signed_off`` (else :class:`CloseoutError`).
      * ``staging_blocked`` — a recorded downstream-gate block
        (``patch-completeness-*.json`` with ``status: fail``) must exist.
      * ``operator_verified`` — a non-empty ``note`` (operator rationale) is
        required.

    Commit order mirrors :func:`run_close_out` (stage-then-commit): validate +
    build payload in memory, then memo → signoff → resolution sidecar →
    (idempotent breaker clear if somehow active) → features.json flip.
    """
    if terminal_class not in TERMINAL_FINISH_CLASSES:
        raise CloseoutError(
            f"unknown terminal class {terminal_class!r}; valid operator-finish "
            f"classes: {sorted(TERMINAL_FINISH_CLASSES)}. For a "
            f"stopped_no_progress close use the no-progress taxonomy via "
            f"run_close_out."
        )

    audit_paths = _audit_paths_for_feature(plan_dir, feature_id)
    if not audit_paths:
        raise CloseoutError(
            f"no audit envelopes found for feature {feature_id!r} in "
            f"{plan_dir / 'audit'}. The operator-finish close requires at least "
            f"one volley round so the signoff envelope can cite audit history."
        )

    # Per-class eligibility (anti-bypass).
    evidence: str | None = None
    if terminal_class == "signed_off_adjacent":
        verdict = _latest_auditor_verdict(audit_paths)
        if verdict != "signed_off":
            raise CloseoutError(
                f"signed_off_adjacent refused: the latest auditor verdict is "
                f"{verdict!r}, not 'signed_off'. This terminal class cannot "
                f"relabel a needs_changes / failed audit as operator-resolved. "
                f"Use staging_blocked or operator_verified, or re-dispatch."
            )
    elif terminal_class == "staging_blocked":
        evidence = _recorded_gate_block(plan_dir)
        if evidence is None:
            raise CloseoutError(
                "staging_blocked refused: no recorded downstream-gate block "
                "(expected a patch-completeness-*.json artifact with "
                "status='fail') found under audit/. staging_blocked requires "
                "on-disk gate evidence."
            )
    else:  # operator_verified
        if not (isinstance(note, str) and note.strip()):
            raise CloseoutError(
                "operator_verified refused: a non-empty --note rationale is "
                "required (record what was verified and why the terminal is "
                "non-defect)."
            )

    signoff_reason = _operator_finish_signoff_reason(
        terminal_class=terminal_class, evidence=evidence, note=note
    )
    decision_paragraph = _operator_finish_decision_paragraph(
        terminal_class=terminal_class, reason=signoff_reason
    )

    # STAGE: build + validate the signoff payload in memory before any side
    # effect (mirrors run_close_out; an invalid payload raises before disk).
    iteration = max(0, len([p for p in audit_paths if "auditor" in p.name]) - 1)
    payload = signoff_writer.build_signoff_dict(
        plan_id=plan_id,
        tier=tier,
        iteration=iteration,
        agents_in_panel=agents_in_panel,
        audit_paths=audit_paths,
        plan_dir=plan_dir,
        volley_status="signed_off",
        signoff_reason=signoff_reason,
    )
    auditor_envelope = _latest_auditor_envelope(audit_paths)
    memo_body = render_closeout_memo(
        plan_id=plan_id,
        feature_id=feature_id,
        reason_class=terminal_class,
        auditor_envelope=auditor_envelope,
        status_label="operator_finished",
        decision_paragraph=decision_paragraph,
    )
    resolution_payload = _build_operator_resolution_sidecar(
        plan_id=plan_id, feature_id=feature_id, reason_class=terminal_class
    )
    resolution_payload["terminal_class"] = terminal_class
    if note is not None:
        resolution_payload["note"] = note
    if evidence is not None:
        resolution_payload["evidence"] = evidence

    memo_path = plan_dir / CLOSEOUT_MEMO_RELPATH
    signoff_path = signoff_writer.signoff_path(plan_dir, plan_id)
    resolution_path = operator_resolution_path(plan_dir, plan_id)

    # COMMIT memo → signoff → resolution sidecar (roll back on OSError).
    memo_path.parent.mkdir(parents=True, exist_ok=True)
    memo_path.write_text(memo_body)
    signoff_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        signoff_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    except OSError:
        memo_path.unlink(missing_ok=True)
        raise
    try:
        resolution_path.write_text(
            json.dumps(resolution_payload, indent=2, ensure_ascii=False) + "\n"
        )
    except OSError:
        signoff_path.unlink(missing_ok=True)
        memo_path.unlink(missing_ok=True)
        raise

    # Idempotent breaker clear: operator-finish does NOT require the breaker, but
    # if a no_progress breaker happens to be active, clear it so the plan's
    # gate-state doesn't keep blocking dispatch after the feature is finished.
    breaker_gate = circuit_breakers.gate_name(circuit_breakers.BreakerKind.NO_PROGRESS)
    breaker_cleared = False
    if breaker_gate in set(gate_pause.active_breakers(plan_dir)):
        breaker_cleared = gate_pause.approve_gate(
            plan_dir, breaker_gate, plan_id=plan_id, actor="operator"
        )

    features_json_path, features_changed = _flip_feature_passes(
        plan_dir,
        feature_id,
        reason_class=terminal_class,
        memo_relpath=str(CLOSEOUT_MEMO_RELPATH),
    )

    return CloseoutResult(
        plan_id=plan_id,
        feature_id=feature_id,
        reason_class=terminal_class,
        memo_path=memo_path,
        signoff_path=signoff_path,
        breaker_cleared=breaker_cleared,
        features_json_path=features_json_path,
        features_passes_flipped=features_changed,
    )


def format_no_progress_close_hint(
    *, plan_id: str, feature_id: str, recommended_class: str | None
) -> str:
    """Render the operator-facing hint block appended to the
    ``no_progress_classification`` INBOX event. Recommended class is the
    aggregate taxonomy class from auditor_taxonomy (passed by the
    supervisor); ``None`` falls back to a placeholder."""
    class_token = recommended_class or "<class>"
    return (
        "\n\n"
        "To close-out this feature without a re-dispatch (operator accepts "
        "the finding as non-defect):\n"
        f"  dontpanic close --operator-resolved "
        f"{plan_id} {feature_id} --reason {class_token}\n"
        "\n"
        "This generates a closeout-memo template at "
        f"{CLOSEOUT_MEMO_RELPATH}, clears breaker:no_progress, writes the "
        "signoff envelope, and flips features.json passes:true — all in one "
        "transaction."
    )


__all__ = [
    "CLOSEOUT_MEMO_RELPATH",
    "CloseoutError",
    "CloseoutResult",
    "KNOWN_CLOSEOUT_CLASSES",
    "TERMINAL_FINISH_CLASSES",
    "format_no_progress_close_hint",
    "operator_resolution_path",
    "render_closeout_memo",
    "run_close_out",
    "run_operator_finish",
]
