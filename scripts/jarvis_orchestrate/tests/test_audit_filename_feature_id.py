"""Plan 2026-05-02-002 F001 — audit envelope filename includes feature_id.

Run: PYTHONPATH=scripts pytest scripts/jarvis_orchestrate/tests/test_audit_filename_feature_id.py
"""

from __future__ import annotations

import datetime as dt
import importlib
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from jarvis_orchestrate import (  # noqa: E402
    audit_writer,
    circuit_breakers,
    prompts,
    supervisor,
)
from jarvis_orchestrate.executors import AGENT_REGISTRY  # noqa: E402
from jarvis_orchestrate.executors.base import (  # noqa: E402
    BaseExecutor,
    DispatchResult,
    DispatchTask,
)

REPO_ROOT = HERE.parents[3]

# Real plan 005 historical envelope, committed at 836c71d (F001 close-out
# of plan 005). Used by the old-pattern readability proof.
HISTORICAL_005_ENVELOPE = (
    REPO_ROOT
    / "docs"
    / "plans"
    / "2026-05-01-005-feat-target-context-platform-fix"
    / "evidence"
    / "f002"
    / "audit-original-volley"
    / "claude-implementer-i0.json"
)


# ──────────────────────────────  fixture-prep helpers  ──────────────────────────────


def _iso_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _build_minimal_audit(
    *,
    plan_id: str,
    agent: str = "claude",
    role: str = "implementer",
    iteration: int = 0,
    target_env: str = "dev",
    target_project: str | None = None,
) -> dict[str, Any]:
    """Construct a writer-valid audit dict (no fixture sanitization needed).
    Summary already carries the canonical D001 prelude so F002's
    `_normalize_summary` no-ops on it."""
    project_line = target_project if target_project is not None else "(none)"
    summary = (
        f"## Target context\n- Repo: Jarvis\n- Env: {target_env}\n"
        f"- Project: {project_line}\n- Command: 1 (see structured target_context.commands_run)\n\n"
        "[F001] Synthetic audit body for filename test.\n\n"
        "$ pytest -q"
    )
    return {
        "task_id": plan_id,
        "audit_id": f"{plan_id}#{agent}#{iteration}",
        "agent": agent,
        "agent_role": role,
        "model_version": "test-model-v1",
        "iteration": iteration,
        "started_at": _iso_now(),
        "completed_at": _iso_now(),
        "audit_status": "signed_off",
        "findings": [],
        "validation_performed": ["test"],
        "quota_consumed": {"tokens_in": 100, "tokens_out": 50, "api_calls": 1},
        "summary": summary,
        "target_context": {
            "env": target_env,
            "project": target_project,
            "commands_run": ["pytest -q"],
        },
    }


# ──────────────────────────────  filename + collision proof  ──────────────────────────────


def test_filename_includes_feature_id(tmp_path: Path) -> None:
    """Acceptance #1: persisted filename matches
    `{agent}-{role}-{feature_id}-i{n}.json`."""
    audit = _build_minimal_audit(plan_id="2026-05-02-002-fix-audit-envelope-filename")
    out = audit_writer.write(audit, tmp_path, feature_id="F001")
    assert out.name == "claude-implementer-F001-i0.json", out.name


def test_filename_iteration_within_feature(tmp_path: Path) -> None:
    """Acceptance #6: iterations within a single feature still work
    (`-i0`, `-i1`)."""
    plan_id = "2026-05-02-002-fix-audit-envelope-filename"
    a0 = _build_minimal_audit(plan_id=plan_id, iteration=0)
    a1 = _build_minimal_audit(plan_id=plan_id, iteration=1)
    out0 = audit_writer.write(a0, tmp_path, feature_id="F001")
    out1 = audit_writer.write(a1, tmp_path, feature_id="F001")
    assert out0.name == "claude-implementer-F001-i0.json"
    assert out1.name == "claude-implementer-F001-i1.json"
    # Both files coexist (no overwrite between iterations).
    assert out0.exists() and out1.exists()


