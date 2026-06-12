"""Guard-hardening F002 — the 7-step removal algorithm (plan 2026-06-11-001).

One fixture per step's refusal/failure arm, exactly as the locked
acceptance enumerates. The implementation mirrors the numbered structure
(step seams are module functions) so ORDER is checkable, not inferred
from prose. All on temp git repos, no network.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import worktree_remove as wr  # noqa: E402
from dontpanic_orchestrate import worktrees as wt  # noqa: E402

PLAN_ID = "2026-06-10-002-feat-worktree-isolation-v0"


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


@pytest.fixture()
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    _git("init", "-q", "-b", "main", cwd=r)
    _git("config", "user.email", "t@e.c", cwd=r)
    _git("config", "user.name", "t", cwd=r)
    (r / "README.md").write_text("x\n")
    (r / ".gitignore").write_text("environments.json\nlocal-scratch/\n")
    plan = r / "docs" / "plans" / PLAN_ID
    plan.mkdir(parents=True)
    (plan / "plan.md").write_text("---\nid: x\n---\n")
    _git("add", ".", cwd=r)
    _git("-c", "commit.gpgsign=false", "commit", "-qm", "init", cwd=r)
    return r


@pytest.fixture()
def bound(home, repo):
    binding = wt.create_worktree(repo / "docs" / "plans" / PLAN_ID)
    return binding, repo


def _audit_entries() -> list[dict]:
    path = wr.audit_log_path()
    if not path.is_file():
        return []
    return [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]


class TestStep1Registry:
    def test_corrupt_registry_refuses_before_anything(self, home, repo):
        wt.registry_path().parent.mkdir(parents=True, exist_ok=True)
        wt.registry_path().write_text("corrupt{")
        with pytest.raises(wt.RegistryCorruptError):
            wr.remove_worktree(PLAN_ID)
        assert _audit_entries() == []

    def test_no_binding_refuses(self, home, repo):
        with pytest.raises(wr.RemoveRefusal) as exc:
            wr.remove_worktree(PLAN_ID)
        assert exc.value.step == 1


class TestStep2Health:
    def test_each_unhealthy_conjunct_refuses(self, bound):
        binding, repo = bound
        wt_path = Path(binding["worktree_path"])
        _git("checkout", "-qb", "elsewhere", cwd=wt_path)  # branch drift
        with pytest.raises(wr.RemoveRefusal) as exc:
            wr.remove_worktree(PLAN_ID)
        assert exc.value.step == 2 and "branch" in str(exc.value)
        assert wt.get_binding(PLAN_ID) is not None
        assert wt_path.is_dir()

    def test_detached_head_refuses(self, bound):
        binding, repo = bound
        wt_path = Path(binding["worktree_path"])
        sha = _git("rev-parse", "HEAD", cwd=wt_path)
        _git("checkout", "-q", sha, cwd=wt_path)
        with pytest.raises(wr.RemoveRefusal) as exc:
            wr.remove_worktree(PLAN_ID)
        assert exc.value.step == 2 and "detached" in str(exc.value)

    def test_completion_path_missing_worktree_with_intent(self, bound):
        """Missing path + prior removal-INTENT → registry-only delete,
        audited via a completion OUTCOME entry. The SOLE step-2 exception."""
        import shutil

        binding, repo = bound
        wt_path = Path(binding["worktree_path"])
        # simulate a prior run that appended intent then died after the
        # physical removal but before the registry delete
        wr._append_intent(PLAN_ID, binding)
        shutil.rmtree(wt_path)
        result = wr.remove_worktree(PLAN_ID)
        assert result["path"] == "completion"
        assert wt.get_binding(PLAN_ID) is None
        entries = _audit_entries()
        assert entries[-1]["event"] == "removal_outcome"
        assert entries[-1]["completion"] is True
        assert entries[-1]["status"] == "completed_registry_only"

    def test_completion_path_negative_missing_worktree_without_intent(self, bound):
        """Missing path WITHOUT an intent entry → refuses (no carve-out)."""
        import shutil

        binding, repo = bound
        shutil.rmtree(binding["worktree_path"])
        with pytest.raises(wr.RemoveRefusal) as exc:
            wr.remove_worktree(PLAN_ID)
        assert exc.value.step == 2
        assert wt.get_binding(PLAN_ID) is not None


class TestStep3Cleanliness:
    def test_dirty_refuses_listing_paths(self, bound):
        binding, _ = bound
        wt_path = Path(binding["worktree_path"])
        (wt_path / "README.md").write_text("modified\n")
        with pytest.raises(wr.RemoveRefusal) as exc:
            wr.remove_worktree(PLAN_ID)
        assert exc.value.step == 3 and "README.md" in str(exc.value)
        assert wt_path.is_dir() and wt.get_binding(PLAN_ID) is not None

    def test_untracked_only_refuses_listing_paths(self, bound):
        binding, _ = bound
        wt_path = Path(binding["worktree_path"])
        (wt_path / "scratch.txt").write_text("x\n")
        with pytest.raises(wr.RemoveRefusal) as exc:
            wr.remove_worktree(PLAN_ID)
        assert exc.value.step == 3 and "scratch.txt" in str(exc.value)

    def test_gitignored_content_refuses_listing_paths(self, bound):
        """Gitignored files are preserved by default (operator policy D003) —
        git worktree remove would delete them, so their presence REFUSES."""
        binding, _ = bound
        wt_path = Path(binding["worktree_path"])
        (wt_path / "environments.json").write_text("{}\n")
        with pytest.raises(wr.RemoveRefusal) as exc:
            wr.remove_worktree(PLAN_ID)
        assert exc.value.step == 3
        assert "environments.json" in str(exc.value)
        assert (wt_path / "environments.json").is_file()  # preserved

    def test_dirty_submodule_refuses_with_submodule_and_paths(self, bound, tmp_path):
        """D011 disposition f-3bb59beaafe5 discharge — real submodule probe:
        modified/untracked/gitignored content inside a registered submodule
        refuses with the submodule path and offending paths."""
        binding, repo = bound
        wt_path = Path(binding["worktree_path"])
        sub_src = tmp_path / "sub-src"
        sub_src.mkdir()
        _git("init", "-q", "-b", "main", cwd=sub_src)
        _git("config", "user.email", "t@e.c", cwd=sub_src)
        _git("config", "user.name", "t", cwd=sub_src)
        (sub_src / "lib.txt").write_text("lib\n")
        _git("add", ".", cwd=sub_src)
        _git("-c", "commit.gpgsign=false", "commit", "-qm", "sub init", cwd=sub_src)
        subprocess.run(
            [
                "git", "-c", "protocol.file.allow=always",
                "submodule", "add", str(sub_src), "vendor/sub",
            ],
            cwd=wt_path, capture_output=True, text=True, check=True,
        )
        _git("-c", "commit.gpgsign=false", "commit", "-qm", "add submodule", cwd=wt_path)
        (wt_path / "vendor" / "sub" / "untracked-in-sub.txt").write_text("x\n")
        with pytest.raises(wr.RemoveRefusal) as exc:
            wr.remove_worktree(PLAN_ID)
        assert exc.value.step == 3
        msg = str(exc.value)
        assert "vendor/sub" in msg and "untracked-in-sub.txt" in msg

    def test_nested_non_submodule_git_dir_refuses(self, bound):
        binding, _ = bound
        wt_path = Path(binding["worktree_path"])
        nested = wt_path / "local-scratch" / "inner-repo"  # gitignored dir
        nested.mkdir(parents=True)
        _git("init", "-q", cwd=nested)
        with pytest.raises(wr.RemoveRefusal) as exc:
            wr.remove_worktree(PLAN_ID)
        assert exc.value.step == 3 and "inner-repo" in str(exc.value)


class TestStep4Intent:
    def test_unwritable_intent_log_refuses_with_worktree_untouched(
        self, bound, monkeypatch
    ):
        binding, _ = bound
        wt_path = Path(binding["worktree_path"])

        def boom(plan_id, b):
            raise OSError("read-only audit log")

        monkeypatch.setattr(wr, "_append_intent", boom)
        with pytest.raises(wr.RemoveRefusal) as exc:
            wr.remove_worktree(PLAN_ID)
        assert exc.value.step == 4
        assert wt_path.is_dir() and wt.get_binding(PLAN_ID) is not None
        assert _audit_entries() == []  # nothing destructive happened, no audit

    def test_intent_entry_shape_never_claims_success(self, bound):
        binding, _ = bound
        wr._append_intent(PLAN_ID, binding)
        entry = _audit_entries()[0]
        assert entry["event"] == "removal_intent"
        for field in ("plan_id", "worktree_path", "branch", "owner_actor", "removed_by", "intent_at"):
            assert entry.get(field), f"intent entry missing {field}"
        assert "status" not in entry and "success" not in entry


class TestStep5GitRemove:
    def test_git_failure_leaves_binding_intact_with_outcome(self, bound, monkeypatch):
        binding, _ = bound
        wt_path = Path(binding["worktree_path"])

        def boom(b):
            raise wt.WorktreeError("git worktree remove failed (simulated)")

        monkeypatch.setattr(wr, "_git_remove", boom)
        with pytest.raises(wr.RemoveError) as exc:
            wr.remove_worktree(PLAN_ID)
        assert exc.value.step == 5
        assert wt.get_binding(PLAN_ID) is not None  # binding LEFT INTACT
        entries = _audit_entries()
        assert entries[0]["event"] == "removal_intent"
        assert entries[-1]["event"] == "removal_outcome"
        assert entries[-1]["status"] == "failed"
        assert "recovery" in str(exc.value).lower() or "re-run" in str(exc.value).lower()

    def test_no_force_flag_anywhere_on_the_surface(self):
        import inspect

        src = inspect.getsource(wr)
        assert "--force" not in src
        from dontpanic_orchestrate import cli

        cli_src = inspect.getsource(cli._plan_worktree_main)
        assert "--force" not in cli_src


class TestStep6RegistryDelete:
    def test_registry_delete_strictly_follows_physical_removal(self):
        """Order is checkable from the implementation: the registry-delete
        seam call appears AFTER the git-remove seam call in the step body."""
        import inspect

        src = inspect.getsource(wr.remove_worktree)
        s4, s5 = src.index("STEP 4"), src.index("STEP 5")
        s6, s7 = src.index("STEP 6"), src.index("STEP 7")
        assert s4 < s5 < s6 < s7
        assert src.index("_append_intent(", s4) < s5
        assert src.index("_git_remove(", s5) < s6
        assert src.index("_registry_delete(", s6) < s7
        assert src.index("_append_outcome(", s7) > s7

    def test_registry_delete_failure_names_orphan_then_rerun_completes(self, bound):
        binding, _ = bound
        wt_path = Path(binding["worktree_path"])

        def boom(plan_id):
            raise wt.WorktreeError("registry write failed (simulated)")

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(wr, "_registry_delete", boom)
            with pytest.raises(wr.RemoveError) as exc:
                wr.remove_worktree(PLAN_ID)
        assert exc.value.step == 6
        assert PLAN_ID in str(exc.value)
        assert not wt_path.exists()  # physical removal DID happen
        assert wt.get_binding(PLAN_ID) is not None  # orphaned binding named
        # status model renders the orphan as broken — never silent
        model = wt.build_status_model()
        assert model["bindings"][0]["healthy"] is False

        # re-run with the seam restored completes via the step-2 completion path
        result = wr.remove_worktree(PLAN_ID)
        assert result["path"] == "completion"
        assert wt.get_binding(PLAN_ID) is None


class TestStep7Outcome:
    def test_outcome_append_failure_after_success_is_loud_degraded(
        self, bound, monkeypatch
    ):
        """D011 disposition f-bc50262f46e1 discharge — the outcome-append
        failure arm: removal succeeded, the final append fails, the command
        is LOUD (non-zero / typed degraded error naming the state), never
        silent success."""
        binding, _ = bound
        wt_path = Path(binding["worktree_path"])
        real_outcome = wr._append_outcome

        def boom(plan_id, b, **kw):
            raise OSError("disk full at outcome append")

        monkeypatch.setattr(wr, "_append_outcome", boom)
        with pytest.raises(wr.RemoveDegraded) as exc:
            wr.remove_worktree(PLAN_ID)
        msg = str(exc.value)
        assert "succeed" in msg.lower()  # removal succeeded...
        assert "outcome" in msg.lower()  # ...but the outcome record failed
        assert not wt_path.exists()
        assert wt.get_binding(PLAN_ID) is None
        # the intent entry + absent worktree remain the durable evidence
        entries = _audit_entries()
        assert entries[0]["event"] == "removal_intent"

    def test_outcome_append_fsyncs(self, bound, monkeypatch):
        import os as _os

        fsynced: list[int] = []
        real_fsync = _os.fsync
        monkeypatch.setattr(
            wr.os, "fsync", lambda fd: (fsynced.append(fd), real_fsync(fd))
        )
        wr.remove_worktree(PLAN_ID)
        assert len(fsynced) >= 2  # intent + outcome both fsynced


class TestHappyPath:
    def test_remove_succeeds_with_intent_then_outcome_in_order(self, bound):
        binding, _ = bound
        wt_path = Path(binding["worktree_path"])
        result = wr.remove_worktree(PLAN_ID)
        assert result["path"] == "removed"
        assert not wt_path.exists()
        assert wt.get_binding(PLAN_ID) is None
        entries = _audit_entries()
        assert [e["event"] for e in entries] == ["removal_intent", "removal_outcome"]
        assert entries[1]["status"] == "removed"
        # completion-OUTCOME shared writer (D011 f-3bb59beaafe5): one writer,
        # one shape — the success outcome carries completion=False explicitly
        assert entries[1]["completion"] is False

    def test_branch_survives_removal(self, bound):
        """Removal deletes the worktree, never the plan branch — the work
        is preserved for the operator's external merge ritual."""
        binding, repo = bound
        wr.remove_worktree(PLAN_ID)
        assert _git("branch", "--list", binding["branch"], cwd=repo).strip()


