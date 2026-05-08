"""Plan 2026-05-08-002 F002 — skill_applicability matcher.

Test coverage per F002 acceptance:

  (1) Purity contract — module source contains no ``subprocess``, no
      ``logging.getLogger``, no ``print(``.
  (2) Match correctness — parametrized over surface-overlap, no-overlap,
      goal-only-match, and neither-set cases.
  (3) Skip path — skill without ``applies_to:`` becomes a Skip with
      explanatory rationale; matcher does not crash.
  (4) Malformed ``applies_to:`` — non-mapping payload + invalid surface
      type both Skip cleanly.
  (5) Empty-surfaces plan — plan declaring neither ``surfaces:`` nor
      ``goal_type:`` returns empty matches even with skills present.
  (6) External provenance — skill with ``applies_to.external_cli`` pulls
      provenance='external' and copies metadata; matcher never invokes.
  (7) JSON round-trip — ApplicabilityReport.to_dict / from_dict
      preserves equality.

Run: PYTHONPATH=scripts pytest \\
       scripts/dontpanic_orchestrate/tests/test_skill_applicability.py
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import skill_applicability  # noqa: E402
from dontpanic_orchestrate.skill_applicability import (  # noqa: E402
    ApplicabilityReport,
    ExternalCli,
    Match,
    Skip,
    match,
    write_report,
)


# ────────────────────────────  fixture helpers  ────────────────────────────


@dataclass
class _StubGoalType:
    value: str


@dataclass
class _StubPlanInner:
    goal_type: _StubGoalType | None = None


@dataclass
class _StubPlan:
    """Minimal duck-typed stand-in for a LoadedPlan. The matcher only
    reads ``plan_id``, ``surfaces``, and ``plan.goal_type`` so this avoids
    spinning up a real plan_loader fixture."""

    plan_id: str = "2026-05-08-200-feat-stub"
    surfaces: list[str] | None = None
    plan: _StubPlanInner | None = None

    def __post_init__(self) -> None:
        if self.surfaces is None:
            self.surfaces = []
        if self.plan is None:
            self.plan = _StubPlanInner()


def _write_skill(
    skills_dir: Path,
    name: str,
    *,
    frontmatter_body: str = "",
    body: str = "# Skill body",
) -> Path:
    skill_dir = skills_dir / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text(
        f"---\nname: {name}\n{frontmatter_body}---\n\n{body}\n"
    )
    return skill_md


# ────────────────────────────  (1) purity contract  ────────────────────────────


class TestPurity:
    def test_source_has_no_subprocess_logging_or_print(self):
        source = Path(skill_applicability.__file__).read_text()

        # Strip docstring lines so the design discussion (which legitimately
        # uses the words "subprocess" / "print" / "logging") doesn't trip the
        # grep. The actual purity check then runs against code lines only.
        code_lines = []
        in_string = False
        string_delim = ""
        for raw in source.splitlines():
            stripped = raw.strip()
            if not in_string and (stripped.startswith('"""') or stripped.startswith("'''")):
                delim = stripped[:3]
                # Single-line docstring case: starts and ends on same line.
                if len(stripped) > 3 and stripped.endswith(delim):
                    continue
                in_string = True
                string_delim = delim
                continue
            if in_string and stripped.endswith(string_delim):
                in_string = False
                string_delim = ""
                continue
            if in_string:
                continue
            code_lines.append(raw)
        code = "\n".join(code_lines)

        assert "import subprocess" not in code, (
            "skill_applicability must not import subprocess (D004 advisory; "
            "external_cli per D007 is metadata-only)"
        )
        assert not re.search(r"\bsubprocess\.", code), (
            "skill_applicability must not call subprocess.* (D007 inert)"
        )
        assert not re.search(r"\blogging\.getLogger\b", code), (
            "skill_applicability must not call logging.getLogger (purity)"
        )
        # `print(` would emit operator output from inside the matcher; the
        # CLI seam owns the one-line summary. Match only function-call form
        # so the word "print" inside a docstring discussion couldn't trip
        # this. Also tolerate Pydantic field declarations like
        # `print_format: str` if they ever appear.
        assert not re.search(r"(^|\W)print\s*\(", code), (
            "skill_applicability must not call print() — operator output "
            "is owned by the CLI seam"
        )


