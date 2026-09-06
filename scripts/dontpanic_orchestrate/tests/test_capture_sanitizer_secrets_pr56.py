"""PR56 / PR49 follow-up (r3422558956, r3408996302): capture-time
sanitization redacts credential shapes, not only operator identity — and
does so WITHOUT corrupting the JSON the audit parser reads next.

The transcript writer is the single fix point (committed envelopes are
immutable), so the sanitizer it applies must:

* redact secret-shaped payloads an auditor may echo back (bearer headers,
  prefixed API keys, ``token=`` pairs) and secret-NAMED JSON fields
  (``"password": "…"``), inside prose and inside JSON string values;
* leave every JSON response parseable, so redaction can never turn a valid
  auditor verdict into ``dispatch_response_malformed`` (review finding:
  the greedy ``Authorization:`` header regex ate closing JSON syntax);
* NOT treat arbitrary absolute paths as secrets.

Residual limitation (stated, not fixed here): ordinary prose that is
sensitive without matching a credential shape, and full local-context
transcripts, are still persisted. Structure-aware redaction covers key
names and credential shapes only.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import completion_dispatch as cd  # noqa: E402
from dontpanic_orchestrate.completion_auditor import run_completion_audit  # noqa: E402

BEARER = "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.abcdefghijklmnop"
JWT = BEARER.split("Bearer ")[1]
PREFIXED = "sk" + "_live_" + "A" * 32  # generated dummy credential shape
ASSIGN = "api_key=AIzaSyD-9tSrke72PouQMnMX-a7eZSW0jkFMBWY"
PASSWORD_VALUE = "synthetic-value-not-a-real-secret"  # noqa: S105 — fixture, not a credential


# ── plain text ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("payload", [BEARER, PREFIXED, ASSIGN])
def test_secret_shapes_do_not_survive_capture(payload: str) -> None:
    out = cd.sanitize_capture(f"auditor echoed: {payload}")
    secret_half = payload.split("=", 1)[-1].split("Bearer ")[-1]
    assert secret_half not in out
    assert "redacted" in out


def test_key_names_are_kept_so_operators_see_what_was_elided() -> None:
    out = cd.sanitize_capture(ASSIGN)
    assert out.startswith("api_key=")


def test_secret_redaction_is_idempotent_and_leaves_plain_text_alone() -> None:
    once = cd.sanitize_capture(f"x {PREFIXED} y")
    assert cd.sanitize_capture(once) == once
    plain = "ran pytest in /private/tmp/work/plan-a and saw 12 passed"
    assert cd.sanitize_capture(plain) == plain  # absolute paths are not secrets


# ── JSON must stay JSON ────────────────────────────────────────────────────────


def _dispositions_with_secrets(finding_ids: list[str]) -> list[dict[str, Any]]:
    return [
        {
            "finding_id": fid,
            "agree": True,
            "severity_disposition": "agree",
            # Secrets INSIDE a string value: the header regex used to run to
            # end-of-line and swallow the closing quote, bracket and brace.
            "comment": f'saw {BEARER} and "password": "{PASSWORD_VALUE}" in the log',
        }
        for fid in finding_ids
    ]


def test_bearer_header_inside_json_string_keeps_the_document_parseable() -> None:
    raw = json.dumps(_dispositions_with_secrets(["F-1", "F-2"]))
    out = cd.sanitize_capture(raw)
    parsed = json.loads(out)  # would raise before the fix
    assert [d["finding_id"] for d in parsed] == ["F-1", "F-2"]
    assert JWT not in out
    assert PASSWORD_VALUE not in out
    assert "Authorization:" in parsed[0]["comment"]  # key half kept, value elided


def test_secret_named_json_fields_are_redacted_by_key() -> None:
    doc = {
        "status": "ok",
        "password": PASSWORD_VALUE,  # noqa: S105 — review finding: survived unchanged
        "nested": {"API_KEY": "plain-looking-but-named-secret", "note": "fine"},
        "count": 3,
    }
    out = cd.sanitize_capture(json.dumps(doc))
    parsed = json.loads(out)
    assert parsed["password"] == "[redacted-secret]"  # noqa: S105
    assert parsed["nested"]["API_KEY"] == "[redacted-secret]"
    assert parsed["nested"]["note"] == "fine"
    assert parsed["status"] == "ok" and parsed["count"] == 3


def test_fenced_json_is_redacted_and_still_parses_through_the_parser() -> None:
    inner = json.dumps(_dispositions_with_secrets(["F-1"]))
    fenced = f"```json\n{inner}\n```"
    out = cd.sanitize_capture(fenced)
    assert JWT not in out
    status, disps = cd._parse_audit_response(out, [_finding("F-1")])
    assert status != "dispatch_response_malformed", disps
    assert disps[0].finding_id == "F-1" and disps[0].agree is True


def test_codex_jsonl_stream_is_redacted_line_by_line_and_still_extracts() -> None:
    inner = json.dumps(_dispositions_with_secrets(["F-1"]))
    stream = "\n".join(
        [
            json.dumps({"type": "turn.started"}),
            json.dumps(
                {"type": "item.completed", "item": {"type": "agent_message", "text": inner}}
            ),
            json.dumps({"type": "turn.completed"}),
        ]
    )
    out = cd.sanitize_capture(stream)
    assert JWT not in out and PASSWORD_VALUE not in out
    status, disps = cd._parse_audit_response(out, [_finding("F-1")])
    assert status != "dispatch_response_malformed", disps
    assert disps[0].agree is True


def test_clean_json_is_returned_byte_for_byte() -> None:
    raw = json.dumps(
        [
            {
                "finding_id": "F-1",
                "agree": True,
                "severity_disposition": "agree",
                "comment": "nothing secret",
            }
        ],
        indent=2,
    )
    assert cd.sanitize_capture(raw) == raw


SENSITIVE = "synthetic-sensitive-value"  # noqa: S105 — fixture, not a credential


def test_secret_named_containers_are_redacted_whole() -> None:
    """Review finding: containers were descended before the key check, so
    {"credentials": {...}} and {"token": [...]} leaked their contents."""
    doc = {"credentials": {"value": SENSITIVE}, "token": [SENSITIVE, "x"], "ok": {"n": 1}}  # noqa: S105
    out = cd.sanitize_capture(json.dumps(doc))
    parsed = json.loads(out)
    assert SENSITIVE not in out
    assert parsed["credentials"] == "[redacted-secret]"
    assert parsed["token"] == "[redacted-secret]"  # noqa: S105
    assert parsed["ok"] == {"n": 1}


def test_embedded_json_with_escaped_quote_in_secret_is_redacted_structurally() -> None:
    """Review finding: a password containing an escaped quote, inside JSON
    carried as a string, evaded the textual key/value pattern."""
    inner = json.dumps({"password": 'pre"fix' + SENSITIVE, "keep": "yes"})
    doc = {"comment": inner}
    out = cd.sanitize_capture(json.dumps(doc))
    parsed = json.loads(out)
    assert SENSITIVE not in out
    embedded = json.loads(parsed["comment"])  # still JSON inside the string
    assert embedded == {"password": "[redacted-secret]", "keep": "yes"}


def _stream_with(inner: str) -> str:
    return "\n".join(
        [
            json.dumps({"type": "turn.started"}),
            json.dumps(
                {"type": "item.completed", "item": {"type": "agent_message", "text": inner}}
            ),
            json.dumps({"type": "turn.completed"}),
        ]
    )


def test_both_gaps_through_the_parser_on_a_codex_stream() -> None:
    disposition = {
        "finding_id": "F-1",
        "agree": True,
        "severity_disposition": "agree",
        "comment": json.dumps(
            {
                "credentials": {"value": SENSITIVE},
                "password": 'q"' + SENSITIVE,
                "token": [SENSITIVE],
            }
        ),
    }
    out = cd.sanitize_capture(_stream_with(json.dumps([disposition])))
    assert SENSITIVE not in out
    status, disps = cd._parse_audit_response(out, [_finding("F-1")])
    assert status != "dispatch_response_malformed", disps
    assert disps[0].agree is True


# ── through the real dispatch + evidence writer ────────────────────────────────


def _finding(fid: str) -> Any:
    from dontpanic_orchestrate.completion_auditor import CompletionFinding

    return CompletionFinding(
        finding_id=fid,
        gap_class="missing_evidence",
        severity="medium",
        title="fixture finding",
        narrative="fixture finding narrative for the sanitizer tests",
        subsystem="fixture",
        journey="onboarding",
    )


def _write_plan(plan_dir: Path) -> Path:
    import yaml

    plan_dir.mkdir(parents=True)
    (plan_dir / "objective_contract.json").write_text(
        json.dumps(
            {
                "goal_type": "parity",
                "source_of_truth": "Some prior plan / curated reference",
                "user_journeys": [
                    {
                        "name": "onboarding",
                        "description": (
                            "User opens the app, completes the welcome flow, and lands "
                            "on the home screen with their workspace loaded."
                        ),
                        "surfaces": ["ios", "android"],
                        "acceptance_signals": ["welcome screen renders within 2 seconds"],
                    }
                ],
                "required_evidence": ["screenshot-onboarding-welcome"],
                "completion_test": "Onboarding runs end-to-end without operator intervention.",
            }
        )
    )
    fm = {
        "id": "2026-09-05-999-feat-sanitizer-fixture",
        "title": "fixture plan",
        "type": "feat",
        "tier": "local",
        "status": "active",
        "date": "2026-09-05",
        "goal_type": "parity",
        "links": {"objective_contract": "./objective_contract.json"},
        "description": "synthetic fixture plan for capture-sanitizer tests",
    }
    (plan_dir / "plan.md").write_text(
        "---\n" + yaml.safe_dump(fm, sort_keys=False) + "---\n\n# fixture\n"
    )
    (plan_dir / "features.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "task_id": "fixture",
                "features": [
                    {
                        "id": "F001",
                        "category": "tooling",
                        "phase": 1,
                        "description": "fixture feature for sanitizer testing",
                        "steps": ["a"],
                        "acceptance": "fixture",
                        "passes": True,
                        "depends_on": [],
                        "evidence_refs": [],
                    }
                ],
            }
        )
    )
    return plan_dir


def test_dispatch_writer_persists_redacted_but_parseable_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The regression the plain-text tests missed: a valid auditor verdict
    carrying a bearer header in a comment must still be recorded as a
    verdict (not malformed), and neither the transcript nor the envelope may
    retain the credential."""
    monkeypatch.delenv("DONTPANIC_GOAL_AUDITOR_ALLOW_SAME_VENDOR", raising=False)
    monkeypatch.delenv("DONTPANIC_GOAL_AUDITOR_OFFLINE", raising=False)
    plan_dir = _write_plan(tmp_path / "plan")
    findings = run_completion_audit(plan_dir)
    assert findings, "fixture must yield findings (missing artifact)"

    def stub(_auditor: str, _prompt: str) -> str:
        disps = _dispositions_with_secrets([f.finding_id for f in findings])
        # Both review gaps, carried as embedded JSON inside a comment string.
        disps[0]["comment"] += " " + json.dumps(
            {
                "credentials": {"value": SENSITIVE},
                "password": 'q"' + SENSITIVE,
                "token": [SENSITIVE],
            }
        )
        return json.dumps(disps)

    transcript = cd.dispatch_completion_audit(
        plan_dir, findings=findings, implementer_agent="claude", dispatch=stub
    )

    assert transcript.status == "agree", transcript.findings_dispositions
    audit_dir = plan_dir / "evidence" / "goal-governance" / "post_impl" / "audit"
    envelope = next(audit_dir.glob("audit-*-1.json"))
    transcript_txt = next(audit_dir.glob("audit-*-1.transcript.txt"))
    env_text = envelope.read_text()
    json.loads(env_text)  # envelope stays valid JSON
    json.loads(transcript_txt.read_text())  # transcript stays valid JSON
    for blob in (env_text, transcript_txt.read_text()):
        assert JWT not in blob
        assert PASSWORD_VALUE not in blob
        assert SENSITIVE not in blob
        assert "[redacted-secret]" in blob
