#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "anthropic>=0.40.0",
#   "google-cloud-firestore>=2.16.0",
#   "google-cloud-logging>=3.10.0",
#   "google-cloud-monitoring>=2.21.0",
# ]
# ///
"""
Daily digest runner — cron entry point.

Runs one session per configured app with a standard daily-digest prompt.
Designed to be called by cron (e.g. 6 AM ET weekdays):

    0 11 * * 1-5 /path/to/run_product_health.sh --mode digest

Outputs a summary to stdout suitable for email/Slack forwarding, plus
writes structured insights to Firestore for dashboard display.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import anthropic

SKILL_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SKILL_DIR))
from orchestrator import load_config, load_state, run_session  # noqa: E402


DIGEST_PROMPT_TEMPLATE = """Daily digest for {app} — {date_iso}.

Review the last 24 hours of activity and operational health. Your output should answer:

1. **Engagement**: What did users do most? Which features are getting the most traffic?
2. **Operational health**: What's broken or degrading? Error rates, failing functions, anomalies.
3. **Cost / scale**: Any unusual spend patterns or traffic spikes?
4. **Top 3-5 findings** ranked by user impact.

Follow this workflow:

1. Call `get_function_invocation_stats` with since_hours=24 to see which services had traffic
   and their 2xx/4xx/5xx breakdown. Functions with elevated 5xx or unusually high 4xx rates are
   candidates for deeper investigation.

{glam_hint}

3. For any function showing elevated error rates, call `get_function_errors` to sample actual
   error messages. Then grep the repo at /workspace/{workspace_repo} for the function name or
   error string to find the code.

4. Use `get_firestore_counts` on the main user-facing collections to verify data is being
   written at expected rates. Unusual drops or spikes are worth flagging.

5. Write every real finding via `write_insight`. Include file:line references from your grep
   of the mounted repo as `evidence`. Always recommend concrete next steps.

6. At the end, output a plain-text summary listing every insight you wrote with severity and
   title, and a one-sentence overall health verdict (HEALTHY | DEGRADED | INCIDENT).

Be concise in prose — the insights are the artifact. Don't pad the summary."""


GLAM_HINT = """2. For Glam, also call `get_daily_usage_metrics(app="glam", days=7)` to pull pre-aggregated
   extractions, try-ons, cost, and DAU. Look for week-over-week regressions. Check `get_alerts`
   for any warnings the app's own monitoring already raised."""

SPINDINE_HINT = """2. For SpinDine there's no pre-aggregated usage_metrics collection, so use
   `get_firestore_counts` with collections=["users", "favorites", "sessions"] (or similar) to
   sample write volume directly. Also query `search_logs` for user-facing operational patterns."""


def digest_prompt(app: str) -> str:
    hint = GLAM_HINT if app == "glam" else SPINDINE_HINT
    workspace_repo = {"glam": "glam", "spindine": "spindine"}[app]
    return DIGEST_PROMPT_TEMPLATE.format(
        app=app,
        date_iso=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        glam_hint=hint,
        workspace_repo=workspace_repo,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run daily product-health digest")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument(
        "--apps",
        nargs="+",
        default=None,
        help="Which apps to run. Defaults to all configured apps.",
    )
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    config = load_config(args.config)
    state = load_state()
    client = anthropic.Anthropic()

    apps_to_run = args.apps if args.apps else sorted(config["apps"].keys())

    overall_start = time.time()
    all_results = []

    for app in apps_to_run:
        if app not in config["apps"]:
            print(f"[skip] unknown app '{app}' — not in config", file=sys.stderr)
            continue

        print(f"\n{'=' * 60}\n== DIGEST: {app}\n{'=' * 60}", flush=True)
        start = time.time()
        try:
            summary = run_session(
                client=client,
                config=config,
                state=state,
                prompt=digest_prompt(app),
                title=f"{app} daily digest {datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
                verbose=not args.quiet,
            )
            summary["app"] = app
            summary["elapsed_s"] = round(time.time() - start, 1)
            all_results.append(summary)
        except Exception as e:
            print(f"[error] {app} digest failed: {e}", file=sys.stderr)
            all_results.append({"app": app, "error": str(e)})

    # Final roll-up
    total_elapsed = time.time() - overall_start
    print(f"\n\n{'#' * 60}")
    print(f"# Daily digest complete — {total_elapsed:.1f}s total")
    print(f"{'#' * 60}")
    for r in all_results:
        if "error" in r:
            print(f"\n[{r['app']}] FAILED: {r['error']}")
            continue
        print(f"\n[{r['app']}] {r['elapsed_s']}s, {r['tool_calls']} tool calls, {len(r['insights_written'])} insights")
        for ins in r["insights_written"]:
            print(f"  · [{ins['severity']:8}] {ins['category']:20} {ins['title']}")

    failed = [r for r in all_results if "error" in r]
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
