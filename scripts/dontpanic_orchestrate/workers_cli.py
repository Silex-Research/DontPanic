"""Plan 2026-07-27-001 F013 — ``dontpanic workers`` CLI (worker profiles).

Subcommands: ``list`` / ``add`` / ``set`` / ``show``. Profiles are the
Track D2 agent cards ({display_name, harness, model, allowed_roles,
capability overrides}); they live under ``worker_profiles.<id>`` in the
global config (default scope) or the per-project config (``--project``).

Exit codes follow the roles-CLI convention: 0 success, 2 usage / could
not resolve, 3 refusal (invalid profile — unknown harness, capability
widening, un-holdable allowed role, shadowed harness name). Refusals
happen BEFORE any config write.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from pydantic import ValidationError

_USAGE = """dontpanic workers — named worker profiles (harness + model + allowed roles)

  list [--project NAME|PATH] [--json]
      List defined profiles (global overlaid by project) with harness,
      model, allowed roles, and validity.
  add <id> --harness <harness> [--model M] [--display-name N]
      [--roles r1,r2] [--cap flag=false ...] [--global | --project NAME|PATH]
      Create a profile. --cap sets a capability override (file_edit /
      tool_use / non_interactive; repeatable) — overrides can only
      RESTRICT the harness, never widen it. Refuses unknown harnesses,
      ids that shadow a harness name, and role/capability combinations
      that can never dispatch (exit 3) — nothing is written on refusal.
  set <id> <field> <value> [--global | --project NAME|PATH]
      Update one field: harness | model | display_name | allowed_roles
      (comma-separated) | capabilities (comma-separated flag=bool pairs,
      e.g. "file_edit=false,tool_use=false"; "none" clears overrides).
      Same validation as add.
  show <id> [--project NAME|PATH] [--json]
      Show one profile: effective capabilities, holdable roles, and the
      role slots that currently resolve to it.
  buzz-bindings [--project NAME|PATH] [--json]
      Show the optional F016 Buzz agent → profile bindings from
      buzz.json ``agent_bindings`` (off by default). Display-only:
      Buzz agent → profile → harness + model. Bindings never grant
      dispatch; unbound Buzz agents gain nothing.

