"""F021 dogfood + general plan validator.

Usage:
  python3 validate.py <plan-dir>...

For each plan directory:
- Load plan.md frontmatter, validate against Plan model.
- If Plan.goal_type ∈ {parity, new_feature, migration, incident}:
  require links.objective_contract, resolve relative to plan_dir,
  validate against ObjectiveContract model. Cross-check goal_type
  consistency between Plan and ObjectiveContract.
- Load features.json, validate against Features model.
- Classify each audit/*.json by artifact type and dispatch:
    - signoff*.json                -> Signoff model
    - *-i\\d+.json (volley pattern) -> Audit envelope model
    - gate-state.json (auxiliary)  -> skip with info-line
    - anything else                -> warn + skip (not error)

Exits 0 if all validate, 1 if any error.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import yaml
from pydantic import ValidationError

SCHEMAS_DIR = Path(__file__).parent
sys.path.insert(0, str(SCHEMAS_DIR))

from models.audit_model import Audit  # noqa: E402
from models.features_model import Features  # noqa: E402
from models.objective_contract_model import (  # noqa: E402
    GoalType as ContractGoalType,
)
from models.objective_contract_model import (  # noqa: E402
    ObjectiveContract,
)
from models.plan_model import GoalType as PlanGoalType  # noqa: E402
from models.plan_model import Plan  # noqa: E402
from models.signoff_model import Signoff  # noqa: E402

# Goal types that require an ObjectiveContract per Goal Governance V1 §4
# applicability rule. Plans with goal_type in this set MUST declare
# links.objective_contract; mechanical/infra/refactor (and absent goal_type)
# do not.
_GOAL_TYPES_REQUIRING_CONTRACT = frozenset({
    PlanGoalType.parity,
    PlanGoalType.new_feature,
    PlanGoalType.migration,
    PlanGoalType.incident,
})

# v1 known-auxiliary list — files under audit/ that are written by orchestrator
# subsystems but are NOT audit envelopes. The validator skips them with an
# info-line instead of false-failing them against the Audit model.
# Extending the list is a one-line change + a new fixture under tests/validator/.
_KNOWN_AUXILIARY = frozenset({"gate-state.json"})

# Volley-pattern audit envelopes end with `-i<digits>.json`
# (e.g. claude-implementer-i0.json, codex-auditor-F002-i1.json).
_AUDIT_ENVELOPE_RE = re.compile(r"-i\d+\.json$")


def _classify_audit_artifact(filename: str) -> str:
    """Return one of: 'signoff', 'audit', 'auxiliary', 'unknown'.

    Pure function; explicit dispatch (not filename-substring). Order:
    signoff prefix wins over volley pattern (both could conceivably match
    a name like 'signoff-i0.json', but signoff is the more specific
    semantic class).
    """
    if filename.startswith("signoff"):
        return "signoff"
    if _AUDIT_ENVELOPE_RE.search(filename):
        return "audit"
    if filename in _KNOWN_AUXILIARY:
        return "auxiliary"
    return "unknown"


def _frontmatter(path: Path) -> dict:
    text = path.read_text()
    if not text.startswith("---"):
        raise ValueError(f"{path}: missing frontmatter delimiter '---'")
    parts = text.split("---", 2)
    if len(parts) < 3:
        raise ValueError(f"{path}: malformed frontmatter")
    return yaml.safe_load(parts[1])


def _check(name: str, model, data) -> tuple[bool, str]:
    try:
        model.model_validate(data)
        return True, f"  ✓ {name}"
    except ValidationError as exc:
        msg = "; ".join(
            f"{'.'.join(str(x) for x in e['loc'])}: {e['msg']}"
            for e in exc.errors()[:5]
        )
        return False, f"  ✗ {name} — {msg}"


def _check_objective_contract(plan_dir: Path, plan_data: dict) -> tuple[bool, str | None]:
    """Goal Governance V1 §4 applicability check.

    Returns (ok, line). When the plan's goal_type doesn't require a contract,
    returns (True, None) — caller should skip printing.
    """
    goal_type_raw = plan_data.get("goal_type")
    if goal_type_raw is None:
        return True, None  # not opted in; backward-compat path

    try:
        goal_type = PlanGoalType(goal_type_raw)
    except ValueError:
        # Plan model validation already flagged this; don't double-report.
        return True, None

    if goal_type not in _GOAL_TYPES_REQUIRING_CONTRACT:
        return True, None  # mechanical / infra / refactor — no contract required

    label = "objective_contract"
    links = plan_data.get("links") or {}
    contract_path_str = links.get("objective_contract") if isinstance(links, dict) else None

    if not contract_path_str:
        return False, (
            f"  ✗ {label} — required by goal_type={goal_type.value} but "
            "links.objective_contract is missing or empty"
        )

    contract_path = (plan_dir / contract_path_str).resolve()
    if not contract_path.is_file():
        return False, (
            f"  ✗ {label} — required by goal_type={goal_type.value} but file "
            f"at {contract_path_str!r} does not exist"
        )

    try:
        contract_data = json.loads(contract_path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        return False, f"  ✗ {label} — failed to load {contract_path_str!r}: {exc}"

    try:
        contract = ObjectiveContract.model_validate(contract_data)
    except ValidationError as exc:
        msg = "; ".join(
            f"{'.'.join(str(x) for x in e['loc'])}: {e['msg']}"
            for e in exc.errors()[:5]
        )
        return False, f"  ✗ {label} — {contract_path_str}: {msg}"

    # Cross-check: Plan.goal_type must match ObjectiveContract.goal_type when
    # both are present. ObjectiveContract.goal_type is the 4-value subset, so
    # mismatch only happens when the plan declares one of the four required
    # types and the contract declares a different one of the four.
    if contract.goal_type.value != goal_type.value:
        return False, (
            f"  ✗ {label} — goal_type mismatch: plan declares "
            f"{goal_type.value!r}, contract declares "
            f"{contract.goal_type.value!r}"
        )

    return True, f"  ✓ {label} ({contract_path_str})"


def validate_plan_dir(plan_dir: Path) -> int:
    print(f"\n[plan] {plan_dir.name}")
    errors = 0

    plan_data: dict | None = None

    plan_md = plan_dir / "plan.md"
    if plan_md.is_file():
        try:
            plan_data = _frontmatter(plan_md)
            ok, line = _check("plan.md frontmatter", Plan, plan_data)
        except (ValueError, yaml.YAMLError) as exc:
            ok, line = False, f"  ✗ plan.md frontmatter — {exc}"
        print(line)
        errors += 0 if ok else 1

        # Goal Governance V1 §4 — gated objective_contract check. Only runs
        # when the plan declares a goal_type that requires a contract. Plans
        # without goal_type (existing-style + mechanical/infra/refactor) are
        # silent here and remain backward-compatible.
        if ok and plan_data is not None:
            contract_ok, contract_line = _check_objective_contract(plan_dir, plan_data)
            if contract_line is not None:
                print(contract_line)
                errors += 0 if contract_ok else 1

    features_json = plan_dir / "features.json"
    if features_json.is_file():
        ok, line = _check(
            "features.json", Features, json.loads(features_json.read_text())
        )
        print(line)
        errors += 0 if ok else 1

    audit_dir = plan_dir / "audit"
    if audit_dir.is_dir():
        for f in sorted(audit_dir.glob("*.json")):
            kind = _classify_audit_artifact(f.name)
            if kind == "auxiliary":
                print(f"  ⊘ audit/{f.name} — auxiliary, skipped")
                continue
            if kind == "unknown":
                print(f"  ⚠ audit/{f.name} — unknown audit artifact, skipped")
                continue
            data = json.loads(f.read_text())
            model = Signoff if kind == "signoff" else Audit
            ok, line = _check(f"audit/{f.name}", model, data)
            print(line)
            errors += 0 if ok else 1

    return errors


def main() -> int:
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <plan-dir>...", file=sys.stderr)
        return 2

    total_errors = 0
    for arg in sys.argv[1:]:
        plan_dir = Path(arg).resolve()
        if not plan_dir.is_dir():
            print(f"Not a directory: {plan_dir}", file=sys.stderr)
            total_errors += 1
            continue
        total_errors += validate_plan_dir(plan_dir)

    print()
    if total_errors == 0:
        print("✓ All plans validate against agent-conventions v1.0 schemas")
        return 0
    print(f"✗ {total_errors} validation error(s)")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
