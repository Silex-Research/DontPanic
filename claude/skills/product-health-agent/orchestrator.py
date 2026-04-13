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
Runtime orchestrator for the product-health-agent.

Reads persisted agent IDs, opens a session, sends a user message, streams
events, dispatches custom tool calls to tools.py, and prints the agent's
response. Supports ad-hoc prompts and tracks results.

Host-side credentials (Firestore, Cloud Logging, Cloud Monitoring) stay here
and are accessed only via the dispatch() call — never shipped to the managed
container.

Usage:
    ./orchestrator.py --config config.json --app glam --prompt "Summarize last 24h"
    ./orchestrator.py --config config.json --app spindine --prompt "Investigate nearbyrestaurantssimple errors"
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
STATE_FILE = SKILL_DIR / "state" / "agent_ids.json"

# Import tool dispatch from sibling module
sys.path.insert(0, str(SKILL_DIR))
from tools import dispatch  # noqa: E402


def load_config(path: Path) -> dict:
    if not path.exists():
        raise SystemExit(f"Config file not found: {path}")
    with path.open("r") as f:
        return json.load(f)


def load_state() -> dict:
    if not STATE_FILE.exists():
        raise SystemExit(
            f"Agent state not found at {STATE_FILE}\n"
            "Run setup_agent.py first."
        )
    with STATE_FILE.open("r") as f:
        return json.load(f)


def run_session(
    client: anthropic.Anthropic,
    config: dict,
    state: dict,
    prompt: str,
    title: str,
    verbose: bool = True,
) -> dict:
    """Open a session, send the prompt, stream events, dispatch custom tools."""
    session = client.beta.sessions.create(
        agent=state["agent_id"],
        environment_id=state["environment_id"],
        title=title,
    )
    if verbose:
        print(f"[session] id={session.id} title={title!r}")
        print(f"[session] agent={state['agent_id']} env={state['environment_id']}")
        print()

    insights_written: list[dict] = []
    tool_calls_total = 0
    agent_text_parts: list[str] = []

    # Stream-first: open the stream, then send the kickoff message.
    # Note: stream lives under sessions.events (not sessions directly).
    with client.beta.sessions.events.stream(session_id=session.id) as stream:
        client.beta.sessions.events.send(
            session_id=session.id,
            events=[{
                "type": "user.message",
                "content": [{"type": "text", "text": prompt}],
            }],
        )

        for event in stream:
            etype = getattr(event, "type", None)

            if etype == "agent.message":
                for block in getattr(event, "content", []) or []:
                    btype = getattr(block, "type", None)
                    if btype == "text":
                        txt = getattr(block, "text", "") or ""
                        agent_text_parts.append(txt)
                        if verbose:
                            print(txt, end="", flush=True)

            elif etype == "agent.custom_tool_use":
                tool_name = getattr(event, "tool_name", None) or getattr(event, "name", None)
                tool_input = getattr(event, "input", {}) or {}
                tool_use_id = getattr(event, "id", None)
                tool_calls_total += 1

                if verbose:
                    print(
                        f"\n[tool] {tool_name}({json.dumps(tool_input)[:200]})",
                        flush=True,
                    )

                result = dispatch(tool_name, tool_input, config)

                # Track write_insight results so we can summarize at the end
                if tool_name == "write_insight" and isinstance(result, dict) and result.get("written"):
                    insights_written.append({
                        "severity": tool_input.get("severity"),
                        "category": tool_input.get("category"),
                        "title": tool_input.get("title"),
                        "path": result.get("path"),
                    })

                # Truncate long results before sending back so the agent's context
                # doesn't explode on giant log dumps
                result_json = json.dumps(result, default=str)
                if len(result_json) > 12000:
                    truncated = {
                        "_truncated": True,
                        "_note": f"Original result was {len(result_json)} chars, truncated to keep context lean.",
                    }
                    if isinstance(result, dict):
                        # Preserve top-level metadata if possible
                        for k in ("app", "project", "count", "filter", "error"):
                            if k in result:
                                truncated[k] = result[k]
                        if "entries" in result and isinstance(result["entries"], list):
                            truncated["entries"] = result["entries"][:20]
                        elif "rows" in result and isinstance(result["rows"], list):
                            truncated["rows"] = result["rows"][:20]
                        elif "services" in result and isinstance(result["services"], list):
                            truncated["services"] = result["services"][:30]
                    result_json = json.dumps(truncated, default=str)

                client.beta.sessions.events.send(
                    session_id=session.id,
                    events=[{
                        "type": "user.custom_tool_result",
                        "custom_tool_use_id": tool_use_id,
                        "content": [{"type": "text", "text": result_json}],
                    }],
                )

            elif etype == "session.status_terminated":
                if verbose:
                    print("\n[session] terminated", flush=True)
                break

            elif etype == "session.status_idle":
                stop_reason = getattr(event, "stop_reason", None)
                reason_type = getattr(stop_reason, "type", None) if stop_reason else None
                if reason_type == "requires_action":
                    # Waiting on a pending tool call — keep streaming
                    continue
                if verbose:
                    print(f"\n[session] idle (stop_reason={reason_type})", flush=True)
                break

            elif etype == "session.error":
                err = getattr(event, "error", None) or {}
                print(f"\n[session] ERROR: {err}", file=sys.stderr, flush=True)

    return {
        "session_id": session.id,
        "tool_calls": tool_calls_total,
        "insights_written": insights_written,
        "text_chars": sum(len(p) for p in agent_text_parts),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the product-health-agent ad hoc")
    parser.add_argument("--config", type=Path, required=True, help="Path to config.json")
    parser.add_argument("--app", choices=["glam", "spindine"], required=True)
    parser.add_argument("--prompt", type=str, required=True, help="The question to ask the agent")
    parser.add_argument("--title", type=str, default=None, help="Session title (optional)")
    parser.add_argument("--quiet", action="store_true", help="Don't stream output to stdout")
    args = parser.parse_args()

    config = load_config(args.config)
    state = load_state()
    client = anthropic.Anthropic()

    title = args.title or f"{args.app} ad-hoc {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}"
    start = time.time()

    summary = run_session(
        client=client,
        config=config,
        state=state,
        prompt=args.prompt,
        title=title,
        verbose=not args.quiet,
    )

    elapsed = time.time() - start
    print("\n" + "=" * 60)
    print(f"Session complete in {elapsed:.1f}s")
    print(f"Tool calls:       {summary['tool_calls']}")
    print(f"Insights written: {len(summary['insights_written'])}")
    for ins in summary["insights_written"]:
        print(f"  [{ins['severity']}] {ins['category']}: {ins['title']}")
        print(f"    → {ins['path']}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
