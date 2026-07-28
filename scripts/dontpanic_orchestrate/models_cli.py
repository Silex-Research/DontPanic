"""Plan 2026-07-27-001 F015 — ``dontpanic models`` CLI (model catalog).

Subcommands: ``list`` / ``aliases``. The catalog is DATA, never
``AGENT_REGISTRY`` keys (D010): discovery covers what a harness can see
today (``ollama list``, the OpenRouter models API with an offline-safe
cache), while registered pass-through harnesses (claude / codex) accept
any freeform model string and forward it to the vendor CLI unchanged.

Exit codes: 0 success (including a documented pass-through), 2 usage /
unknown harness, 1 catalog unavailable (binary missing, offline with no
cache).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_USAGE = """dontpanic models — model catalog discovery + aliases (Track D4)

  list --harness <id> [--refresh] [--json]
      Discover the model catalog for a harness. Discoverable today:
      ollama (`ollama list`, local) and openrouter (models API, cached
      offline-safe under ~/.dontpanic/cache/models/; --refresh forces a
      re-fetch). Registered harnesses without a discovery surface
      (claude, codex) are documented pass-through: any freeform model
      string is forwarded to the harness CLI unchanged — a new model
      version never requires a code change.
  aliases [--project NAME|PATH] [--json]
      Show the merged model_aliases table (global config overlaid by the
      project layer, project wins per key). Aliases resolve single-hop:
      alias -> vendor model id, never alias -> alias.

Set a model freeform via `dontpanic workers set <id> model <M>` or the
roles-level model config; `dontpanic doctor` warns when a configured
model is unknown to its harness catalog and fails only when the harness
probe itself rejects it."""


def _resolve_project_path(project_arg: str | None) -> Path | None:
    """--project NAME|PATH → project root (None with a message on failure);
    absent --project means cwd, mirroring ``workers list``."""
    from dontpanic_orchestrate import project_config as _pc

    if project_arg is None:
        return Path.cwd().resolve()
    resolved = _pc.resolve_project_path(project_arg)
    if resolved is None:
        return None
    return resolved[0]


def models_main(argv: list[str]) -> int:
    """``dontpanic models <subcommand>`` entry point."""
    from dontpanic_orchestrate import model_catalog as mc

    if argv and argv[0] in ("-h", "--help", "help"):
        print(_USAGE)
        return 0
    if not argv:
        print(_USAGE, file=sys.stderr)
        return 2

    sub, rest = argv[0], argv[1:]

    if sub == "list":
        parser = argparse.ArgumentParser(prog="dontpanic models list", add_help=True)
        parser.add_argument(
            "--harness",
            required=True,
            help=f"Harness id ({', '.join(mc.known_catalog_harnesses())}; D015 aliases accepted)",
        )
        parser.add_argument(
            "--refresh",
            action="store_true",
            help="Bypass the offline cache where discovery uses the network (openrouter)",
        )
        parser.add_argument("--json", action="store_true", dest="as_json")
        args = parser.parse_args(rest)
        try:
            catalog = mc.get_catalog(args.harness, refresh=args.refresh)
        except mc.UnknownHarnessError as exc:
            print(f"[models list] {exc}", file=sys.stderr)
            return 2
        except mc.CatalogUnavailableError as exc:
            print(f"[models list] catalog unavailable: {exc}", file=sys.stderr)
            return 1
        if args.as_json:
            print(
                json.dumps(
                    {
                        "harness": catalog.harness,
                        "source": catalog.source,
                        "models": list(catalog.models) if catalog.models is not None else None,
                        "stale": catalog.stale,
                        "detail": catalog.detail,
                    },
                    indent=2,
                    ensure_ascii=False,
                )
            )
            return 0
        if catalog.models is None:
            print(f"harness {catalog.harness}: pass-through (no model discovery surface)")
            print(f"  {catalog.detail}")
            return 0
        stale_note = "  (stale cache — refresh online with --refresh)" if catalog.stale else ""
        print(
            f"harness {catalog.harness}: {len(catalog.models)} models via {catalog.source}{stale_note}"
        )
        for m in catalog.models:
            print(f"  - {m}")
        if catalog.detail:
            print(f"  note: {catalog.detail}")
        return 0

    if sub == "aliases":
        parser = argparse.ArgumentParser(prog="dontpanic models aliases", add_help=True)
        parser.add_argument("--project", default=None)
        parser.add_argument("--json", action="store_true", dest="as_json")
        args = parser.parse_args(rest)
        project_path = _resolve_project_path(args.project)
        if project_path is None:
            print(
                f"[models aliases] could not resolve --project {args.project!r}",
                file=sys.stderr,
            )
            return 2
        aliases = mc.load_model_aliases(project_path)
        if args.as_json:
            print(
                json.dumps({"model_aliases": aliases}, indent=2, ensure_ascii=False, sort_keys=True)
            )
            return 0
        print("DontPanic model aliases (global overlaid by project; single-hop)")
        print("")
        if not aliases:
            print("  (none defined)")
            print("")
            print('Define one in config: "model_aliases": {"sonnet": "claude-sonnet-5"}')
        else:
            width = max(len(k) for k in aliases)
            for key in sorted(aliases):
                print(f"  {key.ljust(width)} -> {aliases[key]}")
        return 0

    print(f"[models] unknown subcommand: {sub!r}", file=sys.stderr)
    print(_USAGE, file=sys.stderr)
    return 2


__all__ = ["models_main"]
