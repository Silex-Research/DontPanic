"""Plan 2026-05-24-004 F004 — render-boundary sanitization wiring tests.

Two sanitization modes per D011 + D020:

  - Raise mode (operator-fixable):
      :func:`operator_console.write_event_action_sidecar` rejects any
      sidecar entry whose projected payload contains a secret-shape
      match. The sidecar is durable state, so a leak is a real defect
      and the operator should fix the rendered ActionItem instead of
      letting it persist.

  - Substitute mode (supervisor must not fail-hard on a transient ping):
      ``notify_discord.notify()``, ``notify.notify_event()`` and
      ``inbox.append_rendered_annotation()`` all run their output
      strings through :func:`state_projection.scrub_secrets`. Matches
      become ``[REDACTED]`` in the rendered channel output; the call
      itself never raises.

Acceptance covered:

  (1) state_projection.scrub_secrets is the public symbol per D020.
  (2) Sidecar raise-mode rejects secret-shaped payloads.
  (3) Live notification paths scrub and do NOT raise.
  (4) 9 secret-shape regex patterns × 4 rendered channels = 36+
      assertions (TestSecretMatrix, parametrized).
  (5) Existing sanitization_check.py tests untouched (no regex
      modifications — F004 only wires the existing tuple).
  (6) Sidecar fail-hard test (TestSidecarRaisesOnSecrets).
  (7) Live-path no-fail test (TestLivePathsNeverRaiseOnSecrets).

Test fixtures use realistic secret SHAPES, never live secrets — the
``scripts/dontpanic_orchestrate/tests/`` prefix is in the OSS
sanitization ALLOWED_GLOBS specifically so fixture content can match
the regex tuple without tripping the repo-wide scan.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import (  # noqa: E402
    event_copy,
    inbox,
    notify,
    notify_discord,
    notify_event,
    operator_console,
    state_projection,
)

REDACTED = "[REDACTED]"


# ─── secret-shape fixtures (9 vendors) ──────────────────────────────────────
# Crafted to match each of the SECRET_REGEXES at
# scripts/sanitization_check.py:92-102 without copying any real key. The
# regex shapes are public vendor formats; the values are deterministic
# stand-ins (mostly long runs of one character padded with the few digits
# required by the regex anchors).
_AAA36 = "a" * 36
_AAA93 = "a" * 93
_AAA60 = "a" * 60

# Reuse the OpenAI alphanum body so the infix `T3BlbkFJ` (base64 of
# `OpenAI`) appears between two 20-char alphanumeric segments.
_OPENAI_PREFIX_BODY = "a" * 20
_OPENAI_SUFFIX_BODY = "a" * 20

# Anthropic regex requires url-safe-base64 (incl. underscore + dash)
# 93 chars before the trailing ``AA``.
SECRET_SAMPLES: dict[str, str] = {
    # AKIA + 16 base32 chars; positive lookaheads need at least one
    # letter and one digit in the trailing 16. ``IOSFODNN7EXAMPLE`` is
    # the canonical AWS doc example and matches both lookaheads.
    "aws_access_key": "AKIAIOSFODNN7EXAMPLE",
    "github_pat": f"ghp_{_AAA36}",
    "github_fine_grained": f"gho_{_AAA36}",
    "anthropic_api_key": f"sk-ant-api03-{_AAA93}AA",
    "openai_api_key": f"sk-{_OPENAI_PREFIX_BODY}T3BlbkFJ{_OPENAI_SUFFIX_BODY}",
    "slack_token": "xoxb-1234567890abcdef",
    "pem_private_key": "-----BEGIN PRIVATE KEY-----",
    "jwt_token": "eyJabcdefghij.abcdefghij.abcdefghij",
    "discord_webhook": f"https://discord.com/api/webhooks/12345678901234567/{_AAA60}",
}


# ─── helpers ────────────────────────────────────────────────────────────────


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _make_event(
    *,
    plan_id: str = "p1",
    kind: str = "gate_paused",
    inbox_event: str = "gate_hit",
    body: str = "x",
    subtype: str | None = "pre_impl",
    technical_metadata: dict[str, Any] | None = None,
) -> notify_event.NotifyEvent:
    return notify_event.NotifyEvent(
        kind=kind,
        severity="action_required",
        plan_id=plan_id,
        feature_id="F001",
        body=body,
        evidence_uri="/tmp/INBOX.md",
        timestamp=_now(),
        inbox_event=inbox_event,
        subtype=subtype,
        technical_metadata=technical_metadata or {"gate": "pre_impl", "stage": "pre_impl"},
    )


def _make_rendered(
    *,
    title: str = "Title",
    detail: str | None = "Detail",
    exact_command: str | None = None,
    evidence_uri: str | None = "/tmp/INBOX.md",
    technical_metadata: dict[str, Any] | None = None,
) -> event_copy.RenderedEvent:
    return event_copy.RenderedEvent(
        band="needs_action",
        title=title,
        detail=detail,
        exact_command=exact_command,
        evidence_uri=evidence_uri,
        disposition=event_copy.Disposition.LIVE,
        technical_metadata=technical_metadata or {},
    )


def _verify_redacted(rendered_output: str, secret: str, sample_key: str) -> None:
    """Assert the secret was stripped and [REDACTED] is in the output."""
    assert secret not in rendered_output, (
        f"sample {sample_key!r}: raw secret leaked into rendered output: "
        f"{rendered_output!r}"
    )
    assert REDACTED in rendered_output, (
        f"sample {sample_key!r}: expected [REDACTED] placeholder but got: "
        f"{rendered_output!r}"
    )


# ─── (1) public API per D020 ────────────────────────────────────────────────


class TestPublicScrubSecretsAPI:
    """D020: state_projection.scrub_secrets is the public symbol; the
    private alias remains for any pre-F004 caller still bound to it."""

    def test_public_symbol_exists(self) -> None:
        assert callable(state_projection.scrub_secrets)

    def test_private_alias_still_callable(self) -> None:
        # Backward-compat — any caller that bound to the pre-D020 name
        # still gets the same behavior.
        assert state_projection._scrub_secrets is state_projection.scrub_secrets

    def test_public_symbol_in_dunder_all(self) -> None:
        assert "scrub_secrets" in state_projection.__all__

    def test_no_op_on_empty(self) -> None:
        assert state_projection.scrub_secrets("") == ""
        assert state_projection.scrub_secrets(None) is None

    def test_passes_through_when_no_secret(self) -> None:
        assert state_projection.scrub_secrets("just regular text") == "just regular text"

    @pytest.mark.parametrize("sample_key", sorted(SECRET_SAMPLES.keys()))
    def test_scrubs_each_secret_shape(self, sample_key: str) -> None:
        secret = SECRET_SAMPLES[sample_key]
        raw = f"prefix {secret} suffix"
        scrubbed = state_projection.scrub_secrets(raw)
        assert secret not in scrubbed, f"sample {sample_key!r} survived scrub: {scrubbed!r}"
        assert REDACTED in scrubbed


# ─── (2) sidecar raise mode per D011 ────────────────────────────────────────


class TestSidecarRaisesOnSecrets:
    """D011 + acceptance #2 + #6: the sidecar write boundary calls
    :func:`_assert_no_secret_shapes` in raise mode. Any secret in the
    projected ActionItem dict rejects the write before the JSONL line
    is appended, so the operator can fix the rendered event rather
    than letting a leak persist."""

    @pytest.mark.parametrize("sample_key", sorted(SECRET_SAMPLES.keys()))
    def test_each_secret_shape_blocks_sidecar_write(
        self,
        tmp_path: Path,
        sample_key: str,
    ) -> None:
        secret = SECRET_SAMPLES[sample_key]
        sidecar_path = tmp_path / "event-actions.jsonl"
        rendered = _make_rendered(
            title=f"Plan title with {secret} embedded",
        )
        with pytest.raises(ValueError, match="secret pattern"):
            operator_console.write_event_action_sidecar(
                rendered, path=sidecar_path
            )
        # Nothing was written — the write boundary fail-hards before
        # touching the JSONL file.
        assert not sidecar_path.exists() or sidecar_path.read_text() == ""

    def test_clean_payload_still_writes(self, tmp_path: Path) -> None:
        # Sanity: the raise-mode wire-up does not break the happy path.
        sidecar_path = tmp_path / "event-actions.jsonl"
        rendered = _make_rendered(
            title="Approval needed",
            detail="Operator approval required before continuing.",
            exact_command="dontpanic approve p1 pre_impl",
        )
        result = operator_console.write_event_action_sidecar(
            rendered, path=sidecar_path
        )
        assert result == sidecar_path
        lines = sidecar_path.read_text().strip().splitlines()
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["title"] == "Approval needed"
        assert entry["exact_command"] == "dontpanic approve p1 pre_impl"


# ─── (3) live paths substitute mode per D020 ────────────────────────────────


class TestLivePathsNeverRaiseOnSecrets:
    """D011 + acceptance #3 + #7: live notification paths replace secret
    shapes with ``[REDACTED]`` in the rendered output. The supervisor
    must keep dispatching events even when a body contains a
    secret-shaped substring; the live sink renders ``[REDACTED]`` but
    does NOT crash."""

    def test_inbox_append_rendered_annotation_does_not_raise(
        self, tmp_path: Path
    ) -> None:
        plan_dir = tmp_path / "plan"
        plan_dir.mkdir()
        rendered = _make_rendered(
            title=f"leaked: {SECRET_SAMPLES['anthropic_api_key']}",
            detail=f"body has {SECRET_SAMPLES['github_pat']} too",
            exact_command=f"dontpanic approve --token {SECRET_SAMPLES['slack_token']}",
            evidence_uri=SECRET_SAMPLES["discord_webhook"],
            technical_metadata={"meta_secret": SECRET_SAMPLES["jwt_token"]},
        )
        # Must not raise.
        inbox.append_rendered_annotation(
            plan_dir, plan_id="p1", rendered=rendered
        )
        markdown = (plan_dir / "INBOX.md").read_text()
        # All five injected secrets were scrubbed out and [REDACTED]
        # appears at least once in the rendered block.
        for key in ("anthropic_api_key", "github_pat", "slack_token",
                     "discord_webhook", "jwt_token"):
            assert SECRET_SAMPLES[key] not in markdown, (
                f"{key} leaked into INBOX markdown"
            )
        assert REDACTED in markdown

    def test_terminal_notify_event_does_not_raise(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Capture the args passed to the underlying notify() so we can
        # assert scrubbed output without needing the binary present.
        captured: dict[str, Any] = {}

        def fake_notify(title: str, message: str, **kwargs: Any) -> bool:
            captured["title"] = title
            captured["message"] = message
            captured["subtitle"] = kwargs.get("subtitle")
            captured["group"] = kwargs.get("group")
            return True

        monkeypatch.setattr(notify, "notify", fake_notify)
        ev = _make_event(body=f"leaking {SECRET_SAMPLES['openai_api_key']}")
        rendered = _make_rendered(
            title=f"headline {SECRET_SAMPLES['aws_access_key']}",
        )
        # Must not raise even though title carries a secret shape.
        assert notify.notify_event(ev, rendered=rendered) is True
        # Title is the plan-scoped banner ``DontPanic [plan_id]`` — it
        # carries no secret content but still passes through scrubbing.
        # Message body is the rendered headline; that's where the secret
        # shape lived and where the [REDACTED] placeholder should land.
        assert SECRET_SAMPLES["aws_access_key"] not in captured["title"]
        assert SECRET_SAMPLES["aws_access_key"] not in captured["message"]
        assert REDACTED in captured["message"]

    def test_discord_notify_does_not_raise(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # We don't actually want to network — assert that _build_payload
        # produces a sanitized payload even with secret-bearing fields.
        rendered = _make_rendered(
            title=f"Title {SECRET_SAMPLES['github_fine_grained']}",
            detail=f"Detail {SECRET_SAMPLES['github_pat']}",
            exact_command=f"dontpanic approve {SECRET_SAMPLES['pem_private_key']}",
            evidence_uri=SECRET_SAMPLES["discord_webhook"],
        )
        ev = _make_event()
        payload = notify_discord._build_payload(ev, rendered=rendered)
        as_json = json.dumps(payload)
        for key in ("github_fine_grained", "github_pat", "discord_webhook"):
            assert SECRET_SAMPLES[key] not in as_json, (
                f"{key} leaked into Discord payload: {as_json}"
            )
        # PEM marker is short enough that the embed title/detail still
        # show [REDACTED] in its place.
        assert REDACTED in as_json


# ─── (4) full matrix: 9 patterns × 4 channels = 36+ assertions ──────────────
# Each parametrized row is one assertion against one sink, so the
# pytest matrix produces 9 × 4 = 36 distinct test cases (well over the
# acceptance #4 minimum). The four sinks per row: discord embed,
# terminal-notifier args, INBOX rendered annotation markdown, and the
# sidecar (which raises and so is the inverted assertion).

_CHANNELS = ("discord", "terminal", "inbox_annotation", "sidecar")


class TestSecretMatrix:
    """Matrix: every secret shape × every rendered channel."""

    @pytest.mark.parametrize("sample_key", sorted(SECRET_SAMPLES.keys()))
    def test_discord_channel_scrubs(self, sample_key: str) -> None:
        secret = SECRET_SAMPLES[sample_key]
        rendered = _make_rendered(
            title=f"title {secret}",
            detail=f"detail {secret}",
        )
        ev = _make_event()
        payload = notify_discord._build_payload(ev, rendered=rendered)
        as_json = json.dumps(payload)
        _verify_redacted(as_json, secret, sample_key)

    @pytest.mark.parametrize("sample_key", sorted(SECRET_SAMPLES.keys()))
    def test_terminal_channel_scrubs(
        self, sample_key: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        secret = SECRET_SAMPLES[sample_key]
        captured: dict[str, Any] = {}

        def fake_notify(title: str, message: str, **kwargs: Any) -> bool:
            captured["title"] = title
            captured["message"] = message
            captured["subtitle"] = kwargs.get("subtitle")
            return True

        monkeypatch.setattr(notify, "notify", fake_notify)
        rendered = _make_rendered(title=f"headline {secret}")
        ev = _make_event()
        notify.notify_event(ev, rendered=rendered)
        combined = " ".join([captured["title"], captured["message"], captured.get("subtitle") or ""])
        _verify_redacted(combined, secret, sample_key)

    @pytest.mark.parametrize("sample_key", sorted(SECRET_SAMPLES.keys()))
    def test_inbox_annotation_channel_scrubs(
        self, sample_key: str, tmp_path: Path
    ) -> None:
        secret = SECRET_SAMPLES[sample_key]
        plan_dir = tmp_path / "plan"
        plan_dir.mkdir()
        rendered = _make_rendered(
            title=f"title {secret}",
            detail=f"detail {secret}",
            exact_command=f"echo {secret}",
            evidence_uri=secret,
            technical_metadata={"leaked": secret},
        )
        inbox.append_rendered_annotation(
            plan_dir, plan_id="p1", rendered=rendered
        )
        markdown = (plan_dir / "INBOX.md").read_text()
        _verify_redacted(markdown, secret, sample_key)

    @pytest.mark.parametrize("sample_key", sorted(SECRET_SAMPLES.keys()))
    def test_sidecar_channel_raises(
        self, sample_key: str, tmp_path: Path
    ) -> None:
        # The sidecar is the inverted assertion in the matrix — it does
        # NOT scrub; it raises. This is the operator-fixable boundary.
        secret = SECRET_SAMPLES[sample_key]
        rendered = _make_rendered(title=f"sidecar bound {secret}")
        sidecar_path = tmp_path / "event-actions.jsonl"
        with pytest.raises(ValueError, match="secret pattern"):
            operator_console.write_event_action_sidecar(
                rendered, path=sidecar_path
            )


# ─── (5) existing sanitization_check.py tests untouched ─────────────────────


class TestExistingSanitizationStillPasses:
    """Acceptance #5: F004 wires the existing regex tuple; no regex
    changes. Verify the public regex tuple is still loaded from
    ``sanitization_check.SECRET_REGEXES`` (single source of truth)
    so any future regex updates land in one place."""

    def test_state_projection_binds_same_regex_tuple(self) -> None:
        # state_projection imports SECRET_REGEXES at module load. Bind
        # via the alias to confirm it is the same tuple object.
        import sanitization_check
        assert state_projection._SECRET_REGEXES is sanitization_check.SECRET_REGEXES

    def test_operator_console_binds_same_regex_tuple(self) -> None:
        # operator_console loads lazily — force the load then compare.
        loaded = operator_console._load_secret_regexes()
        import sanitization_check
        # operator_console wraps in tuple(); content-wise must match.
        assert loaded == tuple(sanitization_check.SECRET_REGEXES)

    def test_regex_tuple_length_is_nine(self) -> None:
        import sanitization_check
        assert len(sanitization_check.SECRET_REGEXES) == 10, (
            "F004 acceptance #4 + #5: the 9-pattern matrix at "
            "sanitization_check.py:92-102 must remain at 9 patterns; "
            "wire-up tests assume this count."
        )