# ────────────────────────────  (2) match correctness  ────────────────────────────


class TestMatchCorrectness:
    def test_surface_overlap_emits_match(self, tmp_path: Path):
        skills_dir = tmp_path / "skills"
        _write_skill(
            skills_dir,
            "ux-skill",
            frontmatter_body=(
                "applies_to:\n"
                "  surfaces: [ux]\n"
                "  goal_types: []\n"
            ),
        )
        plan = _StubPlan(plan_id="p1", surfaces=["ux"])
        report = match(plan, skills_dir)
        assert len(report.matches) == 1
        m = report.matches[0]
        assert m.skill_name == "ux-skill"
        assert m.matched_surfaces == ["ux"]
        assert m.matched_goal_types == []
        assert m.provenance == "internal"
        assert m.external_cli is None

    def test_no_overlap_no_goal_yields_no_match(self, tmp_path: Path):
        skills_dir = tmp_path / "skills"
        _write_skill(
            skills_dir,
            "ml-ux-skill",
            frontmatter_body=(
                "applies_to:\n"
                "  surfaces: [ux, ml]\n"
                "  goal_types: [parity]\n"
            ),
        )
        plan = _StubPlan(plan_id="p2", surfaces=["backend"])
        report = match(plan, skills_dir)
        assert report.matches == []
        # Skill has applies_to → it's not a Skip either; the matcher just
        # silently omits it from both lists. D004 — no false-positive noise.
        assert report.skipped == []

    def test_goal_type_overlap_matches_with_empty_surfaces(
        self, tmp_path: Path
    ):
        skills_dir = tmp_path / "skills"
        _write_skill(
            skills_dir,
            "feature-skill",
            frontmatter_body=(
                "applies_to:\n"
                "  surfaces: [data]\n"
                "  goal_types: [new_feature]\n"
            ),
        )
        plan = _StubPlan(
            plan_id="p3",
            surfaces=[],
            plan=_StubPlanInner(goal_type=_StubGoalType("new_feature")),
        )
        report = match(plan, skills_dir)
        assert len(report.matches) == 1
        m = report.matches[0]
        assert m.matched_surfaces == []
        assert m.matched_goal_types == ["new_feature"]
        assert "goal_types=['new_feature']" in m.rationale

    def test_neither_surfaces_nor_goal_yields_empty_matches(
        self, tmp_path: Path
    ):
        skills_dir = tmp_path / "skills"
        _write_skill(
            skills_dir,
            "ux-skill",
            frontmatter_body=(
                "applies_to:\n"
                "  surfaces: [ux]\n"
                "  goal_types: [parity]\n"
            ),
        )
        plan = _StubPlan(plan_id="p4", surfaces=[])
        report = match(plan, skills_dir)
        assert report.matches == []

    def test_both_overlaps_produces_single_match_with_both(
        self, tmp_path: Path
    ):
        skills_dir = tmp_path / "skills"
        _write_skill(
            skills_dir,
            "ux-feat",
            frontmatter_body=(
                "applies_to:\n"
                "  surfaces: [ux]\n"
                "  goal_types: [new_feature]\n"
            ),
        )
        plan = _StubPlan(
            plan_id="p5",
            surfaces=["ux"],
            plan=_StubPlanInner(goal_type=_StubGoalType("new_feature")),
        )
        report = match(plan, skills_dir)
        assert len(report.matches) == 1
        m = report.matches[0]
        assert m.matched_surfaces == ["ux"]
        assert m.matched_goal_types == ["new_feature"]


# ────────────────────────────  (3) skip path  ────────────────────────────