def test_collision_free_two_features_one_plan(tmp_path: Path) -> None:
    """Acceptance #3: F001 + F002 in same plan_dir produce 4 distinct
    filenames (impl + auditor for each), none overwritten."""
    plan_id = "2026-05-02-002-fix-audit-envelope-filename"
    written: list[Path] = []
    for feature_id in ("F001", "F002"):
        for role in ("implementer", "auditor"):
            agent = "claude" if role == "implementer" else "codex"
            audit = _build_minimal_audit(plan_id=plan_id, agent=agent, role=role, iteration=0)
            written.append(audit_writer.write(audit, tmp_path, feature_id=feature_id))
    audit_dir = tmp_path / "audit"
    listed = sorted(p.name for p in audit_dir.iterdir())
    assert listed == [
        "claude-implementer-F001-i0.json",
        "claude-implementer-F002-i0.json",
        "codex-auditor-F001-i0.json",
        "codex-auditor-F002-i0.json",
    ], listed
    # All 4 files exist on disk (no overwrite between features).
    for p in written:
        assert p.exists(), p


# ──────────────────────────────  feature_id sanitization (acceptance #1, #9)  ──────────────────────────────


@pytest.mark.parametrize(
    "bad_feature_id",
    [
        None,
        "",
        "F1",  # too short
        "F12",  # 2 digits, must be 3
        "F0001",  # 4 digits, must be 3
        "feat-1",  # wrong shape
        "f001",  # lowercase 'f'
        "G001",  # wrong letter
        "F001/../escape",  # path-traversal attempt
        "F001/i0",  # path separator
        "F001\x00",  # NUL byte
        " F001",  # leading whitespace
        "F001 ",  # trailing whitespace
    ],
)
def test_invalid_feature_id_raises_no_partial_artifact(tmp_path: Path, bad_feature_id: Any) -> None:
    """Acceptance #9: invalid feature_id raises ValueError BEFORE any disk
    I/O — `audit_dir` is not created and no files land."""
    audit = _build_minimal_audit(plan_id="2026-05-02-002-fix-audit-envelope-filename")
    audit_dir = tmp_path / "audit"

    with pytest.raises(ValueError):
        audit_writer.write(audit, tmp_path, feature_id=bad_feature_id)

    # No-partial-artifact: writer raised before any mkdir/write_text.
    assert audit_dir.exists() is False, (
        f"audit_dir should not exist after invalid feature_id={bad_feature_id!r}"
    )


def test_valid_feature_id_pattern_matches_features_schema_regex() -> None:
    """The writer's regex must equal the agent-conventions feature-id
    regex (`^F\\d{3}$`). Verified by grepping the schema and the writer
    module."""
    schema_path = REPO_ROOT / "claude" / "shared" / "schemas" / "v1.0" / "features.schema.json"
    schema = json.loads(schema_path.read_text())
    # Schema uses `$ref: "#/$defs/feature"` for the feature item shape;
    # the id pattern lives at `$defs.feature.properties.id.pattern`.
    feature_pattern = schema["$defs"]["feature"]["properties"]["id"]["pattern"]
    assert feature_pattern == r"^F\d{3}$", feature_pattern
    # And the writer module's source contains the same regex literal,
    # so future schema bumps surface as a test-time mismatch (we update
    # both together) rather than as silent drift.
    writer_src = Path(audit_writer.__file__).read_text()
    assert r"^F\d{3}$" in writer_src, (
        "audit_writer.py must use the same regex as features.schema.json"
    )


# ──────────────────────────────  readers + structural no-glob proof  ──────────────────────────────


def test_old_pattern_envelope_remains_readable(tmp_path: Path) -> None:
    """Acceptance #4: a real plan 005 historical envelope (filename at
    the OLD pattern, `claude-implementer-i0.json` — no feature_id
    component) remains readable when supervisor read paths receive a
    Path to it. We exercise:
      * `circuit_breakers.check_diminishing_returns([copy_path])`
      * `circuit_breakers.check_convergence_collapse([copy_path])`
      * `prompts._findings_block(copy_path)`
    None of these depend on filename pattern; all consume the file via
    `json.loads(p.read_text())`."""
    assert HISTORICAL_005_ENVELOPE.exists(), (
        f"missing historical fixture (plan 005 F002 audit-original-volley): {HISTORICAL_005_ENVELOPE}"
    )

    copy_path = tmp_path / "claude-implementer-i0.json"
    shutil.copyfile(HISTORICAL_005_ENVELOPE, copy_path)

    # Single-envelope inputs are below both breakers' minimum window
    # sizes — they should return (False, _) without raising.
    dr_tripped, _ = circuit_breakers.check_diminishing_returns([copy_path])
    cc_tripped, _ = circuit_breakers.check_convergence_collapse([copy_path])
    assert dr_tripped is False
    assert cc_tripped is False

    # _findings_block consumes the file as JSON; on a real envelope it
    # returns either a "(audit_status: ...)" stub or a bullet list.
    rendered = prompts._findings_block(copy_path)
    assert rendered, "renders to non-empty string"
    assert "could not read audit file" not in rendered, rendered