class TestCLISurface:
    def test_cli_remove_happy_path(self, bound, capsys):
        from dontpanic_orchestrate import cli

        rc = cli._plan_worktree_main(["remove", PLAN_ID])
        assert rc == 0
        out = capsys.readouterr().out
        assert "removed" in out.lower()

    def test_cli_remove_refusal_exit_3(self, bound, capsys):
        binding, _ = bound
        (Path(binding["worktree_path"]) / "scratch.txt").write_text("x\n")
        from dontpanic_orchestrate import cli

        rc = cli._plan_worktree_main(["remove", PLAN_ID])
        assert rc == 3
        assert "REFUSED" in capsys.readouterr().err

    def test_cli_remove_rejects_force(self, bound):
        from dontpanic_orchestrate import cli

        rc = cli._plan_worktree_main(["remove", PLAN_ID, "--force"])
        assert rc == 2
        assert wt.get_binding(PLAN_ID) is not None

    def test_cli_remove_runs_unguarded_from_main_checkout(self, bound, monkeypatch):
        """Gate-vs-management scoping: remove operates by plan id from any
        checkout (here: the main repo), protected by its own preconditions."""
        binding, repo = bound
        from dontpanic_orchestrate import cli

        monkeypatch.chdir(repo)
        rc = cli._plan_worktree_main(["remove", PLAN_ID])
        assert rc == 0


class TestCloseNeverRemoves:
    def test_plan_close_performs_no_removal(self, bound, monkeypatch):
        """Regression on the close path: close never removes — at most it
        prints the explicit remove command."""
        import inspect

        from dontpanic_orchestrate import cli, completion_gate

        src = inspect.getsource(cli._plan_close_main) + inspect.getsource(
            completion_gate.close_plan
        )
        assert "remove_worktree" not in src
        assert "worktree remove" not in src or "plan worktree remove" in src
