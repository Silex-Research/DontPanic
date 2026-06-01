"""Token-only command-shape validator for rendered ``exact_command`` copy.

Plan ``2026-05-24-004-feat-event-messaging-v1`` F001, Approach 2 per D012.
D008 honest-commands rule: F003's renderer must consult this validator
before populating ``RenderedEvent.exact_command``; if validation fails the
renderer sets ``exact_command = None`` and emits explanation-only copy.

D021 binds this module to a strict purity contract: it MUST NOT invoke any
``_<cmd>_main(argv)`` handler from ``cli.py`` (those parse AND execute
together — calling them would trigger real side effects: plan loader
mutations, gate state writes, subprocess dispatches, network calls). The
validator's vocabulary is a hand-curated mirror of the dispatch ladder in
``cli.py`` at lines 3105-3175 plus the per-subcommand argparse shapes the
operator-facing INBOX bodies reference. Vocabulary drift mitigation is
manual PR discipline: when a subcommand or flag lands in ``cli.py``, the
validator vocabulary update lands in the same PR.

The module also documents the ``python -m dontpanic_orchestrate`` and bare
``dontpanic`` invocation prefixes that some INBOX bodies emit — F003's
renderer strips those before calling :func:`validate_command_tokens`.

The validator has zero project-local imports and no side-effect-capable
imports (no ``subprocess``, no ``os.system``, no ``cli``, no ``supervisor``).
A purity test in the F001 test suite asserts this.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from typing import Final


@dataclasses.dataclass(frozen=True)
class ValidationResult:
    """Outcome of a token-shape validation pass.

    ``ok`` is the headline pass/fail. ``errors`` carries human-readable
    detail strings the renderer can surface for debugging — they are NOT
    user-facing copy; F003 logs them and falls back to
    ``exact_command = None``.
    """

    ok: bool
    errors: tuple[str, ...] = ()

    @property
    def reason(self) -> str:
        return "; ".join(self.errors) if self.errors else ""


@dataclasses.dataclass(frozen=True)
class SubcommandSpec:
    """Hand-curated shape declaration for one CLI subcommand.

    Mirrors the per-subcommand argparse construction in ``cli.py`` (D012
    Approach 2). Fields:

    - ``positional_min`` / ``positional_max``: count of non-flag positional
      args after the subcommand token (and after any nested-subcommand
      token, when ``subcommands`` is non-None). ``positional_max=None``
      means unbounded.
    - ``bool_flags``: flags that take no value (e.g. ``--all``).
    - ``value_flags``: flags that take exactly one value-token
      (e.g. ``--reason <CLASS>``).
    - ``required_flags``: subset of ``bool_flags | value_flags`` that MUST
      appear in the token sequence.
    - ``mutex_required``: tuple of flag-groups; for each group, at least
      one flag from the group MUST appear. Mirrors argparse's
      ``add_mutually_exclusive_group(required=True)`` shape — used by
      ``resume`` where exactly one of ``--gate`` / ``--all`` is required.
      The validator does not enforce the "exactly one" exclusivity per
      D021 (token-shape only); it enforces "at least one".
    - ``subcommands``: when non-None, the first token after this
      subcommand must be a key in this mapping; validation recurses into
      that nested spec. Used by e.g. ``quota-caps init`` and
      ``architecture regen``.
    """

    positional_min: int = 0
    positional_max: int | None = 0
    bool_flags: frozenset[str] = frozenset()
    value_flags: frozenset[str] = frozenset()
    required_flags: frozenset[str] = frozenset()
    mutex_required: tuple[frozenset[str], ...] = ()
    subcommands: Mapping[str, "SubcommandSpec"] | None = None


# ── Subcommand vocabulary (mirror of cli.py:3105-3175) ──────────────────────
#
# When a subcommand grows a new flag or arg in cli.py, update the matching
# entry below in the same PR. The validator-purity test asserts this module
# does not import cli.py — drift detection is manual PR review per D021.

_QUOTA_CAPS_SPEC = SubcommandSpec(
    subcommands={
        "init": SubcommandSpec(bool_flags=frozenset({"--overwrite"})),
        "show": SubcommandSpec(),
    },
)

# ``plan`` subcommand surfaces per cli.py:_plan_{lock,close,audit,resync}_main.
# ``lock`` accepts --ignore-sufficiency-findings <REASON> per cli.py:2040
# (operator override for blocking sufficiency findings).
_PLAN_SPEC = SubcommandSpec(
    subcommands={
        "lock": SubcommandSpec(
            positional_min=1,
            positional_max=1,
            value_flags=frozenset({"--ignore-sufficiency-findings"}),
        ),
        "close": SubcommandSpec(positional_min=1, positional_max=1),
        "audit": SubcommandSpec(positional_min=1, positional_max=1),
        "resync": SubcommandSpec(positional_min=1, positional_max=1),
    },
)

# ``architecture`` subcommands per architecture.py:_build_parser (regen,
# status, diff, hook). ``hook`` requires one of --install / --uninstall /
# --status (argparse mutex), modeled here via mutex_required.
_ARCHITECTURE_SPEC = SubcommandSpec(
    subcommands={
        "regen": SubcommandSpec(
            value_flags=frozenset({"--repo-root", "--output", "--html-output"}),
            bool_flags=frozenset({"--with-html", "--json-only"}),
        ),
        "status": SubcommandSpec(
            value_flags=frozenset({"--repo-root", "--output"}),
            bool_flags=frozenset({"--json"}),
        ),
        "diff": SubcommandSpec(
            value_flags=frozenset({"--repo-root", "--output"}),
        ),
        "hook": SubcommandSpec(
            value_flags=frozenset({"--repo-root"}),
            bool_flags=frozenset(
                {"--install", "--uninstall", "--status", "--auto-regen", "--json"}
            ),
            mutex_required=(frozenset({"--install", "--uninstall", "--status"}),),
        ),
    },
)

# ``capabilities`` subcommands per capabilities_status.py:build_parser
# (lines ~640 onward). ``status`` takes optional capability_id positional
# plus --format / --profile / --no-cache-write flags; ``setup`` mirrors
# the same surface plus guided-setup interactive flags.
_CAPABILITIES_SPEC = SubcommandSpec(
    subcommands={
        "status": SubcommandSpec(
            positional_min=0,
            positional_max=1,
            value_flags=frozenset({"--format", "--profile"}),
            bool_flags=frozenset({"--no-cache-write"}),
        ),
        "setup": SubcommandSpec(
            positional_min=0,
            positional_max=1,
            value_flags=frozenset({"--format", "--profile"}),
            bool_flags=frozenset(
                {"--print-steps", "--automate-safe", "--confirm", "--no-cache-write"}
            ),
        ),
    },
)

# ``reconcile`` ships ``baseline``, ``check``, and ``homes`` per
# reconcile.py:_build_parser. ``homes`` (Plan 2026-05-30-001 F006) reconciles
# the canonical ~/.dontpanic home against the legacy ~/.jarvis home: dry-run by
# default, ``--confirm`` to migrate. operations_guidance emits
# ``reconcile homes --dry-run`` (AC7c) — bare ``reconcile`` exits 2.
_RECONCILE_SPEC = SubcommandSpec(
    subcommands={
        "baseline": SubcommandSpec(
            bool_flags=frozenset({"--yes"}),
            value_flags=frozenset({"--profile", "--format"}),
        ),
        "check": SubcommandSpec(
            value_flags=frozenset({"--area", "--format"}),
        ),
        "homes": SubcommandSpec(
            bool_flags=frozenset({"--confirm", "--dry-run"}),
            value_flags=frozenset({"--format"}),
        ),
    },
)

# ``dashboard`` subcommand flags per dashboard.py:build_parser. Body strings
# only emit `dashboard build|open|serve --project <name>`; the rest are here
# so operator-pasted ad-hoc invocations validate.
_DASHBOARD_SPEC = SubcommandSpec(
    subcommands={
        "build": SubcommandSpec(
            value_flags=frozenset(
                {"--plans-root", "--out", "--redact-level", "--plan", "--project"}
            ),
        ),
        "open": SubcommandSpec(
            value_flags=frozenset(
                {
                    "--plans-root",
                    "--out",
                    "--redact-level",
                    "--plan",
                    "--project",
                    "--dashboard-dir",
                }
            ),
            bool_flags=frozenset({"--no-launch"}),
        ),
        "serve": SubcommandSpec(
            value_flags=frozenset(
                {
                    "--host",
                    "--port",
                    "--dashboard-dir",
                    "--plans-root",
                    "--state-out",
                    "--watch-interval",
                    "--project",
                }
            ),
            bool_flags=frozenset({"--no-watch", "--once", "--allow-remote"}),
        ),
    },
)

# ``projects`` subcommand flags per cli.py:_projects_{add,list,show,remove}.
_PROJECTS_SPEC = SubcommandSpec(
    subcommands={
        "add": SubcommandSpec(
            positional_min=2,
            positional_max=2,
            value_flags=frozenset({"--implementer", "--auditor", "--notes"}),
            bool_flags=frozenset(
                {"--force", "--yes", "--init-config", "--json", "--onboard", "--dry-run"}
            ),
        ),
        "list": SubcommandSpec(bool_flags=frozenset({"--json"})),
        "show": SubcommandSpec(
            positional_min=1,
            positional_max=1,
            bool_flags=frozenset({"--json"}),
        ),
        "remove": SubcommandSpec(
            positional_min=1,
            positional_max=1,
            bool_flags=frozenset({"--yes", "--json"}),
        ),
    },
)

# ``manifest`` subcommand flags per cli.py:_manifest_{init,show}.
_MANIFEST_SPEC = SubcommandSpec(
    subcommands={
        "init": SubcommandSpec(
            value_flags=frozenset({"--cli-path", "--install-source"}),
            bool_flags=frozenset({"--force", "--yes", "--json"}),
        ),
        "show": SubcommandSpec(bool_flags=frozenset({"--json"})),
    },
)

# ``mcp`` ships ``serve`` only per mcp_server.py:main. Bare ``mcp`` returns
# exit 2 in the real CLI, so the validator requires the subcommand here too.
_MCP_SPEC = SubcommandSpec(
    subcommands={
        "serve": SubcommandSpec(),
    },
)

# ``agent`` subcommands per cli.py:_agent_main (F002). operations_guidance emits
# ``agent brief`` (the refresh-brief setup choice). ``brief`` takes only --json;
# ``status``/``setup`` take a name positional; ``register-worker`` is the guarded
# role-assignment write path.
_AGENT_SPEC = SubcommandSpec(
    subcommands={
        "brief": SubcommandSpec(bool_flags=frozenset({"--json"})),
        "status": SubcommandSpec(positional_min=0, positional_max=1),
        "setup": SubcommandSpec(positional_min=1, positional_max=1),
        "register-worker": SubcommandSpec(
            positional_min=1,
            positional_max=1,
            value_flags=frozenset({"--role"}),
            bool_flags=frozenset({"--global", "--project", "--dry-run"}),
        ),
    },
)

# ``dispatch-from-plan`` and its teaching gateway ``orchestrate`` share one
# shape: ``orchestrate`` (cli.py:_orchestrate_main) forwards its argv verbatim to
# ``_dispatch_from_plan_main``. operations_guidance emits the redispatch command
# ``orchestrate <plan> --confirm`` (AC7a), so the validator recognizes both
# spellings against the identical spec.
_DISPATCH_FROM_PLAN_SPEC = SubcommandSpec(
    positional_min=1,
    positional_max=1,
    bool_flags=frozenset({"--confirm"}),
    value_flags=frozenset(
        {
            "--feature",
            "--implementer",
            "--auditor",
            "--max-iterations",
            "--mode",
            "--allow-incomplete-patch",
            "--unrelated-dirty-state-note",
        }
    ),
)

_VOCABULARY: Final[Mapping[str, SubcommandSpec]] = {
    "ps": SubcommandSpec(),
    "approve": SubcommandSpec(
        positional_min=2,
        positional_max=2,
        bool_flags=frozenset({"--accept-non-satisfied"}),
        value_flags=frozenset({"--child"}),
    ),
    # `resume <plan>` requires exactly one of --gate / --all per
    # cli.py:514-561 (bare `resume <plan>` exits 2 with the bare-resume usage
    # message). The mutex_required group enforces "at least one"; the
    # validator is token-shape only, so "exactly one" exclusivity is left to
    # the real argparser at runtime.
    "resume": SubcommandSpec(
        positional_min=1,
        positional_max=1,
        bool_flags=frozenset({"--all"}),
        value_flags=frozenset({"--gate"}),
        mutex_required=(frozenset({"--gate", "--all"}),),
    ),
    "claude-touch": SubcommandSpec(),
    "close": SubcommandSpec(
        positional_min=2,
        positional_max=2,
        bool_flags=frozenset({"--operator-resolved", "--allow-missing-breaker"}),
        value_flags=frozenset({"--reason"}),
        required_flags=frozenset({"--operator-resolved", "--reason"}),
    ),
    "quota-caps": _QUOTA_CAPS_SPEC,
    "projects": _PROJECTS_SPEC,
    "manifest": _MANIFEST_SPEC,
    "mcp": _MCP_SPEC,
    "state": SubcommandSpec(positional_max=None),
    "plan": _PLAN_SPEC,
    "config": SubcommandSpec(positional_max=None),
    "project": SubcommandSpec(positional_max=None),
    # ``setup`` per cli.py:_setup_main (parser at cli.py:2880-2920). All
    # operator-facing fields are value-flags; --yes is the only bool.
    # Replacing the prior positional_max=None greedy-accept with the real
    # surface so bodies emitting ``setup --implementer claude`` validate.
    "setup": SubcommandSpec(
        value_flags=frozenset(
            {
                "--implementer",
                "--auditor",
                "--goal-auditor",
                "--project-dir",
                "--web-base-url",
                "--ios-scheme",
                "--ios-simulator",
                "--android-package",
                "--android-adb-device-serial",
                "--backend-provider",
                "--backend-project",
                "--backend-auth",
            }
        ),
        bool_flags=frozenset({"--yes"}),
    ),
    "calibrate-claude": SubcommandSpec(
        value_flags=frozenset({"--window", "--dashboard-pct"}),
        required_flags=frozenset({"--window", "--dashboard-pct"}),
    ),
    # ``dispatch-from-plan`` per cli.py:_dispatch_from_plan_main (parser at
    # cli.py:1707-1810). Flags: --feature, --implementer, --auditor,
    # --max-iterations, --mode, --confirm, --allow-incomplete-patch <REASON>,
    # --unrelated-dirty-state-note <REASON>. The legacy bare-dispatch flags
    # (--volley, --role, --iteration, --allow-depth, --allow-incomplete-patch-reason)
    # belong to ``python -m dontpanic_orchestrate <plan-id>`` (no subcommand
    # token), NOT to dispatch-from-plan. Removing them per the F001 audit.
    "dispatch-from-plan": _DISPATCH_FROM_PLAN_SPEC,
    # ``orchestrate`` is the teaching gateway that forwards to dispatch-from-plan
    # (cli.py:_orchestrate_main); same shape. operations_guidance's redispatch
    # command ``orchestrate <plan> --confirm`` (AC7a) validates here.
    "orchestrate": _DISPATCH_FROM_PLAN_SPEC,
    # ``finalize <plan> --feature <F>`` per cli.py:_finalize_main — --feature is
    # required. operations_guidance's no-paid finalize choice emits this (AC6).
    "finalize": SubcommandSpec(
        positional_min=1,
        positional_max=1,
        value_flags=frozenset({"--feature"}),
        required_flags=frozenset({"--feature"}),
    ),
    # ``what-now <plan> [--feature F]`` per cli.py:_what_now_main. Listed in the
    # AC6 command set; read-only guidance surface.
    "what-now": SubcommandSpec(
        positional_min=1,
        positional_max=1,
        value_flags=frozenset({"--feature", "--dashboard-url", "--format"}),
    ),
    "agent": _AGENT_SPEC,
    # ``doctor`` per cli.py:_doctor_main (parser at cli.py:1422-1520). The
    # earlier validator listed --strict, which does not exist; the real
    # promote-WARN-to-FAIL flags are --validate-plans-strict /
    # --architecture-drift-strict / --profile-strict. Adding --json plus the
    # full profile/report/validation flag surface.
    # ``--agent`` (bool) and ``--project NAME_OR_PATH`` (value) per cli.py F005
    # (cli.py:1724-1743). operations_guidance emits ``doctor --agent`` and
    # ``doctor --project <name>`` (F012 setup/doctor surface), so both must
    # validate or those choices would fall back to requires_human (AC6/AC7).
    "doctor": SubcommandSpec(
        bool_flags=frozenset(
            {
                "--json",
                "--skip-auth",
                "--validate-plans",
                "--validate-plans-strict",
                "--architecture-drift-strict",
                "--profile-strict",
                "--report",
                "--agent",
            }
        ),
        value_flags=frozenset(
            {
                "--plans-root",
                "--architecture-json",
                "--profile",
                "--report-path",
                "--project",
            }
        ),
    ),
    "init": SubcommandSpec(positional_max=None),
    "smoke": SubcommandSpec(positional_max=None),
    "architecture": _ARCHITECTURE_SPEC,
    "showcase": SubcommandSpec(positional_max=None),
    "capabilities": _CAPABILITIES_SPEC,
    "reconcile": _RECONCILE_SPEC,
    "dashboard": _DASHBOARD_SPEC,
    # ``next`` per cli.py:_next_main (parser at cli.py:2960-3020). Flags:
    # --scope (choice), --plans-root <path>, --max-parallel <int>,
    # --format (text|json), --include-not-ready (bool, default True),
    # --ready-only (bool, suppresses not-ready). Earlier validator was a
    # bare SubcommandSpec — rejected ``next --format json`` per F001 audit.
    "next": SubcommandSpec(
        value_flags=frozenset(
            {"--scope", "--plans-root", "--max-parallel", "--format"}
        ),
        bool_flags=frozenset({"--include-not-ready", "--ready-only"}),
    ),
}


def known_subcommands() -> frozenset[str]:
    """Return the top-level subcommand vocabulary (read-only snapshot)."""
    return frozenset(_VOCABULARY.keys())


def _is_flag(token: str) -> bool:
    # ``--`` alone is the argparse end-of-flags sentinel; treat as not-a-flag
    # so positional counting catches it as an unexpected positional.
    return token.startswith("-") and token != "--"


def _validate_spec(
    spec: SubcommandSpec,
    tokens: list[str],
    *,
    prog_path: list[str],
) -> ValidationResult:
    """Recursive shape check for a single spec against the remaining tokens."""
    prog = " ".join(prog_path) or "<empty>"
    errors: list[str] = []

    # Nested-subcommand dispatch: first token must be a known sub-key.
    if spec.subcommands is not None:
        if not tokens:
            return ValidationResult(
                ok=False,
                errors=(
                    f"{prog} requires a subcommand "
                    f"(one of {sorted(spec.subcommands)})",
                ),
            )
        sub = tokens[0]
        if sub not in spec.subcommands:
            return ValidationResult(
                ok=False,
                errors=(
                    f"{prog} subcommand {sub!r} not in "
                    f"{sorted(spec.subcommands)}",
                ),
            )
        return _validate_spec(
            spec.subcommands[sub],
            tokens[1:],
            prog_path=[*prog_path, sub],
        )

    positionals: list[str] = []
    seen_flags: set[str] = set()
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if _is_flag(tok):
            if tok in spec.bool_flags:
                seen_flags.add(tok)
                i += 1
                continue
            if tok in spec.value_flags:
                seen_flags.add(tok)
                if i + 1 >= len(tokens):
                    errors.append(f"{prog} flag {tok!r} requires a value")
                    i += 1
                    continue
                # Consume the value token. Even another flag-shaped token is
                # accepted as the value — argparse does the same.
                i += 2
                continue
            errors.append(
                f"{prog} unknown flag {tok!r}; "
                f"allowed: {sorted(spec.bool_flags | spec.value_flags) or '(none)'}"
            )
            i += 1
            continue
        positionals.append(tok)
        i += 1

    if len(positionals) < spec.positional_min:
        errors.append(
            f"{prog} expected at least {spec.positional_min} positional arg(s); "
            f"got {len(positionals)}"
        )
    if spec.positional_max is not None and len(positionals) > spec.positional_max:
        errors.append(
            f"{prog} expected at most {spec.positional_max} positional arg(s); "
            f"got {len(positionals)}"
        )

    missing_required = spec.required_flags - seen_flags
    if missing_required:
        errors.append(
            f"{prog} missing required flag(s): {sorted(missing_required)}"
        )

    for mutex_group in spec.mutex_required:
        if not (seen_flags & mutex_group):
            errors.append(
                f"{prog} requires one of: {sorted(mutex_group)}"
            )

    return ValidationResult(ok=not errors, errors=tuple(errors))


# Plan 2026-05-02-003 F003 — the `approve <plan> pre_resume_after_child` gate
# is routed by cli.py:245 to a *different* argparser than the regular two-arg
# approve. Validating it with the generic approve spec would let bodies omit
# `--child` and slip through; mirror cli.py's gate-form dispatch here.
_PRE_RESUME_AFTER_CHILD_SPEC: Final[SubcommandSpec] = SubcommandSpec(
    positional_min=2,
    positional_max=2,
    bool_flags=frozenset({"--accept-non-satisfied"}),
    value_flags=frozenset({"--child"}),
    required_flags=frozenset({"--child"}),
)

# Bare-suffix form `approve <plan> pre_resume_after_child:CHILD` is refused
# at cli.py:247-258 — the operator must go through the validating
# `--child <child>` form. The validator mirrors that refusal so bodies
# carrying the bare-suffix form never render an exact_command.
_PRE_RESUME_BARE_SUFFIX: Final[str] = "pre_resume_after_child:"


def validate_command_tokens(tokens: list[str]) -> ValidationResult:
    """Validate that ``tokens`` is a well-formed ``dontpanic`` invocation.

    ``tokens`` is the post-``dontpanic`` argv list — e.g.
    ``["approve", "<plan>", "<gate>"]`` for the body string
    ``dontpanic approve <plan> <gate>``. F003's renderer strips any
    ``python -m dontpanic_orchestrate`` or bare ``dontpanic`` prefix before
    calling this function.

    Per D021 this is a pure token-shape check. The validator NEVER imports
    or invokes ``cli._<cmd>_main`` handlers — those parse and execute
    together; calling them would trigger real side effects (plan loader
    mutations, gate state writes, subprocess dispatches).

    Returns a :class:`ValidationResult`. F003 should treat ``ok=False`` as
    "render ``exact_command = None`` with explanation-only copy" per D008.
    """
    if not tokens:
        return ValidationResult(ok=False, errors=("empty command token list",))
    cmd = tokens[0]

    # Plan 2026-05-02-003 F003 gate-form dispatch — `approve <plan>
    # pre_resume_after_child` routes to a parser that REQUIRES `--child`
    # (cli.py:245). Validating it under the generic approve spec would let
    # the body omit --child and render a broken command.
    if cmd == "approve" and len(tokens) >= 3:
        gate_token = tokens[2]
        if gate_token == "pre_resume_after_child":
            return _validate_spec(
                _PRE_RESUME_AFTER_CHILD_SPEC,
                tokens[1:],
                prog_path=["approve"],
            )
        if gate_token.startswith(_PRE_RESUME_BARE_SUFFIX):
            return ValidationResult(
                ok=False,
                errors=(
                    f"approve gate {gate_token!r} uses the bare-suffix form "
                    f"(refused at cli.py:247); use `approve <plan> "
                    f"pre_resume_after_child --child <child_plan_id> "
                    f"[--accept-non-satisfied]` instead",
                ),
            )

    spec = _VOCABULARY.get(cmd)
    if spec is None:
        return ValidationResult(
            ok=False,
            errors=(
                f"unknown subcommand {cmd!r}; "
                f"known: {sorted(_VOCABULARY)}",
            ),
        )
    return _validate_spec(spec, tokens[1:], prog_path=[cmd])
