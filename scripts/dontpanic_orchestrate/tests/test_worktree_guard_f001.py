"""Guard-hardening F001 — wrong-worktree refusal (plan 2026-06-11-001).

One fail-closed guard precondition shared by plan lock / audit / close /
disposition and the orchestrate dispatch entry: strict registry load
(corrupt is NEVER overridable), realpath-resolved invoking-path identity,
and the canonical v0 binding_health predicate. Overrides exist for the
JUDGMENT classes only and proceed ONLY after the override record AND the
binding snapshot are durably (fsync) written.

All entry-point tests run with the auditor seam STUBBED — a stub that
raises if invoked proves the guard refuses BEFORE any paid/gate work, with
zero live auditor invocations and no network access.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import worktree_guard as wg  # noqa: E402
from dontpanic_orchestrate import worktrees as wt  # noqa: E402

PLAN_ID = "2026-06-11-001-feat-worktree-guard-hardening"


def _git(*args: str, cwd: Path) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    ).stdout.strip()


@pytest.fixture()
def home(tmp_path, monkeypatch):
    h = tmp_path / "dp-home"
    h.mkdir()
    monkeypatch.setenv("DONTPANIC_HOME", str(h))
    monkeypatch.delenv("JARVIS_HOME", raising=False)
    return h


def _make_repo(root: Path) -> Path:
    root.mkdir()
    _git("init", "-q", "-b", "main", cwd=root)
    _git("config", "user.email", "t@e.c", cwd=root)
    _git("config", "user.name", "t", cwd=root)
    (root / "README.md").write_text("x\n")
    plan = root / "docs" / "plans" / PLAN_ID
    plan.mkdir(parents=True)
    (plan / "plan.md").write_text(
        f"""---
id: {PLAN_ID}
title: guard synthetic
type: infra
tier: trivial
status: draft
date: "2026-06-11"
description: Synthetic plan for guard-hardening F001 tests.
agents_required:
  - claude
human_gates: []
loop_caps:
  max_iterations: 1
  hard_stop: false
privacy_tier: internal
links:
  features: ./features.json
---

body

## Target