def test_no_filename_pattern_globs_in_readers() -> None:
    """Acceptance #5: structural test — no production reader code uses
    `glob`/`rglob`/`iterdir` against `audit/` with a filename pattern
    that would discriminate against the new feature-id-bearing names.

    This is intentionally conservative: we allow `iterdir` and `glob`
    if they exist in non-orchestrate modules, but flag them in the
    write/read paths the supervisor uses for audit envelopes.
    """
    # Inspect the modules that consume audit envelopes for forbidden
    # filename-shape patterns. These regexes name the OLD audit filename
    # shape — if any source contains them, the reader is fragile to the
    # filename change and must be updated.
    forbidden_filename_regexes = [
        re.compile(r"-i\\?d\+\\?\.json"),  # `-i\d+\.json`
        re.compile(r"-implementer-i"),  # hand-rolled prefix matching
        re.compile(r"-auditor-i"),
    ]
    consumer_modules = [
        REPO_ROOT / "scripts" / "jarvis_orchestrate" / "circuit_breakers.py",
        REPO_ROOT / "scripts" / "jarvis_orchestrate" / "prompts.py",
        REPO_ROOT / "scripts" / "jarvis_orchestrate" / "supervisor.py",
        REPO_ROOT / "scripts" / "jarvis_orchestrate" / "transcript.py",
    ]
    for module in consumer_modules:
        src = module.read_text()
        for pat in forbidden_filename_regexes:
            assert not pat.search(src), (
                f"{module.name} contains a hard-coded old-filename pattern "
                f"({pat.pattern!r}) — readers must not depend on filename shape"
            )


# ──────────────────────────────  both supervisor dispatch paths (acceptance #2)  ──────────────────────────────


class _ScriptedExecutor(BaseExecutor):
    """Mirror of the scripted executor in test_volley_synthetic — returns
    a fixed summary verbatim. The summary already carries the canonical
    target-context prelude so F002 _normalize_summary no-ops on it."""

    def __init__(self, agent: str, summary: str) -> None:
        super().__init__()
        self.agent_name = agent
        self.cli_binary = None
        self._summary = summary

    def is_available(self) -> bool:
        return True

    def dispatch(self, task: DispatchTask) -> DispatchResult:
        return DispatchResult(
            agent=self.agent_name,
            agent_role=task.agent_role,
            iteration=task.iteration,
            started_at=_iso_now(),
            completed_at=_iso_now(),
            success=True,
            summary=self._summary,
            model_version=None,
            raw_response=self._summary,
            quota_consumed={"tokens_in": 100, "tokens_out": 50},
        )


def _make_test_plan(tmp_dir: Path) -> Path:
    plan_id = "2026-04-25-003-infra-filename-feature-id"
    plan_dir = tmp_dir / "docs" / "plans" / plan_id
    plan_dir.mkdir(parents=True)

    plan_md = f"""---
id: {plan_id}
title: filename feature_id integration test plan
type: infra
tier: trivial
status: active
date: "2026-04-25"
description: Synthetic test plan for feature_id-bearing audit filenames.
agents_required:
  - claude
  - codex
loop_caps:
  max_iterations: 1
  hard_stop: false
privacy_tier: internal
links:
  features: ./features.json
---

# filename feature_id integration test plan

## Target

```yaml
target_env: dev
target_project: none
```
"""
    features = {
        "task_id": plan_id,
        "schema_version": "1.0",
        "features": [
            {
                "id": "F001",
                "category": "test",
                "phase": 0,
                "description": "Synthetic feature for filename test.",
                "steps": ["scripted impl", "scripted aud"],
                "acceptance": "Persisted filenames carry feature_id.",
                "passes": False,
                "depends_on": [],
            },
            {
                "id": "F002",
                "category": "test",
                "phase": 1,
                "description": "Second synthetic feature for collision test.",
                "steps": ["scripted impl", "scripted aud"],
                "acceptance": "Distinct filename from F001.",
                "passes": False,
                "depends_on": ["F001"],
            },
        ],
    }
    (plan_dir / "plan.md").write_text(plan_md)
    (plan_dir / "features.json").write_text(
        json.dumps(features, indent=2, ensure_ascii=False, sort_keys=False) + "\n"
    )
    return plan_dir