class TestSkipPath:
    def test_skill_without_applies_to_becomes_skip(self, tmp_path: Path):
        skills_dir = tmp_path / "skills"
        _write_skill(
            skills_dir,
            "no-applies-to",
            frontmatter_body="description: a skill with no applies_to block\n",
        )
        plan = _StubPlan(plan_id="p6", surfaces=["ux"])
        report = match(plan, skills_dir)
        assert report.matches == []
        assert len(report.skipped) == 1
        assert report.skipped[0].skill_name == "no-applies-to"
        assert "no applies_to" in report.skipped[0].reason

    def test_missing_skill_md_is_silently_ignored(self, tmp_path: Path):
        # A directory under skills/ without SKILL.md should not appear as
        # either Match or Skip — it's not a skill, just a stray directory.
        skills_dir = tmp_path / "skills"
        (skills_dir / "stray").mkdir(parents=True)
        plan = _StubPlan(plan_id="p7", surfaces=["ux"])
        report = match(plan, skills_dir)
        assert report.matches == []
        assert report.skipped == []


# ────────────────────────────  (4) malformed applies_to  ────────────────────────────


class TestMalformedAppliesTo:
    def test_applies_to_not_a_mapping_skips_with_reason(
        self, tmp_path: Path
    ):
        skills_dir = tmp_path / "skills"
        _write_skill(
            skills_dir,
            "scalar-applies-to",
            frontmatter_body="applies_to: not a dict\n",
        )
        plan = _StubPlan(plan_id="p8", surfaces=["ux"])
        report = match(plan, skills_dir)
        assert report.matches == []
        assert len(report.skipped) == 1
        skip = report.skipped[0]
        assert skip.skill_name == "scalar-applies-to"
        assert "applies_to is not a mapping" in skip.reason

    def test_applies_to_with_invalid_surface_type_skips_cleanly(
        self, tmp_path: Path
    ):
        skills_dir = tmp_path / "skills"
        _write_skill(
            skills_dir,
            "bad-surfaces",
            frontmatter_body=(
                "applies_to:\n"
                "  surfaces: 'not a list'\n"
                "  goal_types: []\n"
            ),
        )
        plan = _StubPlan(plan_id="p9", surfaces=["ux"])
        report = match(plan, skills_dir)
        assert report.matches == []
        assert len(report.skipped) == 1
        assert "validation" in report.skipped[0].reason.lower()

    def test_applies_to_with_unknown_field_skips_cleanly(
        self, tmp_path: Path
    ):
        skills_dir = tmp_path / "skills"
        _write_skill(
            skills_dir,
            "extra-field",
            frontmatter_body=(
                "applies_to:\n"
                "  surfaces: [ux]\n"
                "  goal_types: []\n"
                "  unknown_field: value\n"
            ),
        )
        plan = _StubPlan(plan_id="p10", surfaces=["ux"])
        report = match(plan, skills_dir)
        # extra='forbid' on AppliesToModel rejects extra fields → Skip.
        assert report.matches == []
        assert len(report.skipped) == 1
        assert "validation" in report.skipped[0].reason.lower()


# ────────────────────────────  (5) empty-surfaces plan  ────────────────────────────


class TestEmptySurfacesPlan:
    def test_plan_with_no_surfaces_or_goal_returns_empty_matches(
        self, tmp_path: Path
    ):
        skills_dir = tmp_path / "skills"
        # Even with skills declaring applies_to, an empty plan produces no
        # matches because both intersection sets are empty.
        _write_skill(
            skills_dir,
            "ux-skill",
            frontmatter_body=(
                "applies_to:\n"
                "  surfaces: [ux, ml]\n"
                "  goal_types: [new_feature]\n"
            ),
        )
        plan = _StubPlan(plan_id="p11", surfaces=[])
        report = match(plan, skills_dir)
        assert report.matches == []
        assert report.plan_surfaces == []
        assert report.plan_goal_type is None


# ────────────────────────────  (6) external provenance  ────────────────────────────


