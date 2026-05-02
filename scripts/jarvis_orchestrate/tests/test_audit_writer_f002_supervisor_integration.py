"""F002 — synthetic supervisor integration tests.

Acceptance #9 (target-context-platform-fix plan):
  case-a-shaped envelope round-trips through a real supervisor volley
  iteration with prelude injected; case-d-shaped envelope causes
  supervisor to raise + exit non-zero.

The unit tests in `test_audit_writer_normalize.py` exercise
`audit_writer.write` directly. These tests exercise the full supervisor
path that calls audit_writer, using scripted executors registered in
the agent registry — same pattern as `test_volley_synthetic.py`.

Run: PYTHONPATH=scripts pytest scripts/jarvis_orchestrate/tests/test_audit_writer_f002_supervisor_integration.py
"""

from __future__ import annotations

import datetime as dt
import importlib
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from jarvis_orchestrate import audit_writer, cli, plan_loader, supervisor  # noqa: E402
from jarvis_orchestrate.executors import AGENT_REGISTRY  # noqa: E402
from jarvis_orchestrate.executors.base import (  # noqa: E402
    BaseExecutor,
    DispatchResult,
    DispatchTask,
)
from jarvis_orchestrate.target_context_prelude import TargetContextError  # noqa: E402

PRELUDE_HEADER = "## Target context\n"


def _iso_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ──────────────────────  scripted executor (mirrors test_volley_synthetic) ──────────────────────


class _ScriptedExecutor(BaseExecutor):
    """Returns a summary string verbatim. Successful dispatch (no error)."""

    def __init__(self, agent: str, summary: str) -> None:
        super().__init__()
        self.agent_name = agent
        self.cli_binary = None
        self._summary = summary
        self.dispatch_count = 0

    def is_available(self) -> bool:
        return True

    def dispatch(self, task: DispatchTask) -> DispatchResult:
        self.dispatch_count += 1
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
    plan_id = "2026-04-25-003-infra-f002-supervisor-integration"
    plan_dir = tmp_dir / "docs" / "plans" / plan_id
    plan_dir.mkdir(parents=True)

    plan_md = f"""---
id: {plan_id}
title: F002 supervisor integration test plan
type: infra
tier: trivial
status: active
date: "2026-04-25"
description: Synthetic test plan exercising audit_writer.write through a real volley round.
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

# F002 supervisor integration test plan

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
                "description": "Synthetic feature exercising audit_writer.write through a volley round.",
                "steps": ["scripted implementer", "scripted auditor"],
                "acceptance": "Round-tripped audit carries the canonical D001 prelude.",
                "passes": False,
                "depends_on": [],
            }
        ],
    }

    (plan_dir / "plan.md").write_text(plan_md)
    (plan_dir / "features.json").write_text(
        json.dumps(features, indent=2, ensure_ascii=False, sort_keys=False) + "\n"
    )
    return plan_dir


def _disable_quota_gate() -> None:
    """Skip the live quota state read so the volley path doesn't depend on
    ~/.jarvis/quota_state.json existing in the test runner's home dir."""
    supervisor._quota_gate = lambda agent: (None, f"[quota] {agent}: bypassed for synthetic test")


def _register_scripted(
    impl_summary: str, aud_summary: str
) -> tuple[_ScriptedExecutor, _ScriptedExecutor]:
    impl = _ScriptedExecutor("claude", impl_summary)
    aud = _ScriptedExecutor("codex", aud_summary)
    AGENT_REGISTRY["claude"] = lambda i=impl: i  # type: ignore[assignment]
    AGENT_REGISTRY["codex"] = lambda a=aud: a  # type: ignore[assignment]
    return impl, aud


@pytest.fixture(autouse=True)
def _restore_supervisor_module():
    """Each test isolates supervisor module state — the quota-gate patch and
    AGENT_REGISTRY shims are reverted after the test runs."""
    yield
    importlib.reload(supervisor)


# ──────────────────────  case-a: roundtrip prelude injection  ──────────────────────


def test_case_a_supervisor_roundtrip_injects_prelude() -> None:
    """Acceptance #9 (case-a half): a real supervisor volley round whose
    scripted implementer summary lacks the canonical prelude — F002 fires
    via audit_writer.write inside _run_round and the persisted audit's
    summary opens with `## Target context\\n`."""
    impl_summary = (
        "F001 complete: scripted implementer returned this summary with NO "
        "canonical target-context prelude block. The struct field is still "
        "populated by the supervisor (target_env=dev, target_project=none) "
        "so F002 must inject the prelude on write.\n\n"
        "$ pytest scripts/jarvis_orchestrate/tests/test_audit_writer_normalize.py -q"
    )
    aud_summary = (
        "Verdict: signed_off. Scripted auditor — no findings.\n\n"
        "$ rg -n 'def _normalize_summary' scripts/jarvis_orchestrate/audit_writer.py"
    )
    assert not impl_summary.startswith(PRELUDE_HEADER)
    assert not aud_summary.startswith(PRELUDE_HEADER)

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        plan_dir = _make_test_plan(tmp)

        _register_scripted(impl_summary, aud_summary)
        _disable_quota_gate()

        result = supervisor.dispatch_volley(plan_dir, "F001", max_iterations=1)

        # Volley produced the implementer + auditor audits.
        impl_audits = sorted((plan_dir / "audit").glob("claude-implementer-i*.json"))
        assert len(impl_audits) >= 1, f"no implementer audit landed: {result}"

        impl = json.loads(impl_audits[0].read_text())
        # F002 contract: persisted summary opens with the canonical header.
        assert impl["summary"].startswith(PRELUDE_HEADER), impl["summary"][:120]
        # Exactly one canonical header (no double-injection).
        assert impl["summary"].count(PRELUDE_HEADER) == 1
        # Body suffix preserved verbatim.
        assert impl_summary in impl["summary"], (
            "scripted body must survive verbatim after prelude prepend"
        )
        # The struct that drove the injection rendered Env: dev.
        assert "- Env: dev\n" in impl["summary"][: len(PRELUDE_HEADER) + 200]

        # Auditor audit also gets the prelude (auditor role → also routed
        # through audit_writer.write with target_context=dev/none).
        aud_audits = sorted((plan_dir / "audit").glob("codex-auditor-i*.json"))
        assert len(aud_audits) >= 1, "no auditor audit landed"
        aud = json.loads(aud_audits[0].read_text())
        assert aud["summary"].startswith(PRELUDE_HEADER)
        assert aud["summary"].count(PRELUDE_HEADER) == 1


