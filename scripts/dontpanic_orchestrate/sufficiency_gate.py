"""Goal Governance V1 F004 — plan-lock sufficiency gate.

Refuses plan lock (and acts as a backstop at first dispatch against hand-
edited locks) when a plan declares ``goal_type ∈ {parity, new_feature,
migration, incident}`` and F003's pre-impl sufficiency findings include
any blocking gap.

Public surface:

    enforce_sufficiency_gate(plan_dir) -> None
        Read-only gate. Raises SufficiencyGateError on refusal.
        Pure modulo file I/O — never mutates state, never writes evidence.

    lock_plan(plan_dir, override_reason=None, approved_by=None) -> Path
        Canonical lock command body. Refuses if status is not draft;
        runs the gate; writes override.json when override_reason is set;
        flips plan.md frontmatter status: draft → active. Returns the
        plan.md path.

    SufficiencyGateError, BLOCKING_SEVERITIES, OVERRIDE_ARTIFACT

**Blocking threshold (locked, F004 design):** ``medium``, ``high``,
and ``critical`` block lock. ``low`` and ``advisory`` pass.

**Override (locked, F004 design):** durable but **input-bound**. The
operator's ``--ignore-sufficiency-findings <reason>`` writes
``evidence/goal-governance/pre_impl/override.json`` with SHA-256 hashes
of the features contract, the objective contract, and the sufficiency findings.
Downstream gate calls honor the override only if all three hashes still
match the on-disk inputs. Runtime feature completion fields are excluded
from the features contract hash so normal ``passes:true`` close-out writes do
not invalidate a lock-time sufficiency override; material contract changes
still invalidate the override and the gate refuses again.

**Coverage:**

- (a) ``dontpanic plan lock`` CLI subcommand — direct caller (lock-time
  override channel).
- (b) Plan validator (``claude/shared/schemas/v1.0/validate.py``) —
  out of scope per D009; documented in F004 close-out.
- (c) MCP ``tool_dispatch`` — reaches the gate via supervisor wiring.
- (d) Direct status helpers in ``plan_loader.py`` — none exist.
- (e) Hand-edited ``plan.md`` lock — caught at first dispatch via
  supervisor wiring (D011 backstop).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dontpanic_orchestrate.nested_orchestration import goal_governance_evidence_path
from dontpanic_orchestrate.sufficiency_auditor import (
    PRE_IMPL_FINDINGS_ARTIFACT,
    SufficiencyFinding,
    _read_frontmatter,
)

# Import the v1.4.0 ObjectiveContract / Plan models (same candidate-list idiom as
# audit_writer / sufficiency_auditor — kept inline rather than centralized).
_SCHEMA_CANDIDATES = [
    Path(__file__).resolve().parents[2] / "claude" / "shared" / "schemas" / "v1.0",
    Path(__file__).resolve().parents[2] / ".claude" / "shared" / "schemas" / "v1.0",
    Path(__file__).resolve().parents[3] / "agent-conventions" / "schemas" / "v1.0",
]
for _candidate in _SCHEMA_CANDIDATES:
    if (_candidate / "models").is_dir():
        sys.path.insert(0, str(_candidate))
        break

from models.plan_model import GoalType  # noqa: E402

# ──────────────────────────────  constants  ──────────────────────────────


BLOCKING_SEVERITIES: frozenset[str] = frozenset({"medium", "high", "critical"})
"""Severities at which a sufficiency finding blocks plan lock. ``low`` and
``advisory`` pass through silently. Locked at F004 design — pre-impl
sufficiency exists to catch decomposition gaps before work starts; medium
gaps (missing journey, ambiguous completion test, parity matrix hole) are
exactly the kind of thing that should stop lock. Tune the auditor prompt
later if this becomes too noisy; never relax the threshold silently."""

_GATED_GOAL_TYPES: frozenset[GoalType] = frozenset(
    {
        GoalType.parity,
        GoalType.new_feature,
        GoalType.migration,
        GoalType.incident,
    }
)

OVERRIDE_ARTIFACT: str = "override.json"
"""Filename under ``evidence/goal-governance/pre_impl/`` when the operator
records an explicit override at lock time."""

_OVERRIDE_SCHEMA_VERSION: int = 1


class SufficiencyGateError(ValueError):
    """Raised when the gate refuses a lock or dispatch. Subclasses
    ValueError so callers that don't want to import this module can catch
    it as a plain ValueError."""


# ──────────────────────────────  pure helpers  ──────────────────────────────


def _should_gate_sufficiency(plan_data: dict[str, Any]) -> bool:
    """Return True iff the plan declares a goal_type that requires a
    pre-impl sufficiency check. Pure function on the parsed frontmatter
    dict — does NOT validate the full Plan schema (callers should do
    that separately)."""
    raw = plan_data.get("goal_type")
    if raw is None:
        return False
    try:
        gt = GoalType(raw)
    except ValueError:
        # Plan model validation flags this elsewhere; the gate is permissive
        # toward unknown goal_types so we don't double-report.
        return False
    return gt in _GATED_GOAL_TYPES


def _sha256_hex(path: Path) -> str:
    """SHA-256 hex digest of a file's bytes. Raises FileNotFoundError if
    the file is missing — callers translate that into a stale-override
    or audit-not-run message."""
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


_FEATURE_EXECUTION_STATE_KEYS: frozenset[str] = frozenset(
    {
        "passes",
        "evidence_refs",
        "verified_by",
        "verified_at",
    }
)


def _features_contract_hash(features_json: Path) -> str:
    """Hash only the plan contract carried by ``features.json``.

    ``features.json`` is both the pre-implementation contract and the
    implementation progress ledger. Lock-time sufficiency overrides must bind
    to the former, not the latter: closing F001 normally flips ``passes:true``
    and appends verification evidence, and that should not make the operator's
    pre-impl override stale for F002. Contract-bearing fields such as
    description, steps, acceptance, dependencies, and introduces remain
    hash-bound.

    Contract-stripping is a *refinement* for well-formed
    ``{"features": [...]}`` files, not a validation gate. A features.json that
    cannot be parsed, is not a JSON object, or lacks a top-level features list
    falls back to hashing the raw file bytes — the conservative pre-D002
    behavior. This keeps the sufficiency gate's refusal and override-staleness
    paths robust on shapeless/placeholder fixtures (which the gate must still be
    able to *evaluate findings* on) while binding the override to file content.
    """
    try:
        raw = json.loads(features_json.read_text())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        # Unreadable, non-UTF-8, or unparseable -> bind the override to the raw
        # file bytes (matches _sha256_hex, which reads bytes and never decodes).
        return _sha256_hex(features_json)
    if not isinstance(raw, dict) or not isinstance(raw.get("features"), list):
        return _sha256_hex(features_json)
    features = raw["features"]

    normalized: dict[str, Any] = {}
    for key, value in raw.items():
        if key == "features":
            normalized_features: list[Any] = []
            for feature in features:
                if isinstance(feature, dict):
                    normalized_features.append(
                        {
                            k: v
                            for k, v in feature.items()
                            if k not in _FEATURE_EXECUTION_STATE_KEYS
                        }
                    )
                else:
                    normalized_features.append(feature)
            normalized["features"] = normalized_features
        else:
            normalized[key] = value

    data = json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def _findings_path(plan_dir: Path) -> Path:
    return goal_governance_evidence_path(plan_dir, "pre_impl", PRE_IMPL_FINDINGS_ARTIFACT)


def _override_path(plan_dir: Path) -> Path:
    return goal_governance_evidence_path(plan_dir, "pre_impl", OVERRIDE_ARTIFACT)


def _resolve_objective_contract_path(plan_dir: Path, plan_data: dict[str, Any]) -> Path:
    """Translate ``links.objective_contract`` into an absolute path. Raises
    SufficiencyGateError on missing/empty links field."""
    links = plan_data.get("links") or {}
    if not isinstance(links, dict):
        raise SufficiencyGateError(
            f"{plan_dir}/plan.md: links must be a mapping, got {type(links).__name__}"
        )
    ref = links.get("objective_contract")
    if not ref:
        raise SufficiencyGateError(
            f"{plan_dir}/plan.md: links.objective_contract is missing — required by "
            f"goal_type={plan_data.get('goal_type')!r}"
        )
    return (plan_dir / ref).resolve()


def _compute_input_hashes(plan_dir: Path, plan_data: dict[str, Any]) -> dict[str, str]:
    """Compute SHA-256 hashes of the features contract + objective contract +
    sufficiency findings. All three must exist; missing files raise
    FileNotFoundError, which the caller translates into a domain message."""
    features_json = plan_dir / "features.json"
    if not features_json.is_file():
        raise SufficiencyGateError(f"{features_json}: features.json missing")
    contract_path = _resolve_objective_contract_path(plan_dir, plan_data)
    if not contract_path.is_file():
        raise SufficiencyGateError(f"{contract_path}: objective contract file missing")
    findings = _findings_path(plan_dir)
    if not findings.is_file():
        raise SufficiencyGateError(
            f"{findings}: pre-impl sufficiency findings missing — "
            "run F003 sufficiency auditor first (see "
            "scripts/dontpanic_orchestrate/sufficiency_auditor.py)"
        )
    return {
        "features_hash": _features_contract_hash(features_json),
        "objective_contract_hash": _sha256_hex(contract_path),
        "sufficiency_findings_hash": _sha256_hex(findings),
    }


def _load_findings(plan_dir: Path) -> list[SufficiencyFinding]:
    """Load the persisted sufficiency findings list. Validates each entry
    against ``SufficiencyFinding`` (severity normalization included), so a
    tampered findings file raises rather than silently passing."""
    findings_path = _findings_path(plan_dir)
    raw = json.loads(findings_path.read_text())
    items = raw.get("findings") if isinstance(raw, dict) else None
    if not isinstance(items, list):
        raise SufficiencyGateError(
            f"{findings_path}: malformed findings file — expected top-level "
            "mapping with 'findings' list"
        )
    return [SufficiencyFinding.model_validate(item) for item in items]


def _blocking_findings(findings: list[SufficiencyFinding]) -> list[SufficiencyFinding]:
    return [f for f in findings if f.severity in BLOCKING_SEVERITIES]


# ──────────────────────────────  override read/write  ──────────────────────────────


def _load_override(plan_dir: Path) -> dict[str, Any] | None:
    path = _override_path(plan_dir)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise SufficiencyGateError(f"{path}: malformed override file: {exc}") from exc
    if not isinstance(data, dict):
        raise SufficiencyGateError(f"{path}: override file must be a JSON object")
    return data


def _override_validity_check(
    override: dict[str, Any], current_hashes: dict[str, str]
) -> tuple[bool, list[str]]:
    """Compare stored override hashes against current input hashes. Returns
    ``(is_valid, mismatched_keys)``. ``is_valid`` is True iff every required
    hash matches — single-key drift invalidates the override."""
    mismatches: list[str] = []
    for key in ("features_hash", "objective_contract_hash", "sufficiency_findings_hash"):
        if override.get(key) != current_hashes.get(key):
            mismatches.append(key)
    return len(mismatches) == 0, mismatches


def _write_override(
    plan_dir: Path,
    *,
    reason: str,
    approved_by: str,
    plan_id: str,
    goal_type: str,
    objective_contract_path: str,
    hashes: dict[str, str],
) -> Path:
    """Persist override.json. Caller is responsible for having already
    validated that an override is the right action (i.e. that gate found
    blocking findings)."""
    path = _override_path(plan_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": _OVERRIDE_SCHEMA_VERSION,
        "reason": reason,
        "approved_by": approved_by,
        "approved_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "plan_id": plan_id,
        "goal_type": goal_type,
        "objective_contract_path": objective_contract_path,
        **hashes,
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    return path


# ──────────────────────────────  the gate  ──────────────────────────────


def enforce_sufficiency_gate(plan_dir: Path) -> None:
    """Read-only sufficiency gate.

    Behavior:

    1. If the plan declares no ``goal_type`` (or one not in the gated set),
       returns silently — backward-compatible no-op.
    2. Otherwise, computes current input hashes (features + contract +
       findings file).
    3. If a valid (hashes-match) ``override.json`` exists, returns silently.
    4. If a stale (hashes-mismatch) override exists, raises with the list
       of inputs that drifted.
    5. Otherwise, loads sufficiency findings; if any have severity in
       :data:`BLOCKING_SEVERITIES`, raises with a structured message
       pointing at the findings file.

    Pure modulo file I/O — never mutates state, never writes evidence.
    """
    plan_dir = Path(plan_dir).resolve()
    plan_md = plan_dir / "plan.md"
    plan_data = _read_frontmatter(plan_md)

    if not _should_gate_sufficiency(plan_data):
        return  # not opted in; gate is silent

    current_hashes = _compute_input_hashes(plan_dir, plan_data)
    override = _load_override(plan_dir)
    if override is not None:
        is_valid, mismatched = _override_validity_check(override, current_hashes)
        if is_valid:
            return  # operator-recorded override; durable, hash-bound
        raise SufficiencyGateError(
            f"{_override_path(plan_dir)}: override is stale — "
            f"input(s) changed since approval: {', '.join(mismatched)}. "
            "Re-run the sufficiency auditor and reissue the override "
            "(or remove override.json to force the standard gate path)."
        )

    findings = _load_findings(plan_dir)
    blocking = _blocking_findings(findings)
    if blocking:
        # Convergence policy (plan 2026-06-09-002 F002/F005). Consults the
        # rounds ledger + recorded dispositions — performs ZERO auditor
        # invocations. When every blocking finding of the latest round is
        # covered by a valid no-audit disposition, the gate passes (the
        # no_auditor_resolution path); otherwise the refusal names the
        # policy branch that fired.
        from dontpanic_orchestrate.sufficiency_convergence import (
            CONFIRMATION_PLACEHOLDER,
            VERDICT_DISPOSITION_REQUIRED,
            VERDICT_PROCEED,
            WAIVED_MATRIX_PIN_HIGH,
            gate_decision,
        )

        decision = gate_decision(plan_dir)
        if decision.verdict == VERDICT_PROCEED:
            return  # resolved by dispositions — no paid call, no new round

        bullet_lines = [
            f"  - {f.journey_id} / {f.gap_class} ({f.severity}): {f.description}" for f in blocking
        ]
        if decision.verdict == VERDICT_DISPOSITION_REQUIRED:
            guidance = (
                "to resolve WITHOUT another paid audit: dontpanic plan disposition "
                "<plan-dir> --finding <id> --kind "
                "deferred_to_impl|waived_with_reason|split_to_followup_plan"
            )
        else:
            guidance = (
                "to override: dontpanic plan lock <plan-dir> "
                '--ignore-sufficiency-findings "<reason>"'
            )
        # v1.1 — name each streak-unlocked high matrix_pin with a runnable
        # disposition command. The reason placeholder MUST be replaced: the
        # literal text is rejected by record_disposition's validation.
        unlocked_lines = [
            (
                f"streak-unlocked high matrix_pin {fid} — resolvable without a "
                f"new paid audit:\n  dontpanic plan disposition {shlex.quote(str(plan_dir))} "
                f"--finding {fid} --kind {WAIVED_MATRIX_PIN_HIGH} "
                f'--reason "{CONFIRMATION_PLACEHOLDER}"'
            )
            for fid in decision.streak_unlocked_ids
        ]
        raise SufficiencyGateError(
            f"plan lock refused — {len(blocking)} blocking sufficiency finding(s) "
            f"at severity ≥ medium:\n"
            + "\n".join(bullet_lines)
            + f"\nconvergence policy branch: {decision.branch} — {decision.detail}\n"
            + ("\n".join(unlocked_lines) + "\n" if unlocked_lines else "")
            + f"findings file: {_findings_path(plan_dir)}\n"
            + guidance
        )


# ──────────────────────────────  plan.md mutation  ──────────────────────────────


_STATUS_DRAFT_RE = re.compile(r"^(status:\s*)draft\s*$", re.MULTILINE)


def _mutate_plan_status_to_active(plan_md: Path) -> None:
    """Flip ``status: draft`` to ``status: active`` inside plan.md
    frontmatter. Preserves all other formatting (comments, ordering,
    blank lines) — single-line regex replace within the YAML block.
    Refuses if the frontmatter is malformed or if the line is absent."""
    text = plan_md.read_text()
    if not text.startswith("---"):
        raise SufficiencyGateError(f"{plan_md}: missing frontmatter delimiter")
    parts = text.split("---", 2)
    if len(parts) < 3:
        raise SufficiencyGateError(f"{plan_md}: malformed frontmatter")
    fm_text = parts[1]
    new_fm, n = _STATUS_DRAFT_RE.subn(r"\1active", fm_text, count=1)
    if n == 0:
        raise SufficiencyGateError(
            f"{plan_md}: no `status: draft` line in frontmatter — refusing to flip"
        )
    plan_md.write_text("---" + new_fm + "---" + parts[2])


# ──────────────────────────────  lock entry point  ──────────────────────────────


def _resolved_approver(approved_by: str | None) -> str:
    if approved_by:
        return approved_by
    return os.environ.get("DONTPANIC_OPERATOR") or os.environ.get("USER") or "operator"


def _capture_worktree_snapshot(plan_dir: Path, command: str) -> None:
    """Worktree Isolation v0 F002 — record the plan's binding as gate
    evidence before side effects. STRICT registry load: a corrupt
    worktrees.json refuses the command (never treated as no-binding).
    Unbound plans: no-op."""
    from dontpanic_orchestrate.worktrees import capture_binding_snapshot

    capture_binding_snapshot(plan_dir, command)


def lock_plan(
    plan_dir: Path,
    *,
    override_reason: str | None = None,
    approved_by: str | None = None,
) -> Path:
    """Canonical lock-command body.

    Refuses if the plan is not in ``status: draft`` (idempotency: re-locking
    an active plan is a no-op-with-warning, not a silent success). Runs the
    gate; if blocked AND ``override_reason`` is supplied, writes
    override.json and proceeds. Then flips frontmatter status from
    ``draft`` → ``active`` and returns the plan.md path.

    The CLI subcommand ``dontpanic plan lock`` wraps this function. The
    override flag (``--ignore-sufficiency-findings <reason>``) lives only at
    this level; downstream supervisor calls don't grow override surface.
    """
    plan_dir = Path(plan_dir).resolve()
    plan_md = plan_dir / "plan.md"
    plan_data = _read_frontmatter(plan_md)

    status = plan_data.get("status")
    if status != "draft":
        raise SufficiencyGateError(
            f"{plan_md}: refusing to lock — current status={status!r}, expected 'draft'"
        )

    _capture_worktree_snapshot(plan_dir, "plan lock")

    if not _should_gate_sufficiency(plan_data):
        # No goal_type / non-gated goal_type: gate is a no-op but the lock
        # mutation still proceeds. Override flag is meaningless here; if
        # the caller passed one, refuse loudly so the intent stays clear.
        if override_reason is not None:
            raise SufficiencyGateError(
                f"{plan_md}: --ignore-sufficiency-findings is meaningless for a plan "
                f"with goal_type={plan_data.get('goal_type')!r} (not in the gated set)"
            )
        _mutate_plan_status_to_active(plan_md)
        return plan_md

    # Gated plan: run gate first.
    try:
        enforce_sufficiency_gate(plan_dir)
    except SufficiencyGateError:
        if override_reason is None:
            raise  # no override → propagate gate refusal verbatim
        # Override path: validate that the override is being applied to a
        # real blocking situation (not a stale override file or missing
        # findings). Recompute hashes here; _compute_input_hashes raises
        # if any input is missing.
        hashes = _compute_input_hashes(plan_dir, plan_data)
        contract_ref = (plan_data.get("links") or {}).get("objective_contract", "")
        approver = _resolved_approver(approved_by)
        _write_override(
            plan_dir,
            reason=override_reason,
            approved_by=approver,
            plan_id=plan_data.get("id", "<unknown>"),
            goal_type=plan_data.get("goal_type", "<unknown>"),
            objective_contract_path=contract_ref,
            hashes=hashes,
        )
        # The legacy override takes precedence over the disposition path and
        # bypasses it entirely — but its use is logged in the rounds ledger
        # (plan 2026-06-09-002 F003 legacy-override interaction).
        from dontpanic_orchestrate.sufficiency_convergence import append_override_event

        append_override_event(plan_dir, reason=override_reason, approved_by=approver)

    _mutate_plan_status_to_active(plan_md)
    return plan_md


__all__ = [
    "BLOCKING_SEVERITIES",
    "OVERRIDE_ARTIFACT",
    "SufficiencyGateError",
    "enforce_sufficiency_gate",
    "lock_plan",
]
