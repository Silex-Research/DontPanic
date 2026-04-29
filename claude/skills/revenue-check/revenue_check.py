"""F003 revenue-check — pull product revenue per app, write revenue.json + cash-flow report.

Adapter-based design:
- FixtureAdapter   — reads JSON fixtures (--stub mode, no credentials needed).
- GlamLedgerAdapter — sums Firestore `creatorEarningsLedger.amount` for finalized + estimated rows.
- DeferredAdapter   — returns source='unavailable' for apps without a Firestore-mirrored revenue surface
                      (e.g., Spin & Dine on StoreKit 2 / App Store Connect — see D001 follow-up).

Live Firestore code paths import firebase_client.py lazily, so fresh-clone tests stay creds-free.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

DEFAULT_REVENUE_OUT = Path("dashboard/state/revenue.json")
DEFAULT_EVIDENCE_DIR = Path("evidence/revenue-check")
DEFAULT_COSTS = Path("dashboard/state/costs.json")
DEFAULT_APPS = ["Styln"]

# Apps whose revenue lives outside any Firestore surface we can pull. See parent plan D001.
DEFERRED_APPS: dict[str, str] = {
    "Spin & Dine": (
        "StoreKit 2 / App Store Connect — no Firestore mirror exists. "
        "Future work: ingest reports from App Store Connect (TODO: linked follow-up task at acceptance time)."
    ),
}


@dataclass(frozen=True)
class RevenueResult:
    monthly_revenue_usd: float | None
    source: str
    granularity: str
    last_event_at: str | None


class RevenueAdapter(Protocol):
    """Each app maps to one adapter. Adapters are pure given their inputs (the test path
    exercises the protocol directly without going through Firestore)."""

    def fetch(self, app: str, as_of: dt.datetime) -> RevenueResult: ...


class FixtureAdapter:
    """Reads `<fixtures_root>/<app>/revenue_events.json`. The expected shape mirrors
    the Glam Firestore export: a list of {month, amount_usd, category, last_event_at}."""

    def __init__(self, fixtures_root: Path) -> None:
        self.root = fixtures_root

    def fetch(self, app: str, as_of: dt.datetime) -> RevenueResult:
        # Slug the app name to a filesystem-safe directory.
        slug = app.replace("/", "-").replace(" ", "_").replace("&", "and").lower()
        events_path = self.root / slug / "revenue_events.json"
        if not events_path.is_file():
            return RevenueResult(
                monthly_revenue_usd=None,
                source=f"fixture:missing:{events_path}",
                granularity="monthly",
                last_event_at=None,
            )
        try:
            data = json.loads(events_path.read_text())
        except (json.JSONDecodeError, OSError):
            return RevenueResult(None, "fixture:unreadable", "monthly", None)

        target_month = as_of.strftime("%Y-%m")
        total = 0.0
        last_at: str | None = None
        for row in data.get("events", []):
            if row.get("month") != target_month:
                continue
            if row.get("category") not in ("finalized", "estimated"):
                continue
            try:
                total += float(row.get("amount_usd") or 0)
            except (TypeError, ValueError):
                continue
            row_at = row.get("last_event_at")
            if row_at and (last_at is None or row_at > last_at):
                last_at = row_at
        return RevenueResult(
            monthly_revenue_usd=round(total, 2),
            source="fixture",
            granularity="monthly",
            last_event_at=last_at,
        )


class DeferredAdapter:
    """Returns source='unavailable' with the deferral reason. Used for apps in DEFERRED_APPS."""

    def __init__(self, reason: str) -> None:
        self.reason = reason

    def fetch(self, app: str, as_of: dt.datetime) -> RevenueResult:
        return RevenueResult(
            monthly_revenue_usd=None,
            source=f"unavailable: {self.reason}",
            granularity="monthly",
            last_event_at=None,
        )


class GlamLedgerAdapter:
    """Live adapter: sums Glam's creatorEarningsLedger entries where category is finalized
    or estimated for the target month. Imports firebase-admin lazily so the import cost is
    only paid in non-stub mode.

    The Firestore query shape is documented here for readers; live execution requires ADC.
    """

    def __init__(self, project_id: str = "glam-ac11e") -> None:
        self.project_id = project_id

    def fetch(self, app: str, as_of: dt.datetime) -> RevenueResult:  # pragma: no cover - live path
        try:
            from google.cloud import firestore  # noqa: F401
        except ImportError:
            return RevenueResult(
                None,
                "unavailable: firebase-admin / google-cloud-firestore not installed",
                "monthly",
                None,
            )

        try:
            from google.cloud.firestore import Client  # noqa: F401
            client = Client(project=self.project_id)
            target_month = as_of.strftime("%Y-%m")
            month_start = dt.datetime(as_of.year, as_of.month, 1, tzinfo=dt.timezone.utc)
            next_month = (
                dt.datetime(as_of.year + 1, 1, 1, tzinfo=dt.timezone.utc)
                if as_of.month == 12
                else dt.datetime(as_of.year, as_of.month + 1, 1, tzinfo=dt.timezone.utc)
            )
            query = (
                client.collection("creatorEarningsLedger")
                .where("createdAt", ">=", month_start)
                .where("createdAt", "<", next_month)
                .where("category", "in", ["finalized", "estimated"])
            )
            total = 0.0
            last_at: str | None = None
            for doc in query.stream():
                d = doc.to_dict()
                try:
                    total += float(d.get("amount") or 0)
                except (TypeError, ValueError):
                    continue
                ts = d.get("createdAt")
                if ts is not None:
                    iso = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)
                    if last_at is None or iso > last_at:
                        last_at = iso
            return RevenueResult(
                monthly_revenue_usd=round(total, 2),
                source=f"firestore:{self.project_id}/creatorEarningsLedger",
                granularity="monthly",
                last_event_at=last_at,
            )
        except Exception as e:
            return RevenueResult(None, f"unavailable: live-query-failed: {type(e).__name__}", "monthly", None)


def resolve_adapter(app: str, *, stub: bool, fixtures_root: Path | None) -> RevenueAdapter:
    if stub or fixtures_root is not None:
        if fixtures_root is None:
            raise ValueError("--stub requires --fixtures or a default fixtures path")
        return FixtureAdapter(fixtures_root)
    if app in DEFERRED_APPS:
        return DeferredAdapter(DEFERRED_APPS[app])
    if app == "Styln":
        return GlamLedgerAdapter()
    return DeferredAdapter(f"no adapter registered for {app}")


def build_revenue_state(
    *,
    apps: list[str],
    adapter_for: dict[str, RevenueAdapter],
    as_of: dt.datetime,
) -> dict[str, Any]:
    by_app: dict[str, Any] = {}
    for app in apps:
        adapter = adapter_for[app]
        result = adapter.fetch(app, as_of)
        by_app[app] = {
            "monthly_revenue_usd": result.monthly_revenue_usd,
            "source": result.source,
            "granularity": result.granularity,
            "last_event_at": result.last_event_at,
        }
    return {
        "generated": as_of.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "by_app": by_app,
    }


def render_cash_flow(
    *,
    revenue: dict[str, Any],
    costs: dict[str, Any] | None,
    as_of: dt.datetime,
) -> dict[str, Any]:
    """Compute net = revenue − GCP cost per app for the cash-flow report.

    Costs are reported month-to-date; revenue is also month-to-date. Net is therefore an MTD
    figure, not a projection. cost-model is the projection skill — revenue-check stays factual.
    """
    cost_totals = (costs or {}).get("totals") or {}
    by_app: dict[str, Any] = {}
    for app, rev_entry in (revenue.get("by_app") or {}).items():
        revenue_usd = rev_entry.get("monthly_revenue_usd")
        cost_usd = cost_totals.get(app)
        try:
            cost_f = float(cost_usd) if cost_usd is not None else None
        except (TypeError, ValueError):
            cost_f = None
        net = None
        if isinstance(revenue_usd, (int, float)) and isinstance(cost_f, (int, float)):
            net = round(revenue_usd - cost_f, 2)
        by_app[app] = {
            "monthly_revenue_usd": revenue_usd,
            "mtd_gcp_cost_usd": cost_f,
            "mtd_net_usd": net,
            "source": rev_entry.get("source"),
        }
    return {
        "generated": as_of.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "by_app": by_app,
    }


def render_cash_flow_markdown(report: dict[str, Any]) -> str:
    lines = [f"# cash-flow — generated {report['generated']}", ""]
    if not report.get("by_app"):
        lines.append("_No apps reported._")
        lines.append("")
        return "\n".join(lines)
    lines.append("| app | monthly revenue $ | MTD GCP cost $ | MTD net $ | source |")
    lines.append("|---|---:|---:|---:|---|")
    for app, entry in report["by_app"].items():
        rev = entry.get("monthly_revenue_usd")
        cost = entry.get("mtd_gcp_cost_usd")
        net = entry.get("mtd_net_usd")
        rev_s = f"{rev:.2f}" if isinstance(rev, (int, float)) else "—"
        cost_s = f"{cost:.2f}" if isinstance(cost, (int, float)) else "—"
        net_s = f"{net:.2f}" if isinstance(net, (int, float)) else "—"
        lines.append(f"| {app} | {rev_s} | {cost_s} | {net_s} | {entry.get('source', '—')} |")
    lines.append("")
    return "\n".join(lines)


def _run_id(report: dict[str, Any]) -> str:
    payload = json.dumps({"generated": report["generated"]}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:12]


def _parse_iso(ts: str) -> dt.datetime:
    return dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Pull revenue per app, write revenue.json + cash-flow report.")
    p.add_argument("--stub", action="store_true", help="Use FixtureAdapter for all apps")
    p.add_argument("--live", action="store_true", help="Opt in to live adapters that may require ADC")
    p.add_argument("--apps", help="Comma-separated app list (default: Styln)")
    p.add_argument("--out", help="Path for revenue.json")
    p.add_argument("--evidence-dir", help="Output directory for cash-flow report")
    p.add_argument("--costs", help="Path to costs.json")
    p.add_argument("--as-of", help="ISO-8601 timestamp to override 'now'")
    p.add_argument("--fixtures", help="Fixtures root (implies --stub)")
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

    apps = [a.strip() for a in args.apps.split(",")] if args.apps else list(DEFAULT_APPS)
    fixtures_root = Path(args.fixtures) if args.fixtures else None
    stub = args.stub or (fixtures_root is not None)

    if stub and args.live:
        print("Use either --stub/--fixtures or --live, not both.", file=sys.stderr)
        return 2

    if not stub and not args.live:
        # Refuse to run live by accident if no flags + no creds expectation.
        # Operator must explicitly opt in to a live mode. fresh-clone CI passes --stub.
        print("revenue-check requires --stub/--fixtures or explicit --live.", file=sys.stderr)
        return 2

    adapter_for: dict[str, RevenueAdapter] = {
        app: resolve_adapter(app, stub=stub, fixtures_root=fixtures_root) for app in apps
    }

    revenue = build_revenue_state(apps=apps, adapter_for=adapter_for, as_of=as_of)

    out_path = Path(args.out) if args.out else DEFAULT_REVENUE_OUT
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(revenue, indent=2, sort_keys=True) + "\n")

    costs = None
    costs_path = Path(args.costs) if args.costs else DEFAULT_COSTS
    if costs_path.is_file():
        try:
            costs = json.loads(costs_path.read_text())
        except (json.JSONDecodeError, OSError):
            costs = None

    cash_flow = render_cash_flow(revenue=revenue, costs=costs, as_of=as_of)
    evidence_root = Path(args.evidence_dir) if args.evidence_dir else DEFAULT_EVIDENCE_DIR
    run_dir = evidence_root / _run_id(revenue)
    run_dir.mkdir(parents=True, exist_ok=True)
    ts_compact = as_of.strftime("%Y%m%dT%H%M%SZ")
    (run_dir / f"cash-flow-{ts_compact}.json").write_text(
        json.dumps(cash_flow, indent=2, sort_keys=True) + "\n"
    )
    (run_dir / f"cash-flow-{ts_compact}.md").write_text(render_cash_flow_markdown(cash_flow))

    print(f"✓ wrote {out_path}")
    print(f"✓ wrote cash-flow report under {run_dir}")
    for app, entry in revenue["by_app"].items():
        rev = entry.get("monthly_revenue_usd")
        rev_s = f"${rev:.2f}" if isinstance(rev, (int, float)) else "—"
        print(f"  {app:<16} {rev_s:>10}  source={entry['source']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