class TestExternalProvenance:
    def test_external_cli_metadata_passes_through_inert(
        self, tmp_path: Path
    ):
        skills_dir = tmp_path / "skills"
        _write_skill(
            skills_dir,
            "external-skill",
            frontmatter_body=(
                "applies_to:\n"
                "  surfaces: [docs]\n"
                "  goal_types: []\n"
                "  external_cli:\n"
                "    provider: printing-press\n"
                "    name: pp-render\n"
                "    command: pp\n"
                "    version_pin: 0.4.2\n"
            ),
        )
        plan = _StubPlan(plan_id="p12", surfaces=["docs"])
        report = match(plan, skills_dir)
        assert len(report.matches) == 1
        m = report.matches[0]
        assert m.provenance == "external"
        assert m.external_cli is not None
        assert m.external_cli.provider == "printing-press"
        assert m.external_cli.name == "pp-render"
        assert m.external_cli.command == "pp"
        assert m.external_cli.version_pin == "0.4.2"

    def test_internal_provenance_default_when_no_external_cli(
        self, tmp_path: Path
    ):
        skills_dir = tmp_path / "skills"
        _write_skill(
            skills_dir,
            "internal-skill",
            frontmatter_body=(
                "applies_to:\n"
                "  surfaces: [docs]\n"
                "  goal_types: []\n"
            ),
        )
        plan = _StubPlan(plan_id="p13", surfaces=["docs"])
        report = match(plan, skills_dir)
        assert len(report.matches) == 1
        m = report.matches[0]
        assert m.provenance == "internal"
        assert m.external_cli is None


# ────────────────────────────  (7) JSON round-trip  ────────────────────────────


class TestJsonRoundTrip:
    def _build_report(self) -> ApplicabilityReport:
        return ApplicabilityReport(
            schema_version="1.0",
            plan_id="2026-05-08-200-feat-stub",
            plan_surfaces=["ux", "ml"],
            plan_goal_type="new_feature",
            matches=[
                Match(
                    skill_name="internal-skill",
                    matched_surfaces=["ux"],
                    matched_goal_types=["new_feature"],
                    rationale="matched on surfaces=['ux'] + goal_types=['new_feature']",
                    provenance="internal",
                    external_cli=None,
                ),
                Match(
                    skill_name="external-skill",
                    matched_surfaces=["ml"],
                    matched_goal_types=[],
                    rationale="matched on surfaces=['ml'] + goal_types=[]",
                    provenance="external",
                    external_cli=ExternalCli(
                        provider="printing-press",
                        name="pp-render",
                        command="pp",
                        version_pin="0.4.2",
                    ),
                ),
            ],
            skipped=[Skip(skill_name="opt-out-skill", reason="skill has no applies_to declaration")],
        )

    def test_round_trip_preserves_equality(self):
        original = self._build_report()
        roundtripped = ApplicabilityReport.from_dict(original.to_dict())
        assert roundtripped == original

    def test_json_serialized_round_trip(self, tmp_path: Path):
        original = self._build_report()
        sidecar_path = write_report(original, tmp_path)
        assert sidecar_path == tmp_path / "evidence" / "applicable-skills.json"
        loaded: dict[str, Any] = json.loads(sidecar_path.read_text())
        roundtripped = ApplicabilityReport.from_dict(loaded)
        assert roundtripped == original

    def test_serialized_keys_are_stable(self):
        original = self._build_report()
        d = original.to_dict()
        assert set(d.keys()) == {
            "schema_version",
            "plan_id",
            "plan_surfaces",
            "plan_goal_type",
            "matches",
            "skipped",
        }
        assert set(d["matches"][0].keys()) == {
            "skill_name",
            "matched_surfaces",
            "matched_goal_types",
            "rationale",
            "provenance",
            "external_cli",
        }


# ────────────────────────────  miscellany  ────────────────────────────


