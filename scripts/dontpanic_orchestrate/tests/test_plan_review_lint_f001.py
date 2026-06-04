"""F001 — scope-signal lint core.

Reproduces each of the three onboarding-v0 stall classes (multi-surface F007,
exemplar-AC F008, missing-prereq + weak-test F012) and asserts the matching
lint flag fires, with negatives proving no false-positive on a clean
single-surface feature.

Run:
    PYTHONPATH=scripts pytest \
        scripts/dontpanic_orchestrate/tests/test_plan_review_lint_f001.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate.plan_review.lint import (  # noqa: E402
    Resolvers,
    ScopeFlag,
    ScopeReport,
    extract_named_tokens,
    lint_feature,
    split_acceptance,
    tag_surfaces,
)

# A resolver set wide enough that the clean negative case's named tokens all
# resolve; the missing-prereq cases name tokens deliberately absent from it.
RESOLVERS = Resolvers(
    commands=frozenset({"plan-review", "quota-caps init", "dontpanic"}),
    flags=frozenset({"--format", "--allow-oversize"}),
    symbols=frozenset({"lint_feature", "ScopeReport"}),
)


# ─────────────────────────── purity (acceptance #1) ─────────────────────────


def test_lint_feature_returns_typed_report():
    feature = {"id": "FX", "description": "pure module", "acceptance": "(1) it works"}
    report = lint_feature(feature, RESOLVERS)
    assert isinstance(report, ScopeReport)
    assert report.feature_id == "FX"
    assert all(isinstance(f, ScopeFlag) for f in report.flags)


def test_lint_feature_does_not_mutate_inputs():
    feature = {
        "id": "FX",
        "description": "engine and cli and dashboard",
        "steps": ["a step"],
        "acceptance": "(1) one (2) two",
    }
    before = dict(feature)
    before_steps = list(feature["steps"])
    lint_feature(feature, RESOLVERS)
    assert feature == before
    assert feature["steps"] == before_steps


def test_lint_feature_is_total_without_resolvers():
    # No resolvers => every named token is unresolved (most conservative read).
    feature = {
        "id": "FX",
        "acceptance": "(1) the `--unknown-flag` flag is accepted",
    }
    report = lint_feature(feature)
    assert report.flags_of_kind("missing_prereq")


# ───────────────────── over_surface (acceptance #2, F007) ───────────────────


def test_f007_multi_surface_yields_over_surface_with_surface_evidence():
    # F007: an engine + CLI + dashboard feature — three surfaces, one dispatch.
    feature = {
        "id": "F007",
        "description": (
            "Wire the orchestration dispatch engine, a new dontpanic CLI "
            "subcommand, and a dashboard html view together."
        ),
        "acceptance": (
            "(1) the supervisor dispatch runs. "
            "(2) the cli subcommand prints. "
            "(3) the dashboard renders."
        ),
    }
    report = lint_feature(feature, RESOLVERS)
    over = report.flags_of_kind("over_surface")
    assert over, "multi-surface feature must yield over_surface"
    assert len(report.surfaces) >= 3
    # Evidence carries the surface list.
    for surface in report.surfaces:
        assert surface in over[0].evidence
    assert over[0].severity == "block"
    # The composite timeout signal also fires for >= 3 surfaces.
    assert report.flags_of_kind("likely_timeout")


def test_engine_plus_cli_is_multi_surface():
    # Auditor i0 finding 3: the calibration corpus's "engine + CLI" shape must
    # not collapse to a single surface and escape over_surface.
    feature = {
        "id": "FX",
        "description": "a lint engine plus a dontpanic cli subcommand",
        "acceptance": "(1) the engine scores (2) the cli subcommand prints.",
    }
    report = lint_feature(feature, RESOLVERS)
    assert "core" in report.surfaces, report.surfaces
    assert "cli" in report.surfaces, report.surfaces
    assert report.flags_of_kind("over_surface")


def test_two_surface_feature_flags_over_surface_as_warn_not_block():
    feature = {
        "id": "FX",
        "description": "a dontpanic cli subcommand that writes decisions.jsonl",
        "acceptance": "(1) the cli runs (2) it appends to decisions.jsonl",
    }
    report = lint_feature(feature, RESOLVERS)
    over = report.flags_of_kind("over_surface")
    assert over and over[0].severity == "warn"


# ────────────────────── exemplar_ac (acceptance #3, F008) ───────────────────


def test_f008_exemplar_acceptance_yields_exemplar_ac():
    # F008: "e.g. roles" — an example instead of an invariant.
    feature = {
        "id": "F008",
        "description": "validate role config in one module",
        "acceptance": (
            "(1) role config is validated for known roles "
            "(e.g. implementer, auditor, goal_auditor)."
        ),
    }
    report = lint_feature(feature, RESOLVERS)
    flags = report.flags_of_kind("exemplar_ac")
    assert flags, "exemplar enumeration without a universal must flag"
    assert "implementer" in flags[0].evidence


def test_including_the_enumeration_without_universal_flags_exemplar():
    # Auditor i0 finding 2: "including the ..." is an exemplar enumeration just
    # like "including ..."; only a co-located universal redeems it.
    feature = {
        "id": "FX",
        "description": "validate role config in one module",
        "acceptance": (
            "(1) role config is validated, including the implementer "
            "and auditor roles."
        ),
    }
    report = lint_feature(feature, RESOLVERS)
    assert report.flags_of_kind("exemplar_ac")


def test_universal_redeems_an_enumeration_no_exemplar_flag():
    feature = {
        "id": "FX",
        "description": "validate role config in one module",
        "acceptance": (
            "(1) every role in the registry is validated, including "
            "implementer, auditor, and goal_auditor."
        ),
    }
    report = lint_feature(feature, RESOLVERS)
    assert not report.flags_of_kind("exemplar_ac")


# ─────────────────────────── weak_test (acceptance #4) ──────────────────────


def test_string_equality_assertion_yields_weak_test():
    feature = {
        "id": "F012",
        "description": "a pure helper module",
        "acceptance": "(1) the rendered output equals the expected string.",
    }
    report = lint_feature(feature, RESOLVERS)
    assert report.flags_of_kind("weak_test")


def test_roundtrip_assertion_does_not_flag_weak_test():
    feature = {
        "id": "FX",
        "description": "a pure helper module",
        "acceptance": (
            "(1) parsing then re-rendering is a round-trip that equals the input."
        ),
    }
    report = lint_feature(feature, RESOLVERS)
    assert not report.flags_of_kind("weak_test")


def test_string_matches_expected_phrasing_yields_weak_test():
    # Operator-finish (D008): codex F2 — the weak-test detector missed the
    # plain "string matches expected" / "matches the expected" phrasings, which
    # are just as whack-a-mole-prone as "==" / "equals".
    for ac in (
        "(1) the result string matches expected for every input.",
        "(1) the output matches the expected value in all cases.",
    ):
        feature = {"id": "FX", "description": "a pure helper module", "acceptance": ac}
        report = lint_feature(feature, RESOLVERS)
        assert report.flags_of_kind("weak_test"), ac


def test_string_matches_expected_redeemed_by_property_marker():
    # The same phrasing is redeemed when a property/invariant marker is present,
    # so the new alternatives don't over-fire on legitimate property assertions.
    feature = {
        "id": "FX",
        "description": "a pure helper module",
        "acceptance": (
            "(1) round-trip parsing matches the expected output as an invariant."
        ),
    }
    report = lint_feature(feature, RESOLVERS)
    assert not report.flags_of_kind("weak_test")


# ───────────────────── missing_prereq (acceptance #5, F012) ─────────────────


def test_f012_missing_prereq_names_unresolved_token():
    # F012: an AC naming the stale `command_validation` allowlist the plan
    # never declared. command_validation is NOT in RESOLVERS.symbols.
    feature = {
        "id": "F012",
        "description": "a pure helper module",
        "acceptance": (
            "(1) the emitted command resolves against "
            "`command_validation.validate_command_tokens`."
        ),
    }
    report = lint_feature(feature, RESOLVERS)
    flags = report.flags_of_kind("missing_prereq")
    assert flags, "an unresolved named symbol must flag missing_prereq"
    assert "command_validation.validate_command_tokens" in flags[0].evidence


def test_unresolved_command_and_flag_each_flag():
    feature = {
        "id": "FX",
        "acceptance": (
            "(1) `frobnicate widgets` runs with the `--nonexistent` flag."
        ),
    }
    report = lint_feature(feature, RESOLVERS)
    evidence = " ".join(f.evidence for f in report.flags_of_kind("missing_prereq"))
    assert "frobnicate widgets" in evidence
    assert "--nonexistent" in evidence


def test_resolved_tokens_do_not_flag_missing_prereq():
    feature = {
        "id": "FX",
        "acceptance": (
            "(1) `plan-review` runs with `--format` and calls `lint_feature`."
        ),
    }
    report = lint_feature(feature, RESOLVERS)
    assert not report.flags_of_kind("missing_prereq")


def test_plain_text_flag_and_symbol_flag_missing_prereq():
    # Auditor i0 finding 1: a flag / symbol named in prose (no backticks) must
    # still be coupling-checked, not silently missed.
    feature = {
        "id": "FX",
        "acceptance": "(1) run with --nonexistent and resolve missing_symbol.",
    }
    report = lint_feature(feature, RESOLVERS)
    evidence = " ".join(f.evidence for f in report.flags_of_kind("missing_prereq"))
    assert "--nonexistent" in evidence
    assert "missing_symbol" in evidence


def test_plain_text_resolved_symbol_does_not_flag():
    # The same plain-text scan must not false-positive on a resolved symbol.
    feature = {"id": "FX", "acceptance": "(1) lint_feature returns a report."}
    report = lint_feature(feature, RESOLVERS)
    assert not report.flags_of_kind("missing_prereq")


def test_dontpanic_prefixed_supported_command_resolves():
    # Auditor i0 finding: `dontpanic plan-review` is the supported invocation
    # shape but `known_subcommands` lists only the bare `plan-review`. The
    # binary-prefixed phrase must resolve, not false-flag missing_prereq.
    feature = {
        "id": "FX",
        "acceptance": "(1) `dontpanic plan-review <plan> [--format text|json]` exits 0.",
    }
    report = lint_feature(feature, RESOLVERS)
    assert not report.flags_of_kind("missing_prereq")


def test_dontpanic_prefixed_unknown_subcommand_still_flags():
    # The prefix-strip must not turn off the signal: an unknown subcommand
    # after `dontpanic` is still a missing prereq.
    feature = {
        "id": "FX",
        "acceptance": "(1) `dontpanic frobnicate <plan>` runs.",
    }
    report = lint_feature(feature, RESOLVERS)
    evidence = " ".join(f.evidence for f in report.flags_of_kind("missing_prereq"))
    assert "dontpanic frobnicate" in evidence


def test_subcommand_with_argument_resolves_on_first_word():
    # `quota-caps init` resolves on its subcommand (`init` is a subcommand arg,
    # not a separate prereq); `quota-caps` is in RESOLVERS.commands.
    feature = {
        "id": "FX",
        "acceptance": "(1) `quota-caps inspect` reports the caps.",
    }
    resolvers = Resolvers(commands=frozenset({"quota-caps"}))
    report = lint_feature(feature, resolvers)
    assert not report.flags_of_kind("missing_prereq")


def test_plain_text_filename_is_not_a_symbol():
    # A dotted filename token is persistence state, not a code symbol; it must
    # not be mistaken for an unresolved symbol.
    feature = {"id": "FX", "acceptance": "(1) it appends to decisions.jsonl."}
    report = lint_feature(feature, RESOLVERS)
    assert not report.flags_of_kind("missing_prereq")


# ──────────────────── clean negative (acceptance #6, F015) ──────────────────


def test_f015_clean_single_surface_feature_no_flags():
    # F015: 4 ACs, one pure core module, invariant ACs, all tokens resolve.
    feature = {
        "id": "F015",
        "description": (
            "A pure deterministic module. `lint_feature` returns a typed "
            "ScopeReport."
        ),
        "steps": [
            "Define the data types.",
            "Implement the pure function.",
            "Add unit tests.",
        ],
        "acceptance": (
            "(1) `lint_feature` is a pure function with no side effects. "
            "(2) every input record yields exactly one typed report. "
            "(3) parsing then rendering round-trips for all records. "
            "(4) the invariant holds for each record."
        ),
    }
    report = lint_feature(feature, RESOLVERS)
    assert report.surfaces == ("core",), report.surfaces
    assert report.flags == (), [f.kind for f in report.flags]
    assert not report.has_block()


def test_over_ac_warns_above_band_and_blocks_when_large():
    warn_acs = " ".join(f"({i}) every criterion {i} holds." for i in range(1, 8))
    warn = lint_feature({"id": "FX", "acceptance": warn_acs}, RESOLVERS)
    assert any(
        f.kind == "over_ac" and f.severity == "warn" for f in warn.flags
    ), [f.severity for f in warn.flags_of_kind("over_ac")]

    block_acs = " ".join(f"({i}) every criterion {i} holds." for i in range(1, 12))
    block = lint_feature({"id": "FX", "acceptance": block_acs}, RESOLVERS)
    assert block.flags_of_kind("over_ac")[0].severity == "block"


# ───────────────────────────── helper unit tests ───────────────────────────


@pytest.mark.parametrize(
    "text,expected",
    [
        ("a pure module that returns a typed report", ("core",)),
        ("the dontpanic cli subcommand", ("cli",)),
        ("render the dashboard html", ("dashboard",)),
    ],
)
def test_tag_surfaces_single_surface(text, expected):
    assert tag_surfaces(text) == expected


def test_split_acceptance_numbered_and_fallback():
    assert split_acceptance("(1) a (2) b (3) c") == ("a", "b", "c")
    assert split_acceptance("just one criterion") == ("just one criterion",)
    assert split_acceptance("   ") == ()


def test_lint_module_imports_nothing_side_effect_capable():
    # Acceptance #1 purity: the lint core must not pull in network / process /
    # orchestration machinery (mirrors command_validation's purity test).
    src = (HERE.parents[2] / "dontpanic_orchestrate" / "plan_review" / "lint.py").read_text()
    import_lines = [
        ln.strip()
        for ln in src.splitlines()
        if ln.strip().startswith(("import ", "from "))
    ]
    forbidden = ("subprocess", "requests", "urllib", "socket", "os",
                 "dontpanic_orchestrate.cli", "dontpanic_orchestrate.supervisor")
    for line in import_lines:
        for token in forbidden:
            assert token not in line, f"lint.py must not import {token}: {line!r}"


def test_extract_named_tokens_classifies():
    toks = dict(extract_named_tokens("`plan-review` `--format` `mod.fn` `bare_sym`"))
    assert toks["plan-review"] == "command"
    assert toks["--format"] == "flag"
    assert toks["mod.fn"] == "symbol"
    assert toks["bare_sym"] == "symbol"
