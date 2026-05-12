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
import sys
from pathlib import Path

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
    plan_loader,
    project_config,
    projects_registry,
    quota_admission,
    quota_caps_loader,
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
            f"[{cli_label}] REFUSED gate-state reconciliation [{exc.kind}] "
            f"for {plan_id}.",
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
    tier = (
        loaded.plan.tier.value
        if hasattr(loaded.plan.tier, "value")
        else str(loaded.plan.tier)
    )
    agents = [
        a.value if hasattr(a, "value") else str(a)
        for a in (loaded.plan.agents_required or [])
    ]
    if not agents:
        agents = ["claude", "codex"]

    try:
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

    print(
        f"[close] operator-resolved feature {args.feature} "
        f"(class={args.reason_class})"
    )
    print(f"[close]   closeout memo: {result.memo_path}")
    print(f"[close]   signoff envelope: {result.signoff_path}")
    print(
        f"[close]   breaker:no_progress cleared: {result.breaker_cleared}"
    )
    print(
        f"[close]   features.json passes flipped: "
        f"{result.features_passes_flipped} ({result.features_json_path})"
    )
    print(
        "[close] NEXT: edit the closeout memo's `Rationale` section before "
        "merging."
    )
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
        # Sample codex rolling_5h via quota_check (sibling of dontpanic_orchestrate
        # under scripts/). Lazy-import to keep the loader decoupled.
        codex_observed: int | None = None
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
            import quota_check as qc

            sample = qc._codex_usage_v2("rolling_5h")
            codex_observed = int(sample.get("observed_native") or 0) or None
        except (ImportError, OSError, RuntimeError) as exc:
            print(
                f"[quota-caps] codex sample failed ({exc}); using high provisional cap",
                file=sys.stderr,
            )
            codex_observed = None
        try:
            data = quota_caps_loader.init_starter_file(
                codex_observed_5h=codex_observed,
                overwrite=overwrite,
            )
        except quota_caps_loader.QuotaCapsError as exc:
            print(f"[quota-caps] {exc}", file=sys.stderr)
            return 2
        # Print the resolved path (honors JARVIS_QUOTA_CAPS_PATH) so the
        # operator sees exactly what was written, not the default constant.
        print(f"[quota-caps] wrote {quota_caps_loader.effective_caps_path()}")
        if codex_observed is not None:
            cap = data["codex"]["plus"]["rolling_5h"]["cap"]
            print(
                f"[quota-caps] codex.plus.rolling_5h cap={cap} (observed {codex_observed} * 1.25)"
            )
        else:
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
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)

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

    payload: dict[str, object] = {
        "action": "added",
        "project": projects_registry.to_public_dict(entry),
    }
    if args.init_config:
        if scaffold_skipped:
            payload["scaffold"] = "skipped (config already exists)"
        elif scaffold_path is not None:
            payload["scaffold"] = str(scaffold_path)

    if args.as_json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(f"[projects add] registered {entry.name!r} → {entry.path}")
        if args.init_config:
            if scaffold_skipped:
                print(
                    "[projects add] per-project config already exists at "
                    f"{project_config.project_config_path(Path(entry.path))} — left untouched"
                )
            elif scaffold_path is not None:
                print(f"[projects add] scaffolded empty per-project config at {scaffold_path}")
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
    parser = argparse.ArgumentParser(
        prog="dontpanic doctor",
        description=(
            "Run the full doctor battery (structural + auth + per-project "
            "preflight). Output structured PASS / WARN / FAIL per check; "
            "exit 0 if all PASS, 1 if any WARN, 2 if any FAIL."
        ),
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

    results = jd.run_all_checks(
        skip_auth=args.skip_auth,
        include_projects=True,
        validate_plans=args.validate_plans,
    )
    print(jd.render_json(results) if args.json else jd.render_text(results))
    return jd.compute_strict_exit(results)


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
    except quota_caps_loader.QuotaCapsError:
        return "config_required", None

    vendors = state.get("vendors") or {}
    agents = sorted({implementer, auditor})
    primary_pct: dict[str, int] = {}
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
            return "config_required", None
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
    if readiness == "ok" and readiness_summary:
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
            "label without refusal."
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
        return 3

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
            "      is recorded to evidence/goal-governance/post_impl/override.json).",
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
    print(f"dontpanic plan: unknown subcommand {sub!r}", file=sys.stderr)
    return 2


def _plan_lock_main(argv: list[str]) -> int:
    """``dontpanic plan lock`` — canonical lock-time entry point for Goal
    Governance V1 F004. Wraps :func:`sufficiency_gate.lock_plan`."""
    parser = argparse.ArgumentParser(
        prog="dontpanic plan lock",
        description=(
            "Run the pre-impl sufficiency gate, then flip plan.md status from "
            "draft to active. For plans without goal_type, the gate is a no-op "
            "but the status flip still proceeds."
        ),
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
    args = parser.parse_args(argv)

    if args.override_reason is not None and not args.override_reason.strip():
        print(
            "[plan lock] --ignore-sufficiency-findings requires a non-empty reason",
            file=sys.stderr,
        )
        return 2

    plan_dir = _resolve_plan_dir(args.plan)
    print(f"[plan lock] plan_dir={plan_dir}")

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
    # NEVER block the lock outcome (D004: advisory only).
    try:
        loaded = plan_loader.load(plan_dir)
        skills_dir = _resolve_skills_dir(plan_dir)
        if skills_dir is not None:
            report = skill_applicability.match(loaded, skills_dir)
            sidecar = skill_applicability.write_report(report, plan_dir)
            print(
                f"[applicable-skills] {len(report.matches)} matches, "
                f"{len(report.skipped)} skips written to "
                f"{sidecar.relative_to(plan_dir)}"
            )
        else:
            print(
                "[applicable-skills] skipped — no claude/skills dir found "
                "above plan_dir"
            )
    except Exception as exc:  # noqa: BLE001 — advisory matcher must never block
        print(
            f"[applicable-skills] WARN: matcher failed ({exc!r}); "
            "lock succeeded — sidecar NOT written",
            file=sys.stderr,
        )

    return 0


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
    args = parser.parse_args(argv)

    plan_dir = _resolve_plan_dir(args.plan)
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
    return 0


# ─────────────────────────  config / project / setup (F006)  ─────────────────────────


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
            "                    `dontpanic project config set` instead).",
            file=sys.stderr,
        )
        return 2
    sub = argv[0]
    rest = argv[1:]
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
    parser = argparse.ArgumentParser(
        prog="dontpanic setup",
        description=(
            "Bootstrap operator config: roles + per-project runtime evidence "
            "defaults. Preview-by-default; use --yes to actually write."
        ),
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


def _print_top_level_help(*, file) -> None:
    print(
        """usage: dontpanic <command> [args]

Private-alpha command surface:
  setup                         Preview or write global roles + project runtime defaults
  config show|set               Inspect or edit ~/.dontpanic/config.json
  project config init|set        Inspect or edit <project>/.dontpanic/dontpanic.json
  projects add|list|show|remove  Register local projects for plan resolution
  manifest init|show             Publish the machine-readable agent manifest
  doctor                         Run local readiness checks
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


def main(argv: list[str] | None = None) -> int:
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
    if raw and raw[0] == "quota-caps":
        return _quota_caps_main(raw[1:])
    if raw and raw[0] == "projects":
        return _projects_main(raw[1:])
    if raw and raw[0] == "manifest":
        return _manifest_main(raw[1:])
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
    except (FileNotFoundError, KeyError, ValueError) as exc:
        print(f"[supervisor] ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"[supervisor] ✓ wrote {audit_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
