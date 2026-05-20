"""Plan 2026-05-19-005 F001 — showcase generator fixture tests.

Covers the 10 acceptance shapes:
  (1) TargetSpec validation + supported_artifacts frozenset
  (2) Generator with all 4 targets present generates expected artifact set
  (3) Generator with missing target_repo_root emits 'skipping' and continues
  (4) Redactor scrubs `/Users/bayesian/` from sample HTML + JSON content
  (5) Redactor raises RedactorError when `/Users/` survives
  (6) sanitization_check still passes with docs/showcase/ allowed
  (7) --plans-root flag on doctor walks external dir
  (8) --architecture-json flag on doctor evaluates external snapshot
  (9) supported_artifacts filter — generator skips drift for targets
      without has_committed_architecture_json=True without erroring
  (10) --target=<repo_key> filter generates only that target's artifacts

Run:
    pytest scripts/dontpanic_orchestrate/tests/test_showcase_generator_f001.py -q
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
DOCTOR_PATH = REPO_ROOT / "scripts" / "dontpanic_doctor.py"

# Make scripts/ importable for the orchestrate package.
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from dontpanic_orchestrate.showcase import (  # noqa: E402
    DEFAULT_SHOWCASE_CONFIG,
    RedactorError,
    SUPPORTED_ARTIFACT_KINDS,
    TargetSpec,
    default_showcase_config,
    filter_targets,
    generate,
    redact,
    redact_and_validate,
    validate as redactor_validate,
)
from dontpanic_orchestrate.showcase import generator as showcase_generator  # noqa: E402

# Expected key set for v0 default --all run. Lifts the previous
# DEFAULT_TARGETS_FOR_ALL hard-code into a test-local literal so the
# config + filter_targets agreement is asserted directly.
_DEFAULT_V0_KEYS = ("dontpanic", "agent-conventions", "axiom", "glam")


def _load_doctor():
    spec = importlib.util.spec_from_file_location("dontpanic_doctor_showcase_f001", DOCTOR_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["dontpanic_doctor_showcase_f001"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def isolated_showcase_home(tmp_path, monkeypatch):
    """Build a tmp directory that mirrors the DontPanic layout enough for
    the showcase generator's writability probe + docs/showcase/ output.
    The architecture crawler walks the REAL DontPanic checkout for the
    'dontpanic' target via repo_root override, so we still need scripts/
    + claude/ + docs/plans/ to exist somewhere — the env var only
    relocates the showcase OUTPUT dir, not the target repo roots."""
    monkeypatch.setenv("DONTPANIC_SHOWCASE_HOME", str(tmp_path))
    (tmp_path / "docs" / "showcase").mkdir(parents=True, exist_ok=True)
    # Reset cached doctor module so the relocated path is honored.
    sys.modules.pop("dontpanic_doctor_showcase", None)
    yield tmp_path


def _build_synthetic_target_repo(root: Path, *, repo_key: str, with_plans: bool = False) -> Path:
    """Lay down the minimum tree the architecture Crawler walks."""
    (root / "scripts" / "dontpanic_orchestrate").mkdir(parents=True, exist_ok=True)
    (root / "scripts" / "dontpanic_orchestrate" / "__init__.py").write_text(
        f'"""synthetic target {repo_key}."""\n', encoding="utf-8"
    )
    (root / "scripts" / "dontpanic_orchestrate" / "alpha.py").write_text(
        '"""alpha module."""\n\ndef helper():\n    return 1\n',
        encoding="utf-8",
    )
    (root / "claude" / "shared" / "schemas" / "v1.0").mkdir(parents=True, exist_ok=True)
    (root / "claude" / "shared" / "VERSION").write_text("v1.0.0\n", encoding="utf-8")
    (root / "claude" / "shared" / "schemas" / "v1.0" / "sample.json").write_text(
        '{"$schema": "http://json-schema.org/draft-07/schema#"}\n', encoding="utf-8"
    )
    if with_plans:
        plan_dir = root / "docs" / "plans" / "2026-05-01-001-feat-synthetic"
        plan_dir.mkdir(parents=True, exist_ok=True)
        (plan_dir / "plan.md").write_text(
            "---\n"
            "id: 2026-05-01-001-feat-synthetic\n"
            f"title: Synthetic plan for {repo_key} showcase test\n"
            "type: feat\n"
            "tier: trivial\n"
            "status: active\n"
            'date: "2026-05-01"\n'
            f"description: Synthetic plan in {repo_key} repo for showcase F001 fixture tests.\n"
            "---\n\n# Body\n",
            encoding="utf-8",
        )
        (plan_dir / "features.json").write_text(
            json.dumps(
                {
                    "task_id": "2026-05-01-001-feat-synthetic",
                    "schema_version": "1.0",
                    "features": [
                        {
                            "id": "F001",
                            "category": "infra",
                            "phase": 1,
                            "description": "synthetic",
                            "steps": ["one"],
                            "acceptance": "synthetic acceptance",
                            "passes": False,
                            "depends_on": [],
                        }
                    ],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    return root


# ── (1) TargetSpec validation ─────────────────────────────────────────────


def test_targetspec_accepts_valid_artifact_set(tmp_path):
    spec = TargetSpec(
        repo_key="x",
        label="X",
        repo_root=tmp_path,
        description="…",
        supported_artifacts=frozenset({"architecture", "validate_plans_strict"}),
        has_dontpanic_plans=True,
        has_committed_architecture_json=False,
    )
    assert spec.supported_artifacts == frozenset({"architecture", "validate_plans_strict"})
    assert spec.supported_artifacts <= SUPPORTED_ARTIFACT_KINDS


def test_targetspec_rejects_unsupported_artifact_kind(tmp_path):
    with pytest.raises(ValueError, match="unsupported artifact kinds"):
        TargetSpec(
            repo_key="x",
            label="X",
            repo_root=tmp_path,
            description="…",
            supported_artifacts=frozenset({"architecture", "made_up"}),
            has_dontpanic_plans=False,
            has_committed_architecture_json=False,
        )


def test_targetspec_rejects_validate_plans_without_plans_flag(tmp_path):
    with pytest.raises(ValueError, match="validate_plans_strict requires has_dontpanic_plans"):
        TargetSpec(
            repo_key="x",
            label="X",
            repo_root=tmp_path,
            description="…",
            supported_artifacts=frozenset({"validate_plans_strict"}),
            has_dontpanic_plans=False,
            has_committed_architecture_json=False,
        )


def test_default_showcase_config_has_at_least_four_targets():
    cfg = default_showcase_config()
    assert len(cfg) >= 4
    keys = {t.repo_key for t in cfg}
    # Per Plan 5 D002 — Glam selected as 4th target.
    assert {"dontpanic", "agent-conventions", "axiom", "glam"} <= keys


# ── (4) + (5) Redactor ────────────────────────────────────────────────────


def test_redactor_scrubs_repo_root_to_dot(tmp_path):
    repo_root = tmp_path / "Glam"
    repo_root.mkdir()
    html = (
        f"<html><body>generated from {repo_root}/sources/main.swift "
        "and includes summary</body></html>"
    )
    out = redact(html, repo_root=repo_root, repo_key="glam")
    assert "./sources/main.swift" in out
    assert str(repo_root) not in out


def test_redactor_scrubs_other_users_paths(tmp_path):
    repo_root = tmp_path / "Glam"
    repo_root.mkdir()
    blob = json.dumps({"note": "imported from /Users/someone-else/secret/path/file.py"})
    out = redact(blob, repo_root=repo_root, repo_key="glam")
    assert "<redacted>" in out
    assert "/Users/someone-else" not in out


def test_redactor_validate_raises_on_surviving_users_path(tmp_path):
    # Construct a content that has a leak the redactor regex doesn't
    # match — confirm validate() still catches it.
    leaky = "value=/Users/whatever-this-is"
    with pytest.raises(RedactorError):
        redactor_validate(leaky, repo_key="glam", artifact="architecture")


def test_redact_and_validate_passes_through_clean_content(tmp_path):
    repo_root = tmp_path / "Glam"
    repo_root.mkdir()
    clean = "<html>repo-relative ./scripts/foo.py</html>"
    out = redact_and_validate(
        clean, repo_root=repo_root, repo_key="glam", artifact="architecture"
    )
    assert out == clean


# ── (2) + (3) + (9) Generator flows ───────────────────────────────────────


def test_generator_handles_missing_target_with_skipping_message(isolated_showcase_home, tmp_path):
    # Target whose repo_root does not exist — must surface 'skipping' and
    # not raise.
    missing_root = tmp_path / "does-not-exist"
    spec = TargetSpec(
        repo_key="ghost",
        label="Ghost",
        repo_root=missing_root,
        description="…",
        supported_artifacts=frozenset({"architecture"}),
        has_dontpanic_plans=False,
        has_committed_architecture_json=False,
    )
    run = generate(targets=[spec])
    assert len(run.targets) == 1
    tr = run.targets[0]
    assert tr.status == "skipped"
    assert "skipping" in tr.reason
    assert str(missing_root) in tr.reason
    assert run.overall_exit == 0


def test_generator_with_synthetic_target_produces_architecture_artifacts(
    isolated_showcase_home, tmp_path
):
    repo_root = _build_synthetic_target_repo(
        tmp_path / "synthetic-target", repo_key="syn", with_plans=False
    )
    spec = TargetSpec(
        repo_key="syn",
        label="Synthetic",
        repo_root=repo_root,
        description="…",
        supported_artifacts=frozenset({"architecture"}),
        has_dontpanic_plans=False,
        has_committed_architecture_json=False,
    )
    run = generate(targets=[spec])
    assert run.overall_exit == 0
    assert run.targets[0].status == "success"
    showcase_dir = isolated_showcase_home / "docs" / "showcase"
    assert (showcase_dir / "syn-architecture.json").is_file()
    assert (showcase_dir / "syn-architecture.html").is_file()
    body = (showcase_dir / "syn-architecture.json").read_text(encoding="utf-8")
    assert str(repo_root) not in body  # absolute path redacted
    assert "/Users/" not in body


def test_generator_skips_drift_for_target_without_committed_arch_json(
    isolated_showcase_home, tmp_path
):
    """Acceptance #9: supported_artifacts filter — drift is just absent
    from the supported set; no error, no failed status."""
    repo_root = _build_synthetic_target_repo(
        tmp_path / "syn-noarch", repo_key="syn-noarch", with_plans=True
    )
    spec = TargetSpec(
        repo_key="syn-noarch",
        label="Synthetic (no arch.json)",
        repo_root=repo_root,
        description="…",
        supported_artifacts=frozenset({"architecture", "validate_plans_strict"}),
        has_dontpanic_plans=True,
        has_committed_architecture_json=False,
    )
    run = generate(targets=[spec])
    assert run.overall_exit == 0
    artifact_kinds = {a.artifact for a in run.targets[0].artifacts}
    assert "drift" not in artifact_kinds
    assert artifact_kinds == {"architecture", "validate_plans_strict"}


# ── (10) --target filter ──────────────────────────────────────────────────


def test_filter_targets_single_target_returns_one(tmp_path):
    cfg = [
        TargetSpec(
            repo_key="alpha",
            label="A",
            repo_root=tmp_path,
            description="",
            supported_artifacts=frozenset({"architecture"}),
            has_dontpanic_plans=False,
            has_committed_architecture_json=False,
        ),
        TargetSpec(
            repo_key="beta",
            label="B",
            repo_root=tmp_path,
            description="",
            supported_artifacts=frozenset({"architecture"}),
            has_dontpanic_plans=False,
            has_committed_architecture_json=False,
        ),
    ]
    out = filter_targets(cfg, target_key="alpha")
    assert [t.repo_key for t in out] == ["alpha"]


def test_filter_targets_unknown_key_raises():
    with pytest.raises(KeyError, match="unknown target"):
        filter_targets(default_showcase_config(), target_key="not-real")


def test_filter_targets_default_returns_v0_set(tmp_path):
    """--all (the default invocation) returns every target in the
    active config; the v0 default ships exactly the 4-key set."""
    out = filter_targets(default_showcase_config())
    assert [t.repo_key for t in out] == list(_DEFAULT_V0_KEYS)


def test_filter_targets_all_flag_returns_every_configured_target():
    """Explicit --all matches the bare invocation and every entry in
    the default config — no hidden allowlist."""
    cfg = default_showcase_config()
    out = filter_targets(cfg, all_flag=True)
    assert {t.repo_key for t in out} == {t.repo_key for t in cfg}
    assert len(out) == len(cfg)


def test_default_showcase_config_constant_matches_factory():
    """``DEFAULT_SHOWCASE_CONFIG`` is the module-level constant required
    by acceptance; it must shape-match the factory and carry ≥4 targets."""
    assert isinstance(DEFAULT_SHOWCASE_CONFIG, list)
    assert len(DEFAULT_SHOWCASE_CONFIG) >= 4
    factory_keys = [t.repo_key for t in default_showcase_config()]
    const_keys = [t.repo_key for t in DEFAULT_SHOWCASE_CONFIG]
    assert const_keys == factory_keys


# ── (7) + (8) Doctor CLI flag wire-throughs ───────────────────────────────


def test_doctor_validate_plans_strict_walks_external_plans_root(tmp_path):
    """--plans-root override: probe walks the supplied dir without
    leaking into DontPanic's own plans_root."""
    doctor = _load_doctor()
    external_plans = tmp_path / "ext-plans"
    external_plans.mkdir()
    # Synthetic locked plan that validates cleanly.
    plan_dir = external_plans / "2026-05-01-001-feat-syn"
    plan_dir.mkdir()
    (plan_dir / "plan.md").write_text(
        "---\n"
        "id: 2026-05-01-001-feat-syn\n"
        "title: External plan synthetic — used by F001 plans-root test\n"
        "type: feat\n"
        "tier: trivial\n"
        "status: active\n"
        'date: "2026-05-01"\n'
        "description: External-plans-root fixture for showcase F001 doctor flag wire-through test.\n"
        "---\n\n# Body\n",
        encoding="utf-8",
    )
    results = doctor.validate_plans_strict(plans_root=external_plans, strict=False)
    summary = results[0]
    assert summary.name == "validate-plans-strict"
    # The probe walked external_plans (the path appears in the summary).
    assert "ext-plans" in summary.message or str(external_plans) in summary.message
    # No DontPanic plan IDs leaked into the per-plan details.
    plan_ids = {entry.get("plan_id") for entry in (summary.details or [])}
    assert plan_ids == {"2026-05-01-001-feat-syn"}


