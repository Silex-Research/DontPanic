"""F002 cost-guard — emit INBOX warnings when app-level run-rate breaches per-app budgets.

Reads costs.json + quota_state.json + config/cost_budgets.json. Compares observed run-rate to
per-app warn (default 80%) and breach (default 100%) thresholds for both GCP $ and LLM tokens.
On breach, appends a structured entry to INBOX.md via the F008 inbox writer
(scripts/dontpanic_orchestrate/inbox.py). Idempotent within a calendar week.

Distinct from F006 budget_ceiling which guards orchestration-agent quotas inside autonomous
dispatches — cost-guard is app-level, F006 is dispatch-level.
"""

from __future__ import annotations

import argparse
import calendar
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

# Reuse the F008 INBOX writer rather than re-implementing the format. The writer accepts any
# directory as the "plan dir" — we pass dashboard/state/cost-guard/ by default and a synthetic
# plan_id so cost-guard entries coexist with the per-plan INBOXes without colliding.
import importlib.util
import sys

_REPO_ROOT = Path(__file__).resolve().parents[3]
_inbox_path = _REPO_ROOT / "scripts" / "dontpanic_orchestrate" / "inbox.py"
_spec = importlib.util.spec_from_file_location("cost_guard_inbox", _inbox_path)
inbox = importlib.util.module_from_spec(_spec)
# Register before exec so @dataclass can resolve cls.__module__ via sys.modules.
sys.modules["cost_guard_inbox"] = inbox
assert _spec.loader is not None
_spec.loader.exec_module(inbox)


DEFAULT_COSTS = Path("dashboard/state/costs.json")
DEFAULT_QUOTA = Path.home() / ".jarvis" / "quota_state.json"
DEFAULT_BUDGETS = Path("config/cost_budgets.json")
DEFAULT_INBOX_DIR = Path("dashboard/state/cost-guard")
DEFAULT_SEEN_STATE = DEFAULT_INBOX_DIR / "cost_guard_seen.json"

PLAN_ID = "cost-guard"
STALE_THRESHOLD_HOURS = 24
DEFAULT_WARN_THRESHOLD = 0.80
DEFAULT_BREACH_THRESHOLD = 1.00


def _parse_iso(ts: str) -> dt.datetime:
    return dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _days_in_month(d: dt.date) -> int:
    return calendar.monthrange(d.year, d.month)[1]


def _hours_since(generated_iso: str | None, as_of: dt.datetime) -> float | None:
    if not generated_iso:
        return None
    try:
        generated = _parse_iso(generated_iso)
    except ValueError:
        return None
    return (as_of - generated).total_seconds() / 3600.0


def _is_stale(generated_iso: str | None, as_of: dt.datetime) -> bool:
    age = _hours_since(generated_iso, as_of)
    return age is None or age > STALE_THRESHOLD_HOURS


def _week_start_iso(as_of: dt.datetime) -> str:
    """Monday 00:00 UTC of the week containing as_of. Used as the dedupe-key shard so that
    a fresh week resets all 'already seen' guards."""
    monday = as_of - dt.timedelta(days=as_of.weekday())
    monday = monday.replace(hour=0, minute=0, second=0, microsecond=0)
    return monday.strftime("%Y-%m-%dT%H:%M:%SZ")


def _all_budgets_zero(budgets: dict[str, Any]) -> bool:
    apps = (budgets.get("apps") or {}).values()
    llm = (budgets.get("llm_models") or {}).values()
    for cfg in apps:
        if isinstance(cfg, dict):
            for v in cfg.values():
                if isinstance(v, (int, float)) and v > 0:
                    return False
    for cfg in llm:
        if isinstance(cfg, dict):
            for v in cfg.values():
                if isinstance(v, (int, float)) and v > 0:
                    return False
    return True


def _resolve_thresholds(budgets: dict[str, Any]) -> tuple[float, float]:
    th = budgets.get("thresholds") or {}
    warn = th.get("warn", DEFAULT_WARN_THRESHOLD)
    breach = th.get("breach", DEFAULT_BREACH_THRESHOLD)
    try:
        return float(warn), float(breach)
    except (TypeError, ValueError):
        return DEFAULT_WARN_THRESHOLD, DEFAULT_BREACH_THRESHOLD


def _project_app_month_end(mtd_usd: float, as_of: dt.datetime) -> float:
    days_into = as_of.date().day
    if days_into <= 0:
        return mtd_usd
    return mtd_usd / days_into * _days_in_month(as_of.date())


def _project_llm_week_end(used: int, week_start_iso: str, as_of: dt.datetime) -> int:
    try:
        ws = _parse_iso(week_start_iso)
    except ValueError:
        return used
    elapsed_hours = max((as_of - ws).total_seconds() / 3600.0, 1.0)
    hourly = used / elapsed_hours
    return round(hourly * 24 * 7)