Assign a profile to a role slot with:  dontpanic roles set <role> <id>
Legacy harness names (claude / codex) stay valid role values."""

_SETTABLE_FIELDS = ("harness", "model", "display_name", "allowed_roles", "capabilities")


class _UsageError(ValueError):
    """Operator input could not be parsed (exit 2, nothing written)."""


def _parse_capability_pairs(pairs: list[str]) -> dict[str, bool] | None:
    """Parse ``flag=true|false`` tokens into a capabilities dict. ``none``
    (alone) clears the overrides. Unknown flags and malformed pairs raise
    :class:`_UsageError` — validation against the harness (narrow-only)
    happens later in validate_profile."""
    from dontpanic_orchestrate.config.worker_profiles import CAPABILITY_FLAGS

    if pairs == ["none"]:
        return None
    caps: dict[str, bool] = {}
    for pair in pairs:
        flag, sep, value = pair.partition("=")
        flag = flag.strip()
        value = value.strip().lower()
        if not sep or flag not in CAPABILITY_FLAGS or value not in ("true", "false"):
            raise _UsageError(
                f"capability override {pair!r} must be <flag>=true|false with flag in "
                f"{list(CAPABILITY_FLAGS)} (or the single token 'none' to clear)"
            )
        caps[flag] = value == "true"
    return caps


def _resolve_scope(project_arg: str | None):
    """Resolve --project to a role_assignment.ProjectScope (None on failure).
    Absent --project on read commands means cwd-project-or-cwd, mirroring
    ``roles show``."""
    from dontpanic_orchestrate import project_config as _pc
    from dontpanic_orchestrate import role_assignment as _ra

    if project_arg is None:
        cwd = Path.cwd().resolve()
        match = _pc.find_project_for_plan_dir(cwd)
        if match is not None:
            return _ra.ProjectScope(path=match[0], name=match[1])
        return _ra.ProjectScope(path=cwd, name=None)
    resolved = _pc.resolve_project_path(project_arg)
    if resolved is None:
        return None
    path, name = resolved
    return _ra.ProjectScope(path=path, name=name)


def _read_config_raw(is_global: bool, project_path: Path | None) -> tuple[dict[str, Any], Path]:
    """Read the target config JSON for a profile write. Mirrors the
    cli_helpers dotted-key writers: global config may not exist yet
    (created on write); the project config must exist (init first)."""
    from dontpanic_orchestrate import global_config as gc
    from dontpanic_orchestrate import project_config as pc
    from dontpanic_orchestrate.config.cli_helpers import InvalidKeyError

    if is_global:
        path = gc.config_path()
        raw = json.loads(path.read_text() or "{}") if path.is_file() else {}
        return raw, path
    if project_path is None:
        raise InvalidKeyError("project scope requires a resolved project path")
    path = pc.project_config_path(project_path)
    if not path.is_file():
        raise InvalidKeyError(
            f"per-project config does not exist at {path}; "
            "run `dontpanic project config init` first"
        )
    return json.loads(path.read_text() or "{}"), path


def _write_global_raw(raw: dict[str, Any]) -> Path:
    from dontpanic_orchestrate import global_config as gc
    from dontpanic_orchestrate.config.cli_helpers import InvalidKeyError

    try:
        gc.GlobalConfig.model_validate(raw)
    except ValidationError as exc:
        raise InvalidKeyError(f"invalid config write: {exc.errors()}") from exc
    home = gc.ensure_dontpanic_home()
    out = home / gc.CONFIG_FILENAME
    out.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n")
    return out


def _write_project_raw(raw: dict[str, Any], project_path: Path) -> Path:
    from dontpanic_orchestrate import project_config as pc
    from dontpanic_orchestrate.config.cli_helpers import InvalidKeyError

    try:
        pc.ProjectConfig.model_validate(raw)
    except ValidationError as exc:
        raise InvalidKeyError(f"invalid project config write: {exc.errors()}") from exc
    path = pc.project_config_path(project_path)
    path.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n")
    return path


def _profile_payload(profile_id: str, profile, scope) -> dict[str, Any]:
    """JSON-friendly projection of one profile with derived facts."""
    from dontpanic_orchestrate import worker_profiles as wp
    from dontpanic_orchestrate.config.worker_profiles import effective_capabilities

    problems = wp.validate_profile(profile_id, profile)
    payload: dict[str, Any] = {
        "id": profile_id,
        "display_name": profile.display_name,
        "harness": profile.harness,
        "model": profile.model,
        "allowed_roles": profile.allowed_roles,
        "effective_capabilities": sorted(effective_capabilities(profile)),
        "holdable_roles": wp.holdable_roles(profile_id, profile),
        "valid": not problems,
        "problems": problems,
    }
    if scope is not None:
        from dontpanic_orchestrate import role_assignment as _ra

        payload["assigned_role_slots"] = [
            r.role for r in _ra.resolve_all(scope) if r.value == profile_id
        ]
    return payload


def _render_profile_lines(payload: dict[str, Any]) -> list[str]:
    roles = payload["allowed_roles"]
    lines = [
        f"  - {payload['id']}"
        + (f" ({payload['display_name']})" if payload["display_name"] else ""),
        f"      harness: {payload['harness']}",
        f"      model:   {payload['model'] or '(harness default)'}",
        f"      allowed_roles: {', '.join(roles) if roles else '(all)'}",
        f"      holdable_roles: {', '.join(payload['holdable_roles']) or '(none)'}",
    ]
    if payload.get("assigned_role_slots"):
        lines.append(f"      assigned to: {', '.join(payload['assigned_role_slots'])}")
    if not payload["valid"]:
        lines.append("      INVALID:")
        lines.extend(f"        - {p}" for p in payload["problems"])
    return lines


def _mutation_parser(prog: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=prog, add_help=True)
    target = parser.add_mutually_exclusive_group()
    target.add_argument(
        "--global",
        action="store_true",
        dest="is_global",
        help="Write ~/.dontpanic/config.json worker_profiles.* (default scope)",
    )
    target.add_argument(
        "--project",
        default=None,
        help="Write <repo>/.dontpanic/dontpanic.json worker_profiles.* (NAME or PATH)",
    )
    return parser


def _apply_profile_write(
    profile_id: str,
    profile_dict: dict[str, Any],
    *,
    is_global: bool,
    project_arg: str | None,
    verb: str,
) -> int:
    """Shared add/set tail: validate (schema + F013 gates) then write."""
    from dontpanic_orchestrate import worker_profiles as wp
    from dontpanic_orchestrate.config.cli_helpers import InvalidKeyError
    from dontpanic_orchestrate.config.worker_profiles import WorkerProfile

    try:
        profile = WorkerProfile.model_validate(profile_dict)
    except ValidationError as exc:
        print(f"[workers {verb}] REFUSED: invalid profile: {exc.errors()}", file=sys.stderr)
        return 3

    problems = wp.validate_profile(profile_id, profile)
    if problems:
        print(f"[workers {verb}] REFUSED — profile {profile_id!r} is invalid:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 3

    scope_path: Path | None = None
    if not is_global:
        scope = _resolve_scope(project_arg)
        if scope is None:
            print(
                f"[workers {verb}] could not resolve --project {project_arg!r} to a "
                "registered project or an existing directory",
                file=sys.stderr,
            )
            return 2
        scope_path = scope.path

    try:
        raw, _ = _read_config_raw(is_global, scope_path)
        block = raw.setdefault("worker_profiles", {})
        block[profile_id] = profile.model_dump(exclude_none=True)
        if is_global:
            path = _write_global_raw(raw)
        elif scope_path is not None:
            path = _write_project_raw(raw, scope_path)
        else:  # unreachable: scope resolution failed earlier with exit 2
            raise InvalidKeyError("project scope requires a resolved project path")
    except InvalidKeyError as exc:
        print(f"[workers {verb}] REFUSED: {exc}", file=sys.stderr)
        return 3

    scope_label = "global" if is_global else "project"
    print(
        f"[workers {verb}] wrote worker_profiles.{profile_id} "
        f"(harness={profile.harness}, model={profile.model or '(harness default)'}, "
        f"allowed_roles={profile.allowed_roles or '(all)'}) ({scope_label}: {path})"
    )
    return 0


def workers_main(argv: list[str]) -> int:
    """``dontpanic workers <subcommand>`` entry point."""
    from dontpanic_orchestrate import worker_profiles as wp

    if argv and argv[0] in ("-h", "--help", "help"):
        print(_USAGE)
        return 0
    if not argv:
        print(_USAGE, file=sys.stderr)
        return 2

    sub, rest = argv[0], argv[1:]

    if sub == "list":
        parser = argparse.ArgumentParser(prog="dontpanic workers list", add_help=True)
        parser.add_argument("--project", default=None)
        parser.add_argument("--json", action="store_true", dest="as_json")
        args = parser.parse_args(rest)
        scope = _resolve_scope(args.project)
        if scope is None:
            print(
                f"[workers list] could not resolve --project {args.project!r}",
                file=sys.stderr,
            )
            return 2
        profiles = wp.load_profiles(scope.path)
        payloads = [
            _profile_payload(pid, profile, scope) for pid, profile in sorted(profiles.items())
        ]
        if args.as_json:
            print(json.dumps({"worker_profiles": payloads}, indent=2, ensure_ascii=False))
            return 0
        print("DontPanic worker profiles")
        print("")
        if not payloads:
            print("  (none defined)")
            print("")
            print(
                "Create one:  dontpanic workers add <id> --harness <claude|codex> [--model M] [--roles r1,r2]"
            )
        else:
            for payload in payloads:
                for line in _render_profile_lines(payload):
                    print(line)
        return 0

    if sub == "show":
        parser = argparse.ArgumentParser(prog="dontpanic workers show", add_help=True)
        parser.add_argument("id")
        parser.add_argument("--project", default=None)
        parser.add_argument("--json", action="store_true", dest="as_json")
        args = parser.parse_args(rest)
        scope = _resolve_scope(args.project)
        if scope is None:
            print(
                f"[workers show] could not resolve --project {args.project!r}",
                file=sys.stderr,
            )
            return 2
        profile = wp.load_profiles(scope.path).get(args.id)
        if profile is None:
            print(f"[workers show] no worker profile named {args.id!r}", file=sys.stderr)
            return 2
        payload = _profile_payload(args.id, profile, scope)
        if args.as_json:
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        else:
            print("DontPanic worker profile")
            print("")
            for line in _render_profile_lines(payload):
                print(line)
        return 0

    if sub == "buzz-bindings":
        from dontpanic_orchestrate import buzz_bindings as bb

        parser = argparse.ArgumentParser(prog="dontpanic workers buzz-bindings", add_help=True)
        parser.add_argument("--project", default=None)
        parser.add_argument("--json", action="store_true", dest="as_json")
        args = parser.parse_args(rest)
        scope = _resolve_scope(args.project)
        if scope is None:
            print(
                f"[workers buzz-bindings] could not resolve --project {args.project!r}",
                file=sys.stderr,
            )
            return 2
        rows = bb.resolve_agent_bindings(project_path=scope.path)
        if args.as_json:
            print(
                json.dumps(
                    {"agent_bindings": bb.binding_payloads(rows)},
                    indent=2,
                    ensure_ascii=False,
                )
            )
            return 0
        print("Buzz agent bindings (buzz.json agent_bindings)")
        print("")
        if not rows:
            print("  (none configured — feature off by default)")
            print("")
            print(
                f"Bind a Buzz agent to a worker profile by adding to {bb.bindings_config_path()}:"
            )
            print('  "agent_bindings": { "<buzz agent id or display name>": "<profile id>" }')
        else:
            for row in rows:
                if row.bound:
                    label = f" ({row.display_name})" if row.display_name else ""
                    print(
                        f"  - {row.buzz_agent} -> {row.profile_id}{label}  "
                        f"harness={row.harness}, model={row.model or '(harness default)'}"
                    )
                else:
                    print(f"  - {row.buzz_agent} -> {row.profile_id}  UNBOUND")
                    print(f"      {row.problem}")
        print("")
        print(
            "Display-only: bindings never grant dispatch — Buzz stays the membership/UX "
            "surface, DontPanic roles/profiles stay the dispatch authority (F007 "
            "confirm-gated caller required for any Buzz-initiated run)."
        )
        return 0

    if sub == "add":
        parser = _mutation_parser("dontpanic workers add")
        parser.add_argument("id", help="Profile id (lowercase slug, e.g. honey)")
        parser.add_argument("--harness", required=True, help="Registered harness (claude|codex)")
        parser.add_argument("--model", default=None, help="Vendor model-id override")
        parser.add_argument("--display-name", default=None, dest="display_name")
        parser.add_argument(
            "--roles",
            default=None,
            help="Comma-separated allowed roles (default: all roles)",
        )
        parser.add_argument(
            "--cap",
            action="append",
            default=None,
            dest="caps",
            metavar="FLAG=BOOL",
            help="Capability override (file_edit|tool_use|non_interactive)=true|false; "
            "repeatable. Overrides restrict the harness, never widen it.",
        )
        args = parser.parse_args(rest)
        try:
            capabilities = _parse_capability_pairs(args.caps) if args.caps else None
        except _UsageError as exc:
            print(f"[workers add] {exc}", file=sys.stderr)
            return 2
        profile_dict: dict[str, Any] = {
            "harness": args.harness,
            "model": args.model,
            "display_name": args.display_name,
            "allowed_roles": (
                [r.strip() for r in args.roles.split(",") if r.strip()]
                if args.roles is not None
                else None
            ),
            "capabilities": capabilities,
        }
        return _apply_profile_write(
            args.id,
            profile_dict,
            is_global=args.is_global or args.project is None,
            project_arg=args.project,
            verb="add",
        )

    if sub == "set":
        parser = _mutation_parser("dontpanic workers set")
        parser.add_argument("id")
        parser.add_argument("field", choices=list(_SETTABLE_FIELDS))
        parser.add_argument("value")
        args = parser.parse_args(rest)
        is_global = args.is_global or args.project is None
        # Load the CURRENT profile from the target scope's own layer so a
        # `set` mutates what add wrote there, not the merged view.
        scope_path: Path | None = None
        if not is_global:
            scope = _resolve_scope(args.project)
            if scope is None:
                print(
                    f"[workers set] could not resolve --project {args.project!r}",
                    file=sys.stderr,
                )
                return 2
            scope_path = scope.path
        try:
            raw, _ = _read_config_raw(is_global, scope_path)
        except Exception as exc:  # InvalidKeyError (missing project config)
            print(f"[workers set] REFUSED: {exc}", file=sys.stderr)
            return 3
        existing = (raw.get("worker_profiles") or {}).get(args.id)
        if existing is None:
            scope_label = "global" if is_global else "project"
            print(
                f"[workers set] no worker profile {args.id!r} in the {scope_label} "
                "config; create it with `dontpanic workers add` first",
                file=sys.stderr,
            )
            return 2
        value: Any = args.value
        if args.field == "allowed_roles":
            value = [r.strip() for r in args.value.split(",") if r.strip()] or None
        elif args.field == "capabilities":
            try:
                value = _parse_capability_pairs(
                    [p.strip() for p in args.value.split(",") if p.strip()]
                )
            except _UsageError as exc:
                print(f"[workers set] {exc}", file=sys.stderr)
                return 2
        profile_dict = {**existing, args.field: value}
        return _apply_profile_write(
            args.id,
            profile_dict,
            is_global=is_global,
            project_arg=args.project,
            verb="set",
        )

    print(f"[workers] unknown subcommand: {sub!r}", file=sys.stderr)
    print(_USAGE, file=sys.stderr)
    return 2


__all__ = ["workers_main"]