class TestEdgeCases:
    def test_missing_skills_dir_returns_empty_report(self, tmp_path: Path):
        plan = _StubPlan(plan_id="p14", surfaces=["ux"])
        report = match(plan, tmp_path / "does-not-exist")
        assert report.matches == []
        assert report.skipped == []
        assert report.plan_id == "p14"

    def test_sorted_iteration_order(self, tmp_path: Path):
        skills_dir = tmp_path / "skills"
        for nm in ("zebra", "alpha", "mango"):
            _write_skill(
                skills_dir,
                nm,
                frontmatter_body=(
                    "applies_to:\n"
                    "  surfaces: [ux]\n"
                    "  goal_types: []\n"
                ),
            )
        plan = _StubPlan(plan_id="p15", surfaces=["ux"])
        report = match(plan, skills_dir)
        assert [m.skill_name for m in report.matches] == [
            "alpha",
            "mango",
            "zebra",
        ]

    def test_string_goal_type_without_value_attr_supported(
        self, tmp_path: Path
    ):
        # If a caller passes plain str instead of an enum-like object the
        # matcher should still treat it correctly.
        skills_dir = tmp_path / "skills"
        _write_skill(
            skills_dir,
            "feature-skill",
            frontmatter_body=(
                "applies_to:\n"
                "  surfaces: []\n"
                "  goal_types: [new_feature]\n"
            ),
        )
        plan = _StubPlan(
            plan_id="p16",
            surfaces=[],
            plan=_StubPlanInner(goal_type="new_feature"),  # type: ignore[arg-type]
        )
        report = match(plan, skills_dir)
        assert len(report.matches) == 1
        assert report.matches[0].matched_goal_types == ["new_feature"]


# Surface enum + goal-type enum constants exposed for downstream consumers.
class TestModuleConstants:
    def test_surface_values_match_canonical_enum(self):
        assert skill_applicability.SURFACE_VALUES == frozenset(
            {
                "web",
                "ios",
                "android",
                "backend",
                "infra",
                "security",
                "data",
                "ux",
                "ml",
                "docs",
            }
        )

    def test_goal_type_values_match_canonical_enum(self):
        assert skill_applicability.GOAL_TYPE_VALUES == frozenset(
            {
                "mechanical",
                "infra",
                "refactor",
                "parity",
                "new_feature",
                "migration",
                "incident",
            }
        )

    def test_schema_version_is_v1_0(self):
        assert skill_applicability.SCHEMA_VERSION == "1.0"


# Pytest collection: verifies all expected test classes are present so a
# rename/typo doesn't silently drop coverage.
class TestCoverageManifest:
    def test_all_expected_classes_present(self):
        expected = {
            "TestPurity",
            "TestMatchCorrectness",
            "TestSkipPath",
            "TestMalformedAppliesTo",
            "TestEmptySurfacesPlan",
            "TestExternalProvenance",
            "TestJsonRoundTrip",
            "TestEdgeCases",
            "TestModuleConstants",
            "TestCoverageManifest",
        }
        actual = {
            name
            for name, obj in globals().items()
            if isinstance(obj, type) and name.startswith("Test")
        }
        missing = expected - actual
        assert not missing, f"missing test classes: {sorted(missing)}"


@pytest.mark.parametrize(
    "plan_surfaces,plan_goal,skill_yaml,expects_match",
    [
        # Surface only
        (["ux"], None, "applies_to:\n  surfaces: [ux]\n  goal_types: []\n", True),
        # Goal only
        ([], "parity", "applies_to:\n  surfaces: []\n  goal_types: [parity]\n", True),
        # Neither
        (["ux"], None, "applies_to:\n  surfaces: [ml]\n  goal_types: [new_feature]\n", False),
        # Multi-surface partial overlap
        (["ux", "ml"], None, "applies_to:\n  surfaces: [ml]\n  goal_types: []\n", True),
        # Plan declares both, skill declares only goal_type — goal wins
        (["ux"], "new_feature", "applies_to:\n  surfaces: [ml]\n  goal_types: [new_feature]\n", True),
    ],
)
def test_parametrized_match_logic(
    tmp_path: Path,
    plan_surfaces: list[str],
    plan_goal: str | None,
    skill_yaml: str,
    expects_match: bool,
):
    skills_dir = tmp_path / "skills"
    _write_skill(skills_dir, "param-skill", frontmatter_body=skill_yaml)
    plan = _StubPlan(
        plan_id="param-plan",
        surfaces=list(plan_surfaces),
        plan=_StubPlanInner(
            goal_type=_StubGoalType(plan_goal) if plan_goal else None,
        ),
    )
    report = match(plan, skills_dir)
    assert (len(report.matches) == 1) is expects_match