# ──────────────────────  case-d: missing target_context raises + no file lands  ──────────────────────


def test_case_d_supervisor_missing_target_context_raises_no_file_landed() -> None:
    """Acceptance #9 (case-d half): a real supervisor volley round whose
    audit dict lacks `target_context` (struct absent — case-d shape) MUST
    cause `audit_writer.write` to raise `TargetContextError` from inside
    the supervisor cycle, AND the implementer audit file MUST NOT land.

    Simulation: monkey-patch `audit_writer.build_audit` to drop the
    `target_context` field after construction. This mirrors a legacy
    envelope that pre-dates the F023 EC6 schema field — exactly the
    case-d shape from F001's fixtures.
    """
    impl_summary = (
        "F001 complete: scripted implementer summary. Target context field "
        "will be stripped by the test harness to simulate a case-d envelope."
    )
    aud_summary = "Verdict: signed_off."

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        plan_dir = _make_test_plan(tmp)
        audit_dir = plan_dir / "audit"

        _register_scripted(impl_summary, aud_summary)
        _disable_quota_gate()

        # Drop target_context from the built audit dict to force case-d.
        original_build_audit = audit_writer.build_audit

        def _strip_target_context(*args: Any, **kwargs: Any) -> dict[str, Any]:
            built = original_build_audit(*args, **kwargs)
            built.pop("target_context", None)
            return built

        supervisor.audit_writer.build_audit = _strip_target_context  # type: ignore[assignment]

        try:
            with pytest.raises(TargetContextError) as exc_info:
                supervisor.dispatch_volley(plan_dir, "F001", max_iterations=1)
        finally:
            supervisor.audit_writer.build_audit = original_build_audit

        # The raised error must carry the audit_id + plan_id context that F002
        # wraps around the underlying validator message.
        msg = str(exc_info.value)
        assert "envelope" in msg and "for plan" in msg, msg
        assert plan_loader.load(plan_dir).plan_id in msg, msg

        # No implementer/auditor audit file landed (no partial artifact).
        if audit_dir.exists():
            stragglers = sorted(audit_dir.iterdir())
        else:
            stragglers = []
        assert stragglers == [], (
            f"case-d must produce no audit files; got {[p.name for p in stragglers]}"
        )


def test_case_d_cli_main_returns_nonzero_on_invalid_target_context() -> None:
    """Acceptance #9 (case-d, exit-code half): the CLI entrypoint surface
    `cli.main([...])` MUST return a non-zero exit code when a case-d-shaped
    envelope (target_context absent) propagates `TargetContextError` out
    of `audit_writer.write` during the supervisor's volley cycle.

    Goes through `cli.main(...)` end-to-end (per Codex i1 auditor spec):
    constructs a real plan dir, registers scripted executors, simulates
    the case-d shape by stripping `target_context` from the audit dict
    after `build_audit`, then invokes `cli.main` with the same argv
    shape `python -m jarvis_orchestrate <plan> --volley` would parse.
    `TargetContextError` is a `ValueError` subclass; the cli's volley
    error path catches `(FileNotFoundError, KeyError, ValueError,
    RuntimeError)` and returns 1 — that is the exit-code surface."""
    impl_summary = "F001 scripted implementer."
    aud_summary = "Verdict."

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        plan_dir = _make_test_plan(tmp)

        _register_scripted(impl_summary, aud_summary)
        _disable_quota_gate()

        original_build_audit = audit_writer.build_audit

        def _strip_target_context(*args: Any, **kwargs: Any) -> dict[str, Any]:
            built = original_build_audit(*args, **kwargs)
            built.pop("target_context", None)
            return built

        supervisor.audit_writer.build_audit = _strip_target_context  # type: ignore[assignment]

        try:
            rc = cli.main(
                [
                    str(plan_dir),
                    "--volley",
                    "--feature",
                    "F001",
                    "--max-iterations",
                    "1",
                ]
            )
        finally:
            supervisor.audit_writer.build_audit = original_build_audit

        assert rc != 0, f"cli.main must return non-zero on case-d; got rc={rc}"

        # No implementer audit landed (no-partial-artifact contract carried
        # through from audit_writer.write into the CLI surface).
        audit_dir = plan_dir / "audit"
        if audit_dir.exists():
            stragglers = sorted(p.name for p in audit_dir.iterdir())
        else:
            stragglers = []
        assert stragglers == [], (
            f"case-d via cli.main must produce no audit files; got {stragglers}"
        )
