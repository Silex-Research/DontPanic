"""Plan 2026-06-12-001 — audit evidence-writer hygiene.

F001 — capture-time sanitization: workstation paths and operator identity
never reach disk; the in-memory transcript equals what disk holds.

F002 — append-only re-audit: the next iteration is derived from the audit
directory; explicit colliding iterations refuse; readers consume the
latest. All offline via the injected dispatch seam — zero paid calls.
"""

from __future__ import annotations

import getpass
import json
import socket
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import completion_dispatch as cd  # noqa: E402
from dontpanic_orchestrate import completion_gate as cg  # noqa: E402

USER = getpass.getuser()
HOME = str(Path.home())
HOST = socket.gethostname()


@pytest.fixture()
def plan_dir(tmp_path):
    p = tmp_path / "docs" / "plans" / "2026-06-12-001-fix-audit-evidence-writer-hygiene"
    p.mkdir(parents=True)
    (p / "plan.md").write_text(
        "---\nid: x\nstatus: active\nlinks:\n"
        "  features: ./features.json\n"
        "  objective_contract: ./objective_contract.json\n---\n"
    )
    (p / "objective_contract.json").write_text(
        json.dumps(
            {
                "goal_type": "new_feature",
                "source_of_truth": "synthetic writer-hygiene fixture",
                "completion_test": "envelope writes are sanitized and append-only",
                "user_journeys": [
                    {
                        "name": "j1",
                        "description": "synthetic journey",
                        "surfaces": ["core"],
                        "states": ["s1"],
                    }
                ],
            }
        )
    )
    (p / "features.json").write_text(
        json.dumps({"task_id": "x", "schema_version": "1.0", "features": []})
    )
    return p


def _dispatch_returning(raw: str):
    def dispatch(auditor: str, prompt: str) -> str:
        return raw

    return dispatch


def _run(plan_dir, raw: str, iteration=None):
    kwargs = {"findings": [], "dispatch": _dispatch_returning(raw)}
    if iteration is not None:
        kwargs["iteration"] = iteration
    return cd.dispatch_completion_audit(plan_dir, **kwargs)


CLEAN_RESPONSE = '[]'


def _real(placeholdered: str) -> str:
    """Map a sanitized path string back to the real filesystem location
    (test-side only — the writer computes real paths from plan_dir, the
    recorded strings are informational placeholders)."""
    return placeholdered.replace("<home>", HOME).replace("<operator>", USER)


class TestF001CaptureSanitization:
    def test_home_paths_and_identity_never_reach_disk(self, plan_dir):
        dirty = (
            f'I inspected {HOME}/Documents/GitHub/DontPanic/scripts and the '
            f'actor {USER}@{HOST} approved.\n[]'
        )
        t = _run(plan_dir, dirty)
        env_bytes = Path(_real(t.envelope_path)).read_text()
        txt_bytes = Path(_real(t.transcript_path)).read_text()
        for payload in (env_bytes, txt_bytes):
            assert HOME not in payload
            assert USER not in payload
        assert "<home>" in txt_bytes
        assert "<operator>@<host>" in txt_bytes or "<operator>" in txt_bytes

    def test_in_memory_transcript_equals_disk(self, plan_dir):
        dirty = f'path {HOME}/x noted\n[]'
        t = _run(plan_dir, dirty)
        # what the gate consumes equals what disk holds — no divergence
        assert HOME not in t.raw_response
        assert HOME not in t.transcript_path and HOME not in t.envelope_path
        on_disk = json.loads(Path(_real(t.envelope_path)).read_text())
        assert on_disk["raw_response"] == t.raw_response
        assert on_disk["transcript_path"] == t.transcript_path

    def test_path_fields_are_placeholdered_but_files_land_in_audit_dir(self, plan_dir):
        t = _run(plan_dir, CLEAN_RESPONSE)
        for recorded in (t.transcript_path, t.envelope_path):
            assert HOME not in recorded and USER not in recorded
        env_file = Path(_real(t.envelope_path))
        txt_file = Path(_real(t.transcript_path))
        assert env_file.is_file() and txt_file.is_file()
        assert env_file.parent.name == "audit"

    def test_envelope_reparses_and_dispositions_parse_unchanged(self, plan_dir):
        raw = (
            '[{"finding_id": "auditor-overlay-001", "agree": true, '
            f'"severity_disposition": "agree", "comment": "notes from {HOME}/repo"}}]'
        )
        t = _run(plan_dir, raw)
        assert t.status == "agree"  # sanitization happened pre-parse without breaking it
        reread = cg._load_latest_audit_envelope(plan_dir)
        assert reread is not None
        assert reread.status == t.status
        assert len(reread.findings_dispositions) == 1
        assert reread.findings_dispositions[0].finding_id == "auditor-overlay-001"
        assert reread.findings_dispositions[0].comment == "notes from <home>/repo"

    def test_clean_content_passes_through_byte_identical(self, plan_dir):
        body = '{"hello": "world", "n": 1}\n[]'
        t = _run(plan_dir, body)
        assert t.raw_response == cd.sanitize_capture(body)
        assert cd.sanitize_capture("no identifiers here") == "no identifiers here"

    def test_sanitizer_is_exported_pure_function(self):
        out = cd.sanitize_capture(f"{HOME}/a/b and {USER}@{HOST} and {USER}")
        assert out == "<home>/a/b and <operator>@<host> and <operator>"
        # pure: same input, same output
        assert cd.sanitize_capture(out) == out


