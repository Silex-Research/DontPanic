"""Fixture tests for plan 2026-05-19-004 F004 — supervisor regen-to-working-tree hook.

Covers the acceptance criteria:
  (a) regen fires when an architecture-relevant file is committed
  (b) regen does NOT fire when only docs/ (non-plan) files commit
  (c) regen does NOT auto-commit (`git diff --staged` is empty after the hook)
  (d) INBOX architecture_regenerated event is emitted with expected fields
  (e) regen failure is logged + does not crash the volley terminal
  (f) commit_policy.mode != child_commit is a no-op
  (g) state_transition tag fires fresh→fresh / stale→fresh / absent→fresh

Tests drive :func:`architecture_regen_hook.maybe_regen_after_commit`
directly against a tmp_path git repo. The supervisor wiring above
``dispatch_volley`` is a one-liner around the same helper, so behavioural
coverage at the hook boundary is sufficient — and avoids the dependency
weight of stubbing the full implementer/auditor pair just to land on the
``signed_off`` branch.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from dontpanic_orchestrate import architecture as arch
from dontpanic_orchestrate import architecture_regen_hook as hook
from dontpanic_orchestrate import inbox

REPO_ROOT = Path(__file__).resolve().parents[3]


# ── Fixtures ───────────────────────────────────────────────────────────────


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.setdefault("GIT_AUTHOR_NAME", "Test")
    env.setdefault("GIT_AUTHOR_EMAIL", "test@example.com")
    env.setdefault("GIT_COMMITTER_NAME", "Test")
    env.setdefault("GIT_COMMITTER_EMAIL", "test@example.com")
    return subprocess.run(
        ["git", *args],
        cwd=str(repo),
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )


def _build_synthetic_repo(root: Path) -> None:
    """Lay down a DontPanic-shaped tree the crawler can snapshot."""
    modules = root / "scripts" / "dontpanic_orchestrate"
    modules.mkdir(parents=True)
    (modules / "__init__.py").write_text('"""synthetic"""\n', encoding="utf-8")
    (modules / "supervisor.py").write_text(
        '"""supervisor"""\n\ndef dispatch():\n    return True\n', encoding="utf-8"
    )
    (modules / "audit_writer.py").write_text(
        '"""audit"""\n\ndef write_audit(p):\n    return p\n', encoding="utf-8"
    )

    schemas = root / "claude" / "shared" / "schemas" / "v1.0"
    schemas.mkdir(parents=True)
    (root / "claude" / "shared" / "VERSION").write_text("1.0.0\n", encoding="utf-8")
    (schemas / "plan.schema.json").write_text(
        json.dumps({"$id": "plan", "type": "object"}, sort_keys=True), encoding="utf-8"
    )

    # A plan dir that's NOT the focal plan (so its plan.md is part of the
    # snapshot but the focal plan's INBOX lives elsewhere).
    other_plan = root / "docs" / "plans" / "2026-05-19-100-feat-alpha"
    other_plan.mkdir(parents=True)
    (other_plan / "plan.md").write_text(
        "---\nid: 2026-05-19-100-feat-alpha\ntitle: Alpha\nstatus: active\n---\n",
        encoding="utf-8",
    )
    (other_plan / "features.json").write_text(
        json.dumps({"task_id": "2026-05-19-100-feat-alpha", "features": [{"id": "F001"}]}),
        encoding="utf-8",
    )


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _build_synthetic_repo(repo)
    _git(repo, "init", "--quiet", "--initial-branch=main")
    _git(repo, "add", ".")
    _git(repo, "commit", "--quiet", "-m", "init")
    # Seed an architecture.json so we can observe state_transition + diffs.
    arch.regen(repo, with_html=False)
    _git(repo, "add", "docs/architecture/architecture.json")
    _git(repo, "commit", "--quiet", "-m", "seed snapshot")
    return repo


@pytest.fixture()
def focal_plan_dir(git_repo: Path) -> Path:
    """Plan dir for the in-flight F004 fixture — separate from the seeded
    'alpha' plan so the INBOX assertions are unambiguous."""
    plan_dir = git_repo / "docs" / "plans" / "2026-05-19-004-feat-arch-regen-target"
    plan_dir.mkdir(parents=True)
    (plan_dir / "plan.md").write_text(
        "---\nid: 2026-05-19-004-feat-arch-regen-target\ntitle: Target\nstatus: active\n---\n",
        encoding="utf-8",
    )
    return plan_dir


# ── Tests ──────────────────────────────────────────────────────────────────


def test_a_regen_fires_on_architecture_relevant_commit(
    git_repo: Path, focal_plan_dir: Path
) -> None:
    """Touching a `scripts/dontpanic_orchestrate/**` file in the latest
    commit must trigger an architecture regen."""
    target = git_repo / "scripts" / "dontpanic_orchestrate" / "supervisor.py"
    target.write_text(target.read_text(encoding="utf-8") + "\n# drift A\n", encoding="utf-8")
    _git(git_repo, "add", "scripts/dontpanic_orchestrate/supervisor.py")
    _git(git_repo, "commit", "--quiet", "-m", "edit relevant")

    snap_path = git_repo / "docs" / "architecture" / "architecture.json"
    snap_before = snap_path.read_bytes()

    result = hook.maybe_regen_after_commit(
        plan_dir=focal_plan_dir,
        plan_id="2026-05-19-004-feat-arch-regen-target",
        feature_id="F004",
        commit_policy_mode="child_commit",
        repo_root=git_repo,
    )
    assert result is not None, "hook must fire when relevant file is committed"
    assert "scripts/dontpanic_orchestrate/supervisor.py" in result["matched_files"]
    assert result["state_transition"].endswith("->fresh")

    snap_after = snap_path.read_bytes()
    assert snap_after != snap_before, "architecture.json should be rewritten"


def test_b_no_regen_when_only_non_relevant_docs_commit(
    git_repo: Path, focal_plan_dir: Path
) -> None:
    """A commit that only touches docs/ outside of plans/ must NOT
    trigger regen."""
    (git_repo / "docs" / "notes.md").parent.mkdir(parents=True, exist_ok=True)
    (git_repo / "docs" / "notes.md").write_text("hello\n", encoding="utf-8")
    _git(git_repo, "add", "docs/notes.md")
    _git(git_repo, "commit", "--quiet", "-m", "non-relevant doc")

    snap_path = git_repo / "docs" / "architecture" / "architecture.json"
    snap_before = snap_path.read_bytes()

    result = hook.maybe_regen_after_commit(
        plan_dir=focal_plan_dir,
        plan_id="2026-05-19-004-feat-arch-regen-target",
        feature_id="F004",
        commit_policy_mode="child_commit",
        repo_root=git_repo,
    )
    assert result is None, "hook must be a no-op for non-relevant commits"
    assert snap_path.read_bytes() == snap_before
    assert not (focal_plan_dir / "INBOX.md").exists()


def test_c_regen_does_not_stage_or_commit_the_map(
    git_repo: Path, focal_plan_dir: Path
) -> None:
    """CRITICAL invariant: after the hook fires, `git diff --staged`
    must be empty (no architecture.json staged) and HEAD must not
    contain architecture.json in the just-created commit either."""
    target = git_repo / "scripts" / "dontpanic_orchestrate" / "supervisor.py"
    target.write_text(target.read_text(encoding="utf-8") + "\n# drift C\n", encoding="utf-8")
    _git(git_repo, "add", "scripts/dontpanic_orchestrate/supervisor.py")
    _git(git_repo, "commit", "--quiet", "-m", "trigger regen")

    head_files_before = _git(
        git_repo, "show", "--name-only", "--pretty=", "HEAD"
    ).stdout
    assert "docs/architecture/architecture.json" not in head_files_before, (
        "test setup invariant — pre-hook commit must not include arch.json"
    )

    result = hook.maybe_regen_after_commit(
        plan_dir=focal_plan_dir,
        plan_id="2026-05-19-004-feat-arch-regen-target",
        feature_id="F004",
        commit_policy_mode="child_commit",
        repo_root=git_repo,
    )
    assert result is not None

    staged = _git(git_repo, "diff", "--name-only", "--cached").stdout.strip()
    assert staged == "", f"hook must not stage anything; got: {staged!r}"

    # HEAD is unchanged after the hook (no new commit).
    head_files_after = _git(
        git_repo, "show", "--name-only", "--pretty=", "HEAD"
    ).stdout
    assert head_files_after == head_files_before
    assert "docs/architecture/architecture.json" not in head_files_after

    # The regenerated file IS in the working tree (unstaged change).
    unstaged = _git(git_repo, "status", "--porcelain").stdout
    assert "docs/architecture/architecture.json" in unstaged


def test_d_inbox_event_emitted_with_expected_fields(
    git_repo: Path, focal_plan_dir: Path
) -> None:
    """The hook must emit an INBOX `architecture_regenerated` event with
    fingerprint + delta + count headers."""
    target = git_repo / "scripts" / "dontpanic_orchestrate" / "supervisor.py"
    target.write_text(target.read_text(encoding="utf-8") + "\n# drift D\n", encoding="utf-8")
    _git(git_repo, "add", "scripts/dontpanic_orchestrate/supervisor.py")
    _git(git_repo, "commit", "--quiet", "-m", "edit for inbox")

    result = hook.maybe_regen_after_commit(
        plan_dir=focal_plan_dir,
        plan_id="2026-05-19-004-feat-arch-regen-target",
        feature_id="F004",
        commit_policy_mode="child_commit",
        repo_root=git_repo,
    )
    assert result is not None

    entries = inbox.read_events(focal_plan_dir)
    regen_events = [e for e in entries if e.event == "architecture_regenerated"]
    assert len(regen_events) == 1, f"expected one architecture_regenerated event; got {regen_events}"
    entry = regen_events[0]
    assert entry.plan_id == "2026-05-19-004-feat-arch-regen-target"
    assert entry.headers.get("feature_id") == "F004"
    # Headers carry the fingerprint + counts the operator inspects.
    for required in (
        "prior_fingerprint",
        "new_fingerprint",
        "files_added",
        "files_removed",
        "files_modified",
        "total_modules",
        "total_plans",
        "state_transition",
    ):
        assert required in entry.headers, f"INBOX entry missing header {required!r}: {entry.headers}"
    # supervisor.py edit shows up as a modified file. The focal plan dir
    # itself was created after the seeded fingerprint, so plan.md may also
    # land as files_added — keep the assertion narrow to what we control.
    assert int(entry.headers["files_modified"]) >= 1, entry.headers
    assert int(entry.headers["files_removed"]) == 0, entry.headers
    assert entry.headers["state_transition"] == "stale->fresh"
    assert entry.headers["prior_fingerprint"] != entry.headers["new_fingerprint"]


def test_e_regen_failure_is_logged_and_does_not_raise(
    git_repo: Path, focal_plan_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If `architecture.regen` raises, the hook must catch + emit an
    `architecture_regen_failed` INBOX event and return None. The volley
    terminal would otherwise crash."""
    target = git_repo / "scripts" / "dontpanic_orchestrate" / "supervisor.py"
    target.write_text(target.read_text(encoding="utf-8") + "\n# drift E\n", encoding="utf-8")
    _git(git_repo, "add", "scripts/dontpanic_orchestrate/supervisor.py")
    _git(git_repo, "commit", "--quiet", "-m", "edit for failure")

    def _boom(*args, **kwargs):
        raise RuntimeError("synthetic crawler failure")

    monkeypatch.setattr(hook.architecture, "regen", _boom)

    result = hook.maybe_regen_after_commit(
        plan_dir=focal_plan_dir,
        plan_id="2026-05-19-004-feat-arch-regen-target",
        feature_id="F004",
        commit_policy_mode="child_commit",
        repo_root=git_repo,
    )
    assert result is None, "failure path must return None, not raise"

    entries = inbox.read_events(focal_plan_dir)
    failure_events = [e for e in entries if e.event == "architecture_regen_failed"]
    assert len(failure_events) == 1
    assert failure_events[0].headers.get("error_type") == "RuntimeError"
    # And no successful regen event leaked through.
    assert not any(e.event == "architecture_regenerated" for e in entries)


