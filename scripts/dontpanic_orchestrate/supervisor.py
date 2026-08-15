"""Supervisor — orchestration entry points.

F004: dispatch_single_agent — one agent, one shot.
F005a: dispatch_volley — implementer/auditor pair, iterate until signoff or cap.

Both read ~/.jarvis/quota_state.json before each dispatch (F020 gate) and
soft-warn at >=90%; flip JARVIS_QUOTA_ENFORCE=hard to raise QuotaExceeded.
"""

from __future__ import annotations

import atexit
import datetime as dt
import json
import os
import re
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dontpanic_orchestrate import (
    active_supervisors,
    audit_writer,
    auditor_taxonomy,
    circuit_breakers,
    command_guard,
    completion_gate,
    decision_brief,
    ec5_classifier,
    gate_pause,
    inbox,
    model_catalog,
    nested_orchestration,
    notify,
    notify_event,
    patch_completeness_gate,
    plan_drift,
    plan_loader,
    project_config,
    projects_registry,
    prompts,
    quota_admission,
    quota_caps_loader,
    signoff_writer,
    sufficiency_gate,
    transcript,
    verification_runner,
    worker_profiles,
)
from dontpanic_orchestrate.config.resolvers import resolve_model
from dontpanic_orchestrate.environments_loader import (
    check_firebaserc_consistency,
    find_repo_root_for_plan,
    load_environments,
    validate_target,
)
from dontpanic_orchestrate.execution_environment import ExecutionEnvironment
from dontpanic_orchestrate.executors import get_executor
from dontpanic_orchestrate.executors.base import (
    BaseExecutor,
    DispatchTask,
    _derive_permission_policy,
)
from dontpanic_orchestrate.plan_review import cross_feature

QUOTA_STATE_PATH = Path.home() / ".jarvis" / "quota_state.json"
SOFT_THRESHOLD_PERCENT = 90.0


class QuotaExceeded(RuntimeError):
    pass


class PausedOnGate(RuntimeError):
    """F007 Slice 2: raised by dispatch_single_agent when pre-dispatch
    admission or plan-declared gates leave at least one entry unmet. The
    volley path returns a VolleyResult instead since it has a structured
    terminal type; single-agent dispatch returns Path on success, so the
    pause case is signaled via exception instead."""

    pass


class PausedOnDrift(RuntimeError):
    """F014 (codex F009 #5): raised by dispatch_single_agent when the SAME F009
    plan-drift reconciliation the volley path runs pauses the single-agent
    dispatch — either the plan context drifted between dispatch-start baseline
    and the paid call (no paid single-agent call proceeds on stale context), or
    a prior BLOCKING_POLICY scope/policy drift is still awaiting human
    acknowledgement (`dontpanic approve <plan> drift:<class>`). The volley path
    returns ``VolleyResult(final_status="paused_on_drift")``; single-agent
    dispatch returns Path on success, so it signals the pause via exception."""

    pass


# Plan 2026-05-08-003 F002 — operator/runtime envs that must NEVER auto-clear
# `pre_impl` even on direct dispatch. Match is case-insensitive against
# ``effective_env`` (the resolved string the supervisor stamps on INBOX).
_AUTO_CLEAR_REFUSED_ENVS: frozenset[str] = frozenset({"prod", "production"})

_AUTO_CLEAR_ACTOR: str = "supervisor:auto_clear_pre_impl"


def _load_prior_envelopes_for_classification(
    audit_paths: list[Path],
    *,
    exclude: Path | None = None,
) -> list[dict[str, Any]]:
    """Plan 2026-05-08-003 F003 — load earlier audit envelopes (implementer
    + auditor) for taxonomy ``collect_saved_evidence_paths`` so the
    evidence-shape classifier sees evidence the implementer landed in
    prior rounds. Best-effort: malformed JSON / missing files are skipped
    silently — the classifier degrades to ``unknown``/``defect`` rather
    than crashing the no-progress terminal."""
    out: list[dict[str, Any]] = []
    for ap in audit_paths:
        if exclude is not None and ap == exclude:
            continue
        try:
            text = ap.read_text()
            payload = json.loads(text)
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            out.append(payload)
    return out


def _maybe_auto_clear_pre_impl(
    *,
    loaded: plan_loader.LoadedPlan,
    declared_gates: list[Any],
    direct_dispatch: bool,
    effective_env: str | None,
    effective_project: str | None,
    feature_id: str,
) -> str | None:
    """Plan 2026-05-08-003 F002 — narrow auto-clear of the `pre_impl`
    lifecycle gate for direct operator dispatch in eligible dev/test
    contexts. Returns the recorded reason on auto-clear, ``None`` when
    the policy refuses (caller falls through to the normal staged pause).

    Refuses when any of the following holds:
      - ``direct_dispatch`` is False (background/programmatic dispatch
        keeps the normal manual approve/resume contract).
      - ``effective_env`` matches a prod/production label.
      - the plan does not declare ``pre_impl``.
      - ``pre_impl`` is already in ``cleared_gates``.
      - the staged ``pre_impl`` evaluation has more than one pending gate
        (multi-gate states never auto-clear beyond the owned single-gate
        case — D005).

    On success: writes a normal gate event with ``actor='supervisor:
    auto_clear_pre_impl'`` so the audit log distinguishes auto-clear from
    operator approve/resume entries, plus an operator-readable INBOX
    ``auto_cleared_pre_impl`` event naming the command context. Manual
    approve/resume semantics for every other gate are unchanged.
    """
    if not direct_dispatch:
        return None
    if effective_env and effective_env.strip().lower() in _AUTO_CLEAR_REFUSED_ENVS:
        return None

    declared_strs = [g.value if hasattr(g, "value") else str(g) for g in declared_gates]
    if "pre_impl" not in declared_strs:
        return None

    compat = gate_pause.load_gate_state_compat(loaded.plan_dir)
    if "pre_impl" in compat.cleared_gates:
        return None

    pre_impl_info = gate_pause.evaluate_human_gates(
        loaded.plan_dir, declared_gates, stage="pre_impl"
    )
    if pre_impl_info.pending != ["pre_impl"]:
        # Either nothing pending (unusual at this seam — staged check
        # already gated that), or a multi-gate stage state. D005 forbids
        # the wide carve-out; defer to the manual flow.
        return None

    auto_reason = (
        "direct operator dispatch; "
        f"target_env={effective_env or '(none)'}; "
        f"target_project={effective_project or '(none)'}; "
        "pre_impl is the only pending lifecycle gate."
    )
    # Pause briefly so `gate_events` carries the same shape as the manual
    # path (paused → cleared transition with stage='pre_impl'). This keeps
    # downstream audit consumers — signoff_writer, transcripts — uniform
    # whether the clear came from auto-clear or operator approve.
    gate_pause.record_pause(
        loaded.plan_dir,
        plan_id=loaded.plan_id,
        pause_gates=["pre_impl"],
        stage="pre_impl",
    )
    changed = gate_pause.approve_gate(
        loaded.plan_dir,
        "pre_impl",
        plan_id=loaded.plan_id,
        actor=_AUTO_CLEAR_ACTOR,
    )
    if not changed:
        # Should not happen given the cleared_gates check above, but be
        # defensive — failing closed (manual flow) is always safer than
        # failing open.
        return None

    inbox.append_event(
        loaded.plan_dir,
        event="auto_cleared_pre_impl",
        plan_id=loaded.plan_id,
        body=(
            "Supervisor auto-cleared the `pre_impl` lifecycle gate for "
            "this direct CLI dispatch.\n\n"
            f"Reason: {auto_reason}\n\n"
            "This narrow carve-out applies only to direct operator "
            "dispatch in dev/test contexts where `pre_impl` is the sole "
            "pending lifecycle gate. Manual `approve` / `resume --gate` "
            "/ `resume --all` semantics are unchanged for all other "
            "paths and gates."
        ),
        actor=_AUTO_CLEAR_ACTOR,
        target_env=effective_env or "(none)",
        target_project=effective_project or "(none)",
        feature_id=feature_id,
    )
    return auto_reason


def _sync_pre_impl_for_active_plan(
    loaded: plan_loader.LoadedPlan,
    *,
    feature_id: str | None = None,
) -> None:
    """Plan 2026-05-09-002 F002 — post-reconcile sync: when ``plan.md``
    status is ``active`` (lock complete + ready for implementer), clear
    the ``pre_impl`` lifecycle gate implicitly so dispatch proceeds
    without a separate ``dontpanic approve <plan> pre_impl`` step.

    Runs AFTER :func:`_reconcile_gate_state_or_raise` returns
    successfully (D004 of plan 2026-05-09-002): the reconciliation
    helper stays documented-pure per its plan 2026-05-08-003 F001
    contract, and the mutation lives in
    :func:`gate_pause.implicit_clear_pre_impl_for_active_plan`.

    Trigger is ``status == 'active'`` exactly. Post-implementation
    states (``ready_for_audit``, ``in_audit``, ``completed``,
    ``abandoned``, ``blocked``) explicitly do NOT trigger — a completed
    plan should not be re-dispatchable through this seam (D005).
    """
    if not plan_loader.plan_status_enables_implicit_pre_impl(loaded):
        return
    declared = list(loaded.plan.human_gates or [])
    changed = gate_pause.implicit_clear_pre_impl_for_active_plan(
        loaded.plan_dir,
        plan_id=loaded.plan_id,
        declared_gates=declared,
    )
    if not changed:
        return
    inbox.append_event(
        loaded.plan_dir,
        event="pre_impl_status_synced",
        plan_id=loaded.plan_id,
        body=(
            "Supervisor implicitly cleared the `pre_impl` lifecycle gate "
            "because plan.md status is `active`.\n\n"
            f"Plan: {loaded.plan_id}\n"
            f"Status: active\n"
            f"Feature: {feature_id or '(none)'}\n\n"
            "An operator who flips status to `active` (with a lock D-entry "
            "in decisions.jsonl) is signaling that the plan is ready for "
            "implementer dispatch. The supervisor treats the status flip as "
            "the authorizing action — no separate `dontpanic approve <plan> "
            "pre_impl` is required.\n\n"
            "Manual approve/resume semantics for every other gate "
            "(`pre_merge`, `on_escalation`, `breaker:*`, `defer:*`) are "
            "unchanged. Only `pre_impl` is in scope for this implicit "
            "clearance, and only when status is exactly `active`."
        ),
        status="active",
        feature_id=feature_id or "",
    )


def _attention_brief(
    loaded: plan_loader.LoadedPlan | None,
    feature_id: str | None,
    *,
    inbox_event: str,
    pending_gates: list[str] | None = None,
) -> decision_brief.DecisionBrief | None:
    """Plan 2026-08-09-002 F005 — the brief for a non-gate attention event.

    Every renderable ``needs_action`` event the supervisor emits goes through
    here, so the impact-first copy is live on the production path rather than
    only under a test that hands ``render()`` a brief. Returns ``None`` when
    no ``LoadedPlan`` is in scope: a brief built from nothing would report the
    plan id as "what changes", which is worse than the pre-existing copy the
    renderer falls back to. Never raises — these notifications are advisory by
    contract and must not take a dispatch down.
    """
    if loaded is None:
        return None
    try:
        return decision_brief.build_for_attention(
            loaded,
            feature_id,
            inbox_event=inbox_event,
            pending_gates=pending_gates or [],
        )
    except Exception:  # noqa: BLE001 — advisory copy, never fatal
        return None


