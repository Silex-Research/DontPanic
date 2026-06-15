"""argparse entry for `python -m dontpanic_orchestrate`.

Single-agent dispatch (F004):
  python -m dontpanic_orchestrate <plan-id> [--feature F001] [--role implementer]

Volley dispatch (F005a — implementer/auditor pair, iterate until signoff or cap):
  python -m dontpanic_orchestrate <plan-id> --volley [--feature F001]
                                                  [--implementer claude] [--auditor codex]
                                                  [--max-iterations 3]
                                                  [--mode interactive|p0|autonomous]

Pre-flight + dispatch (plan 2026-05-01-001 F002):
  python -m dontpanic_orchestrate dispatch-from-plan <plan-id>
      [--feature F001] [--implementer claude] [--auditor codex]
      [--max-iterations N] [--mode interactive|autonomous] [--confirm]

  Strict dry-run by default: prints a 10-field pre-flight context block and
  exits 0 without dispatching, regardless of TTY state. With `--confirm`,
  validates quota readiness == ok and calls supervisor.dispatch_volley
  in-process. Blocking readiness states each exit 3 with a kind-specific
  remediation pointer:
    config_required        → `python -m dontpanic_orchestrate quota-caps init`
    calibration_required   → `python -m dontpanic_orchestrate calibrate-claude`
    unit_mismatch          → edit ~/.jarvis/quota_caps.json
    missing_state          → `python scripts/quota_check.py`

Active-supervisor registry (F023 EC13):
  python -m dontpanic_orchestrate ps

Engagement-surface gate handling (F008 + F006 + F007):
  python -m dontpanic_orchestrate approve <plan-id> <gate>      # preferred — clear one declared gate
  python -m dontpanic_orchestrate resume  <plan-id> --gate <gate>  # parity alias for approve
  python -m dontpanic_orchestrate resume  <plan-id> --all       # explicit bulk-clear (legacy behavior)

Interactive backoff touch (F007 Slice 2):
  python -m dontpanic_orchestrate claude-touch               # record human Claude request now

Operator quota caps (plan 2026-04-30-001 F004):
  python -m dontpanic_orchestrate quota-caps init [--overwrite]
  python -m dontpanic_orchestrate quota-caps show

Claude calibration (plan 2026-04-30-001 F005):
  python -m dontpanic_orchestrate calibrate-claude --dashboard-pct N [--window rolling_7d|rolling_5h]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from dontpanic_orchestrate import (
    active_supervisors,
    agent_manifest,
    calibration_loader,
    closeout,
    completion_gate,
    gate_pause,
    git_state,
    inbox,
    interactive_state,
    mcp_server,
    nested_orchestration,
    patch_completeness_gate,
    plan_drift,
    plan_loader,
    project_config,
    projects_registry,
    quota_admission,
    quota_caps_loader,
    release_impact,
    repo_onboarding,
    skill_applicability,
    sufficiency_gate,
    supervisor,
)
from dontpanic_orchestrate import (
    circuit_breakers as cb,
)
from dontpanic_orchestrate.patch_completeness_gate import (
    MIN_REASON_LEN as _PATCH_MIN_REASON_LEN,
)
from dontpanic_orchestrate.patch_completeness_gate import (
    PatchCompletenessError,
)
from dontpanic_orchestrate.supervisor import QuotaExceeded


def _validate_patch_reason(flag: str):
    """Argparse layer-A validator factory for the F003 override flags.

    Returns a callable suitable for ``add_argument(type=...)`` that raises
    ``argparse.ArgumentTypeError`` with a remediation message on values
    shorter than ``MIN_REASON_LEN`` non-whitespace chars. The patch_
    completeness_gate.validate_reason() function re-checks at layer B
    (defense-in-depth) when the supervisor consumes the flag.
    """

    def _coerce(value: str) -> str:
        if not isinstance(value, str):
            raise argparse.ArgumentTypeError(
                f"{flag} reason must be a string; got {type(value).__name__}"
            )
        stripped = value.strip()
        if len(stripped) < _PATCH_MIN_REASON_LEN:
            raise argparse.ArgumentTypeError(
                f"{flag} reason must be at least {_PATCH_MIN_REASON_LEN} non-whitespace "
                f"characters; got {len(stripped)} ({value!r}). Provide a substantive "
                "operator note explaining why the patch surface is allowed to ship "
                "with this gap."
            )
        return value

    return _coerce


def _resolve_plan_dir(plan_arg: str) -> Path:
    """Resolve a plan ID (or absolute dir path) to a plan directory.

    Plan 2026-05-03-001 F003: when no direct path match, consult registered
    projects (via ``project_config.find_project_for_plan_dir`` for cwd
    awareness, then fall back to walking every registered project) and
    honor each project's per-project ``plans_dir`` from its
    ``.dontpanic/dontpanic.json`` (legacy ``.jarvis/jarvis.json`` fallback).
    Default ``plans_dir`` remains ``docs/plans``
    when the per-project config is missing or doesn't override it.

    Resolution order (first match wins):
      1. plan_arg as a literal path that resolves to a directory
      2. cwd is under a registered project AND
         ``<project>/<project_plans_dir>/<plan_arg>`` exists
      3. for any registered project R,
         ``<R.path>/<R_plans_dir>/<plan_arg>`` exists (depth-first)
      4. ``<cwd>/docs/plans/<plan_arg>`` (legacy fallback for un-registered
         operators — keeps the bare ``jarvis`` smoke-test usable from the
         repo root before any registry entry exists)

    Refuses with ``SystemExit`` (mapped to exit 2 by argparse + main()
    callers) when nothing matches. There is no ``Path.cwd()`` fallback
    that silently picks up a stray plan dir from the wrong project.
    """
    p = Path(plan_arg)
    if p.is_dir():
        return p

    # Step 2: cwd-anchored project context. The supervisor consults the same
    # helper to pick per-project agent/gate defaults; using it here keeps
    # plan resolution + dispatch defaults grounded in the same project.
    cwd = Path.cwd().resolve()
    cwd_project = project_config.find_project_for_plan_dir(cwd)
    if cwd_project is not None:
        cwd_proj_path = cwd_project[0]
        cfg = project_config.load_project_config(cwd_proj_path)
        plans_dir = cfg.plans_dir if cfg is not None else project_config.DEFAULT_PLANS_DIR
        candidate = cwd_proj_path / plans_dir / plan_arg
        if candidate.is_dir():
            return candidate.resolve()

    # Step 3: walk every registered project. Honors each project's own
    # plans_dir override so a multi-repo registry (e.g. one repo authoring
    # plans under `plans/`, another under `docs/plans/`) all work.
    reg = projects_registry.load_registry()
    for entry in reg.projects:
        proj_path = Path(entry.path).expanduser().resolve()
        cfg = project_config.load_project_config(proj_path)
        plans_dir = cfg.plans_dir if cfg is not None else project_config.DEFAULT_PLANS_DIR
        candidate = proj_path / plans_dir / plan_arg
        if candidate.is_dir():
            return candidate.resolve()

    # Step 4: legacy cwd fallback. Only the hardcoded `docs/plans` path —
    # callers running from un-registered repos still get the historical
    # behavior. NOT a `Path.cwd()` bare fallback — the per-project plans_dir
    # only applies when a registered project resolves.
    cwd_match = Path.cwd() / "docs" / "plans" / plan_arg
    if cwd_match.is_dir():
        return cwd_match
    raise SystemExit(f"plan not found: {plan_arg}")


def _resolve_default_actions_plan_dir() -> Path | None:
    """Best-effort cwd-anchored default plan for the ``agent brief`` actions block.

    Plan 2026-06-02-001 F003: the agent-brief surface renders the managed
    ActionItem block by default. With no explicit ``--actions PLAN`` the plan is
    resolved here — the cwd project's most-recent (lexicographically-greatest,
    i.e. latest date-prefixed) plan directory that still has at least one
    in-flight feature (``passes`` != ``true``), or ``None`` when no project/plan
    resolves. Fully guarded — never raises — so the default brief path stays
    robust even on an un-registered repo or unreadable plan metadata."""
    try:
        cwd = Path.cwd().resolve()
        match = project_config.find_project_for_plan_dir(cwd)
        if match is None:
            return None
        proj_path = match[0]
        cfg = project_config.load_project_config(proj_path)
        plans_dir = cfg.plans_dir if cfg is not None else project_config.DEFAULT_PLANS_DIR
        root = proj_path / plans_dir
        if not root.is_dir():
            return None
        in_flight: list[Path] = []
        for child in sorted(root.iterdir()):
            if not child.is_dir():
                continue
            try:
                data = json.loads((child / "features.json").read_text())
            except (OSError, ValueError):
                continue
            features = data.get("features") if isinstance(data, dict) else None
            if not isinstance(features, list):
                continue
            if any(isinstance(f, dict) and f.get("passes") is not True for f in features):
                in_flight.append(child)
        return in_flight[-1] if in_flight else None
    except Exception:  # noqa: BLE001 — default resolution is advisory, never fatal
        return None


def _resolve_brief_action_items(actions_plan: str | None) -> list[Any]:
    """Resolve the ActionItem list for the ``agent brief`` managed actions block.

    Plan 2026-06-02-001 F003: the agent-brief surface ALWAYS renders the managed
    block from the ActionItem spine. ``actions_plan`` (the explicit
    ``--actions PLAN`` flag) pins a specific plan and intentionally propagates a
    ``SystemExit`` when that plan id does not resolve (a typed operator error,
    exit 2). Without the flag the plan is auto-resolved from the cwd project; any
    failure THERE degrades to an empty list so the block renders as
    "No actions pending" rather than crashing the brief."""
    from dontpanic_orchestrate import operations_guidance

    if actions_plan is not None:
        # Explicit plan: let an unresolved id raise SystemExit (exit 2) — the
        # operator named a plan that does not exist and should be told so.
        plan_dir: Path | None = _resolve_plan_dir(actions_plan)
    else:
        plan_dir = _resolve_default_actions_plan_dir()
    if plan_dir is None:
        return []
    try:
        plan_id = plan_loader.load(plan_dir).plan_id
        guidance = operations_guidance.collect_state(plan_dir, plan_id=plan_id)
        return guidance.to_action_items()
    except Exception:  # noqa: BLE001 — the brief must render even if collection fails
        return []


def _ps_main(argv: list[str]) -> int:
    """F023 EC13: list live supervisors registered in
    ~/.jarvis/active_supervisors.jsonl. Filters dead PIDs and prunes the file
    as a side effect."""
    entries = active_supervisors.list_active()
    print(active_supervisors.format_entries(entries))
    return 0


def _reconcile_gate_state_for_cli(
    plan_dir: Path,
    *,
    plan_id: str,
    declared_gates: list[str],
    cli_label: str,
) -> bool:
    """Plan 2026-05-08-003 F001 — fail-loud reconciliation entry for CLI
    approve/resume. Returns ``True`` when the operator should exit 2 (a
    contradiction was surfaced); ``False`` when the persisted state is
    consistent and the caller may proceed.

    Side effects on contradiction: writes a classified INBOX event and prints
    a remediation block to stderr. ``gate-state.json`` is never mutated (D004).
    """
    try:
        gate_pause.reconcile_gate_state(
            plan_dir,
            plan_id=plan_id,
            declared_gates=declared_gates,
        )
    except gate_pause.GateStateReconciliationError as exc:
        inbox.append_event(
            plan_dir,
            event="gate_state_reconciliation_failed",
            plan_id=plan_id,
            body=gate_pause.format_reconciliation_inbox_body(exc),
            kind=exc.kind,
            gate=exc.gate or "",
            stage=exc.stage or "",
            persisted_state_path=str(exc.persisted_state_path),
            cli=cli_label,
        )
        print(
            f"[{cli_label}] REFUSED gate-state reconciliation [{exc.kind}] for {plan_id}.",
            file=sys.stderr,
        )
        print(gate_pause.format_reconciliation_inbox_body(exc), file=sys.stderr)
        return True
    return False


def _approve_main(argv: list[str]) -> int:
    """F008 Item 2 + F003: clear a single declared gate for a plan.

    Plan 2026-05-02-003 F003: when ``gate == 'pre_resume_after_child'``, the
    handler accepts ``--child <child_plan_id>`` and ``--accept-non-satisfied``
    flags and routes to nested_orchestration.approve_pre_resume_after_child
    (fan-in memo + child-compliance validation). The bare-suffix form
    ``pre_resume_after_child:CHILD`` is refused with a directive to use the
    ``--child`` flag (bare-resume discipline — direct clearance bypasses
    validation).
    """
    # Plan 2026-05-02-003 F003 — special-case BEFORE the strict 2-arg check
    # because the F003 form takes 3+ args.
    if len(argv) >= 2 and argv[1] == "pre_resume_after_child":
        return _approve_pre_resume_after_child_main(argv)
    if len(argv) >= 2 and argv[1].startswith(nested_orchestration.PRE_RESUME_GATE_PREFIX):
        # Bare suffix form like `approve <plan> pre_resume_after_child:CHILD`
        # — refuse so operator goes through the validating path.
        suffix_only = argv[1][len(nested_orchestration.PRE_RESUME_GATE_PREFIX) :]
        print(
            f"[approve] REFUSED gate {argv[1]!r} — use the validated form: "
            f"`approve <plan> pre_resume_after_child --child {suffix_only or '<child_plan_id>'} "
            "[--accept-non-satisfied]`. Direct clearance via the `:suffix` "
            "form bypasses fan-in memo + child-compliance validation.",
            file=sys.stderr,
        )
        return 2

    # F014 — blocking-drift human acknowledgement. `approve <plan> drift:<class>`
    # (or bare `drift`) clears the durable plan-drift ack marker that a prior
    # BLOCKING_POLICY scope/policy drift recorded, authorising work to resume
    # against the new boundary. Deleting the marker lets the NEXT dispatch record
    # a fresh baseline against the now-accepted scope and proceed; without it the
    # run stays paused on every re-dispatch (blocks-then-resumes).
    if len(argv) == 2 and (
        argv[1] == "drift" or argv[1].startswith(plan_drift.DRIFT_GATE_PREFIX)
    ):
        plan_arg, drift_token = argv
        plan_dir = _resolve_plan_dir(plan_arg)
        loaded = plan_loader.load(plan_dir)
        requested_class = (
            None
            if drift_token == "drift"
            else drift_token[len(plan_drift.DRIFT_GATE_PREFIX):] or None
        )
        try:
            cleared = plan_drift.acknowledge_blocking_drift(
                plan_dir,
                plan_id=loaded.plan_id,
                drift_class=requested_class,
            )
        except plan_drift.DriftAckError as exc:
            print(f"[approve] REFUSED {drift_token!r}: {exc}", file=sys.stderr)
            return 2
        inbox.append_event(
            plan_dir,
            event="plan_drift_acknowledged",
            plan_id=loaded.plan_id,
            body=(
                f"Operator acknowledged blocking plan-drift "
                f"({cleared.get('drift_class')}) via 'approve {drift_token}'.\n\n"
                f"Changed files: {', '.join(cleared.get('changed_files') or []) or '(none)'}\n"
                f"The next dispatch records a fresh baseline against the accepted "
                f"scope and proceeds."
            ),
            drift_class=str(cleared.get("drift_class")),
            feature_id=cleared.get("feature_id"),
        )
        print(
            f"[approve] acknowledged blocking drift "
            f"({cleared.get('drift_class')}) for {loaded.plan_id} — "
            f"redispatch to resume"
        )
        return 0

    if len(argv) != 2:
        print("usage: dontpanic approve <plan-id> <gate>", file=sys.stderr)
        return 2
    plan_arg, gate = argv
    # F006: the global circuit breaker is hard-stop and intentionally has no
    # operator clearance path. Refuse the approve so the CLI surface matches
    # the spec ("APPROVAL_BREAKERS frozenset names the 6 pause-for-approval
    # kinds; the 7th (global) is hard-stop"). Operators wait out the 24h
    # window; there is no jarvis clear-global-breaker.
    global_gate = f"breaker:{cb.BreakerKind.GLOBAL_CIRCUIT_BREAKER.value}"
    if gate == global_gate:
        print(
            f"[approve] REFUSED gate {gate!r} — the global circuit breaker is "
            "hard-stop and has no operator clearance path. Wait for the 24h "
            "window to expire (see ~/.jarvis/breaker_history.jsonl).",
            file=sys.stderr,
        )
        return 2
    plan_dir = _resolve_plan_dir(plan_arg)
    loaded = plan_loader.load(plan_dir)
    # plan.human_gates is a list of HumanGate enum members; compare on .value
    # so the user-supplied string CLI arg matches the declared set.
    declared_strs = [
        g.value if hasattr(g, "value") else str(g) for g in (loaded.plan.human_gates or [])
    ]
    # Plan 2026-05-08-003 F001 — fail-loud gate-state reconciliation.
    # Surfaces persisted-vs-declared contradictions before approve_gate would
    # touch state. INBOX classification + exit 2 keep the artifact untouched
    # for operator review.
    if _reconcile_gate_state_for_cli(
        plan_dir,
        plan_id=loaded.plan_id,
        declared_gates=declared_strs,
        cli_label="approve",
    ):
        return 2
    # F006: synthetic breaker:<kind> gates are valid declared names too — the
    # supervisor adds them to active_breakers on trip. Don't false-warn when
    # operator approves a known breaker name (either currently active or any
    # known approval-required BreakerKind, in case the operator is pre-clearing).
    # The global kind is excluded above; the rest of APPROVAL_BREAKERS is fair game.
    # F007: same treatment for synthetic defer:<kind> gates added by the
    # admission reconcile.
    active_breakers = gate_pause.active_breakers(plan_dir)
    active_defers = gate_pause.active_defers(plan_dir)
    breaker_names = {f"breaker:{k.value}" for k in cb.APPROVAL_BREAKERS}
    defer_names = {quota_admission.gate_name(k) for k in quota_admission.DeferKind}
    valid_targets = (
        set(declared_strs) | set(active_breakers) | set(active_defers) | breaker_names | defer_names
    )
    if gate not in valid_targets:
        print(
            f"[approve] WARNING gate {gate!r} not in plan.human_gates {declared_strs} "
            f"and not a known breaker:* name; recording anyway",
            file=sys.stderr,
        )
    # Plan 2026-05-04-002 F001 — staged lifecycle gates (`pre_impl`,
    # `pre_merge`) may only be cleared via `approve` when the supervisor
    # recorded them as currently pending: either the gate is in `pause_gates`
    # OR the gate is the canonical gate of the persisted `pending_stage`.
    # Already-cleared lifecycle gates exit 2 (vs the legacy 0 for the
    # idempotent re-approve path) so operators don't accidentally treat
    # "no-op" as a successful re-clearance signal. Non-lifecycle gates
    # (on_escalation, breaker:*, defer:*) keep their existing relaxed
    # semantics — pre-clearing a future on_escalation is still allowed.
    if gate_pause.is_lifecycle_gate(gate):
        compat = gate_pause.load_gate_state_compat(plan_dir)
        currently_pending = gate_pause.is_gate_currently_pending(plan_dir, gate)
        stage_match = compat.pending_stage is not None and gate in {
            *([compat.pending_stage] if compat.pending_stage in declared_strs else [])
        }
        if gate in compat.cleared_gates:
            print(
                f"[approve] REFUSED gate {gate!r} — already cleared "
                f"(staged lifecycle gates exit 2 on re-clear so callers "
                f"distinguish no-op from success).",
                file=sys.stderr,
            )
            return 2
        if not (currently_pending or stage_match):
            persisted_pause = (
                gate_pause.load_gate_state_compat(plan_dir).raw.get("pause_gates") or []
            )
            print(
                f"[approve] REFUSED lifecycle gate {gate!r} — not currently pending. "
                f"pending_stage={compat.pending_stage or '(none)'}, "
                f"pause_gates={list(persisted_pause)}. "
                f"Lifecycle gates may only be cleared once the supervisor pauses on them.",
                file=sys.stderr,
            )
            return 2
    changed = gate_pause.approve_gate(plan_dir, gate, plan_id=loaded.plan_id)
    if changed:
        inbox.append_event(
            plan_dir,
            event="gate_cleared",
            plan_id=loaded.plan_id,
            body=f"Operator cleared gate '{gate}' via 'approve'.",
            gate=gate,
        )
        print(f"[approve] cleared gate {gate!r} for {loaded.plan_id}")
    else:
        print(f"[approve] gate {gate!r} was already cleared")
    # Remaining unmet = unmet plan-declared + every still-active breaker +
    # every still-active defer. unmet_gates() considers only plan-declared
    # gates, which used to give operators a misleading "(none)" while a
    # transient breaker:* / defer:* was still blocking dispatch.
    remaining = gate_pause.evaluate(plan_dir, declared_strs).unmet
    print(f"[approve] remaining unmet gates: {remaining or '(none)'}")
    return 0


def _approve_pre_resume_after_child_main(argv: list[str]) -> int:
    """Plan 2026-05-02-003 F003: validate-and-clear a pre_resume_after_child gate.

    Shape:
      approve <parent> pre_resume_after_child --child <child_plan_id>
                                              [--accept-non-satisfied]

    Validation chain (refuses with exit 2 on first failure):
      1. Gate must currently be armed for this child on the parent.
      2. Fan-in memo at parent's evidence/fan-in-from-{child}.md must exist.
         When absent, prints a stub template the operator can paste in.
      3. The memo must declare `## Return Condition / status: satisfied`.
         (This is the operator's explicit re-entry declaration; the
         --accept-non-satisfied flag does NOT override the memo's own status.)
      4. Child's audit/charter-compliance-{child}.json must record
         return_condition_status='satisfied' UNLESS --accept-non-satisfied.

    On success: clears the gate, writes INBOX gate_cleared event recording
    whether --accept-non-satisfied was applied, records best-effort
    volley.return_to_parent_approved event on the parent's events.jsonl.
    """
    parser = argparse.ArgumentParser(
        prog="dontpanic approve <parent> pre_resume_after_child",
        add_help=True,
    )
    parser.add_argument(
        "plan_id",
        help="Parent plan ID or absolute parent dir path.",
    )
    parser.add_argument(
        "_gate_token",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--child",
        required=True,
        metavar="<child_plan_id>",
        help="The child plan_id whose pre_resume_after_child gate to clear.",
    )
    parser.add_argument(
        "--accept-non-satisfied",
        action="store_true",
        dest="accept_non_satisfied",
        help=(
            "Override: clear the gate even when the child's "
            "audit/charter-compliance-*.json records "
            "return_condition_status != 'satisfied'. Does NOT override the "
            "fan-in memo's own status — the memo must always be 'satisfied'."
        ),
    )
    args = parser.parse_args(argv)

    plan_arg = args.plan_id
    child_plan_id = args.child
    parent_plan_dir = _resolve_plan_dir(plan_arg)
    loaded = plan_loader.load(parent_plan_dir)

    # plans_root inferred from parent_plan_dir.parent. Production callers run
    # against `<repo>/docs/plans/<parent>/`; tests pass tmp_path layouts the
    # same shape.
    plans_root = parent_plan_dir.parent
    child_plan_dir = plans_root / child_plan_id
    if not child_plan_dir.is_dir():
        print(
            f"[approve pre_resume_after_child] child plan dir not found: {child_plan_dir}",
            file=sys.stderr,
        )
        return 2

    # Surface the fan-in memo template when the memo is missing — easier than
    # re-running approve to discover the format.
    memo_path = nested_orchestration.fan_in_memo_path(parent_plan_dir, child_plan_id)
    if not memo_path.is_file():
        print(
            f"[approve pre_resume_after_child] fan-in memo missing at {memo_path}.",
            file=sys.stderr,
        )
        print("Paste this template into the file and re-run:", file=sys.stderr)
        print("---", file=sys.stderr)
        print(
            nested_orchestration.FAN_IN_MEMO_TEMPLATE.format(child_plan_id=child_plan_id),
            file=sys.stderr,
        )
        print("---", file=sys.stderr)
        return 2

    try:
        outcome = nested_orchestration.approve_pre_resume_after_child(
            parent_plan_dir,
            parent_plan_id=loaded.plan_id,
            child_plan_id=child_plan_id,
            child_plan_dir=child_plan_dir,
            accept_non_satisfied=args.accept_non_satisfied,
        )
    except nested_orchestration.ChildPauseApproveError as exc:
        print(f"[approve pre_resume_after_child] REFUSED: {exc}", file=sys.stderr)
        return 2

    body_lines = [
        f"Operator cleared pre_resume_after_child gate for child {child_plan_id!r}.",
        f"Fan-in memo: {outcome['memo_path']} (status={outcome['memo_status']})",
        f"Child compliance: status={outcome['child_status']!r}",
    ]
    if outcome["override_applied"]:
        body_lines.append(
            "OVERRIDE applied (--accept-non-satisfied). Operator must record "
            "rationale in the parent's decisions.jsonl."
        )
    inbox.append_event(
        parent_plan_dir,
        event="gate_cleared",
        plan_id=loaded.plan_id,
        body="\n".join(body_lines),
        gate=outcome["gate"],
        child_plan_id=child_plan_id,
        accept_non_satisfied=str(outcome["override_applied"]).lower(),
    )
    nested_orchestration.record_event(
        parent_plan_dir,
        kind="volley.return_to_parent_approved",
        payload={
            "child_plan_id": child_plan_id,
            "child_status": outcome["child_status"],
            "memo_status": outcome["memo_status"],
            "override_applied": outcome["override_applied"],
        },
        plan_id=loaded.plan_id,
    )
    print(
        f"[approve pre_resume_after_child] cleared {outcome['gate']!r} for "
        f"{loaded.plan_id} (override={outcome['override_applied']})"
    )
    return 0


_RESUME_BARE_USAGE = (
    "usage: dontpanic resume <plan> (--gate <name> | --all)\n"
    "  preferred for partial clearance: dontpanic approve <plan> <gate>\n"
    "  bulk clear (explicit): dontpanic resume <plan> --all"
)


def _resume_main(argv: list[str]) -> int:
    """Plan 2026-05-02-001 F001: gate-discipline-aware resume.

    Bare `resume <plan>` no longer silently bulk-clears every gate. New shape:

      resume <plan> --gate <name>   clear exactly one gate (parity with
                                    `approve <plan> <gate>`); INBOX records
                                    `event=gate_cleared` with body noting
                                    `via 'resume --gate'` so the audit trail
                                    distinguishes the entry path
      resume <plan> --all           explicit bulk-clear (the legacy behavior);
                                    INBOX records `event=resumed` with body
                                    noting `via 'resume --all'`

    Bare `resume <plan>` (no flag) refuses with exit 2 and a usage message
    that names `approve <gate>` as the preferred path. The flags are mutually
    exclusive — argparse rejects `--gate X --all` with exit 2.
    """
    parser = argparse.ArgumentParser(
        prog="dontpanic resume",
        usage=_RESUME_BARE_USAGE,
        add_help=True,
    )
    parser.add_argument("plan_id", help="Plan ID or absolute plan dir path")
    grp = parser.add_mutually_exclusive_group()
    grp.add_argument(
        "--gate",
        default=None,
        metavar="<name>",
        help="Clear exactly one gate (parity with `approve <plan> <gate>`).",
    )
    grp.add_argument(
        "--all",
        action="store_true",
        dest="all_gates",
        help="Explicit bulk-clear of every plan-declared gate + active "
        "breakers/defers (legacy behavior, now behind a required flag).",
    )
    args = parser.parse_args(argv)

    plan_arg = args.plan_id

    # Bare `resume <plan>` (no --gate, no --all): refuse with the documented
    # usage message. Note: argparse parses successfully because the mutex
    # group is not required=True; we detect "neither flag" here.
    if args.gate is None and not args.all_gates:
        print(_RESUME_BARE_USAGE, file=sys.stderr)
        return 2

    plan_dir = _resolve_plan_dir(plan_arg)
    loaded = plan_loader.load(plan_dir)
    declared_strs = [
        g.value if hasattr(g, "value") else str(g) for g in (loaded.plan.human_gates or [])
    ]
    # Plan 2026-05-08-003 F001 — fail-loud gate-state reconciliation. Mirrors
    # the approve path so persisted-vs-declared contradictions are surfaced
    # before approve_gate / resume_all touch state.
    if _reconcile_gate_state_for_cli(
        plan_dir,
        plan_id=loaded.plan_id,
        declared_gates=declared_strs,
        cli_label="resume",
    ):
        return 2
    active_breakers = gate_pause.active_breakers(plan_dir)
    active_defers = gate_pause.active_defers(plan_dir)

    if args.gate is not None:
        gate = args.gate
        # Plan 2026-05-02-003 F003 — bare-resume discipline: pre_resume_after_child
        # gates can ONLY be cleared via the validating approve form (which
        # reads the fan-in memo + child-compliance side-car). `resume --gate`
        # would bypass that validation, so refuse with exit 2 and direct the
        # operator to the canonical command.
        if gate.startswith(nested_orchestration.PRE_RESUME_GATE_PREFIX):
            child_id = gate[len(nested_orchestration.PRE_RESUME_GATE_PREFIX) :]
            print(
                f"[resume --gate] REFUSED gate {gate!r} — child-return gates "
                "must be cleared via the validating approve form: "
                f"`approve <plan> pre_resume_after_child --child "
                f"{child_id or '<child_plan_id>'} [--accept-non-satisfied]`. "
                "Direct clearance bypasses fan-in memo + child-compliance "
                "validation.",
                file=sys.stderr,
            )
            return 2
        # Parity with `_approve_main`: the global circuit breaker is hard-stop
        # and intentionally has no operator clearance path. Refuse with exit 2
        # and leave gate-state.json untouched.
        global_gate = f"breaker:{cb.BreakerKind.GLOBAL_CIRCUIT_BREAKER.value}"
        if gate == global_gate:
            print(
                f"[resume --gate] REFUSED gate {gate!r} — "
                "global breaker has no operator clearance path. "
                "Wait for the 24h window to expire "
                "(see ~/.jarvis/breaker_history.jsonl).",
                file=sys.stderr,
            )
            return 2
        valid_targets = set(declared_strs) | set(active_breakers) | set(active_defers)
        if gate not in valid_targets:
            available = sorted(valid_targets)
            available_render = available or ["(none)"]
            print(
                f"[resume --gate] unknown gate {gate!r}; available gates: {available_render}",
                file=sys.stderr,
            )
            return 2
        # Plan 2026-05-04-002 F001 — staged lifecycle gates may only be cleared
        # via `resume --gate` when the supervisor recorded them as currently
        # pending. Mirrors the `_approve_main` enforcement so per-gate
        # clearance has the same constraint regardless of entry path.
        # Already-cleared lifecycle gates exit 2 (not 0) so the operator
        # doesn't read no-op as success. Non-lifecycle declared gates and
        # active breakers/defers keep their legacy relaxed semantics.
        if gate_pause.is_lifecycle_gate(gate):
            compat = gate_pause.load_gate_state_compat(plan_dir)
            currently_pending = gate_pause.is_gate_currently_pending(plan_dir, gate)
            stage_match = compat.pending_stage is not None and gate in {
                *([compat.pending_stage] if compat.pending_stage in declared_strs else [])
            }
            if gate in compat.cleared_gates:
                print(
                    f"[resume --gate] REFUSED gate {gate!r} — already cleared "
                    f"(staged lifecycle gates exit 2 on re-clear).",
                    file=sys.stderr,
                )
                return 2
            if not (currently_pending or stage_match):
                persisted_pause = compat.raw.get("pause_gates") or []
                print(
                    f"[resume --gate] REFUSED lifecycle gate {gate!r} — not currently pending. "
                    f"pending_stage={compat.pending_stage or '(none)'}, "
                    f"pause_gates={list(persisted_pause)}.",
                    file=sys.stderr,
                )
                return 2
        # Idempotent re-clear: approve_gate returns False when the gate is
        # already cleared (or — for transient breaker:* / defer:* — no longer
        # active). In that case we exit 0 with state untouched and emit no
        # INBOX event, no history entry. Parity with `_approve_main`.
        changed = gate_pause.approve_gate(plan_dir, gate, plan_id=loaded.plan_id)
        if not changed:
            print(f"[resume --gate] gate {gate!r} was already cleared")
            return 0
        inbox.append_event(
            plan_dir,
            event="gate_cleared",
            plan_id=loaded.plan_id,
            body=f"Operator cleared gate '{gate}' via 'resume --gate'.",
            gate=gate,
        )
        print(f"[resume --gate] cleared gate {gate!r} for {loaded.plan_id}")
        remaining = gate_pause.evaluate(plan_dir, declared_strs).unmet
        print(f"[resume --gate] remaining unmet gates: {remaining or '(none)'}")
        return 0

    # --all path: existing bulk-clear behavior, with INBOX body now naming
    # the new explicit form so audit history distinguishes it from any
    # legacy bare-resume traces.
    declared = list(loaded.plan.human_gates or [])
    if not declared and not active_breakers and not active_defers:
        print(
            f"[resume --all] plan {loaded.plan_id} has no plan-declared gates, "
            f"no active breakers, and no active defers — nothing to clear"
        )
        return 0
    newly = gate_pause.resume_all(plan_dir, plan_id=loaded.plan_id, declared_gates=declared)
    if newly:
        inbox.append_event(
            plan_dir,
            event="resumed",
            plan_id=loaded.plan_id,
            body=(
                f"Operator cleared all gates via 'resume --all'.\n"
                f"Newly cleared: {newly}\n"
                f"Plan-declared: {declared}\n"
                f"Active breakers (pre-clear): {active_breakers}\n"
                f"Active defers (pre-clear): {active_defers}"
            ),
            cleared_gates=",".join(newly),
        )
        print(f"[resume --all] cleared {len(newly)} gates: {newly}")
    else:
        print("[resume --all] all declared gates were already cleared")
    return 0


def _claude_touch_main(argv: list[str]) -> int:
    """F007 Slice 2: record that a human just made a Claude request. The
    supervisor's autonomous-class admission check reads this state and pauses
    via defer:interactive_backoff for JARVIS_INTERACTIVE_BACKOFF_MINUTES (30
    min default) after the touch.

    No args. Touches `claude` only — future agent variants can ride a later
    slice. State path overridable via JARVIS_INTERACTIVE_STATE_PATH for
    hermetic tests; conftest autouse fixture sets it per-test.
    """
    if argv:
        print("usage: dontpanic claude-touch", file=sys.stderr)
        return 2
    ts = interactive_state.touch("claude")
    minutes = interactive_state.backoff_minutes()
    print(
        f"[claude-touch] recorded human Claude request at {ts} "
        f"(backoff window {minutes:g} min). Autonomous Claude-heavy "
        "dispatches will defer until the window elapses."
    )
    return 0


def _finalize_main(argv: list[str]) -> int:
    """``dontpanic finalize <plan> --feature <F>`` — Plan 2026-05-30-001 F007.

    No-paid finalization of a cleanly auditor-signed_off + pre_merge-cleared
    feature: repairs the signoff envelope if the pre_merge pause skipped it and
    flips only that feature's ``passes: true``. Never re-runs a paid volley.

    Exit codes (distinct per refusal so scripts/dashboard can branch):
      0 — finalized (or idempotent no-op)
      2 — usage error
      3 — refused: latest auditor verdict is not signed_off
      4 — refused: pre_merge gate not cleared
      5 — refused: no auditor envelope for the feature
      6 — refused: plan drifted since dispatch; reconcile before finalizing (F009)
    """
    parser = argparse.ArgumentParser(
        prog="dontpanic finalize",
        description=(
            "Finalize a signed_off + pre_merge-cleared feature with no paid "
            "agent calls: repair the signoff envelope if missing and flip only "
            "that feature's passes:true. Refuses (no mutation) when the latest "
            "auditor verdict is not signed_off, pre_merge is uncleared, or no "
            "auditor envelope exists."
        ),
    )
    parser.add_argument("plan", help="Plan ID (resolved against ./docs/plans/) or dir path")
    parser.add_argument("--feature", required=True, help="Feature ID, e.g. F001")
    args = parser.parse_args(argv)

    from dontpanic_orchestrate import signed_off_finalizer

    _refusal_exit = {"not_signed_off": 3, "pre_merge_uncleared": 4, "no_audit": 5}

    plan_dir = _resolve_plan_dir(args.plan)
    plan_id = plan_loader.load(plan_dir).plan_id

    # F009 — no-paid finalization still MUTATES signoff + features.json state.
    # If the plan drifted since dispatch recorded its baseline, finalizing would
    # bake a success signoff against stale context. Run the same drift check the
    # paid signoff boundary uses BEFORE any mutation and refuse on refresh/
    # blocking drift (additive ledger drift is reconciled in-place and proceeds).
    try:
        drift = plan_drift.check_and_reconcile(
            plan_dir,
            plan_id=plan_id,
            feature_id=args.feature,
            stage=plan_drift.STAGE_SIGNOFF,
        )
    except plan_drift.DriftBaselineMissingError as exc:
        # FAIL CLOSED (F009 codex #1): no readable dispatch-start baseline means
        # we cannot prove the plan has not drifted. Refuse to finalize against
        # unverifiable context rather than baking a signoff blind.
        print(
            f"[finalize] REFUSED (plan_drift): {exc}",
            file=sys.stderr,
        )
        return 6
    if not drift.proceed:
        guidance = drift.guidance
        cmd = ""
        if guidance is not None and getattr(guidance, "choices", None):
            cmd = guidance.choices[0].exact_command or ""
        print(
            f"[finalize] REFUSED (plan_drift): {drift.report.headline(plan_id)}",
            file=sys.stderr,
        )
        print(
            f"[finalize]   changed: {', '.join(drift.report.changed_files) or '(none)'}",
            file=sys.stderr,
        )
        if cmd:
            print(f"[finalize]   reconcile then: {cmd}", file=sys.stderr)
        return 6

    try:
        result = signed_off_finalizer.finalize_signed_off_feature(
            plan_dir, plan_id=plan_id, feature_id=args.feature
        )
    except signed_off_finalizer.FinalizeError as exc:
        print(f"[finalize] REFUSED ({exc.code}): {exc}", file=sys.stderr)
        return _refusal_exit.get(exc.code, 3)

    if result.already_finalized:
        print(f"[finalize] {args.feature} already finalized — no-op")
    else:
        print(f"[finalize] {args.feature} finalized (no paid calls)")
    print(f"[finalize]   signoff: {result.signoff_path} (repaired={result.signoff_repaired})")
    print(f"[finalize]   features.json passes flipped: {result.features_passes_flipped}")
    return 0


def _what_now_main(argv: list[str]) -> int:
    """``dontpanic what-now <plan> [--feature F]`` — Plan 2026-05-30-001 F007.

    Read-only operations guidance: collects the plan's quota / iteration / gate /
    signoff state and prints a short decision set (recommended action +
    alternatives, exact commands where safe, one dashboard affordance). The same
    typed ActionChoice data feeds the dashboard ActionItems via
    ``Guidance.to_action_items``.
    """
    parser = argparse.ArgumentParser(
        prog="dontpanic what-now",
        description=(
            "Operations guidance for blocked work: wait/redispatch, "
            "raise-ceiling, finalize a cleared signoff, resume/close, onboard, "
            "or reconcile — with exact commands where safe."
        ),
    )
    parser.add_argument("plan", help="Plan ID (resolved against ./docs/plans/) or dir path")
    parser.add_argument("--feature", default="F001", help="Feature ID (default F001)")
    parser.add_argument(
        "--dashboard-url",
        default=None,
        help="Active dashboard URL when a singleton is running (omit when not).",
    )
    parser.add_argument("--format", choices=["text", "json"], default="text")
    args = parser.parse_args(argv)

    from dontpanic_orchestrate import operations_guidance

    plan_dir = _resolve_plan_dir(args.plan)
    plan_id = plan_loader.load(plan_dir).plan_id
    guidance = operations_guidance.collect_state(
        plan_dir,
        plan_id=plan_id,
        feature_id=args.feature,
        dashboard_url=args.dashboard_url,
    )
    # Plan 2026-06-02-001 F003 — BOTH the text and JSON surfaces render the
    # ActionItem spine, not an independently-computed shape. The guidance is
    # projected once into the canonical ActionItem envelope and both formats
    # render from the same `action_renderers` boundary (deduped by dedupe_key,
    # scrubbed + brand-normalized at the render boundary), so the CLI text, the
    # CLI JSON, and the dashboard can never drift.
    from dontpanic_orchestrate import action_renderers

    action_items = guidance.to_action_items()
    if args.format == "json":
        # F003 fix (codex audit i2 — high/security): the legacy guidance JSON shape
        # (`choices`, etc.) is preserved for back-compat, but EVERY human-facing
        # string is scrubbed + brand-normalized at the output boundary so the JSON
        # surface can no longer leak secret-shaped substrings or brand drift the way
        # the prior raw `guidance.to_dict()` did. `action_items` is the canonical
        # spine list, rendered through the same shared boundary so it stays
        # byte-consistent with the dashboard and the agent brief.
        payload = _scrub_json_payload(guidance.to_dict())
        payload["action_items"] = action_renderers.render_dashboard(action_items)["items"]
        print(json.dumps(payload, indent=2))
    else:
        print(action_renderers.render_cli_what_now(action_items, fmt="text"), end="")
    return 0


def _scrub_json_payload(value: Any) -> Any:
    """Recursively scrub every string in a JSON-able structure through the shared
    render boundary (secret-shape redaction + brand-drift normalization).

    F003 fix (codex audit i2): applied to the legacy what-now JSON surface so no
    field leaks, while preserving the structural shape consumers depend on."""
    from dontpanic_orchestrate import action_renderers as _ar

    if isinstance(value, str):
        return _ar.scrub_render_text(value)
    if isinstance(value, dict):
        return {k: _scrub_json_payload(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_scrub_json_payload(v) for v in value]
    return value


def _repair_add_common_args(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--scope",
        default="fleet",
        help="'fleet' / 'global' (aggregate) or a project name to scope to.",
    )
    p.add_argument("--plans-root", default=None, help="Override the plans root.")
    p.add_argument(
        "--repo-root", default=None, help="Override the repo root for provider probes."
    )
    p.add_argument("--format", choices=["json", "text"], default="json")


def _repair_main(argv: list[str]) -> int:
    """``dontpanic repair plan|apply`` — Plan 2026-06-04-006 F003/F004.

    ``repair plan`` (F003) is emit-only: gather the live 005 render-gate output
    read-only, adapt each card to a safety-classified RepairAction, and print the
    dependency-ordered agent-handoff bundle. Mutates NOTHING.

    ``repair apply --safe-derived-state`` (F004) executes ONLY apply_tier=
    derived_state actions; ``repair apply --safe --confirm`` additionally runs the
    confirmed_local allowlist. No tier runs deploy/creds/paid/role/plan-state/
    registry/destructive/baseline. Every executed action is round-trip verified.
    """
    parser = argparse.ArgumentParser(
        prog="dontpanic repair",
        description=(
            "Emit (plan) or run (apply) the ordered, safety-classified repair plan. "
            "`repair plan` never mutates; `repair apply` runs only the auto_safe batch "
            "for the explicit tier flag and refuses every forbidden kind."
        ),
    )
    sub = parser.add_subparsers(dest="subcmd")
    p_plan = sub.add_parser(
        "plan", help="Emit the safe-repair bundle for a scope (read-only)."
    )
    _repair_add_common_args(p_plan)
    p_apply = sub.add_parser(
        "apply", help="Run the auto_safe batch locally for an explicit tier flag."
    )
    _repair_add_common_args(p_apply)
    p_apply.add_argument(
        "--safe-derived-state",
        action="store_true",
        help="Run ONLY apply_tier=derived_state actions (projection regeneration).",
    )
    p_apply.add_argument(
        "--safe",
        action="store_true",
        help="With --confirm, additionally run the confirmed_local allowlist.",
    )
    p_apply.add_argument(
        "--confirm",
        action="store_true",
        help="Required alongside --safe to run the stronger confirmed_local tier.",
    )
    args = parser.parse_args(argv)

    if args.subcmd == "plan":
        return _repair_plan_cmd(args)
    if args.subcmd == "apply":
        return _repair_apply_cmd(args)
    parser.print_help(sys.stderr)
    return 2


def _repair_scope_roots(args: Any) -> "tuple[str | None, Path | None, Path | None, str]":
    project_name = None if args.scope in ("fleet", "global") else args.scope
    plans_root = Path(args.plans_root) if args.plans_root else None
    repo_root = Path(args.repo_root) if args.repo_root else None
    scope = args.scope if project_name is None else f"project:{project_name}"
    return project_name, plans_root, repo_root, scope


def _repair_plan_cmd(args: Any) -> int:
    from dontpanic_orchestrate import dashboard as _dashboard
    from dontpanic_orchestrate import repair_bundle as _repair_bundle

    project_name, plans_root, repo_root, scope = _repair_scope_roots(args)
    cards = _dashboard.gather_action_items_readonly(
        plans_root=plans_root, repo_root=repo_root, project_name=project_name
    )
    actions = [_repair_bundle.action_to_repair_action(c) for c in cards]
    bundle = _repair_bundle.build_bundle(actions, scope=scope)
    if args.format == "json":
        print(_repair_bundle.render_json(bundle))
    else:
        print(_repair_bundle.render_human(bundle), end="")
    return 0


def _repair_apply_cmd(args: Any) -> int:
    from dontpanic_orchestrate import dashboard as _dashboard
    from dontpanic_orchestrate import repair_apply as _repair_apply
    from dontpanic_orchestrate import repair_bundle as _repair_bundle
    from dontpanic_orchestrate import repair_safety as _repair_safety

    # Tier resolution — execution requires an explicit, escalating flag.
    if args.safe_derived_state:
        run_tier = _repair_safety.RUN_TIER_DERIVED
    elif args.safe and args.confirm:
        run_tier = _repair_safety.RUN_TIER_CONFIRM
    elif args.safe:
        print(
            "error: --safe requires --confirm to run the confirmed_local tier; "
            "use --safe-derived-state for the derived-state batch.",
            file=sys.stderr,
        )
        return 2
    else:
        print(
            "error: specify --safe-derived-state (derived-state batch) or "
            "--safe --confirm (also the confirmed_local allowlist).",
            file=sys.stderr,
        )
        return 2

    project_name, plans_root, repo_root, scope = _repair_scope_roots(args)
    cards, live_state = _dashboard.gather_repair_inputs(
        plans_root=plans_root, repo_root=repo_root, project_name=project_name
    )
    actions = [_repair_bundle.action_to_repair_action(c) for c in cards]

    def _effect_fn(action: Any) -> None:
        # Every derived_state kind regenerates the cached projection; dashboard.build
        # is the single idempotent regen (state/what-now/caps/reconcile/arch/export).
        # confirmed_local effects are not wired until producers assert them, so they
        # raise here and the runner records an honest execution_failed refusal.
        if action.kind in _repair_safety.DERIVED_STATE_KINDS:
            _dashboard.build(
                plans_root=plans_root,
                repo_root=repo_root,
                project_name=project_name,
            )
            return
        raise NotImplementedError(
            f"no local effect wired for kind={action.kind!r}"
        )

    def _recompute_fn() -> Any:
        _cards, ls = _dashboard.gather_repair_inputs(
            plans_root=plans_root, repo_root=repo_root, project_name=project_name
        )
        return ls

    report = _repair_apply.apply_repairs(
        actions,
        live_state,
        run_tier=run_tier,
        effect_fn=_effect_fn,
        recompute_fn=_recompute_fn,
    )

    payload = {
        "scope": scope,
        "run_tier": run_tier,
        "applied": [{"id": s.action_id, "outcome": s.outcome} for s in report.applied],
        "refused": [
            {"id": r.action_id, "reason": r.reason, "detail": r.detail}
            for r in report.refused
        ],
        "deferred": [{"id": d.action_id, "reason": d.reason} for d in report.deferred],
    }
    if args.format == "json":
        print(json.dumps(payload, indent=2))
    else:
        defective = [s for s in report.applied if s.outcome == "unchanged"]
        print(f"repair apply ({run_tier}) for scope: {scope}")
        print(
            f"  applied: {len(report.applied)}  "
            f"refused: {len(report.refused)}  "
            f"deferred: {len(report.deferred)}  "
            f"defective(unchanged): {len(defective)}"
        )
    return 0


def _plan_review_main(argv: list[str]) -> int:
    """``dontpanic plan-review <plan> [--format text|json]`` — plan 2026-06-01-001 F003.

    Read-only scope lint. Runs the F001 lint over every feature and the F002
    split proposer over each, assembles a single typed
    :class:`~dontpanic_orchestrate.plan_review.report.PlanScopeReport`, and
    renders it as human ``text`` (default) or machine ``json`` from that one
    source. Never writes a plan file (acceptance #2).

    Exit code (acceptance #3): non-zero (1) iff at least one block-severity flag
    is present across the plan; 0 otherwise. Exit 2 is reserved for usage
    errors (argparse).
    """
    parser = argparse.ArgumentParser(
        prog="dontpanic plan-review",
        description=(
            "Read-only scope lint for a plan: runs the deterministic F001 "
            "lint over every feature and the F002 split proposer over each, "
            "then prints a scope report. Exit code is non-zero iff any "
            "block-severity flag is present. Never edits the plan."
        ),
    )
    parser.add_argument("plan", help="Plan ID (resolved against ./docs/plans/) or dir path")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    parser.add_argument(
        "--since",
        metavar="REF_OR_PATH",
        default=None,
        help=(
            "Plan 2026-06-01-001 F006 — run the mid-development scope-delta lint "
            "against a PRIOR snapshot of this plan's features.json. Accepts a "
            "git ref (e.g. HEAD) OR a path to a prior features.json. Classifies "
            "each changed feature as sharpen/expand/split and exits non-zero "
            "when the scope-change protocol refuses a change (budget-busting "
            "expand on a locked feature, or a lossy split)."
        ),
    )
    args = parser.parse_args(argv)

    from dontpanic_orchestrate.plan_review import report as plan_review_report

    plan_dir = _resolve_plan_dir(args.plan)
    loaded = plan_loader.load(plan_dir)

    feature_dicts = [f.model_dump(mode="json") for f in loaded.features.features]  # enum->str (plan 2026-06-08-006 F002)
    resolvers = plan_review_report.build_default_resolvers()
    scope_report = plan_review_report.build_plan_scope_report(
        loaded.plan_id, feature_dicts, resolvers
    )

    if args.format == "json":
        print(json.dumps(scope_report.to_dict(), indent=2))
    else:
        print(plan_review_report.render_text(scope_report), end="")

    # Plan 2026-06-05-004 F005 — advisory conventions-disposition check (warn-only,
    # never blocks). Opt-in: fires only for plans that DECLARE a surface
    # (loaded.surfaces), so a plan that merely mentions a surface in prose is not
    # flagged. Text mode only for v0 (does not change the json schema / exit code).
    if args.format != "json":
        _print_disposition_advisory(plan_dir, loaded)

    exit_code = 1 if scope_report.has_block() else 0

    # Plan 2026-06-01-001 F006 — scope-delta lint invoked here on a plan-artifact
    # change (prior snapshot via --since). The concrete integration path proving
    # review_scope_delta runs on a plan change (operator decision D019: first
    # reachable wiring, minimal + bounded — no file watcher, no dashboard).
    if args.since is not None:
        delta_code = _run_scope_delta_review(
            plan_dir, loaded, feature_dicts, since=args.since, fmt=args.format
        )
        exit_code = exit_code or delta_code

    return exit_code


def _print_disposition_advisory(plan_dir: Path, loaded) -> None:
    """Plan 2026-06-05-004 F005 — print advisory conventions-disposition warnings.

    Opt-in + warn-only: silent unless the plan declares one or more surfaces. Never
    changes the verdict / exit code.
    """
    declared = list(getattr(loaded, "surfaces", None) or [])
    if not declared:
        return
    from dontpanic_orchestrate.conventions_ledger import load_ledger  # noqa: PLC0415
    from dontpanic_orchestrate.plan_review.disposition_check import (  # noqa: PLC0415
        check_plan_dispositions,
    )

    findings = check_plan_dispositions(declared=declared, ledger=load_ledger(plan_dir))
    if not findings:
        return
    print("\nconventions disposition (advisory — warn only):")
    for f in findings:
        print(f"  [warn] surface_disposition: {f.message}")


def _load_prior_features(plan_dir: Path, since: str) -> list[dict]:
    """Load a prior ``features.json`` for the F006 scope-delta lint. ``since`` is
    either a path to a prior features.json OR a git ref (resolved via
    ``git show <ref>:<repo-relative features.json>``). Returns ``[]`` when the
    prior cannot be loaded (first snapshot / unknown ref) so the delta lint
    reports no changes rather than erroring."""
    candidate = Path(since)
    if candidate.is_file():
        try:
            blob = json.loads(candidate.read_text())
        except (OSError, json.JSONDecodeError):
            return []
        if isinstance(blob, list):
            return list(blob)
        return list(blob.get("features", []))
    import subprocess  # noqa: PLC0415 — keep optional dependency local

    features_path = plan_dir / "features.json"
    try:
        rel = subprocess.run(  # noqa: S603,S607
            ["git", "-C", str(plan_dir), "ls-files", "--full-name", str(features_path)],  # noqa: S607
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
        if not rel:
            return []
        out = subprocess.run(  # noqa: S603,S607
            ["git", "-C", str(plan_dir), "show", f"{since}:{rel}"],  # noqa: S607
            capture_output=True,
            text=True,
            check=False,
        )
        if out.returncode != 0 or not out.stdout.strip():
            return []
        return list(json.loads(out.stdout).get("features", []))
    except (OSError, json.JSONDecodeError):
        return []


def _run_scope_delta_review(
    plan_dir: Path,
    loaded: plan_loader.LoadedPlan,
    current_features: list[dict],
    *,
    since: str,
    fmt: str,
) -> int:
    """F006 wiring helper: load the prior snapshot, run the changed-feature-only
    scope-delta lint, render it, and return non-zero iff the scope-change
    protocol refused a change. A LOCKED (active) plan treats all current
    features as locked so a budget-busting expand is refused (acceptance #3)."""
    from dontpanic_orchestrate.plan_review import scope_delta

    prior_features = _load_prior_features(plan_dir, since)
    status = getattr(getattr(loaded.plan, "status", None), "value", None) or str(
        getattr(loaded.plan, "status", "")
    )
    locked_ids = (
        {str(f.get("id")) for f in current_features if f.get("id")}
        if status == "active"
        else set()
    )
    report = scope_delta.review_scope_delta(
        prior_features, current_features, locked_ids=locked_ids
    )
    if fmt == "json":
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(scope_delta.render_text(report), end="")
    return 1 if report.is_blocked else 0


def _close_main(argv: list[str]) -> int:
    """Plan 2026-05-11-002 v3 F004 — operator-resolved feature close-out.

    Shape:
      dontpanic close --operator-resolved <plan-id> <feature-id> --reason <class>

    The ``--operator-resolved`` flag is required (the surface is reserved
    for operator close-out of a ``stopped_no_progress`` terminal that the
    operator judged non-defect). Other close shapes — plan-level
    active → completed — live under ``dontpanic plan close``.
    """
    parser = argparse.ArgumentParser(
        prog="dontpanic close",
        description=(
            "Operator-resolved feature close-out for a stopped_no_progress "
            "terminal that the operator judged non-defect. Generates a "
            "minimal closeout-memo template, clears breaker:no_progress, "
            "writes a signoff envelope, and flips features.json passes:true "
            "for the feature in one transaction."
        ),
    )
    parser.add_argument(
        "--operator-resolved",
        action="store_true",
        dest="operator_resolved",
        required=False,
        help=(
            "REQUIRED. Affirms the operator is closing out the feature "
            "without a re-dispatch. Reserved flag — the surface refuses to "
            "run without it so accidental close-outs don't slip through."
        ),
    )
    parser.add_argument(
        "plan",
        help="Plan ID (resolved against ./docs/plans/) or absolute dir path.",
    )
    parser.add_argument(
        "feature",
        help="Feature ID — e.g. F001 — that hit stopped_no_progress.",
    )
    parser.add_argument(
        "--reason",
        required=True,
        dest="reason_class",
        metavar="CLASS",
        help=(
            "Taxonomy class for the close-out (e.g. spec_ambiguity, "
            "scope_overreach, environmental_reproduction_failure, "
            "evidence_shape_disagreement, operator_judgment). Recorded in "
            "the signoff envelope's signoff_reason and on the closeout-memo "
            "header."
        ),
    )
    parser.add_argument(
        "--allow-missing-breaker",
        action="store_true",
        dest="allow_missing_breaker",
        help=(
            "Skip the safety check that refuses to close-out when "
            "breaker:no_progress is not currently active. Use only when "
            "operator has already cleared the breaker manually."
        ),
    )
    parser.add_argument(
        "--note",
        dest="note",
        default=None,
        help=(
            "Operator rationale. REQUIRED for --reason operator_verified "
            "(record what was verified and why the terminal is non-defect); "
            "optional context for other terminal-finish classes."
        ),
    )
    args = parser.parse_args(argv)

    if not args.operator_resolved:
        print(
            "[close] REFUSED: --operator-resolved flag is required. Use "
            "`dontpanic plan close <plan>` for plan-level lifecycle close.",
            file=sys.stderr,
        )
        return 2

    plan_dir = _resolve_plan_dir(args.plan)
    loaded = plan_loader.load(plan_dir)

    # Resolve tier + agents_in_panel from the loaded plan so the signoff
    # envelope's schema validation matches the plan's actual declaration.
    tier = loaded.plan.tier.value if hasattr(loaded.plan.tier, "value") else str(loaded.plan.tier)
    agents = [
        a.value if hasattr(a, "value") else str(a) for a in (loaded.plan.agents_required or [])
    ]
    if not agents:
        agents = ["claude", "codex"]

    # Plan 2026-06-02-002 F002 — route honest terminal-finish classes
    # (signed_off_adjacent / staging_blocked / operator_verified) through the
    # operator-finish path. It does not require breaker:no_progress and records
    # the actual terminal class instead of a stopped_no_progress pretence.
    is_operator_finish = args.reason_class in closeout.TERMINAL_FINISH_CLASSES
    try:
        if is_operator_finish:
            result = closeout.run_operator_finish(
                plan_dir=plan_dir,
                plan_id=loaded.plan_id,
                feature_id=args.feature,
                terminal_class=args.reason_class,
                tier=tier,
                agents_in_panel=agents,
                note=args.note,
            )
        else:
            result = closeout.run_close_out(
                plan_dir=plan_dir,
                plan_id=loaded.plan_id,
                feature_id=args.feature,
                reason_class=args.reason_class,
                tier=tier,
                agents_in_panel=agents,
                require_active_breaker=not args.allow_missing_breaker,
            )
    except closeout.CloseoutError as exc:
        print(f"[close] REFUSED: {exc}", file=sys.stderr)
        return 3

    # INBOX trail so the operator's close-out is visible alongside the
    # supervisor's existing event stream.
    inbox.append_event(
        plan_dir,
        event="feature_operator_resolved",
        plan_id=loaded.plan_id,
        feature_id=args.feature,
        reason_class=args.reason_class,
        body=(
            f"Operator closed feature {args.feature} as operator_resolved "
            f"(class={args.reason_class}).\n\n"
            f"Closeout memo: {result.memo_path.relative_to(plan_dir)}\n"
            f"Signoff envelope: {result.signoff_path.relative_to(plan_dir)}\n"
            f"breaker:no_progress cleared: {result.breaker_cleared}\n"
            f"features.json passes flipped: {result.features_passes_flipped}\n\n"
            f"Edit the closeout memo's `Rationale` section before merging."
        ),
    )

    print(f"[close] operator-resolved feature {args.feature} (class={args.reason_class})")
    print(f"[close]   closeout memo: {result.memo_path}")
    print(f"[close]   signoff envelope: {result.signoff_path}")
    print(f"[close]   breaker:no_progress cleared: {result.breaker_cleared}")
    print(
        f"[close]   features.json passes flipped: "
        f"{result.features_passes_flipped} ({result.features_json_path})"
    )
    print("[close] NEXT: edit the closeout memo's `Rationale` section before merging.")
    return 0


def _quota_caps_main(argv: list[str]) -> int:
    """Plan 2026-04-30-001 F004: operator-editable per-vendor quota caps.

    Subcommands:
      init    Write starter ~/.jarvis/quota_caps.json. Samples current Codex
              rolling_5h usage to derive a generous starter cap (* 1.25).
              Refuses to overwrite without --overwrite.
      show    Read + validate the file, print effective caps.
    """
    if not argv or argv[0] not in {"init", "show"}:
        print(
            "usage: dontpanic quota-caps {init|show} [--overwrite]",
            file=sys.stderr,
        )
        return 2
    sub = argv[0]
    rest = argv[1:]

    if sub == "init":
        overwrite = "--overwrite" in rest
        # Sample Codex windows via quota_check (sibling of dontpanic_orchestrate
        # under scripts/). Lazy-import to keep the loader decoupled.
        codex_observed_5h: int | None = None
        codex_observed_7d: int | None = None
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
            import quota_check as qc

            sample_5h = qc._codex_usage_v2("rolling_5h")
            sample_7d = qc._codex_usage_v2("rolling_7d")
            codex_observed_5h = int(sample_5h.get("observed_native") or 0) or None
            codex_observed_7d = int(sample_7d.get("observed_native") or 0) or None
        except (ImportError, OSError, RuntimeError) as exc:
            print(
                f"[quota-caps] codex sample failed ({exc}); using high provisional cap",
                file=sys.stderr,
            )
            codex_observed_5h = None
            codex_observed_7d = None
        try:
            data = quota_caps_loader.init_starter_file(
                codex_observed_5h=codex_observed_5h,
                codex_observed_7d=codex_observed_7d,
                overwrite=overwrite,
            )
        except quota_caps_loader.QuotaCapsError as exc:
            print(f"[quota-caps] {exc}", file=sys.stderr)
            return 2
        # Print the resolved path (honors JARVIS_QUOTA_CAPS_PATH) so the
        # operator sees exactly what was written, not the default constant.
        print(f"[quota-caps] wrote {quota_caps_loader.effective_caps_path()}")
        if codex_observed_5h is not None:
            cap = data["codex"]["plus"]["rolling_5h"]["cap"]
            print(
                f"[quota-caps] codex.plus.rolling_5h cap={cap} (observed {codex_observed_5h} * 1.25)"
            )
        if codex_observed_7d is not None:
            cap = data["codex"]["plus"]["rolling_7d"]["cap"]
            print(
                f"[quota-caps] codex.plus.rolling_7d cap={cap} (observed {codex_observed_7d} * 1.25)"
            )
        if codex_observed_5h is None and codex_observed_7d is None:
            print(
                "[quota-caps] codex cap = high provisional; re-run after some "
                "usage exists to derive a tighter cap"
            )
        return 0

    # show
    try:
        print(quota_caps_loader.show())
    except quota_caps_loader.QuotaCapsError as exc:
        print(f"[quota-caps] {exc}", file=sys.stderr)
        return 2
    return 0


_PROJECTS_USAGE = (
    "usage: dontpanic projects {add|list|show|remove} [args] [--json]\n"
    "  add <name> <path> [--force --yes] [--implementer X] [--auditor Y] [--notes ...]\n"
    "                    [--onboard] [--dry-run]\n"
    "  list\n"
    "  show <name>\n"
    "  remove <name> [--yes]    (default is dry-run preview)"
)


def _projects_main(argv: list[str]) -> int:
    """Plan 2026-05-03-001 F002: project registry CRUD.

    Subcommands:
      add     register a project (name + path); refuses collision unless
              `--force --yes`; refuses non-existent path; refuses bad-shape
              name (D003 regex).
      list    print registered projects (table by default, JSON with
              `--json`).
      show    print one entry (JSON with `--json`).
      remove  unregister; default is dry-run preview, `--yes` actually
              deletes.

    All subcommands accept `--json` for machine-readable output so agents
    shelling out can parse without screen-scraping. F002 ships CRUD only;
    supervisor wiring (per-project override precedence) lands in F003 per
    D004 / D007.
    """
    if not argv:
        print(_PROJECTS_USAGE, file=sys.stderr)
        return 2
    sub = argv[0]
    rest = argv[1:]
    if sub == "add":
        return _projects_add(rest)
    if sub == "list":
        return _projects_list(rest)
    if sub == "show":
        return _projects_show(rest)
    if sub == "remove":
        return _projects_remove(rest)
    print(f"[projects] unknown subcommand: {sub!r}", file=sys.stderr)
    print(_PROJECTS_USAGE, file=sys.stderr)
    return 2


def _projects_add(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="dontpanic projects add",
        add_help=True,
    )
    parser.add_argument("name", help="Project name (D003 regex)")
    parser.add_argument("path", help="Project directory (must exist)")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing entry with the same name. Requires --yes for non-interactive use.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        dest="yes",
        help="Skip confirmation prompt. Required with --force.",
    )
    parser.add_argument("--implementer", default=None)
    parser.add_argument("--auditor", default=None)
    parser.add_argument("--notes", default=None)
    parser.add_argument(
        "--init-config",
        action="store_true",
        dest="init_config",
        help=(
            "Plan 2026-05-03-001 F003: scaffold an empty per-project config "
            "at <project>/.dontpanic/dontpanic.json after registration. Default "
            "behavior (without this flag) is no scaffold — operators who "
            "want a per-project config opt in explicitly to avoid surprise."
        ),
    )
    parser.add_argument(
        "--onboard",
        action="store_true",
        help=(
            "Plan 2026-05-30-001 F003: scaffold repo onboarding after "
            "registration — write .dontpanic/dontpanic.json with explicit "
            "defaults, insert a generated DontPanic brief block into AGENTS.md, "
            "and a pointer block into CLAUDE.md. Content outside the managed "
            "markers is never touched; re-running refreshes only stale blocks."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help=(
            "Preview all intended writes (registration + --onboard scaffolding) "
            "without changing any file."
        ),
    )
    parser.add_argument(
        "--no-hooks",
        action="store_true",
        dest="no_hooks",
        help=(
            "Plan 2026-06-06-003 F003: skip installing the pre-commit "
            "architecture hook. By default `projects add` installs a chained "
            "pre-commit hook that regenerates + stages docs/architecture/"
            "architecture.json on commit, keeping the committed map fresh. Any "
            "prior pre-commit hook is preserved (chained, not clobbered)."
        ),
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)

    # --onboard already writes a full .dontpanic/dontpanic.json with explicit
    # defaults. --init-config (which scaffolds a bare `{}`) would run first and
    # then suppress onboarding's richer config write — leaving the empty stub.
    # Reject the combination rather than silently degrading to `{}`.
    if args.onboard and args.init_config:
        print(
            "[projects add] --onboard and --init-config are mutually exclusive: "
            "--onboard already writes .dontpanic/dontpanic.json with explicit "
            "defaults. Use --onboard alone.",
            file=sys.stderr,
        )
        return 2

    if args.dry_run:
        return _projects_add_dry_run(args)

    if args.force and not args.yes:
        # Non-interactive: refuse without --yes. Keeps the surface scriptable
        # without taking on a TTY-prompting dependency.
        print(
            "[projects add] --force requires --yes for non-interactive use",
            file=sys.stderr,
        )
        return 2

    try:
        entry = projects_registry.add_project(
            name=args.name,
            path=args.path,
            force=args.force,
            default_implementer=args.implementer,
            default_auditor=args.auditor,
            notes=args.notes,
        )
    except projects_registry.ProjectsRegistryError as exc:
        print(f"[projects add] {exc}", file=sys.stderr)
        return 2

    scaffold_path: Path | None = None
    scaffold_skipped = False
    if args.init_config:
        try:
            scaffold_path = project_config.scaffold_empty_config(Path(entry.path))
        except FileExistsError:
            # Pre-existing per-project config — leave it alone, surface the
            # fact in the human/JSON output. Don't fail the add.
            scaffold_skipped = True

    # Plan 2026-06-06-003 F003 — install the chained pre-commit architecture hook
    # so commits keep the committed map fresh (auto_regen=True). Best-effort +
    # opt-out (--no-hooks): a non-git path or an install conflict is surfaced in
    # the output, never fatal to the registration.
    from dontpanic_orchestrate import architecture_hook

    hooks_result: dict[str, object] | None = None
    if not args.no_hooks:
        repo_path = Path(entry.path)
        if (repo_path / ".git").exists():
            try:
                res = architecture_hook.install(repo_path, auto_regen=True)
                hooks_result = {
                    "installed": True,
                    "hook_path": res.get("hook_path"),
                    "backed_up": bool(res.get("backed_up", False)),
                }
            except Exception as exc:  # noqa: BLE001 — a hook problem never fails the add
                hooks_result = {"installed": False, "reason": str(exc)}
        else:
            hooks_result = {"installed": False, "reason": "not a git repository"}

    payload: dict[str, object] = {
        "action": "added",
        "project": projects_registry.to_public_dict(entry),
    }
    if hooks_result is not None:
        payload["hooks"] = hooks_result
    if args.init_config:
        if scaffold_skipped:
            payload["scaffold"] = "skipped (config already exists)"
        elif scaffold_path is not None:
            payload["scaffold"] = str(scaffold_path)

    onboard_plan = None
    if args.onboard:
        # F003: apply repo onboarding after registration. Writes the explicit-
        # defaults config + managed AGENTS.md / CLAUDE.md blocks; content outside
        # the markers is never touched.
        onboard_plan = repo_onboarding.apply_onboarding(Path(entry.path), dry_run=False)
        payload["onboard"] = repo_onboarding.plan_to_public_dict(onboard_plan)

    if args.as_json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(f"[projects add] registered {entry.name!r} → {entry.path}")
        if hooks_result is not None:
            if hooks_result.get("installed"):
                chained = " (prior pre-commit hook preserved)" if hooks_result.get("backed_up") else ""
                print(f"[projects add] installed pre-commit architecture hook{chained}")
            else:
                print(
                    f"[projects add] pre-commit hook NOT installed: {hooks_result.get('reason')}"
                )
        if args.init_config:
            if scaffold_skipped:
                print(
                    "[projects add] per-project config already exists at "
                    f"{project_config.project_config_path(Path(entry.path))} — left untouched"
                )
            elif scaffold_path is not None:
                print(f"[projects add] scaffolded empty per-project config at {scaffold_path}")
        if onboard_plan is not None:
            _print_onboarding_actions(onboard_plan, dry_run=False)
    return 0


def _print_onboarding_actions(plan: repo_onboarding.OnboardingPlan, *, dry_run: bool) -> None:
    """Human-readable rendering of an onboarding plan's actions (shared by the
    apply + dry-run paths)."""
    prefix = "[projects add] would" if dry_run else "[projects add]"
    verb = {
        "create": "create",
        "update": "update",
        "noop": "skip (current)",
        "warn": "WARNING",
    }
    for action in plan.actions:
        label = verb.get(action.action, action.action)
        print(f"{prefix} {label}: {action.path} — {action.detail}")


def _projects_add_dry_run(args: argparse.Namespace) -> int:
    """``projects add ... --dry-run`` — preview registration + (optional)
    onboarding writes without changing any file (F003 acceptance #1).

    Resolves and validates the path the same way ``add_project`` would (must be
    an existing directory) but writes nothing: not the registry, not the config,
    not AGENTS.md / CLAUDE.md.
    """
    proj_path = Path(args.path).expanduser().resolve()
    if not proj_path.is_dir():
        print(
            f"[projects add] path does not exist or is not a directory: {proj_path}",
            file=sys.stderr,
        )
        return 2
    if not projects_registry.PROJECT_NAME_PATTERN.fullmatch(args.name):
        print(
            f"[projects add] project name {args.name!r} does not match "
            f"{projects_registry.PROJECT_NAME_PATTERN.pattern}",
            file=sys.stderr,
        )
        return 2

    onboard_plan = None
    if args.onboard:
        onboard_plan = repo_onboarding.apply_onboarding(proj_path, dry_run=True)

    if args.as_json:
        payload: dict[str, object] = {
            "action": "dry_run",
            "project": {"name": args.name, "path": str(proj_path)},
        }
        if onboard_plan is not None:
            payload["onboard"] = repo_onboarding.plan_to_public_dict(onboard_plan)
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(
            f"[projects add] dry-run: would register {args.name!r} → {proj_path}. "
            "Pass without --dry-run to apply."
        )
        if onboard_plan is not None:
            _print_onboarding_actions(onboard_plan, dry_run=True)
    return 0


def _projects_list(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="dontpanic projects list",
        add_help=True,
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)
    reg = projects_registry.load_registry()

    if args.as_json:
        print(
            json.dumps(
                {"projects": [projects_registry.to_public_dict(p) for p in reg.projects]},
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0

    if not reg.projects:
        print("[projects list] no projects registered")
        return 0

    name_w = max(len("NAME"), *(len(p.name) for p in reg.projects))
    path_w = max(len("PATH"), *(len(p.path) for p in reg.projects))
    header = f"{'NAME':<{name_w}}  {'PATH':<{path_w}}  LAST_USED"
    print(header)
    for p in reg.projects:
        print(f"{p.name:<{name_w}}  {p.path:<{path_w}}  {p.last_used_at or '(never)'}")
    return 0


def _projects_show(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="dontpanic projects show",
        add_help=True,
    )
    parser.add_argument("name")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)

    entry = projects_registry.find_project(args.name)
    if entry is None:
        print(f"[projects show] project not found: {args.name!r}", file=sys.stderr)
        return 2

    payload = projects_registry.to_public_dict(entry)
    if args.as_json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        # Human-readable: same JSON shape, just pretty-printed (operators
        # asked for "readable JSON" in the F002 spec).
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


def _projects_remove(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="dontpanic projects remove",
        add_help=True,
    )
    parser.add_argument("name")
    parser.add_argument(
        "--yes",
        action="store_true",
        dest="yes",
        help="Actually delete. Default is dry-run preview.",
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)

    entry = projects_registry.find_project(args.name)
    if entry is None:
        print(f"[projects remove] project not found: {args.name!r}", file=sys.stderr)
        return 2

    if not args.yes:
        # Dry-run: report what would happen, leave registry untouched.
        if args.as_json:
            print(
                json.dumps(
                    {
                        "action": "dry_run",
                        "project": projects_registry.to_public_dict(entry),
                    },
                    indent=2,
                    ensure_ascii=False,
                )
            )
        else:
            print(
                f"[projects remove] dry-run: would remove {entry.name!r} → "
                f"{entry.path}. Pass --yes to actually delete."
            )
        return 0

    removed = projects_registry.remove_project(args.name)
    if removed is None:
        # Same entry just looked up via `find_project_by_name`; if the
        # registry lost it between read and write, surface as a real error
        # rather than relying on `assert` (strips under `python -O`).
        raise RuntimeError(
            f"projects registry race: {args.name!r} disappeared between lookup and remove"
        )
    payload = {"action": "removed", "project": projects_registry.to_public_dict(removed)}
    if args.as_json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(f"[projects remove] removed {removed.name!r}")
    return 0


_MANIFEST_USAGE = (
    "usage: dontpanic manifest {init|show} [--json]\n"
    "  init [--force --yes] [--cli-path PATH] [--install-source pipx|pip-editable|source]\n"
    "  show"
)


def _manifest_main(argv: list[str]) -> int:
    """Plan 2026-05-03-003 F001: agent manifest CRUD.

    Subcommands:
      init  Bootstrap a fresh manifest at ~/.dontpanic/agent-manifest.json
            (or the legacy ~/.jarvis/agent-manifest.json when only
            $JARVIS_HOME is set). Refuses on collision unless `--force --yes`.
      show  Print the current manifest as JSON, or refuse with exit 2 if
            missing.

    Both subcommands accept `--json`. `init` --force requires --yes for
    non-interactive use (parity with `dontpanic projects add` per D008 of
    plan 2026-05-03-001 / D004 of this plan).
    """
    if not argv:
        print(_MANIFEST_USAGE, file=sys.stderr)
        return 2
    sub = argv[0]
    rest = argv[1:]
    if sub == "init":
        return _manifest_init(rest)
    if sub == "show":
        return _manifest_show(rest)
    print(f"[manifest] unknown subcommand: {sub!r}", file=sys.stderr)
    print(_MANIFEST_USAGE, file=sys.stderr)
    return 2


def _manifest_init(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="dontpanic manifest init",
        add_help=True,
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing manifest. Requires --yes for non-interactive use.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        dest="yes",
        help="Skip confirmation prompt. Required with --force.",
    )
    parser.add_argument(
        "--cli-path",
        default="dontpanic",
        help="Path to the dontpanic CLI binary (default: 'dontpanic').",
    )
    parser.add_argument(
        "--install-source",
        choices=["pipx", "pip-editable", "source"],
        default="source",
        help="Where this DontPanic install came from (default: 'source').",
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)

    if args.force and not args.yes:
        # Non-interactive safety rail — same shape as `projects add` (D008
        # of plan 2026-05-03-001). Destructive intent is two-flag, not
        # one-flag-with-prompt, so the surface stays scriptable.
        print(
            "[manifest init] --force requires --yes for non-interactive use",
            file=sys.stderr,
        )
        return 2

    existing = agent_manifest.manifest_path()
    if existing.is_file() and not args.force:
        print(
            f"[manifest init] manifest already exists at {existing}; "
            f"pass --force --yes to overwrite",
            file=sys.stderr,
        )
        return 2

    manifest = agent_manifest.bootstrap_manifest(
        install_source=args.install_source,
        cli_path=args.cli_path,
    )
    agent_manifest.write_manifest(manifest)

    payload = {
        "action": "wrote",
        "manifest": agent_manifest.to_public_dict(manifest),
    }
    if args.as_json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(f"[manifest init] wrote {existing}")
    return 0


def _manifest_show(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="dontpanic manifest show",
        add_help=True,
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)

    manifest = agent_manifest.load_manifest()
    if manifest is None:
        print(
            f"[manifest show] manifest not found at "
            f"{agent_manifest.manifest_path()}; run "
            "`dontpanic manifest init` first",
            file=sys.stderr,
        )
        return 2

    payload = agent_manifest.to_public_dict(manifest)
    # Default `show` already prints structured JSON (operators asked for
    # "readable JSON"); --json is the same shape, kept explicit so agents
    # parsing the output don't depend on default semantics.
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    _ = args  # parser ran for --help / unknown-arg validation; flag itself unused.
    return 0


def _mcp_main(argv: list[str]) -> int:
    """Plan 2026-05-03-003 F002: ``dontpanic mcp serve`` thin local MCP server.

    Phase B is local-only (D003). ``serve`` is the only subcommand; it runs
    the stdio JSON-RPC loop. The future ``tools`` introspection subcommand
    is reserved but intentionally not implemented in F002 so the surface
    stays minimal.
    """
    return mcp_server.main(argv)


def _calibrate_claude_main(argv: list[str]) -> int:
    """Plan 2026-04-30-001 F005: write Claude calibration ratio to the sticky
    file at ~/.jarvis/quota_calibration.json so F006 can convert the local
    weighted_tokens_local_proxy signal into a comparable percent_of_plan number.

    Reads observed_native from the requested window of the current
    ~/.jarvis/quota_state.json. The operator supplies the matching dashboard
    percent (claude.ai/settings/usage). Ratio = dashboard_pct / observed_native.
    """
    parser = argparse.ArgumentParser(
        prog="dontpanic calibrate-claude",
        description=__doc__,
    )
    parser.add_argument(
        "--dashboard-pct",
        type=float,
        required=True,
        help=(
            "Current weekly% (rolling_7d) or session% (rolling_5h) shown on "
            "claude.ai/settings/usage. Must be in (0, 100]."
        ),
    )
    parser.add_argument(
        "--window",
        default="rolling_7d",
        choices=sorted(calibration_loader.SUPPORTED_WINDOWS),
        help="Window to calibrate (default: rolling_7d).",
    )
    args = parser.parse_args(argv)

    # Read the corresponding observed_native from current quota state. We need
    # the latest tracker output; if missing, ask operator to refresh first.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    try:
        import quota_check  # noqa: F401  # presence check: validates scripts/ is on sys.path
    except ImportError as exc:
        print(f"[calibrate-claude] failed to import quota_check: {exc}", file=sys.stderr)
        return 2

    state_path = Path.home() / ".jarvis" / "quota_state.json"
    if not state_path.is_file():
        print(
            f"[calibrate-claude] {state_path} missing; run "
            "`python3 scripts/quota_check.py` first to generate it",
            file=sys.stderr,
        )
        return 2
    try:
        import json as _json

        state = _json.loads(state_path.read_text())
    except (OSError, _json.JSONDecodeError) as exc:
        print(f"[calibrate-claude] failed to read quota_state: {exc}", file=sys.stderr)
        return 2

    claude_block = state.get("vendors", {}).get("claude", {})
    window_block = claude_block.get("windows", {}).get(args.window, {})
    observed_native = window_block.get("observed_native")
    if not isinstance(observed_native, (int, float)) or observed_native <= 0:
        print(
            f"[calibrate-claude] vendors.claude.windows.{args.window}.observed_native "
            f"is missing or zero in {state_path}; refresh tracker first or pick the "
            "other window. Calibrating against zero observed is meaningless.",
            file=sys.stderr,
        )
        return 2

    try:
        entry = calibration_loader.write_calibration(
            vendor="claude",
            window=args.window,
            dashboard_pct=args.dashboard_pct,
            observed_native=float(observed_native),
        )
    except calibration_loader.CalibrationError as exc:
        print(f"[calibrate-claude] {exc}", file=sys.stderr)
        return 2

    print(
        f"[calibrate-claude] wrote {calibration_loader.CALIBRATION_FILE}\n"
        f"  vendor=claude window={args.window}\n"
        f"  dashboard_pct={entry['dashboard_pct']}  observed_native={int(entry['observed_native'])}\n"
        f"  ratio={entry['ratio']:.6e}  confidence={entry['confidence']}\n"
        f"  stamped_at={entry['stamped_at']}\n"
        "Re-run `python3 scripts/quota_check.py` to see the calibrated state."
    )
    return 0


# ────────────────────────  dontpanic doctor (F003)  ──────────────────────────


def _doctor_main(argv: list[str]) -> int:
    """Plan 2026-05-03-001 F003: ``dontpanic doctor`` wraps
    ``scripts/jarvis_doctor.py`` so users have a single console-script
    entry point. Includes per-project preflight by default and uses the
    strict 0/1/2 exit-code matrix.

    The bare script (``python3 scripts/jarvis_doctor.py``) keeps its
    legacy 0/1 contract and skips per-project checks unless the operator
    explicitly opts in via ``--include-projects --strict-codes``. This
    wrapper is the new canonical surface; the legacy script remains for
    backward compatibility per AC#5.
    """
    # F005: diagnostic-class agent-guidance footer, projected from the F002
    # inventory (run diagnostics before changing config or dispatching work).
    from dontpanic_orchestrate import command_guidance

    parser = argparse.ArgumentParser(
        prog="dontpanic doctor",
        description=(
            "Run the full doctor battery (structural + auth + per-project "
            "preflight). Output structured PASS / WARN / FAIL per check; "
            "exit 0 if all PASS, 1 if any WARN, 2 if any FAIL."
        ),
        epilog=command_guidance.command_help_agent_snippet("doctor"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Machine-readable output (mirrors the legacy script's shape).",
    )
    parser.add_argument(
        "--skip-auth",
        action="store_true",
        help="Omit gcloud-auth + firebase-auth probes (CI / fresh-clone mode).",
    )
    parser.add_argument(
        "--validate-plans",
        action="store_true",
        help=(
            "Plan 2026-05-12-001 F001 (D024): cross-check every plan's "
            "child_charter.allowed_paths against feature-step paths and "
            "flag acceptance items that name credentialed resources when "
            "parent_acceptance_item defers them. Advisory WARN findings."
        ),
    )
    parser.add_argument(
        "--validate-plans-strict",
        action="store_true",
        help=(
            "Plan 2026-05-19-003 F003: promote the strict jsonschema "
            "plan-validation probe from advisory (WARN) to blocker (FAIL). "
            "When set, any locked plan that fails to validate against the "
            "v1.9 plan schema produces exit 2 under the strict-codes matrix."
        ),
    )
    parser.add_argument(
        "--architecture-drift-strict",
        action="store_true",
        help=(
            "Plan 2026-05-19-004 F003: promote the architecture-drift "
            "probe from advisory (WARN) to blocker (FAIL). When set, a "
            "stale_major drift or absent architecture.json produces exit "
            "2 under the strict-codes matrix. stale_minor stays advisory."
        ),
    )
    parser.add_argument(
        "--plans-root",
        type=Path,
        default=None,
        help=(
            "Plan 2026-05-19-005 F001: override the plans root walked by "
            "validate-plans-strict. Default = <repo>/docs/plans. Enables "
            "the showcase generator (and operators) to validate plan "
            "inventories in external checkouts without copying runtime code."
        ),
    )
    parser.add_argument(
        "--architecture-json",
        type=Path,
        default=None,
        help=(
            "Plan 2026-05-19-005 F001: override the architecture.json path "
            "the drift probe reads. Default = <repo>/docs/architecture/"
            "architecture.json. Enables drift evaluation against an "
            "external snapshot."
        ),
    )
    # Plan 2026-05-19-002 F004-i1 fix: --profile + --profile-strict + --report
    # + --report-path must be available on the console-script entry too,
    # not just on the bare scripts/dontpanic_doctor.py. Both surfaces share
    # the same flag namespace.
    parser.add_argument(
        "--profile",
        type=str,
        default=None,
        choices=("core", "discord", "firebase-dashboard", "openclaw", "ci"),
        help=(
            "Plan 2026-05-19-002 F001: run the profile-aware prereq probe "
            "sweep. When omitted, doctor runs the legacy CheckResult "
            "pipeline unchanged."
        ),
    )
    parser.add_argument(
        "--profile-strict",
        action="store_true",
        help=("Plan 2026-05-19-002 F001: promote WARN -> FAIL under the selected --profile."),
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help=(
            "Plan 2026-05-19-002 F004: render docs/install-report.html "
            "(self-contained HTML5; mobile-responsive). Requires --profile."
        ),
    )
    parser.add_argument(
        "--report-path",
        type=Path,
        default=None,
        help=(
            "Plan 2026-05-19-002 F004: override the install-report output "
            "path. Default = <repo>/docs/install-report.html."
        ),
    )
    parser.add_argument(
        "--agent",
        action="store_true",
        help=(
            "Plan 2026-05-30-001 F005: validate the machine onboarding layer "
            "(CLI, agent-manifest, registered executors, global roles.*) and "
            "list registered worker executors."
        ),
    )
    parser.add_argument(
        "--project",
        type=str,
        default=None,
        metavar="NAME_OR_PATH",
        help=(
            "Plan 2026-05-30-001 F005: validate ONE project's onboarding "
            "(config / agents / roles.* / managed AGENTS.md block) by "
            "registry name or filesystem path."
        ),
    )
    args = parser.parse_args(argv)

    # Lazy import: scripts/ may not be on sys.path when the console script
    # is installed via pipx. Add it before importing jarvis_doctor.
    # ``jarvis_doctor`` is a thin alias that re-exports the canonical
    # ``dontpanic_doctor`` API; tests pre-populate sys.modules['jarvis_doctor']
    # to swap in stubbed run_all_checks, so we keep the import name as-is.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    try:
        import jarvis_doctor as jd  # type: ignore[import-not-found]
    finally:
        sys.path.pop(0)

    # F001 + F004 path: --profile (with optional --report) delegates to
    # the canonical jd.main() driver. This keeps the profile-aware
    # render_text/render_json + report wiring in one place rather than
    # forking the logic between cli.py and dontpanic_doctor.py.
    if args.profile is not None or args.report:
        return jd.main(argv)

    # Plan 2026-05-30-001 F005: the agent / project onboarding surfaces are
    # owned by jd.main (single place for render + strict-exit). Delegate the
    # raw argv so the new flags + their 0/1/2 matrix flow through unchanged.
    if args.agent or args.project is not None:
        return jd.main(argv)

    results = jd.run_all_checks(
        skip_auth=args.skip_auth,
        include_projects=True,
        validate_plans=args.validate_plans,
        validate_plans_strict_mode=args.validate_plans_strict,
        architecture_drift_strict_mode=args.architecture_drift_strict,
        plans_root=args.plans_root,
        architecture_json=args.architecture_json,
    )
    print(jd.render_json(results) if args.json else jd.render_text(results))
    # Plan 4 F003 / Plan 3 F003 acceptance: in advisory mode the
    # validate-plans-strict and architecture-drift probes emit WARN findings
    # but those must NOT escalate the canonical exit code (acceptance says
    # advisory → exit 0 when no other probe fails). Strict mode keeps
    # WARN→1/FAIL→2 behavior so a malformed plan / major drift still blocks.
    # Probe-specific override per codex-auditor Plan 3 F003 i1 finding.
    exit_inputs = list(results)
    if not args.validate_plans_strict:
        exit_inputs = [
            r
            for r in exit_inputs
            if r.name != "validate-plans-strict" and not r.name.startswith("validate-plans-strict:")
        ]
    if not args.architecture_drift_strict:
        exit_inputs = [r for r in exit_inputs if r.name != "architecture-drift"]
    # Plan 2026-05-23-004 F005: dashboard readiness probes
    # (dashboard-files, dashboard-cache, dashboard-state) are V0
    # advisory-only — a missing dashboard cache must not escalate the
    # canonical exit code. Strip them from the strict-exit computation
    # unconditionally; the WARN text + remediation still renders.
    exit_inputs = [
        r for r in exit_inputs if not r.name.startswith("dashboard-")
    ]
    # 2026-06-03-001 agent-command-surface: the skill-rubrics probe is
    # self-describing advisory ("core use is not blocked") — a high-value
    # skill missing an invocation rubric is guidance, not a readiness
    # blocker, so it must not escalate the canonical exit code either.
    exit_inputs = [
        r for r in exit_inputs if not r.name.startswith("skill-rubrics")
    ]
    return jd.compute_strict_exit(exit_inputs)


# ──────────────────────────  dispatch-from-plan (F002)  ──────────────────────────


# Remediation lines surfaced by --confirm when readiness is non-ok. Kept here
# (not in supervisor or quota_caps_loader) because the strings are CLI-shaped:
# they reference the other `python -m dontpanic_orchestrate ...` subcommands the
# operator would run from the same shell. Test acceptance pins each substring.
_READINESS_REMEDIATION: dict[str, str] = {
    "config_required": (
        "Remediation: run `python -m dontpanic_orchestrate quota-caps init` "
        "(or edit ~/.jarvis/quota_caps.json if already present)."
    ),
    "calibration_required": (
        "Remediation: run `python -m dontpanic_orchestrate calibrate-claude "
        "--dashboard-pct N` after sampling claude.ai/settings/usage."
    ),
    "unit_mismatch": (
        "Remediation: edit ~/.jarvis/quota_caps.json so each cap.unit matches "
        "what `quota_check.py` reports as observed_unit for that vendor/window."
    ),
    "missing_state": (
        "Remediation: run `python scripts/quota_check.py` to populate ~/.jarvis/quota_state.json."
    ),
}


def _read_quota_state_for_readiness() -> dict | None:
    """Honor JARVIS_QUOTA_STATE_PATH for hermetic test isolation; mirrors the
    convention in circuit_breakers._read_quota_state. Returns None when the
    file is missing OR malformed OR has no vendors{} block — all three reduce
    to readiness=missing_state because dispatch_volley needs vendors{} for
    its quota gate."""
    import json
    import os

    env_override = os.environ.get("JARVIS_QUOTA_STATE_PATH")
    p = Path(env_override) if env_override else (Path.home() / ".jarvis" / "quota_state.json")
    if not p.is_file():
        return None
    try:
        state = json.loads(p.read_text())
    except (OSError, ValueError):
        return None
    vendors = state.get("vendors")
    if not isinstance(vendors, dict) or not vendors:
        return None
    return state


def _compute_readiness(*, implementer: str, auditor: str) -> tuple[str, str | None]:
    """Reduce per-agent collect_agent_coverage outcomes into one of:

      ok / config_required / calibration_required / unit_mismatch / missing_state

    Order of precedence when impl/auditor disagree: alphabetical by agent name
    (matches `_check_budget_v2`'s sorted-iteration). Returns
    (label, summary_line). For label=ok the summary line is `claude=N% / codex=N%`
    formatted from primary.pct_of_cap; for non-ok it is None.

    TRIPPED is not a readiness label (the plan enumerates 5 states, none are
    "tripped"): a tripped quota is a runtime concern that supervisor.dispatch_volley
    handles via its own breaker, not a config issue the operator must fix
    before invoking this CLI.
    """
    state = _read_quota_state_for_readiness()
    if state is None:
        return "missing_state", None

    try:
        caps = quota_caps_loader.load()
    except quota_caps_loader.QuotaCapsError as exc:
        return "config_required", str(exc)

    vendors = state.get("vendors") or {}
    agents = sorted({implementer, auditor})
    primary_pct: dict[str, int] = {}
    config_details: list[str] = []
    for agent in agents:
        report = cb.collect_agent_coverage(agent=agent, vendors=vendors, caps=caps)
        if report.terminal is not None:
            outcome = report.terminal.outcome
            if outcome == cb.WindowOutcome.CALIBRATION_REQUIRED:
                return "calibration_required", None
            if outcome == cb.WindowOutcome.UNIT_MISMATCH:
                return "unit_mismatch", None
            # TRIPPED: fall through, dispatch_volley owns the runtime breaker
        if report.config_cause is not None:
            if report.config_cause == "missing_vendor_block":
                config_details.append(
                    f"{agent}: missing quota_state vendor block; run `python scripts/quota_check.py`"
                )
            else:
                for ev in report.evaluations:
                    if ev.outcome == cb.WindowOutcome.NO_CAP:
                        config_details.append(
                            f"{ev.agent}.{ev.tier}.{ev.window}: add cap in ~/.jarvis/quota_caps.json "
                            f"(observed {int(ev.observed_native or 0)} {ev.observed_unit})"
                        )
                if not config_details:
                    config_details.append(f"{agent}: quota cap configuration incomplete")
            return "config_required", "; ".join(config_details)
        if report.primary is not None and report.primary.pct_of_cap is not None:
            primary_pct[agent] = int(round(report.primary.pct_of_cap * 100))

    summary = " / ".join(f"{a}={primary_pct.get(a, 0)}%" for a in agents)
    return "ok", summary


def _print_preflight_block(
    *,
    plan_dir: Path,
    feature_id: str,
    tier: str,
    target_env: str,
    target_project: str | None,
    implementer: str,
    auditor: str,
    human_gates: list[str],
    max_iterations: int | None,
    readiness: str,
    readiness_summary: str | None,
) -> None:
    """Print the 10 required fields in declared order. The list rendering
    (gates, target_project=None) is intentionally simple — operator review
    explicitly preferred a flat printable block over a tree/yaml dump so it
    pastes cleanly into Discord (Plan B) and INBOX entries."""
    print("[dispatch-from-plan] pre-flight context")
    print(f"  plan_path:      {plan_dir}")
    print(f"  feature:        {feature_id}")
    print(f"  tier:           {tier}")
    print(f"  target_env:     {target_env}")
    project_render = target_project if target_project is not None else "(none)"
    print(f"  target_project: {project_render}")
    print(f"  implementer:    {implementer}")
    print(f"  auditor:        {auditor}")
    gates_render = ",".join(human_gates) if human_gates else "(none)"
    print(f"  human_gates:    {gates_render}")
    iters_render = str(max_iterations) if max_iterations is not None else "(plan default)"
    print(f"  max_iterations: {iters_render}")
    print(f"  quota_readiness: {readiness}")
    if readiness_summary:
        print(f"    {readiness_summary}")


def _dispatch_from_plan_main(argv: list[str]) -> int:
    """F002 — strict-dry-run pre-flight wrapper around supervisor.dispatch_volley.

    Without `--confirm`: print the 10-field block, exit 0. Always. No TTY-
    conditional branching, no interactive prompt — deferred to D006 `--ask`.

    With `--confirm`: gate on quota readiness == ok, then call
    supervisor.dispatch_volley(...) IN-PROCESS with the same forwarded kwargs
    the existing top-level CLI surfaces. Same module, same enforcement, same
    audit/INBOX/transcript artifacts.
    """
    # F005: dispatch/paid-class agent-guidance footer, projected from the F002
    # inventory so the help says not to auto-run paid dispatch unless DontPanic
    # surfaced a ready candidate or the human explicitly approved it. Appended
    # to the existing quota-readiness epilog rather than restated inline.
    from dontpanic_orchestrate import command_guidance

    parser = argparse.ArgumentParser(
        prog="dontpanic dispatch-from-plan",
        description=(
            "Strict-dry-run pre-flight wrapper. Prints 10-field context block "
            "and exits 0; pass --confirm to actually dispatch in-process via "
            "supervisor.dispatch_volley."
        ),
        epilog=(
            "Quota readiness states that block --confirm (exit 3):\n"
            "  missing_state         ~/.jarvis/quota_state.json absent or unreadable\n"
            "                        → run: python scripts/quota_check.py\n"
            "  config_required       caps file or vendor block missing\n"
            "                        → run: python -m dontpanic_orchestrate quota-caps init\n"
            "                          (or edit ~/.jarvis/quota_caps.json if vendor entry missing)\n"
            "  calibration_required  Claude window has percent_of_plan cap with non-manual confidence\n"
            "                        → run: python -m dontpanic_orchestrate calibrate-claude --dashboard-pct N\n"
            "  unit_mismatch         non-Claude vendor cap.unit ≠ observed_unit\n"
            "                        → edit ~/.jarvis/quota_caps.json so cap.unit matches observed_unit\n"
            "Stale calibration is warning-only (not blocking). Dry-run mode prints the\n"
            "label without refusal.\n\n"
            + command_guidance.command_help_agent_snippet("dispatch-from-plan")
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "plan", help="Plan ID (resolved against ./docs/plans/) or absolute dir path"
    )
    parser.add_argument("--feature", default="F001", help="Feature ID (default F001)")
    parser.add_argument(
        "--implementer", default=None, help="Implementer agent (default: agents_required[0])"
    )
    parser.add_argument(
        "--auditor", default=None, help="Auditor agent (default: agents_required[1])"
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=None,
        help="Override loop_caps.max_iterations",
    )
    parser.add_argument(
        "--mode",
        default=None,
        choices=["interactive", "autonomous"],
        help=(
            "Runtime dispatch class override. interactive=bypass admission gates; "
            "autonomous=enforce. P0 is plan-derived only and cannot be forced. "
            "Default: derived from plan.tier."
        ),
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help=(
            "Commit to in-process dispatch_volley. Without this flag, "
            "dispatch-from-plan is a strict dry-run."
        ),
    )
    # Plan 2026-05-01-004 F003: patch-completeness gate operator overrides.
    # Layer A — argparse validates the >=8 char minimum; layer B in
    # patch_completeness_gate.validate_reason re-validates programmatically.
    parser.add_argument(
        "--allow-incomplete-patch",
        type=_validate_patch_reason("--allow-incomplete-patch"),
        default=None,
        metavar="REASON",
        help=(
            "Override the patch-completeness gate even when block-severity "
            "findings are present. REASON must be >=8 non-whitespace chars; "
            "lands verbatim in signoff.json under patch_completeness.override_reason."
        ),
    )
    parser.add_argument(
        "--unrelated-dirty-state-note",
        type=_validate_patch_reason("--unrelated-dirty-state-note"),
        default=None,
        metavar="REASON",
        help=(
            "Acknowledge unstaged-modified files outside the plan's touched "
            "set. REASON must be >=8 non-whitespace chars; lands verbatim in "
            "signoff.json under patch_completeness.unrelated_dirty_state_note."
        ),
    )
    # Plan 2026-06-01-001 F007: pre-dispatch sizing gate operator override.
    # Reuses the >=8-char layer-A validator the patch-completeness overrides
    # use; the rationale lands in evidence/plan-review/pre_dispatch/.
    parser.add_argument(
        "--allow-oversize",
        type=_validate_patch_reason("--allow-oversize"),
        default=None,
        metavar="REASON",
        help=(
            "Override the pre-dispatch sizing gate even when the target "
            "feature carries a block-severity size flag. REASON must be >=8 "
            "non-whitespace chars; lands verbatim in "
            "evidence/plan-review/pre_dispatch/<feature>-oversize-override.json."
        ),
    )
    # Plan 2026-06-01-001 F008: cross-feature-edit acknowledgement override.
    # Reuses the >=8-char layer-A validator; the rationale lands in
    # evidence/plan-review/cross_feature/<feature>-cross-feature-ack.json.
    parser.add_argument(
        "--acknowledge-cross-feature",
        type=_validate_patch_reason("--acknowledge-cross-feature"),
        default=None,
        metavar="REASON",
        help=(
            "Acknowledge a legitimate edit to files owned by another feature, "
            "passing the patch-completeness cross-feature-edit gate. REASON "
            "must be >=8 non-whitespace chars; lands verbatim in "
            "evidence/plan-review/cross_feature/<feature>-cross-feature-ack.json."
        ),
    )
    args = parser.parse_args(argv)

    # Plan resolution. Distinct exit code (2) from the dispatch path so
    # operator wrappers (Discord, cron) can disambiguate "plan invalid" from
    # "quota blocked". F003: route through the shared resolver so registered
    # projects' per-project ``plans_dir`` is honored, not just hardcoded
    # ``./docs/plans/``.
    plan_arg = args.plan
    try:
        plan_dir_candidate = _resolve_plan_dir(plan_arg)
    except SystemExit:
        print(
            f"[dispatch-from-plan] plan not found: {plan_arg!r} "
            "(checked literal path, registered projects' plans_dir, and "
            "./docs/plans/)",
            file=sys.stderr,
        )
        return 2

    try:
        loaded = plan_loader.load(plan_dir_candidate)
    except (FileNotFoundError, ValueError) as exc:
        # plan_loader raises ValueError for schema/frontmatter problems and
        # FileNotFoundError for missing plan.md / features.json. Both are
        # exit-2 ("plan resolution / schema validation error") per the plan.
        print(f"[dispatch-from-plan] plan validation failed: {exc}", file=sys.stderr)
        return 2

    plan_dir = loaded.plan_dir
    plan = loaded.plan

    # Resolve impl/auditor with the same fallback dispatch_volley uses, so
    # the printed defaults match what dispatch will actually run with.
    # F003: chain is CLI arg > plan.agents_required > per-project config >
    # global config > hardcoded.
    agents_req = list(plan.agents_required or [])
    project_match = project_config.find_project_for_plan_dir(plan_dir)
    project_path_for_resolve = project_match[0] if project_match else None
    resolved_defaults = project_config.resolve_dispatch_defaults(project_path_for_resolve)
    plan_impl = str(agents_req[0]).split(".")[-1] if agents_req else None
    plan_aud = str(agents_req[1]).split(".")[-1] if len(agents_req) >= 2 else None
    impl = args.implementer or plan_impl or resolved_defaults["implementer"]
    aud = args.auditor or plan_aud or resolved_defaults["auditor"]

    human_gates = [g.value if hasattr(g, "value") else str(g) for g in (plan.human_gates or [])]
    loop_caps = plan.loop_caps
    plan_max_iter = loop_caps.max_iterations if loop_caps is not None else None
    effective_max_iter = args.max_iterations if args.max_iterations is not None else plan_max_iter

    readiness, readiness_summary = _compute_readiness(implementer=impl, auditor=aud)

    _print_preflight_block(
        plan_dir=plan_dir,
        feature_id=args.feature,
        tier=str(plan.tier.value if hasattr(plan.tier, "value") else plan.tier),
        target_env=loaded.target_env,
        target_project=loaded.target_project,
        implementer=impl,
        auditor=aud,
        human_gates=human_gates,
        max_iterations=effective_max_iter,
        readiness=readiness,
        readiness_summary=readiness_summary,
    )

    # Plan 2026-06-01-001 F009 — actionable config-readiness pre-flight, distinct
    # from the quota-readiness/budget machinery above. Validates the quota-caps
    # config file AND the resolved role values BEFORE any paid work, turning a
    # malformed `{}` caps file (D039) or a bad role (D065 Grok-Builder split-brain)
    # into a clean, actionable stop with a runnable remediation — never a raw
    # schema crash mid-volley. Printed in both modes; enforced only on --confirm.
    from dontpanic_orchestrate import config_readiness as _config_readiness
    from dontpanic_orchestrate.executors import AGENT_REGISTRY as _AGENT_REGISTRY

    config_ready = _config_readiness.check_config_readiness(
        roles=[impl, aud], registered_executors=set(_AGENT_REGISTRY)
    )
    if config_ready.ok:
        print("[dispatch-from-plan] config-readiness: ok")
    else:
        print(f"[dispatch-from-plan] config-readiness: NOT READY ({config_ready.file})")

    # Plan 2026-06-01-001 F007 — pre-dispatch sizing gate. Run the F001 sizing
    # lint over the TARGET feature in the pre-flight (acceptance #1), in both
    # dry-run and confirm modes, and print the verdict. The refusal itself is
    # enforced only on the --confirm path, before the volley starts; the
    # decision depends only on size flags so the (free, pure) lint needs no
    # resolver wiring. A feature id the plan doesn't declare yet is skipped
    # here — dispatch_volley surfaces that error on the confirm path.
    from dontpanic_orchestrate.plan_review import sizing_gate

    sizing_result = None
    try:
        target_feature = loaded.feature(args.feature)
    except KeyError:
        print(
            f"[dispatch-from-plan] sizing-lint: feature {args.feature!r} not in "
            f"{loaded.plan_id}; skipping size check"
        )
    else:
        sizing_result = sizing_gate.evaluate_feature(target_feature)
        print(sizing_gate.render_preflight(sizing_result))

    if not args.confirm:
        # Strict dry-run. Always exit 0 — no TTY check, no interactive prompt.
        # The plan's D006 leaves room for a future `--ask` flag; this branch
        # holds firm so automation (Discord / cron) sees deterministic
        # exit-0-and-print behavior.
        # Plan 2026-05-01-004 F003 D009: in dry-run, run the patch-
        # completeness gate against the current working tree so the operator
        # previews what the post-volley enforcement would surface. Findings
        # render to stdout; gate never raises in dry-run.
        try:
            preview_state = git_state.capture(plan_dir)
        except Exception:  # defensive — capture is documented best-effort
            preview_state = None
        if preview_state is not None:
            affected = getattr(plan, "affected_paths", None) or []
            try:
                preview_block = patch_completeness_gate.enforce(
                    plan_dir,
                    plan_id=loaded.plan_id,
                    iteration=0,
                    role="implementer",
                    audit_paths=[],
                    affected_paths=list(affected) if affected else None,
                    repo_root=plan_dir,
                    allow_incomplete_patch_reason=args.allow_incomplete_patch,
                    unrelated_dirty_state_note=args.unrelated_dirty_state_note,
                    dry_run=True,
                    git_state_override=preview_state,
                )
            except ValueError as exc:
                # Layer-B reject of a malformed reason (shouldn't happen
                # because argparse layer-A already validated, but kept for
                # defense-in-depth). Surface as exit-2 to mirror argparse.
                print(f"[dispatch-from-plan] {exc}", file=sys.stderr)
                return 2
            if preview_block is not None:
                print(
                    f"[dispatch-from-plan] patch-completeness preview: "
                    f"status={preview_block['status']} "
                    f"findings={len(preview_block['findings'])}"
                )
                for finding in preview_block["findings"]:
                    print(
                        f"  {finding['mode']} | {finding['severity']} | "
                        f"{','.join(finding['files'])} | {finding['recommendation']}"
                    )
        return 0

    if readiness != "ok":
        remediation = _READINESS_REMEDIATION.get(readiness, "")
        print(
            f"[dispatch-from-plan] BLOCKED: quota readiness={readiness!r}; refusing to dispatch.",
            file=sys.stderr,
        )
        if remediation:
            print(remediation, file=sys.stderr)
        if readiness_summary:
            print(f"Detail: {readiness_summary}", file=sys.stderr)
        return 3

    # Plan 2026-06-01-001 F009 — config-readiness enforcement. A malformed caps
    # config or an invalid role is refused with the actionable message + runnable
    # remediation before any paid call (exit 6, distinct from quota=3 / patch=4 /
    # sizing=5), so the operator is never stranded by a low-level schema crash.
    if not config_ready.ok:
        print(
            f"[dispatch-from-plan] BLOCKED: config not ready.\n{config_ready.render()}",
            file=sys.stderr,
        )
        return 6

    # Plan 2026-06-01-001 F007 — pre-dispatch sizing gate enforcement. Runs
    # AFTER the existing quota-readiness check (acceptance #4 — existing checks
    # still run) but BEFORE supervisor.dispatch_volley, so an over-budget
    # feature is refused before any paid work. An explicit --allow-oversize
    # reason records the rationale and proceeds (acceptance #3); otherwise the
    # F002 split proposal is surfaced as the remediation and dispatch is
    # refused with a dedicated exit code (5) so operator wrappers can
    # disambiguate a sizing block from quota (3) / patch-completeness (4).
    if sizing_result is not None and sizing_result.is_blocked:
        if args.allow_oversize is None:
            print(
                sizing_gate.render_block_message(sizing_result), file=sys.stderr
            )
            return 5
        override_path = sizing_gate.record_override(
            plan_dir,
            plan_id=loaded.plan_id,
            feature_id=sizing_result.feature_id or args.feature,
            reason=args.allow_oversize,
            result=sizing_result,
        )
        print(
            "[dispatch-from-plan] sizing gate OVERRIDDEN "
            f"(--allow-oversize); rationale recorded to {override_path}"
        )

    # In-process hand-off. NO subprocess shell-out — same interpreter, same
    # supervisor module, same active_supervisors registry entry, same
    # audit/INBOX/transcript files. The dispatch_from_plan wrapper is purely
    # a pre-flight + readiness check on top of dispatch_volley.
    print(
        f"[dispatch-from-plan] readiness=ok; dispatching {loaded.plan_id} via supervisor.dispatch_volley"
    )
    try:
        result = supervisor.dispatch_volley(
            plan_dir=plan_dir,
            feature_id=args.feature,
            implementer_agent=args.implementer,
            auditor_agent=args.auditor,
            max_iterations=args.max_iterations,
            mode=args.mode,
            allow_incomplete_patch_reason=args.allow_incomplete_patch,
            unrelated_dirty_state_note=args.unrelated_dirty_state_note,
            # Plan 2026-06-01-001 F008 — cross-feature-edit acknowledgement.
            cross_feature_ack_reason=args.acknowledge_cross_feature,
            # Plan 2026-05-08-003 F002 — operator-initiated CLI dispatch
            # is the canonical "direct dispatch" surface that the narrow
            # pre_impl auto-clear targets.
            direct_dispatch=True,
        )
    except PatchCompletenessError as exc:
        # Plan 2026-05-01-004 F003: dedicated exit code (4) so operator
        # wrappers can disambiguate "patch incomplete" from quota / generic
        # failures.
        print(f"[dispatch-from-plan] BLOCKED by patch-completeness gate:\n{exc}", file=sys.stderr)
        return 4
    except QuotaExceeded as exc:
        print(f"[dispatch-from-plan] BLOCKED by quota gate: {exc}", file=sys.stderr)
        return 2
    except (FileNotFoundError, KeyError, ValueError, RuntimeError) as exc:
        print(f"[dispatch-from-plan] ERROR: {exc}", file=sys.stderr)
        return 1

    print(
        f"\n[dispatch-from-plan] volley terminal: {result.final_status} "
        f"after {result.rounds} round(s)"
    )
    print(f"[dispatch-from-plan] reason: {result.reason}")
    print(f"[dispatch-from-plan] {len(result.audit_paths)} audit JSONs written")
    return 0 if result.final_status == "signed_off" else 3


def _plan_main(argv: list[str]) -> int:
    """Top-level dispatch for ``dontpanic plan <subcommand>``.

    Subcommands:
      ``lock``    — F1 / F004: pre-impl sufficiency gate + draft → active flip.
      ``audit``   — F2 / F003: post-impl audit-only entry. Runs the F1+F002+F0
                    pipeline and prints the decision. No mutation.
      ``close``   — F2 / F003: post-impl close gate + active → completed flip.
                    Refuses on blocking decision unless --ignore-completion-
                    findings <reason> is supplied (operator override is
                    recorded to evidence/goal-governance/post_impl/override.json).

    Future plan-scoped subcommands (``plan show``, ``plan validate``, etc.)
    attach here so the surface stays single-namespace and discoverable.
    """
    if not argv or argv[0] in ("-h", "--help"):
        print(
            "usage: dontpanic plan <subcommand>\n\n"
            "subcommands:\n"
            "  lock <plan-dir> [--ignore-sufficiency-findings <reason>]\n"
            "      Run the pre-impl sufficiency gate (Goal Governance V1 F004)\n"
            "      and flip plan.md status from draft → active. Refuses if the\n"
            "      gate finds blocking findings unless --ignore-sufficiency-\n"
            "      findings <reason> is supplied (operator override is recorded\n"
            "      to evidence/goal-governance/pre_impl/override.json).\n"
            "  audit <plan-dir>\n"
            "      Run the post-impl completion audit (F001 + F002 + F0\n"
            "      classifier) and print the decision. No status flip.\n"
            "  close <plan-dir> [--dry-run] [--ignore-completion-findings <reason>]\n"
            "      Run the post-impl gate and flip plan.md status from active\n"
            "      → completed. Refuses on blocking decision unless --ignore-\n"
            "      completion-findings <reason> is supplied (operator override\n"
            "      is recorded to evidence/goal-governance/post_impl/override.json).\n"
            "  resync <plan-dir>\n"
            "      Retry any failed/pending entries in evidence/external_sync.json\n"
            "      via the registered category adapters. Idempotent — already-\n"
            "      pushed entries are skipped. Plan 2026-05-20-001 F002.\n"
            "  disposition <plan-dir> --finding <id> --kind <kind> [--reason] [--followup]\n"
            "      Record a per-finding sufficiency disposition against the latest\n"
            "      audit round (convergence policy, plan 2026-06-09-002). Resolves\n"
            "      eligible findings WITHOUT another paid audit. Kinds:\n"
            "      accepted_into_plan / deferred_to_impl / waived_with_reason /\n"
            "      split_to_followup_plan.\n"
            "  worktree <create|list>\n"
            "      Per-plan git worktree isolation (plan 2026-06-10-002): create a\n"
            "      bound plan worktree from the repo's default branch, or render\n"
            "      the worktree-status model (branch, dirty, health, owner).",
            file=sys.stderr,
        )
        return 2
    sub = argv[0]
    rest = argv[1:]
    if sub == "lock":
        return _plan_lock_main(rest)
    if sub == "audit":
        return _plan_audit_main(rest)
    if sub == "close":
        return _plan_close_main(rest)
    if sub == "resync":
        return _plan_resync_main(rest)
    if sub == "disposition":
        return _plan_disposition_main(rest)
    if sub == "worktree":
        return _plan_worktree_main(rest)
    print(f"dontpanic plan: unknown subcommand {sub!r}", file=sys.stderr)
    return 2


def _plan_worktree_main(argv: list[str]) -> int:
    """``dontpanic plan worktree create|list|remove`` — Worktree Isolation
    v0 (plan 2026-06-10-002) + guard-hardening F002 removal (plan
    2026-06-11-001). These are worktree-MANAGEMENT commands: deliberately
    OUTSIDE the wrong-worktree guard (they operate on bindings by plan id
    from any checkout) and protected by their own preconditions — strict
    registry load, binding_health, full-policy cleanliness. There is NO
    force flag on this surface."""
    from dontpanic_orchestrate import worktrees as _wt

    if not argv or argv[0] not in ("create", "list", "remove"):
        print(
            "usage: dontpanic plan worktree <subcommand>\n\n"
            "subcommands:\n"
            "  create <plan-dir> [--base <ref>] [--copy-local-config]\n"
            "      Create the plan's dedicated git worktree on branch\n"
            "      plan/<plan-id> at a repo-key-qualified path under\n"
            "      $DONTPANIC_HOME/worktrees/, from the repo's default branch\n"
            "      (or --base) resolved to a recorded commit SHA, and bind it\n"
            "      in the worktrees registry. Allowlisted operator-local\n"
            "      config (environments.json) is declared when missing or\n"
            "      divergent; --copy-local-config opts into copying it.\n"
            "  list\n"
            "      Render the worktree-status model: one row per binding with\n"
            "      branch, current branch, dirty state, untracked count,\n"
            "      owner, and health reasons.\n"
            "  remove <plan-id>\n"
            "      Health-gated, audit-first removal (7-step sequence): refuses\n"
            "      on any dirty, gitignored, submodule, or nested-repo content;\n"
            "      appends fsynced intent + outcome records to\n"
            "      $DONTPANIC_HOME/worktree-audit.jsonl; deletes the registry\n"
            "      binding only after successful physical removal. No force\n"
            "      flag exists. The plan branch always survives.",
            file=sys.stderr,
        )
        return 2
    if argv[0] == "remove":
        from dontpanic_orchestrate import worktree_remove as _wr

        parser = argparse.ArgumentParser(prog="dontpanic plan worktree remove")
        parser.add_argument("plan_id", help="Plan ID of the bound worktree")
        try:
            args = parser.parse_args(argv[1:])
        except SystemExit:
            return 2
        try:
            result = _wr.remove_worktree(args.plan_id)
        except _wr.RemoveRefusal as exc:
            print(f"[plan worktree remove] REFUSED (step {exc.step}): {exc}", file=sys.stderr)
            return 3
        except _wt.RegistryCorruptError as exc:
            print(f"[plan worktree remove] REFUSED: {exc}", file=sys.stderr)
            return 3
        except _wr.RemoveError as exc:
            print(f"[plan worktree remove] FAILED (step {exc.step}): {exc}", file=sys.stderr)
            return 4
        except _wr.RemoveDegraded as exc:
            print(f"[plan worktree remove] DEGRADED: {exc}", file=sys.stderr)
            return 5
        if result["path"] == "completion":
            print(
                f"[plan worktree remove] removed (registry-only completion path) "
                f"for plan {result['plan_id']} — the worktree was already gone; "
                "the orphaned binding is now cleared and audited"
            )
        else:
            print(
                f"[plan worktree remove] removed {result['worktree_path']} "
                f"(plan {result['plan_id']}); intent + outcome audited at "
                f"{_wr.audit_log_path()}"
            )
        return 0
    if argv[0] == "create":
        parser = argparse.ArgumentParser(prog="dontpanic plan worktree create")
        parser.add_argument("plan", help="Plan ID (resolved against ./docs/plans/) or dir path")
        parser.add_argument("--base", default=None, metavar="REF",
                            help="Explicit base ref (default: the repo's default branch)")
        # Guard-hardening F003 (operator policy D003): allowlisted operator-
        # local config is DECLARED when missing/divergent; this flag opts in
        # to copying it. No symlinks at either end; overwrites are refused.
        parser.add_argument(
            "--copy-local-config",
            action="store_true",
            dest="copy_local_config",
            help=(
                "Copy allowlisted operator-local config (environments.json) "
                "from the repo root into the new worktree. Never overwrites "
                "divergent content; never follows or creates symlinks."
            ),
        )
        args = parser.parse_args(argv[1:])
        plan_dir = _resolve_plan_dir(args.plan)
        try:
            binding = _wt.create_worktree(plan_dir, base=args.base)
        except _wt.WorktreeError as exc:
            print(f"[plan worktree create] REFUSED: {exc}", file=sys.stderr)
            return 3
        print(f"[plan worktree create] worktree_path={binding['worktree_path']}")
        print(f"[plan worktree create] branch={binding['branch']}")
        print(
            f"[plan worktree create] base_ref={binding['base_ref']} "
            f"base_sha={binding['base_sha']}"
        )
        print(f"[plan worktree create] owner_actor={binding['owner_actor']}")
        # F003: declare missing/divergent allowlisted local config (default)
        # and perform the opt-in copy. Runs strictly AFTER create succeeded —
        # a refused create (incl. corrupt registry) never reaches this point.
        from dontpanic_orchestrate import worktree_local_config as _wlc

        for notice in _wlc.local_config_report(
            Path(binding["repo_root"]),
            Path(binding["worktree_path"]),
            copy=args.copy_local_config,
        ):
            print(
                f"[plan worktree create] local-config {notice['kind']}: "
                f"{notice['message']}"
            )
        return 0
    # list
    model = _wt.build_status_model()
    if model["registry_corrupt"]:
        print(
            f"[plan worktree list] WARNING: registry at {model['registry_path']} "
            "is CORRUPT — bindings below may be incomplete; fix or remove the file."
        )
    if not model["bindings"]:
        print("[plan worktree list] no worktree bindings")
        return 0
    for row in model["bindings"]:
        if row["healthy"]:
            state = f"dirty={row['dirty']} untracked={row['untracked_count']}"
        else:
            state = f"UNHEALTHY: {row['health_reason']} (dirty=unknown untracked=unknown)"
        drift = (
            f" current_branch={row['current_branch']}"
            if row["current_branch"] not in (None, row["branch"]) else ""
        )
        print(
            f"  {row['plan_id']}  branch={row['branch']}{drift}  {state}  "
            f"owner={row['owner_actor']}  path={row['worktree_path']}"
        )
    return 0


def _run_worktree_guard(
    plan_dir: Path, command: str, label: str, override_reason: str | None = None
) -> int | None:
    """Guard-hardening F001 — the shared wrong-worktree guard precondition,
    evaluated BEFORE any gate side effect or evidence write on every
    plan-gate entry point (lock / audit / close / disposition; the
    orchestrate dispatch seam wires the same function in supervisor).
    Returns an exit code on refusal, None when the command may proceed."""
    from dontpanic_orchestrate import worktree_guard as _wg
    from dontpanic_orchestrate.worktrees import RegistryCorruptError as _WtCorrupt

    try:
        result = _wg.guard_plan_command(
            plan_dir, command, override_reason=override_reason
        )
    except (_wg.GuardRefusal, _WtCorrupt) as exc:
        print(f"[{label}] REFUSED: {exc}", file=sys.stderr)
        return 3
    if result is not None and result.get("guard") == "override":
        print(
            f"[{label}] worktree guard OVERRIDDEN "
            f"({result['refusal_class']}) — override record + binding snapshot "
            "durably written to the plan's audit evidence"
        )
    return None


def _add_worktree_guard_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--override-worktree-guard",
        default=None,
        metavar="REASON",
        dest="worktree_guard_override",
        help=(
            "Override a wrong-worktree guard refusal (judgment classes only — "
            "a corrupt registry is never overridable). Proceeds only after the "
            "override record and a binding snapshot are durably written to the "
            "plan's audit evidence."
        ),
    )


def _plan_disposition_main(argv: list[str]) -> int:
    """``dontpanic plan disposition`` — record a per-finding operator
    disposition against the latest sufficiency audit round (plan
    2026-06-09-002 F003). No hand-editing of evidence files; each recorded
    disposition is mirrored into the plan's decisions.jsonl. Performs zero
    auditor invocations."""
    from dontpanic_orchestrate.sufficiency_convergence import (
        DISPOSITION_KINDS,
        ConvergenceError,
        gate_decision,
        record_disposition,
    )

    parser = argparse.ArgumentParser(
        prog="dontpanic plan disposition",
        description=(
            "Record a per-finding sufficiency disposition (convergence policy, "
            "plan 2026-09-002). waived_with_reason requires --reason; "
            "split_to_followup_plan requires --followup; deferred_to_impl and "
            "split_to_followup_plan are refused for plan_contract findings; "
            "accepted_into_plan stays blocking until the plan is actually "
            "edited and re-audited."
        ),
    )
    parser.add_argument("plan", help="Plan ID or absolute plan-dir path")
    parser.add_argument("--finding", required=True, help="finding_id from the rounds ledger")
    parser.add_argument("--kind", required=True, choices=list(DISPOSITION_KINDS))
    parser.add_argument("--reason", default=None)
    parser.add_argument("--followup", default=None, metavar="PLAN_REF")
    _add_worktree_guard_flag(parser)
    args = parser.parse_args(argv)

    plan_dir = _resolve_plan_dir(args.plan)
    guard_rc = _run_worktree_guard(
        plan_dir, "plan disposition", "plan disposition", args.worktree_guard_override
    )
    if guard_rc is not None:
        return guard_rc
    try:
        entry = record_disposition(
            plan_dir,
            finding_id=args.finding,
            kind=args.kind,
            reason=args.reason,
            followup_plan=args.followup,
            recorded_by=os.environ.get("DONTPANIC_OPERATOR")
            or os.environ.get("USER")
            or "operator",
        )
    except ConvergenceError as exc:
        print(f"[plan disposition] REFUSED: {exc}", file=sys.stderr)
        return 3
    print(
        f"[plan disposition] recorded {args.kind} for {args.finding} "
        f"(fingerprint {entry['fingerprint']}, round {entry['round']})"
    )
    decision = gate_decision(plan_dir)
    print(f"[plan disposition] convergence verdict now: {decision.verdict} ({decision.branch})")
    if decision.undisposed_ids:
        print(
            "[plan disposition] still undisposed: " + ", ".join(decision.undisposed_ids)
        )
    return 0


def _run_pre_lock_scope_gate(
    plan_dir: Path, *, allow_oversize: str | None
) -> int | None:
    """Plan 2026-06-01-001 F004 — pre-lock design gate.

    Runs the F001 scope lint over every feature in the plan. Returns:

      * ``3`` — the plan carries a block-severity scope flag and no
        ``--allow-oversize`` override was supplied: prints the refusal message
        naming the flags and refuses the lock (no status transition occurs).
      * ``None`` — the lock may proceed. Either the plan is clean, or an
        override was supplied (in which case the verbatim rationale is recorded
        to the plan's ``decisions.jsonl`` first).
    """
    from dontpanic_orchestrate.plan_review import pre_lock_gate
    from dontpanic_orchestrate.plan_review import report as plan_review_report

    # Load + lint is wrapped: a lint-infrastructure failure (unloadable plan,
    # resolver build error) must NEVER block the lock (D005 — the gate degrades
    # gracefully and is additive). A genuine block-severity flag is the only
    # thing that refuses; everything else proceeds with a one-line WARN.
    try:
        loaded = plan_loader.load(plan_dir)
        feature_dicts = [f.model_dump(mode="json") for f in loaded.features.features]  # enum->str (plan 2026-06-08-006 F002)
        resolvers = plan_review_report.build_default_resolvers()
        result = pre_lock_gate.evaluate_plan(loaded.plan_id, feature_dicts, resolvers)
    except Exception as exc:  # noqa: BLE001 — degrade, never block on lint infra
        print(
            f"[plan lock] WARN: pre-lock design gate skipped ({exc!r}); "
            "lint did not run — proceeding with the lock",
            file=sys.stderr,
        )
        return None

    if not result.is_blocked:
        return None

    if allow_oversize is None:
        print(pre_lock_gate.render_block_message(result), file=sys.stderr)
        return 3

    # Override supplied: record the verbatim rationale to decisions.jsonl,
    # then allow the lock to proceed.
    decisions_path = pre_lock_gate.record_override(
        loaded.plan_dir,
        plan_id=loaded.plan_id,
        reason=allow_oversize,
        result=result,
    )
    print(
        "[plan lock] pre-lock design gate OVERRIDDEN (--allow-oversize); "
        f"flags: {', '.join(result.flag_names())}"
    )
    print(f"[plan lock] override rationale recorded at {decisions_path}")
    return None


def _resolve_design_executor(plan_dir: Path):
    """Best-effort: resolve the plan's goal_auditor and return its executor for
    the F005 design-volley. Returns ``None`` (recommend, don't run) when no
    auditor/executor can be resolved — so an opt-in lock never crashes on a
    missing executor."""
    try:
        from dontpanic_orchestrate import completion_dispatch
        from dontpanic_orchestrate.executors import get_executor

        auditor = completion_dispatch._resolve_goal_auditor_agent(plan_dir)
        executor = get_executor(auditor)
        return executor if executor.is_available() else None
    except Exception:  # noqa: BLE001 — best-effort; recommend instead of crash
        return None


def _run_pre_lock_design_volley(
    plan_dir: Path,
    *,
    operator_requested: bool,
    executor=None,
    run_volley=None,
) -> None:
    """Plan 2026-06-01-001 F005 — opt-in design-review volley at pre_lock
    (operator decision D019: minimal, bounded, advisory). Runs ONLY when the
    F001 lint reports uncertainty (warn flags) OR the operator passes
    ``--design-review``; never auto-runs on a clean plan. Advisory: prints the
    verdict + findings; it does NOT block the lock (the F004 deterministic gate
    owns blocking). Degrades-never-blocks. Tests inject ``executor`` +
    ``run_volley`` so there is no live paid call."""
    try:
        from dontpanic_orchestrate.plan_review import (
            design_review,
        )
        from dontpanic_orchestrate.plan_review import (
            report as plan_review_report,
        )

        loaded = plan_loader.load(plan_dir)
        feature_dicts = [f.model_dump(mode="json") for f in loaded.features.features]  # enum->str (plan 2026-06-08-006 F002)
        report = plan_review_report.build_plan_scope_report(
            loaded.plan_id, feature_dicts, plan_review_report.build_default_resolvers()
        )
        if not design_review.should_run_design_volley(
            report, operator_requested=operator_requested
        ):
            print(
                "[plan lock] design-review: skipped (lint not uncertain, "
                "--design-review not set)"
            )
            return
        auditor = executor if executor is not None else _resolve_design_executor(plan_dir)
        if auditor is None:
            print(
                "[plan lock] design-review: RECOMMENDED (lint uncertain or "
                "requested) but no goal_auditor executor is available; re-run "
                "after configuring roles.goal_auditor."
            )
            return
        contract = None
        contract_path = plan_dir / "objective_contract.json"
        if contract_path.is_file():
            try:
                contract = json.loads(contract_path.read_text())
            except (OSError, json.JSONDecodeError):
                contract = None
        runner = run_volley if run_volley is not None else design_review.run_design_volley
        envelope = runner(
            loaded.plan_id,
            feature_dicts,
            auditor=auditor,
            objective_contract=contract,
            plan_dir=plan_dir,
        )
        print(f"[plan lock] design-review volley: verdict={envelope.verdict}")
        for f in envelope.findings:
            print(f"  [{f.kind}/{f.severity}] {f.feature_id}: {f.evidence}")
    except Exception as exc:  # noqa: BLE001 — advisory; never block the lock
        print(f"[plan lock] WARN: design-review volley skipped ({exc!r})")


def _ensure_sufficiency_findings(plan_dir) -> None:
    """Plan 2026-06-08-006 — generate the pre-impl sufficiency findings when the
    plan is in the gated goal_type set, then 2026-06-09 — regenerate them when
    the plan changed.

    The lock gate REQUIRES ``sufficiency-findings.json``. The original generator
    skipped generation whenever ANY findings file existed; a stale artifact (e.g.
    committed from a prior *refused* lock) therefore survived plan edits forever,
    so a plan tightened to address those exact findings could never clear the
    gate ("lock regenerates fresh audit evidence" was a false mental model —
    governance correctness defect). The artifact now carries an
    ``input_fingerprint`` over the plan-contract files (plan.md / features.json /
    objective_contract.json / decisions.jsonl) plus ``generated_at``; we reuse it
    only when the fingerprint still matches the current inputs, and regenerate
    when it is missing (a pre-fingerprint artifact, can't prove fresh) or drifted.

    If no auditor is configured the generator prints an actionable message and
    lets the gate's own refusal carry the final word — never a silent dead-end."""
    from dontpanic_orchestrate import sufficiency_gate as _sg
    from dontpanic_orchestrate.sufficiency_auditor import (
        SufficiencyAuditError,
        compute_input_fingerprint,
        generate_sufficiency_findings,
    )

    # Decide gating from the SAME YAML frontmatter the gate itself reads (audit
    # 2026-06-08): a raw-text regex would miss quoted/tagged forms like
    # goal_type: "new_feature" and skip generation for a plan the gate DOES gate,
    # recreating the dead-end. Reuse _read_frontmatter so the two can't drift.
    try:
        plan_data = _sg._read_frontmatter(plan_dir / "plan.md")
    except Exception:  # noqa: BLE001 — unreadable frontmatter: let the gate speak
        return
    if not _sg._should_gate_sufficiency(plan_data):
        return  # non-gated goal_type — the gate is a no-op, no paid call needed

    findings_path = _sg._findings_path(plan_dir)
    if findings_path.is_file():
        # Reuse ONLY when the persisted fingerprint still matches the plan's
        # current contract inputs; otherwise the findings are stale and must be
        # regenerated rather than block an edited plan.
        try:
            existing = json.loads(findings_path.read_text())
        except (OSError, json.JSONDecodeError):
            existing = None
        stored_fp = existing.get("input_fingerprint") if isinstance(existing, dict) else None
        current_fp = compute_input_fingerprint(plan_dir)
        if stored_fp is not None and stored_fp == current_fp:
            stamp = existing.get("generated_at", "<unknown>")
            count = len(existing.get("findings", [])) if isinstance(existing, dict) else 0
            print(
                f"[plan lock] reusing sufficiency findings — plan inputs unchanged "
                f"since {stamp} ({count} finding(s)); no re-audit needed."
            )
            return
        if stored_fp is None:
            print(
                "[plan lock] existing sufficiency findings predate input-"
                "fingerprinting — cannot prove they reflect the current plan; "
                "regenerating via the cross-vendor auditor..."
            )
        else:
            print(
                "[plan lock] plan inputs changed since the last sufficiency audit "
                "— regenerating findings (stale evidence is never reused)..."
            )
    else:
        print(
            "[plan lock] pre-impl sufficiency findings missing — generating via the "
            "cross-vendor auditor (Goal Governance V1 F003)..."
        )

    try:
        findings = generate_sufficiency_findings(plan_dir)
        print(f"[plan lock] sufficiency audit: generated {len(findings)} finding(s)")
    except SufficiencyAuditError as exc:
        print(f"[plan lock] sufficiency audit could not run: {exc}")
        print(
            "[plan lock]   configure roles.goal_auditor + a reachable executor, "
            "then re-run `dontpanic plan lock`."
        )
    except Exception as exc:  # noqa: BLE001 — advisory; the gate below still guards
        print(f"[plan lock] WARN: sufficiency generation failed ({exc!r})")


def _plan_lock_main(argv: list[str]) -> int:
    """``dontpanic plan lock`` — canonical lock-time entry point for Goal
    Governance V1 F004. Wraps :func:`sufficiency_gate.lock_plan`."""
    # F005: lifecycle-mutation agent-guidance footer, projected from the F002
    # inventory so the help says not to auto-run this lifecycle mutation unless
    # DontPanic surfaced the action or the human approved it.
    from dontpanic_orchestrate import command_guidance

    parser = argparse.ArgumentParser(
        prog="dontpanic plan lock",
        description=(
            "Run the pre-impl sufficiency gate, then flip plan.md status from "
            "draft to active. For plans without goal_type, the gate is a no-op "
            "but the status flip still proceeds."
        ),
        epilog=command_guidance.command_help_agent_snippet("plan"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("plan", help="Plan ID or absolute plan-dir path")
    parser.add_argument(
        "--ignore-sufficiency-findings",
        default=None,
        metavar="REASON",
        dest="override_reason",
        help=(
            "Operator override: bypass blocking sufficiency findings with a "
            "recorded reason. Writes evidence/goal-governance/pre_impl/"
            "override.json (durable but invalidated by changes to "
            "features.json / objective contract / sufficiency findings)."
        ),
    )
    # Plan 2026-06-01-001 F004: pre-lock design gate operator override.
    # Reuses the >=8-char layer-A validator the patch-completeness / sizing
    # overrides use; the rationale lands verbatim in the plan's decisions.jsonl.
    parser.add_argument(
        "--allow-oversize",
        type=_validate_patch_reason("--allow-oversize"),
        default=None,
        metavar="REASON",
        dest="allow_oversize",
        help=(
            "Override the pre-lock design gate even when a feature carries a "
            "block-severity scope flag (over_surface / over_ac / exemplar_ac / "
            "missing_prereq). REASON must be >=8 non-whitespace chars; lands "
            "verbatim in the plan's decisions.jsonl."
        ),
    )
    # Plan 2026-06-01-001 F005 — opt-in design-review volley at pre_lock.
    parser.add_argument(
        "--design-review",
        action="store_true",
        dest="design_review",
        help=(
            "Run the F005 design-review volley at lock (advisory red-team of the "
            "feature decomposition). Opt-in: it also auto-runs when the F001 "
            "lint reports uncertainty, but this flag forces it. Never blocks the "
            "lock; prints the verdict + findings."
        ),
    )
    _add_worktree_guard_flag(parser)
    args = parser.parse_args(argv)

    if args.override_reason is not None and not args.override_reason.strip():
        print(
            "[plan lock] --ignore-sufficiency-findings requires a non-empty reason",
            file=sys.stderr,
        )
        return 2

    plan_dir = _resolve_plan_dir(args.plan)
    guard_rc = _run_worktree_guard(
        plan_dir, "plan lock", "plan lock", args.worktree_guard_override
    )
    if guard_rc is not None:
        return guard_rc
    print(f"[plan lock] plan_dir={plan_dir}")

    # Plan 2026-05-20-001 F002 — pre-flight external_refs reachability.
    # Runs BEFORE the status flip so a sync=push_status ref pointing at a
    # 404 blocks lock loud. sync=none refs tolerate unreachable URIs.
    try:
        _validate_external_refs_at_lock(plan_dir)
    except Exception as exc:  # noqa: BLE001 — surfaced as REFUSED
        print(f"[plan lock] REFUSED (external_refs): {exc}", file=sys.stderr)
        return 3

    # Plan 2026-05-22-002 F003 — pre-flight requires_capabilities validation.
    # Unknown capability_id is operator-introduced config error (not env state),
    # so it MUST block the status flip with a closest-match suggestion.
    try:
        _validate_requires_capabilities_at_lock(plan_dir)
    except Exception as exc:  # noqa: BLE001 — surfaced as REFUSED
        print(f"[plan lock] REFUSED (requires_capabilities): {exc}", file=sys.stderr)
        return 3

    # Plan 2026-06-01-001 F004 — pre-lock design gate. Runs the F001 scope lint
    # over every feature BEFORE the status flip; a block-severity scope flag
    # refuses the lock unless --allow-oversize <reason> records a rationale in
    # decisions.jsonl. Additive: the existing external_refs / requires_
    # capabilities / sufficiency validation above and below is untouched.
    gate_rc = _run_pre_lock_scope_gate(plan_dir, allow_oversize=args.allow_oversize)
    if gate_rc is not None:
        return gate_rc

    # Plan 2026-06-01-001 F005 — opt-in design-review volley (advisory, never
    # blocks the lock). Runs on lint uncertainty OR --design-review.
    _run_pre_lock_design_volley(plan_dir, operator_requested=args.design_review)

    # Plan 2026-06-08-006 — generate the pre-impl sufficiency findings before the
    # gate checks for them, so a gated plan locks in one command instead of
    # dead-ending on a required-but-ungenerated artifact.
    _ensure_sufficiency_findings(plan_dir)

    try:
        plan_md = sufficiency_gate.lock_plan(
            plan_dir,
            override_reason=args.override_reason,
        )
    except sufficiency_gate.SufficiencyGateError as exc:
        print(f"[plan lock] REFUSED: {exc}", file=sys.stderr)
        return 3

    if args.override_reason is not None:
        override_path = plan_dir / "evidence" / "goal-governance" / "pre_impl" / "override.json"
        if override_path.is_file():
            print(f"[plan lock] override recorded at {override_path}")
    print(f"[plan lock] status flipped: draft → active in {plan_md}")

    # Plan 2026-05-08-002 F002 — emit advisory applicable-skills sidecar.
    # Best-effort: matcher errors are surfaced as a one-line warning but
    # NEVER block the lock outcome (D004: advisory only). Runs BEFORE
    # the required-capabilities sidecar so the latter can read the
    # ApplicabilityReport for F005 skill→capability inference.
    applicability_report: Any | None = None
    try:
        loaded = plan_loader.load(plan_dir)
        skills_dir = _resolve_skills_dir(plan_dir)
        if skills_dir is not None:
            applicability_report = skill_applicability.match(loaded, skills_dir)
            sidecar = skill_applicability.write_report(applicability_report, plan_dir)
            print(
                f"[applicable-skills] {len(applicability_report.matches)} matches, "
                f"{len(applicability_report.skipped)} skips written to "
                f"{sidecar.relative_to(plan_dir)}"
            )
        else:
            print("[applicable-skills] skipped — no claude/skills dir found above plan_dir")
    except Exception as exc:  # noqa: BLE001 — advisory matcher must never block
        print(
            f"[applicable-skills] WARN: matcher failed ({exc!r}); "
            "lock succeeded — sidecar NOT written",
            file=sys.stderr,
        )

    # Plan 2026-05-22-002 F003 + 2026-05-21-001 F005 — emit advisory
    # required-capabilities sidecar. Best-effort: emission failures surface
    # as a one-line warning but NEVER block lock outcome.
    try:
        _emit_required_capabilities_sidecar(plan_dir, applicability_report=applicability_report)
    except Exception as exc:  # noqa: BLE001 — advisory emitter must never block
        print(
            f"[required-capabilities] WARN: sidecar emit failed ({exc!r}); "
            "lock succeeded — sidecar NOT written",
            file=sys.stderr,
        )

    # Plan 2026-05-23-007 F003 — release-impact advisory (secondary surface).
    # Combines draft-time plan intent (surfaces, allowed_paths, step path
    # tokens) with lock-time git diff paths when available. Writes NOTHING:
    # output goes to stdout only, no v0 sidecar. Failure is a one-line
    # warning that never blocks lock.
    try:
        _emit_plan_lock_release_impact_advisory(plan_dir)
    except Exception as exc:  # noqa: BLE001 — advisory must never block lock
        print(
            f"[release-impact] WARN: advisory failed ({exc!r}); lock succeeded — "
            "no advisory printed",
            file=sys.stderr,
        )

    return 0


def _emit_plan_lock_release_impact_advisory(plan_dir: Path) -> None:
    """F003 secondary surface — print a release-impact advisory at lock time.

    Best-effort and non-blocking. The advisory is rendered to stdout under a
    ``[release-impact]`` prefix; nothing is written to disk. Inputs:
      - lock-time ``git diff --name-only HEAD`` paths (+ untracked files),
        captured if a git repo is available in an ancestor of ``plan_dir``.
        Failures to read git are silent.
      - draft-time plan intent: ``surfaces``, charter ``allowed_paths``,
        and feature-step path tokens (same shape as the draft-time advisory
        emitted by :mod:`planning_readiness`).
    """
    diff_paths = _git_changed_paths_for_lock(plan_dir)
    plan_obj = plan_loader.load(plan_dir)

    raw_surfaces = getattr(plan_obj.plan, "surfaces", None) or []
    plan_surfaces: list[str] = []
    for s in raw_surfaces:
        s_val = s.value if hasattr(s, "value") else str(s)
        if s_val:
            plan_surfaces.append(s_val)

    charter = getattr(plan_obj, "child_charter", None)
    allowed_paths: list[str] = []
    if charter is not None:
        for p in getattr(charter, "allowed_paths", None) or []:
            allowed_paths.append(str(p))

    step_tokens: list[str] = []
    seen: set[str] = set()
    for feature in getattr(plan_obj.features, "features", []) or []:
        if getattr(feature, "passes", False):
            continue
        for step in getattr(feature, "steps", None) or []:
            for raw in str(step).split():
                cleaned = raw.strip(".,;:()[]`\"'")
                if "/" not in cleaned:
                    continue
                if cleaned.startswith(("http://", "https://")):
                    continue
                normalized = cleaned.replace("\\", "/")
                while normalized.startswith("./"):
                    normalized = normalized[2:]
                if normalized and normalized not in seen:
                    seen.add(normalized)
                    step_tokens.append(normalized)

    advisory = release_impact.analyze(
        changed_paths=diff_paths,
        plan_surfaces=plan_surfaces,
        allowed_paths=allowed_paths,
        step_path_tokens=step_tokens,
    )

    # No inputs and no surfaces → nothing useful to say. Avoid noise.
    if not advisory.surfaces and not advisory.internal_only:
        return

    source_bits: list[str] = []
    if diff_paths:
        source_bits.append(f"{len(diff_paths)} git-diff path(s)")
    if plan_surfaces:
        source_bits.append(f"surfaces={plan_surfaces}")
    if allowed_paths:
        source_bits.append(f"allowed_paths={len(allowed_paths)}")
    source_summary = ", ".join(source_bits) if source_bits else "intent-only"
    print(
        f"[release-impact] advisory (no sidecar written; inputs: {source_summary}):"
    )
    for line in release_impact.render_text(advisory).split("\n"):
        print(f"  {line}")


def _git_changed_paths_for_lock(plan_dir: Path) -> list[str]:
    """Best-effort lock-time path scan. Returns the union of staged+unstaged
    diff paths (``git diff --name-only HEAD``) and untracked-but-not-ignored
    files. Any git failure (missing binary, not a repo, timeout) returns an
    empty list — the advisory still has draft-time intent inputs."""
    import subprocess  # noqa: PLC0415 — keep optional dependency local

    repo_root: Path | None = None
    for ancestor in [plan_dir, *plan_dir.parents]:
        if (ancestor / ".git").exists():
            repo_root = ancestor
            break
    if repo_root is None:
        return []

    paths: list[str] = []
    seen: set[str] = set()

    def _run(cmd: list[str]) -> str:
        try:
            result = subprocess.run(
                cmd,
                cwd=str(repo_root),
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            return ""
        if result.returncode != 0:
            return ""
        return result.stdout

    for line in _run(["git", "diff", "--name-only", "HEAD"]).splitlines():
        s = line.strip()
        if s and s not in seen:
            seen.add(s)
            paths.append(s)
    for line in _run(
        ["git", "ls-files", "--others", "--exclude-standard"]
    ).splitlines():
        s = line.strip()
        if s and s not in seen:
            seen.add(s)
            paths.append(s)
    return paths


def _resolve_skills_dir(plan_dir: Path) -> Path | None:
    """Walk up from plan_dir looking for ``claude/skills/``. Returns the
    first hit; ``None`` when no such directory exists in any ancestor.
    Kept here (not in skill_applicability) so the matcher stays focused
    on pure matching with an injectable skills_dir."""
    for ancestor in [plan_dir, *plan_dir.parents]:
        candidate = ancestor / "claude" / "skills"
        if candidate.is_dir():
            return candidate
    return None


# ──────────────────────────────  plan audit / close (F2/F003)  ──────────────────────────────


def _format_decision_summary(result: completion_gate.AuditPlanResult) -> list[str]:
    """Render an operator-readable summary of an
    :class:`completion_gate.AuditPlanResult`. Kept short — full envelope
    + findings JSON live on disk; CLI prints the headline only so a
    typical close-out fits on one screen."""
    lines: list[str] = []
    if result.audit_transcript is not None:
        env = result.audit_transcript
        lines.append(
            f"  audit: {env.auditor_agent} → status={env.status} "
            f"(iter={env.iteration}, {len(env.findings_dispositions)} disposition(s))"
        )
        lines.append(f"  envelope: {env.envelope_path}")
    lines.append(f"  v1 findings: {len(result.findings)}")
    if result.cluster_decisions:
        for d in result.cluster_decisions[:6]:
            lines.append(
                f"  cluster {d.subsystem}/{d.journey}: {d.finding_count} finding(s) → {d.triage}"
            )
        extra = len(result.cluster_decisions) - 6
        if extra > 0:
            lines.append(f"  … and {extra} more cluster(s)")
    if result.reasons:
        lines.append("  reasons:")
        for r in result.reasons:
            lines.append(f"    - {r}")
    return lines


def _plan_audit_main(argv: list[str]) -> int:
    """``dontpanic plan audit`` — F2/F003 audit-only entry point.

    Runs F001 (completion auditor) + F002 (cross-vendor dispatcher) +
    F0 classifier and prints the decision. Does NOT mutate plan.md.

    Exit-code matrix mirrors ``plan close``:
      0 — non-blocking decision (or exempt plan)
      2 — usage error / argparse failure
      3 — blocking decision (refuse-equivalent for the audit-only surface)
      4 — F001 audit-error (objective contract / findings file failure)
      5 — F002 vendor-error (SameVendorRefused, no override env)
    """
    parser = argparse.ArgumentParser(
        prog="dontpanic plan audit",
        description=(
            "Run the post-impl completion audit (F001 + F002 + F0 classifier) "
            "and print the decision. No status mutation. Exits 3 if the "
            "decision is blocking."
        ),
    )
    parser.add_argument("plan", help="Plan ID or absolute plan-dir path")
    _add_worktree_guard_flag(parser)
    args = parser.parse_args(argv)

    plan_dir = _resolve_plan_dir(args.plan)
    guard_rc = _run_worktree_guard(
        plan_dir, "plan audit", "plan audit", args.worktree_guard_override
    )
    if guard_rc is not None:
        return guard_rc
    from dontpanic_orchestrate.worktrees import (
        RegistryCorruptError as _WtCorrupt,
        capture_binding_snapshot as _wt_capture,
    )
    try:
        _wt_capture(plan_dir, "plan audit")
    except _WtCorrupt as exc:
        print(f"[plan audit] REFUSED: {exc}", file=sys.stderr)
        return 3
    print(f"[plan audit] plan_dir={plan_dir}")

    try:
        result = completion_gate.audit_plan(plan_dir)
    except completion_gate.SameVendorRefused as exc:
        print(f"[plan audit] VENDOR ERROR: {exc}", file=sys.stderr)
        print(
            "  set DONTPANIC_GOAL_AUDITOR_ALLOW_SAME_VENDOR=1 to override "
            "(record the override in close-out evidence)",
            file=sys.stderr,
        )
        return 5
    except completion_gate.CompletionAuditError as exc:
        print(f"[plan audit] AUDIT ERROR: {exc}", file=sys.stderr)
        return 4
    except completion_gate.CompletionDispatchError as exc:
        print(f"[plan audit] DISPATCH ERROR: {exc}", file=sys.stderr)
        return 4
    except completion_gate.SufficiencyAuditError as exc:
        # Resolver failures (no goal_auditor configured, etc.).
        print(f"[plan audit] AUDIT ERROR: {exc}", file=sys.stderr)
        return 4
    except completion_gate.CompletionGateError as exc:
        print(f"[plan audit] ERROR: {exc}", file=sys.stderr)
        return 4

    for line in _format_decision_summary(result):
        print(line)

    if result.blocking:
        print("[plan audit] DECISION: blocking", file=sys.stderr)
        return 3
    print("[plan audit] DECISION: non-blocking")
    return 0


def _plan_close_main(argv: list[str]) -> int:
    """``dontpanic plan close`` — canonical close-time entry point for
    Goal Governance V1 F2/F003. Wraps :func:`completion_gate.close_plan`.

    Exit-code matrix:
      0 — pass (clean close OR honored override OR exempt-plan flip OR
          idempotent re-close on already-completed plan)
      2 — usage error / argparse failure / draft-status refuse / empty
          override reason / --skip-audit (refused)
      3 — blocking decision, no override
      4 — F001 audit-error
      5 — F002 vendor-error (SameVendorRefused, no override env)
    """
    parser = argparse.ArgumentParser(
        prog="dontpanic plan close",
        description=(
            "Run the post-impl completion gate (F001 + F002 + F0 classifier) "
            "and flip plan.md status from active to completed on success. "
            "For exempt plans (goal_type outside the gated set), the gate is "
            "a no-op but the status flip still proceeds."
        ),
    )
    parser.add_argument("plan", help="Plan ID or absolute plan-dir path")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Run the audit + decision pipeline but do NOT mutate plan.md "
            "or write override.json. Operator preview tool."
        ),
    )
    parser.add_argument(
        "--ignore-completion-findings",
        default=None,
        metavar="REASON",
        dest="override_reason",
        help=(
            "Operator override: bypass blocking completion findings with a "
            "recorded reason. Writes evidence/goal-governance/post_impl/"
            "override.json (input-bound — drift in features.json / objective "
            "contract / completion_findings.json / evidence manifest "
            "invalidates it)."
        ),
    )
    parser.add_argument(
        "--skip-audit",
        action="store_true",
        help=argparse.SUPPRESS,  # parsed but always refused — see below
    )
    _add_worktree_guard_flag(parser)
    args = parser.parse_args(argv)

    if args.skip_audit:
        print(
            "[plan close] --skip-audit is refused in v1.\n"
            "  If you intentionally need to close without honoring the audit\n"
            "  decision, run: dontpanic plan close <plan-id> "
            '--ignore-completion-findings "<reason>"',
            file=sys.stderr,
        )
        return 2

    if args.override_reason is not None and not args.override_reason.strip():
        print(
            "[plan close] --ignore-completion-findings requires a non-empty reason",
            file=sys.stderr,
        )
        return 2

    plan_dir = _resolve_plan_dir(args.plan)
    guard_rc = _run_worktree_guard(
        plan_dir, "plan close", "plan close", args.worktree_guard_override
    )
    if guard_rc is not None:
        return guard_rc
    from dontpanic_orchestrate.worktrees import (
        RegistryCorruptError as _WtCorrupt,
        capture_binding_snapshot as _wt_capture,
    )
    try:
        _wt_capture(plan_dir, "plan close")
    except _WtCorrupt as exc:
        print(f"[plan close] REFUSED: {exc}", file=sys.stderr)
        return 3
    print(f"[plan close] plan_dir={plan_dir}{' (dry-run)' if args.dry_run else ''}")

    try:
        result = completion_gate.close_plan(
            plan_dir,
            override_reason=args.override_reason,
            dry_run=args.dry_run,
        )
    except completion_gate.SameVendorRefused as exc:
        print(f"[plan close] VENDOR ERROR: {exc}", file=sys.stderr)
        print(
            "  set DONTPANIC_GOAL_AUDITOR_ALLOW_SAME_VENDOR=1 to override "
            "(record the override in close-out evidence)",
            file=sys.stderr,
        )
        return 5
    except completion_gate.CompletionAuditError as exc:
        print(f"[plan close] AUDIT ERROR: {exc}", file=sys.stderr)
        return 4
    except completion_gate.CompletionDispatchError as exc:
        print(f"[plan close] DISPATCH ERROR: {exc}", file=sys.stderr)
        return 4
    except completion_gate.SufficiencyAuditError as exc:
        print(f"[plan close] AUDIT ERROR: {exc}", file=sys.stderr)
        return 4
    except completion_gate.CompletionGateError as exc:
        # Distinguish refusal-on-blocking from usage errors (status mismatch,
        # contract missing, etc.). Refusal-on-blocking carries the literal
        # 'plan close refused' prefix from close_plan; usage errors don't.
        msg = str(exc)
        if "refusing to close" in msg:
            print(f"[plan close] USAGE ERROR: {msg}", file=sys.stderr)
            return 2
        if "plan close refused" in msg:
            print(f"[plan close] REFUSED:\n{msg}", file=sys.stderr)
            return 3
        print(f"[plan close] ERROR: {msg}", file=sys.stderr)
        return 2

    if result.audit_result is not None:
        for line in _format_decision_summary(result.audit_result):
            print(line)
    for note in result.notes:
        print(f"[plan close] {note}")
    if result.override_recorded:
        print(f"[plan close] override recorded at {completion_gate._override_path(plan_dir)}")
    if result.status_flipped:
        print(f"[plan close] status flipped: active → completed in {result.plan_md}")

    # Plan 2026-05-20-001 F002 — push external_refs status outbound.
    # NEVER blocks close: failures land as evidence records, not raised
    # exceptions. dry_run=True writes status=pending and prints the
    # intended payload instead of calling the vendor.
    try:
        _run_external_refs_at_close(plan_dir, dry_run=args.dry_run)
    except Exception as exc:  # noqa: BLE001 — defensive; should not happen
        print(
            f"[plan close] external_refs hook crashed: "
            f"{type(exc).__name__}: {exc} (close still succeeded)",
            file=sys.stderr,
        )
    return 0


# ─────────────────────────  plan resync (F002)  ─────────────────────────


def _resolver_for_external_refs():
    """Lazy bootstrap of the adapter resolver. Kept tiny so plans with no
    external_refs never pay the import cost. Tests monkeypatch this seam
    via :data:`_RESOLVER_FACTORY`."""

    factory = _RESOLVER_FACTORY
    if factory is not None:
        return factory()
    from dontpanic_orchestrate.integrations.adapter_registry import default_resolver

    return default_resolver()


def _capability_index_for_external_refs():
    """Plan 2026-05-21-001 F004 — lazy load of the capability manifest
    index. Only invoked when at least one external_ref declares a
    ``capability_id``, so plans with legacy refs (or no refs) don't pay
    the manifest-load cost. Tests monkeypatch this seam via
    :data:`_CAPABILITY_INDEX_FACTORY`."""

    factory = _CAPABILITY_INDEX_FACTORY
    if factory is not None:
        return factory()
    from dontpanic_orchestrate.capabilities import load_capabilities

    return load_capabilities()


# Test-injectable override. ``None`` falls through to ``default_resolver``.
_RESOLVER_FACTORY = None

# Test-injectable override. ``None`` falls through to ``load_capabilities``.
_CAPABILITY_INDEX_FACTORY = None


def _read_external_refs_from_frontmatter(plan_dir: Path) -> list:
    """Narrow reader: parse only `external_refs[]` from plan.md frontmatter
    and validate each entry against :class:`ExternalRef`. Does NOT invoke
    the full :func:`plan_loader.load` validator so the lock-time hook
    survives plans whose features.json is structurally valid against the
    sufficiency gate but missing top-level task_id/schema_version (which
    the F004 sufficiency-gate fixtures intentionally omit). When the
    plan declares no refs, returns an empty list — caller skips."""

    import yaml
    from models.plan_model import ExternalRef  # noqa: E402

    plan_md = plan_dir / "plan.md"
    if not plan_md.is_file():
        return []
    text = plan_md.read_text()
    if not text.startswith("---"):
        return []
    parts = text.split("---", 2)
    if len(parts) < 3:
        return []
    fm = yaml.safe_load(parts[1]) or {}
    raw_refs = fm.get("external_refs") or []
    if not raw_refs:
        return []
    return [ExternalRef.model_validate(r) for r in raw_refs]


def _validate_external_refs_at_lock(plan_dir: Path) -> None:
    """Pre-lock validation hook. Reads `external_refs[]` directly from
    plan.md (no full plan_loader.load — see
    :func:`_read_external_refs_from_frontmatter` for the rationale) and
    calls into :func:`external_refs_sync.validate_refs_for_lock`. Plans
    with no refs return immediately.

    Plan 2026-05-21-001 F004 — when any ref declares ``capability_id``,
    load the manifest index and pass it through so unknown or
    incompatible capability IDs fail loud at lock-time. Plans with only
    legacy refs (no ``capability_id``) skip the manifest load entirely
    for backward compatibility."""

    from dontpanic_orchestrate import external_refs_sync as ers

    refs = _read_external_refs_from_frontmatter(plan_dir)
    if not refs:
        return
    resolver = _resolver_for_external_refs()
    capability_index = None
    if any(getattr(r, "capability_id", None) is not None for r in refs):
        capability_index = _capability_index_for_external_refs()
    ers.validate_refs_for_lock(refs, resolver, capability_index=capability_index)


def _validate_requires_capabilities_at_lock(plan_dir: Path) -> None:
    """Plan 2026-05-22-002 F003 — pre-lock validation hook.

    Reads ``requires_capabilities[]`` from plan.md frontmatter and validates
    each id against the manifest registry. Unknown ids raise
    :class:`RequiresCapabilityUnknownError` with a closest-match suggestion;
    callers translate that into a loud REFUSED. Plans without the field
    return immediately so backward-compat plans pay no manifest-load cost."""

    from dontpanic_orchestrate import capabilities_lock_sidecar as sidecar

    required_ids = sidecar.read_requires_capabilities(plan_dir)
    if not required_ids:
        return
    capability_index = _capability_index_for_external_refs()
    sidecar.validate_requires_capabilities(required_ids, capability_index)


def _emit_required_capabilities_sidecar(
    plan_dir: Path, *, applicability_report: Any | None = None
) -> None:
    """Plan 2026-05-22-002 F003 + 2026-05-21-001 F005 — post-lock sidecar.

    Emits ``evidence/required-capabilities.json`` when the plan declares
    external_refs[], requires_capabilities[], a surface that hints at a
    capability (F005), or a skill applicability report carries an
    external_cli command bound to a manifest (F005). Returns silently
    when none of those produce a binding. Prints the warning chip when
    any required capability has status != ready. Lock proceeds
    regardless — sidecar is advisory only."""

    from dontpanic_orchestrate import capabilities_lock_sidecar as sidecar

    external_refs = sidecar.read_external_refs(plan_dir)
    # F005: surface or skill matches alone can trigger emission, so do not
    # short-circuit here on empty refs+requires.

    capability_index = _capability_index_for_external_refs()
    # Resolver is needed for the scheme→capability_id fallback path. Lazy-
    # load via the same factory the external_refs lock-time path uses so
    # tests can monkeypatch a single seam. F005 inference treats a None
    # resolver as "no adapter-registration probe" — surface/skill matches
    # still surface, they just default to status=unknown rather than
    # not_registered.
    resolver = _resolver_for_external_refs() if external_refs else None

    sidecar_path = sidecar.emit_required_capabilities(
        plan_dir,
        capability_index=capability_index,
        resolver=resolver,
        applicability_report=applicability_report,
    )
    if sidecar_path is None:
        return

    unready = sidecar.count_unready_capabilities(sidecar_path)
    rel = sidecar_path.relative_to(plan_dir.resolve())
    if unready > 0:
        # Acceptance #5 specifies the chip text references the bare
        # filename (``required-capabilities.json``) rather than the
        # ``evidence/`` relative path; keep the full path on a follow-up
        # line so operators can still copy/paste it.
        print(
            f"[required-capabilities] WARN: plan requires {unready} "
            f"capabilities not ready (see {sidecar_path.name})"
        )
        print(f"[required-capabilities] sidecar: {rel}")
    else:
        print(f"[required-capabilities] sidecar written to {rel}")


def _run_external_refs_at_close(plan_dir: Path, *, dry_run: bool) -> None:
    """Close-time hook. Skips when plan declares no refs."""

    from dontpanic_orchestrate import external_refs_sync as ers

    refs = _read_external_refs_from_frontmatter(plan_dir)
    if not refs:
        return
    resolver = _resolver_for_external_refs()
    result = ers.run_close_push(
        refs,
        resolver,
        plan_dir,
        dry_run=dry_run,
    )
    if dry_run:
        for line in ers.format_dry_run_preview(result):
            print(line)
    else:
        print(
            f"[plan close] external_sync: {result.pushed_count} pushed, "
            f"{result.failed_count} failed (evidence: {result.evidence_path})"
        )


def _plan_resync_main(argv: list[str]) -> int:
    """``dontpanic plan resync`` — retry failed/pending entries in
    ``evidence/external_sync.json``. Idempotent: already-pushed entries
    are skipped. Plan 2026-05-20-001 F002.

    Exit-code matrix:
      0 — resync complete (any combination of pushed/failed/skipped)
      2 — usage error / no evidence file present
    """

    parser = argparse.ArgumentParser(
        prog="dontpanic plan resync",
        description=(
            "Retry any failed/pending entries in evidence/external_sync.json "
            "via the registered category adapters. Idempotent."
        ),
    )
    parser.add_argument("plan", help="Plan ID or absolute plan-dir path")
    args = parser.parse_args(argv)

    plan_dir = _resolve_plan_dir(args.plan)
    print(f"[plan resync] plan_dir={plan_dir}")

    from dontpanic_orchestrate import external_refs_sync as ers

    if not (plan_dir / ers.EVIDENCE_RELPATH).is_file():
        print(
            f"[plan resync] no evidence file at {plan_dir / ers.EVIDENCE_RELPATH} "
            f"— nothing to retry. Run `dontpanic plan close` first.",
            file=sys.stderr,
        )
        return 2

    resolver = _resolver_for_external_refs()
    try:
        result = ers.run_resync(plan_dir, resolver)
    except ers.ExternalRefsSyncError as exc:
        print(f"[plan resync] ERROR: {exc}", file=sys.stderr)
        return 2

    print(
        f"[plan resync] {result.pushed_count} pushed, "
        f"{result.failed_count} failed "
        f"({len(result.records)} total in {result.evidence_path})"
    )
    return 0


# ─────────────────────────  config / project / setup (F006)  ─────────────────────────


def _config_inventory_main(argv: list[str]) -> int:
    """``dontpanic config inventory`` — the configuration setup cockpit.

    Plan 2026-05-30-001 F008. One command surfaces every DontPanic config
    surface and its status, the exact safe command to edit each one, the
    human-required (secret/auth) steps with NO secret values, and exactly one
    response-level dashboard hint when any item needs human input. ``--setup-plan``
    emits the typed ActionChoice list + draft DontPanic plan for the incomplete
    areas instead of forcing the agent to invent next steps.
    """
    parser = argparse.ArgumentParser(
        prog="dontpanic config inventory",
        description=(
            "Configuration inventory and setup cockpit: assess, configure, and "
            "update every core DontPanic surface without spelunking files."
        ),
    )
    parser.add_argument(
        "--project",
        default=None,
        help="Project NAME (registry) or PATH for project-scoped surfaces.",
    )
    parser.add_argument("--format", choices=["text", "json"], default="text")
    parser.add_argument(
        "--dashboard-url",
        default=None,
        help="Active dashboard URL when a singleton is running (omit when not).",
    )
    parser.add_argument(
        "--setup-plan",
        action="store_true",
        help="Emit ActionChoices + a draft DontPanic plan for incomplete setup areas.",
    )
    args = parser.parse_args(argv)

    from dontpanic_orchestrate import config_inventory as ci

    try:
        inventory = ci.collect_inventory(
            project=args.project, dashboard_url=args.dashboard_url
        )
    except ci.UnresolvedProjectError as exc:
        # Hard-refuse an unresolved --project selector (D003): never silently
        # degrade to machine-only inventory for a project the caller asked about.
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.setup_plan:
        plan = ci.build_setup_plan(inventory)
        if args.format == "json":
            print(json.dumps(plan, indent=2))
        else:
            print(f"Setup plan: {plan['draft_plan']['summary']}")
            for choice in plan["choices"]:
                cmd = choice["exact_command"] or "(human action required)"
                print(f"  - {choice['title']}: {cmd}")
            if plan["dashboard_hint"]:
                print(f"  dashboard: {plan['dashboard_hint']['text']}")
        return 0
    if args.format == "json":
        print(json.dumps(inventory.to_dict(), indent=2))
    else:
        print(ci.render_text(inventory), end="")
    return 0


def _config_main(argv: list[str]) -> int:
    """``dontpanic config <subcommand>`` — global config CRUD (Plan G F006)."""
    if not argv or argv[0] in ("-h", "--help"):
        print(
            "usage: dontpanic config <subcommand>\n\n"
            "subcommands:\n"
            "  show              Print resolved global config (roles + legacy fields)\n"
            "  set <key> <value> Write a single dotted key under ~/.dontpanic/config.json\n"
            "                    Canonical role keys: roles.implementer / roles.auditor /\n"
            "                    roles.goal_auditor. Legacy default_implementer /\n"
            "                    default_auditor still accepted.\n"
            "                    runtime_evidence.* refused at global tier (D015 — use\n"
            "                    `dontpanic project config set` instead).\n"
            "  inventory         Setup cockpit: every config surface + status, safe\n"
            "                    commands, human-required steps, dashboard hint\n"
            "                    [--project NAME|PATH] [--format text|json]\n"
            "                    [--setup-plan] [--dashboard-url URL]",
            file=sys.stderr,
        )
        return 2
    sub = argv[0]
    rest = argv[1:]
    if sub == "inventory":
        return _config_inventory_main(rest)
    from dontpanic_orchestrate import global_config as _gc
    from dontpanic_orchestrate.config import cli_helpers as _ch

    if sub == "show":
        cfg = _gc.load_config()
        print(_ch.render_global_show(cfg))
        return 0
    if sub == "set":
        if len(rest) != 2:
            print("usage: dontpanic config set <dotted-key> <value>", file=sys.stderr)
            return 2
        key, value = rest
        try:
            path = _ch.write_global_dotted_key(key, value)
        except _ch.InvalidKeyError as exc:
            print(f"[config set] REFUSED: {exc}", file=sys.stderr)
            return 3
        print(f"[config set] wrote {key} → {path}")
        return 0
    print(f"dontpanic config: unknown subcommand {sub!r}", file=sys.stderr)
    return 2


def _project_main(argv: list[str]) -> int:
    """``dontpanic project <subcommand>`` — currently routes to ``project config`` (F006)."""
    if not argv or argv[0] in ("-h", "--help"):
        print(
            "usage: dontpanic project <subcommand>\n\n"
            "subcommands:\n"
            "  config init [--overwrite]   Scaffold <cwd>/.dontpanic/dontpanic.json\n"
            "  config set <key> <value>    Write a single dotted key in the per-project config",
            file=sys.stderr,
        )
        return 2
    if argv[0] == "config":
        return _project_config_main(argv[1:])
    print(f"dontpanic project: unknown subcommand {argv[0]!r}", file=sys.stderr)
    return 2


def _project_config_main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(
            "usage: dontpanic project config <subcommand>\n\n"
            "subcommands:\n"
            "  init [--overwrite]\n"
            "      Scaffold <cwd>/.dontpanic/dontpanic.json (refuses if it exists\n"
            "      unless --overwrite is passed).\n"
            "  set <dotted-key> <value>\n"
            "      Write a single key. Examples:\n"
            "        roles.goal_auditor codex\n"
            "        runtime_evidence.web.base_url http://localhost:3000\n"
            "        runtime_evidence.backend.auth env:GLAM_FIREBASE_SA",
            file=sys.stderr,
        )
        return 2
    sub = argv[0]
    rest = argv[1:]
    from dontpanic_orchestrate import project_config as _pc
    from dontpanic_orchestrate.config import cli_helpers as _ch

    project_dir = Path.cwd().resolve()

    if sub == "init":
        overwrite = False
        if rest and rest[0] == "--overwrite":
            overwrite = True
            rest = rest[1:]
        if rest:
            print(f"unexpected args after init: {rest}", file=sys.stderr)
            return 2
        path = _pc.project_config_path(project_dir)
        if path.exists() and not overwrite:
            print(
                f"[project config init] REFUSED: per-project config already exists at "
                f"{path}; pass --overwrite to replace it",
                file=sys.stderr,
            )
            return 3
        try:
            if path.exists():
                # Overwrite path: blow it away then scaffold.
                path.unlink()
            _pc.scaffold_empty_config(project_dir)
        except FileExistsError as exc:
            # ``scaffold_empty_config`` only raises this when the legacy
            # ``.jarvis/jarvis.json`` exists — that's not handled by the
            # plain `--overwrite` path, surface the refusal clearly.
            print(f"[project config init] REFUSED: {exc}", file=sys.stderr)
            return 3
        print(f"[project config init] wrote {_pc.project_config_path(project_dir)}")
        return 0

    if sub == "set":
        if len(rest) != 2:
            print(
                "usage: dontpanic project config set <dotted-key> <value>",
                file=sys.stderr,
            )
            return 2
        key, value = rest
        try:
            path = _ch.write_project_dotted_key(project_dir, key, value)
        except _ch.InvalidKeyError as exc:
            print(f"[project config set] REFUSED: {exc}", file=sys.stderr)
            return 3
        print(f"[project config set] wrote {key} → {path}")
        return 0

    print(f"dontpanic project config: unknown subcommand {sub!r}", file=sys.stderr)
    return 2


def _setup_main(argv: list[str]) -> int:
    """``dontpanic setup`` — preview-by-default; mutation requires ``--yes``."""
    # F005: configuration-mutation agent-guidance footer, projected from the
    # F002 inventory (inspect status/doctor before changing config; ask before
    # persistent changes unless DontPanic surfaced an automatable action).
    from dontpanic_orchestrate import command_guidance

    parser = argparse.ArgumentParser(
        prog="dontpanic setup",
        description=(
            "Bootstrap operator config: roles + per-project runtime evidence "
            "defaults. Preview-by-default; use --yes to actually write."
        ),
        epilog=command_guidance.command_help_agent_snippet("setup"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--implementer", help="Set roles.implementer (global)")
    parser.add_argument("--auditor", help="Set roles.auditor (global)")
    parser.add_argument("--goal-auditor", help="Set roles.goal_auditor (global)")
    parser.add_argument(
        "--project-dir",
        type=Path,
        help="Per-project target for runtime_evidence.* writes (D015 — required)",
    )
    parser.add_argument("--web-base-url", help="runtime_evidence.web.base_url")
    parser.add_argument("--ios-scheme", help="runtime_evidence.ios.scheme")
    parser.add_argument("--ios-simulator", help="runtime_evidence.ios.simulator")
    parser.add_argument("--android-package", help="runtime_evidence.android.package")
    parser.add_argument(
        "--android-adb-device-serial",
        help="runtime_evidence.android.adb_device_serial",
    )
    parser.add_argument("--backend-provider", help="runtime_evidence.backend.provider")
    parser.add_argument("--backend-project", help="runtime_evidence.backend.project")
    parser.add_argument(
        "--backend-auth",
        help="runtime_evidence.backend.auth (POINTER only: 'adc', 'env:NAME', or path)",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Actually perform the writes. Without this flag, setup is preview-only.",
    )
    args = parser.parse_args(argv)

    from dontpanic_orchestrate.config import setup as _setup

    setup_args = _setup.SetupArgs(
        implementer=args.implementer,
        auditor=args.auditor,
        goal_auditor=args.goal_auditor,
        project_dir=args.project_dir,
        web_base_url=args.web_base_url,
        ios_scheme=args.ios_scheme,
        ios_simulator=args.ios_simulator,
        android_package=args.android_package,
        android_adb_device_serial=args.android_adb_device_serial,
        backend_provider=args.backend_provider,
        backend_project=args.backend_project,
        backend_auth=args.backend_auth,
    )
    try:
        plan = _setup.plan_setup(setup_args)
    except _setup.SetupError as exc:
        print(f"[setup] REFUSED: {exc}", file=sys.stderr)
        return 2

    for line in plan.preview_lines:
        print(line)

    if not args.yes:
        print("\n[setup] preview-only run; pass --yes to apply these writes.")
        return 0

    try:
        _setup.apply_setup(plan)
    except Exception as exc:  # noqa: BLE001 — surface to operator with exit 3
        print(f"[setup] FAILED during apply: {exc}", file=sys.stderr)
        return 3
    print("\n[setup] applied.")
    return 0


def _next_main(argv: list[str]) -> int:
    """Plan 2026-05-23-007 F002 — read-only parallel-readiness recommender.

    Scans active/draft plan directories (single repo or every registered
    project under fleet scope), classifies each not-yet-passing feature as
    ready or not-ready, and prints either a human-readable text summary
    or the JSON envelope agents consume.

    The command never writes files. ``--include-not-ready`` is on by
    default so operators see the blockers next to the unblocked work;
    pass ``--ready-only`` to suppress the not-ready section.
    """
    # F005: class-specific agent-guidance footer, projected from the F002
    # inventory so read-only help teaches that this surface is safe to inspect
    # before mutation.
    from dontpanic_orchestrate import command_guidance

    parser = argparse.ArgumentParser(
        prog="dontpanic next",
        description=(
            "Recommend ready-to-dispatch features (read-only). Repo scope "
            "analyzes one plans root; fleet scope aggregates per-project "
            "analyses from the project registry."
        ),
        epilog=command_guidance.command_help_agent_snippet("next"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--scope",
        choices=["repo", "fleet"],
        default="repo",
        help="repo (default) analyzes a single plans root; fleet aggregates "
        "every active registered project.",
    )
    parser.add_argument(
        "--plans-root",
        type=Path,
        default=None,
        help="(repo scope) override the plans root; defaults to "
        "<cwd-project>/docs/plans or ./docs/plans.",
    )
    parser.add_argument(
        "--max-parallel",
        type=int,
        default=0,
        help="cap on candidate_commands[]. 0 (default) = include every "
        "ready item.",
    )
    parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="output format; text is human-readable, json is the agent "
        "handoff shape.",
    )
    parser.add_argument(
        "--include-not-ready",
        dest="include_not_ready",
        action="store_true",
        default=True,
        help="(default) include the not-ready list and the reasons.",
    )
    parser.add_argument(
        "--ready-only",
        dest="include_not_ready",
        action="store_false",
        help="suppress the not-ready section.",
    )
    args = parser.parse_args(argv)

    # Imported here so the planning_readiness module is only loaded when
    # the command is invoked (it pulls in plan_loader's schema discovery).
    from dontpanic_orchestrate import planning_readiness

    if args.scope == "fleet":
        report = planning_readiness.analyze_fleet(
            max_parallel=args.max_parallel,
            include_not_ready=args.include_not_ready,
        )
    else:
        if args.plans_root is not None:
            plans_root = args.plans_root.expanduser().resolve()
        else:
            # Resolve cwd-project plans_dir, else fall back to ./docs/plans.
            cwd = Path.cwd().resolve()
            cwd_project = project_config.find_project_for_plan_dir(cwd)
            if cwd_project is not None:
                proj_path = cwd_project[0]
                cfg = project_config.load_project_config(proj_path)
                plans_dir = (
                    cfg.plans_dir if cfg is not None else project_config.DEFAULT_PLANS_DIR
                )
                plans_root = (proj_path / plans_dir).resolve()
            else:
                plans_root = (cwd / "docs" / "plans").resolve()
        report = planning_readiness.analyze_repo(
            plans_root,
            max_parallel=args.max_parallel,
            include_not_ready=args.include_not_ready,
        )

    if args.format == "json":
        print(planning_readiness.render_json(report))
    else:
        print(planning_readiness.render_text(report), end="")
    return 0


# ──────────────────────────  agent surface + orchestrate gateway (F002)  ──────────────────────────

_AGENT_USAGE = """usage: dontpanic agent <subcommand>

Machine agent surface — bootstrap a newly installed interactive agent and
classify it as operator-only or worker-capable.

subcommands:
  brief                       Print the generated DontPanic operating brief
  status [<name>] [--json]    Show worker executors, known operator-only agents,
                              effective roles, and the classification of the
                              named agent (or the current agent when no <name>).
                              --json emits the three INDEPENDENT capability
                              booleans (can_operate / can_be_dispatched /
                              can_orchestrate)
  setup <name>                Operator + worker setup guidance for a named agent
  commands [--json]           Print the command-guidance inventory as a stable,
                              versioned JSON envelope (read-only; never runs a
                              guided command handler)
  guide [--path|--write]      Print the version-matched local operating guide
                              (offline 'start here'); --path prints its on-disk
                              locator, --write materializes it under the home
  register-worker <name>      Assign a registered executor to a role (guarded —
                              refuses agents with no executor)

Any agent can OPERATE DontPanic by running these commands; only agents with a
registered executor can be DISPATCHED as workers."""


def _agent_main(argv: list[str]) -> int:
    """``dontpanic agent <subcommand>`` — machine agent surface (F002).

    Subcommands print the generated brief, classify the current/named agent,
    emit setup guidance, and (guarded) register a worker role. None of these
    invoke a real agent CLI — they read the executor registry and config only.
    """
    from dontpanic_orchestrate import agent_brief, agent_guide, agent_surface

    if not argv or argv[0] in ("-h", "--help", "help"):
        # Bare `agent` is a teaching surface, not an error: print the brief so a
        # freshly installed interactive agent learns the command set, then the
        # subcommand usage. Help exits 0; this matches the orchestrate gateway.
        print(agent_brief.generate_brief().text, end="")
        print()
        print(_AGENT_USAGE)
        return 0

    sub = argv[0]
    rest = argv[1:]

    if sub == "brief":
        parser = argparse.ArgumentParser(prog="dontpanic agent brief", add_help=True)
        parser.add_argument("--json", action="store_true", dest="as_json")
        parser.add_argument(
            "--actions",
            metavar="PLAN",
            default=None,
            help="Plan 2026-06-02-001 F003 — pin which plan the agent-brief "
            "managed actions block renders from. The block is rendered by "
            "DEFAULT (auto-resolved from the cwd project's most-recent in-flight "
            "plan); this flag overrides that with a specific PLAN. Always "
            "rendered from the ActionItem spine — deduped by dedupe_key, scrubbed "
            "+ brand-normalized at the render boundary.",
        )
        args = parser.parse_args(rest)
        from dontpanic_orchestrate import action_renderers

        brief = agent_brief.generate_brief()
        # F003: the agent-brief surface ALWAYS carries the managed ActionItem
        # block — routed through the spine, never an independently-computed
        # shape. The plan is the explicit --actions PLAN when given, else the cwd
        # project's current in-flight plan; when neither resolves the block
        # renders empty ("No actions pending") rather than being omitted, so the
        # surface is always present and always spine-sourced.
        action_items = _resolve_brief_action_items(args.actions)
        block = action_renderers.render_agent_brief_block(action_items)
        if args.as_json:
            payload = agent_brief.to_public_dict(brief)
            payload["actions_block"] = block
            payload["action_items"] = action_renderers.render_dashboard(action_items)["items"]
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        else:
            print(brief.text, end="")
            print()
            print(block, end="")
        return 0

    if sub == "status":
        parser = argparse.ArgumentParser(prog="dontpanic agent status", add_help=True)
        parser.add_argument(
            "name",
            nargs="?",
            default=None,
            help="Optional agent name to classify (operator-only vs worker-capable)",
        )
        parser.add_argument(
            "--json",
            action="store_true",
            dest="as_json",
            help="Emit the three INDEPENDENT capability booleans (can_operate / "
            "can_be_dispatched / can_orchestrate) as JSON",
        )
        args = parser.parse_args(rest)
        if args.as_json:
            payload = agent_surface.status_payload(Path.cwd().resolve(), name=args.name)
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        else:
            print(agent_surface.render_status(Path.cwd().resolve(), name=args.name), end="")
        return 0

    if sub == "setup":
        parser = argparse.ArgumentParser(prog="dontpanic agent setup", add_help=True)
        parser.add_argument("name", help="Agent name to produce setup guidance for")
        args = parser.parse_args(rest)
        print(agent_surface.render_setup(args.name), end="")
        return 0

    if sub == "commands":
        parser = argparse.ArgumentParser(prog="dontpanic agent commands", add_help=True)
        parser.add_argument(
            "--json",
            action="store_true",
            dest="as_json",
            help="(default, and the only supported format) emit the command-guidance "
            "inventory as a versioned JSON envelope",
        )
        parser.parse_args(rest)
        # Plan 2026-06-03-001 F003 — read-only machine guidance surface. Prints the
        # F002 command-guidance inventory as a stable, versioned JSON envelope
        # (schema version + source summary + per-command entries) so an outer
        # harness can inspect DontPanic's affordances without scraping help text.
        # This reads command_guidance metadata ONLY — it never resolves a command
        # path back to a handler or invokes a guided command.
        from dontpanic_orchestrate import command_guidance

        payload = command_guidance.inventory_public_payload()
        print(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True))
        return 0

    if sub == "guide":
        parser = argparse.ArgumentParser(prog="dontpanic agent guide", add_help=True)
        locate = parser.add_mutually_exclusive_group()
        locate.add_argument(
            "--path",
            action="store_true",
            dest="as_path",
            help="Print the on-disk guide locator path (<dontpanic_home>/"
            f"{agent_guide.GUIDE_FILENAME}) instead of the guide body",
        )
        locate.add_argument(
            "--write",
            action="store_true",
            dest="do_write",
            help="Materialize the guide to the locator path and print where it "
            "was written",
        )
        args = parser.parse_args(rest)
        # Plan 2026-06-03-001 F006 — versioned local guide artifact. The guide is
        # generated from the operating brief + the F002 command-guidance
        # inventory (no second manual). Default prints the body; --path prints the
        # locator (no write); --write materializes it under the DontPanic home.
        from dontpanic_orchestrate import global_config

        if args.do_write:
            home = global_config.ensure_dontpanic_home()
            written = agent_guide.write_guide(home)
            print(str(written))
            return 0
        if args.as_path:
            print(str(agent_guide.guide_path(global_config.dontpanic_home())))
            return 0
        print(agent_guide.render_guide().text, end="")
        return 0

    if sub == "register-worker":
        return _agent_register_worker(rest)

    print(f"[agent] unknown subcommand: {sub!r}", file=sys.stderr)
    print(_AGENT_USAGE, file=sys.stderr)
    return 2


def _agent_register_worker(argv: list[str]) -> int:
    """``dontpanic agent register-worker <name> [--role ROLE] [--project|--global]``.

    Guarded write path: refuses (exit 3, no write) when ``<name>`` has no
    executor in AGENT_REGISTRY. Otherwise writes only ``roles.<role> = <name>``
    via the shared dotted-key writer — global by default, project-scoped with
    ``--project`` (which requires an initialized per-project config)."""
    from dontpanic_orchestrate import agent_surface
    from dontpanic_orchestrate.config import cli_helpers as _ch

    parser = argparse.ArgumentParser(prog="dontpanic agent register-worker", add_help=True)
    parser.add_argument("name", help="Worker executor to register (must be in AGENT_REGISTRY)")
    parser.add_argument(
        "--role",
        choices=list(agent_surface.ROLES),
        default="implementer",
        help="Role to assign the executor to (default: implementer)",
    )
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument(
        "--global",
        action="store_true",
        dest="is_global",
        help="Write to ~/.dontpanic/config.json (default scope)",
    )
    scope.add_argument(
        "--project",
        action="store_true",
        dest="is_project",
        help="Write to <cwd>/.dontpanic/dontpanic.json (requires project config init)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the intended write without changing any file",
    )
    args = parser.parse_args(argv)

    # Guard FIRST — never touch config for an agent with no executor.
    try:
        agent_surface.assert_registrable(args.name)
    except agent_surface.RegisterWorkerError as exc:
        print(f"[agent register-worker] REFUSED: {exc}", file=sys.stderr)
        return 3

    key = f"roles.{args.role}"
    scope_label = "project" if args.is_project else "global"

    if args.dry_run:
        target = (
            "<cwd>/.dontpanic/dontpanic.json" if args.is_project else "~/.dontpanic/config.json"
        )
        print(
            f"[agent register-worker] DRY-RUN: would set {key} → {args.name} "
            f"in {scope_label} config ({target})"
        )
        return 0

    try:
        if args.is_project:
            path = _ch.write_project_dotted_key(Path.cwd().resolve(), key, args.name)
        else:
            path = _ch.write_global_dotted_key(key, args.name)
    except _ch.InvalidKeyError as exc:
        print(f"[agent register-worker] REFUSED: {exc}", file=sys.stderr)
        return 3

    print(f"[agent register-worker] wrote {key} → {args.name} ({scope_label}: {path})")
    return 0


_ROLES_USAGE = """usage: dontpanic roles <subcommand>

Simple worker role assignment — the low-friction path for "use Codex as
auditor for this project" without hand-editing JSON.

subcommands:
  show [--project NAME|PATH] [--json]
      List available worker executors and the effective implementer /
      auditor / goal_auditor with the source layer each value came from.
  set <role> <executor> [--global | --project NAME|PATH] [--dry-run] [--yes]
      Assign a worker executor to a role. Guarded — refuses any agent with
      no executor in AGENT_REGISTRY (operator-only agents can operate
      DontPanic but cannot be assigned as workers). Default scope is global;
      --project writes <repo>/.dontpanic/dontpanic.json roles.*; --global
      writes ~/.dontpanic/config.json roles.*. Preview-by-default is shown
      with --dry-run; otherwise the write happens immediately."""


def _roles_usage_with_workers() -> str:
    """``_ROLES_USAGE`` plus the live worker-executor roster.

    The static usage text describes ``AGENT_REGISTRY`` generically; the
    teaching output (``roles --help`` / no-arg / unknown-subcommand) also
    names the executors a human can actually assign — ``available_worker_executors()``
    — so the help is self-contained without running ``roles show`` (F004 #1/#6)."""
    from dontpanic_orchestrate import role_assignment as _ra

    workers = _ra.available_worker_executors()
    worker_line = ", ".join(workers) if workers else "(none registered)"
    return (
        f"{_ROLES_USAGE}\n\n"
        f"available worker executors (assignable to a role): {worker_line}"
    )


def _resolve_roles_scope(project_arg: str | None):
    """Resolve a ``--project NAME|PATH`` (or cwd when absent) to a
    :class:`role_assignment.ProjectScope`. Returns the scope, or ``None``
    when an explicit identifier resolves to neither a registered project
    nor an existing directory (the caller maps this to exit 2)."""
    from dontpanic_orchestrate import project_config as _pc
    from dontpanic_orchestrate import role_assignment as _ra

    if project_arg is None:
        cwd = Path.cwd().resolve()
        match = _pc.find_project_for_plan_dir(cwd)
        if match is not None:
            return _ra.ProjectScope(path=match[0], name=match[1])
        return _ra.ProjectScope(path=cwd, name=None)
    resolved = _pc.resolve_project_path(project_arg)
    if resolved is None:
        return None
    path, name = resolved
    return _ra.ProjectScope(path=path, name=name)


def _roles_main(argv: list[str]) -> int:
    """``dontpanic roles <subcommand>`` — worker role assignment surface (F004).

    ``show`` reports effective roles + source layers + available executors;
    ``set`` writes a single ``roles.<role>`` key after guarding the executor
    against AGENT_REGISTRY. Neither path invokes a real agent CLI — the
    registry is read for classification only."""
    from dontpanic_orchestrate import agent_surface
    from dontpanic_orchestrate import role_assignment as _ra
    from dontpanic_orchestrate.config import cli_helpers as _ch

    if argv and argv[0] in ("-h", "--help", "help"):
        print(_roles_usage_with_workers())
        return 0
    if not argv:
        # No-arg is an actionable error (CLI convention): teach on stderr, exit 2.
        print(_roles_usage_with_workers(), file=sys.stderr)
        return 2

    sub = argv[0]
    rest = argv[1:]

    if sub == "show":
        parser = argparse.ArgumentParser(prog="dontpanic roles show", add_help=True)
        parser.add_argument(
            "--project",
            default=None,
            help="Registered project NAME or filesystem PATH (default: cwd)",
        )
        parser.add_argument("--json", action="store_true", dest="as_json")
        args = parser.parse_args(rest)
        scope = _resolve_roles_scope(args.project)
        if scope is None:
            print(
                f"[roles show] could not resolve --project {args.project!r} to a "
                "registered project or an existing directory",
                file=sys.stderr,
            )
            return 2
        if args.as_json:
            print(json.dumps(_ra.dashboard_projection(scope), indent=2, ensure_ascii=False))
        else:
            print(_ra.render_show(scope), end="")
        return 0

    if sub == "set":
        parser = argparse.ArgumentParser(prog="dontpanic roles set", add_help=True)
        parser.add_argument("role", choices=list(_ra.ROLES), help="Role slot to assign")
        parser.add_argument("executor", help="Worker executor (must be in AGENT_REGISTRY)")
        target = parser.add_mutually_exclusive_group()
        target.add_argument(
            "--global",
            action="store_true",
            dest="is_global",
            help="Write ~/.dontpanic/config.json roles.* (default scope)",
        )
        target.add_argument(
            "--project",
            default=None,
            help="Write <repo>/.dontpanic/dontpanic.json roles.* (NAME or PATH)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview the exact file + value change without writing",
        )
        parser.add_argument(
            "--yes",
            action="store_true",
            help="Accepted for symmetry with other mutating commands (writes are "
            "explicit here; no interactive prompt to confirm)",
        )
        args = parser.parse_args(rest)

        is_global = args.is_global or args.project is None

        # Guard FIRST — never touch config for an agent with no executor
        # (acceptance #5/#6). The message distinguishes operator-only from
        # worker-capable, identical to `agent register-worker`.
        try:
            _ra.assert_assignable(args.executor)
        except agent_surface.RegisterWorkerError as exc:
            print(f"[roles set] REFUSED: {exc}", file=sys.stderr)
            return 3

        scope = None
        if not is_global:
            scope = _resolve_roles_scope(args.project)
            if scope is None:
                print(
                    f"[roles set] could not resolve --project {args.project!r} to a "
                    "registered project or an existing directory",
                    file=sys.stderr,
                )
                return 2

        preview = _ra.render_set_preview(
            args.role, args.executor, is_global=is_global, scope=scope
        )
        if args.dry_run:
            print(f"[roles set] DRY-RUN: would {preview}")
            return 0

        key = f"roles.{args.role}"
        try:
            if is_global:
                path = _ch.write_global_dotted_key(key, args.executor)
            else:
                assert scope is not None
                path = _ch.write_project_dotted_key(scope.path, key, args.executor)
        except _ch.InvalidKeyError as exc:
            print(f"[roles set] REFUSED: {exc}", file=sys.stderr)
            return 3

        scope_label = "global" if is_global else "project"
        print(f"[roles set] wrote {key} → {args.executor} ({scope_label}: {path})")
        return 0

    print(f"[roles] unknown subcommand: {sub!r}", file=sys.stderr)
    print(_roles_usage_with_workers(), file=sys.stderr)
    return 2


def _orchestrate_main(argv: list[str]) -> int:
    """``dontpanic orchestrate`` — teaching gateway over ``dispatch-from-plan``.

    No args, ``--help``, or an invalid shape (a leading flag with no plan)
    prints the generated brief plus the canonical workflow. A plan id/path
    forwards verbatim to :func:`_dispatch_from_plan_main`, so dry-run-by-default
    and ``--confirm`` semantics are preserved exactly (F002 acceptance #5-7)."""
    from dontpanic_orchestrate import agent_brief

    def _teach(*, file) -> None:
        brief = agent_brief.generate_brief()
        print(brief.text, end="", file=file)
        print("", file=file)
        print("CANONICAL WORKFLOW", file=file)
        print(agent_brief.CANONICAL_WORKFLOW, file=file)
        print("", file=file)
        print(
            "Run `dontpanic orchestrate <plan-id-or-path>` to dry-run a dispatch, "
            "or add --confirm to commit. This forwards to dispatch-from-plan.",
            file=file,
        )

    # No args or explicit help → teaching output on stdout, exit 0.
    if not argv or argv[0] in ("-h", "--help", "help"):
        _teach(file=sys.stdout)
        return 0

    # Invalid shape: a leading flag means no plan id/path was supplied. Print
    # the teaching output to stderr and exit 2 (actionable, per CLI convention).
    if argv[0].startswith("-"):
        print(
            f"[orchestrate] no plan id/path supplied (saw {argv[0]!r} first).\n",
            file=sys.stderr,
        )
        _teach(file=sys.stderr)
        return 2

    # Plan id/path present → forward verbatim, preserving dry-run/--confirm.
    return _dispatch_from_plan_main(argv)


def _skills_main(argv: list[str]) -> int:
    """``dontpanic skills <recommend|rubric>`` — Plan 2026-05-30-001 F016.

    Surfaces the F011/F015 SkillAction set (``recommend``) with CLI/dashboard
    parity and provides the rubric migration path (``rubric``) for high-value
    skills that lack invocation metadata.
    """
    sub = argv[0] if argv else None
    if sub == "recommend":
        return _skills_recommend_main(argv[1:])
    if sub == "rubric":
        return _skills_rubric_main(argv[1:])
    print(
        "usage: dontpanic skills <recommend|rubric> ...\n"
        "  recommend <plan> [--stage STAGE] [--format text|json]\n"
        "  rubric (--suggest <skill> | --list-missing) [--plan <plan>] "
        "[--skills-dir DIR] [--format text|json]",
        file=sys.stderr if sub not in (None, "-h", "--help", "help") else sys.stdout,
    )
    return 0 if sub in (None, "-h", "--help", "help") else 2


def _skills_recommend_main(argv: list[str]) -> int:
    """``dontpanic skills recommend <plan> [--stage STAGE] [--format ...]``.

    Renders the SkillAction recommendations for a plan: skill, recommendation,
    reason, risk, command, approval requirement, and evidence target — the SAME
    typed data the dashboard renders (F016 AC9). Missing inputs collapse to ONE
    action (AC8); F008-inventory blockers explain unavailable resources (AC10).
    """
    parser = argparse.ArgumentParser(prog="dontpanic skills recommend")
    parser.add_argument("plan", nargs="?", default=None, help="Plan ID or dir path")
    parser.add_argument("--plan", dest="plan_flag", default=None, help="Plan ID or dir path")
    parser.add_argument("--stage", default=None, help="Lifecycle stage to scope recommendations")
    parser.add_argument("--skills-dir", default=None, help="Override the claude/skills dir")
    parser.add_argument("--dashboard-url", default=None, help="Active dashboard URL when running")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    args = parser.parse_args(argv)

    from dontpanic_orchestrate import skill_recommendation

    plan_arg = args.plan or args.plan_flag
    if not plan_arg:
        print("[skills recommend] a plan id/path is required", file=sys.stderr)
        return 2
    plan_dir = _resolve_plan_dir(plan_arg)
    if args.skills_dir is not None:
        skills_dir = Path(args.skills_dir)
    else:
        skills_dir = _resolve_skills_dir(plan_dir)
        if skills_dir is None:
            print(
                "[skills recommend] no claude/skills dir found above the plan; "
                "pass --skills-dir to point at one",
                file=sys.stderr,
            )
            return 2
    report = skill_recommendation.collect(
        plan_dir,
        skills_dir,
        stage=args.stage,
        dashboard_url=args.dashboard_url,
    )
    if args.format == "json":
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(skill_recommendation.render_text(report), end="")
    return 0


def _skills_rubric_main(argv: list[str]) -> int:
    """``dontpanic skills rubric (--suggest <skill> | --list-missing)``.

    The F016 migration path (AC11). ``--suggest`` proposes a SAFE starting
    ``invocation:`` block for one skill; ``--list-missing`` identifies high-value
    skills that lack a rubric. Advisory only — never blocks core use.
    """
    parser = argparse.ArgumentParser(prog="dontpanic skills rubric")
    parser.add_argument("--suggest", default=None, metavar="SKILL", help="Skill to propose a rubric for")
    parser.add_argument("--list-missing", action="store_true", help="List high-value skills lacking a rubric")
    parser.add_argument("--plan", default=None, help="Plan to scope --list-missing applicability")
    parser.add_argument("--skills-dir", default=None, help="Override the claude/skills dir")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    args = parser.parse_args(argv)

    from dontpanic_orchestrate import skill_recommendation

    if not args.suggest and not args.list_missing:
        print("[skills rubric] pass --suggest <skill> or --list-missing", file=sys.stderr)
        return 2

    # Resolve the skills dir: explicit override, else from the plan, else cwd.
    skills_dir: Path | None
    if args.skills_dir is not None:
        skills_dir = Path(args.skills_dir)
    elif args.plan is not None:
        skills_dir = _resolve_skills_dir(_resolve_plan_dir(args.plan))
    else:
        skills_dir = _resolve_skills_dir(Path.cwd())
    if skills_dir is None:
        print("[skills rubric] no claude/skills dir found; pass --skills-dir", file=sys.stderr)
        return 2

    if args.suggest:
        frontmatter = skill_recommendation._read_skill_frontmatter(skills_dir, args.suggest)
        if frontmatter is None:
            print(
                f"[skills rubric] skill {args.suggest!r} has no readable SKILL.md "
                f"in {skills_dir}",
                file=sys.stderr,
            )
            return 2
        suggestion = skill_recommendation.suggest_rubric(args.suggest, frontmatter)
        if args.format == "json":
            print(json.dumps(suggestion.to_dict(), indent=2))
        else:
            print(skill_recommendation.render_rubric_text(suggestion), end="")
        return 0

    # --list-missing
    applicable: set[str] | None = None
    if args.plan is not None:
        try:
            from dontpanic_orchestrate import skill_applicability

            loaded = plan_loader.load(_resolve_plan_dir(args.plan))
            report = skill_applicability.match(loaded, skills_dir)
            applicable = {m.skill_name for m in report.matches}
        except Exception:  # noqa: BLE001 — advisory; fall back to applies_to heuristic
            applicable = None
    missing = skill_recommendation.skills_missing_rubrics(
        skills_dir, applicable_names=applicable
    )
    if args.format == "json":
        print(json.dumps({"skills_missing_rubrics": missing}, indent=2))
    else:
        if not missing:
            print("No high-value skills are missing an invocation rubric.")
        else:
            print("High-value skills missing an invocation rubric (advisory):")
            for name in missing:
                print(f"  {name} — run `dontpanic skills rubric --suggest {name}`")
    return 0


def _print_top_level_help(*, file) -> None:
    # The "Start here (for AI agents)" block is the F004 discovery pointer. It is
    # rendered from the shared guidance helper (projected over the F002 inventory)
    # rather than hand-maintained here, so the entrypoint can never drift from the
    # real command surface, and it deliberately points at the generated brief
    # instead of restating it.
    from dontpanic_orchestrate import command_guidance

    agent_snippet = command_guidance.root_help_agent_snippet()
    print(
        f"""usage: dontpanic <command> [args]

{agent_snippet}

Public-alpha command surface:
  setup                         Preview or write global roles + project runtime defaults
  config show|set               Inspect or edit ~/.dontpanic/config.json
  project config init|set        Inspect or edit <project>/.dontpanic/dontpanic.json
  projects add|list|show|remove  Register local projects for plan resolution
  manifest init|show             Publish the machine-readable agent manifest
  agent brief|status|setup|commands|guide|register-worker  Machine agent surface (operator vs worker; `commands` = JSON guidance, `guide` = offline operating guide)
  roles show|set                 Assign worker executors to implementer/auditor/goal_auditor roles
  operator-roles set|list        Operator-role PREFERENCES (intent only; never dispatch authority)
  skills recommend|rubric        Skill recommendations for a plan + rubric migration suggestions
  orchestrate [<plan>]           Teaching gateway: brief/workflow, or forward to dispatch-from-plan
  doctor                         Run local readiness checks
  init                           Interactive installer (default --profile=core)
  smoke                          Mocked supervisor-plumbing smoke test (no real CLI)
  architecture regen|status|diff Codebase + plan snapshot + drift surface
  showcase regen                 Generate showcase artifacts for external repos
  capabilities status            Inspect capability readiness vs. local env
  capabilities setup             Plan or execute setup for one capability (--print-steps | --automate-safe --confirm)
  reconcile baseline             Build (and with `--yes` write) ~/.dontpanic/install-snapshot.json
  reconcile check                Compare current capability manifests against the install snapshot
  dashboard build|open|serve     Local-first operator console (export state, open path, localhost-only serve)
  repair plan|apply              Emit the ordered, safety-classified repair bundle (plan, read-only) or run the auto_safe batch (apply --safe-derived-state | --safe --confirm)
  next                          Read-only parallel-readiness recommender (text/JSON, repo|fleet)
  state snapshot|export-dashboard Read-only state projection for dashboards, agents, and adapters
  plan lock|audit|close          Goal-governed plan lifecycle gates
  close --operator-resolved      Operator close-out of a stopped_no_progress feature
  dispatch-from-plan             Dry-run or confirm feature-by-feature dispatch
  approve|resume|ps              Clear gates and inspect active supervisors
  quota-caps|calibrate-claude    Configure local quota guardrails
  mcp serve                      Start the local MCP server

Compatibility:
  dontpanic <plan-id> [--volley] [--feature F001] still runs the legacy direct
  dispatch entry point. Prefer `dontpanic dispatch-from-plan <plan-id>` for new
  work because it prints the preflight context and is dry-run by default.

Use `dontpanic <command> --help` for command-specific options.""",
        file=file,
    )


def _operator_roles_main(argv: list[str]) -> int:
    """``dontpanic operator-roles set|list`` — operator-role PREFERENCE config
    (intent only, never dispatch authority; D009/F004). Thin wrapper that builds
    a parser from the operator_roles module's own subparser registrar and prints
    the resolved map (with scope provenance) as JSON for ``list``."""
    from dontpanic_orchestrate import operator_roles

    parser = argparse.ArgumentParser(prog="dontpanic operator-roles")
    sub = parser.add_subparsers(dest="_or_top")
    operator_roles.add_operator_roles_subparser(sub)
    # The registrar nests under an "operator-roles" command; strip that layer so
    # `dontpanic operator-roles set ...` maps onto the registrar's subcommands.
    args = parser.parse_args(["operator-roles", *argv])
    if getattr(args, "or_action", None) is None:
        parser.parse_args(["operator-roles", "--help"])
        return 2
    result = operator_roles.run_operator_roles_command(args)
    if result is not None:
        print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    """Public CLI entry point. Wraps the dispatch in the F003 invocation-ledger
    seam: start a recorder, run the command, finalize EXACTLY ONE record in a
    ``finally`` (covering normal return, error rc, argparse SystemExit, early
    failure, KeyboardInterrupt, and SIGTERM). The ledger is fail-open — it never
    changes the command's behavior or exit code."""
    from dontpanic_orchestrate import invocation_ledger

    raw_argv = argv if argv is not None else sys.argv[1:]
    recorder = invocation_ledger.start_recording(raw_argv)
    result = invocation_ledger.RESULT_OK
    try:
        rc = _run_cli(argv)
        if rc not in (0, None):
            result = invocation_ledger.RESULT_ERROR
        return rc
    except KeyboardInterrupt:
        result = invocation_ledger.RESULT_INTERRUPTED
        raise
    except SystemExit as exc:
        result = invocation_ledger.RESULT_OK if exc.code in (0, None) else invocation_ledger.RESULT_ERROR
        raise
    except BaseException:
        result = invocation_ledger.RESULT_ERROR
        raise
    finally:
        recorder.finalize(result)


def _run_cli(argv: list[str] | None = None) -> int:
    raw = argv if argv is not None else sys.argv[1:]
    # --version / -V prints the public package name and version, resolving
    # to `dontpanic_orchestrate.__version__` as the single source of truth.
    if raw and raw[0] in ("--version", "-V"):
        from dontpanic_orchestrate import __version__

        print(f"dontpanic {__version__}")
        return 0
    if not raw:
        _print_top_level_help(file=sys.stderr)
        return 2
    if raw[0] in ("--help", "-h", "help"):
        _print_top_level_help(file=sys.stdout)
        return 0
    if raw and raw[0] == "ps":
        return _ps_main(raw[1:])
    if raw and raw[0] == "approve":
        return _approve_main(raw[1:])
    if raw and raw[0] == "resume":
        return _resume_main(raw[1:])
    if raw and raw[0] == "claude-touch":
        return _claude_touch_main(raw[1:])
    if raw and raw[0] == "close":
        return _close_main(raw[1:])
    if raw and raw[0] == "finalize":
        return _finalize_main(raw[1:])
    if raw and raw[0] == "what-now":
        return _what_now_main(raw[1:])
    if raw and raw[0] == "repair":
        return _repair_main(raw[1:])
    if raw and raw[0] == "plan-review":
        return _plan_review_main(raw[1:])
    if raw and raw[0] == "quota-caps":
        return _quota_caps_main(raw[1:])
    if raw and raw[0] == "projects":
        return _projects_main(raw[1:])
    if raw and raw[0] == "manifest":
        return _manifest_main(raw[1:])
    if raw and raw[0] == "agent":
        return _agent_main(raw[1:])
    if raw and raw[0] == "operator":
        from dontpanic_orchestrate.operator_brief import cli_main as _operator_brief_cli

        return _operator_brief_cli(raw[1:])
    if raw and raw[0] == "triage":
        from dontpanic_orchestrate.triage_apply import cli_main as _triage_apply_cli

        return _triage_apply_cli(raw[1:])
    if raw and raw[0] == "orchestrate":
        return _orchestrate_main(raw[1:])
    if raw and raw[0] == "roles":
        return _roles_main(raw[1:])
    if raw and raw[0] == "operator-roles":
        return _operator_roles_main(raw[1:])
    if raw and raw[0] == "skills":
        return _skills_main(raw[1:])
    if raw and raw[0] == "mcp":
        return _mcp_main(raw[1:])
    if raw and raw[0] == "state":
        from dontpanic_orchestrate import state_cli

        return state_cli.main(raw[1:])
    if raw and raw[0] == "plan":
        return _plan_main(raw[1:])
    if raw and raw[0] == "config":
        return _config_main(raw[1:])
    if raw and raw[0] == "project":
        return _project_main(raw[1:])
    if raw and raw[0] == "setup":
        return _setup_main(raw[1:])
    if raw and raw[0] == "calibrate-claude":
        return _calibrate_claude_main(raw[1:])
    if raw and raw[0] == "dispatch-from-plan":
        return _dispatch_from_plan_main(raw[1:])
    if raw and raw[0] == "doctor":
        return _doctor_main(raw[1:])
    if raw and raw[0] == "init":
        from dontpanic_orchestrate.init import init_main as _init_main

        return _init_main(raw[1:])
    if raw and raw[0] == "smoke":
        from dontpanic_orchestrate.smoke import smoke_main as _smoke_main

        return _smoke_main(raw[1:])
    if raw and raw[0] == "integrations":
        from dontpanic_orchestrate.integrations_cli import integrations_main as _itg_main

        return _itg_main(raw[1:])
    if raw and raw[0] == "architecture":
        from dontpanic_orchestrate import architecture as _arch

        return _arch.cli_main(raw[1:])
    if raw and raw[0] == "showcase":
        from dontpanic_orchestrate.showcase import showcase_main

        return showcase_main(raw[1:])
    if raw and raw[0] == "capabilities":
        sub = raw[1] if len(raw) > 1 else None
        if sub == "setup":
            from dontpanic_orchestrate.capabilities_setup import main as _capabilities_setup_main

            return _capabilities_setup_main(raw[2:])
        from dontpanic_orchestrate.capabilities_status import main as _capabilities_main

        return _capabilities_main(raw[1:])
    if raw and raw[0] == "reconcile":
        from dontpanic_orchestrate.reconcile import reconcile_main as _reconcile_main

        return _reconcile_main(raw[1:])
    if raw and raw[0] == "dashboard":
        from dontpanic_orchestrate.dashboard import main as _dashboard_main

        return _dashboard_main(raw[1:])
    if raw and raw[0] == "next":
        return _next_main(raw[1:])

    p = argparse.ArgumentParser(prog="dontpanic", description=__doc__)
    p.add_argument("plan", help="Plan ID (resolved against ./docs/plans/) or absolute dir path")
    p.add_argument("--feature", default="F001", help="Feature ID to dispatch (default F001)")
    p.add_argument(
        "--role", default="implementer", help="Single-agent mode: agent role (default implementer)"
    )
    p.add_argument(
        "--iteration", type=int, default=0, help="Single-agent mode: iteration number (default 0)"
    )
    p.add_argument(
        "--volley",
        action="store_true",
        help="Volley mode: implementer/auditor pair iterating until signoff or cap",
    )
    p.add_argument(
        "--implementer",
        default=None,
        help="Volley mode: implementer agent (default: agents_required[0])",
    )
    p.add_argument(
        "--auditor", default=None, help="Volley mode: auditor agent (default: agents_required[1])"
    )
    p.add_argument(
        "--max-iterations",
        type=int,
        default=None,
        help="Volley mode: override loop_caps.max_iterations",
    )
    p.add_argument(
        "--mode",
        default=None,
        choices=["interactive", "autonomous"],
        help="F007: runtime dispatch class override. interactive=bypass admission gates; "
        "autonomous=enforce. P0 is plan-derived only (plan.tier=p0) and cannot be "
        "forced via this flag — that would silently expand emergency-lane scope. "
        "Default: derived from plan.tier (p0 → p0; else autonomous).",
    )
    p.add_argument(
        "--allow-depth",
        type=int,
        default=None,
        help="Plan 2026-05-02-003 F001 (D002): operator-only override for nested-"
        "orchestration depth_limit. Frontmatter cannot raise the platform cap "
        "(default 3); this flag does, and the override is recorded in the "
        "audit envelope's validation_performed for audit-trail visibility.",
    )
    args = p.parse_args(raw)

    plan_dir = _resolve_plan_dir(args.plan)
    print(f"[supervisor] plan_dir={plan_dir}")

    if args.volley:
        print(
            f"[supervisor] mode=volley feature={args.feature} "
            f"impl={args.implementer or '(plan default)'} "
            f"aud={args.auditor or '(plan default)'} "
            f"runtime_class={args.mode or '(derived)'}"
        )
        try:
            result = supervisor.dispatch_volley(
                plan_dir=plan_dir,
                feature_id=args.feature,
                implementer_agent=args.implementer,
                auditor_agent=args.auditor,
                max_iterations=args.max_iterations,
                mode=args.mode,
                allow_depth=args.allow_depth,
                # Plan 2026-05-08-003 F002 — legacy `--volley` CLI is also
                # operator-initiated direct dispatch.
                direct_dispatch=True,
            )
        except QuotaExceeded as exc:
            print(f"[supervisor] BLOCKED by quota gate: {exc}", file=sys.stderr)
            return 2
        except (FileNotFoundError, KeyError, ValueError, RuntimeError) as exc:
            print(f"[supervisor] ERROR: {exc}", file=sys.stderr)
            return 1

        print(
            f"\n[supervisor] volley terminal: {result.final_status} after {result.rounds} round(s)"
        )
        print(f"[supervisor] reason: {result.reason}")
        print(f"[supervisor] {len(result.audit_paths)} audit JSONs written")
        # Exit 0 only if signed_off; non-zero for any non-success terminal
        return 0 if result.final_status == "signed_off" else 3

    # Single-agent path (F004 + F007 admission)
    print(
        f"[supervisor] mode=single feature={args.feature} role={args.role} "
        f"iter={args.iteration} runtime_class={args.mode or '(derived)'}"
    )
    try:
        audit_path = supervisor.dispatch_single_agent(
            plan_dir=plan_dir,
            feature_id=args.feature,
            agent_role=args.role,
            iteration=args.iteration,
            mode=args.mode,
            allow_depth=args.allow_depth,
        )
    except QuotaExceeded as exc:
        print(f"[supervisor] BLOCKED by quota gate: {exc}", file=sys.stderr)
        return 2
    except supervisor.PausedOnGate as exc:
        print(f"[supervisor] PAUSED on gate: {exc}", file=sys.stderr)
        return 3
    except supervisor.PausedOnDrift as exc:
        # F014 — single-agent path paused on plan drift (stale context or a
        # blocking scope/policy boundary awaiting `dontpanic approve <plan>
        # drift:<class>`). No paid call was made.
        print(f"[supervisor] PAUSED on plan drift: {exc}", file=sys.stderr)
        return 3
    except (FileNotFoundError, KeyError, ValueError) as exc:
        print(f"[supervisor] ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"[supervisor] ✓ wrote {audit_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
