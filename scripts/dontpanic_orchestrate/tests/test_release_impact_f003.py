"""Plan 2026-05-23-007 F003 — release-impact advisory checker tests.

Coverage matrix (the plan's acceptance #6 requires golden fixtures for at
least docs-only, schema, CLI, dashboard, capability-manifest, social-preview,
and internal-only changes):

  1. CLI change (scripts/dontpanic_orchestrate/cli.py) → root_changelog + cli_help.
  2. Schema change (claude/shared/schemas/v1.0/plan.schema.json) → shared_changelog + schemas, no root_changelog.
  3. Dashboard change (dashboard/index.html) → root_changelog + dashboard.
  4. Capability manifest change (capabilities/agent-claude-cli.json) → root_changelog + capability_manifest.
  5. Docs-only README change → root_changelog + readme.
  6. Social preview (.github/social-preview.png) → root_changelog + public_metadata.
  7. Internal-only change (scripts/dontpanic_orchestrate/circuit_breakers.py) → empty / internal_only.
  8. Plan-intent (surfaces=[infra]) → root_changelog + cli_help + capability_manifest + schemas + shared_changelog.
  9. Allowed_paths=docs/** → root_changelog + readme suggestions.
 10. Step path tokens mention a schema path → schemas + shared_changelog.
 11. Combined (intent + path) → union of suggestions.
 12. Render text shape: includes "Release impact" heading and surface ids.
 13. Read-only invariant: analyze never writes any files.
 14. No-secret invariant: advisory text doesn't echo any secret-looking values.
 15. planning_readiness emits a release_impact warning for a plan whose surfaces
     and allowed_paths trigger advice; preserves stable JSON envelope.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import release_impact  # noqa: E402


# ─────────────────────────  unit tests — analyze_paths  ─────────────────────────


def test_cli_change_suggests_root_changelog_and_cli_help() -> None:
    advisory = release_impact.analyze_paths(
        ["scripts/dontpanic_orchestrate/cli.py"]
    )
    ids = advisory.surface_ids()
    assert "root_changelog" in ids
    assert "cli_help" in ids
    assert "schemas" not in ids
    assert not advisory.internal_only


def test_schema_change_suggests_shared_changelog_and_schemas_only() -> None:
    advisory = release_impact.analyze_paths(
        ["claude/shared/schemas/v1.0/plan.schema.json"]
    )
    ids = advisory.surface_ids()
    assert "shared_changelog" in ids
    assert "schemas" in ids
    # Pure schema bump → no root changelog mandate.
    assert "root_changelog" not in ids
    assert "cli_help" not in ids


def test_dashboard_change_suggests_root_and_dashboard() -> None:
    advisory = release_impact.analyze_paths(["dashboard/index.html"])
    ids = advisory.surface_ids()
    assert "root_changelog" in ids
    assert "dashboard" in ids


def test_dashboard_backend_module_change_suggests_root_and_dashboard() -> None:
    advisory = release_impact.analyze_paths(
        ["scripts/dontpanic_orchestrate/dashboard_relevance.py"]
    )
    ids = advisory.surface_ids()
    assert "root_changelog" in ids
    assert "dashboard" in ids


def test_capability_manifest_change_suggests_root_and_capability_manifest() -> None:
    advisory = release_impact.analyze_paths(
        ["capabilities/agent-claude-cli.json"]
    )
    ids = advisory.surface_ids()
    assert "root_changelog" in ids
    assert "capability_manifest" in ids


def test_readme_change_suggests_root_and_readme() -> None:
    advisory = release_impact.analyze_paths(["README.md"])
    ids = advisory.surface_ids()
    assert "root_changelog" in ids
    assert "readme" in ids


def test_onboarding_change_suggests_root_and_onboarding() -> None:
    advisory = release_impact.analyze_paths(["docs/GETTING_STARTED.md"])
    ids = advisory.surface_ids()
    assert "root_changelog" in ids
    assert "onboarding" in ids


def test_social_preview_suggests_public_metadata() -> None:
    advisory = release_impact.analyze_paths([".github/social-preview.png"])
    ids = advisory.surface_ids()
    assert "root_changelog" in ids
    assert "public_metadata" in ids


def test_internal_only_change_returns_no_surfaces() -> None:
    advisory = release_impact.analyze_paths(
        [
            "scripts/dontpanic_orchestrate/circuit_breakers.py",
            "scripts/dontpanic_orchestrate/tests/test_circuit_breakers.py",
        ]
    )
    assert advisory.surface_ids() == ()
    assert advisory.internal_only


def test_plan_ledger_files_suppressed_as_internal() -> None:
    advisory = release_impact.analyze_paths(
        [
            "docs/plans/2026-05-23-007-feat-plan-intake-readiness-v0/INBOX.md",
            "docs/plans/2026-05-23-007-feat-plan-intake-readiness-v0/audit/x.json",
            "docs/plans/2026-05-23-007-feat-plan-intake-readiness-v0/evidence/y.md",
            "docs/plans/2026-05-23-007-feat-plan-intake-readiness-v0/decisions.jsonl",
        ]
    )
    assert advisory.surface_ids() == ()
    assert advisory.internal_only


# ─────────────────────────  plan intent tests  ─────────────────────────


def test_plan_intent_infra_surface_suggests_root_and_infra_surfaces() -> None:
    advisory = release_impact.analyze_plan_intent(plan_surfaces=["infra"])
    ids = advisory.surface_ids()
    assert "root_changelog" in ids
    assert "cli_help" in ids
    assert "capability_manifest" in ids
    assert "schemas" in ids
    assert "shared_changelog" in ids


def test_plan_intent_docs_surface_suggests_readme_and_onboarding() -> None:
    advisory = release_impact.analyze_plan_intent(plan_surfaces=["docs"])
    ids = advisory.surface_ids()
    assert "root_changelog" in ids
    assert "readme" in ids
    assert "onboarding" in ids


def test_plan_intent_allowed_paths_picks_up_dashboard() -> None:
    advisory = release_impact.analyze_plan_intent(
        allowed_paths=["dashboard/**", "scripts/dontpanic_orchestrate/dashboard*.py"]
    )
    ids = advisory.surface_ids()
    assert "dashboard" in ids
    assert "root_changelog" in ids


def test_plan_intent_step_token_pointing_at_schema() -> None:
    advisory = release_impact.analyze_plan_intent(
        step_path_tokens=["claude/shared/schemas/v1.0/plan.schema.json"]
    )
    ids = advisory.surface_ids()
    assert "schemas" in ids
    assert "shared_changelog" in ids


def test_plan_intent_allowed_paths_broad_docs_glob_suggests_readme() -> None:
    """Auditor-required assertion (codex-auditor-F003-i0): the broad glob
    ``docs/**`` in a charter's ``allowed_paths`` must yield root_changelog +
    readme suggestions via the intent-broad pattern table. Without explicit
    normalization, the concrete-path rule table (which targets specific
    files like docs/PRODUCT.md) does not fire on a subtree glob."""
    advisory = release_impact.analyze_plan_intent(allowed_paths=["docs/**"])
    ids = advisory.surface_ids()
    assert "root_changelog" in ids, f"expected root_changelog in {ids}"
    assert "readme" in ids, f"expected readme in {ids}"
    # docs/** is broad — also surfaces onboarding (READMEs + getting-started
    # both live under the docs subtree).
    assert "onboarding" in ids, f"expected onboarding in {ids}"
    # And the advisory must NOT be flagged as internal-only — broad docs
    # globs are public-surface intent.
    assert not advisory.internal_only


def test_plan_intent_narrow_subtree_glob_does_not_fire_broad_rule() -> None:
    """The intent-broad table matches LITERALLY after normalization, so a
    narrow glob like ``docs/synthetic/**`` (a plan-internal scratch space)
    does NOT inherit the ``docs/**`` rule's surfaces. The operator declared
    narrow scope and we respect that."""
    advisory = release_impact.analyze_plan_intent(
        allowed_paths=["docs/synthetic/**"]
    )
    # Either no surfaces (most likely — no rule matches) or strictly an
    # internal_only flavor. We must NOT get root_changelog/readme suggestions.
    ids = advisory.surface_ids()
    assert "root_changelog" not in ids, (
        f"narrow docs/synthetic/** should not trigger root_changelog: {ids}"
    )
    assert "readme" not in ids, (
        f"narrow docs/synthetic/** should not trigger readme: {ids}"
    )


def test_plan_intent_broad_globs_for_other_subtrees() -> None:
    """Other broad subtree globs also fire their intent-broad rules:
    ``claude/shared/**`` → shared_changelog, ``capabilities/**`` →
    capability_manifest, ``.github/**`` → public_metadata."""
    shared = release_impact.analyze_plan_intent(
        allowed_paths=["claude/shared/**"]
    ).surface_ids()
    assert "shared_changelog" in shared

    caps = release_impact.analyze_plan_intent(
        allowed_paths=["capabilities/**"]
    ).surface_ids()
    assert "capability_manifest" in caps
    assert "root_changelog" in caps

    gh = release_impact.analyze_plan_intent(
        allowed_paths=[".github/**"]
    ).surface_ids()
    assert "public_metadata" in gh
    assert "root_changelog" in gh


def test_plan_intent_empty_is_internal_only_false_when_no_inputs() -> None:
    advisory = release_impact.analyze_plan_intent()
    assert advisory.surface_ids() == ()
    # No inputs at all → not "internal-only", it's "no advice".
    assert not advisory.internal_only


# ─────────────────────────  combined analyze  ─────────────────────────


def test_combined_intent_and_diff_unions_evidence() -> None:
    advisory = release_impact.analyze(
        changed_paths=["scripts/dontpanic_orchestrate/cli.py"],
        plan_surfaces=["docs"],
    )
    ids = advisory.surface_ids()
    assert "root_changelog" in ids
    # From the cli.py path.
    assert "cli_help" in ids
    # From the docs surface.
    assert "readme" in ids
    assert "onboarding" in ids


def test_combined_no_inputs_returns_empty_non_internal_advisory() -> None:
    advisory = release_impact.analyze()
    assert advisory.surface_ids() == ()
    assert not advisory.internal_only


# ─────────────────────────  rendering  ─────────────────────────


def test_render_text_lists_surfaces_with_evidence_for_path_advisory() -> None:
    advisory = release_impact.analyze_paths(["dashboard/index.html"])
    text = release_impact.render_text(advisory)
    assert "Release impact" in text
    assert "dashboard" in text
    assert "root_changelog" in text
    # Evidence includes the path that triggered the suggestion.
    assert "dashboard/index.html" in text


def test_render_text_for_internal_only_change_says_internal() -> None:
    advisory = release_impact.analyze_paths(
        ["scripts/dontpanic_orchestrate/circuit_breakers.py"]
    )
    text = release_impact.render_text(advisory)
    assert "internal-only" in text or "no public-surface" in text


# ─────────────────────────  read-only invariant  ─────────────────────────


def test_analyze_writes_no_files(tmp_path: Path, monkeypatch) -> None:
    # Run analyze with a chdir into a tmp_path so any write would surface
    # there. The check below asserts nothing landed.
    monkeypatch.chdir(tmp_path)
    initial = sorted(p.name for p in tmp_path.iterdir())
    release_impact.analyze(
        changed_paths=["dashboard/index.html", "scripts/dontpanic_orchestrate/cli.py"],
        plan_surfaces=["infra", "docs"],
        allowed_paths=["docs/**"],
        step_path_tokens=["docs/RELEASE_IMPACT.md"],
    )
    after = sorted(p.name for p in tmp_path.iterdir())
    assert initial == after, f"analyze wrote files: {set(after) - set(initial)}"


# ─────────────────────────  acceptance #7 invariant  ─────────────────────────


def test_no_secret_values_in_advisory_text() -> None:
    """Acceptance #7: no secret values read or written. The advisory only
    consumes the path STRINGS it is given; it does not read file contents."""
    # Pass paths that LOOK like secret-bearing files. The advisory should
    # only echo the path string itself, never any content.
    advisory = release_impact.analyze_paths(
        [
            ".secrets/api-key.json",
            "config/secrets/openai-token.env",
            "scripts/dontpanic_orchestrate/cli.py",
        ]
    )
    text = release_impact.render_text(advisory)
    # The advisory's text may reference path strings but must not contain
    # values that look like a real secret (we never read file contents).
    for needle in ("sk-", "AIzaSy", "AKIA", "ghp_", "Bearer "):
        assert needle not in text


# ─────────────────────────  planning_readiness integration  ─────────────────────────


def _write_plan(
    plans_root: Path,
    plan_id: str,
    *,
    surfaces: list[str] | None = None,
    allowed_paths: list[str] | None = None,
    feature_steps: list[str] | None = None,
) -> Path:
    plan_dir = plans_root / plan_id
    plan_dir.mkdir(parents=True)
    surfaces_yaml = ""
    if surfaces:
        surfaces_yaml = "surfaces:\n" + "\n".join(f"  - {s}" for s in surfaces) + "\n"
    extras = (
        "orchestration:\n"
        "  parent_plan_id: 2026-05-23-006-infra-planning-intelligence-roadmap-v0\n"
        "  spawn_reason: operator_manual\n"
        "  depth_limit: 3\n"
        "child_charter:\n"
        "  kind: implementation\n"
        "  parent_objective: synthetic\n"
        '  parent_acceptance_item: "synthetic"\n'
        "  allowed_paths:\n"
    )
    for p in allowed_paths or ["docs/synthetic/**"]:
        extras += f'    - "{p}"\n'
    extras += (
        "  forbidden_decisions:\n"
        "    - none\n"
        "  return_condition_summary: synthetic\n"
        "  may_edit_product_code: true\n"
        "commit_policy:\n"
        "  mode: child_commit\n"
        "  requires:\n"
        "    - tests_pass\n"
    )

    (plan_dir / "plan.md").write_text(
        f"""---
id: {plan_id}
title: Synthetic release-impact plan {plan_id}
description: Synthetic release-impact fixture.
type: infra
tier: trivial
status: active
date: "2026-05-23"
agents_required:
  - claude
human_gates:
  []
loop_caps:
  max_iterations: 1
  hard_stop: false
privacy_tier: internal
{surfaces_yaml}links:
  features: ./features.json
{extras}---

# Synthetic

## Target

```yaml
target_env: dev
target_project: none
```
"""
    )
    feats = [
        {
            "id": "F001",
            "category": "test",
            "phase": 0,
            "description": "synthetic feature",
            "steps": feature_steps or ["scripted step"],
            "acceptance": "ok",
            "passes": False,
            "depends_on": [],
        }
    ]
    (plan_dir / "features.json").write_text(
        json.dumps(
            {
                "task_id": plan_id,
                "schema_version": "1.0",
                "features": feats,
            },
            indent=2,
        )
        + "\n"
    )
    return plan_dir


def test_planning_readiness_emits_release_impact_warning(tmp_path: Path) -> None:
    from dontpanic_orchestrate import planning_readiness

    plans_root = tmp_path / "docs" / "plans"
    _write_plan(
        plans_root,
        "2026-05-23-200-feat-dashboard-tweak",
        surfaces=["ux"],
        allowed_paths=["dashboard/**", "scripts/dontpanic_orchestrate/dashboard*.py"],
        feature_steps=[
            "Edit dashboard/index.html to add a new tab.",
            "Update scripts/dontpanic_orchestrate/dashboard.py to emit the tab.",
        ],
    )
    report = planning_readiness.analyze_repo(
        plans_root,
        active_entries=[],
    )
    release_warnings = [w for w in report.warnings if w.kind == "release_impact"]
    assert len(release_warnings) == 1
    w = release_warnings[0]
    assert w.subject == "2026-05-23-200-feat-dashboard-tweak"
    assert "Release impact" in w.message
    assert "dashboard" in w.message
    # Detail carries the structured advisory.
    assert w.detail.get("surfaces"), "expected structured surfaces in warning detail"
    surface_ids = [s["surface"] for s in w.detail["surfaces"]]
    assert "dashboard" in surface_ids


def test_planning_readiness_json_envelope_preserves_release_impact(tmp_path: Path) -> None:
    from dontpanic_orchestrate import planning_readiness

    plans_root = tmp_path / "docs" / "plans"
    _write_plan(
        plans_root,
        "2026-05-23-201-feat-cli-rename",
        surfaces=["infra"],
        allowed_paths=["scripts/dontpanic_orchestrate/cli.py"],
        feature_steps=["Rename `dontpanic foo` to `dontpanic bar` in cli.py."],
    )
    report = planning_readiness.analyze_repo(plans_root, active_entries=[])
    raw = planning_readiness.render_json(report)
    parsed = json.loads(raw)
    assert parsed["schema_version"] == planning_readiness.SCHEMA_VERSION
    release_warnings = [
        w for w in parsed["warnings"] if w["kind"] == "release_impact"
    ]
    assert len(release_warnings) == 1
    # JSON detail must be present.
    detail = release_warnings[0]["detail"]
    assert "surfaces" in detail
    surface_ids = [s["surface"] for s in detail["surfaces"]]
    assert "cli_help" in surface_ids
    assert "root_changelog" in surface_ids


def test_planning_readiness_no_release_impact_for_intent_less_plan(tmp_path: Path) -> None:
    from dontpanic_orchestrate import planning_readiness

    plans_root = tmp_path / "docs" / "plans"
    _write_plan(
        plans_root,
        "2026-05-23-202-feat-no-intent",
        surfaces=[],
        # Allowed_paths default to docs/synthetic/** which matches "general
        # docs" with no changelog suggestion.
        feature_steps=["work on internal-only logic"],
    )
    report = planning_readiness.analyze_repo(plans_root, active_entries=[])
    release_warnings = [w for w in report.warnings if w.kind == "release_impact"]
    # Either zero (no surfaces inferred) or an internal-only advisory.
    if release_warnings:
        # Must be the internal-only flavor; cannot suggest concrete surfaces.
        assert len(release_warnings) == 1
        detail = release_warnings[0].detail
        assert detail.get("internal_only") is True
        assert detail.get("surfaces") in ([], None)


# ─────────────────────────  docs/RELEASE_IMPACT.md exists  ─────────────────────────


def test_release_impact_doc_exists_at_known_path() -> None:
    """Acceptance #2 + #3 require the documented path/surface table to
    live somewhere stable. The runtime path is wired into the advisory's
    rendered output via `docs/RELEASE_IMPACT.md`; if that file is renamed
    or removed, this test flags the drift."""
    repo_root = HERE.parents[3]
    doc = repo_root / "docs" / "RELEASE_IMPACT.md"
    assert doc.is_file(), f"expected {doc} to exist for F003 acceptance"
    text = doc.read_text()
    # The doc must mention each known surface id so docs/runtime stay
    # in lockstep.
    for surface in release_impact.SURFACES:
        assert surface in text, f"docs/RELEASE_IMPACT.md missing surface id {surface!r}"


def test_root_changelog_exists_and_references_shared() -> None:
    """Acceptance #1: root CHANGELOG.md exists and explains its
    relationship to claude/shared/CHANGELOG.md."""
    repo_root = HERE.parents[3]
    changelog = repo_root / "CHANGELOG.md"
    assert changelog.is_file(), "root CHANGELOG.md must exist (F003 acceptance #1)"
    text = changelog.read_text()
    assert "claude/shared/CHANGELOG.md" in text, (
        "root CHANGELOG.md must reference claude/shared/CHANGELOG.md"
    )


# ─────────────────────────  plan-lock secondary-surface emission  ─────────────────────────


def test_plan_lock_release_impact_helper_emits_advisory(
    tmp_path: Path, capsys
) -> None:
    """F003 acceptance #5: `dontpanic plan lock` is the secondary advisory
    surface. The helper extracts plan intent + (optional) git diff paths and
    prints a release-impact advisory to stdout. No sidecar is written; the
    helper must not raise on a plan with no git history."""
    from dontpanic_orchestrate import cli as cli_module

    plans_root = tmp_path / "docs" / "plans"
    plan_dir = _write_plan(
        plans_root,
        "2026-05-23-300-feat-lock-emission",
        surfaces=["ux"],
        allowed_paths=["dashboard/**"],
        feature_steps=["Edit dashboard/index.html to add a tab."],
    )

    # tmp_path is not a git repo; the helper must still emit a draft-intent
    # advisory and not raise.
    cli_module._emit_plan_lock_release_impact_advisory(plan_dir)
    captured = capsys.readouterr()
    assert "[release-impact]" in captured.out, (
        f"expected [release-impact] block in stdout, got: {captured.out!r}"
    )
    assert "dashboard" in captured.out, (
        f"expected 'dashboard' surface mentioned, got: {captured.out!r}"
    )
    # No sidecar must land on disk inside the plan dir.
    sidecars = [
        p.name
        for p in plan_dir.iterdir()
        if "release" in p.name.lower() or "impact" in p.name.lower()
    ]
    assert sidecars == [], f"plan-lock advisory must not write a sidecar; saw {sidecars}"


def test_plan_lock_release_impact_helper_silent_for_intentless_plan(
    tmp_path: Path, capsys
) -> None:
    """An intent-less plan (no surfaces, narrow internal allowed_paths, no
    git diff) produces no actionable advice. The helper either prints
    nothing or an internal-only acknowledgement — but never an empty bullet
    list."""
    from dontpanic_orchestrate import cli as cli_module

    plans_root = tmp_path / "docs" / "plans"
    plan_dir = _write_plan(
        plans_root,
        "2026-05-23-301-feat-no-intent-lock",
        surfaces=[],
        allowed_paths=["docs/synthetic/**"],
        feature_steps=["work on internal-only logic"],
    )
    cli_module._emit_plan_lock_release_impact_advisory(plan_dir)
    out = capsys.readouterr().out
    # Either silent or an internal-only one-liner; must NOT advise root_changelog.
    if "[release-impact]" in out:
        assert (
            "internal-only" in out
            or "no public-surface" in out
            or "no advisory inputs" in out
        ), f"unexpected advisory body for intentless plan: {out!r}"


def test_git_changed_paths_for_lock_returns_empty_outside_repo(
    tmp_path: Path,
) -> None:
    """Helper must tolerate plan_dir outside any git repo (returns []), so
    plan lock works on freshly-extracted plan archives."""
    from dontpanic_orchestrate import cli as cli_module

    plan_dir = tmp_path / "isolated-plan"
    plan_dir.mkdir()
    assert cli_module._git_changed_paths_for_lock(plan_dir) == []