def test_f_evidence_only_mode_is_a_noop(
    git_repo: Path, focal_plan_dir: Path
) -> None:
    """commit_policy.mode != 'child_commit' (e.g., evidence_only) must
    skip the hook entirely. No INBOX event, no working-tree mutation."""
    target = git_repo / "scripts" / "dontpanic_orchestrate" / "supervisor.py"
    target.write_text(target.read_text(encoding="utf-8") + "\n# drift F\n", encoding="utf-8")
    _git(git_repo, "add", "scripts/dontpanic_orchestrate/supervisor.py")
    _git(git_repo, "commit", "--quiet", "-m", "edit ignored")

    snap_path = git_repo / "docs" / "architecture" / "architecture.json"
    snap_before = snap_path.read_bytes()

    result = hook.maybe_regen_after_commit(
        plan_dir=focal_plan_dir,
        plan_id="2026-05-19-004-feat-arch-regen-target",
        feature_id="F004",
        commit_policy_mode="evidence_only",
        repo_root=git_repo,
    )
    assert result is None
    assert snap_path.read_bytes() == snap_before
    assert not (focal_plan_dir / "INBOX.md").exists()


def test_g_plan_features_json_match_triggers_regen(
    git_repo: Path, focal_plan_dir: Path
) -> None:
    """The `docs/plans/*/features.json` glob must match. The seeded
    alpha plan's features.json is part of the snapshot, so editing +
    committing it triggers regen."""
    feat_path = git_repo / "docs" / "plans" / "2026-05-19-100-feat-alpha" / "features.json"
    payload = json.loads(feat_path.read_text(encoding="utf-8"))
    payload["features"].append({"id": "F002"})
    feat_path.write_text(json.dumps(payload), encoding="utf-8")
    _git(git_repo, "add", "docs/plans/2026-05-19-100-feat-alpha/features.json")
    _git(git_repo, "commit", "--quiet", "-m", "edit features")

    result = hook.maybe_regen_after_commit(
        plan_dir=focal_plan_dir,
        plan_id="2026-05-19-004-feat-arch-regen-target",
        feature_id="F004",
        commit_policy_mode="child_commit",
        repo_root=git_repo,
    )
    assert result is not None
    assert "docs/plans/2026-05-19-100-feat-alpha/features.json" in result["matched_files"]


