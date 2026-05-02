"""argparse entry for `python -m jarvis_orchestrate`.

Single-agent dispatch (F004):
  python -m jarvis_orchestrate <plan-id> [--feature F001] [--role implementer]

Volley dispatch (F005a — implementer/auditor pair, iterate until signoff or cap):
  python -m jarvis_orchestrate <plan-id> --volley [--feature F001]
                                                  [--implementer claude] [--auditor codex]
                                                  [--max-iterations 3]
                                                  [--mode interactive|p0|autonomous]

Pre-flight + dispatch (plan 2026-05-01-001 F002):
  python -m jarvis_orchestrate dispatch-from-plan <plan-id>
      [--feature F001] [--implementer claude] [--auditor codex]
      [--max-iterations N] [--mode interactive|autonomous] [--confirm]

  Strict dry-run by default: prints a 10-field pre-flight context block and
  exits 0 without dispatching, regardless of TTY state. With `--confirm`,
  validates quota readiness == ok and calls supervisor.dispatch_volley
  in-process. Blocking readiness states each exit 3 with a kind-specific
  remediation pointer:
    config_required        → `python -m jarvis_orchestrate quota-caps init`
    calibration_required   → `python -m jarvis_orchestrate calibrate-claude`
    unit_mismatch          → edit ~/.jarvis/quota_caps.json
    missing_state          → `python scripts/quota_check.py`

Active-supervisor registry (F023 EC13):
  python -m jarvis_orchestrate ps

Engagement-surface gate handling (F008 + F006 + F007):
  python -m jarvis_orchestrate approve <plan-id> <gate>      # preferred — clear one declared gate
  python -m jarvis_orchestrate resume  <plan-id> --gate <gate>  # parity alias for approve
  python -m jarvis_orchestrate resume  <plan-id> --all       # explicit bulk-clear (legacy behavior)

Interactive backoff touch (F007 Slice 2):
  python -m jarvis_orchestrate claude-touch               # record human Claude request now

Operator quota caps (plan 2026-04-30-001 F004):
  python -m jarvis_orchestrate quota-caps init [--overwrite]
  python -m jarvis_orchestrate quota-caps show

Claude calibration (plan 2026-04-30-001 F005):
  python -m jarvis_orchestrate calibrate-claude --dashboard-pct N [--window rolling_7d|rolling_5h]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from jarvis_orchestrate import (
    active_supervisors,
    calibration_loader,
    gate_pause,
    inbox,
    interactive_state,
    plan_loader,
    quota_admission,
    quota_caps_loader,
    supervisor,
)
from jarvis_orchestrate import (
    circuit_breakers as cb,
)
from jarvis_orchestrate.supervisor import QuotaExceeded


def _resolve_plan_dir(plan_arg: str) -> Path:
    p = Path(plan_arg)
    if p.is_dir():
        return p
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


def _approve_main(argv: list[str]) -> int:
    """F008 Item 2: clear a single declared gate for a plan."""
    if len(argv) != 2:
        print("usage: jarvis-orchestrate approve <plan-id> <gate>", file=sys.stderr)
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


_RESUME_BARE_USAGE = (
    "usage: jarvis-orchestrate resume <plan> (--gate <name> | --all)\n"
    "  preferred for partial clearance: jarvis-orchestrate approve <plan> <gate>\n"
    "  bulk clear (explicit): jarvis-orchestrate resume <plan> --all"
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
        prog="jarvis-orchestrate resume",
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
    active_breakers = gate_pause.active_breakers(plan_dir)
    active_defers = gate_pause.active_defers(plan_dir)

    if args.gate is not None:
        gate = args.gate
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
        print("usage: jarvis-orchestrate claude-touch", file=sys.stderr)
        return 2
    ts = interactive_state.touch("claude")
    minutes = interactive_state.backoff_minutes()
    print(
        f"[claude-touch] recorded human Claude request at {ts} "
        f"(backoff window {minutes:g} min). Autonomous Claude-heavy "
        "dispatches will defer until the window elapses."
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
            "usage: jarvis-orchestrate quota-caps {init|show} [--overwrite]",
            file=sys.stderr,
        )
        return 2
    sub = argv[0]
    rest = argv[1:]

    if sub == "init":
        overwrite = "--overwrite" in rest
        # Sample codex rolling_5h via quota_check (sibling of jarvis_orchestrate
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


def _calibrate_claude_main(argv: list[str]) -> int:
    """Plan 2026-04-30-001 F005: write Claude calibration ratio to the sticky
    file at ~/.jarvis/quota_calibration.json so F006 can convert the local
    weighted_tokens_local_proxy signal into a comparable percent_of_plan number.

    Reads observed_native from the requested window of the current
    ~/.jarvis/quota_state.json. The operator supplies the matching dashboard
    percent (claude.ai/settings/usage). Ratio = dashboard_pct / observed_native.
    """
    parser = argparse.ArgumentParser(
        prog="jarvis-orchestrate calibrate-claude",
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


# ──────────────────────────  dispatch-from-plan (F002)  ──────────────────────────


# Remediation lines surfaced by --confirm when readiness is non-ok. Kept here
# (not in supervisor or quota_caps_loader) because the strings are CLI-shaped:
# they reference the other `python -m jarvis_orchestrate ...` subcommands the
# operator would run from the same shell. Test acceptance pins each substring.
_READINESS_REMEDIATION: dict[str, str] = {
    "config_required": (
        "Remediation: run `python -m jarvis_orchestrate quota-caps init` "
        "(or edit ~/.jarvis/quota_caps.json if already present)."
    ),
    "calibration_required": (
        "Remediation: run `python -m jarvis_orchestrate calibrate-claude "
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
        prog="jarvis-orchestrate dispatch-from-plan",
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
            "                        → run: python -m jarvis_orchestrate quota-caps init\n"
            "                          (or edit ~/.jarvis/quota_caps.json if vendor entry missing)\n"
            "  calibration_required  Claude window has percent_of_plan cap with non-manual confidence\n"
            "                        → run: python -m jarvis_orchestrate calibrate-claude --dashboard-pct N\n"
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
    args = parser.parse_args(argv)

    # Plan resolution. Distinct exit code (2) from the dispatch path so
    # operator wrappers (Discord, cron) can disambiguate "plan invalid" from
    # "quota blocked".
    plan_arg = args.plan
    plan_dir_candidate: Path | None = None
    direct = Path(plan_arg)
    if direct.is_dir():
        plan_dir_candidate = direct
    else:
        cwd_match = Path.cwd() / "docs" / "plans" / plan_arg
        if cwd_match.is_dir():
            plan_dir_candidate = cwd_match
    if plan_dir_candidate is None:
        print(
            f"[dispatch-from-plan] plan not found: {plan_arg!r} "
            f"(looked under ./docs/plans/{plan_arg}/ and as a literal path)",
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
    agents_req = list(plan.agents_required or [])
    impl_default = str(agents_req[0]).split(".")[-1] if agents_req else "claude"
    aud_default = str(agents_req[1]).split(".")[-1] if len(agents_req) >= 2 else "codex"
    impl = args.implementer or impl_default
    aud = args.auditor or aud_default

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
        )
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


def main(argv: list[str] | None = None) -> int:
    raw = argv if argv is not None else sys.argv[1:]
    if raw and raw[0] == "ps":
        return _ps_main(raw[1:])
    if raw and raw[0] == "approve":
        return _approve_main(raw[1:])
    if raw and raw[0] == "resume":
        return _resume_main(raw[1:])
    if raw and raw[0] == "claude-touch":
        return _claude_touch_main(raw[1:])
    if raw and raw[0] == "quota-caps":
        return _quota_caps_main(raw[1:])
    if raw and raw[0] == "calibrate-claude":
        return _calibrate_claude_main(raw[1:])
    if raw and raw[0] == "dispatch-from-plan":
        return _dispatch_from_plan_main(raw[1:])

    p = argparse.ArgumentParser(prog="jarvis-orchestrate", description=__doc__)
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
