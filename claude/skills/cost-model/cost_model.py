"""F001 cost-model — project month-end and next-month spend per app and per LLM provider.

Reads costs.json + quota_state.json + (optional) revenue.json. Pure-read; never mutates inputs.
Emits a markdown report and JSON sibling under <out>/<run-id>/cost-model-<ts>.{md,json}.

Companion to F020 quota_check.py and #691 refresh-costs.sh. See SKILL.md for ergonomics.
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

DEFAULT_COSTS = Path("dashboard/state/costs.json")
DEFAULT_QUOTA = Path.home() / ".jarvis" / "quota_state.json"
DEFAULT_REVENUE = Path("dashboard/state/revenue.json")
DEFAULT_OUT = Path("evidence/cost-model")

STALE_THRESHOLD_HOURS = 24


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


def _next_month(d: dt.date) -> dt.date:
    if d.month == 12:
        return dt.date(d.year + 1, 1, 1)
    return dt.date(d.year, d.month + 1, 1)


def _hours_since(generated_iso: str, as_of: dt.datetime) -> float | None:
    try:
        generated = _parse_iso(generated_iso)
    except (TypeError, ValueError):
        return None
    return (as_of - generated).total_seconds() / 3600.0


def _is_stale(generated_iso: str | None, as_of: dt.datetime) -> bool:
    if not generated_iso:
        return True
    age = _hours_since(generated_iso, as_of)
    if age is None:
        return True
    return age > STALE_THRESHOLD_HOURS


def project_app_gcp(
    *,
    mtd_usd: float,
    as_of: dt.datetime,
) -> dict[str, Any]:
    """Project GCP month-end and next-month spend from MTD using straight-line trajectory."""
    today = as_of.date()
    days_into = today.day
    dim = _days_in_month(today)
    dinm = _days_in_month(_next_month(today))
    daily_rate = mtd_usd / days_into if days_into > 0 else 0.0
    return {
        "mtd_usd": round(mtd_usd, 2),
        "days_into_month": days_into,
        "days_in_month": dim,
        "daily_rate_usd": round(daily_rate, 4),
        "projected_month_end_usd": round(daily_rate * dim, 2),
        "projected_next_month_usd": round(daily_rate * dinm, 2),
    }


def project_llm_model(
    *,
    used: int,
    limit: int | None,
    unit: str | None,
    week_start_iso: str,
    as_of: dt.datetime,
) -> dict[str, Any]:
    """Project per-model weekly + monthly token usage from week-to-date burn."""
    try:
        week_start = _parse_iso(week_start_iso)
    except (TypeError, ValueError):
        return {
            "used": used,
            "limit": limit,
            "unit": unit,
            "projected_week_end": used,
            "projected_monthly": used,
            "percent_of_cap_week_end": None,
            "percent_of_cap_monthly": None,
        }
    elapsed_hours = max((as_of - week_start).total_seconds() / 3600.0, 1.0)
    hourly_rate = used / elapsed_hours
    week_end_proj = round(hourly_rate * 24 * 7)
    monthly_proj = round(week_end_proj * 4.33)
    pct_week = (
        round(100.0 * week_end_proj / limit, 2)
        if isinstance(limit, int) and limit > 0
        else None
    )
    pct_monthly = (
        round(100.0 * monthly_proj / (limit * 4.33), 2)
        if isinstance(limit, int) and limit > 0
        else None
    )
    return {
        "used": used,
        "limit": limit,
        "unit": unit,
        "projected_week_end": week_end_proj,
        "projected_monthly": monthly_proj,
        "percent_of_cap_week_end": pct_week,
        "percent_of_cap_monthly": pct_monthly,
    }


def build_report(
    *,
    costs: dict[str, Any] | None,
    quota: dict[str, Any] | None,
    revenue: dict[str, Any] | None,
    as_of: dt.datetime,
) -> dict[str, Any]:
    """Compose the structured projection. Pure function — given the same inputs it returns
    the same output, which is what makes the golden-output tests possible."""
    if not costs and not quota:
        return {
            "generated": as_of.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "as_of": as_of.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "mode": "data_unavailable",
            "by_app": {},
            "by_llm": {},
            "notes": ["Both costs.json and quota_state.json missing or unreadable."],
        }

    by_app: dict[str, Any] = {}
    notes: list[str] = []

    if costs:
        if _is_stale(costs.get("generated"), as_of):
            notes.append(
                f"costs.json is stale (>{STALE_THRESHOLD_HOURS}h old); projections may not reflect current burn."
            )
        totals = costs.get("totals") or {}
        for app, mtd in sorted(totals.items()):
            if app == "Total":
                continue
            try:
                mtd_f = float(mtd)
            except (TypeError, ValueError):
                continue
            entry = project_app_gcp(mtd_usd=mtd_f, as_of=as_of)
            if revenue:
                rev_app = (revenue.get("by_app") or {}).get(app) or {}
                monthly_rev = rev_app.get("monthly_revenue_usd")
                if isinstance(monthly_rev, (int, float)):
                    entry["monthly_revenue_usd"] = round(float(monthly_rev), 2)
                    entry["projected_net_month_end_usd"] = round(
                        float(monthly_rev) - entry["projected_month_end_usd"], 2
                    )
            by_app[app] = entry
    else:
        notes.append("costs.json missing — GCP projections unavailable.")

    by_llm: dict[str, Any] = {}
    if quota:
        if _is_stale(quota.get("generated"), as_of):
            notes.append(
                f"quota_state.json is stale (>{STALE_THRESHOLD_HOURS}h old); LLM projections may not reflect current burn."
            )
        week_start = quota.get("week_start") or as_of.strftime("%Y-%m-%dT00:00:00+00:00")
        models = quota.get("models") or {}
        for model_name, info in sorted(models.items()):
            if not isinstance(info, dict):
                continue
            limit = info.get("limit")
            if limit is not None and not isinstance(limit, int):
                limit = None
            used = int(info.get("used") or 0)
            by_llm[model_name] = project_llm_model(
                used=used,
                limit=limit,
                unit=info.get("unit"),
                week_start_iso=week_start,
                as_of=as_of,
            )
    else:
        notes.append("quota_state.json missing — LLM projections unavailable.")

    if revenue and not (revenue.get("by_app") or {}):
        notes.append("revenue.json present but empty — running cost-only.")

    mode = "with-revenue" if (revenue and (revenue.get("by_app") or {}) and costs) else "cost-only"
    if not costs and not quota:
        mode = "data_unavailable"

    return {
        "generated": as_of.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "as_of": as_of.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "mode": mode,
        "by_app": by_app,
        "by_llm": by_llm,
        "notes": notes,
    }


def render_markdown(report: dict[str, Any]) -> str:
    """Operator-facing markdown view. Keep deterministic — no relative time strings."""
    lines: list[str] = []
    lines.append(f"# cost-model — generated {report['generated']}")
    lines.append("")
    lines.append(f"- mode: `{report['mode']}`")
    lines.append(f"- as_of: `{report['as_of']}`")
    if report.get("notes"):
        lines.append("- notes:")
        for n in report["notes"]:
            lines.append(f"  - {n}")
    lines.append("")

    if report["by_app"]:
        lines.append("## GCP — per-app projection")
        lines.append("")
        if report["mode"] == "with-revenue":
            lines.append("| app | MTD $ | daily $ | projected month-end $ | projected next month $ | monthly revenue $ | net month-end $ |")
            lines.append("|---|---:|---:|---:|---:|---:|---:|")
            for app, entry in report["by_app"].items():
                rev = entry.get("monthly_revenue_usd")
                net = entry.get("projected_net_month_end_usd")
                lines.append(
                    f"| {app} | {entry['mtd_usd']:.2f} | {entry['daily_rate_usd']:.4f} | "
                    f"{entry['projected_month_end_usd']:.2f} | {entry['projected_next_month_usd']:.2f} | "
                    f"{(rev if rev is not None else 0):.2f} | {(net if net is not None else 0):.2f} |"
                )
        else:
            lines.append("| app | MTD $ | daily $ | projected month-end $ | projected next month $ |")
            lines.append("|---|---:|---:|---:|---:|")
            for app, entry in report["by_app"].items():
                lines.append(
                    f"| {app} | {entry['mtd_usd']:.2f} | {entry['daily_rate_usd']:.4f} | "
                    f"{entry['projected_month_end_usd']:.2f} | {entry['projected_next_month_usd']:.2f} |"
                )
        lines.append("")

    if report["by_llm"]:
        lines.append("## LLM — per-model projection")
        lines.append("")
        lines.append("| model | used | unit | limit | projected week-end | % cap week | projected monthly | % cap monthly |")
        lines.append("|---|---:|:---:|---:|---:|---:|---:|---:|")
        for model, entry in report["by_llm"].items():
            limit_str = str(entry["limit"]) if entry["limit"] is not None else "—"
            pct_week = f"{entry['percent_of_cap_week_end']:.2f}" if entry.get("percent_of_cap_week_end") is not None else "—"
            pct_monthly = f"{entry['percent_of_cap_monthly']:.2f}" if entry.get("percent_of_cap_monthly") is not None else "—"
            unit = entry.get("unit") or "—"
            lines.append(
                f"| {model} | {entry['used']} | {unit} | {limit_str} | "
                f"{entry['projected_week_end']} | {pct_week} | "
                f"{entry['projected_monthly']} | {pct_monthly} |"
            )
        lines.append("")

    if report["mode"] == "data_unavailable":
        lines.append("_No cost or quota state available. Run `scripts/maintainer/refresh-costs.sh` and `scripts/quota_check.py` first._")
        lines.append("")

    return "\n".join(lines)


def _resolve_inputs(args: argparse.Namespace) -> tuple[Path, Path, Path]:
    if args.fixtures:
        base = Path(args.fixtures)
        return (
            base / "costs.json",
            base / "quota_state.json",
            base / "revenue.json",
        )
    return (
        Path(args.costs) if args.costs else DEFAULT_COSTS,
        Path(args.quota) if args.quota else DEFAULT_QUOTA,
        Path(args.revenue) if args.revenue else DEFAULT_REVENUE,
    )


def _run_id(report: dict[str, Any]) -> str:
    payload = json.dumps(
        {"as_of": report["as_of"], "mode": report["mode"]},
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:12]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Project month-end and next-month spend per app and LLM provider.")
    p.add_argument("--costs", help="Path to costs.json")
    p.add_argument("--quota", help="Path to quota_state.json")
    p.add_argument("--revenue", help="Path to revenue.json")
    p.add_argument("--out", help="Output directory")
    p.add_argument("--as-of", help="ISO-8601 timestamp to override 'now' (deterministic tests)")
    p.add_argument("--fixtures", help="Directory containing costs.json + quota_state.json + (optional) revenue.json")
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

    costs_path, quota_path, revenue_path = _resolve_inputs(args)
    costs = _load_json(costs_path)
    quota = _load_json(quota_path)
    revenue = _load_json(revenue_path)

    report = build_report(costs=costs, quota=quota, revenue=revenue, as_of=as_of)

    out_root = Path(args.out) if args.out else DEFAULT_OUT
    run_dir = out_root / _run_id(report)
    run_dir.mkdir(parents=True, exist_ok=True)

    ts_compact = as_of.strftime("%Y%m%dT%H%M%SZ")
    json_path = run_dir / f"cost-model-{ts_compact}.json"
    md_path = run_dir / f"cost-model-{ts_compact}.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    md_path.write_text(render_markdown(report))

    print(f"✓ wrote {md_path}")
    print(f"✓ wrote {json_path}")
    print(f"  mode: {report['mode']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