def _disable_quota_gate() -> None:
    supervisor._quota_gate = lambda agent: (
        None,
        f"[quota] {agent}: bypassed for synthetic test",
    )


def _register_scripted(impl_summary: str, aud_summary: str) -> None:
    impl = _ScriptedExecutor("claude", impl_summary)
    aud = _ScriptedExecutor("codex", aud_summary)
    AGENT_REGISTRY["claude"] = lambda i=impl: i  # type: ignore[assignment]
    AGENT_REGISTRY["codex"] = lambda a=aud: a  # type: ignore[assignment]


@pytest.fixture(autouse=True)
def _restore_supervisor_module():
    yield
    importlib.reload(supervisor)


def test_dispatch_volley_writes_filename_with_feature_id() -> None:
    """Acceptance #2 (volley path): supervisor.dispatch_volley persists
    audit envelopes with feature_id in the filename."""
    impl_summary = (
        "## Target context\n- Repo: Jarvis\n- Env: dev\n- Project: (none)\n"
        "- Command: 1 (see structured target_context.commands_run)\n\n"
        "[F001] scripted body.\n\n$ pytest -q"
    )
    aud_summary = (
        "## Target context\n- Repo: Jarvis\n- Env: dev\n- Project: (none)\n"
        "- Command: 1 (see structured target_context.commands_run)\n\n"
        "Verdict: signed_off.\n\n$ rg -n test"
    )
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        plan_dir = _make_test_plan(tmp)
        _register_scripted(impl_summary, aud_summary)
        _disable_quota_gate()

        supervisor.dispatch_volley(plan_dir, "F001", max_iterations=1)

        names = sorted(p.name for p in (plan_dir / "audit").glob("*.json"))
        # Expect filenames carrying F001 (volley persists impl + auditor each round).
        assert any(n.startswith("claude-implementer-F001-i") for n in names), names
        assert any(n.startswith("codex-auditor-F001-i") for n in names), names


def test_dispatch_single_agent_writes_filename_with_feature_id() -> None:
    """Acceptance #2 (single-agent path): supervisor.dispatch_single_agent
    persists audit envelope with feature_id in the filename."""
    impl_summary = (
        "## Target context\n- Repo: Jarvis\n- Env: dev\n- Project: (none)\n"
        "- Command: 1 (see structured target_context.commands_run)\n\n"
        "[F001] scripted single-agent body.\n\n$ pytest -q"
    )
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        plan_dir = _make_test_plan(tmp)
        _register_scripted(impl_summary, "(unused)")
        _disable_quota_gate()

        out_path = supervisor.dispatch_single_agent(
            plan_dir=plan_dir,
            feature_id="F001",
            agent_role="implementer",
            iteration=0,
        )
        assert out_path.name == "claude-implementer-F001-i0.json", out_path.name


def test_collision_free_two_features_via_supervisor() -> None:
    """Acceptance #2 + #3 end-to-end: dispatching F001 then F002 against
    the same plan dir leaves both features' envelopes coexisting."""
    impl_summary = (
        "## Target context\n- Repo: Jarvis\n- Env: dev\n- Project: (none)\n"
        "- Command: 1 (see structured target_context.commands_run)\n\n"
        "scripted body.\n\n$ pytest -q"
    )
    aud_summary = (
        "## Target context\n- Repo: Jarvis\n- Env: dev\n- Project: (none)\n"
        "- Command: 1 (see structured target_context.commands_run)\n\n"
        "Verdict: signed_off.\n\n$ rg -n test"
    )
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        plan_dir = _make_test_plan(tmp)
        _register_scripted(impl_summary, aud_summary)
        _disable_quota_gate()

        supervisor.dispatch_volley(plan_dir, "F001", max_iterations=1)
        supervisor.dispatch_volley(plan_dir, "F002", max_iterations=1)

        names = sorted(p.name for p in (plan_dir / "audit").glob("*.json"))
        # Each feature contributed at least an implementer and auditor envelope.
        assert any("F001" in n for n in names), names
        assert any("F002" in n for n in names), names
        # No collision: the two features' impl/auditor envelopes have distinct names.
        assert len({n for n in names if "implementer" in n}) >= 2
        assert len({n for n in names if "auditor" in n}) >= 2
