"""Plan 2026-05-19-002 F002 — Walker fixture tests.

>=10 cases covering each acceptance bullet from features.json#F002:

  (1) all-pass path exits 0 with no prompts
  (2) fail probe with auto_install_safe=True triggers per-probe prompt
      + executes via subprocess.run(argv: list[str], shell=False)
  (3) fail probe with auto_install_safe=False prompts copy-paste in
      interactive mode + reports structurally in non-interactive mode
  (4) --non-interactive exits 1 with JSON listing all fail+warn probes
  (5) idempotent re-run picks up new probe results without state file
  (6) shell-string fix_command raises validator error at STARTUP
      (not at exec time)
  (7) operator-aborted prompt exits with code 130
  (8) advisory items surface in output but NEVER prompt
  (9) Walker() (no flags) defaults to --profile=core
  (10) per-probe operator decline allows the loop to continue

Run:
    pytest scripts/dontpanic_orchestrate/tests/test_init_walker_f002.py -q
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from dontpanic_orchestrate import prereq_registry as pr
from dontpanic_orchestrate.init import (
    DEFAULT_PROFILE,
    EXIT_ABORTED,
    EXIT_BLOCKED,
    EXIT_READY,
    EXIT_REMAINING,
    RegistryValidationError,
    WalkResult,
    Walker,
    render_walk_json,
    render_walk_text,
    validate_registry,
)


# ── synthetic probe factory ──────────────────────────────────────────────


def _passing_probe(name: str = "synthetic-pass") -> pr.PrereqProbe:
    return pr.PrereqProbe(
        name=name,
        probe_command=lambda: (True, f"{name} ok"),
        version_constraint=None,
        fix_url="https://example.test/" + name,
        fix_command=["echo", f"fix-{name}"],
        auto_install_safe=False,
        why_needed=f"why {name}",
        required_for_profiles=frozenset({"core"}),
        activation_condition=pr.ActivationCondition.ALWAYS,
        severity_when_inactive=pr.SeverityWhenInactive.OMIT,
    )


def _failing_probe(
    name: str = "synthetic-fail",
    *,
    auto_install_safe: bool = False,
    fix_command: list[str] | None = None,
) -> pr.PrereqProbe:
    return pr.PrereqProbe(
        name=name,
        probe_command=lambda: (False, f"{name} fail"),
        version_constraint=None,
        fix_url="https://example.test/" + name,
        fix_command=fix_command if fix_command is not None else ["true"],
        auto_install_safe=auto_install_safe,
        why_needed=f"why {name}",
        required_for_profiles=frozenset({"core"}),
        activation_condition=pr.ActivationCondition.ALWAYS,
        severity_when_inactive=pr.SeverityWhenInactive.OMIT,
    )


def _advisory_probe(name: str = "synthetic-advisory") -> pr.PrereqProbe:
    """An out-of-profile advisory: probe is required_for={ci}; when run
    under --profile=core with auditor_codex_selected=False (default), the
    matrix surfaces it as ADVISORY (not omit). Mirrors codex-cli."""
    return pr.PrereqProbe(
        name=name,
        probe_command=lambda: (False, f"{name} missing"),
        version_constraint=None,
        fix_url="https://example.test/" + name,
        fix_command=["echo", "advisory-fix"],
        auto_install_safe=False,
        why_needed=f"why {name}",
        required_for_profiles=frozenset({"ci"}),
        activation_condition=pr.ActivationCondition.AUDITOR_CODEX_SELECTED,
        severity_when_inactive=pr.SeverityWhenInactive.ADVISORY,
    )


@pytest.fixture()
def all_false_activation() -> pr.ActivationContext:
    """Stable activation context — no github remote, no codex, no
    firebase target. Keeps the activation matrix deterministic across
    tests so codex-style advisory probes stay advisory."""
    return pr.ActivationContext(
        repo_root=Path("/tmp"),
        github_remote_present=False,
        auditor_codex_selected=False,
        dispatch_requires_push=False,
        firebase_target_set=False,
    )


# ── (1) all-pass path exits 0 with no prompts ─────────────────────────────


def test_all_pass_path_exits_zero_with_no_prompts(all_false_activation) -> None:
    probes = [_passing_probe("p1"), _passing_probe("p2")]
    prompts: list[str] = []
    outputs: list[str] = []

    def _prompt(q: str) -> str:
        prompts.append(q)
        return ""

    walker = Walker(
        profile="core",
        probes=probes,
        prompt_fn=_prompt,
        output_fn=outputs.append,
        activation_context=all_false_activation,
    )
    result = walker.run()
    assert result.exit_code() == EXIT_READY
    assert prompts == [], "all-pass path must not prompt"
    assert not result.actions


# ── (2) fail + auto_install_safe=True triggers prompt + argv exec ────────


def test_fail_auto_install_safe_uses_strict_argv_subprocess(
    all_false_activation,
) -> None:
    """The single most important contract: when the operator confirms
    a fix, the walker invokes ``subprocess.run`` with the argv list
    UNCHANGED, ``shell=False``, and NEVER joins the argv into a shell
    string. Mocked subprocess_runner records each call so we can assert
    the exact kwargs."""

    fix_argv = ["brew", "install", "jq"]
    probe = _failing_probe(
        "jq-missing", auto_install_safe=True, fix_command=fix_argv
    )

    seen_calls: list[dict[str, Any]] = []

    def _fake_run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess:
        seen_calls.append({"args": args, "kwargs": kwargs})
        return subprocess.CompletedProcess(
            args=args[0] if args else kwargs.get("args"),
            returncode=0,
            stdout="installed",
            stderr="",
        )

    walker = Walker(
        profile="core",
        probes=[probe],
        prompt_fn=lambda q: "y",
        output_fn=lambda _l: None,
        subprocess_runner=_fake_run,
        activation_context=all_false_activation,
    )
    result = walker.run()

    assert len(seen_calls) == 1, "auto-fix must invoke subprocess exactly once"
    call = seen_calls[0]
    # argv MUST be a list[str] passed positionally — not a joined string.
    assert call["args"][0] == fix_argv
    assert isinstance(call["args"][0], list)
    assert all(isinstance(s, str) for s in call["args"][0])
    # shell=False is the strict-argv invariant.
    assert call["kwargs"]["shell"] is False
    # No "shell" key with truthy value anywhere.
    assert all(
        not (k == "shell" and v is True) for k, v in call["kwargs"].items()
    )
    assert result.actions[0].decision == "ran"
    assert result.actions[0].fix_command == fix_argv


# ── (3) fail + auto_install_safe=False — copy-paste in interactive ───────


def test_fail_auto_install_safe_false_uses_copy_paste_prompt(
    all_false_activation,
) -> None:
    probe = _failing_probe(
        "manual-fix", auto_install_safe=False, fix_command=["gh", "auth", "login"]
    )

    prompts: list[str] = []

    def _prompt(q: str) -> str:
        prompts.append(q)
        return ""  # Enter

    def _fake_run(*_args: Any, **_kw: Any) -> subprocess.CompletedProcess:
        raise AssertionError(
            "subprocess.run must NOT be invoked for auto_install_safe=False probes"
        )

    walker = Walker(
        profile="core",
        probes=[probe],
        prompt_fn=_prompt,
        output_fn=lambda _l: None,
        subprocess_runner=_fake_run,
        activation_context=all_false_activation,
    )
    result = walker.run()
    # We expect a "Press Enter" copy-paste prompt; never the [Y/n] prompt.
    assert any("Press Enter" in p for p in prompts), prompts
    assert all("[Y/n]" not in p for p in prompts), prompts
    assert result.actions[0].decision == "manual_acknowledged"


def test_fail_auto_install_safe_false_reports_structurally_in_non_interactive(
    all_false_activation,
) -> None:
    """Acceptance #3 (the non-interactive half): a fail probe whose
    fix is NOT auto-install-safe is still surfaced in the JSON envelope
    so an agent installer can read it and act."""

    probe = _failing_probe(
        "manual-fix-2",
        auto_install_safe=False,
        fix_command=["gh", "auth", "login"],
    )
    walker = Walker(
        profile="core",
        probes=[probe],
        non_interactive=True,
        prompt_fn=lambda q: "",
        output_fn=lambda _l: None,
        activation_context=all_false_activation,
    )
    result = walker.run()
    envelope = json.loads(render_walk_json(result))
    names = [p["name"] for p in envelope["fail_warn_probes"]]
    assert "manual-fix-2" in names
    assert envelope["exit_code"] == EXIT_REMAINING
    assert envelope["mode"] == "non_interactive"


# ── (4) --non-interactive exits 1 with structured JSON ───────────────────


def test_non_interactive_exits_one_with_json_listing_fail_probes(
    all_false_activation,
) -> None:
    probes = [
        _passing_probe("ok-1"),
        _failing_probe("bad-1", auto_install_safe=True, fix_command=["true"]),
        _failing_probe("bad-2", auto_install_safe=False, fix_command=["false"]),
    ]
    walker = Walker(
        profile="core",
        probes=probes,
        non_interactive=True,
        prompt_fn=lambda q: pytest.fail(
            "non-interactive must not prompt; got " + repr(q)
        ),
        output_fn=lambda _l: None,
        activation_context=all_false_activation,
    )
    result = walker.run()
    assert result.exit_code() == EXIT_REMAINING

    envelope = json.loads(render_walk_json(result))
    assert envelope["mode"] == "non_interactive"
    assert envelope["exit_code"] == EXIT_REMAINING
    names = {p["name"] for p in envelope["fail_warn_probes"]}
    assert {"bad-1", "bad-2"} <= names
    # Each fail+warn probe carries its fix_command as a list[str].
    for p in envelope["fail_warn_probes"]:
        assert isinstance(p["fix_command"], list)
        assert all(isinstance(s, str) for s in p["fix_command"])


def test_non_interactive_all_pass_exits_zero(all_false_activation) -> None:
    walker = Walker(
        profile="core",
        probes=[_passing_probe()],
        non_interactive=True,
        prompt_fn=lambda q: pytest.fail("must not prompt"),
        output_fn=lambda _l: None,
        activation_context=all_false_activation,
    )
    result = walker.run()
    assert result.exit_code() == EXIT_READY


# ── (5) idempotent re-run picks up new probe results without state file ──


def test_idempotent_re_run_picks_up_new_probe_results(
    all_false_activation, tmp_path
) -> None:
    """The walker MUST NOT persist any state between runs — each
    invocation calls ProbeRunner fresh. Simulated by toggling a probe's
    pass/fail flip between two Walker instantiations and asserting the
    second one observes the new result without any state-file plumbing.
    """

    # Use a mutable flag that the probe callable reads; the second
    # Walker should see the new value automatically.
    state = {"pass": False}

    def _toggleable() -> tuple[bool, str]:
        return state["pass"], "ok" if state["pass"] else "fail"

    probe = pr.PrereqProbe(
        name="toggleable",
        probe_command=_toggleable,
        version_constraint=None,
        fix_url="https://example.test/toggleable",
        fix_command=["true"],
        auto_install_safe=True,
        why_needed="x",
        required_for_profiles=frozenset({"core"}),
        activation_condition=pr.ActivationCondition.ALWAYS,
        severity_when_inactive=pr.SeverityWhenInactive.OMIT,
    )

    # First invocation: probe fails. Walker (non-interactive) reports it.
    walker_a = Walker(
        profile="core",
        probes=[probe],
        non_interactive=True,
        prompt_fn=lambda q: "",
        output_fn=lambda _l: None,
        activation_context=all_false_activation,
    )
    result_a = walker_a.run()
    assert result_a.exit_code() == EXIT_REMAINING

    # Operator "fixes" the underlying environment between runs.
    state["pass"] = True

    # Second invocation: walker MUST see the new probe result without
    # ever consulting a state file (none exists). Assert no state file
    # was written under tmp_path.
    walker_b = Walker(
        profile="core",
        probes=[probe],
        non_interactive=True,
        prompt_fn=lambda q: "",
        output_fn=lambda _l: None,
        activation_context=all_false_activation,
    )
    result_b = walker_b.run()
    assert result_b.exit_code() == EXIT_READY

    # No state file written anywhere under the dontpanic init namespace.
    # We use tmp_path as a sentinel — if the walker ever introduced a
    # state file it would naturally land here under cwd-based logic.
    assert list(tmp_path.iterdir()) == []


# ── (6) shell-string fix_command raises validator error at STARTUP ──────


def test_shell_string_fix_command_rejected_at_dataclass_construction() -> None:
    """``PrereqProbe.__post_init__`` is the first guard rail; the
    walker validator below is the second. This test pins the first."""
    with pytest.raises(ValueError, match="fix_command must be list"):
        pr.PrereqProbe(
            name="shell-string",
            probe_command=lambda: (False, "x"),
            version_constraint=None,
            fix_url="https://example.test",
            fix_command="brew install jq && gh auth login",  # type: ignore[arg-type]
            auto_install_safe=True,
            why_needed="x",
            required_for_profiles=frozenset({"core"}),
            activation_condition=pr.ActivationCondition.ALWAYS,
            severity_when_inactive=pr.SeverityWhenInactive.OMIT,
        )


def test_walker_validate_registry_rejects_shell_string_at_startup() -> None:
    """Second guard rail: even if a probe were smuggled in with a bad
    fix_command (e.g. via direct __dict__ mutation), the walker
    validator must fail at STARTUP, NOT exec time."""

    probe = _failing_probe(
        "boobytrap", auto_install_safe=True, fix_command=["true"]
    )
    # Bypass the dataclass invariant via object.__setattr__ on a frozen
    # dataclass so we can exercise the standalone validator.
    object.__setattr__(
        probe, "fix_command", "brew install jq && gh auth login"
    )
    with pytest.raises(RegistryValidationError, match="strict argv allowlist"):
        validate_registry([probe])

    # The Walker __init__ must also fail fast.
    with pytest.raises(RegistryValidationError):
        Walker(
            profile="core",
            probes=[probe],
            prompt_fn=lambda q: "",
            output_fn=lambda _l: None,
        )


# ── (7) operator-aborted prompt exits with code 130 ─────────────────────


def test_operator_aborted_prompt_exits_130(all_false_activation) -> None:
    probe = _failing_probe(
        "abort-me", auto_install_safe=True, fix_command=["true"]
    )

    def _prompt(_q: str) -> str:
        raise KeyboardInterrupt

    walker = Walker(
        profile="core",
        probes=[probe],
        prompt_fn=_prompt,
        output_fn=lambda _l: None,
        activation_context=all_false_activation,
    )
    result = walker.run()
    assert result.aborted is True
    assert result.exit_code() == EXIT_ABORTED


# ── (8) advisory items NEVER prompt ─────────────────────────────────────


def test_advisory_probes_never_prompt(all_false_activation) -> None:
    """An advisory probe (e.g. codex-cli under --profile=core when
    auditor_codex_selected=False) surfaces in output but the walker
    MUST NOT prompt for it."""

    advisory = _advisory_probe("codex-style-advisory")
    prompted: list[str] = []

    def _prompt(q: str) -> str:
        prompted.append(q)
        return ""

    walker = Walker(
        profile="core",
        probes=[advisory],
        prompt_fn=_prompt,
        output_fn=lambda _l: None,
        activation_context=all_false_activation,
    )
    result = walker.run()
    assert prompted == [], (
        "advisory items must never prompt the operator; got prompts: "
        + repr(prompted)
    )
    # The advisory probe appears in the sweep but is not a fail/warn,
    # so the walker exits cleanly.
    assert result.exit_code() == EXIT_READY


# ── (9) Walker() (no args) defaults to --profile=core ───────────────────


def test_walker_defaults_to_profile_core() -> None:
    """The walker constructor default IS the contract — init_main()
    relies on argparse defaulting --profile to 'core' and the walker
    accepting that exact string. Pin both halves."""
    walker = Walker(
        probes=[_passing_probe()],
        prompt_fn=lambda q: "",
        output_fn=lambda _l: None,
    )
    assert walker.profile == "core"
    assert DEFAULT_PROFILE == "core"


# ── (10) per-probe operator decline allows the loop to continue ─────────


def test_per_probe_decline_continues_loop(all_false_activation) -> None:
    # Probe results render alphabetically by ProbeRunner — name them so
    # "a-…" is the declined one and "b-…" is the executed one.
    probe_a = _failing_probe(
        "a-decline-me", auto_install_safe=True, fix_command=["true"]
    )
    probe_b = _failing_probe(
        "b-run-me", auto_install_safe=True, fix_command=["true"]
    )

    answers = iter(["n", "y"])
    seen_runs: list[list[str]] = []

    def _prompt(_q: str) -> str:
        return next(answers)

    def _fake_run(*args: Any, **_kw: Any) -> subprocess.CompletedProcess:
        seen_runs.append(args[0])
        return subprocess.CompletedProcess(
            args=args[0], returncode=0, stdout="ok", stderr=""
        )

    walker = Walker(
        profile="core",
        probes=[probe_a, probe_b],
        prompt_fn=_prompt,
        output_fn=lambda _l: None,
        subprocess_runner=_fake_run,
        activation_context=all_false_activation,
    )
    result = walker.run()
    # Exactly one execution — the declined probe must NOT exec.
    assert len(seen_runs) == 1
    assert seen_runs[0] == ["true"]
    decisions = {a.probe_name: a.decision for a in result.actions}
    assert decisions == {"a-decline-me": "declined", "b-run-me": "ran"}


# ── (11) bonus: render_walk_text + JSON shape pinned ────────────────────


def test_render_walk_text_contains_profile_and_exit_code(
    all_false_activation,
) -> None:
    walker = Walker(
        profile="core",
        probes=[_passing_probe()],
        prompt_fn=lambda q: "",
        output_fn=lambda _l: None,
        activation_context=all_false_activation,
    )
    result = walker.run()
    text = render_walk_text(result)
    assert "profile=core" in text
    assert "exit_code=" in text


# ── (12) auditor F002-i0 finding #1: interactive remaining = EXIT 1 ─────


def test_interactive_remaining_fail_returns_exit_code_one_not_two(
    all_false_activation,
) -> None:
    """Auditor F002-i0 finding #1: an interactive walk that ends with a
    remaining FAIL probe MUST return EXIT_REMAINING (1), NOT 2.

    Background: ``pr.SweepResult.exit_code()`` returns the doctor's
    strict 0/1/2 matrix where FAIL maps to 2. The walker reserves
    exit code 2 for unrecoverable startup errors (invalid registry)
    and must collapse all remaining fail/warn to EXIT_REMAINING=1."""

    # Probe whose probe_command stays failing across the re-sweep. We
    # decline its auto-fix prompt so the FAIL remains after the walk.
    probe = _failing_probe(
        "stuck-fail", auto_install_safe=True, fix_command=["true"]
    )

    walker = Walker(
        profile="core",
        probes=[probe],
        prompt_fn=lambda _q: "n",  # decline; FAIL remains
        output_fn=lambda _l: None,
        activation_context=all_false_activation,
    )
    result = walker.run()
    assert result.exit_code() == EXIT_REMAINING, (
        f"interactive remaining FAIL must map to EXIT_REMAINING=1, got "
        f"{result.exit_code()}"
    )
    # Sanity: EXIT_REMAINING is 1 and EXIT_BLOCKED is 2.
    assert EXIT_REMAINING == 1
    assert EXIT_BLOCKED == 2


# ── (13) auditor F002-i0 finding #2: advisory surfaces as info ──────────


def test_advisory_probe_surfaces_in_walker_output(all_false_activation) -> None:
    """Auditor F002-i0 finding #2: advisory probes must appear in the
    interactive output as info (non-blocking, non-prompting). Before
    this fix, advisory items were silently skipped — the operator
    saw "all probes green" even when an advisory item was present."""

    advisory = _advisory_probe("codex-style-advisory")
    outputs: list[str] = []
    prompts: list[str] = []

    walker = Walker(
        profile="core",
        probes=[advisory],
        prompt_fn=lambda q: prompts.append(q) or "",
        output_fn=outputs.append,
        activation_context=all_false_activation,
    )
    result = walker.run()

    # No prompts for advisory items.
    assert prompts == []
    # Output must mention the advisory probe's name + the [advisory]
    # marker so a human reader sees it.
    combined = "\n".join(outputs)
    assert "advisory" in combined.lower()
    assert "codex-style-advisory" in combined
    # Exit is still READY (advisory is non-blocking).
    assert result.exit_code() == EXIT_READY


def test_render_walk_text_includes_advisory_section(all_false_activation) -> None:
    """The text renderer (used outside the live walk for end-of-run
    summaries + non-interactive output) must also surface advisory
    items so the JSON/text outputs stay consistent."""

    advisory = _advisory_probe("text-render-advisory")
    walker = Walker(
        profile="core",
        probes=[advisory],
        prompt_fn=lambda q: "",
        output_fn=lambda _l: None,
        activation_context=all_false_activation,
    )
    result = walker.run()
    text = render_walk_text(result)
    assert "text-render-advisory" in text
    assert "advisory" in text.lower()


def test_per_probe_recheck_skips_prompt_when_prior_action_incidentally_clears_probe(
    all_false_activation,
) -> None:
    """F002-i1 medium/correctness hand-patch (Walker per-probe recheck).

    When the operator confirms probe A's auto-fix and that fix incidentally
    flips probe B from FAIL to PASS as a side effect, the walker MUST NOT
    prompt the operator about probe B with its stale initial result.
    Walker re-sweeps after every action and consults the fresh sweep
    before deciding whether to prompt the next probe in the loop.
    """
    # Shared cross-probe state — toggled by probe-A's auto-fix exec.
    state = {"both_fixed": False}

    def _probe_a_command() -> tuple[bool, str]:
        return (state["both_fixed"], "A: ok" if state["both_fixed"] else "A: fail")

    def _probe_b_command() -> tuple[bool, str]:
        return (state["both_fixed"], "B: ok" if state["both_fixed"] else "B: fail")

    probe_a = pr.PrereqProbe(
        name="probe-a",
        probe_command=_probe_a_command,
        version_constraint=None,
        fix_url="https://example.test/a",
        fix_command=["echo", "fix-a"],
        auto_install_safe=True,
        why_needed="needed",
        required_for_profiles=frozenset({"core"}),
        activation_condition=pr.ActivationCondition.ALWAYS,
        severity_when_inactive=pr.SeverityWhenInactive.OMIT,
    )
    probe_b = pr.PrereqProbe(
        name="probe-b",
        probe_command=_probe_b_command,
        version_constraint=None,
        fix_url="https://example.test/b",
        fix_command=["echo", "fix-b"],
        auto_install_safe=True,
        why_needed="needed",
        required_for_profiles=frozenset({"core"}),
        activation_condition=pr.ActivationCondition.ALWAYS,
        severity_when_inactive=pr.SeverityWhenInactive.OMIT,
    )

    # A-fix flips the shared state — B's probe_command then returns True.
    def _fake_run(argv: list[str], **_kw: Any) -> subprocess.CompletedProcess:
        if argv == ["echo", "fix-a"]:
            state["both_fixed"] = True
        return subprocess.CompletedProcess(args=argv, returncode=0, stdout="", stderr="")

    prompts: list[str] = []

    def _prompt(q: str) -> str:
        prompts.append(q)
        return "y"  # always confirm

    walker = Walker(
        profile="core",
        probes=[probe_a, probe_b],
        prompt_fn=_prompt,
        output_fn=lambda _l: None,
        subprocess_runner=_fake_run,
        activation_context=all_false_activation,
    )
    result = walker.run()

    # Exactly one [Y/n] prompt — for probe-a. probe-b was incidentally
    # cleared by probe-a's auto-fix and re-sweep saw it pass.
    yn_prompts = [p for p in prompts if "[Y/n]" in p]
    assert len(yn_prompts) == 1, (
        f"expected exactly 1 auto-fix prompt; got {len(yn_prompts)}: {yn_prompts!r}"
    )
    assert "probe-a" in yn_prompts[0] or "fix-a" in yn_prompts[0]
    # Only probe-a should have an action recorded; probe-b was skipped
    # because the re-sweep showed it now passing.
    assert [a.probe_name for a in result.actions] == ["probe-a"]
    # Final sweep is clean.
    assert result.exit_code() == EXIT_READY


def test_render_walk_json_carries_schema_version(all_false_activation) -> None:
    walker = Walker(
        profile="core",
        probes=[_failing_probe(auto_install_safe=False)],
        non_interactive=True,
        prompt_fn=lambda q: "",
        output_fn=lambda _l: None,
        activation_context=all_false_activation,
    )
    payload = json.loads(render_walk_json(walker.run()))
    assert payload["schema_version"] == "1.0.0"
    assert payload["profile"] == "core"
    assert payload["mode"] == "non_interactive"
    assert "fail_warn_probes" in payload
    assert "actions" in payload
