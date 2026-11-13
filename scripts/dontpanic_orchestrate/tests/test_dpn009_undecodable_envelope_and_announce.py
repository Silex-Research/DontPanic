"""DPN-009 — undecodable auditor envelopes disqualify a successor; a durable
signoff survives a failed success announcement.

Finding 1 (Grok tiebreak on #98): ``_latest_auditor_by_completed_at`` used to
SKIP an auditor envelope that was not valid UTF-8, not valid JSON (a torn /
truncated in-place write), not a JSON object, or unreadable. A later, broken
envelope for a feature could then leave an OLDER signed_off envelope as that
feature's "latest", so a stale successor still counted. Such a file now
disqualifies the successor (fail closed).

Finding 2 (CodeRabbit on #97, supervisor:1759): the deferred success
announcement runs after ``signoff.json`` is durable; if it raised, the
``dispatch_volley`` backstop emitted a ``blocked`` terminal and rewrote the
signoff as blocked. A failed success announcement is now a warning only.

Real code paths throughout: successor fixtures are written by the REAL
``signoff_writer`` with the same shapes as the DP-003 / DPN-011 successor
tests, and the supervisor tests run the REAL ``_emit_volley_terminal`` /
``dispatch_volley`` with the deterministic executors of the DP-003 harness.
The only injected faults are at the announcement boundary (INBOX append /
notification dispatch) and the signoff writer boundary.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import (  # noqa: E402
    inbox,
    nested_orchestration,
    plan_loader,
    signed_off_finalizer,
    signoff_writer,
    supervisor,
)
from dontpanic_orchestrate.patch_completeness_gate import PatchCompletenessError  # noqa: E402
from dontpanic_orchestrate.tests import test_dp003_signoff_integrity as dp3  # noqa: E402

# Fixtures reused from the DP-003 module (same registry isolation and the same
# deterministic executor / quota / local-notification harness).
repo = dp3.repo
captured = dp3.captured

CHILD_ID = dp3.CHILD_ID
PARENT_ID = dp3.PARENT_ID
SUCCESSOR_ID = dp3._SUCCESSOR_ID
TOP_ID = dp3.TOP_ID


# ───────────────────────── Finding 1 — successor fixtures ─────────────────────────


def _successor_with_signed_off_i0(repo: Path, *, summary: str | None = None) -> tuple[Path, Path]:
    """Single-feature satisfied successor (``requires: [tests_pass]``): an
    F001 i0 volley signed_off and listed by a CURRENT, digest-bound signoff
    from the real writer, with its bound side-car. ``summary`` overrides the
    auditor's summary text (written as UTF-8) BEFORE the signoff is written.
    Returns ``(successor_dir, i0_auditor)``."""
    succ = dp3._child_successor(repo, [dp3._feature("F001", "Successor feature one.")])
    t = dp3._base_time()
    impl, aud = dp3._volley(succ, "F001", 0, "signed_off", t)
    if summary is not None:
        env = json.loads(aud.read_text(encoding="utf-8"))
        env["summary"] = summary
        env["findings"] = [{"severity": "info", "note": summary}]
        aud.write_bytes(json.dumps(env, ensure_ascii=False).encode("utf-8"))
    dp3._write_successor_signoff(succ, [impl, aud], iteration=0)
    signoff = json.loads(signoff_writer.signoff_path(succ, SUCCESSOR_ID).read_text())
    assert signoff["signoff"] is True and signoff["next_action"] == "merge"
    assert aud.name in [Path(a).name for a in signoff["audits"]]
    assert isinstance(signoff.get("audit_digests"), dict) and signoff["audit_digests"]
    side = json.loads(dp3._side_car(succ, SUCCESSOR_ID).read_text())
    assert side["return_condition_status"] == "satisfied"
    assert side["signoff_id"] == signoff["signoff_id"]
    return succ, aud


def _later_auditor_path(succ: Path) -> Path:
    """The auditor-named path for a LATER (i1) F001 volley."""
    return succ / "audit" / "codex-auditor-F001-i1.json"


def _is_successor(succ: Path) -> bool:
    return signed_off_finalizer._is_satisfied_successor(
        succ, parent_plan_id=PARENT_ID, acceptance_item="parent acceptance #1"
    )


def _assert_not_successor_and_finalize_refused(repo: Path, succ: Path) -> None:
    assert _is_successor(succ) is False
    plan_dir = dp3._superseded_child_with_signoff(repo)
    dp3._assert_refused(plan_dir, CHILD_ID, "child_not_satisfied")


def _assert_successor_and_finalize_accepted(repo: Path, succ: Path) -> None:
    assert _is_successor(succ) is True
    plan_dir = dp3._superseded_child_with_signoff(repo)
    fin = signed_off_finalizer.finalize_signed_off_feature(
        plan_dir, plan_id=CHILD_ID, feature_id="F001"
    )
    assert fin.features_passes_flipped is True
    assert dp3._passes(plan_dir) is True


# (a) torn write → invalid UTF-8
def test_dpn009_later_invalid_utf8_auditor_envelope_disqualifies_successor(repo: Path) -> None:
    succ, _i0 = _successor_with_signed_off_i0(repo)
    bad = _later_auditor_path(succ)
    bad.write_bytes(b'{"verdict": "blocked", "completed_at": "\xff\xfe')
    with pytest.raises(UnicodeDecodeError):
        bad.read_bytes().decode("utf-8")
    _assert_not_successor_and_finalize_refused(repo, succ)


# (b) valid UTF-8 but truncated JSON
def test_dpn009_later_truncated_json_auditor_envelope_disqualifies_successor(repo: Path) -> None:
    succ, _i0 = _successor_with_signed_off_i0(repo)
    bad = _later_auditor_path(succ)
    bad.write_bytes(b'{"verdict": "blocked", "comp')
    with pytest.raises(json.JSONDecodeError):
        json.loads(bad.read_bytes().decode("utf-8"))
    _assert_not_successor_and_finalize_refused(repo, succ)


# (c) valid JSON, not an object
@pytest.mark.parametrize("payload", [b"[]", b'"x"', b"null", b"42"])
def test_dpn009_later_non_object_auditor_envelope_disqualifies_successor(
    repo: Path, payload: bytes
) -> None:
    succ, _i0 = _successor_with_signed_off_i0(repo)
    bad = _later_auditor_path(succ)
    bad.write_bytes(payload)
    assert not isinstance(json.loads(payload.decode("utf-8")), dict)
    _assert_not_successor_and_finalize_refused(repo, succ)


# (d) unreadable auditor-named file (chmod 000; restored in finally)
@pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0, reason="root can read chmod-000 files"
)
def test_dpn009_later_unreadable_auditor_envelope_disqualifies_successor(repo: Path) -> None:
    succ, _i0 = _successor_with_signed_off_i0(repo)
    bad = _later_auditor_path(succ)
    bad.write_text(json.dumps({"audit_status": "blocked"}))
    os.chmod(bad, 0)
    try:
        # Precondition: the file is genuinely unreadable for this process
        # (not running as root), so the refusal comes from the OSError branch.
        with pytest.raises(PermissionError):
            bad.read_bytes()
        _assert_not_successor_and_finalize_refused(repo, succ)
    finally:
        os.chmod(bad, 0o644)


def test_dpn009_latest_helper_raises_naming_path_and_reason(tmp_path: Path) -> None:
    """Unit-level: each unreadable/undecodable kind raises ``_NoLatestAuditor``
    naming the path and the reason (never skipped). The OSError case uses a
    directory passed straight to the helper — root-independent."""
    good = tmp_path / "codex-auditor-F001-i0.json"
    good.write_text(
        json.dumps({"audit_status": "signed_off", "completed_at": "2026-11-12T00:00:00Z"})
    )
    cases = {
        "codex-auditor-F001-i1.json": (
            b'{"verdict": "blocked", "completed_at": "\xff\xfe',
            "not valid UTF-8",
        ),
        "codex-auditor-F001-i2.json": (b'{"verdict": "blocked", "comp', "not valid JSON"),
        "codex-auditor-F001-i3.json": (b"[]", "not a JSON object"),
    }
    for name, (payload, reason) in cases.items():
        bad = tmp_path / name
        bad.write_bytes(payload)
        with pytest.raises(signed_off_finalizer._NoLatestAuditor) as exc:
            signed_off_finalizer._latest_auditor_by_completed_at([good, bad])
        assert str(bad) in str(exc.value) and reason in str(exc.value), str(exc.value)
        bad.unlink()
    unreadable = tmp_path / "codex-auditor-F001-i4.json"
    unreadable.mkdir()
    with pytest.raises(signed_off_finalizer._NoLatestAuditor) as exc:
        signed_off_finalizer._latest_auditor_by_completed_at([good, unreadable])
    assert str(unreadable) in str(exc.value) and "cannot be read" in str(exc.value)
    # Non-auditor names are still ignored (name filter unchanged).
    other = tmp_path / "claude-implementer-F001-i1.json"
    other.write_bytes(b"\xff\xfe")
    latest = signed_off_finalizer._latest_auditor_by_completed_at([good, other])
    assert latest is not None and latest[0] == good


# (e) valid UTF-8 non-ASCII text is still a successor
_NON_ASCII_SUMMARY = "Revue validée — tout est bon ✅ 🚀 (naïve café)"


def test_dpn009_non_ascii_utf8_latest_envelope_still_successor(repo: Path) -> None:
    """Positive control (in-process): a signed_off, listed, current latest
    envelope whose text is non-ASCII UTF-8 is still a successor."""
    succ, aud = _successor_with_signed_off_i0(repo, summary=_NON_ASCII_SUMMARY)
    raw = aud.read_bytes()
    assert _NON_ASCII_SUMMARY.encode("utf-8") in raw
    with pytest.raises(UnicodeDecodeError):
        raw.decode("ascii")
    _assert_successor_and_finalize_accepted(repo, succ)


_ASCII_LOCALE_PROBE = textwrap.dedent(
    """
    import json, locale, sys
    from pathlib import Path
    from dontpanic_orchestrate import signed_off_finalizer
    succ = Path(sys.argv[1])
    print(json.dumps({
        "encoding": locale.getpreferredencoding(False),
        "utf8_mode": sys.flags.utf8_mode,
        "successor": signed_off_finalizer._is_satisfied_successor(
            succ, parent_plan_id=sys.argv[2], acceptance_item="parent acceptance #1"
        ),
    }))
    """
)


def test_dpn009_non_ascii_utf8_envelope_successor_under_ascii_locale(repo: Path) -> None:
    """Locale independence: the same non-ASCII UTF-8 successor is judged in a
    fresh interpreter whose default text encoding is ASCII (``LC_ALL=C``,
    locale coercion and UTF-8 mode disabled). Decoding must be explicit
    UTF-8, so it is still a successor. (Monkeypatching ``locale`` in-process
    cannot affect ``open()``'s C-level default, hence the subprocess.)"""
    succ, _aud = _successor_with_signed_off_i0(repo, summary=_NON_ASCII_SUMMARY)
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "PYTHONPATH": str(HERE.parents[2]),
        "LC_ALL": "C",
        "LANG": "C",
        "PYTHONCOERCECLOCALE": "0",
        "PYTHONUTF8": "0",
        "TMPDIR": os.environ.get("TMPDIR", "/tmp"),
    }
    proc = subprocess.run(
        [sys.executable, "-X", "utf8=0", "-c", _ASCII_LOCALE_PROBE, str(succ), PARENT_ID],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    # Precondition: the child really decodes default text as ASCII.
    assert out["utf8_mode"] == 0
    assert out["encoding"].lower().replace("-", "") in {"usascii", "ascii", "ansi_x3.41968"}, out
    assert out["successor"] is True, out


# (f) positive control: no bad file
def test_dpn009_successor_without_bad_file_accepted(repo: Path) -> None:
    succ, _i0 = _successor_with_signed_off_i0(repo)
    assert not _later_auditor_path(succ).exists()
    _assert_successor_and_finalize_accepted(repo, succ)


# ───────────────────────── Finding 2 — announce failure after durable signoff ─────────────────────────


def _signoff(plan_dir: Path, plan_id: str = TOP_ID) -> dict[str, Any]:
    return json.loads(signoff_writer.signoff_path(plan_dir, plan_id).read_text())


def _terminal_statuses(plan_dir: Path) -> list[str | None]:
    return [e.headers.get("final_status") for e in dp3._terminal_inbox(plan_dir)]


def _fail_success_announcement(
    monkeypatch: pytest.MonkeyPatch, where: str, captured: list[Any]
) -> list[str]:
    """Make the SUCCESS announcement fail once at ``where``:

    * ``"notify"`` — the INBOX success event is written, then the
      notification dispatch raises (partial failure);
    * ``"inbox"`` — the INBOX append raises (nothing announced).

    Non-success announcements are untouched. Returns a list that records
    each injected failure."""
    fired: list[str] = []
    if where == "notify":
        recorder = supervisor.notify_event.dispatch_event

        def _flaky_dispatch(event: Any, **kw: Any) -> Any:
            if getattr(event, "kind", None) == "signoff" and not fired:
                fired.append("notify")
                raise RuntimeError("notification sink down (injected)")
            return recorder(event, **kw)

        monkeypatch.setattr(supervisor.notify_event, "dispatch_event", _flaky_dispatch)
    else:
        real_append = inbox.append_event

        def _flaky_append(plan_dir: Path, *, event: str, **kw: Any) -> Any:
            if event == "volley_terminal" and kw.get("final_status") == "signed_off" and not fired:
                fired.append("inbox")
                raise OSError(28, "No space left on device (injected)")
            return real_append(plan_dir, event=event, **kw)

        monkeypatch.setattr(supervisor.inbox, "append_event", _flaky_append)
    return fired


# (g) real _emit_volley_terminal
@pytest.mark.parametrize("where", ["notify", "inbox"])
def test_dpn009_emit_terminal_success_announce_failure_keeps_signed_off(
    repo: Path,
    captured: list[Any],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    where: str,
) -> None:
    plan_dir = dp3._make_plan(repo, TOP_ID)
    auditor = dp3._write_envelopes(plan_dir, TOP_ID)
    loaded = plan_loader.load(plan_dir)
    sp = signoff_writer.signoff_path(plan_dir, TOP_ID)
    assert not sp.exists()
    fired = _fail_success_announcement(monkeypatch, where, captured)

    out = supervisor._emit_volley_terminal(
        supervisor.VolleyResult("signed_off", 1, "auditor signed off", [auditor]),
        loaded=loaded,
        feature_id="F001",
        agents_in_panel=["claude", "codex"],
    )

    assert fired == [where]
    assert out.final_status == "signed_off", out
    assert out.reason == "auditor signed off"
    so = _signoff(plan_dir)
    assert so["signoff"] is True and so["next_action"] == "merge", so
    assert [Path(a).name for a in so["audits"]] == [auditor.name]
    printed = capsys.readouterr().out
    assert "[volley] WARN: signed_off terminal announce failed:" in printed, printed
    # Nothing blocked was announced; the partial failure leaves exactly what
    # got through before the fault.
    assert "blocked" not in _terminal_statuses(plan_dir)
    if where == "notify":
        assert _terminal_statuses(plan_dir) == ["signed_off"]
    else:
        assert _terminal_statuses(plan_dir) == []
    assert [getattr(e, "kind", None) for e in captured] == []


class _BadReprError(RuntimeError):
    def __repr__(self) -> str:
        raise ValueError("repr exploded (injected)")


class _BrokenStdout:
    def write(self, _s: str) -> int:
        raise OSError(32, "Broken pipe (injected)")

    def flush(self) -> None:
        raise OSError(32, "Broken pipe (injected)")


# (g2) the WARN print itself fails — still signed_off, nothing escapes
@pytest.mark.parametrize("how", ["repr", "stdout"])
def test_dpn009_emit_terminal_warn_print_failure_still_signed_off(
    repo: Path,
    captured: list[Any],
    monkeypatch: pytest.MonkeyPatch,
    how: str,
) -> None:
    """The success announcement raises AND building/printing the WARN raises
    (the exception's ``__repr__`` raises, or stdout is broken). Nothing may
    escape ``_emit_volley_terminal``; the durable success signoff stands."""
    plan_dir = dp3._make_plan(repo, TOP_ID)
    auditor = dp3._write_envelopes(plan_dir, TOP_ID)
    loaded = plan_loader.load(plan_dir)
    sp = signoff_writer.signoff_path(plan_dir, TOP_ID)
    assert not sp.exists()
    fired: list[str] = []
    real_append = inbox.append_event

    def _flaky_append(plan_dir: Path, *, event: str, **kw: Any) -> Any:
        if event == "volley_terminal" and kw.get("final_status") == "signed_off" and not fired:
            fired.append(how)
            if how == "repr":
                raise _BadReprError("inbox down (injected)")
            # Break stdout only now, so the WARN print is what hits it.
            monkeypatch.setattr(sys, "stdout", _BrokenStdout())
            raise OSError(28, "No space left on device (injected)")
        return real_append(plan_dir, event=event, **kw)

    monkeypatch.setattr(supervisor.inbox, "append_event", _flaky_append)

    out = supervisor._emit_volley_terminal(
        supervisor.VolleyResult("signed_off", 1, "auditor signed off", [auditor]),
        loaded=loaded,
        feature_id="F001",
        agents_in_panel=["claude", "codex"],
    )

    assert fired == [how]
    assert out.final_status == "signed_off", out
    assert out.reason == "auditor signed off"
    so = _signoff(plan_dir)
    assert so["signoff"] is True and so["next_action"] == "merge", so
    assert [Path(a).name for a in so["audits"]] == [auditor.name]
    assert _terminal_statuses(plan_dir) == []
    assert [getattr(e, "kind", None) for e in captured] == []


# (h) real dispatch_volley iter loop
@pytest.mark.parametrize("where", ["notify", "inbox"])
def test_dpn009_dispatch_success_announce_failure_not_rewritten_blocked(
    repo: Path,
    captured: list[Any],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    where: str,
) -> None:
    plan_dir = dp3._make_plan(repo, TOP_ID)
    dp3._clear_pre_merge(plan_dir, TOP_ID)
    fired = _fail_success_announcement(monkeypatch, where, captured)

    result = supervisor.dispatch_volley(plan_dir, "F001", max_iterations=1)

    assert fired == [where]
    assert result.final_status == "signed_off", result
    so = _signoff(plan_dir)
    assert so["signoff"] is True and so["next_action"] == "merge", so
    assert so.get("volley_status", "signed_off") == "signed_off", so
    assert dp3._transcript_terminals(plan_dir) == ["signed_off"]
    assert "blocked" not in _terminal_statuses(plan_dir)
    assert dp3._crash_caught(plan_dir) == []
    assert "[volley] WARN: signed_off terminal announce failed:" in capsys.readouterr().out


# (i) regression guards
def test_dpn009_writer_failure_still_downgrades_and_announces_blocked(
    repo: Path, captured: list[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    plan_dir = dp3._make_plan(repo, TOP_ID)
    auditor = dp3._write_envelopes(plan_dir, TOP_ID)
    loaded = plan_loader.load(plan_dir)
    monkeypatch.setattr(signoff_writer, "VALID_TIERS", frozenset())  # real SignoffWriteError

    out = supervisor._emit_volley_terminal(
        supervisor.VolleyResult("signed_off", 1, "auditor signed off", [auditor]),
        loaded=loaded,
        feature_id="F001",
        agents_in_panel=["claude", "codex"],
    )

    assert out.final_status == "blocked"
    assert "SignoffWriteError" in out.reason
    assert _terminal_statuses(plan_dir) == ["blocked"]
    assert [e.kind for e in captured] == ["volley_terminal"]
    assert not signoff_writer.signoff_path(plan_dir, TOP_ID).exists()


def test_dpn009_child_charter_violation_still_downgrades_and_announces_blocked(
    repo: Path, captured: list[Any]
) -> None:
    plan_dir = dp3._make_child(repo, memo_status=None)  # no close-out memo -> real violation
    auditor = dp3._write_envelopes(plan_dir, CHILD_ID)
    loaded = plan_loader.load(plan_dir)

    out = supervisor._emit_volley_terminal(
        supervisor.VolleyResult("signed_off", 1, "auditor signed off", [auditor]),
        loaded=loaded,
        feature_id="F001",
        agents_in_panel=["claude", "codex"],
    )

    assert out.final_status == "blocked"
    assert nested_orchestration.ChildCharterViolation.__name__ in out.reason
    assert _terminal_statuses(plan_dir) == ["blocked"]
    assert [e.kind for e in captured] == ["volley_terminal"]


def test_dpn009_blocked_announce_failure_after_writer_failure_still_raises(
    repo: Path, captured: list[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The containment is limited to the durable-signoff case: when the writer
    failed and the result was downgraded to blocked, a failing blocked
    announcement still propagates (unchanged behaviour)."""
    plan_dir = dp3._make_plan(repo, TOP_ID)
    auditor = dp3._write_envelopes(plan_dir, TOP_ID)
    loaded = plan_loader.load(plan_dir)
    monkeypatch.setattr(signoff_writer, "VALID_TIERS", frozenset())

    def _boom(event: Any, **kw: Any) -> Any:
        raise RuntimeError("notification sink down (injected)")

    monkeypatch.setattr(supervisor.notify_event, "dispatch_event", _boom)
    with pytest.raises(RuntimeError, match="sink down"):
        supervisor._emit_volley_terminal(
            supervisor.VolleyResult("signed_off", 1, "auditor signed off", [auditor]),
            loaded=loaded,
            feature_id="F001",
            agents_in_panel=["claude", "codex"],
        )


def test_dpn009_non_success_terminal_still_announces_first(
    repo: Path, captured: list[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    plan_dir = dp3._make_plan(repo, TOP_ID)
    auditor = dp3._write_envelopes(plan_dir, TOP_ID)
    loaded = plan_loader.load(plan_dir)
    order: list[str] = []
    real_announce = supervisor._announce_volley_terminal
    real_write = signoff_writer.write_signoff

    def _announce(result: Any, **kw: Any) -> None:
        order.append(f"announce:{result.final_status}")
        real_announce(result, **kw)

    def _write(**kw: Any) -> Path:
        order.append(f"write:{kw['volley_status']}")
        return real_write(**kw)

    monkeypatch.setattr(supervisor, "_announce_volley_terminal", _announce)
    monkeypatch.setattr(signoff_writer, "write_signoff", _write)

    out = supervisor._emit_volley_terminal(
        supervisor.VolleyResult("blocked", 1, "auditor blocked", [auditor]),
        loaded=loaded,
        feature_id="F001",
        agents_in_panel=["claude", "codex"],
    )

    assert out.final_status == "blocked"
    assert order == ["announce:blocked", "write:blocked"]
    assert _terminal_statuses(plan_dir) == ["blocked"]

    # And the success path still writes first, announces after.
    order.clear()
    plan2 = dp3._make_plan(repo, "2026-11-12-405-infra-dpn009-top2")
    aud2 = dp3._write_envelopes(plan2, plan2.name)
    out2 = supervisor._emit_volley_terminal(
        supervisor.VolleyResult("signed_off", 1, "auditor signed off", [aud2]),
        loaded=plan_loader.load(plan2),
        feature_id="F001",
        agents_in_panel=["claude", "codex"],
    )
    assert out2.final_status == "signed_off"
    assert order == ["write:signed_off", "announce:signed_off"]


def test_dpn009_patch_completeness_error_still_announces_one_blocked_and_raises(
    repo: Path, captured: list[Any]
) -> None:
    plan_dir = dp3._make_plan(repo, TOP_ID)
    auditor = dp3._write_envelopes(plan_dir, TOP_ID)
    (plan_dir / "tests").mkdir()
    (plan_dir / "tests" / "test_new.py").write_text("def test_x(): assert True\n")
    dp3._git_state(plan_dir, {"untracked": ["tests/test_new.py"]})
    loaded = plan_loader.load(plan_dir)

    with pytest.raises(PatchCompletenessError) as exc:
        supervisor._emit_volley_terminal(
            supervisor.VolleyResult("signed_off", 1, "auditor signed off", [auditor]),
            loaded=loaded,
            feature_id="F001",
            agents_in_panel=["claude", "codex"],
        )

    assert getattr(exc.value, "volley_terminal_announced", False) is True
    dp3._assert_one_blocked_terminal(plan_dir, captured, "PatchCompletenessError")