def test_h_matches_relevant_glob_unit_cases() -> None:
    """Pure unit check on the glob matcher — covers each branch of
    :data:`ARCHITECTURE_RELEVANT_GLOBS` without needing a git tree."""
    assert hook.matches_relevant_glob("scripts/dontpanic_orchestrate/supervisor.py")
    assert hook.matches_relevant_glob("scripts/dontpanic_orchestrate/tests/test_x.py")
    assert hook.matches_relevant_glob("claude/shared/VERSION")
    assert hook.matches_relevant_glob("claude/shared/schemas/v1.0/plan.schema.json")
    assert hook.matches_relevant_glob("docs/plans/2026-05-19-004-feat-x/plan.md")
    assert hook.matches_relevant_glob("docs/plans/2026-05-19-004-feat-x/features.json")
    # Non-matches:
    assert not hook.matches_relevant_glob("docs/notes.md")
    assert not hook.matches_relevant_glob("docs/architecture/architecture.json")
    assert not hook.matches_relevant_glob(
        "docs/plans/2026-05-19-004-feat-x/events.jsonl"
    )
    assert not hook.matches_relevant_glob("README.md")


# ── Supervisor wiring (F004 audit i0 follow-up) ────────────────────────────


def test_i_supervisor_invokes_hook_on_signed_off_branch() -> None:
    """Integration check: walk the AST of `dispatch_volley` and assert that
    the path returning a `signed_off` :class:`VolleyResult` calls
    :func:`architecture_regen_hook.maybe_regen_after_commit` with the
    expected keyword arguments.

    The prior audit (i0) flagged that the hook-only fixture tests would not
    catch a bad import, wrong call placement, or argument-wiring drift in
    ``supervisor.py``. A live ``dispatch_volley`` integration would require
    standing up plan loader, gate state, executor registry, environments
    registry, and CLI quota — heavy machinery for a one-line wiring check.
    An AST inspection of the function body is the minimum-weight test that
    catches all three failure modes the auditor named.
    """
    import ast
    import importlib

    sup_module = importlib.import_module("dontpanic_orchestrate.supervisor")
    source = Path(sup_module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)

    dispatch_volley = next(
        (
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "dispatch_volley"
        ),
        None,
    )
    assert dispatch_volley is not None, "dispatch_volley not found in supervisor.py"

    # Find every Call inside dispatch_volley that targets
    # `maybe_regen_after_commit`. The supervisor imports the hook module
    # lazily inside a try-block, so the call is `_arch_regen_hook.maybe_regen_after_commit(...)`.
    hook_calls: list[ast.Call] = []
    for sub in ast.walk(dispatch_volley):
        if not isinstance(sub, ast.Call):
            continue
        func = sub.func
        if isinstance(func, ast.Attribute) and func.attr == "maybe_regen_after_commit":
            hook_calls.append(sub)
    assert hook_calls, (
        "dispatch_volley must call maybe_regen_after_commit somewhere on the "
        "signed_off branch (audit i0 finding)."
    )

    # Locate the signed_off VolleyResult construction within dispatch_volley.
    # The supervisor returns `_emit_volley_terminal(VolleyResult("signed_off", ...))`
    # at the signed_off terminal.
    signed_off_calls: list[ast.Call] = []
    for sub in ast.walk(dispatch_volley):
        if not isinstance(sub, ast.Call):
            continue
        func = sub.func
        is_volley_result = (
            (isinstance(func, ast.Name) and func.id == "VolleyResult")
            or (isinstance(func, ast.Attribute) and func.attr == "VolleyResult")
        )
        if not is_volley_result:
            continue
        if sub.args and isinstance(sub.args[0], ast.Constant) and sub.args[0].value == "signed_off":
            signed_off_calls.append(sub)
    assert signed_off_calls, "no VolleyResult('signed_off', ...) construction found"

    # Placement: the hook call must precede a signed_off return on the
    # function source. We compare line numbers — the hook fires AFTER the
    # auditor signs off but BEFORE the volley terminal returns.
    earliest_hook_line = min(c.lineno for c in hook_calls)
    earliest_signed_off_line = min(c.lineno for c in signed_off_calls)
    assert earliest_hook_line < earliest_signed_off_line, (
        f"hook call (line {earliest_hook_line}) must precede the signed_off "
        f"VolleyResult (line {earliest_signed_off_line})"
    )

    # Argument wiring: the call MUST pass plan_dir, plan_id, feature_id,
    # commit_policy_mode (the four args the hook needs to function). Any
    # rename or missing arg would silently make the hook a no-op.
    primary = hook_calls[0]
    kwarg_names = {kw.arg for kw in primary.keywords if kw.arg is not None}
    required_kwargs = {"plan_dir", "plan_id", "feature_id", "commit_policy_mode"}
    missing = required_kwargs - kwarg_names
    assert not missing, (
        f"maybe_regen_after_commit call missing required kwargs: {missing}; "
        f"saw {kwarg_names}"
    )

    # `commit_policy_mode` must be sourced from loaded.commit_policy (not a
    # hardcoded literal), otherwise the no-auto-commit invariant could be
    # bypassed for non-child_commit plans.
    commit_policy_kw = next(
        kw for kw in primary.keywords if kw.arg == "commit_policy_mode"
    )
    rendered = ast.unparse(commit_policy_kw.value)
    assert "commit_policy" in rendered, (
        f"commit_policy_mode kwarg must reference loaded.commit_policy.mode; "
        f"got: {rendered!r}"
    )

    # The hook module must be importable as `architecture_regen_hook` from
    # the dontpanic_orchestrate package. A typo in the supervisor's lazy
    # import would crash with ImportError at signed_off time; we surface
    # that here.
    importlib.import_module("dontpanic_orchestrate.architecture_regen_hook")
