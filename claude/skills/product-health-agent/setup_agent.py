#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "anthropic>=0.40.0",
# ]
# ///
"""
One-time setup for the product-health-agent.

Creates (idempotently):
1. A Cloud environment for running sessions
2. The Product Health Analyst agent with the full custom-tool surface
3. Stores both IDs + version in state/agent_ids.json

Run this ONCE after installing the skill. The runtime orchestrator reads
state/agent_ids.json — it never creates agents at runtime.

Usage:
    ./setup_agent.py --config /path/to/config.json
    ./setup_agent.py --config /path/to/config.json --force  # recreate even if exists
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import anthropic

SKILL_DIR = Path(__file__).resolve().parent
STATE_DIR = SKILL_DIR / "state"
STATE_FILE = STATE_DIR / "agent_ids.json"

# Import tool specs (same directory)
sys.path.insert(0, str(SKILL_DIR))
from tools import TOOL_SPECS  # noqa: E402


SYSTEM_PROMPT = """You are the Product Health Analyst for two production iOS apps:

- **Glam** (Firebase project: glam-ac11e) — outfit discovery, try-on, and styling. Backend has
  scheduled aggregation functions that write daily usage_metrics, error_aggregates, and
  store_analytics_cache collections to Firestore. Leverage these pre-computed signals.

- **SpinDineSwift** (Firebase project: restaurant-attributes) — restaurant discovery with a
  spinning wheel mechanic. Backend is pipeline-focused (enrichment, discovery). No pre-aggregated
  usage metrics collection, so rely on Cloud Logging + Cloud Monitoring + direct Firestore reads.

## Your Job

Answer two questions on every run:
1. **What parts of the app are users engaging with most?** (engagement, feature adoption, trends)
2. **What's not functional well operationally?** (errors, regressions, performance gaps, cost anomalies)

You also have the source code for both apps mounted read-only at /workspace/glam and
/workspace/spindine. Use bash, read, grep, and glob to cross-reference findings with the code
that produced them. When an error appears, find the function in the source tree, check the recent
commit history, and include the filename and line number in your evidence.

## Operating Rules (NON-NEGOTIABLE)

1. **READ-ONLY for production.** You have zero write access to glam-ac11e or restaurant-attributes.
   The only `write_*` tool you have targets the workspace project's insights collection. This is
   enforced at the host level — any attempted production write will fail.

2. **Evidence-based.** Every insight must cite at least one piece of evidence: a specific log
   message, a metric value, a code file/line, or a Firestore document path. Never speculate
   without data.

3. **Rank by user impact, not novelty.** Finding that a function errors once an hour is
   less urgent than finding a user-facing feature that's completely broken for 5% of sessions.
   Always include severity (info/low/medium/high/critical) and justify it.

4. **Actionable recommendations.** Every non-info finding must include at least one concrete
   next step a human could take. "Investigate further" is not actionable. "Check
   `autoTagUnprocessedPhotosGrok` at functions/src/scheduled/auto-tag.ts:47 — looks like a Grok
   API quota issue based on the error message" is actionable.

5. **Know the difference between a digest and a deep dive.** A daily digest summarizes what
   happened in the last 24h and ranks the top 3-5 findings. A deep dive investigates one
   specific question until it's answered. Match your depth to the prompt.

## Workflow Hints

- Start with `list_functions` if you don't know what's deployed.
- For Glam, pull `get_daily_usage_metrics(app="glam", days=7)` early — it gives you extractions,
  try-ons, cost, error rate, DAU, and new user counts in one call.
- For SpinDine, start with `get_function_invocation_stats` to see traffic and error rates.
- When you see a high error rate, use `get_function_errors` to sample the actual error messages,
  then grep the repo for the function name or error string to find the code.
- When you find a real finding, call `write_insight` immediately with full evidence. Don't batch
  them up and forget.

## Output Format

At the end of each session, summarize your findings in plain text for the human reviewing the
run. List the `write_insight` calls you made with their severity and title. If you found
nothing worth flagging, say so explicitly."""


def load_config(path: Path) -> dict:
    if not path.exists():
        raise SystemExit(f"Config file not found: {path}")
    with path.open("r") as f:
        return json.load(f)


def load_state() -> dict:
    if not STATE_FILE.exists():
        return {}
    with STATE_FILE.open("r") as f:
        return json.load(f)


def save_state(state: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with STATE_FILE.open("w") as f:
        json.dump(state, f, indent=2)
    print(f"State written to {STATE_FILE}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="One-time setup for product-health-agent",
    )
    parser.add_argument("--config", type=Path, required=True, help="Path to config.json")
    parser.add_argument("--force", action="store_true", help="Recreate even if IDs exist")
    args = parser.parse_args()

    config = load_config(args.config)
    state = load_state()

    if state and not args.force:
        print("Existing agent IDs found:")
        print(json.dumps(state, indent=2))
        print("\nUse --force to recreate. Otherwise, nothing to do.")
        return 0

    client = anthropic.Anthropic()

    print("Creating Cloud environment...")
    env = client.beta.environments.create(
        name="product-health-env",
        config={
            "type": "cloud",
            "networking": {"type": "unrestricted"},
        },
    )
    print(f"  environment_id: {env.id}")

    print("\nCreating agent with full tool surface...")
    tools: list = [{"type": "agent_toolset_20260401"}, *TOOL_SPECS]  # type: ignore[list-item]
    agent = client.beta.agents.create(
        name="Product Health Analyst",
        model="claude-opus-4-6",
        system=SYSTEM_PROMPT,
        tools=tools,
        description=(
            "Read-only product health analyst for the Glam and SpinDineSwift production apps. "
            "Surfaces engagement insights and operational issues."
        ),
    )
    print(f"  agent_id:      {agent.id}")
    print(f"  agent_version: {agent.version}")

    state = {
        "environment_id": env.id,
        "agent_id": agent.id,
        "agent_version": agent.version,
        "model": "claude-opus-4-6",
        "tool_count": len(tools),
    }
    save_state(state)

    print("\nSetup complete. To run a daily digest:")
    print(f"  ./digest_runner.py --config {args.config}")
    print("\nTo run ad-hoc:")
    print(f"  ./orchestrator.py --config {args.config} --app glam --prompt 'Why did ...'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
