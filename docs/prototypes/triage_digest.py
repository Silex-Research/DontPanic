#!/usr/bin/env python3
"""PROTOTYPE — the triage digest an agent operator reads and narrates.

Reads the REAL fleet what-now (~/.dontpanic/dashboard/fleet-what-now.json) and
sorts every item into five buckets, so the human sees only what needs THEM and
the agent gets an actionable list for everything else. Throwaway; not wired in.
"""
from __future__ import annotations
import json, os, sys
from collections import defaultdict

HOME = os.path.expanduser("~/.dontpanic/dashboard/fleet-what-now.json")

def bucket(it: dict) -> str:
    band = it.get("band")
    if band in ("info", "advisory"):
        return "quiet"                       # never shown by default
    rc = it.get("resolution_class")
    title = (it.get("title") or "").lower()
    if rc == "operator_attested":
        return "you_auth"                    # needs your credentials
    if "approval" in title or title.startswith("gate ") or "gate " in title:
        return "you_decide"                  # needs your judgment
    if it.get("automatable") is True:
        return "auto"                        # DontPanic runs it, unattended
    if rc == "command_resolvable":
        return "agent"                       # your agent operator can run it
    return "you_decide"                      # unknown → fail closed to human

def main() -> int:
    d = json.load(open(HOME))
    items = d.get("items", [])
    by = defaultdict(list)
    for it in items:
        by[bucket(it)].append(it)

    def cmds(key, n=99):
        return [(i.get("title"), i.get("exact_command")) for i in by[key][:n]]

    print(f"TRIAGE of {len(items)} fleet items\n" + "=" * 48)
    print(f"  YOU must authenticate : {len(by['you_auth'])}")
    print(f"  YOU must decide       : {len(by['you_decide'])}")
    print(f"  Agent can run for you : {len(by['agent'])}")
    print(f"  DontPanic auto-runs   : {len(by['auto'])}")
    print(f"  Hidden (info/advisory): {len(by['quiet'])}")
    human = len(by['you_auth']) + len(by['you_decide'])
    print(f"\n  >>> The human sees {human} of {len(items)} items "
          f"({100*human//max(len(items),1)}%). The rest is handled.\n")

    print("── WHAT NEEDS YOU ──")
    for title, cmd in cmds("you_auth") + cmds("you_decide"):
        print(f"  • {title}")
        if cmd: print(f"      → {cmd}")
    print("\n── WHAT YOUR AGENT WOULD RUN (sample of "
          f"{len(by['agent'])}) ──")
    seen = set()
    for title, cmd in cmds("agent"):
        key = cmd or title
        if key in seen: continue
        seen.add(key)
        if len(seen) > 6: break
        print(f"  • {cmd or title}")
    print(f"\n── DontPanic AUTO-RUNS unattended ({len(by['auto'])}) ──")
    seen = set()
    for title, cmd in cmds("auto"):
        key = cmd or title
        if key in seen: continue
        seen.add(key)
        if len(seen) > 5: break
        print(f"  • {cmd or title}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