```yaml
target_env: dev
target_project: synthetic-guard-test
```
"""
    )
    (plan / "features.json").write_text(
        json.dumps(
            {
                "task_id": PLAN_ID,
                "schema_version": "1.0",
                "features": [
                    {
                        "id": "F001",
                        "category": "functional",
                        "description": "synthetic guard fixture feature",
                        "acceptance": "synthetic acceptance for the guard test",
                        "passes": False,
                    }
                ],
            }
        )
        + "\n"
    )
    _git("add", ".", cwd=root)
    _git("-c", "commit.gpgsign=false", "commit", "-qm", "init", cwd=root)
    return root


@pytest.fixture()
def repo(tmp_path):
    return _make_repo(tmp_path / "repo")


def _plan_dir(repo: Path) -> Path:
    return repo / "docs" / "plans" / PLAN_ID


def _bound(repo: Path) -> dict:
    return wt.create_worktree(_plan_dir(repo))


def _overrides(plan_dir: Path) -> list[dict]:
    path = plan_dir / "audit" / wg.OVERRIDE_FILENAME
    if not path.is_file():
        return []
    return [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]


def _snapshots(plan_dir: Path) -> list[dict]:
    path = plan_dir / "audit" / wt.SNAPSHOT_FILENAME
    if not path.is_file():
        return []
    return [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]


class TestGuardCore:
    def test_unbound_plan_passes_through_absent_registry(self, home, repo):
        assert wg.guard_plan_command(_plan_dir(repo), "plan lock") is None

    def test_unbound_plan_passes_through_valid_registry(self, home, repo, tmp_path):
        other = _make_repo(tmp_path / "other-repo")
        plan = other / "docs" / "plans" / PLAN_ID
        wt.create_worktree(plan)
        wt.remove_binding(PLAN_ID)  # leaves a valid (empty) registry file
        assert wt.registry_path().is_file()
        assert wg.guard_plan_command(_plan_dir(repo), "plan lock") is None

    def test_corrupt_registry_fails_closed_never_unbound(self, home, repo):
        wt.registry_path().parent.mkdir(parents=True, exist_ok=True)
        wt.registry_path().write_text("corrupt{")
        with pytest.raises(wt.RegistryCorruptError):
            wg.guard_plan_command(_plan_dir(repo), "plan lock")

    def test_corrupt_registry_rejects_the_override_flag(self, home, repo):
        wt.registry_path().parent.mkdir(parents=True, exist_ok=True)
        wt.registry_path().write_text("corrupt{")
        with pytest.raises(wt.RegistryCorruptError) as exc:
            wg.guard_plan_command(
                _plan_dir(repo), "plan lock", override_reason="please just work"
            )
        assert "never" in str(exc.value).lower()
        assert _overrides(_plan_dir(repo)) == []

    def test_right_worktree_passes(self, home, repo):
        b = _bound(repo)
        wt_plan = Path(b["worktree_path"]) / "docs" / "plans" / PLAN_ID
        result = wg.guard_plan_command(
            wt_plan, "plan lock", invoking_cwd=Path(b["worktree_path"])
        )
        assert result is not None and result["guard"] == "pass"

    def test_wrong_invoking_path_refuses_naming_both_and_commands(self, home, repo):
        b = _bound(repo)
        with pytest.raises(wg.GuardRefusal) as exc:
            wg.guard_plan_command(_plan_dir(repo), "plan lock", invoking_cwd=repo)
        assert exc.value.refusal_class == wg.CLASS_WRONG_PATH
        msg = str(exc.value)
        assert b["worktree_path"] in msg and str(repo.resolve()) in msg
        assert wg.OVERRIDE_FLAG in msg

    def test_symlinked_spelling_of_bound_path_passes(self, home, repo, tmp_path):
        b = _bound(repo)
        link = tmp_path / "wt-symlink"
        link.symlink_to(b["worktree_path"])
        wt_plan = Path(b["worktree_path"]) / "docs" / "plans" / PLAN_ID
        result = wg.guard_plan_command(wt_plan, "plan lock", invoking_cwd=link)
        assert result is not None and result["guard"] == "pass"

    def test_deleted_worktree_refuses_via_health_conjunct(self, home, repo):
        import shutil

        b = _bound(repo)
        shutil.rmtree(b["worktree_path"])
        with pytest.raises(wg.GuardRefusal) as exc:
            wg.guard_plan_command(
                _plan_dir(repo), "plan lock", invoking_cwd=Path(b["worktree_path"]).parent
            )
        assert exc.value.refusal_class in (wg.CLASS_UNHEALTHY, wg.CLASS_WRONG_PATH)
        assert "exist" in str(exc.value) or "worktree" in str(exc.value)

    def test_swapped_repo_at_same_path_and_branch_refuses(self, home, repo, tmp_path):
        import shutil

        b = _bound(repo)
        wt_path = Path(b["worktree_path"])
        shutil.rmtree(wt_path)
        # unrelated repository at the SAME path on the SAME branch name
        imposter = _make_repo(tmp_path / "imposter")
        _git("checkout", "-qb", b["branch"], cwd=imposter)
        shutil.copytree(imposter, wt_path)
        with pytest.raises(wg.GuardRefusal) as exc:
            wg.guard_plan_command(
                wt_path / "docs" / "plans" / PLAN_ID, "plan lock", invoking_cwd=wt_path
            )
        assert exc.value.refusal_class == wg.CLASS_UNHEALTHY
        assert "repo_root" in str(exc.value)

    def test_branch_drift_refuses_through_the_guard(self, home, repo):
        b = _bound(repo)
        wt_path = Path(b["worktree_path"])
        _git("checkout", "-qb", "elsewhere", cwd=wt_path)
        with pytest.raises(wg.GuardRefusal) as exc:
            wg.guard_plan_command(
                wt_path / "docs" / "plans" / PLAN_ID, "plan lock", invoking_cwd=wt_path
            )
        assert exc.value.refusal_class == wg.CLASS_UNHEALTHY
        assert "branch" in str(exc.value)

    def test_detached_head_refuses_through_the_guard(self, home, repo):
        b = _bound(repo)
        wt_path = Path(b["worktree_path"])
        sha = _git("rev-parse", "HEAD", cwd=wt_path)
        _git("checkout", "-q", sha, cwd=wt_path)
        with pytest.raises(wg.GuardRefusal) as exc:
            wg.guard_plan_command(
                wt_path / "docs" / "plans" / PLAN_ID, "plan lock", invoking_cwd=wt_path
            )
        assert exc.value.refusal_class == wg.CLASS_UNHEALTHY
        assert "detached" in str(exc.value)

    def test_non_git_invoking_cwd_is_indeterminate_and_refuses(self, home, repo, tmp_path):
        _bound(repo)
        outside = tmp_path / "not-a-repo"
        outside.mkdir()
        with pytest.raises(wg.GuardRefusal) as exc:
            wg.guard_plan_command(_plan_dir(repo), "plan lock", invoking_cwd=outside)
        assert exc.value.refusal_class == wg.CLASS_INDETERMINATE


class TestOverridePath:
    """The override flag (spelled --override-worktree-guard — D011 disposition
    f-662edc459cc1 discharge) is honoured for the judgment classes only and
    proceeds ONLY after BOTH evidence artifacts are durably written."""

    def _assert_override_evidence(self, plan_dir: Path, cls: str, reason: str):
        recs = _overrides(plan_dir)
        assert len(recs) == 1
        rec = recs[0]
        for field in (
            "plan_id",
            "command",
            "refusal_class",
            "invoking_path",
            "bound_path",
            "reason",
            "actor",
            "recorded_at",
        ):
            assert rec.get(field), f"override record missing {field}"
        assert rec["refusal_class"] == cls and rec["reason"] == reason
        snaps = _snapshots(plan_dir)
        assert len(snaps) >= 1 and snaps[-1]["plan_id"] == PLAN_ID

    def test_wrong_path_override_records_both_artifacts(self, home, repo):
        _bound(repo)
        result = wg.guard_plan_command(
            _plan_dir(repo),
            "plan lock",
            invoking_cwd=repo,
            override_reason="operator accepts the wrong-path risk",
        )
        assert result is not None and result["guard"] == "override"
        self._assert_override_evidence(
            _plan_dir(repo), wg.CLASS_WRONG_PATH, "operator accepts the wrong-path risk"
        )

    def test_unhealthy_binding_override_records_both_artifacts(self, home, repo):
        b = _bound(repo)
        wt_path = Path(b["worktree_path"])
        _git("checkout", "-qb", "elsewhere", cwd=wt_path)
        result = wg.guard_plan_command(
            wt_path / "docs" / "plans" / PLAN_ID,
            "plan lock",
            invoking_cwd=wt_path,
            override_reason="branch drift acknowledged",
        )
        assert result is not None and result["guard"] == "override"
        self._assert_override_evidence(
            wt_path / "docs" / "plans" / PLAN_ID,
            wg.CLASS_UNHEALTHY,
            "branch drift acknowledged",
        )

    def test_indeterminate_override_records_both_artifacts(self, home, repo, tmp_path):
        _bound(repo)
        outside = tmp_path / "not-a-repo"
        outside.mkdir()
        result = wg.guard_plan_command(
            _plan_dir(repo),
            "plan lock",
            invoking_cwd=outside,
            override_reason="indeterminate state acknowledged",
        )
        assert result is not None and result["guard"] == "override"
        self._assert_override_evidence(
            _plan_dir(repo), wg.CLASS_INDETERMINATE, "indeterminate state acknowledged"
        )

    def test_override_requires_a_reason(self, home, repo):
        _bound(repo)
        with pytest.raises((wg.GuardRefusal, ValueError)):
            wg.guard_plan_command(
                _plan_dir(repo), "plan lock", invoking_cwd=repo, override_reason="   "
            )
        assert _overrides(_plan_dir(repo)) == []

    def test_failed_evidence_write_refuses_instead_of_proceeding(
        self, home, repo, monkeypatch
    ):
        _bound(repo)

        def boom(path, record):
            raise OSError("disk full")

        monkeypatch.setattr(wg, "_append_durable", boom)
        with pytest.raises(wg.GuardRefusal) as exc:
            wg.guard_plan_command(
                _plan_dir(repo),
                "plan lock",
                invoking_cwd=repo,
                override_reason="should not proceed",
            )
        assert "evidence" in str(exc.value).lower()

    def test_durable_write_fsyncs(self, home, repo, monkeypatch):
        """Crash-durability contract: the append helper flushes AND fsyncs."""
        import os as _os

        _bound(repo)
        fsynced: list[int] = []
        real_fsync = _os.fsync
        monkeypatch.setattr(wg.os, "fsync", lambda fd: (fsynced.append(fd), real_fsync(fd)))
        wg.guard_plan_command(
            _plan_dir(repo), "plan lock", invoking_cwd=repo, override_reason="fsync probe"
        )
        assert len(fsynced) >= 2  # override record + binding snapshot


class TestEntryPointWiring:
    """Each guarded entry refuses from a wrong checkout BEFORE its gate body
    runs — the auditor/gate seam is stubbed to raise if ever invoked."""

    @pytest.fixture()
    def bound(self, home, repo):
        return _bound(repo), repo

    def _stub(self, monkeypatch, module, attr):
        calls: list = []

        def boom(*a, **k):
            calls.append(1)
            raise AssertionError(f"{attr} must not be invoked when the guard refuses")

        monkeypatch.setattr(module, attr, boom)
        return calls

    def test_plan_lock_refuses_from_wrong_checkout(self, bound, monkeypatch, capsys):
        _, repo = bound
        from dontpanic_orchestrate import cli, sufficiency_gate

        calls = self._stub(monkeypatch, sufficiency_gate, "lock_plan")
        monkeypatch.chdir(repo)
        rc = cli._plan_lock_main([str(_plan_dir(repo))])
        assert rc == 3 and calls == []
        assert "REFUSED" in capsys.readouterr().err

    def test_plan_audit_refuses_with_zero_auditor_invocations(
        self, bound, monkeypatch, capsys
    ):
        _, repo = bound
        from dontpanic_orchestrate import cli

        calls = self._stub(monkeypatch, cli.completion_gate, "audit_plan")
        monkeypatch.chdir(repo)
        rc = cli._plan_audit_main([str(_plan_dir(repo))])
        assert rc == 3 and calls == []
        assert "REFUSED" in capsys.readouterr().err

    def test_plan_close_refuses_with_zero_auditor_invocations(
        self, bound, monkeypatch, capsys
    ):
        _, repo = bound
        from dontpanic_orchestrate import cli

        calls = self._stub(monkeypatch, cli.completion_gate, "close_plan")
        monkeypatch.chdir(repo)
        rc = cli._plan_close_main([str(_plan_dir(repo))])
        assert rc == 3 and calls == []
        assert "REFUSED" in capsys.readouterr().err

    def test_plan_disposition_refuses_before_recording(self, bound, monkeypatch, capsys):
        _, repo = bound
        from dontpanic_orchestrate import cli, sufficiency_convergence

        calls = self._stub(monkeypatch, sufficiency_convergence, "record_disposition")
        monkeypatch.chdir(repo)
        rc = cli._plan_disposition_main(
            [str(_plan_dir(repo)), "--finding", "f-x", "--kind", "deferred_to_impl"]
        )
        assert rc == 3 and calls == []
        assert "REFUSED" in capsys.readouterr().err

    def test_plan_lock_proceeds_from_the_bound_worktree(self, bound, monkeypatch):
        b, repo = bound
        from dontpanic_orchestrate import cli

        wt_path = Path(b["worktree_path"])
        wt_plan = wt_path / "docs" / "plans" / PLAN_ID
        monkeypatch.chdir(wt_path)
        rc = cli._plan_lock_main([str(wt_plan)])
        assert rc == 0
        assert "status: active" in (wt_plan / "plan.md").read_text()

    def test_plan_lock_override_flag_proceeds_with_evidence(
        self, bound, monkeypatch, capsys
    ):
        _, repo = bound
        from dontpanic_orchestrate import cli

        monkeypatch.chdir(repo)
        rc = cli._plan_lock_main(
            [str(_plan_dir(repo)), "--override-worktree-guard", "operator-approved bypass"]
        )
        assert rc == 0
        assert len(_overrides(_plan_dir(repo))) == 1
        assert "status: active" in (_plan_dir(repo) / "plan.md").read_text()

    def test_dispatch_seam_guards_before_capture_and_reconcile(self):
        import inspect

        from dontpanic_orchestrate import supervisor

        src = inspect.getsource(supervisor.dispatch_volley)
        assert "guard_plan_command" in src
        assert src.index("guard_plan_command") < src.index("_wt_capture(")
        assert src.index("_wt_capture(") < src.index("_reconcile_gate_state_or_raise(")

    def test_dispatch_volley_refuses_from_wrong_checkout(self, bound, monkeypatch):
        """Behavioral: dispatch_volley raises the guard refusal from a wrong
        cwd before touching executors or the auditor (stubbed seam)."""
        _, repo = bound
        from dontpanic_orchestrate import supervisor

        monkeypatch.chdir(repo)
        with pytest.raises(wg.GuardRefusal):
            supervisor.dispatch_volley(_plan_dir(repo), "F001")


class TestCommandScoping:
    """Gate-vs-management scoping (D011): worktree create/remove are
    deliberately OUTSIDE the wrong-worktree guard; the plan namespace
    exposes no merge subcommand."""

    def test_worktree_create_runs_unguarded_from_main_checkout(
        self, home, repo, monkeypatch
    ):
        from dontpanic_orchestrate import cli

        monkeypatch.chdir(repo)  # main checkout, not a bound worktree
        rc = cli._plan_worktree_main(["create", str(_plan_dir(repo))])
        assert rc == 0
        assert wt.get_binding(PLAN_ID) is not None

    def test_worktree_namespace_never_calls_the_guard(self):
        import inspect

        from dontpanic_orchestrate import cli

        src = inspect.getsource(cli._plan_worktree_main)
        assert "guard_plan_command" not in src

    def test_plan_namespace_has_no_merge_subcommand(self, capsys):
        from dontpanic_orchestrate import cli

        rc = cli._plan_main(["merge"])
        assert rc == 2
        assert "unknown subcommand" in capsys.readouterr().err
        help_rc = cli._plan_main(["--help"])
        assert help_rc == 2
        assert "merge" not in capsys.readouterr().err.lower()