def _dedupe_key(scope: str, kind: str, week_start: str) -> str:
    return hashlib.sha256(f"{scope}|{kind}|{week_start}".encode()).hexdigest()


def _load_seen(path: Path) -> set[str]:
    data = _load_json(path) or {}
    keys = data.get("keys") or []
    return set(keys) if isinstance(keys, list) else set()


def _save_seen(path: Path, keys: set[str], as_of: dt.datetime) -> None:
    payload = {
        "generated": as_of.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "keys": sorted(keys),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n")


def evaluate(
    *,
    costs: dict[str, Any] | None,
    quota: dict[str, Any] | None,
    budgets: dict[str, Any] | None,
    as_of: dt.datetime,
) -> list[dict[str, Any]]:
    """Pure function: given inputs, return the list of findings (no I/O)."""
    if not budgets or _all_budgets_zero(budgets):
        return [{
            "scope": "global",
            "kind": "no_budgets_configured",
            "severity": "info",
            "body": "config/cost_budgets.json has no non-zero budgets. Operator must populate values for cost-guard to alert.",
        }]

    findings: list[dict[str, Any]] = []

    costs_stale = costs is None or _is_stale((costs or {}).get("generated"), as_of)
    quota_stale = quota is None or _is_stale((quota or {}).get("generated"), as_of)
    if costs_stale and quota_stale:
        findings.append({
            "scope": "global",
            "kind": "data_stale",
            "severity": "info",
            "body": f"Both costs.json and quota_state.json are missing or >{STALE_THRESHOLD_HOURS}h old. Skipping breach checks.",
        })
        return findings

    warn_th, breach_th = _resolve_thresholds(budgets)

    if costs and not costs_stale:
        app_budgets = (budgets.get("apps") or {})
        totals = costs.get("totals") or {}
        for app, mtd in sorted(totals.items()):
            if app == "Total":
                continue
            cfg = app_budgets.get(app) or {}
            budget = cfg.get("gcp_monthly_budget_usd") or 0
            if not isinstance(budget, (int, float)) or budget <= 0:
                continue
            try:
                projected = _project_app_month_end(float(mtd), as_of)
            except (TypeError, ValueError):
                continue
            ratio = projected / budget
            if ratio >= breach_th:
                findings.append({
                    "scope": f"app:{app}",
                    "kind": "cost_breach",
                    "severity": "action_required",
                    "ratio": round(ratio, 4),
                    "projected_month_end_usd": round(projected, 2),
                    "budget_usd": float(budget),
                    "body": (
                        f"GCP projection for {app} ({projected:.2f} USD month-end) is at "
                        f"{ratio*100:.1f}% of the configured monthly budget ({budget:.2f} USD). "
                        f"Threshold: {breach_th*100:.0f}%."
                    ),
                })
            elif ratio >= warn_th:
                findings.append({
                    "scope": f"app:{app}",
                    "kind": "cost_warn",
                    "severity": "review",
                    "ratio": round(ratio, 4),
                    "projected_month_end_usd": round(projected, 2),
                    "budget_usd": float(budget),
                    "body": (
                        f"GCP projection for {app} ({projected:.2f} USD month-end) is at "
                        f"{ratio*100:.1f}% of the configured monthly budget ({budget:.2f} USD). "
                        f"Threshold: {warn_th*100:.0f}%."
                    ),
                })

    if quota and not quota_stale:
        llm_budgets = (budgets.get("llm_models") or {})
        week_start = quota.get("week_start") or _week_start_iso(as_of)
        models = quota.get("models") or {}
        for model_name, info in sorted(models.items()):
            if not isinstance(info, dict):
                continue
            cfg = llm_budgets.get(model_name) or {}
            # Each model's budget can be either weekly_token_budget or weekly_call_budget.
            budget = cfg.get("weekly_token_budget") or cfg.get("weekly_call_budget") or 0
            if not isinstance(budget, (int, float)) or budget <= 0:
                continue
            used = info.get("used")
            if not isinstance(used, (int, float)):
                continue
            projected = _project_llm_week_end(int(used), week_start, as_of)
            ratio = projected / budget if budget > 0 else 0
            if ratio >= breach_th:
                findings.append({
                    "scope": f"llm:{model_name}",
                    "kind": "cost_breach",
                    "severity": "action_required",
                    "ratio": round(ratio, 4),
                    "projected_week_end": projected,
                    "budget": float(budget),
                    "body": (
                        f"LLM projection for {model_name} ({projected} {info.get('unit') or 'units'} "
                        f"week-end) is at {ratio*100:.1f}% of the configured weekly budget ({budget}). "
                        f"Threshold: {breach_th*100:.0f}%."
                    ),
                })
            elif ratio >= warn_th:
                findings.append({
                    "scope": f"llm:{model_name}",
                    "kind": "cost_warn",
                    "severity": "review",
                    "ratio": round(ratio, 4),
                    "projected_week_end": projected,
                    "budget": float(budget),
                    "body": (
                        f"LLM projection for {model_name} ({projected} {info.get('unit') or 'units'} "
                        f"week-end) is at {ratio*100:.1f}% of the configured weekly budget ({budget}). "
                        f"Threshold: {warn_th*100:.0f}%."
                    ),
                })

    if not findings:
        if costs_stale or quota_stale:
            findings.append({
                "scope": "global",
                "kind": "data_stale",
                "severity": "info",
                "body": (
                    f"{'costs.json' if costs_stale else 'quota_state.json'} is stale "
                    f"(>{STALE_THRESHOLD_HOURS}h old); other input was checked normally and produced no findings."
                ),
            })
    return findings


def emit_findings(
    findings: list[dict[str, Any]],
    *,
    inbox_dir: Path,
    seen_state_path: Path,
    as_of: dt.datetime,
) -> dict[str, int]:
    """Append entries to INBOX.md, honoring the dedupe-by-week guard. Returns counts."""
    week_start = _week_start_iso(as_of)
    seen = _load_seen(seen_state_path)
    appended = 0
    skipped_idempotent = 0
    for f in findings:
        # Findings with kind in {no_budgets_configured, data_stale} also dedupe within a week
        # so repeated invocations don't spam.
        key = _dedupe_key(f["scope"], f["kind"], week_start)
        if key in seen:
            skipped_idempotent += 1
            continue
        inbox.append_event(
            inbox_dir,
            f["kind"],
            plan_id=PLAN_ID,
            timestamp=as_of.strftime("%Y-%m-%dT%H:%M:%SZ"),
            scope=f["scope"],
            severity=f.get("severity", "info"),
            ratio=f.get("ratio"),
            body=f.get("body", ""),
        )
        seen.add(key)
        appended += 1
    _save_seen(seen_state_path, seen, as_of)
    return {
        "appended": appended,
        "skipped_idempotent": skipped_idempotent,
        "total_findings": len(findings),
    }


def _resolve_inputs(args: argparse.Namespace) -> tuple[Path, Path, Path]:
    if args.fixtures:
        base = Path(args.fixtures)
        return (
            base / "costs.json",
            base / "quota_state.json",
            base / "cost_budgets.json",
        )
    return (
        Path(args.costs) if args.costs else DEFAULT_COSTS,
        Path(args.quota) if args.quota else DEFAULT_QUOTA,
        Path(args.budgets) if args.budgets else DEFAULT_BUDGETS,
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="App-level budget guard. Reads cost state, emits INBOX entries.")
    p.add_argument("--costs", help="Path to costs.json")
    p.add_argument("--quota", help="Path to quota_state.json")
    p.add_argument("--budgets", help="Path to cost_budgets.json")
    p.add_argument("--inbox-dir", help="Directory containing INBOX.md")
    p.add_argument("--seen-state", help="Path to dedupe state file")
    p.add_argument("--as-of", help="ISO-8601 timestamp to override 'now'")
    p.add_argument("--fixtures", help="Directory containing costs.json + quota_state.json + cost_budgets.json")
    args = p.parse_args(argv)

    if args.as_of:
        try:
            as_of = _parse_iso(args.as_of)
            if as_of.tzinfo is None:
                as_of = as_of.replace(tzinfo=dt.timezone.utc)
        except ValueError:
            print(f"Invalid --as-of: {args.as_of}", file=sys.stderr)
            return 2
    else:
        as_of = dt.datetime.now(dt.timezone.utc)

    inbox_dir = Path(args.inbox_dir) if args.inbox_dir else DEFAULT_INBOX_DIR
    seen_state = Path(args.seen_state) if args.seen_state else (inbox_dir / "cost_guard_seen.json")

    costs_path, quota_path, budgets_path = _resolve_inputs(args)
    costs = _load_json(costs_path)
    quota = _load_json(quota_path)
    budgets = _load_json(budgets_path)

    findings = evaluate(costs=costs, quota=quota, budgets=budgets, as_of=as_of)
    counts = emit_findings(findings, inbox_dir=inbox_dir, seen_state_path=seen_state, as_of=as_of)

    print(f"✓ findings: {counts['total_findings']}")
    print(f"  appended:          {counts['appended']}")
    print(f"  skipped (in-week): {counts['skipped_idempotent']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