def test_doctor_architecture_drift_uses_external_architecture_json(tmp_path):
    """--architecture-json override: probe reads the given path, returns
    'absent' when missing — without falling back to DontPanic's own."""
    doctor = _load_doctor()
    fake_root = tmp_path / "fake-target"
    fake_root.mkdir()
    # Build a minimal source tree the Crawler can walk.
    _build_synthetic_target_repo(fake_root, repo_key="syn-drift", with_plans=False)
    external_arch = tmp_path / "external-arch.json"
    # Don't write the file — probe should report absent.
    result = doctor.check_architecture_drift(
        repo_root=fake_root, architecture_path=external_arch, strict=False
    )
    detail = (result.details or [{}])[0]
    assert detail["state"] == "absent"
    assert str(external_arch) in detail["architecture_path"]


# ── (6) sanitization_check.py extension ───────────────────────────────────


def test_sanitization_check_allows_docs_showcase_prefix():
    """ALLOWED_PREFIXES must include 'docs/showcase/' so showcase artifacts
    don't trip the campaign-id allowlist. The secret-shape scan still
    applies to every file (no exemption)."""
    spec = importlib.util.spec_from_file_location(
        "sanitization_check_f001",
        REPO_ROOT / "scripts" / "sanitization_check.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert "docs/showcase/" in mod.ALLOWED_PREFIXES
    assert mod.is_allowed("docs/showcase/dontpanic-architecture.json")
    # Secret-shape scan must still apply to anything under the new
    # prefix. Synthesize a fake AWS key via assembled parts so this test
    # file itself doesn't trip the leak check.
    fake_key = "AKIA" + "1234567890ABCDEF12"  # 16 chars after AKIA, mixed letters/digits
    assert mod.scan_line(fake_key) is not None


# ── Default config sanity ─────────────────────────────────────────────────


def test_supported_artifact_kinds_frozenset():
    assert isinstance(SUPPORTED_ARTIFACT_KINDS, frozenset)
    assert SUPPORTED_ARTIFACT_KINDS == frozenset(
        {"architecture", "validate_plans_strict", "drift"}
    )