class TestF002AppendOnlyIterations:
    def test_two_audits_write_two_iterations_first_preserved(self, plan_dir):
        t1 = _run(plan_dir, CLEAN_RESPONSE)
        first = Path(_real(t1.envelope_path))
        first_bytes = first.read_bytes()
        t2 = _run(plan_dir, '[{"finding_id": "auditor-overlay-002", "agree": false, "severity_disposition": "no_finding", "comment": "x"}]')
        assert t1.iteration == 1 and t2.iteration == 2
        assert first.read_bytes() == first_bytes  # byte-identical after re-audit
        second = Path(_real(t2.envelope_path))
        assert second.name != first.name and second.is_file()

    def test_reader_returns_latest_iteration_verdict(self, plan_dir):
        _run(plan_dir, CLEAN_RESPONSE)
        _run(plan_dir, '[{"finding_id": "auditor-overlay-009", "agree": true, "severity_disposition": "agree", "comment": "later"}]')
        latest = cg._load_latest_audit_envelope(plan_dir)
        assert latest.iteration == 2
        assert latest.findings_dispositions and latest.findings_dispositions[0].finding_id == "auditor-overlay-009"

    def test_explicit_colliding_iteration_refuses_naming_file(self, plan_dir):
        t1 = _run(plan_dir, CLEAN_RESPONSE)
        with pytest.raises(cd.CompletionDispatchError) as exc:
            _run(plan_dir, CLEAN_RESPONSE, iteration=1)
        assert "audit-" in str(exc.value)  # names the existing envelope
        # nothing was overwritten
        assert Path(_real(t1.envelope_path)).is_file()

    def test_explicit_noncolliding_iteration_honoured(self, plan_dir):
        t = _run(plan_dir, CLEAN_RESPONSE, iteration=7)
        assert t.iteration == 7
        assert "audit-" in t.envelope_path and "-7." in t.envelope_path

    def test_envelope_iteration_field_matches_filename(self, plan_dir):
        _run(plan_dir, CLEAN_RESPONSE)
        t2 = _run(plan_dir, CLEAN_RESPONSE)
        on_disk = json.loads(Path(_real(t2.envelope_path)).read_text())
        assert on_disk["iteration"] == 2
        assert "-2.json" in t2.envelope_path

    def test_mixed_auditors_number_independently(self, plan_dir, monkeypatch):
        _run(plan_dir, CLEAN_RESPONSE)  # codex iteration 1
        # a foreign auditor's pre-existing envelopes must not bump codex
        audit_dir = plan_dir / "evidence" / "goal-governance" / "post_impl" / "audit"
        (audit_dir / "audit-claude-5.json").write_text("{}")
        t = _run(plan_dir, CLEAN_RESPONSE)
        assert t.iteration == 2  # not 6

    def test_latest_reader_in_mixed_auditor_directory(self, plan_dir):
        # codex audit-iteration overlay D004: per-auditor numbering means a
        # foreign auditor's leftover envelope can carry a HIGHER iteration
        # number than the current auditor's newest verdict. The reader must
        # support per-auditor selection so callers can honour the contract's
        # "highest iteration FOR THE AUDITOR".
        _run(plan_dir, CLEAN_RESPONSE)  # codex iteration 1
        t2 = _run(plan_dir, '[{"finding_id": "auditor-overlay-009", "agree": true, "severity_disposition": "agree", "comment": "later"}]')  # codex iteration 2
        audit_dir = plan_dir / "evidence" / "goal-governance" / "post_impl" / "audit"
        foreign = json.loads(Path(_real(t2.envelope_path)).read_text())
        foreign["auditor_agent"] = "claude"
        foreign["iteration"] = 5
        foreign["findings_dispositions"] = []
        (audit_dir / "audit-claude-5.json").write_text(json.dumps(foreign))
        # auditor-scoped read: codex's own latest, not the foreign 5
        scoped = cg._load_latest_audit_envelope(plan_dir, auditor="codex")
        assert scoped.auditor_agent == "codex" and scoped.iteration == 2
        # unscoped read keeps the historical global-highest behaviour
        unscoped = cg._load_latest_audit_envelope(plan_dir)
        assert unscoped.iteration == 5

    def test_gate_entry_points_default_to_derived_iteration(self):
        import inspect

        for fn in (cg.audit_plan, cg.close_plan, cd.dispatch_completion_audit):
            sig = inspect.signature(fn)
            assert sig.parameters["iteration"].default is None, (
                f"{fn.__name__} must derive the iteration, not hardcode 1"
            )