def _reconcile_gate_state_or_raise(
    plan_dir: Path,
    *,
    plan_id: str,
    declared_gates: list[Any],
    feature_id: str | None = None,
    loaded: plan_loader.LoadedPlan | None = None,
) -> None:
    """Plan 2026-05-08-003 F001 — fail-loud gate-state reconciliation entry
    point. Wraps :func:`gate_pause.reconcile_gate_state` so every dispatch path
    surfaces the contradiction the same way: classified INBOX event +
    terminal-notifier ping + re-raise for the supervisor's caller to surface.

    No mutation of ``gate-state.json`` before the failure (D004); the artifact
    stays inspectable for operator remediation.
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
            feature_id=feature_id or "",
        )
        # Plan 2026-05-24-004 F003 (audit i0 finding #3): dispatch through
        # ALL sinks so the rendered terminal path produces the modern
        # "DontPanic [..]" title (replaces the legacy jarvis: notify.notify
        # that used to fire here). INBOX write above is the truth-of-record;
        # both live channels are advisory and fail-soft.
        notify_event.dispatch_event(
            notify_event.NotifyEvent(
                kind="gate_state_reconciliation_failed",
                severity=notify_event.SEVERITY_ESCALATION,
                plan_id=plan_id,
                feature_id=feature_id,
                body=(
                    f"**Gate-state contradiction** — `{exc.kind}` "
                    f"(gate=`{exc.gate or '-'}`, stage=`{exc.stage or '-'}`). "
                    f"See INBOX for full reconciliation report."
                ),
                evidence_uri=str(exc.persisted_state_path),
                timestamp=dt.datetime.now(dt.timezone.utc),
                inbox_event="gate_state_reconciliation_failed",
                subtype=exc.kind,
                technical_metadata={
                    "gate": exc.gate or "",
                    "stage": exc.stage or "",
                    "persisted_state_path": str(exc.persisted_state_path),
                },
                decision_brief=_attention_brief(
                    loaded, feature_id, inbox_event="gate_state_reconciliation_failed"
                ),
            ),
            plan_dir=plan_dir,
        )
        raise


def _trip_breaker(
    plan_dir: Path,
    plan_id: str,
    feature_id: str,
    kind: circuit_breakers.BreakerKind,
    reason: str,
    loaded: plan_loader.LoadedPlan | None = None,
) -> None:
    """F006 — record the breaker hit. The 6 approval-required kinds add a
    synthetic gate; all 7 (including the global hard-stop) record an INBOX
    entry, fire terminal-notifier, and append to ~/.jarvis/breaker_history.jsonl
    so the global breaker can count cap-hits across plans."""
    circuit_breakers.record_global_hit(plan_id, kind)
    if kind in circuit_breakers.APPROVAL_BREAKERS:
        gate_pause.add_breaker(
            plan_dir, circuit_breakers.gate_name(kind), plan_id=plan_id, reason=reason
        )
    inbox.append_event(
        plan_dir,
        event="breaker_tripped",
        plan_id=plan_id,
        body=(
            f"Circuit breaker tripped: {kind.value}\n\n"
            f"Reason: {reason}\n\n"
            + (
                "Operator clearance required: "
                f"`jarvis approve {plan_id} breaker:{kind.value}` "
                f"or `jarvis resume {plan_id} --all`."
                if kind in circuit_breakers.APPROVAL_BREAKERS
                else "Hard stop: global circuit breaker. No operator clearance "
                "available — wait out the 24h window."
            )
        ),
        breaker_kind=kind.value,
        feature_id=feature_id,
        approval_required=str(kind in circuit_breakers.APPROVAL_BREAKERS).lower(),
    )
    # Plan 2026-05-24-004 F003 (audit i0 finding #3): dispatch through ALL
    # sinks so the rendered terminal path produces the modern "DontPanic [..]"
    # title (replaces the legacy `jarvis: breaker` notify.notify above).
    notify_event.dispatch_event(
        notify_event.NotifyEvent(
            kind="breaker_tripped",
            severity=notify_event.SEVERITY_ESCALATION,
            plan_id=plan_id,
            feature_id=feature_id,
            body=f"**Breaker** `{kind.value}` — {reason[:300]}",
            evidence_uri=str(plan_dir / "INBOX.md"),
            timestamp=dt.datetime.now(dt.timezone.utc),
            inbox_event="breaker_tripped",
            breaker_kind=kind.value,
            # The six approval breakers name the gate the operator would
            # clear; the global hard stop deliberately names none, and the
            # brief then says so rather than promising a clearance that does
            # not exist.
            decision_brief=_attention_brief(
                loaded,
                feature_id,
                inbox_event="breaker_tripped",
                pending_gates=(
                    [circuit_breakers.gate_name(kind)]
                    if kind in circuit_breakers.APPROVAL_BREAKERS
                    else []
                ),
            ),
        ),
        plan_dir=plan_dir,
    )


def _emit_gate_paused_discord(
    plan_dir: Path,
    plan_id: str,
    feature_id: str,
    *,
    pending_gates: list[str],
    stage: str = "general",
    target_env: str | None = None,
    target_project: str | None = None,
    loaded: plan_loader.LoadedPlan | None = None,
) -> None:
    """Plan 2026-05-01-002 F003 — gate-pause notification emit.

    Plan 2026-05-24-004 F003 (audit i0 finding #3): dispatches through ALL
    sinks (Discord + terminal-notifier) rather than Discord-only. The
    callers used to fire a paired legacy ``notify.notify(title="jarvis: gate
    pause...")`` for the terminal channel; that legacy emit has been
    removed so the modern rendered path (DontPanic-branded title +
    value-first headline) is the single source of truth. INBOX write at
    each caller is the truth-of-record; the live channels are advisory.

    Always action_required severity (pauses are by definition
    operator-actionable). evidence_uri points at the plan's INBOX.md so
    operators can drill down. Populates ``inbox_event='gate_hit'`` (per
    F002) and threads ``subtype`` (stage), ``target_env``, ``target_project``
    so the translation table can render structured copy.

    Plan 2026-08-09-002 F003: this is the pause-emission site, and the only
    place on the live path where the plan title and the feature's declared
    ``user_impact`` are both in scope — ``dispatch_event`` calls
    ``event_copy.render(event)`` with no metadata arguments. So the
    DecisionBrief is snapshotted here and rides along on the event, immutable,
    for every sink to read. ``loaded`` is optional so callers that have no
    LoadedPlan (none today) still emit a working pause notification."""
    brief = (
        decision_brief.build_for_gate_pause(
            loaded,
            feature_id,
            stage=stage,
            pending_gates=list(pending_gates),
        )
        if loaded is not None
        else None
    )
    # Plan 2026-08-09-002 F005 (audit i2 finding 2): until now the only
    # structured orchestration fact this emitter published was ``subtype``
    # (the *stage*). F005 moves the plan label, gate and stage out of the
    # headline and into a supporting reference line — and a fact the event
    # never carried cannot be relocated, so the pause was rendering
    # "stage `implement`" and silently dropping the gate the operator is being
    # asked to clear.
    #
    # The gate is published under ``pending_gates`` rather than ``gate`` on
    # purpose. ``event_copy._reference_gate_stage`` reads ``pending_gates``
    # first, so the reference line now names the real gate; but
    # ``event_copy._gather_fields`` derives the ``{gate}`` format field from
    # ``gate`` / ``subtype`` only, so the rendered approval command still
    # resolves through the subtype alias and stays byte-identical. That
    # matters: F005 is prose-only and its acceptance 7 forbids moving any
    # exact command (audit i0 finding 1 caught an earlier revision of this
    # feature doing exactly that by publishing ``gate``). The approval command
    # naming the stage rather than the gate remains a real defect, owned by
    # plan 2026-08-10-001 F001/F002 which changes it on purpose and carries
    # the before/after evidence. ``tests/tools/f005_emitter_command_probe.py``
    # drives this emitter and pins the command against the pre-change capture
    # in ``tests/fixtures/f005_prechange_emitter_commands.json``.
    #
    # Empty values are omitted rather than published as empty strings: a pause
    # with no unmet gate has no gate to name, and the reference line stays
    # quiet instead of printing an empty pair of backticks.
    gate_reference = {
        key: value
        for key, value in (
            ("pending_gates", ", ".join(pending_gates)),
            ("stage", stage),
        )
        if value
    }
    notify_event.dispatch_event(
        notify_event.NotifyEvent(
            kind="gate_paused",
            severity=notify_event.SEVERITY_ACTION_REQUIRED,
            plan_id=plan_id,
            feature_id=feature_id,
            body=(
                f"**Gate pause** ({stage}) — awaiting: "
                f"{', '.join(pending_gates) or '(none)'}\n"
                f"Clear: `dontpanic approve {plan_id} <gate>` or "
                f"`dontpanic resume {plan_id} --all`"
            ),
            evidence_uri=str(plan_dir / "INBOX.md"),
            timestamp=dt.datetime.now(dt.timezone.utc),
            inbox_event="gate_hit",
            subtype=stage,
            target_env=target_env,
            target_project=target_project,
            technical_metadata=gate_reference,
            decision_brief=brief,
        ),
        plan_dir=plan_dir,
    )


def _maybe_emit_quota_warn(
    plan_dir: Path,
    plan_id: str,
    agent: str,
    pct: float | None,
    feature_id: str,
) -> None:
    """F008 Item 1 — emit INBOX quota_warn when soft threshold hit (enforce=soft)."""
    if pct is None or pct < SOFT_THRESHOLD_PERCENT:
        return
    inbox.append_event(
        plan_dir,
        event="quota_warn",
        plan_id=plan_id,
        body=(
            f"Quota soft-warn: {agent} at {pct}% of weekly cap "
            f"(threshold {SOFT_THRESHOLD_PERCENT}%). Volley proceeding because "
            "JARVIS_QUOTA_ENFORCE=soft (default). Set =hard to halt at threshold."
        ),
        agent=agent,
        percent_weekly=pct,
        threshold=SOFT_THRESHOLD_PERCENT,
        feature_id=feature_id,
    )
    # Plan 2026-05-24-004 F003 — dashboard_action disposition: routes the
    # soft-warn through the sidecar + INBOX rendered annotation so the
    # dashboard shows the quota pressure without paging Discord.
    notify_event.dispatch_event(
        notify_event.NotifyEvent(
            kind="quota_warn",
            severity=notify_event.SEVERITY_INFO,
            plan_id=plan_id,
            feature_id=feature_id,
            body="",
            timestamp=dt.datetime.now(dt.timezone.utc),
            inbox_event="quota_warn",
            technical_metadata={
                "agent": agent,
                "percent_weekly": pct,
                "threshold": SOFT_THRESHOLD_PERCENT,
            },
        ),
        plan_dir=plan_dir,
    )


@contextmanager
def _registered_supervisor(
    plan_id: str,
    target_env: str,
    target_project: str | None,
    config_dir: str | None,
    plan_dir: Path | None = None,
    dispatch_fingerprint: plan_drift.PlanFingerprint | None = None,
):
    """F023 EC13: register the running supervisor in
    ~/.jarvis/active_supervisors.jsonl on entry, unregister on exit. Re-entrancy
    against the same plan_id surfaces a warning (not a hard block — the operator
    may legitimately want overlapping runs against different cloud projects but
    the same plan structure).

    F009 (codex #2) — the active supervisor state records the dispatch-start
    plan-run fingerprint (source file content hashes + mtimes + capture time) so
    it captures WHAT plan state this run is operating against. When the volley
    path passes ``dispatch_fingerprint`` (the fingerprint recorded BEFORE plan
    load, at dispatch start), that EXACT fingerprint is persisted — not a later
    recompute taken after plan load / gate preflight mutations, which would
    record post-mutation state and defeat true dispatch-start accountability.
    On the volley path this is also FAIL CLOSED: if the dispatch-start
    fingerprint cannot be persisted into active state, registration raises
    rather than running with no recorded baseline-of-record. The single-agent
    path (no ``dispatch_fingerprint``) keeps the advisory recompute fallback —
    F009's drift contract is volley-only (single-agent SPLIT to F014)."""
    existing = active_supervisors.check_reentrancy(plan_id)
    if existing is not None and existing.pid != os.getpid():
        print(
            f"[supervisor-registry] WARNING re-entrancy: another supervisor "
            f"(pid={existing.pid}, env={existing.target_env}, "
            f"project={existing.target_project or '(none)'}) is already active "
            f"on plan {plan_id!r}. Audits may interleave."
        )
    fingerprint_meta: dict | None = None
    require_fingerprint = dispatch_fingerprint is not None
    if dispatch_fingerprint is not None:
        # Persist the dispatch-start fingerprint verbatim (codex #2).
        fingerprint_meta = {
            "file_hashes": dispatch_fingerprint.file_hashes,
            "file_mtimes": dispatch_fingerprint.file_mtimes,
            "captured_at": dispatch_fingerprint.captured_at,
        }
    elif plan_dir is not None:
        # Single-agent / fallback path: advisory recompute (best-effort).
        try:
            fp = plan_drift.compute_fingerprint(plan_dir)
            fingerprint_meta = {
                "file_hashes": fp.file_hashes,
                "file_mtimes": fp.file_mtimes,
                "captured_at": fp.captured_at,
            }
        except Exception as _fp_exc:  # noqa: BLE001 — advisory metadata
            print(f"[supervisor-registry] fingerprint capture skipped: {_fp_exc}")
    try:
        entry = active_supervisors.register(
            plan_id=plan_id,
            target_env=target_env,
            target_project=target_project,
            supervisor_config_dir=config_dir,
            plan_fingerprint=fingerprint_meta,
        )
    except Exception as _reg_exc:  # noqa: BLE001 — fail closed when required
        if require_fingerprint:
            raise RuntimeError(
                f"F009 fail-closed: could not persist dispatch-start plan-run "
                f"fingerprint into active supervisor state for {plan_id!r} "
                f"({_reg_exc})"
            ) from _reg_exc
        raise
    # FAIL CLOSED (codex #2): on the volley path the dispatch-start fingerprint
    # is the baseline-of-record for active-run accountability. If it did not
    # round-trip into the persisted entry, refuse to run blind.
    if require_fingerprint and not getattr(entry, "plan_fingerprint", None):
        raise RuntimeError(
            f"F009 fail-closed: active supervisor entry for {plan_id!r} did not "
            "persist the dispatch-start plan-run fingerprint"
        )
    cleanup_done = {"flag": False}

    def _cleanup() -> None:
        if cleanup_done["flag"]:
            return
        cleanup_done["flag"] = True
        active_supervisors.unregister(plan_id, pid=entry.pid)

    atexit.register(_cleanup)
    try:
        yield entry
    finally:
        _cleanup()


def _validate_environment_registry(
    plan_dir: Path, target_env: str, target_project: str | None
) -> tuple[str | None, Path | None, str]:
    """F023 EC1+A + EC11 pre-dispatch check.

    Returns (registry_repo_label_or_None, registry_repo_root_or_None, log_line).
    Raises EnvironmentsTargetMismatchError / EnvironmentsValidationError to halt
    dispatch before ExecutionEnvironment opens or any executor is called. Host-
    local plans (target_project=None) and plans living outside any
    environments.json scope skip silently. When the registry resolves and the
    consumer repo has a .firebaserc, EC11 also verifies the target project is
    reachable via that file.
    """
    if target_project is None:
        return None, None, "[env-registry] target_project=None (host-local) — skip"
    repo_root = find_repo_root_for_plan(plan_dir)
    if repo_root is None:
        return None, None, "[env-registry] no environments.json on path — skip"
    env = load_environments(repo_root)
    validate_target(env, target_env, target_project)
    fr_status = check_firebaserc_consistency(repo_root, target_project)
    fr_tail = f" + {fr_status}" if fr_status else ""
    return (
        env.repo,
        repo_root,
        (
            f"[env-registry] {env.repo} ({repo_root}): "
            f"{target_env} → {target_project} validated{fr_tail}"
        ),
    )


def _read_quota_state() -> dict | None:
    """F020 quota gate read. Honors JARVIS_QUOTA_STATE_PATH for hermetic
    test isolation (matches F006/F007 admission paths)."""
    env_override = os.environ.get("JARVIS_QUOTA_STATE_PATH")
    p = Path(env_override) if env_override else QUOTA_STATE_PATH
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _format_admission_quota_reason(quota: quota_admission.QuotaCheck) -> str:
    """F006b fix#1: render the admission defer reason without crashing on
    observed_pct=None. Numeric path keeps the historical 'percent_weekly N%
    > threshold M%' shape so existing INBOX log parsing works; cause path
    surfaces the structured cause for caps_file_missing / calibration_required
    / unit_mismatch / missing_vendor_block / no_cap_for_signal."""
    pct = quota.observed_pct
    threshold = quota.threshold
    agent = quota.offending_agent or "?"
    if isinstance(pct, (int, float)):
        return f"{agent} percent_weekly {float(pct):.1f}% > threshold {threshold:.1f}%"
    cause = quota.cause or "unknown"
    return (
        f"{agent} defer:{cause} (no numeric observed_pct; see "
        "~/.jarvis/quota_state.json + ~/.jarvis/quota_caps.json or run "
        "`python -m dontpanic_orchestrate quota-caps init`)"
    )


def _emit_budget_kind_specific_event(
    plan_dir: Path,
    plan_id: str,
    bd_result: circuit_breakers.BudgetCeilingResult,
    feature_id: str,
    loaded: plan_loader.LoadedPlan | None = None,
) -> None:
    """F006b fix#1: emit a kind-specific INBOX event BEFORE the generic
    breaker_tripped event from _trip_breaker. Keeps the F008 gate-pause
    semantics unchanged (volley still pauses on breaker:budget_ceiling) while
    giving operators a clear action signal in INBOX:

      - CALIBRATION_REQUIRED → 'calibration_required' event with
        calibrate-claude command
      - UNIT_MISMATCH → 'unit_mismatch' event pointing at quota_caps.json
      - CONFIG_REQUIRED → 'config_required' event with details.cause
        (caps_file_missing / no_cap_for_signal / missing_vendor_block)
      - TRIPPED → no extra event (the breaker_tripped one is sufficient)
    """
    kind = bd_result.kind
    if kind == circuit_breakers.BudgetCeilingKind.CALIBRATION_REQUIRED:
        inbox.append_event(
            plan_dir,
            event="calibration_required",
            plan_id=plan_id,
            body=(
                f"Calibration required for {bd_result.agent}.{bd_result.window} "
                f"(confidence={bd_result.confidence!r}). The breaker cannot "
                f"convert weighted_tokens_local_proxy into percent_of_plan "
                "without a manual calibration sample. Run:\n\n"
                f"  python -m dontpanic_orchestrate calibrate-claude "
                f"--window {bd_result.window} --dashboard-pct N\n\n"
                "where N is the current percent shown on "
                "claude.ai/settings/usage for the matching window."
            ),
            agent=bd_result.agent or "",
            window=bd_result.window or "",
            feature_id=feature_id,
        )
        # Plan 2026-05-01-002 F003 — calibration_required emit point.
        # Plan 2026-05-24-004 F003 (audit i0 finding #1): fan to ALL sinks so
        # the rendered terminal + sidecar + INBOX-annotation paths fire for
        # this LIVE-disposition event (was Discord-only).
        notify_event.dispatch_event(
            notify_event.NotifyEvent(
                kind="calibration_required",
                severity=notify_event.SEVERITY_ACTION_REQUIRED,
                plan_id=plan_id,
                feature_id=feature_id,
                body=(
                    f"**Calibration required** for `{bd_result.agent}."
                    f"{bd_result.window}`. Run "
                    f"`python -m dontpanic_orchestrate calibrate-claude "
                    f"--window {bd_result.window} --dashboard-pct N`."
                ),
                evidence_uri=str(plan_dir / "INBOX.md"),
                timestamp=dt.datetime.now(dt.timezone.utc),
                inbox_event="calibration_required",
                technical_metadata={
                    "agent": bd_result.agent or "",
                    "window": bd_result.window or "",
                },
                decision_brief=_attention_brief(
                    loaded, feature_id, inbox_event="calibration_required"
                ),
            ),
            plan_dir=plan_dir,
        )
    elif kind == circuit_breakers.BudgetCeilingKind.UNIT_MISMATCH:
        inbox.append_event(
            plan_dir,
            event="unit_mismatch",
            plan_id=plan_id,
            body=(
                f"Unit mismatch for {bd_result.agent}.{bd_result.tier}."
                f"{bd_result.window}: cap.unit={bd_result.cap_unit!r} ≠ "
                f"observed_unit={bd_result.observed_unit!r}. Edit "
                "~/.jarvis/quota_caps.json so cap.unit matches what "
                "quota_check.py emits."
            ),
            agent=bd_result.agent or "",
            window=bd_result.window or "",
            feature_id=feature_id,
        )
        # Plan 2026-05-24-004 F003 — dashboard_action: surface the cap
        # drift on the dashboard via the sidecar path.
        notify_event.dispatch_event(
            notify_event.NotifyEvent(
                kind="unit_mismatch",
                severity=notify_event.SEVERITY_ACTION_REQUIRED,
                plan_id=plan_id,
                feature_id=feature_id,
                body="",
                timestamp=dt.datetime.now(dt.timezone.utc),
                inbox_event="unit_mismatch",
                technical_metadata={
                    "agent": bd_result.agent or "",
                    "window": bd_result.window or "",
                    "cap_unit": bd_result.cap_unit or "",
                    "observed_unit": bd_result.observed_unit or "",
                },
                decision_brief=_attention_brief(
                    loaded, feature_id, inbox_event="unit_mismatch"
                ),
            ),
            plan_dir=plan_dir,
        )
    elif kind == circuit_breakers.BudgetCeilingKind.CONFIG_REQUIRED:
        cause = (bd_result.details or {}).get("cause", "unknown")
        inbox.append_event(
            plan_dir,
            event="config_required",
            plan_id=plan_id,
            body=(
                f"Quota config required (cause={cause}). "
                + (bd_result.reason or "")
                + "\n\nRun `python -m dontpanic_orchestrate quota-caps init` to "
                "seed defaults, hand-edit ~/.jarvis/quota_caps.json for "
                "no_cap_for_signal, or re-run scripts/quota_check.py for "
                "missing_vendor_block."
            ),
            cause=cause,
            feature_id=feature_id,
        )
        # Plan 2026-05-24-004 F003 — dashboard_action: operator must seed
        # quota config; surface as an ActionItem on the dashboard.
        notify_event.dispatch_event(
            notify_event.NotifyEvent(
                kind="config_required",
                severity=notify_event.SEVERITY_ACTION_REQUIRED,
                plan_id=plan_id,
                feature_id=feature_id,
                body="",
                timestamp=dt.datetime.now(dt.timezone.utc),
                inbox_event="config_required",
                technical_metadata={"cause": cause},
                decision_brief=_attention_brief(
                    loaded, feature_id, inbox_event="config_required"
                ),
            ),
            plan_dir=plan_dir,
        )
    # TRIPPED falls through — the breaker_tripped INBOX event from
    # _trip_breaker carries enough for the operator to act on.


def _quota_gate(agent: str) -> tuple[float | None, str]:
    """Returns (percent_of_primary_cap, decision_log_line). Raises QuotaExceeded
    if hard-blocked.

    F006b: V2 path uses circuit_breakers.collect_agent_coverage to share the
    cap lookup + calibration safety + unit check + missing-vendor-block
    classification with check_budget_ceiling and quota_admission. Soft-warn
    at SOFT_THRESHOLD_PERCENT (90%) of the operator-cap on the primary
    window (rolling_5h preferred per DEFAULT_WINDOW_PRIORITY). Surfaces
    'unmetered/config_required' when no usable window — NOT 'safe'. Legacy
    fallback (vendors{} missing) preserves the F020 percent_weekly behavior.

    Returns the percent value (0-100+) for callers that surface it in
    INBOX events; None when no usable signal exists. The decision log line
    is the human-readable summary; non-empty even when pct is None.
    """
    state = _read_quota_state()
    if state is None:
        return None, "[quota] no state file — skipping gate (run scripts/quota_check.py)"

    enforce = os.environ.get("JARVIS_QUOTA_ENFORCE", "soft").lower()
    vendors = state.get("vendors")
    if isinstance(vendors, dict) and vendors:
        return _quota_gate_v2(agent, vendors, enforce)

    # Legacy fallback (pre-F002 state shape) — keeps F020 behavior alive
    # for the cost-model + cost-guard skills until plan 2026-04-29-004
    # reactivation migrates them. Single deprecation log per process.
    circuit_breakers._warn_once(
        "quota_gate",
        "_global",
        "legacy_fallback",
        "[quota_gate] vendors{} missing in quota_state.json; using legacy "
        "models{}.percent_weekly path. Re-run scripts/quota_check.py.",
    )
    info = (state.get("models") or {}).get(agent) or {}
    pct = info.get("percent_weekly")
    if pct is None:
        return None, f"[quota] {agent}: unmetered or no cap ({info.get('plan', '?')})"
    line = f"[quota] {agent}: {pct}% of weekly cap ({info.get('plan', '?')}) [legacy]"
    if pct >= SOFT_THRESHOLD_PERCENT:
        if enforce == "hard":
            raise QuotaExceeded(
                f"{agent} weekly quota at {pct}% ≥ {SOFT_THRESHOLD_PERCENT}% — "
                f"set JARVIS_QUOTA_ENFORCE=soft (default) to log-and-proceed."
            )
        line += f"  ⚠ above {SOFT_THRESHOLD_PERCENT}% soft threshold (proceeding)"
    return pct, line


def _quota_gate_v2(agent: str, vendors: dict, enforce: str) -> tuple[float | None, str]:
    """V2 path for _quota_gate — shares collect_agent_coverage with the
    breaker. Translates the per-agent verdict into the (pct, line) shape
    the existing supervisor caller + signoff_writer expect."""
    try:
        caps = quota_caps_loader.load()
    except quota_caps_loader.QuotaCapsError as exc:
        circuit_breakers._warn_once(
            "quota_gate",
            agent,
            "caps_file_missing",
            f"[quota_gate] caps file unavailable: {exc}",
        )
        line = (
            f"[quota] {agent}: caps file missing → config_required "
            f"(run `python -m dontpanic_orchestrate quota-caps init`)"
        )
        if enforce == "hard":
            raise QuotaExceeded(line) from exc
        return None, line

    report = circuit_breakers.collect_agent_coverage(
        agent=agent,
        vendors=vendors,
        caps=caps,
    )

    if report.terminal is not None:
        # Calibration / unit_mismatch — block dispatch with explicit reason.
        # Stale advisory still emitted by check_budget_ceiling; not duplicated
        # here to avoid double-warn from the same dispatch.
        line = (
            f"[quota] {agent}: {report.terminal.outcome.value} on "
            f"{report.terminal.window} — {report.terminal.reason}"
        )
        if enforce == "hard":
            raise QuotaExceeded(line)
        return None, line

    if report.config_cause is not None:
        circuit_breakers._warn_once(
            "quota_gate",
            agent,
            report.config_cause,
            f"[quota_gate] {agent}: {report.config_cause}",
        )
        line = (
            f"[quota] {agent}: config_required ({report.config_cause}) — "
            f"add caps via `quota-caps init` or fix state"
        )
        if enforce == "hard":
            raise QuotaExceeded(line)
        return None, line

    if report.primary is None:
        # All windows NO_SIGNAL — agent dispatched but no logged usage.
        # Benign; surface as unmetered.
        return None, f"[quota] {agent}: no signal in any window (unmetered for now)"

    primary = report.primary
    pct = float(primary.pct_of_cap or 0.0) * 100.0
    line = (
        f"[quota] {agent}: {pct:.1f}% of {primary.window} cap "
        f"(tier={report.tier}, cap={primary.cap} {primary.cap_unit}, "
        f"confidence={primary.confidence})"
    )
    if pct >= SOFT_THRESHOLD_PERCENT:
        if enforce == "hard":
            raise QuotaExceeded(
                f"{agent} {primary.window} at {pct:.1f}% ≥ "
                f"{SOFT_THRESHOLD_PERCENT}% — set JARVIS_QUOTA_ENFORCE=soft "
                "(default) to log-and-proceed."
            )
        line += f"  ⚠ above {SOFT_THRESHOLD_PERCENT}% soft threshold (proceeding)"
    return pct, line


def _run_nested_orch_guards(plan_dir: Path, *, allow_depth: int | None) -> str | None:
    """Plan 2026-05-02-003 F001: run depth + cycle + repeated-finding guards
    when the plan has an `orchestration` block. Top-level plans are no-ops.
    Returns the audit-trail validation_performed marker string when
    `allow_depth` was used; None otherwise. Raises NestedOrchestrationError
    on any guard failure (caller surfaces as non-zero exit)."""
    nested_orchestration.check_depth(plan_dir, override_max=allow_depth)
    nested_orchestration.check_cycle(plan_dir)
    nested_orchestration.check_repeated_finding(plan_dir)
    if allow_depth is not None:
        return f"depth_override applied ({allow_depth})"
    return None


def _arm_parent_pre_resume_gate_for_child(loaded: plan_loader.LoadedPlan) -> None:
    """Plan 2026-05-02-003 F003: when a child plan dispatches, arm the parent's
    `pre_resume_after_child:{child_plan_id}` gate. Idempotent on the gate
    (re-dispatch doesn't double-arm). The INBOX nested_child_pending entry is
    only written on first arm. The events.jsonl `volley.spawn_child` trace is
    best-effort and may write on every dispatch (it's append-only history).

    Top-level plans (no orchestration) are no-ops. Missing parent dirs are
    logged as warnings but don't block child dispatch — F001's
    check_repeated_finding has stronger handling for genuine missing-parent
    scenarios.
    """
    orch = loaded.orchestration
    if orch is None:
        return
    plans_root = loaded.plan_dir.parent
    parent_plan_dir = plans_root / orch.parent_plan_id
    if not parent_plan_dir.is_dir():
        # F001's depth/cycle guards run before this and would raise on missing
        # parents that participate in the chain. Reaching here with a missing
        # dir means the parent_plan_id is something exotic (probably a test
        # fixture) — best-effort skip to avoid blocking dispatch.
        return

    newly_armed = gate_pause.add_pre_resume_after_child(
        parent_plan_dir,
        loaded.plan_id,
        plan_id=orch.parent_plan_id,
        reason=f"child {loaded.plan_id!r} dispatched",
    )
    if newly_armed:
        body = (
            f"Child plan {loaded.plan_id} is in flight (parent: "
            f"{orch.parent_plan_id}, spawn_reason: {orch.spawn_reason}). "
            "Parent re-entry is paused until operator runs:\n"
            f"  jarvis-orchestrate approve {orch.parent_plan_id} "
            f"pre_resume_after_child --child {loaded.plan_id}\n"
            f"After authoring evidence/fan-in-from-{loaded.plan_id}.md "
            "with `## Return Condition / status: satisfied`."
        )
        try:
            inbox.append_event(
                parent_plan_dir,
                event="nested_child_pending",
                plan_id=orch.parent_plan_id,
                body=body,
                child_plan_id=loaded.plan_id,
                spawn_reason=orch.spawn_reason,
            )
        except OSError:
            # INBOX is operator surface; failures should NOT block child
            # dispatch. Canonical state (gate-state.json) is already written.
            pass

    # Best-effort spawn event on parent's events.jsonl (D006 — never raises).
    finding_signature = (
        orch.spawn_finding.finding_signature if orch.spawn_finding is not None else None
    )
    nested_orchestration.record_event(
        parent_plan_dir,
        kind="volley.spawn_child",
        payload={
            "parent_plan_id": orch.parent_plan_id,
            "child_plan_id": loaded.plan_id,
            "spawn_reason": orch.spawn_reason,
            "finding_signature": finding_signature,
            "newly_armed": newly_armed,
        },
        plan_id=orch.parent_plan_id,
    )


def dispatch_single_agent(
    plan_dir: Path,
    feature_id: str,
    agent_role: str = "implementer",
    iteration: int = 0,
    target_env: str | None = None,
    target_project: str | None = None,
    mode: str | None = None,
    allow_depth: int | None = None,
) -> Path:
    """F004 path: dispatch one agent, produce + validate audit JSON.

    F023 Step 1 (EC9 + EC10): wraps the dispatch in an ExecutionEnvironment so
    the subprocess inherits an isolated CLI-state namespace, not ambient shell
    state. target_env / target_project remain optional until EC2 lands a plan-
    level Target contract; when unset, isolation still applies but no project
    label is injected into the subprocess env.

    F007 Slice 2: pre-dispatch admission applies here too.

    Plan 2026-05-03-001 F003: agent resolution mirrors :func:`dispatch_volley`.
    The agent_role ('implementer' / 'auditor') maps onto the per-plan
    ``agents_required`` indices first, then through the
    :func:`project_config.resolve_dispatch_defaults` chain (per-project
    ``.jarvis/jarvis.json`` > global ``~/.jarvis/config.json`` > hardcoded
    fallbacks 'claude' / 'codex'). The executor is then resolved through
    :data:`AGENT_REGISTRY` rather than hardcoded to Claude — this is the
    single-agent parity contract for F003.

    F014 (codex F009 #4/#5): the single-agent path is guarded by the SAME F009
    plan-drift reconciliation as ``dispatch_volley`` — an early fail-closed
    dispatch-start baseline, a blocking-drift human-ack gate, and a
    ``check_and_reconcile`` immediately before the (paid) executor dispatch so
    no paid single-agent call proceeds on stale plan context. Drift pauses raise
    :class:`PausedOnDrift`.
    """
    # F014 (codex F009 #5) — blocking-drift human-ack gate, mirroring the volley
    # path. A prior run that detected BLOCKING_POLICY scope/policy drift wrote a
    # durable ack marker; until an operator clears it via
    # `dontpanic approve <plan> drift:<class>`, refuse to record a fresh baseline
    # or make any paid call. Runs FIRST so a plain re-dispatch cannot launder an
    # un-acknowledged scope change.
    _ack_reason = plan_drift.blocking_ack_pause_reason(plan_dir)
    if _ack_reason is not None:
        print(f"[single-agent] PAUSED — blocking-drift ack required: {_ack_reason}")
        raise PausedOnDrift(_ack_reason)

    # F014 (codex F009 #4) — record the dispatch-start plan-run fingerprint at
    # the VERY TOP, before the sufficiency/completion backstops read plan
    # artifacts into memory, so every later drift check compares against true
    # untouched disk state (AC1 parity with the volley path). FAIL CLOSED: if a
    # baseline cannot be recorded we cannot detect drift at all, so refuse.
    try:
        plan_drift.record_baseline(plan_dir)
    except Exception as _fp_exc:  # noqa: BLE001 — re-raised as fail-closed
        raise PausedOnDrift(
            f"F009 plan-drift baseline could not be recorded for {plan_dir} "
            f"({_fp_exc}); failing closed — cannot guarantee drift detection"
        ) from _fp_exc

    # Goal Governance V1 F004: dispatch backstop. Refuse to act on any plan
    # whose declared goal_type requires a pre-impl sufficiency check unless
    # the findings are non-blocking or a valid (hash-bound) override exists.
    # No-op for plans without goal_type — full backward compat.
    sufficiency_gate.enforce_sufficiency_gate(plan_dir)
    # Goal Governance V1 F2/F003: post-impl backstop. Refuse dispatch against
    # plans hand-edited to status='completed' that lack the required F2 audit
    # evidence (completion_findings.json + audit envelope OR a valid input-bound
    # override). Mirror of the F1 backstop above but on the close boundary.
    # No-op for plans not in status='completed' or with non-gated goal_type.
    completion_gate.enforce_completion_gate(plan_dir)

    loaded = plan_loader.load(plan_dir)
    feature = loaded.feature(feature_id)

    # Plan 2026-05-08-003 F001 — fail-loud gate-state reconciliation. Runs
    # BEFORE _arm_parent_pre_resume_gate_for_child / admission reconcile / any
    # other gate-state write, so contradictions are surfaced on the persisted
    # artifact rather than silently normalized into a fresh write.
    _reconcile_gate_state_or_raise(
        loaded.plan_dir,
        plan_id=loaded.plan_id,
        declared_gates=list(loaded.plan.human_gates or []),
        feature_id=feature_id,
        loaded=loaded,
    )
    # Plan 2026-05-09-002 F002 — post-reconcile sync: when plan.status is
    # `active`, treat the lock D-entry + status flip as the authorizing
    # action and implicitly clear `pre_impl`. Reconcile stays pure.
    _sync_pre_impl_for_active_plan(loaded, feature_id=feature_id)

    # Plan 2026-05-02-003 F001: nested-orchestration guards (no-op for top-level plans).
    nested_marker = _run_nested_orch_guards(plan_dir, allow_depth=allow_depth)
    # Plan 2026-05-02-003 F003: when a child plan dispatches, arm the parent's
    # pre_resume_after_child gate (idempotent), write INBOX nested_child_pending
    # once on first arm, and record best-effort volley.spawn_child trace.
    _arm_parent_pre_resume_gate_for_child(loaded)

    # Plan 2026-05-03-001 F003: resolve the effective agent for this role.
    # Order: plan.agents_required[index] > per-project > global > hardcoded.
    # Index 0 = implementer, index 1 = auditor; non-canonical roles fall
    # straight through to the implementer slot for back-compat with callers
    # that pass an arbitrary string.
    agents_req = list(loaded.plan.agents_required or [])
    project_match = project_config.find_project_for_plan_dir(loaded.plan_dir)
    project_path_for_resolve = project_match[0] if project_match else None
    resolved_defaults = project_config.resolve_dispatch_defaults(project_path_for_resolve)
    if agent_role == "auditor":
        plan_pick = str(agents_req[1]).split(".")[-1] if len(agents_req) >= 2 else None
        agent_name = plan_pick or resolved_defaults["auditor"]
    else:
        plan_pick = str(agents_req[0]).split(".")[-1] if agents_req else None
        agent_name = plan_pick or resolved_defaults["implementer"]
    # F013 — the configured value may be a worker-profile id. Resolve
    # profile → harness (+ profile model override) BEFORE the quota gate and
    # executor resolution so quota, argv, and audits key on the real harness;
    # role/capability gates refuse clearly here instead of KeyError-ing in
    # AGENT_REGISTRY. Legacy harness names pass through (profile_id=None).
    worker = worker_profiles.resolve_worker(loaded.plan_dir, agent_role, agent_name)
    agent_name = worker.harness
    if project_match is not None:
        # Stamp last_used_at on the resolved registered project so
        # `jarvis projects list` reflects real recency. Best-effort —
        # missing-name (registry edited mid-flight) must not block dispatch.
        try:
            projects_registry.update_last_used(project_match[1])
        except projects_registry.ProjectsRegistryError:
            pass

    quota_pct, quota_line = _quota_gate(agent_name)
    print(quota_line)

    effective_env = target_env if target_env is not None else loaded.target_env
    effective_project = target_project if target_project is not None else loaded.target_project

    registry_repo, registry_repo_root, registry_log = _validate_environment_registry(
        loaded.plan_dir, effective_env, effective_project
    )
    print(registry_log)

    # F007 Slice 2 — pre-dispatch admission for single-agent path. F003:
    # admission evaluates against the resolved agent_name (not hardcoded
    # 'claude') so per-project / global overrides flow through to quota +
    # interactive-backoff signals correctly.
    plan_tier_str = (
        loaded.plan.tier.value
        if hasattr(loaded.plan.tier, "value")
        else str(loaded.plan.tier or "")
    )
    admission = quota_admission.evaluate(plan_tier_str, agents=[agent_name], mode_override=mode)
    print(
        f"[admission] class={admission.dispatch_class.value} "
        f"quota_over={admission.quota.over_threshold} "
        f"backoff_within={admission.interactive.within_backoff}"
    )
    reason_for: dict[str, str] = {}
    if admission.quota.over_threshold:
        reason_for[quota_admission.gate_name(quota_admission.DeferKind.QUOTA_THRESHOLD)] = (
            _format_admission_quota_reason(admission.quota)
        )
    if admission.interactive.within_backoff:
        reason_for[quota_admission.gate_name(quota_admission.DeferKind.INTERACTIVE_BACKOFF)] = (
            f"interactive backoff active for {agent_name} — "
            f"{admission.interactive.minutes_remaining:.1f} min remaining"
        )
    gate_pause.reconcile_defers(
        loaded.plan_dir,
        set(admission.active_gates),
        plan_id=loaded.plan_id,
        reason_for=reason_for,
    )
    declared_gates = list(loaded.plan.human_gates or [])
    gate_check = gate_pause.evaluate(loaded.plan_dir, declared_gates)
    if gate_check.paused:
        gate_pause.record_pause(
            loaded.plan_dir, plan_id=loaded.plan_id, pause_gates=gate_check.unmet
        )
        inbox.append_event(
            loaded.plan_dir,
            event="gate_hit",
            plan_id=loaded.plan_id,
            body=(
                f"Single-agent dispatch paused before run.\n\n"
                f"Awaiting: {gate_check.unmet}\n\n"
                f"Clear one (preferred): python -m dontpanic_orchestrate approve {loaded.plan_id} <gate>\n"
                f"Clear all (explicit):  python -m dontpanic_orchestrate resume {loaded.plan_id} --all"
            ),
            unmet_gates=",".join(gate_check.unmet),
            feature_id=feature_id,
        )
        # Plan 2026-05-24-004 F003 (audit i0 finding #3): the rendered
        # terminal sink fires from _emit_gate_paused_discord, replacing
        # the legacy `jarvis: gate pause` notify.notify that used to run
        # here.
        _emit_gate_paused_discord(
            loaded.plan_dir,
            loaded.plan_id,
            feature_id,
            pending_gates=list(gate_check.unmet),
            stage="general",
            target_env=effective_env,
            target_project=effective_project,
            loaded=loaded,
        )
        raise PausedOnGate(
            f"single-agent paused on gates {gate_check.unmet}; "
            f"clear via `jarvis approve {loaded.plan_id} <gate>` or "
            f"`jarvis resume {loaded.plan_id} --all`"
        )

    with (
        ExecutionEnvironment(
            plan_id=loaded.plan_id,
            target_env=effective_env,
            target_project=effective_project,
        ) as exec_env,
        _registered_supervisor(
            loaded.plan_id,
            effective_env,
            effective_project,
            str(exec_env.root),
            plan_dir=loaded.plan_dir,
        ),
    ):
        task = DispatchTask(
            plan_id=loaded.plan_id,
            plan_dir=loaded.plan_dir,
            feature_id=feature_id,
            feature_description=feature["description"],
            feature_acceptance=feature["acceptance"],
            feature_steps=feature.get("steps") or [],
            agent_role=agent_role,
            iteration=iteration,
            subprocess_env=exec_env.subprocess_env(),
            cwd=registry_repo_root,
            permission_policy=_derive_permission_policy(agent_role),
            # F013 profile model wins; else F012 role-level model override
            # (per-call > project > global); None keeps the harness CLI
            # default. i2: harness threads the actually-dispatched agent so a
            # model paired with a different vendor in a deeper config layer
            # is suppressed, not forwarded. F015: config model_aliases resolve
            # single-hop on the effective model; freeform strings pass through.
            model=model_catalog.resolve_alias(
                worker.model or resolve_model(loaded.plan_dir, agent_role, harness=agent_name),
                loaded.plan_dir,
            ),
        )

        # F003: resolve executor through AGENT_REGISTRY rather than
        # hardcoding ClaudeCLIExecutor; respects per-project / global
        # overrides flowing through ``agent_name``. KeyError on unknown
        # name surfaces as a clear runtime error rather than silent
        # claude-fallback.
        executor = _resolve_executor(agent_name)

        # F014 — fold any gate-state the supervisor ITSELF authored during this
        # dispatch's setup (e.g. _sync_pre_impl_for_active_plan / admission
        # reconcile clearing `pre_impl`) into the drift baseline before the
        # pre-paid check, mirroring the volley's advance_gate_baseline. Without
        # this, our own legitimate gate mutation would read as external gate
        # tampering and falsely pause; an external edit to any OTHER tracked file
        # (features / plan / decisions / objective) is still caught.
        try:
            plan_drift.advance_gate_baseline(loaded.plan_dir)
        except Exception as _adv_exc:  # noqa: BLE001 — advisory, never fatal
            print(f"[single-agent] gate-baseline advance skipped: {_adv_exc}")

        # F014 (codex F009 #4) — plan-drift check immediately BEFORE the paid
        # executor dispatch, using the SAME check_and_reconcile the volley path
        # runs. No paid single-agent call proceeds on stale plan context: if the
        # plan artifacts drifted between the dispatch-start baseline and now,
        # pause (raise PausedOnDrift). BLOCKING_POLICY drift records the durable
        # ack marker inside check_and_reconcile, so the pause survives re-
        # dispatch until acknowledged. FAIL CLOSED: a drift check that itself
        # raises (missing baseline, etc.) pauses rather than proceeding.
        try:
            _drift = plan_drift.check_and_reconcile(
                loaded.plan_dir,
                plan_id=loaded.plan_id,
                feature_id=feature_id,
                stage=plan_drift.STAGE_IMPLEMENTER,
            )
        except Exception as _drift_exc:  # noqa: BLE001 — fail CLOSED, do not proceed
            print(
                f"[single-agent] plan-drift check ERRORED at "
                f"{plan_drift.STAGE_IMPLEMENTER}; failing closed (pause): {_drift_exc}"
            )
            raise PausedOnDrift(
                f"plan-drift check failed at {plan_drift.STAGE_IMPLEMENTER} "
                f"({_drift_exc}); paused fail-closed — verify plan files on disk "
                "and redispatch"
            ) from _drift_exc
        if not _drift.proceed:
            cls = _drift.report.drift_class.value
            print(
                f"[single-agent] PAUSED on plan drift ({cls}) at "
                f"{plan_drift.STAGE_IMPLEMENTER}: "
                f"{', '.join(_drift.report.changed_files)}"
            )
            raise PausedOnDrift(_drift.pause_reason or _drift.report.headline(loaded.plan_id))

        result = executor.dispatch(task)

        audit = audit_writer.build_audit(
            loaded=loaded,
            result=result,
            feature_id=feature_id,
            validation_performed=[
                *([nested_marker] if nested_marker else []),
                f"read ~/.jarvis/quota_state.json ({agent_name} pct={quota_pct})",
                f"{agent_name} dispatch (binary={getattr(executor, 'binary', None) or '?'})",
                # F013 — evidence records the resolved dispatch identity.
                f"worker_profile={worker.profile_id or '(none)'} "
                f"harness={worker.harness} "
                f"model={task.model or '(harness default)'}",
                f"captured stdout {len(result.raw_response)} bytes",
                f"subprocess exit {0 if result.success else 'nonzero'}",
                f"execution_env_root={exec_env.root}",
                f"target_env={effective_env} target_project={effective_project or '(none)'}",
                "target_source=kwarg"
                if target_env is not None or target_project is not None
                else "target_source=plan",
                f"env_registry={registry_repo or '(none)'}",
                f"cwd={registry_repo_root or '(inherit)'}",
            ],
            target_context={
                "env": effective_env,
                "project": effective_project,
            },
        )
        _apply_target_accountability(
            audit,
            role=agent_role,
            plan_target_env=effective_env,
            plan_target_project=effective_project,
        )

        return audit_writer.write(audit, loaded.plan_dir, feature_id=feature_id)


# ─────────────────────────────  F005a: volley  ─────────────────────────────


@dataclass
class VolleyResult:
    final_status: str  # "signed_off" | "needs_changes" | "blocked" | "stopped_quota" | "stopped_cap" | "stopped_no_progress" | "paused_on_gate" | "paused_on_drift"
    rounds: int  # number of (implementer, auditor) pairs completed
    reason: str  # human-readable termination reason
    audit_paths: list[Path]  # all audit JSONs produced, in order


def _emit_volley_terminal(
    result: VolleyResult,
    *,
    loaded: plan_loader.LoadedPlan,
    feature_id: str,
    agents_in_panel: list[str],
    allow_incomplete_patch_reason: str | None = None,
    unrelated_dirty_state_note: str | None = None,
    cross_feature_ack_reason: str | None = None,
) -> VolleyResult:
    """F008 Items 1+3+4 — fire INBOX entry, terminal-notifier, signoff.json on
    any volley terminal state. Returns the input result unchanged so callers
    can `return _emit_volley_terminal(...)`.

    Plan 2026-05-01-004 F003: between notify and signoff_writer we run the
    patch-completeness gate. Block-tier findings without override raise
    ``PatchCompletenessError`` and skip signoff persistence. The pass /
    override path threads the resulting block into ``signoff.json`` via the
    new ``patch_completeness`` kwarg.
    """
    plan_dir = loaded.plan_dir
    inbox.append_event(
        plan_dir,
        event="volley_terminal",
        plan_id=loaded.plan_id,
        body=(
            f"final_status: {result.final_status}\n"
            f"rounds: {result.rounds}\n"
            f"audits: {[p.name for p in result.audit_paths]}\n"
            f"reason: {result.reason}"
        ),
        final_status=result.final_status,
        rounds=result.rounds,
        feature_id=feature_id,
    )
    # Plan 2026-05-24-004 F003 (audit i0 finding #2): the legacy
    # `notify.notify(title=f"jarvis: {result.final_status} ...")` call that
    # used to fire here is removed — the modern dispatch below fans through
    # ALL sinks (audit i0 finding #1) so the terminal-notifier sink now
    # produces the rendered "DontPanic [{plan_id}]" title via notify_event.
    _signoff_severity = (
        notify_event.SEVERITY_INFO
        if result.final_status == "signed_off"
        else notify_event.SEVERITY_ACTION_REQUIRED
    )
    try:
        _signoff_display_name = (
            loaded.feature(feature_id).get("description", "") if feature_id else ""
        )
    except KeyError:
        _signoff_display_name = ""
    notify_event.dispatch_event(
        notify_event.NotifyEvent(
            kind="signoff" if result.final_status == "signed_off" else "volley_terminal",
            severity=_signoff_severity,
            plan_id=loaded.plan_id,
            feature_id=feature_id,
            body=(f"**{result.final_status}** — {result.reason[:300]}\nrounds: {result.rounds}"),
            evidence_uri=str(plan_dir / "signoff.json"),
            timestamp=dt.datetime.now(dt.timezone.utc),
            inbox_event="volley_terminal",
            feature_display_name=_signoff_display_name or None,
            iteration_count=result.rounds,
            technical_metadata={
                "final_status": result.final_status,
                "rounds": result.rounds,
            },
            decision_brief=_attention_brief(
                loaded, feature_id, inbox_event="volley_terminal"
            ),
        ),
        plan_dir=plan_dir,
    )
    if result.audit_paths:
        iteration = max(0, result.rounds - 1)
        # Plan 2026-05-01-004 F003: pre-signoff patch-completeness gate.
        # Fires ONLY on the signed_off terminal (the supervisor would
        # otherwise flip passes:true). Other terminals (blocked, paused,
        # quota_exceeded) skip the gate — the volley already failed for
        # a different reason and the gate's PatchCompletenessError would
        # mask it. Persisted report still reflects state on disk via
        # the F001 sidecar.
        patch_completeness_block: dict | None = None
        if result.final_status == "signed_off":
            affected_paths = getattr(loaded.plan, "affected_paths", None) or []
            patch_completeness_block = patch_completeness_gate.enforce(
                plan_dir,
                plan_id=loaded.plan_id,
                iteration=iteration,
                role="implementer",
                audit_paths=list(result.audit_paths),
                affected_paths=list(affected_paths) if affected_paths else None,
                repo_root=plan_dir,
                allow_incomplete_patch_reason=allow_incomplete_patch_reason,
                unrelated_dirty_state_note=unrelated_dirty_state_note,
                dry_run=False,
            )
            # Plan 2026-06-01-001 F008 — cross-feature edit detection. Runs at
            # patch-completeness on the signed_off terminal, alongside the F003
            # patch gate. Additive + degrades-never-blocks on lint-infra failure
            # (cannot load features / git-state) — mirrors the F004 pre-lock
            # gate's D005 contract; only a genuine bleed
            # (CrossFeatureEditError) blocks. The feature->owned-paths map is
            # derived from the plan's own features; the diff surface is the F001
            # git-state sidecar.
            try:
                feature_dicts = [f.model_dump() for f in loaded.features.features]
                git_state_path = plan_dir / "evidence" / f"git-state-{iteration}-implementer.json"
                # The dispatch DIFF is the git-state sidecar only (staged ∪
                # unstaged_modified ∪ untracked). `affected_paths` is a plan
                # DECLARATION, not what the patch actually touched, so it is
                # deliberately NOT folded in here — including it would flag
                # foreign-owned paths the dispatch never touched (codex F008
                # audit i0, acceptance #2/#3 "diff touching").
                touched: set[str] = set()
                if git_state_path.is_file():
                    git_state = json.loads(git_state_path.read_text())
                    touched = cross_feature.touched_paths_from_git_state(git_state)
            except Exception as exc:  # noqa: BLE001 — degrade, never block on infra
                print(
                    f"[volley] WARN: cross-feature edit detection skipped "
                    f"({exc!r}); detector did not run"
                )
                feature_dicts = None
                touched = set()
            if feature_dicts is not None and touched:
                cross_feature.enforce(
                    plan_dir,
                    plan_id=loaded.plan_id,
                    current_feature_id=feature_id,
                    features=feature_dicts,
                    touched_paths=touched,
                    acknowledge_reason=cross_feature_ack_reason,
                )
        try:
            signoff_writer.write_signoff(
                plan_id=loaded.plan_id,
                tier=loaded.plan.tier.value
                if hasattr(loaded.plan.tier, "value")
                else str(loaded.plan.tier),
                iteration=iteration,
                agents_in_panel=agents_in_panel,
                audit_paths=list(result.audit_paths),
                plan_dir=plan_dir,
                volley_status=result.final_status,
                signoff_reason=result.reason,
                # Plan 2026-05-02-003 F002: pass charter/policy if present so
                # signoff-time compliance (allowed_paths + return-condition +
                # requires) runs before the envelope persists. Top-level
                # plans (None/None) skip the check entirely.
                child_charter=loaded.child_charter,
                commit_policy=loaded.commit_policy,
                # Plan 2026-05-02-003 F003: orchestration drives the
                # best-effort volley.return_to_parent trace on the child's
                # events.jsonl. None for top-level plans.
                orchestration=loaded.orchestration,
                patch_completeness=patch_completeness_block,
            )
        except (
            signoff_writer.SignoffWriteError,
            nested_orchestration.ChildCharterViolation,
        ) as exc:
            print(f"[volley] signoff_writer skipped: {exc}")
    return result


def dispatch_volley(
    plan_dir: Path,
    feature_id: str,
    implementer_agent: str | None = None,
    auditor_agent: str | None = None,
    max_iterations: int | None = None,
    target_env: str | None = None,
    target_project: str | None = None,
    mode: str | None = None,
    allow_depth: int | None = None,
    allow_incomplete_patch_reason: str | None = None,
    unrelated_dirty_state_note: str | None = None,
    cross_feature_ack_reason: str | None = None,
    direct_dispatch: bool = False,
) -> VolleyResult:
    """F005a: sequential build/audit volley.

    Round 0: implementer dispatches, auditor reviews.
    Round N+1: implementer addresses auditor findings, auditor re-reviews.
    Stops on: auditor signed_off, max_iterations hit, quota soft-block,
    no-progress (auditor status unchanged across 2 consecutive rounds).

    If implementer_agent / auditor_agent are None, falls back to plan's
    `agents_required` convention: index 0 = implementer, index 1 = auditor.

    F023 Step 1 (EC9 + EC10): the volley opens a single ExecutionEnvironment
    and shares it across all rounds; tool-state mutations stay sandboxed and
    cleanup runs on volley terminate. target_env / target_project remain
    optional until EC2 lands a plan-level Target contract.
    """
    # F009 (codex #2 i1): record the plan-run fingerprint at the VERY TOP of
    # dispatch — before the sufficiency/completion backstops below, which read
    # plan.md and (when gated) features/objective inputs into memory. AC1
    # requires the baseline to reflect true dispatch-start disk state captured
    # BEFORE any plan/feature load, so every later drift check compares against
    # untouched disk state. Capturing after the gates would let a pre-gate edit
    # be silently baked into the baseline. FAIL CLOSED (codex #3): if a baseline
    # cannot be recorded we cannot detect drift at all, so refuse to proceed
    # rather than run blind on stale context. The captured fingerprint is also
    # threaded into the active supervisor registration below (codex #2) so
    # active-run state records the EXACT dispatch-start disk fingerprint, not a
    # later recompute taken after plan load / gate preflight mutations.
    # F014 (codex F009 #5) — blocking-drift human-ack gate. If a PRIOR run
    # detected BLOCKING_POLICY scope/policy drift and the operator has not yet
    # acknowledged it, refuse to proceed: do NOT record a fresh baseline (which
    # would silently bless the new scope) and make NO paid call. The pause is
    # durable across re-dispatch until `dontpanic approve <plan> drift:<class>`
    # clears the marker. This runs BEFORE the baseline record below so a plain
    # re-dispatch cannot launder an un-acknowledged scope change.
    _ack_reason = plan_drift.blocking_ack_pause_reason(plan_dir)
    if _ack_reason is not None:
        print(f"[volley] PAUSED — blocking-drift ack required: {_ack_reason}")
        return VolleyResult("paused_on_drift", 0, _ack_reason, [])

    try:
        dispatch_start_fingerprint = plan_drift.compute_fingerprint(plan_dir)
        plan_drift.record_baseline(plan_dir, dispatch_start_fingerprint)
    except Exception as _fp_exc:  # noqa: BLE001 — re-raised as fail-closed
        raise RuntimeError(
            f"F009 plan-drift baseline could not be recorded for {plan_dir} "
            f"({_fp_exc}); failing closed — cannot guarantee drift detection"
        ) from _fp_exc

    # Goal Governance V1 F004: dispatch backstop. Refuse to act on any plan
    # whose declared goal_type requires a pre-impl sufficiency check unless
    # the findings are non-blocking or a valid (hash-bound) override exists.
    # No-op for plans without goal_type — full backward compat.
    sufficiency_gate.enforce_sufficiency_gate(plan_dir)
    # Goal Governance V1 F2/F003: post-impl backstop. Refuse dispatch against
    # plans hand-edited to status='completed' that lack the required F2 audit
    # evidence (completion_findings.json + audit envelope OR a valid input-bound
    # override). Mirror of the F1 backstop above but on the close boundary.
    # No-op for plans not in status='completed' or with non-gated goal_type.
    completion_gate.enforce_completion_gate(plan_dir)

    loaded = plan_loader.load(plan_dir)
    feature = loaded.feature(feature_id)

    # F009 — dispatch-boundary plan-drift check (BEFORE gate finalization).
    # The baseline was recorded above against true dispatch-start disk state;
    # recompute now so a plan artifact edited between baseline capture and the
    # plan load — including a mid-run hand-edit to audit/gate-state.json — is
    # surfaced as a graceful ``paused_on_drift`` here, ahead of the fail-loud
    # gate-state reconciliation below. Without this, an externally-mutated
    # gate-state would crash _reconcile_gate_state_or_raise with an
    # undeclared-gate error instead of pausing the volley cleanly before any
    # paid call. FAIL CLOSED (codex F009 #3): a drift check that itself errors
    # pauses rather than proceeding on possibly-stale context.
    try:
        _dispatch_drift = plan_drift.check_and_reconcile(
            loaded.plan_dir,
            plan_id=loaded.plan_id,
            feature_id=feature_id,
            stage=plan_drift.STAGE_DISPATCH,
        )
    except Exception as _drift_exc:  # noqa: BLE001 — fail CLOSED, do not proceed
        print(
            f"[volley] plan-drift check ERRORED at {plan_drift.STAGE_DISPATCH}; "
            f"failing closed (pause): {_drift_exc}"
        )
        return VolleyResult(
            "paused_on_drift",
            0,
            f"plan-drift check failed at {plan_drift.STAGE_DISPATCH} "
            f"({_drift_exc}); paused fail-closed — verify plan files on disk "
            "and redispatch",
            [],
        )
    if not _dispatch_drift.proceed:
        cls = _dispatch_drift.report.drift_class.value
        print(
            f"[volley] PAUSED on plan drift ({cls}) at "
            f"{plan_drift.STAGE_DISPATCH}: "
            f"{', '.join(_dispatch_drift.report.changed_files)}"
        )
        return VolleyResult(
            "paused_on_drift",
            0,
            _dispatch_drift.pause_reason or _dispatch_drift.report.headline(loaded.plan_id),
            [],
        )

    # Guard-hardening F001 (plan 2026-06-11-001) — the shared wrong-worktree
    # guard precondition, BEFORE the binding snapshot and any gate side
    # effect: strict registry load (corrupt never overridable), realpath
    # invoking-path identity, canonical binding_health. Raises GuardRefusal /
    # RegistryCorruptError fail-closed; unbound plans pass through.
    from dontpanic_orchestrate.worktree_guard import guard_plan_command as _wt_guard

    _wt_guard(loaded.plan_dir, "orchestrate dispatch")

    # Worktree Isolation v0 F002 — record the plan's worktree binding as
    # evidence on the build path. Strict registry load: a corrupt
    # worktrees.json refuses dispatch (never silently treated as no-binding);
    # unbound plans are untouched.
    from dontpanic_orchestrate.worktrees import capture_binding_snapshot as _wt_capture

    _wt_capture(loaded.plan_dir, "orchestrate dispatch")

    # Plan 2026-05-08-003 F001 — fail-loud gate-state reconciliation. Mirrors
    # the dispatch_single_agent placement so volley dispatch refuses to
    # proceed when persisted gate-state contradicts the plan declaration.
    _reconcile_gate_state_or_raise(
        loaded.plan_dir,
        plan_id=loaded.plan_id,
        declared_gates=list(loaded.plan.human_gates or []),
        feature_id=feature_id,
        loaded=loaded,
    )
    # Plan 2026-05-09-002 F002 — same post-reconcile sync as
    # dispatch_single_agent so a status=active plan dispatched via the
    # volley path also benefits from the implicit pre_impl clearance.
    _sync_pre_impl_for_active_plan(loaded, feature_id=feature_id)
    # The reconcile + pre_impl auto-clear above are the supervisor's OWN
    # legitimate gate-state mutations, made AFTER the dispatch-start baseline was
    # recorded. Fold them into the drift baseline now — mirroring the
    # dispatch_single_agent placement — so the first _drift_pause_or_none check
    # below does not see the supervisor's own gate write as external
    # context_refresh drift and spuriously pause before the first paid call.
    # Gate-only advance: a concurrent edit to features/decisions/plan/objective
    # in the same window is still caught (plan_drift.advance_gate_baseline).
    plan_drift.advance_gate_baseline(loaded.plan_dir)

    # Plan 2026-05-02-003 F001: nested-orchestration guards (no-op for top-level plans).
    nested_marker = _run_nested_orch_guards(plan_dir, allow_depth=allow_depth)
    # Plan 2026-05-02-003 F003: when a child plan dispatches, arm the parent's
    # pre_resume_after_child gate (idempotent), write INBOX nested_child_pending
    # once on first arm, and record best-effort volley.spawn_child trace.
    _arm_parent_pre_resume_gate_for_child(loaded)

    # Resolve role pairing — F005a uses agents_required[0/1] convention.
    # F003 fallback chain (when neither CLI arg nor agents_required declares):
    # per-project `<project>/.jarvis/jarvis.json` > global `~/.jarvis/config.json`
    # > hardcoded ('claude' / 'codex'). Plan's agents_required[] still wins
    # over per-project / global because it's an explicit per-plan declaration.
    agents_req = list(loaded.plan.agents_required or [])
    project_match = project_config.find_project_for_plan_dir(loaded.plan_dir)
    project_path = project_match[0] if project_match else None
    resolved = project_config.resolve_dispatch_defaults(project_path)
    plan_impl = str(agents_req[0]).split(".")[-1] if agents_req else None
    plan_aud = str(agents_req[1]).split(".")[-1] if len(agents_req) >= 2 else None
    impl_name = implementer_agent or plan_impl or resolved["implementer"]
    aud_name = auditor_agent or plan_aud or resolved["auditor"]
    # F013 i1 (codex audit i0 high finding): the configured value may be a
    # worker-profile id (or a D015 harness alias). Resolve BOTH roles through
    # resolve_worker BEFORE quota, admission, and executor resolution, so the
    # volley path keys everything on the real harness — parity with the
    # single-agent path. Gate refusals surface here as WorkerProfileError
    # with an operator-fixable message instead of a registry KeyError.
    impl_worker = worker_profiles.resolve_worker(loaded.plan_dir, "implementer", impl_name)
    aud_worker = worker_profiles.resolve_worker(loaded.plan_dir, "auditor", aud_name)
    impl_name = impl_worker.harness
    aud_name = aud_worker.harness
    if impl_worker.profile_id or aud_worker.profile_id:
        print(
            f"[volley] worker profiles: impl={impl_worker.profile_id or '(legacy)'}"
            f"→{impl_worker.harness} aud={aud_worker.profile_id or '(legacy)'}"
            f"→{aud_worker.harness}"
        )
    if project_match is not None:
        # Stamp last_used_at on the resolved registered project so
        # `jarvis projects list` reflects real recency. Best-effort —
        # missing-name (registry edited mid-flight) must not block dispatch.
        try:
            projects_registry.update_last_used(project_match[1])
        except projects_registry.ProjectsRegistryError:
            pass

    # Iteration cap from plan or argument
    cap = max_iterations
    if cap is None:
        loop_caps = loaded.plan.loop_caps
        cap = loop_caps.max_iterations if loop_caps and loop_caps.max_iterations is not None else 1

    audit_paths: list[Path] = []
    prior_aud_path: Path | None = None
    prior_aud_status: str | None = None
    # Plan 2026-05-30-002 F001 (D029 fix): retain the prior round's full auditor
    # envelope so check_no_progress can compare finding-signature SETS, not just
    # verdict strings — a shrinking blocking-finding set is progress and must not
    # trip no-progress even when both verdicts stay ``needs_changes``.
    prior_aud_envelope: dict[str, Any] | None = None

    effective_env = target_env if target_env is not None else loaded.target_env
    effective_project = target_project if target_project is not None else loaded.target_project
    target_source = "kwarg" if (target_env is not None or target_project is not None) else "plan"

    registry_repo, registry_repo_root, registry_log = _validate_environment_registry(
        loaded.plan_dir, effective_env, effective_project
    )
    print(registry_log)

    # F006 — global circuit breaker. Hard stop when ≥3 iteration_cap hits in
    # the last 24h across any plan. Evaluated BEFORE executor resolution so a
    # tripped breaker reliably halts dispatch even when AGENT_REGISTRY can't
    # produce the named agents (KeyError previously masked the breaker).
    global_state = circuit_breakers.evaluate_global()
    if global_state.tripped:
        reason = (
            f"global circuit breaker tripped: {global_state.hits_in_window} "
            f"iteration_cap hits in the last "
            f"{global_state.window_seconds // 3600}h "
            f"(threshold {global_state.threshold})"
        )
        _trip_breaker(
            loaded.plan_dir,
            loaded.plan_id,
            feature_id,
            circuit_breakers.BreakerKind.GLOBAL_CIRCUIT_BREAKER,
            reason,
            loaded=loaded,
        )
        return _emit_volley_terminal(
            VolleyResult(
                circuit_breakers.TERMINAL_STATUS[
                    circuit_breakers.BreakerKind.GLOBAL_CIRCUIT_BREAKER
                ],
                0,
                reason,
                audit_paths,
            ),
            loaded=loaded,
            feature_id=feature_id,
            agents_in_panel=[impl_name, aud_name],
        )

    # F007 Slice 2 — pre-dispatch admission reconcile. Evaluates runtime
    # dispatch class (p0 from plan.tier, interactive from --mode/env, else
    # autonomous) and computes which defer:* gates should be active given
    # current ~/.jarvis/quota_state.json + ~/.jarvis/interactive_state.json.
    # Reconciles active_defers in gate-state.json: auto-adds gates whose
    # condition is true, auto-removes gates whose condition is no longer
    # true. Must run BEFORE the gate_pause.evaluate() check so the
    # paused_on_gate path picks up the freshly reconciled defers.
    plan_tier_str = (
        loaded.plan.tier.value
        if hasattr(loaded.plan.tier, "value")
        else str(loaded.plan.tier or "")
    )
    admission = quota_admission.evaluate(
        plan_tier_str,
        agents=[impl_name, aud_name],
        mode_override=mode,
    )
    print(
        f"[admission] class={admission.dispatch_class.value} "
        f"quota_over={admission.quota.over_threshold} "
        f"backoff_within={admission.interactive.within_backoff}"
    )
    reason_for: dict[str, str] = {}
    if admission.quota.over_threshold:
        reason_for[quota_admission.gate_name(quota_admission.DeferKind.QUOTA_THRESHOLD)] = (
            _format_admission_quota_reason(admission.quota)
        )
    if admission.interactive.within_backoff:
        reason_for[quota_admission.gate_name(quota_admission.DeferKind.INTERACTIVE_BACKOFF)] = (
            f"interactive backoff active for claude — "
            f"{admission.interactive.minutes_remaining:.1f} min remaining"
        )
    added, removed = gate_pause.reconcile_defers(
        loaded.plan_dir,
        set(admission.active_gates),
        plan_id=loaded.plan_id,
        reason_for=reason_for,
    )
    for gate in added:
        body = f"Admission defer activated: {gate}\n\n"
        body += f"Reason: {reason_for.get(gate, '(see gate-state.json)')}\n"
        body += (
            f"\nClear one (preferred): python -m dontpanic_orchestrate approve {loaded.plan_id} {gate}\n"
            f"Clear all (explicit):  python -m dontpanic_orchestrate resume {loaded.plan_id} --all"
        )
        inbox.append_event(
            loaded.plan_dir,
            event="defer_tripped",
            plan_id=loaded.plan_id,
            body=body,
            defer_gate=gate,
            dispatch_class=admission.dispatch_class.value,
            feature_id=feature_id,
        )
        notify.notify(
            title=f"jarvis: defer {gate} — {loaded.plan_id}",
            message=reason_for.get(gate, gate)[:120],
            subtitle=feature_id,
        )
    for gate in removed:
        inbox.append_event(
            loaded.plan_dir,
            event="defer_cleared",
            plan_id=loaded.plan_id,
            body=f"Admission defer auto-cleared (condition no longer true): {gate}",
            defer_gate=gate,
            dispatch_class=admission.dispatch_class.value,
            feature_id=feature_id,
        )

    # F008 Item 2 + F006 + F007 — gate-pause check. Evaluated BEFORE executor
    # resolution so an active breaker:* / defer:* gate (or any unmet plan-
    # declared gate) reliably halts dispatch with paused_on_gate, even when
    # AGENT_REGISTRY can't produce the named agents. Approval-required
    # breakers must preempt resolution for the same reason the global
    # breaker does — otherwise an empty registry KeyErrors before pausing.
    #
    # Plan 2026-05-04-002 F001 — lifecycle-staged human gates (`pre_impl`,
    # `pre_merge`) are intentionally EXCLUDED from this upfront check; they
    # fire at their canonical lifecycle points below (pre_impl just before the
    # iter-0 implementer subprocess spawns; pre_merge immediately before
    # signoff_writer.write_signoff(passes=True) on the candidate-success
    # path). Other declared human gates (e.g. on_escalation, tier_promotion)
    # remain in the upfront bucket per D003.
    declared_gates = list(loaded.plan.human_gates or [])
    upfront_declared_gates = [
        g
        for g in declared_gates
        if (g.value if hasattr(g, "value") else str(g)) not in gate_pause.LIFECYCLE_STAGED_GATES
    ]
    gate_check = gate_pause.evaluate(loaded.plan_dir, upfront_declared_gates)
    if gate_check.paused:
        gate_pause.record_pause(
            loaded.plan_dir, plan_id=loaded.plan_id, pause_gates=gate_check.unmet
        )
        inbox.append_event(
            loaded.plan_dir,
            event="gate_hit",
            plan_id=loaded.plan_id,
            body=(
                f"Supervisor paused before iteration 0.\n\n"
                f"Declared gates: {gate_check.declared}\n"
                f"Cleared gates : {gate_check.cleared}\n"
                f"Awaiting      : {gate_check.unmet}\n\n"
                f"Clear one (preferred): python -m dontpanic_orchestrate approve {loaded.plan_id} <gate>\n"
                f"Clear all (explicit):  python -m dontpanic_orchestrate resume {loaded.plan_id} --all"
            ),
            unmet_gates=",".join(gate_check.unmet),
            target_env=effective_env,
            target_project=effective_project or "(none)",
            feature_id=feature_id,
        )
        # Plan 2026-05-24-004 F003 (audit i0 finding #3): legacy
        # `jarvis: gate pause` notify.notify removed; rendered terminal
        # sink fires via _emit_gate_paused_discord.
        _emit_gate_paused_discord(
            loaded.plan_dir,
            loaded.plan_id,
            feature_id,
            pending_gates=list(gate_check.unmet),
            stage="upfront",
            target_env=effective_env,
            target_project=effective_project,
            loaded=loaded,
        )
        print(f"[volley] PAUSED on gates: {gate_check.unmet}")
        return VolleyResult(
            "paused_on_gate",
            0,
            f"unmet gates: {gate_check.unmet}; "
            f"clear via `jarvis approve {loaded.plan_id} <gate>` or "
            f"`jarvis resume {loaded.plan_id} --all`",
            audit_paths,
        )

    impl_executor = _resolve_executor(impl_name)
    aud_executor = _resolve_executor(aud_name)

    print(f"[volley] feature={feature_id} impl={impl_name} aud={aud_name} cap={cap}")

    inbox.append_event(
        loaded.plan_dir,
        event="volley_start",
        plan_id=loaded.plan_id,
        body=f"impl={impl_name} aud={aud_name} cap={cap} target_env={effective_env} target_project={effective_project or '(none)'}",
        feature_id=feature_id,
    )

    with (
        ExecutionEnvironment(
            plan_id=loaded.plan_id,
            target_env=effective_env,
            target_project=effective_project,
        ) as exec_env,
        _registered_supervisor(
            loaded.plan_id,
            effective_env,
            effective_project,
            str(exec_env.root),
            plan_dir=loaded.plan_dir,
            dispatch_fingerprint=dispatch_start_fingerprint,
        ),
    ):
        print(
            f"[volley] execution_env_root={exec_env.root} "
            f"target_env={effective_env} "
            f"target_project={effective_project or '(none)'} "
            f"source={target_source} "
            f"cwd={registry_repo_root or '(inherit)'}"
        )
        round_subprocess_env = exec_env.subprocess_env()
        round_env_log = (
            f"execution_env_root={exec_env.root} "
            f"target_env={effective_env} "
            f"target_project={effective_project or '(none)'} "
            f"target_source={target_source} "
            f"env_registry={registry_repo or '(none)'} "
            f"cwd={registry_repo_root or '(inherit)'}"
        )

        # F006 — pre-loop setup for wall-clock + budget breakers
        loop_caps = loaded.plan.loop_caps
        wall_clock_hours = (
            loop_caps.wall_clock_hours
            if loop_caps and loop_caps.wall_clock_hours is not None
            else circuit_breakers.DEFAULT_WALL_CLOCK_HOURS
        )
        per_agent_caps: dict[str, float] = {}
        if loaded.plan.quota_caps:
            for agent_field in ("claude", "codex", "gemini"):
                v = getattr(loaded.plan.quota_caps, agent_field, None)
                if v is not None:
                    per_agent_caps[agent_field] = float(v)
        volley_start = dt.datetime.now(dt.timezone.utc)

        # Plan 2026-05-01-002 F003 — volley_start emit point. Fires after
        # admission, gate-pause, breaker, and executor resolution all clear,
        # immediately before the first iteration. Operators monitoring
        # Discord see "volley started" only when the volley actually begins
        # paying for agent dispatches.
        inbox.append_event(
            loaded.plan_dir,
            event="volley_start",
            plan_id=loaded.plan_id,
            body=(f"Volley begins: {impl_name} (impl) + {aud_name} (aud), max_iterations={cap}"),
            feature_id=feature_id,
            implementer=impl_name,
            auditor=aud_name,
        )
        try:
            _vs_display_name = loaded.feature(feature_id).get("description", "") or None
        except KeyError:
            _vs_display_name = None
        notify_event.dispatch_event(
            notify_event.NotifyEvent(
                kind="volley_start",
                severity=notify_event.SEVERITY_INFO,
                plan_id=loaded.plan_id,
                feature_id=feature_id,
                body=(f"**Volley start** — `{impl_name}` (impl) + `{aud_name}` (aud), cap={cap}"),
                action_link=None,
                timestamp=volley_start,
                inbox_event="volley_start",
                iteration_count=cap,
                feature_display_name=_vs_display_name,
                target_env=effective_env,
                target_project=effective_project,
                technical_metadata={
                    "implementer": impl_name,
                    "auditor": aud_name,
                },
            ),
        )

        def _trip_and_return(
            kind: circuit_breakers.BreakerKind, reason: str, rounds: int
        ) -> VolleyResult:
            _trip_breaker(
                loaded.plan_dir, loaded.plan_id, feature_id, kind, reason, loaded=loaded
            )
            return _emit_volley_terminal(
                VolleyResult(circuit_breakers.TERMINAL_STATUS[kind], rounds, reason, audit_paths),
                loaded=loaded,
                feature_id=feature_id,
                agents_in_panel=[impl_name, aud_name],
            )

        # F009 — the plan-run fingerprint baseline is recorded EARLIER, before
        # plan_loader.load() above (codex #2), so it reflects true dispatch-start
        # disk state and fails closed if unrecordable.

        def _drift_pause_or_none(stage: str, rounds: int) -> VolleyResult | None:
            """F009 — recompute the plan fingerprint, reconcile, and either
            proceed (None) or return a ``paused_on_drift`` VolleyResult. Additive
            decisions.jsonl drift is reconciled in-place (no pause, AC3). Refresh
            / blocking drift pauses BEFORE the next paid call so budget is
            protected (AC2/AC4/AC5). The single INBOX event + dashboard
            ActionChoice are emitted inside check_and_reconcile (AC6)."""
            try:
                decision = plan_drift.check_and_reconcile(
                    loaded.plan_dir,
                    plan_id=loaded.plan_id,
                    feature_id=feature_id,
                    stage=stage,
                )
            except Exception as _drift_exc:  # noqa: BLE001 — fail CLOSED, do not proceed
                # FAIL CLOSED (codex F009 #3): a drift check that errors must NOT
                # let the volley proceed on possibly-stale context. Pause for the
                # operator instead of silently continuing.
                print(
                    f"[volley] plan-drift check ERRORED at {stage}; failing closed "
                    f"(pause): {_drift_exc}"
                )
                return VolleyResult(
                    "paused_on_drift",
                    rounds,
                    f"plan-drift check failed at {stage} ({_drift_exc}); paused "
                    "fail-closed — verify plan files on disk and redispatch",
                    audit_paths,
                )
            if decision.proceed:
                if decision.report.drift_class is plan_drift.DriftClass.ADDITIVE_LEDGER:
                    print(
                        f"[volley] plan drift reconciled (additive ledger) at "
                        f"{stage}: {', '.join(decision.report.changed_files)}"
                    )
                return None
            cls = decision.report.drift_class.value
            print(
                f"[volley] PAUSED on plan drift ({cls}) at {stage}: "
                f"{', '.join(decision.report.changed_files)}"
            )
            try:
                notify_event.dispatch_event(
                    notify_event.NotifyEvent(
                        kind="plan_drift",
                        severity=notify_event.SEVERITY_ACTION_REQUIRED,
                        plan_id=loaded.plan_id,
                        feature_id=feature_id,
                        body=decision.pause_reason or decision.report.headline(loaded.plan_id),
                        timestamp=dt.datetime.now(dt.timezone.utc),
                        inbox_event="plan_drift_detected",
                        subtype=cls,
                        target_env=effective_env,
                        target_project=effective_project,
                        technical_metadata={
                            "drift_class": cls,
                            "changed_files": ",".join(decision.report.changed_files),
                            "stage": stage,
                            "budget_protected": str(decision.report.budget_protected),
                        },
                    ),
                    plan_dir=loaded.plan_dir,
                )
            except Exception as _ne_exc:  # noqa: BLE001 — notification is advisory
                print(f"[volley] plan-drift notify skipped: {_ne_exc}")
            return VolleyResult(
                "paused_on_drift",
                rounds,
                decision.pause_reason or decision.report.headline(loaded.plan_id),
                audit_paths,
            )

        # Plan 2026-05-12-001 v4 F003 (D025): top-level ValueError
        # backstop. The agent-output pipeline's shlex.split calls are now
        # wrapped in command_guard, but dependencies (Pydantic validators,
        # subprocess output parsers, anything we don't control) may still
        # raise ValueError on bad LLM output. Catching here guarantees the
        # volley reaches a clean terminal instead of orphaning the run.
        #
        # Plan 2026-05-12-001 v4 F004 (D025 root cause #2): pair the F003 catch
        # with a broader ``Exception`` backstop so non-ValueError surprises
        # (OSError on a missing schema, AttributeError on a malformed envelope,
        # KeyError on an absent dict key, etc.) still produce a terminal-state
        # checkpoint instead of orphaning the dispatch with an implementer
        # envelope on disk and no record of what came next. ``current_stage``
        # tracks which phase of the iter was active so the operator can
        # distinguish "implementer never started" from "auditor crashed after
        # implementer landed work" from "post-iter validation choked".
        iteration = -1
        current_stage = "iter_setup"
        try:
            for iteration in range(cap + 1):
                current_stage = "iter_setup"
                # F006 wall-clock + budget breakers — checked at the top of each
                # iteration so a long-running prior round has a chance to trip.
                wc_tripped, wc_reason = circuit_breakers.check_wall_clock(
                    volley_start, wall_clock_hours
                )
                if wc_tripped:
                    return _trip_and_return(
                        circuit_breakers.BreakerKind.WALL_CLOCK, wc_reason, iteration
                    )
                bd_result = circuit_breakers.check_budget_ceiling(audit_paths, per_agent_caps)
                if bd_result.tripped:
                    # F006b fix#1: emit kind-specific INBOX event BEFORE the
                    # generic breaker_tripped event so operators see a clear
                    # action signal (calibration_required / unit_mismatch /
                    # config_required) alongside the gate-pause notification.
                    # All kinds still funnel through breaker:budget_ceiling for
                    # the F008 pause-and-resume contract.
                    _emit_budget_kind_specific_event(
                        loaded.plan_dir,
                        loaded.plan_id,
                        bd_result,
                        feature_id,
                        loaded=loaded,
                    )
                    return _trip_and_return(
                        circuit_breakers.BreakerKind.BUDGET_CEILING,
                        bd_result.reason,
                        iteration,
                    )

                # Plan 2026-05-04-002 F001 — `pre_impl` staged check. Evaluated
                # AFTER plan load + capability checks (executor resolution above
                # already ran) and AFTER the upfront breaker/defer gate check, but
                # BEFORE the implementer subprocess spawns. Idempotency contract
                # (D006 audit-focus item 8): the stage is evaluated AT MOST ONCE
                # per plan-lifetime — once `pre_impl` is in `completed_stages`,
                # the supervisor skips evaluate_human_gates entirely, including
                # across resume boundaries. Only fires on iteration 0; iteration
                # 1+ within the same loop has by-construction already passed the
                # check.
                if iteration == 0 and not gate_pause.is_stage_completed(
                    loaded.plan_dir, "pre_impl"
                ):
                    # Plan 2026-05-08-003 F002 — narrow auto-clear carve-out
                    # for direct operator CLI dispatch in eligible dev/test
                    # contexts. On success, the helper records a normal
                    # gate_event + INBOX entry and the staged check below
                    # naturally observes pre_impl as cleared, falling through
                    # to the implementer round without a separate operator
                    # approve/resume.
                    auto_clear_reason = _maybe_auto_clear_pre_impl(
                        loaded=loaded,
                        declared_gates=declared_gates,
                        direct_dispatch=direct_dispatch,
                        effective_env=effective_env,
                        effective_project=effective_project,
                        feature_id=feature_id,
                    )
                    if auto_clear_reason is not None:
                        print(f"[volley] pre_impl auto-cleared: {auto_clear_reason}")
                        # F009 — the supervisor just mutated gate-state itself.
                        # Fold that legitimate clear into the plan-drift baseline
                        # so the upcoming implementer drift check does not see
                        # OUR own gate clear as external tampering and pause.
                        try:
                            plan_drift.advance_gate_baseline(loaded.plan_dir)
                        except Exception as _adv_exc:  # noqa: BLE001 — advisory
                            print(f"[volley] gate-baseline advance skipped: {_adv_exc}")
                    else:
                        pre_impl_info = gate_pause.evaluate_human_gates(
                            loaded.plan_dir, declared_gates, stage="pre_impl"
                        )
                        if pre_impl_info.paused:
                            gate_pause.record_pause(
                                loaded.plan_dir,
                                plan_id=loaded.plan_id,
                                pause_gates=pre_impl_info.pending,
                                stage="pre_impl",
                            )
                            inbox.append_event(
                                loaded.plan_dir,
                                event="gate_hit",
                                plan_id=loaded.plan_id,
                                body=(
                                    "Supervisor paused at lifecycle stage 'pre_impl' "
                                    "before iteration 0 implementer dispatch.\n\n"
                                    f"Awaiting: {pre_impl_info.pending}\n\n"
                                    f"Clear one (preferred): python -m dontpanic_orchestrate "
                                    f"approve {loaded.plan_id} <gate>\n"
                                    f"Clear all (explicit):  python -m dontpanic_orchestrate "
                                    f"resume {loaded.plan_id} --all"
                                ),
                                unmet_gates=",".join(pre_impl_info.pending),
                                stage="pre_impl",
                                target_env=effective_env,
                                target_project=effective_project or "(none)",
                                feature_id=feature_id,
                            )
                            # Plan 2026-05-24-004 F003 (audit i0 finding #3):
                            # legacy `jarvis: pre_impl gate pause` notify.notify
                            # removed; rendered terminal sink fires via
                            # _emit_gate_paused_discord.
                            _emit_gate_paused_discord(
                                loaded.plan_dir,
                                loaded.plan_id,
                                feature_id,
                                pending_gates=list(pre_impl_info.pending),
                                stage="pre_impl",
                                target_env=effective_env,
                                target_project=effective_project,
                                loaded=loaded,
                            )
                            print(f"[volley] PAUSED on pre_impl gates: {pre_impl_info.pending}")
                            return VolleyResult(
                                "paused_on_gate",
                                0,
                                f"unmet pre_impl gates: {pre_impl_info.pending}; "
                                f"clear via `jarvis approve {loaded.plan_id} <gate>` or "
                                f"`jarvis resume {loaded.plan_id} --all`",
                                audit_paths,
                            )

                # Implementer round
                current_stage = "implementer"
                # F009 — plan-drift check BEFORE the (paid) implementer call.
                _drift_pause = _drift_pause_or_none(plan_drift.STAGE_IMPLEMENTER, iteration)
                if _drift_pause is not None:
                    return _drift_pause
                try:
                    impl_pct, impl_quota_line = _quota_gate(impl_name)
                except QuotaExceeded as exc:
                    inbox.append_event(
                        loaded.plan_dir,
                        event="error",
                        plan_id=loaded.plan_id,
                        body=f"Quota hard-block (implementer): {exc}",
                        agent=impl_name,
                        feature_id=feature_id,
                    )
                    return _emit_volley_terminal(
                        VolleyResult("stopped_quota", iteration, str(exc), audit_paths),
                        loaded=loaded,
                        feature_id=feature_id,
                        agents_in_panel=[impl_name, aud_name],
                    )
                print(impl_quota_line)
                _maybe_emit_quota_warn(
                    loaded.plan_dir, loaded.plan_id, impl_name, impl_pct, feature_id
                )

                impl_audit_path = _run_round(
                    loaded=loaded,
                    executor=impl_executor,
                    agent_name=impl_name,
                    role="implementer",
                    iteration=iteration,
                    feature=feature,
                    prompt=prompts.implementer_prompt(
                        plan_id=loaded.plan_id,
                        plan_dir=loaded.plan_dir,
                        feature=feature,
                        iteration=iteration,
                        prior_auditor_path=prior_aud_path,
                        target_env=effective_env,
                        target_project=effective_project,
                    ),
                    extra_validation=[
                        *([nested_marker] if nested_marker else []),
                        f"quota gate impl={impl_pct}",
                        f"prior_auditor_path={prior_aud_path or '(none)'}",
                        round_env_log,
                    ],
                    subprocess_env=round_subprocess_env,
                    target_env=effective_env,
                    target_project=effective_project,
                    cwd=registry_repo_root,
                    worker=impl_worker,
                )
                audit_paths.append(impl_audit_path)

                # Plan 2026-05-04-003 F003 — surface timeout-with-work classification
                # in the transcript so operators see the signal without parsing
                # envelope JSON. The auditor still runs next; this round is just
                # excluded from no-progress / diminishing-returns counters.
                impl_envelope: dict[str, Any] | None
                try:
                    impl_envelope = json.loads(impl_audit_path.read_text())
                except (OSError, json.JSONDecodeError):
                    impl_envelope = None
                is_timeout_with_work = circuit_breakers._envelope_is_timeout_with_work(
                    impl_envelope
                )
                if is_timeout_with_work:
                    transcript.append_note(
                        loaded.plan_dir,
                        feature_id,
                        iteration,
                        (
                            "envelope is blocked-with-worktree-changes; not counted "
                            "toward no-progress / diminishing-returns; auditor still "
                            "inspecting landed work"
                        ),
                    )

                # Auditor round
                current_stage = "auditor"
                # F009 — plan-drift check BEFORE the (paid) auditor call.
                _drift_pause = _drift_pause_or_none(plan_drift.STAGE_AUDITOR, iteration)
                if _drift_pause is not None:
                    return _drift_pause
                try:
                    aud_pct, aud_quota_line = _quota_gate(aud_name)
                except QuotaExceeded as exc:
                    inbox.append_event(
                        loaded.plan_dir,
                        event="error",
                        plan_id=loaded.plan_id,
                        body=f"Quota hard-block (auditor): {exc}",
                        agent=aud_name,
                        feature_id=feature_id,
                    )
                    return _emit_volley_terminal(
                        VolleyResult("stopped_quota", iteration + 1, str(exc), audit_paths),
                        loaded=loaded,
                        feature_id=feature_id,
                        agents_in_panel=[impl_name, aud_name],
                    )
                print(aud_quota_line)
                _maybe_emit_quota_warn(
                    loaded.plan_dir, loaded.plan_id, aud_name, aud_pct, feature_id
                )

                # Supervisor-run regression (2026-08-15). The auditor's sandbox
                # is read-only by design (D012) so it can collect but never
                # execute tests — five consecutive audits on plan
                # 2026-08-13-001 reported exactly that, and nothing else in the
                # harness ran tests either. Run the plan-declared command here,
                # on the trusted host, and hand the auditor the output. Opt-in:
                # no `verification` block means nothing runs. Never fatal — a
                # broken runner must not eat the volley, and its status reaches
                # the auditor either way.
                verification_result = None
                _v_spec = verification_runner.spec_from_plan(loaded.plan)
                if _v_spec is not None:
                    try:
                        verification_result = verification_runner.run_verification(
                            loaded.plan_dir,
                            _v_spec,
                            iteration=iteration,
                            repo_root=registry_repo_root or loaded.plan_dir,
                            role="supervisor",
                            env=round_subprocess_env,
                        )
                        print(
                            f"[volley] verification: {verification_result.status} "
                            f"({_v_spec.command})"
                        )
                    except Exception as exc:  # noqa: BLE001 — advisory, never fatal
                        print(f"[volley] verification runner failed: {exc}")

                aud_audit_path = _run_round(
                    loaded=loaded,
                    executor=aud_executor,
                    agent_name=aud_name,
                    role="auditor",
                    iteration=iteration,
                    feature=feature,
                    prompt=prompts.auditor_prompt(
                        plan_id=loaded.plan_id,
                        plan_dir=loaded.plan_dir,
                        feature=feature,
                        iteration=iteration,
                        implementer_audit_path=impl_audit_path,
                        target_env=effective_env,
                        target_project=effective_project,
                        verification_block=verification_runner.render_context_block(
                            verification_result
                        ),
                    ),
                    extra_validation=[
                        *([nested_marker] if nested_marker else []),
                        f"quota gate aud={aud_pct}",
                        f"reviewing implementer audit at {impl_audit_path.name}",
                        round_env_log,
                    ],
                    subprocess_env=round_subprocess_env,
                    target_env=effective_env,
                    target_project=effective_project,
                    cwd=registry_repo_root,
                    worker=aud_worker,
                )
                audit_paths.append(aud_audit_path)

                current_stage = "post_iter"
                # Read auditor's verdict
                aud_data = json.loads(aud_audit_path.read_text())
                aud_status = aud_data.get("audit_status", "inconclusive")

                # Plan 2026-05-09-002 F001 — verdict-mismatch detection. The
                # auditor can write a canonical narrative-verdict line in the
                # summary that disagrees with the structured ``audit_status``
                # field (the SpinDine vibe-plan-001 F001-i1 regression: summary
                # said ``**Verdict: signed_off**`` while audit_status was
                # ``needs_changes``). Reading only the structured field
                # silently produces another paid iteration. Fail loud instead
                # — INBOX classification + raise — mirroring the gate_pause
                # GateStateReconciliationError discipline from plan 2026-05-08-
                # 003 F001.
                mismatch = auditor_taxonomy.detect_verdict_mismatch(
                    plan_id=loaded.plan_id,
                    feature_id=feature_id,
                    iteration=iteration,
                    audit_path=aud_audit_path,
                    audit_envelope=aud_data,
                )
                if mismatch is not None:
                    inbox.append_event(
                        loaded.plan_dir,
                        event="verdict_mismatch",
                        plan_id=loaded.plan_id,
                        body=auditor_taxonomy.format_verdict_mismatch_inbox_body(mismatch),
                        narrative_verdict=mismatch.narrative_verdict,
                        structured_status=mismatch.structured_status,
                        audit_path=str(mismatch.audit_path),
                        feature_id=feature_id,
                        iteration=str(iteration),
                    )
                    # Plan 2026-05-24-004 F003 (audit i0 finding #2): the
                    # legacy `notify.notify(title=f"jarvis: verdict mismatch ...")`
                    # call is removed — the dispatch below fans through ALL
                    # sinks (audit i0 finding #1) so the terminal sink now
                    # produces the rendered DontPanic-branded title via
                    # notify_event.
                    try:
                        _vm_display_name = loaded.feature(feature_id).get("description", "") or None
                    except KeyError:
                        _vm_display_name = None
                    notify_event.dispatch_event(
                        notify_event.NotifyEvent(
                            kind="verdict_mismatch",
                            severity=notify_event.SEVERITY_ACTION_REQUIRED,
                            plan_id=loaded.plan_id,
                            feature_id=feature_id,
                            body=(
                                f"**Verdict mismatch** — narrative=`{mismatch.narrative_verdict}` "
                                f"vs structured=`{mismatch.structured_status}` "
                                f"(iter {iteration})."
                            ),
                            evidence_uri=str(mismatch.audit_path),
                            timestamp=dt.datetime.now(dt.timezone.utc),
                            inbox_event="verdict_mismatch",
                            subtype=mismatch.structured_status,
                            iteration_count=iteration,
                            feature_display_name=_vm_display_name,
                            technical_metadata={
                                "narrative_verdict": mismatch.narrative_verdict,
                                "structured_status": mismatch.structured_status,
                                "audit_path": str(mismatch.audit_path),
                                "iteration": iteration,
                            },
                            decision_brief=_attention_brief(
                                loaded, feature_id, inbox_event="verdict_mismatch"
                            ),
                        ),
                        plan_dir=loaded.plan_dir,
                    )
                    raise mismatch

                print(f"[volley] iter={iteration} auditor verdict: {aud_status}")

                if aud_status == "signed_off":
                    # Plan 2026-05-04-002 F001 — `pre_merge` staged check fires
                    # ONLY on the candidate-success path (D005). It runs after
                    # the auditor's terminal `signed_off` verdict is observed
                    # (no blocking findings — `audit_status == 'signed_off'`
                    # already implies that) and immediately BEFORE
                    # `signoff_writer.write_signoff(passes=True)` would persist
                    # the success envelope (signoff_writer is invoked inside
                    # _emit_volley_terminal). When pre_merge is uncleared, the
                    # supervisor pauses with paused_on_gate WITHOUT writing a
                    # success signoff; failure-path terminals (handled in the
                    # branches below) NEVER consult pre_merge — failure evidence
                    # is unconditionally durable per D005.
                    # Idempotency: once `pre_merge` is in `completed_stages`,
                    # skip evaluate_human_gates entirely (audit-focus item 8).
                    pre_merge_info = (
                        None
                        if gate_pause.is_stage_completed(loaded.plan_dir, "pre_merge")
                        else gate_pause.evaluate_human_gates(
                            loaded.plan_dir, declared_gates, stage="pre_merge"
                        )
                    )
                    if pre_merge_info is not None and pre_merge_info.paused:
                        gate_pause.record_pause(
                            loaded.plan_dir,
                            plan_id=loaded.plan_id,
                            pause_gates=pre_merge_info.pending,
                            stage="pre_merge",
                        )
                        inbox.append_event(
                            loaded.plan_dir,
                            event="gate_hit",
                            plan_id=loaded.plan_id,
                            body=(
                                "Supervisor paused at lifecycle stage 'pre_merge' "
                                "after auditor signoff and before success-signoff write.\n\n"
                                f"Awaiting: {pre_merge_info.pending}\n\n"
                                f"Clear one (preferred): python -m dontpanic_orchestrate "
                                f"approve {loaded.plan_id} <gate>\n"
                                f"Clear all (explicit):  python -m dontpanic_orchestrate "
                                f"resume {loaded.plan_id} --all"
                            ),
                            unmet_gates=",".join(pre_merge_info.pending),
                            stage="pre_merge",
                            target_env=effective_env,
                            target_project=effective_project or "(none)",
                            feature_id=feature_id,
                        )
                        # Plan 2026-05-24-004 F003 (audit i0 finding #3):
                        # legacy `jarvis: pre_merge gate pause` notify.notify
                        # removed; rendered terminal sink fires via
                        # _emit_gate_paused_discord.
                        _emit_gate_paused_discord(
                            loaded.plan_dir,
                            loaded.plan_id,
                            feature_id,
                            pending_gates=list(pre_merge_info.pending),
                            stage="pre_merge",
                            target_env=effective_env,
                            target_project=effective_project,
                            loaded=loaded,
                        )
                        print(f"[volley] PAUSED on pre_merge gates: {pre_merge_info.pending}")
                        return VolleyResult(
                            "paused_on_gate",
                            iteration + 1,
                            f"unmet pre_merge gates: {pre_merge_info.pending}; "
                            f"clear via `jarvis approve {loaded.plan_id} <gate>` or "
                            f"`jarvis resume {loaded.plan_id} --all`",
                            audit_paths,
                        )

                    # F009 — final plan-drift check BEFORE finalizing signoff.
                    # If the plan changed during this volley, do NOT persist a
                    # success signoff against stale context; pause for refresh /
                    # human ack instead (AC2/AC4/AC5).
                    _drift_pause = _drift_pause_or_none(plan_drift.STAGE_SIGNOFF, iteration + 1)
                    if _drift_pause is not None:
                        return _drift_pause

                    transcript.append_terminal(
                        loaded.plan_dir,
                        feature_id,
                        aud_status,
                        iteration + 1,
                        reason="auditor signed off",
                    )
                    # Plan 2026-05-19-004 F004 — post-commit architecture regen
                    # hook. Fires only when commit_policy.mode == 'child_commit'
                    # (the implementer just landed a commit on this volley) AND
                    # the just-committed diff touches an architecture-relevant
                    # path. NEVER auto-commits the regenerated map; the operator
                    # sees architecture.json in `git status` and decides.
                    # Wrapped so any failure inside the hook (or in the hook
                    # module import) leaves the volley terminal unaffected.
                    try:
                        from dontpanic_orchestrate import (
                            architecture_regen_hook as _arch_regen_hook,
                        )

                        try:
                            _arch_display_name = (
                                loaded.feature(feature_id).get("description", "") or None
                            )
                        except KeyError:
                            _arch_display_name = None
                        _arch_regen_hook.maybe_regen_after_commit(
                            plan_dir=loaded.plan_dir,
                            plan_id=loaded.plan_id,
                            feature_id=feature_id,
                            commit_policy_mode=(
                                loaded.commit_policy.mode
                                if loaded.commit_policy is not None
                                else None
                            ),
                            repo_root=registry_repo_root,
                            feature_display_name=_arch_display_name,
                        )
                    except Exception as _arch_exc:  # noqa: BLE001 — never crash terminal
                        print(f"[volley] architecture regen hook skipped: {_arch_exc}")
                    return _emit_volley_terminal(
                        VolleyResult(
                            "signed_off", iteration + 1, "auditor signed off", audit_paths
                        ),
                        loaded=loaded,
                        feature_id=feature_id,
                        agents_in_panel=[impl_name, aud_name],
                        # Plan 2026-05-01-004 F003: thread operator overrides only on
                        # the signed_off path. Other terminals skip the gate per
                        # _emit_volley_terminal's final_status check.
                        allow_incomplete_patch_reason=allow_incomplete_patch_reason,
                        unrelated_dirty_state_note=unrelated_dirty_state_note,
                        # Plan 2026-06-01-001 F008: cross-feature-edit acknowledgement.
                        cross_feature_ack_reason=cross_feature_ack_reason,
                    )

                if aud_status == "blocked":
                    # Plan 2026-05-12-001 v4 F002 — reconcile verdict string
                    # against finding-class taxonomy before terminating. The
                    # auditor's structured ``audit_status`` is unreliable for
                    # advisory-class findings (D022: plan 010 F002 codex
                    # returned `blocked` because its sandbox couldn't run
                    # pytest, but the only finding was a test_coverage advisory
                    # — pre-fix the supervisor terminated `blocked after 1
                    # round` and the operator had to use F004 `close
                    # --operator-resolved --reason environmental_reproduction_failure`
                    # to clean up. Three reconciliation paths:
                    #   (a) empty findings → `blocked_no_findings` terminal +
                    #       INBOX event. NOT auto-promoted to environmental
                    #       because we have no evidence the blocker IS
                    #       environmental (could be network / format / refusal).
                    #   (b) all-advisory findings → promote to
                    #       `stopped_environmental_blocker` (F003 ENVIRONMENTAL_BLOCKER
                    #       semantics) + reconciliation INBOX event.
                    #   (c) any substantive finding (implementation_defect /
                    #       unknown) → preserve original `blocked` terminal.
                    blocked_envelope = (
                        json.loads(aud_audit_path.read_text())
                        if aud_audit_path.is_file()
                        else dict(aud_data)
                    )
                    raw_findings = blocked_envelope.get("findings")
                    findings_list = raw_findings if isinstance(raw_findings, list) else []
                    prior_envelopes = _load_prior_envelopes_for_classification(
                        audit_paths, exclude=aud_audit_path
                    )

                    if not findings_list:
                        no_findings_reason = (
                            f"verdict=blocked with empty findings on round "
                            f"{iteration + 1} — auditor unable to produce "
                            "findings; operator review required."
                        )
                        inbox.append_event(
                            loaded.plan_dir,
                            event="blocked_no_findings",
                            plan_id=loaded.plan_id,
                            body=(
                                "Auditor terminated with `audit_status=blocked` "
                                "but produced ZERO findings on this round.\n\n"
                                "This is opaque: we have no evidence that the "
                                "blocker is environmental (network, sandbox, "
                                "missing tool), substantive (real implementation "
                                "defect with unsaid context), or a tool/format "
                                "failure (auditor refused to serialize, network "
                                "outage on the auditor side). The supervisor "
                                "intentionally does NOT auto-promote this to "
                                "`stopped_environmental_blocker` because there "
                                "is no advisory signal to justify the override.\n\n"
                                f"Auditor envelope: {aud_audit_path}\n\n"
                                "Operator action: read the envelope, then decide "
                                "(a) re-dispatch, (b) `close --operator-resolved "
                                "--reason environmental_reproduction_failure` if "
                                "local verification confirms an env blocker, or "
                                "(c) close as a real defect."
                            ),
                            feature_id=feature_id,
                            iteration=str(iteration + 1),
                            audit_path=str(aud_audit_path),
                        )
                        transcript.append_terminal(
                            loaded.plan_dir,
                            feature_id,
                            "blocked_no_findings",
                            iteration + 1,
                            reason=no_findings_reason,
                        )
                        return _emit_volley_terminal(
                            VolleyResult(
                                "blocked_no_findings",
                                iteration + 1,
                                no_findings_reason,
                                audit_paths,
                            ),
                            loaded=loaded,
                            feature_id=feature_id,
                            agents_in_panel=[impl_name, aud_name],
                        )

                    saved_paths = auditor_taxonomy.collect_saved_evidence_paths(
                        [blocked_envelope, *prior_envelopes]
                    )
                    if auditor_taxonomy.is_advisory_only_findings_set(
                        findings_list,
                        feature_id=feature_id,
                        saved_evidence_paths=saved_paths,
                    ):
                        classification = auditor_taxonomy.classify_terminal(
                            feature_id=feature_id,
                            final_audit_envelope=blocked_envelope,
                            prior_envelopes=prior_envelopes,
                        )
                        try:
                            auditor_taxonomy.write_classification_sidecar(
                                plan_dir=loaded.plan_dir,
                                feature_id=feature_id,
                                iteration=iteration + 1,
                                classification=classification,
                            )
                        except OSError as exc:
                            print(f"[volley] taxonomy sidecar write skipped: {exc}")
                        reconcile_reason = (
                            f"verdict=blocked reconciled to environmental_blocker "
                            f"on round {iteration + 1}: every auditor finding "
                            f"classified as advisory "
                            f"(aggregate={classification.aggregate.value}); "
                            f"promoted to stopped_environmental_blocker per F003 "
                            f"ENVIRONMENTAL_BLOCKER semantics; recommended: "
                            f"{classification.recommended_action}"
                        )
                        inbox.append_event(
                            loaded.plan_dir,
                            event="verdict_blocked_reconciled",
                            plan_id=loaded.plan_id,
                            body=(
                                "Auditor returned `audit_status=blocked` but "
                                "every finding classified as advisory-only "
                                "via the v3 taxonomy. The supervisor refuses "
                                "to trust the verdict string alone when the "
                                "underlying findings are non-substantive.\n\n"
                                f"Aggregate class: {classification.aggregate.value}\n"
                                f"Blocking: {classification.blocking}\n"
                                f"Recommended action: {classification.recommended_action}\n\n"
                                "Terminal promoted from `blocked` to "
                                "`stopped_environmental_blocker` (matches "
                                "F003 ENVIRONMENTAL_BLOCKER semantics — "
                                "operator clears via the normal "
                                "`dontpanic approve <plan> "
                                "breaker:environmental_blocker` flow rather "
                                "than manual `close --operator-resolved`).\n\n"
                                + auditor_taxonomy.format_inbox_body(classification)
                            ),
                            aggregate=classification.aggregate.value,
                            blocking=str(classification.blocking).lower(),
                            feature_id=feature_id,
                            iteration=str(iteration + 1),
                            original_verdict="blocked",
                        )
                        # Plan 2026-05-24-004 F002 — Discord sink for the
                        # reconciliation. INBOX above is the truth-of-record.
                        try:
                            _vbr_display_name = (
                                loaded.feature(feature_id).get("description", "") or None
                            )
                        except KeyError:
                            _vbr_display_name = None
                        # Plan 2026-05-24-004 F003 (audit i0 finding #1):
                        # fan to ALL sinks + pass plan_dir so the rendered
                        # terminal + sidecar + INBOX-annotation paths fire
                        # for this LIVE-disposition event.
                        notify_event.dispatch_event(
                            notify_event.NotifyEvent(
                                kind="verdict_blocked_reconciled",
                                severity=notify_event.SEVERITY_ACTION_REQUIRED,
                                plan_id=loaded.plan_id,
                                feature_id=feature_id,
                                body=(
                                    "**Verdict reconciled** — auditor said "
                                    f"`blocked` but findings classify as "
                                    f"`{classification.aggregate.value}` "
                                    f"(blocking={classification.blocking}). "
                                    "Promoted to "
                                    "`stopped_environmental_blocker`."
                                ),
                                evidence_uri=str(loaded.plan_dir / "INBOX.md"),
                                timestamp=dt.datetime.now(dt.timezone.utc),
                                inbox_event="verdict_blocked_reconciled",
                                aggregate_class=classification.aggregate.value,
                                blocking=bool(classification.blocking),
                                iteration_count=iteration + 1,
                                feature_display_name=_vbr_display_name,
                                technical_metadata={
                                    "original_verdict": "blocked",
                                },
                                decision_brief=_attention_brief(
                                    loaded,
                                    feature_id,
                                    inbox_event="verdict_blocked_reconciled",
                                    pending_gates=[
                                        circuit_breakers.gate_name(
                                            circuit_breakers.BreakerKind.ENVIRONMENTAL_BLOCKER
                                        )
                                    ],
                                ),
                            ),
                            plan_dir=loaded.plan_dir,
                        )
                        transcript.append_terminal(
                            loaded.plan_dir,
                            feature_id,
                            circuit_breakers.TERMINAL_STATUS[
                                circuit_breakers.BreakerKind.ENVIRONMENTAL_BLOCKER
                            ],
                            iteration + 1,
                            reason=reconcile_reason,
                        )
                        return _trip_and_return(
                            circuit_breakers.BreakerKind.ENVIRONMENTAL_BLOCKER,
                            reconcile_reason,
                            iteration + 1,
                        )

                    transcript.append_terminal(
                        loaded.plan_dir,
                        feature_id,
                        aud_status,
                        iteration + 1,
                        reason="auditor blocked",
                    )
                    return _emit_volley_terminal(
                        VolleyResult("blocked", iteration + 1, "auditor blocked", audit_paths),
                        loaded=loaded,
                        feature_id=feature_id,
                        agents_in_panel=[impl_name, aud_name],
                    )

                # Plan 2026-05-09-002 F003 — environmental volley short-circuit.
                # Fires BEFORE the no_progress / diminishing_returns / convergence
                # checks: when the auditor verdict is `needs_changes` AND every
                # finding classifies as `environmental_reproduction_failure`
                # (advisory aggregate, blocking=False), the volley terminates
                # immediately with `stopped_environmental_blocker` so no second
                # implementer round dispatches against an env the agent provably
                # can't satisfy. Mixed (env + defect), defect-only, scope, and
                # unknown aggregates all fall through to the existing iterate
                # path. Malformed envelopes also fall through (classify_terminal
                # collapses to unknown+blocking, which doesn't match here).
                if aud_status == "needs_changes":
                    env_envelope = (
                        json.loads(aud_audit_path.read_text()) if aud_audit_path.is_file() else {}
                    )
                    env_classification = auditor_taxonomy.classify_terminal(
                        feature_id=feature_id,
                        final_audit_envelope=env_envelope,
                        prior_envelopes=_load_prior_envelopes_for_classification(
                            audit_paths, exclude=aud_audit_path
                        ),
                    )
                    if (
                        env_classification.aggregate
                        == auditor_taxonomy.FindingClass.ENVIRONMENTAL_REPRODUCTION_FAILURE
                        and not env_classification.blocking
                    ):
                        try:
                            auditor_taxonomy.write_classification_sidecar(
                                plan_dir=loaded.plan_dir,
                                feature_id=feature_id,
                                iteration=iteration + 1,
                                classification=env_classification,
                            )
                        except OSError as exc:
                            print(f"[volley] taxonomy sidecar write skipped: {exc}")
                        inbox.append_event(
                            loaded.plan_dir,
                            event="environmental_blocker_short_circuit",
                            plan_id=loaded.plan_id,
                            body=auditor_taxonomy.format_inbox_body(env_classification),
                            aggregate=env_classification.aggregate.value,
                            blocking=str(env_classification.blocking).lower(),
                            feature_id=feature_id,
                            iteration=str(iteration + 1),
                        )
                        # Plan 2026-05-24-004 F002 — Discord sink for the
                        # environmental short-circuit. INBOX above is the
                        # truth-of-record.
                        try:
                            _eb_display_name = (
                                loaded.feature(feature_id).get("description", "") or None
                            )
                        except KeyError:
                            _eb_display_name = None
                        # Plan 2026-05-24-004 F003 (audit i0 finding #1):
                        # fan to ALL sinks + pass plan_dir so the rendered
                        # terminal + sidecar + INBOX-annotation paths fire
                        # for this LIVE-disposition event.
                        notify_event.dispatch_event(
                            notify_event.NotifyEvent(
                                kind="environmental_blocker_short_circuit",
                                severity=notify_event.SEVERITY_ACTION_REQUIRED,
                                plan_id=loaded.plan_id,
                                feature_id=feature_id,
                                body=(
                                    "**Environmental blocker** — all round "
                                    f"{iteration + 1} findings classify as "
                                    "`environmental_reproduction_failure`. "
                                    "Volley terminating without another paid "
                                    "implementer round."
                                ),
                                evidence_uri=str(loaded.plan_dir / "INBOX.md"),
                                timestamp=dt.datetime.now(dt.timezone.utc),
                                inbox_event="environmental_blocker_short_circuit",
                                aggregate_class=env_classification.aggregate.value,
                                blocking=bool(env_classification.blocking),
                                iteration_count=iteration + 1,
                                feature_display_name=_eb_display_name,
                                decision_brief=_attention_brief(
                                    loaded,
                                    feature_id,
                                    inbox_event="environmental_blocker_short_circuit",
                                    pending_gates=[
                                        circuit_breakers.gate_name(
                                            circuit_breakers.BreakerKind.ENVIRONMENTAL_BLOCKER
                                        )
                                    ],
                                ),
                            ),
                            plan_dir=loaded.plan_dir,
                        )
                        env_reason = (
                            f"environmental blocker — round {iteration + 1} auditor "
                            f"findings classify as environmental_reproduction_failure "
                            f"(advisory, non-blocking); recommended: "
                            f"{env_classification.recommended_action}"
                        )
                        transcript.append_terminal(
                            loaded.plan_dir,
                            feature_id,
                            circuit_breakers.TERMINAL_STATUS[
                                circuit_breakers.BreakerKind.ENVIRONMENTAL_BLOCKER
                            ],
                            iteration + 1,
                            reason=env_reason,
                        )
                        return _trip_and_return(
                            circuit_breakers.BreakerKind.ENVIRONMENTAL_BLOCKER,
                            env_reason,
                            iteration + 1,
                        )

                # F006 — diminishing returns + convergence collapse heuristics.
                # Run before the no-progress check so they're surfaced explicitly
                # when their pattern fits, even if no_progress would also fire.
                dr_tripped, dr_reason = circuit_breakers.check_diminishing_returns(audit_paths)
                if dr_tripped:
                    transcript.append_terminal(
                        loaded.plan_dir,
                        feature_id,
                        circuit_breakers.TERMINAL_STATUS[
                            circuit_breakers.BreakerKind.DIMINISHING_RETURNS
                        ],
                        iteration + 1,
                        reason=dr_reason,
                    )
                    return _trip_and_return(
                        circuit_breakers.BreakerKind.DIMINISHING_RETURNS,
                        dr_reason,
                        iteration + 1,
                    )
                cc_tripped, cc_reason = circuit_breakers.check_convergence_collapse(audit_paths)
                if cc_tripped:
                    transcript.append_terminal(
                        loaded.plan_dir,
                        feature_id,
                        circuit_breakers.TERMINAL_STATUS[
                            circuit_breakers.BreakerKind.CONVERGENCE_COLLAPSE
                        ],
                        iteration + 1,
                        reason=cc_reason,
                    )
                    return _trip_and_return(
                        circuit_breakers.BreakerKind.CONVERGENCE_COLLAPSE,
                        cc_reason,
                        iteration + 1,
                    )

                # No-progress: auditor verdict identical to last round.
                # Plan 2026-05-04-003 F003: pass the implementer envelope so the
                # detector skips counting timeout-with-work iterations (D008 +
                # audit-focus item 1).
                # Plan 2026-05-30-002 F001 (D029 fix): pass the prior + current
                # auditor ENVELOPES (not bare verdict strings) so the breaker can
                # compare finding-signature SETS. A shrinking blocking-finding set
                # is progress and must not trip even when both verdicts stay
                # ``needs_changes``. Falls back to verdict-string semantics when an
                # envelope is missing or any finding lacks usable issue text.
                np_tripped, np_reason = circuit_breakers.check_no_progress(
                    prior_aud_envelope if prior_aud_envelope is not None else prior_aud_status,
                    aud_data,
                    current_impl_envelope=impl_envelope,
                )
                if np_tripped:
                    # Plan 2026-05-08-003 F003 — taxonomy classification on the
                    # stopped_no_progress terminal. Classification is advisory:
                    # implementation_defect / mixed / unknown stay blocking, and
                    # the supervisor never auto-signs-off based on a downgraded
                    # class (D006). Output goes to (a) a sidecar JSON the F2
                    # close gate can cite, (b) a classified INBOX event the
                    # operator reads, and (c) the terminal reason string so
                    # signoff_writer / volley_terminal events name the class.
                    aud_envelope = (
                        json.loads(aud_audit_path.read_text()) if aud_audit_path.is_file() else {}
                    )
                    prior_envelopes = _load_prior_envelopes_for_classification(
                        audit_paths, exclude=aud_audit_path
                    )
                    classification = auditor_taxonomy.classify_terminal(
                        feature_id=feature_id,
                        final_audit_envelope=aud_envelope,
                        prior_envelopes=prior_envelopes,
                    )
                    try:
                        auditor_taxonomy.write_classification_sidecar(
                            plan_dir=loaded.plan_dir,
                            feature_id=feature_id,
                            iteration=iteration + 1,
                            classification=classification,
                        )
                    except OSError as exc:
                        print(f"[volley] taxonomy sidecar write skipped: {exc}")
                    # Plan 2026-05-11-002 v3 F004 — surface the recommended
                    # close command inline so operators see the next step
                    # without hunting through docs. The classification's
                    # aggregate class is the natural default for the
                    # ``--reason`` flag; operator may override.
                    from dontpanic_orchestrate import closeout

                    close_hint = closeout.format_no_progress_close_hint(
                        plan_id=loaded.plan_id,
                        feature_id=feature_id,
                        recommended_class=classification.aggregate.value,
                    )
                    inbox.append_event(
                        loaded.plan_dir,
                        event="no_progress_classification",
                        plan_id=loaded.plan_id,
                        body=auditor_taxonomy.format_inbox_body(classification) + close_hint,
                        aggregate=classification.aggregate.value,
                        blocking=str(classification.blocking).lower(),
                        feature_id=feature_id,
                    )
                    # Plan 2026-05-24-004 F002 — Discord sink advisory. INBOX
                    # above is the truth-of-record.
                    try:
                        _np_display_name = loaded.feature(feature_id).get("description", "") or None
                    except KeyError:
                        _np_display_name = None
                    # Plan 2026-05-24-004 F003 (audit i0 finding #1): fan to
                    # ALL sinks + pass plan_dir so the rendered terminal +
                    # sidecar + INBOX-annotation paths fire for this
                    # LIVE-disposition event.
                    notify_event.dispatch_event(
                        notify_event.NotifyEvent(
                            kind="no_progress_classification",
                            severity=notify_event.SEVERITY_ACTION_REQUIRED,
                            plan_id=loaded.plan_id,
                            feature_id=feature_id,
                            body=(
                                "**No-progress taxonomy** — aggregate=`"
                                f"{classification.aggregate.value}` "
                                f"(blocking={classification.blocking}). "
                                f"Recommended: {classification.recommended_action}"
                            ),
                            evidence_uri=str(loaded.plan_dir / "INBOX.md"),
                            timestamp=dt.datetime.now(dt.timezone.utc),
                            inbox_event="no_progress_classification",
                            aggregate_class=classification.aggregate.value,
                            blocking=bool(classification.blocking),
                            feature_display_name=_np_display_name,
                            decision_brief=_attention_brief(
                                loaded,
                                feature_id,
                                inbox_event="no_progress_classification",
                            ),
                        ),
                        plan_dir=loaded.plan_dir,
                    )
                    np_reason = (
                        f"{np_reason}\n"
                        f"taxonomy=[{classification.aggregate.value}] "
                        f"blocking={classification.blocking}; "
                        f"recommended: {classification.recommended_action}"
                    )
                    transcript.append_terminal(
                        loaded.plan_dir,
                        feature_id,
                        "stopped_no_progress",
                        iteration + 1,
                        reason=np_reason,
                    )
                    return _trip_and_return(
                        circuit_breakers.BreakerKind.NO_PROGRESS,
                        np_reason,
                        iteration + 1,
                    )

                prior_aud_path = aud_audit_path
                # Plan 2026-05-04-003 F003 (audit-focus item 1): a skipped
                # timeout-with-work round must NOT establish the no-progress
                # baseline for the next round. Only countable rounds advance
                # `prior_aud_status`. `prior_aud_path` still updates because the
                # implementer prompt benefits from the freshest auditor context
                # (orthogonal to counter accumulation).
                if not is_timeout_with_work:
                    prior_aud_status = aud_status
                    # Plan 2026-05-30-002 F001 — advance the envelope baseline in
                    # lockstep with prior_aud_status so the next round's
                    # no-progress check compares finding-signature sets.
                    prior_aud_envelope = aud_data

        except ValueError as _backstop_exc:
            # F003 backstop catches ValueError for D025 root cause #1, but
            # ``target_context_prelude.TargetContextError`` is also a
            # ``ValueError`` subclass and signals an intentional F023 EC6
            # validation failure that MUST propagate to the caller (audit
            # rejected; no audit file should land). Re-raise it here so the
            # F003 net doesn't swallow legitimate platform validation.
            from dontpanic_orchestrate.target_context_prelude import TargetContextError

            if isinstance(_backstop_exc, TargetContextError):
                raise
            rounds_done = max(0, iteration + 1)
            backstop_reason = (
                "supervisor caught ValueError in iter loop "
                f"(iteration={iteration}): {_backstop_exc}. "
                "F003 backstop (D025 root cause #1) — likely a shlex.split "
                "failure on agent prose somewhere in the post-iter pipeline "
                "outside our wrapped call sites (dependency, subprocess parser, "
                "or Pydantic validator). Operator: inspect the last persisted "
                "audit envelope and use `dontpanic close --operator-resolved` "
                "(F2 F004 CLI) to close out manually if needed."
            )
            _write_backstop_checkpoint(
                plan_dir=loaded.plan_dir,
                feature_id=feature_id,
                iteration=max(0, iteration),
                exception=_backstop_exc,
                audit_paths=audit_paths,
                stage="iter_loop_backstop",
                plan_id=loaded.plan_id,
                recovery_notes=(
                    "F003 ValueError backstop fired (likely shlex parse "
                    "failure on agent prose outside our wrapped call sites). "
                    "Inspect audit_paths for any orphaned implementer "
                    "envelope; the operator-resolved close-out command above "
                    "clears breaker:no_progress and flips features.json."
                ),
            )
            transcript.append_terminal(
                loaded.plan_dir,
                feature_id,
                "blocked",
                rounds_done,
                reason=backstop_reason,
            )
            inbox.append_event(
                loaded.plan_dir,
                event="volley_crash_caught",
                plan_id=loaded.plan_id,
                body=backstop_reason,
                feature_id=feature_id,
            )
            return _emit_volley_terminal(
                VolleyResult("blocked", rounds_done, backstop_reason, audit_paths),
                loaded=loaded,
                feature_id=feature_id,
                agents_in_panel=[impl_name, aud_name],
            )
        except auditor_taxonomy.VerdictMismatchError:
            # Designed-propagate contract violation (plan 2026-05-09-002 F001).
            # The mismatch detector already wrote the canonical INBOX event +
            # operator notification BEFORE raising — the supervisor's job here
            # is to surface the failure to the caller, NOT to swallow it into
            # a generic 'blocked' terminal. Re-raise verbatim.
            raise
        except Exception as _f004_exc:
            # F004 (D025 root cause #2): broad-Exception backstop. The F003
            # ValueError clause above handles shlex/dependency parse failures;
            # this clause catches everything else the iter body might raise
            # (OSError on a torn schema, AttributeError on a malformed
            # envelope, KeyError, RuntimeError from a misbehaving executor,
            # etc.). Each of these previously orphaned the dispatch with no
            # terminal record; F004 guarantees a ``terminal-state-iter{N}.json``
            # checkpoint + clean ``blocked`` terminal so the operator-resolved
            # close-out CLI has a documented surface to recover from.
            rounds_done = max(0, iteration + 1)
            f004_reason = (
                "supervisor caught unhandled exception in iter loop "
                f"(iteration={iteration}, stage={current_stage}): "
                f"{type(_f004_exc).__name__}: {_f004_exc}. "
                "F004 backstop (D025 root cause #2). Operator: read "
                f"audit/terminal-state-iter{max(0, iteration)}.json for the "
                "stage + last-good envelope pointers, then use "
                "`dontpanic close --operator-resolved` (F2 F004 CLI) to close "
                "this feature without a re-dispatch when the failure is not a "
                "real implementation defect."
            )
            _write_iter_checkpoint(
                plan_dir=loaded.plan_dir,
                feature_id=feature_id,
                iteration=max(0, iteration),
                stage=current_stage,
                exception=_f004_exc,
                last_good_paths=audit_paths,
                plan_id=loaded.plan_id,
                recovery_notes=(
                    f"F004 broad-Exception backstop fired during stage="
                    f"{current_stage!r}. The iter loop raised "
                    f"{type(_f004_exc).__name__} after "
                    f"{len(audit_paths)} audit envelope(s) landed; the "
                    "last entry in ``audit_paths`` is the most recent "
                    "successful write (e.g. the orphaned implementer "
                    "envelope when stage==auditor). Use the recommended "
                    "close-out command to clear breaker:no_progress and "
                    "flip features.json."
                ),
            )
            transcript.append_terminal(
                loaded.plan_dir,
                feature_id,
                "blocked",
                rounds_done,
                reason=f004_reason,
            )
            inbox.append_event(
                loaded.plan_dir,
                event="volley_crash_caught",
                plan_id=loaded.plan_id,
                body=f004_reason,
                feature_id=feature_id,
                stage=current_stage,
                exception_class=type(_f004_exc).__name__,
            )
            return _emit_volley_terminal(
                VolleyResult("blocked", rounds_done, f004_reason, audit_paths),
                loaded=loaded,
                feature_id=feature_id,
                agents_in_panel=[impl_name, aud_name],
            )

        # F006 — iteration cap. Triggers the breaker (counted toward the global
        # circuit breaker's 24h window) and writes a synthetic gate so next-run
        # dispatch is paused until the operator approves or resumes.
        cap_reason = f"max_iterations={cap} reached without signoff"
        transcript.append_terminal(
            loaded.plan_dir,
            feature_id,
            "stopped_cap",
            cap + 1,
            reason=cap_reason,
        )
        return _trip_and_return(
            circuit_breakers.BreakerKind.ITERATION_CAP,
            cap_reason,
            cap + 1,
        )


def _format_recovery_command(*, plan_id: str | None, feature_id: str, reason_class: str) -> str:
    """Render the operator-facing close-out command. Uses the real plan_id
    when supervisor-internal callers can provide it; falls back to ``<id>`` for
    legacy callers (kept so F003 backstop tests stay green when they
    instantiate the helper without a plan_id)."""
    plan_token = plan_id or "<id>"
    return f"dontpanic close --operator-resolved {plan_token} {feature_id} --reason {reason_class}"


def _write_backstop_checkpoint(
    *,
    plan_dir: Path,
    feature_id: str,
    iteration: int,
    exception: BaseException,
    audit_paths: list[Path],
    stage: str | None = None,
    plan_id: str | None = None,
    recommended_command: str | None = None,
    recovery_notes: str | None = None,
) -> Path | None:
    """Plan 2026-05-12-001 v4 F003 (D025) + F004: write
    ``<plan_dir>/audit/terminal-state-iter{N}.json`` recording the failure
    surface so the operator can recover via the F2 F004 close CLI without
    grepping through (often tee-buffered, possibly empty) dispatch logs.

    F003 introduced this as a minimal stub for the iter-loop ValueError
    backstop. F004 extends it with:
      * ``stage``  — which phase failed (``implementer`` / ``auditor`` /
        ``post_iter`` / ``iter_loop_backstop``). Operator can read this to
        know whether the implementer envelope on disk reflects landed work
        (auditor/post_iter stage) or never started (implementer stage).
      * ``plan_id`` — folded into the recommended-recovery command so the
        operator can copy-paste the close-out string verbatim.
      * ``recommended_command`` — explicit override; when omitted, derived
        from ``plan_id`` + ``feature_id`` with reason class
        ``environmental_reproduction_failure``.
      * ``recovery_notes`` — free-text addendum (e.g. pointing at the
        orphaned implementer envelope or recording the shlex parse-error
        context).

    Best-effort: any OSError during write is swallowed because the caller's
    next step (transcript + INBOX + signoff) MUST still execute. The on-disk
    audit envelopes plus the INBOX trail remain the durable recovery surface
    even when this artifact write fails (read-only mount, disk full, etc.).
    """
    try:
        target = plan_dir / "audit" / f"terminal-state-iter{iteration}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        recovery_command = recommended_command or _format_recovery_command(
            plan_id=plan_id,
            feature_id=feature_id,
            reason_class="environmental_reproduction_failure",
        )
        payload: dict[str, Any] = {
            "schema": "terminal-state.v0",
            "feature_id": feature_id,
            "iteration": iteration,
            "stage": stage or "iter_loop_backstop",
            "exception_class": type(exception).__name__,
            "exception_message": str(exception)[:1000],
            "audit_paths": [str(p) for p in audit_paths],
            "last_good_audit_path": str(audit_paths[-1]) if audit_paths else None,
            "recommended_recovery": recovery_command,
            "recommended_command": recovery_command,
            "written_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        if plan_id is not None:
            payload["plan_id"] = plan_id
        if recovery_notes:
            payload["recovery_notes"] = recovery_notes
        target.write_text(json.dumps(payload, indent=2, sort_keys=True))
        return target
    except OSError:
        return None


def _write_iter_checkpoint(
    *,
    plan_dir: Path,
    feature_id: str,
    iteration: int,
    stage: str,
    exception: BaseException,
    last_good_paths: list[Path],
    plan_id: str | None = None,
    recovery_notes: str | None = None,
) -> Path | None:
    """Plan 2026-05-12-001 v4 F004 — named entry point for per-iter
    checkpointing. Thin wrapper over :func:`_write_backstop_checkpoint` with
    ``stage`` promoted to a required positional-style kwarg so call sites
    document which phase failed. ``last_good_paths`` is the audit-path slice
    captured before the exception (e.g. the implementer envelope when
    the auditor stage crashed)."""
    return _write_backstop_checkpoint(
        plan_dir=plan_dir,
        feature_id=feature_id,
        iteration=iteration,
        exception=exception,
        audit_paths=list(last_good_paths),
        stage=stage,
        plan_id=plan_id,
        recovery_notes=recovery_notes,
    )


def _apply_target_accountability(
    audit: dict[str, Any],
    role: str,
    plan_target_env: str,
    plan_target_project: str | None,
) -> None:
    """F023 EC3 + EC5: post-hoc accountability check on a built audit dict.

    Asymmetric reject:
      - implementer: any violation downgrades status to needs_changes (non-terminal)
      - auditor: any violation forces blocked (volley-terminal)

    Mutates `audit` in place. Adds findings (severity=high) describing each
    violation. Three classes of violation:
      1. Summary missing `Env: <plan_target_env>` declaration line.
      2. Summary missing `Project: <plan_target_project>` declaration line
         (skipped when plan_target_project is None — host-local plan).
      3. Any command in target_context.commands_run rejected by command_guard.
    """
    summary = audit.get("summary") or ""
    findings: list[dict[str, Any]] = list(audit.get("findings") or [])
    new_findings: list[dict[str, Any]] = []

    if not _summary_declares(summary, "Env", plan_target_env):
        env_present_with_other_value = _summary_declares_key(summary, "Env")
        new_findings.append(
            {
                "severity": "high",
                "category": "correctness",
                "issue": (
                    f"Mismatched `Env: {plan_target_env}` declaration in summary; "
                    "target accountability requires the declared env to match the plan target."
                    if env_present_with_other_value
                    else (
                        f"Missing `Env: {plan_target_env}` declaration in summary; "
                        "F023 EC5 requires {repo, env, project, command} declaration before side-effect calls."
                    )
                ),
                "evidence": "Parsed agent summary did not contain a matching `Env:` line.",
                "recommendation": f"Add a line `Env: {plan_target_env}` near the top of the summary.",
            }
        )

    if plan_target_project is not None and not _summary_declares(
        summary, "Project", plan_target_project
    ):
        project_present_with_other_value = _summary_declares_key(summary, "Project")
        new_findings.append(
            {
                "severity": "high",
                "category": "correctness",
                "issue": (
                    f"Mismatched `Project: {plan_target_project}` declaration in summary; "
                    "target accountability requires the declared project to match the plan target."
                    if project_present_with_other_value
                    else (
                        f"Missing `Project: {plan_target_project}` declaration in summary; "
                        "F023 EC5 requires the declared target_project to match plan target."
                    )
                ),
                "evidence": "Parsed agent summary did not contain a matching `Project:` line.",
                "recommendation": f"Add a line `Project: {plan_target_project}` near the top of the summary.",
            }
        )

    target_ctx = audit.get("target_context") or {}
    for cmd in target_ctx.get("commands_run") or []:
        # Plan 2026-05-12-001 v4 F003 (D025 root cause #1): defend against
        # untrusted agent prose. ``check_command`` no longer raises on
        # malformed shlex input — it surfaces the parser message via
        # ``GuardResult.parse_error`` so we can emit an advisory parsing
        # warning and skip the entry instead of killing the volley.
        try:
            guard = command_guard.check_command(cmd)
        except ValueError as exc:  # belt-and-braces: dependencies may still raise
            new_findings.append(
                {
                    "severity": "advisory",
                    "category": "parsing",
                    "issue": f"shlex parse failed: {exc}",
                    "evidence": f"Could not parse commands_run entry: {str(cmd)[:200]!r}",
                    "recommendation": (
                        "Quote/escape command strings consistently in summaries. "
                        "Supervisor skipped command_guard checks on this entry."
                    ),
                }
            )
            continue
        if guard.parse_error is not None:
            # ``guard.parse_error`` already includes the "shlex parse failed:"
            # prefix from command_guard._argv; re-prefixing here previously
            # produced double-prefixed advisories ("shlex parse failed: shlex
            # parse failed: ..."). Use it verbatim.
            new_findings.append(
                {
                    "severity": "advisory",
                    "category": "parsing",
                    "issue": guard.parse_error,
                    "evidence": f"Could not parse commands_run entry: {str(cmd)[:200]!r}",
                    "recommendation": (
                        "Quote/escape command strings consistently in summaries. "
                        "Supervisor skipped command_guard checks on this entry."
                    ),
                }
            )
            continue
        if not guard.allowed:
            new_findings.append(
                {
                    "severity": "high",
                    "category": "security",
                    "issue": f"Forbidden command in commands_run: {cmd!r}",
                    "evidence": f"command_guard: {guard.reason}",
                    "recommendation": (
                        "Use the explicit-flag equivalent (e.g. --project / --context) "
                        "rather than mutating shared CLI state."
                    ),
                }
            )

    if not new_findings:
        return

    prior_status = audit.get("audit_status")
    classified_findings = ec5_classifier.apply_ec5_classifier_to_findings(
        findings + new_findings,
        audit,
    )
    audit["findings"] = classified_findings

    has_blocking_finding = any(
        f.get("severity") in {"critical", "high"} for f in classified_findings
    )
    if role == "auditor":
        if has_blocking_finding:
            audit["audit_status"] = "blocked"
        elif prior_status == "blocked":
            # Preserve blocked statuses that predate target-accountability
            # enrichment, such as executor failures. EC5 downgrades should not
            # convert an already-blocked audit into signoff.
            audit["audit_status"] = "blocked"
        else:
            audit["audit_status"] = prior_status or "signed_off"
    elif has_blocking_finding and audit.get("audit_status") == "signed_off":
        audit["audit_status"] = "needs_changes"


_DECLARATION_RE_CACHE: dict[tuple[str, str], re.Pattern[str]] = {}
_DECLARATION_KEY_RE_CACHE: dict[str, re.Pattern[str]] = {}


def _summary_declares(summary: str, key: str, value: str) -> bool:
    """Check whether summary contains `<key>: <value>`.

    Accept both legacy plain declarations (`Env: dev`) and the canonical
    target-context prelude bullets (`- Env: dev`).
    """
    cache_key = (key, value)
    pattern = _DECLARATION_RE_CACHE.get(cache_key)
    if pattern is None:
        pattern = re.compile(
            rf"^[ \t]*(?:-\s*)?{re.escape(key)}\s*:\s*{re.escape(value)}\s*$",
            re.MULTILINE | re.IGNORECASE,
        )
        _DECLARATION_RE_CACHE[cache_key] = pattern
    return bool(pattern.search(summary))


def _summary_declares_key(summary: str, key: str) -> bool:
    """True when summary contains this declaration key with any value."""
    pattern = _DECLARATION_KEY_RE_CACHE.get(key)
    if pattern is None:
        pattern = re.compile(
            rf"^[ \t]*(?:-\s*)?{re.escape(key)}\s*:\s*\S+.*$",
            re.MULTILINE | re.IGNORECASE,
        )
        _DECLARATION_KEY_RE_CACHE[key] = pattern
    return bool(pattern.search(summary))


def _resolve_executor(agent_name: str) -> BaseExecutor:
    executor = get_executor(agent_name)
    if not executor.is_available():
        raise RuntimeError(f"agent {agent_name!r} not available — {executor.availability_hint()}")
    return executor


def _run_round(
    loaded: plan_loader.LoadedPlan,
    executor: BaseExecutor,
    agent_name: str,
    role: str,
    iteration: int,
    feature: dict[str, Any],
    prompt: str,
    extra_validation: list[str],
    subprocess_env: dict[str, str] | None = None,
    target_env: str | None = None,
    target_project: str | None = None,
    cwd: Path | None = None,
    worker: worker_profiles.ResolvedWorker | None = None,
) -> Path:
    # F013 — profile-level model wins over the F012 role-level override.
    # F015 — config model_aliases resolve single-hop on the effective model.
    effective_model = model_catalog.resolve_alias(
        (worker.model if worker is not None else None)
        or resolve_model(loaded.plan_dir, role, harness=agent_name),
        loaded.plan_dir,
    )
    task = DispatchTask(
        plan_id=loaded.plan_id,
        plan_dir=loaded.plan_dir,
        feature_id=feature["id"],
        feature_description=feature["description"],
        feature_acceptance=feature["acceptance"],
        feature_steps=feature.get("steps") or [],
        agent_role=role,
        iteration=iteration,
        extra_context={"prompt_override": prompt},
        subprocess_env=dict(subprocess_env) if subprocess_env else {},
        cwd=cwd,
        permission_policy=_derive_permission_policy(role),
        # F013 profile model > F012 role-level model override (per-call >
        # project > global); None keeps the harness CLI default. i2: harness
        # threads the actually-dispatched agent so a model paired with a
        # different vendor in a deeper config layer is suppressed.
        model=effective_model,
    )
    # Override the prompt builder by monkey-patching at task level —
    # cleaner: pass prompt directly. For now, executors build their own;
    # to use volley prompts we need executors to honor extra_context["prompt_override"].
    # See codex_cli/claude_cli for the override hook below.
    result = executor.dispatch(task)

    if not result.success:
        inbox.append_event(
            loaded.plan_dir,
            event="error",
            plan_id=loaded.plan_id,
            body=(
                f"Executor {agent_name} ({role}) iteration {iteration} reported "
                f"failure: {result.error or '(no error string)'}.\nVolley continues "
                "and the audit JSON below records the failure surface."
            ),
            agent=agent_name,
            role=role,
            iteration=iteration,
            feature_id=feature["id"],
        )

    target_context = None
    if target_env is not None:
        target_context = {"env": target_env, "project": target_project}

    audit = audit_writer.build_audit(
        loaded=loaded,
        result=result,
        feature_id=feature["id"],
        validation_performed=[
            f"{agent_name} {role} round (iteration {iteration})",
            # F013 — dispatch identity evidence: profile id, harness, model.
            f"worker: profile_id={worker.profile_id if worker else None} "
            f"harness={agent_name} model={effective_model or '(harness default)'}",
            *extra_validation,
            f"captured stdout {len(result.raw_response)} bytes",
        ],
        target_context=target_context,
    )
    if target_env is not None:
        _apply_target_accountability(
            audit,
            role=role,
            plan_target_env=target_env,
            plan_target_project=target_project,
        )
    audit_path = audit_writer.write(audit, loaded.plan_dir, feature_id=feature["id"])

    transcript.append_round(
        plan_dir=loaded.plan_dir,
        feature_id=feature["id"],
        iteration=iteration,
        agent=agent_name,
        role=role,
        audit_status=audit.get("audit_status", "?"),
        tokens_in=result.quota_consumed.get("tokens_in"),
        tokens_out=result.quota_consumed.get("tokens_out"),
        audit_path=audit_path,
    )
    return audit_path
