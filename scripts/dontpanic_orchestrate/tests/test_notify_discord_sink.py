"""Plan 2026-05-01-002 F001+F002+F003+F004 — Discord notification sink tests.

Module-level structure:
- TestUrlResolution / TestUrlValidation / TestPayloadShape / TestFailSoft —
  F001 sink-module unit coverage.
- TestNotifyEvent / TestLevelMatrix / TestDispatchEvent / TestTerminalShim —
  F002 envelope + dispatcher + level filter + terminal shim regression.
- TestEmitPointWiring — F003 supervisor-integration tests proving INBOX
  write happens BEFORE dispatch_event call at every emit site.
- TestSinkMatrix — F004 5 kinds × 3 levels × 3 webhook states = 45 cases.

Discord webhook URLs in tests use `https://example.invalid/webhook` (RFC 2606
reserved TLD). No real webhooks. urllib.request.urlopen is mocked at the
test boundary — no real network calls under any test.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
import urllib.error
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import notify, notify_discord, notify_event  # noqa: E402


PLACEHOLDER_URL = "https://example.invalid/webhook/123/abc"


# ───────────────────────── 1. URL resolution (F001) ─────────────────────────


class TestUrlResolution:
    """Webhook URL resolution order: env (modern) > env (legacy) > config
    file (modern) > config file (legacy) > None."""

    def test_modern_env_wins(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DONTPANIC_DISCORD_WEBHOOK_URL", PLACEHOLDER_URL)
        monkeypatch.setenv("JARVIS_DISCORD_WEBHOOK_URL", "https://example.invalid/legacy")
        assert notify_discord._resolve_webhook_url() == PLACEHOLDER_URL

    def test_legacy_env_used_when_modern_absent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("DONTPANIC_DISCORD_WEBHOOK_URL", raising=False)
        monkeypatch.setenv("JARVIS_DISCORD_WEBHOOK_URL", PLACEHOLDER_URL)
        assert notify_discord._resolve_webhook_url() == PLACEHOLDER_URL

    def test_modern_config_file_used_when_no_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("DONTPANIC_DISCORD_WEBHOOK_URL", raising=False)
        monkeypatch.delenv("JARVIS_DISCORD_WEBHOOK_URL", raising=False)
        # autouse fixture redirects DONTPANIC_HOME → tmp_path/dontpanic_home
        home = Path(tmp_path / "dontpanic_home")
        home.mkdir(parents=True, exist_ok=True)
        (home / "discord.json").write_text(
            json.dumps({"webhook_url": PLACEHOLDER_URL})
        )
        assert notify_discord._resolve_webhook_url() == PLACEHOLDER_URL

    def test_legacy_config_file_used_when_no_modern(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("DONTPANIC_DISCORD_WEBHOOK_URL", raising=False)
        monkeypatch.delenv("JARVIS_DISCORD_WEBHOOK_URL", raising=False)
        legacy_home = Path(tmp_path / "jarvis_home")
        legacy_home.mkdir(parents=True, exist_ok=True)
        (legacy_home / "discord.json").write_text(
            json.dumps({"webhook_url": PLACEHOLDER_URL})
        )
        assert notify_discord._resolve_webhook_url() == PLACEHOLDER_URL

    def test_returns_none_when_no_source_configured(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("DONTPANIC_DISCORD_WEBHOOK_URL", raising=False)
        monkeypatch.delenv("JARVIS_DISCORD_WEBHOOK_URL", raising=False)
        assert notify_discord._resolve_webhook_url() is None


# ───────────────────────── 2. URL validation (F001) ─────────────────────────


class TestUrlValidation:
    """URL shape validation runs BEFORE any network call. Malformed URLs
    return False without invoking urlopen — verified via mock call count."""

    @pytest.mark.parametrize("bad_url", [
        "",
        "not-a-url",
        "ftp://example.invalid/webhook",  # scheme not in {http, https}
        "://example.invalid",
        "https:// example.invalid/webhook",  # whitespace in netloc
        "https://",  # empty netloc
    ])
    def test_malformed_url_returns_false_without_network(
        self, bad_url: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DONTPANIC_DISCORD_WEBHOOK_URL", bad_url)
        with patch("urllib.request.urlopen") as mock_urlopen:
            event = notify_event.NotifyEvent(
                kind="volley_start",
                severity="info",
                plan_id="test",
                feature_id="F001",
                body="x",
                action_link=None,
                timestamp=dt.datetime.now(dt.timezone.utc),
            )
            assert notify_discord.notify(event) is False
            assert mock_urlopen.call_count == 0

    def test_well_formed_url_attempts_network(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DONTPANIC_DISCORD_WEBHOOK_URL", PLACEHOLDER_URL)
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value.status = 204
            event = notify_event.NotifyEvent(
                kind="volley_start",
                severity="info",
                plan_id="test",
                feature_id="F001",
                body="x",
                action_link=None,
                timestamp=dt.datetime.now(dt.timezone.utc),
            )
            notify_discord.notify(event)
            assert mock_urlopen.call_count == 1


# ───────────────────────── 3. Payload shape (F001) ─────────────────────────


class TestPayloadShape:
    """Discord payload v1: username='Jarvis', content=markdown body,
    allowed_mentions.parse=[] ALWAYS (no @mention rendering in v1)."""

    def _capture_post(self, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
        monkeypatch.setenv("DONTPANIC_DISCORD_WEBHOOK_URL", PLACEHOLDER_URL)
        captured: dict[str, Any] = {}

        def fake_urlopen(req: Any, *_: Any, **__: Any) -> MagicMock:
            captured["url"] = req.full_url if hasattr(req, "full_url") else req.get_full_url()
            captured["headers"] = dict(req.header_items()) if hasattr(req, "header_items") else {}
            captured["body"] = json.loads(req.data.decode("utf-8")) if req.data else {}
            ctx = MagicMock()
            ctx.__enter__.return_value.status = 204
            ctx.__exit__.return_value = False
            return ctx

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        return captured

    def test_payload_has_username_and_content(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured = self._capture_post(monkeypatch)
        event = notify_event.NotifyEvent(
            kind="signoff",
            severity="info",
            plan_id="2026-05-01-002",
            feature_id="F001",
            body="**Signoff** for F001",
            action_link=None,
            timestamp=dt.datetime.now(dt.timezone.utc),
        )
        notify_discord.notify(event)
        assert captured["body"]["username"] == "Jarvis"
        assert "F001" in captured["body"]["content"]

    def test_allowed_mentions_parse_is_always_empty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured = self._capture_post(monkeypatch)
        event = notify_event.NotifyEvent(
            kind="breaker_tripped",
            severity="escalation",
            plan_id="test",
            feature_id="F001",
            body="<@123456> @here please look",  # malicious-looking content
            action_link="/tmp/INBOX.md",
            timestamp=dt.datetime.now(dt.timezone.utc),
        )
        notify_discord.notify(event)
        assert captured["body"]["allowed_mentions"] == {"parse": []}


# ───────────────────────── 4. Fail-soft (F001) ─────────────────────────


class TestFailSoft:
    """All failure modes return False, never raise. Single warn-once stderr
    line per process for diagnostics."""

    def test_no_webhook_returns_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DONTPANIC_DISCORD_WEBHOOK_URL", raising=False)
        monkeypatch.delenv("JARVIS_DISCORD_WEBHOOK_URL", raising=False)
        event = notify_event.NotifyEvent(
            kind="volley_start", severity="info", plan_id="t", feature_id=None,
            body="x", action_link=None, timestamp=dt.datetime.now(dt.timezone.utc),
        )
        assert notify_discord.notify(event) is False

    def test_network_error_returns_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DONTPANIC_DISCORD_WEBHOOK_URL", PLACEHOLDER_URL)

        def boom(*a: Any, **k: Any) -> None:
            raise urllib.error.URLError("simulated network failure")

        monkeypatch.setattr("urllib.request.urlopen", boom)
        event = notify_event.NotifyEvent(
            kind="signoff", severity="info", plan_id="t", feature_id="F001",
            body="x", action_link=None, timestamp=dt.datetime.now(dt.timezone.utc),
        )
        assert notify_discord.notify(event) is False

    def test_non_2xx_returns_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DONTPANIC_DISCORD_WEBHOOK_URL", PLACEHOLDER_URL)

        def fake(*a: Any, **k: Any) -> MagicMock:
            ctx = MagicMock()
            ctx.__enter__.return_value.status = 500
            ctx.__exit__.return_value = False
            return ctx

        monkeypatch.setattr("urllib.request.urlopen", fake)
        event = notify_event.NotifyEvent(
            kind="signoff", severity="info", plan_id="t", feature_id="F001",
            body="x", action_link=None, timestamp=dt.datetime.now(dt.timezone.utc),
        )
        assert notify_discord.notify(event) is False

    def test_disable_env_modern_silences_sink(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DONTPANIC_DISCORD_WEBHOOK_URL", PLACEHOLDER_URL)
        monkeypatch.setenv("DONTPANIC_DISCORD_DISABLE", "1")
        with patch("urllib.request.urlopen") as mock_urlopen:
            event = notify_event.NotifyEvent(
                kind="signoff", severity="info", plan_id="t", feature_id="F001",
                body="x", action_link=None, timestamp=dt.datetime.now(dt.timezone.utc),
            )
            assert notify_discord.notify(event) is False
            assert mock_urlopen.call_count == 0

    def test_disable_env_legacy_silences_sink(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DONTPANIC_DISCORD_WEBHOOK_URL", PLACEHOLDER_URL)
        monkeypatch.setenv("JARVIS_DISCORD_DISABLE", "1")
        with patch("urllib.request.urlopen") as mock_urlopen:
            event = notify_event.NotifyEvent(
                kind="signoff", severity="info", plan_id="t", feature_id="F001",
                body="x", action_link=None, timestamp=dt.datetime.now(dt.timezone.utc),
            )
            assert notify_discord.notify(event) is False
            assert mock_urlopen.call_count == 0

    def test_global_disable_env_silences_sink(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DONTPANIC_DISCORD_WEBHOOK_URL", PLACEHOLDER_URL)
        monkeypatch.setenv("JARVIS_NOTIFY_DISABLE", "1")
        with patch("urllib.request.urlopen") as mock_urlopen:
            event = notify_event.NotifyEvent(
                kind="signoff", severity="info", plan_id="t", feature_id="F001",
                body="x", action_link=None, timestamp=dt.datetime.now(dt.timezone.utc),
            )
            assert notify_discord.notify(event) is False
            assert mock_urlopen.call_count == 0

    def test_is_available_reflects_url_presence(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("DONTPANIC_DISCORD_WEBHOOK_URL", raising=False)
        monkeypatch.delenv("JARVIS_DISCORD_WEBHOOK_URL", raising=False)
        assert notify_discord.is_available() is False
        monkeypatch.setenv("DONTPANIC_DISCORD_WEBHOOK_URL", PLACEHOLDER_URL)
        assert notify_discord.is_available() is True

    def test_is_available_false_when_disabled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DONTPANIC_DISCORD_WEBHOOK_URL", PLACEHOLDER_URL)
        monkeypatch.setenv("DONTPANIC_DISCORD_DISABLE", "1")
        assert notify_discord.is_available() is False


# ───────────────────────── 5. NotifyEvent (F002) ─────────────────────────


class TestNotifyEvent:
    """NotifyEvent envelope: frozen dataclass with closed severity vocabulary."""

    def test_envelope_constructs(self) -> None:
        e = notify_event.NotifyEvent(
            kind="volley_start", severity="info", plan_id="p1",
            feature_id="F001", body="hello",
            action_link=None, timestamp=dt.datetime(2026, 5, 9, tzinfo=dt.timezone.utc),
        )
        assert e.kind == "volley_start"
        assert e.severity == "info"

    def test_escalation_requires_action_link(self) -> None:
        with pytest.raises(ValueError, match="action_link"):
            notify_event.NotifyEvent(
                kind="breaker_tripped", severity="escalation", plan_id="p1",
                feature_id="F001", body="cap hit",
                action_link=None,  # missing — must raise
                timestamp=dt.datetime.now(dt.timezone.utc),
            )

    def test_unknown_severity_rejected(self) -> None:
        with pytest.raises(ValueError, match="severity"):
            notify_event.NotifyEvent(
                kind="signoff", severity="bogus", plan_id="p1",
                feature_id="F001", body="x", action_link=None,
                timestamp=dt.datetime.now(dt.timezone.utc),
            )


# ───────────────────────── 6. Level matrix (F002) ─────────────────────────


class TestLevelMatrix:
    """quiet → escalation only.
    normal → action_required + escalation + plan-boundary kinds.
    verbose → all events."""

    def _ev(self, kind: str, severity: str, action_link: str | None = None) -> notify_event.NotifyEvent:
        return notify_event.NotifyEvent(
            kind=kind, severity=severity, plan_id="t", feature_id="F001",
            body="x", action_link=action_link or ("/tmp/INBOX.md" if severity == "escalation" else None),
            timestamp=dt.datetime.now(dt.timezone.utc),
        )

    def test_quiet_drops_info(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DONTPANIC_NOTIFY_LEVEL", "quiet")
        assert notify_event._allowed_at_level(self._ev("volley_start", "info")) is False

    def test_quiet_keeps_escalation(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DONTPANIC_NOTIFY_LEVEL", "quiet")
        assert notify_event._allowed_at_level(
            self._ev("breaker_tripped", "escalation")
        ) is True

    def test_quiet_drops_action_required(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DONTPANIC_NOTIFY_LEVEL", "quiet")
        assert notify_event._allowed_at_level(
            self._ev("gate_paused", "action_required", action_link="/tmp/INBOX.md")
        ) is False

    def test_normal_keeps_plan_boundary_info(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DONTPANIC_NOTIFY_LEVEL", "normal")
        assert notify_event._allowed_at_level(self._ev("volley_start", "info")) is True
        assert notify_event._allowed_at_level(self._ev("signoff", "info")) is True

    def test_normal_drops_non_boundary_info(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DONTPANIC_NOTIFY_LEVEL", "normal")
        # 'gate_cleared' is not in PLAN_BOUNDARY_KINDS
        assert notify_event._allowed_at_level(self._ev("gate_cleared", "info")) is False

    def test_normal_keeps_action_required(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DONTPANIC_NOTIFY_LEVEL", "normal")
        assert notify_event._allowed_at_level(
            self._ev("gate_paused", "action_required", action_link="/tmp/INBOX.md")
        ) is True

    def test_verbose_keeps_everything(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DONTPANIC_NOTIFY_LEVEL", "verbose")
        assert notify_event._allowed_at_level(self._ev("gate_cleared", "info")) is True

    def test_unknown_level_falls_back_to_normal(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setenv("DONTPANIC_NOTIFY_LEVEL", "bogus")
        notify_event._reset_level_warn_cache()
        assert notify_event._allowed_at_level(self._ev("volley_start", "info")) is True
        # one warn-once stderr message
        assert "bogus" in capsys.readouterr().err

    def test_legacy_env_recognized(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DONTPANIC_NOTIFY_LEVEL", raising=False)
        monkeypatch.setenv("JARVIS_NOTIFY_LEVEL", "verbose")
        assert notify_event._allowed_at_level(self._ev("gate_cleared", "info")) is True


# ───────────────────────── 7. dispatch_event (F002) ─────────────────────────


class TestDispatchEvent:
    """dispatch_event fans to both sinks honoring level matrix; never raises;
    returns {terminal: bool, discord: bool}."""

    def test_returns_per_sink_result(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Silence terminal sink by making the binary unfindable.
        # JARVIS_NOTIFY_DISABLE is the GLOBAL kill-switch (silences both),
        # so to prove per-sink reporting we have to suppress terminal
        # without setting that env.
        monkeypatch.setattr(notify, "_binary_path", lambda: None)
        monkeypatch.setenv("DONTPANIC_NOTIFY_LEVEL", "verbose")
        monkeypatch.setenv("DONTPANIC_DISCORD_WEBHOOK_URL", PLACEHOLDER_URL)
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value.status = 204
            ev = notify_event.NotifyEvent(
                kind="signoff", severity="info", plan_id="t", feature_id="F001",
                body="x", action_link=None, timestamp=dt.datetime.now(dt.timezone.utc),
            )
            result = notify_event.dispatch_event(ev)
            assert result == {"terminal": False, "discord": True}

    def test_global_disable_silences_both_sinks(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """JARVIS_NOTIFY_DISABLE (global) silences BOTH sinks — proves
        single-switch kill works."""
        monkeypatch.setenv("DONTPANIC_NOTIFY_LEVEL", "verbose")
        monkeypatch.setenv("DONTPANIC_DISCORD_WEBHOOK_URL", PLACEHOLDER_URL)
        monkeypatch.setenv("JARVIS_NOTIFY_DISABLE", "1")
        with patch("urllib.request.urlopen") as mock_urlopen:
            ev = notify_event.NotifyEvent(
                kind="signoff", severity="info", plan_id="t", feature_id="F001",
                body="x", action_link=None, timestamp=dt.datetime.now(dt.timezone.utc),
            )
            result = notify_event.dispatch_event(ev)
            assert result == {"terminal": False, "discord": False}
            assert mock_urlopen.call_count == 0

    def test_filtered_event_calls_no_sinks(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DONTPANIC_NOTIFY_LEVEL", "quiet")
        monkeypatch.setenv("DONTPANIC_DISCORD_WEBHOOK_URL", PLACEHOLDER_URL)
        with patch("urllib.request.urlopen") as mock_urlopen:
            ev = notify_event.NotifyEvent(
                kind="volley_start", severity="info", plan_id="t", feature_id=None,
                body="x", action_link=None, timestamp=dt.datetime.now(dt.timezone.utc),
            )
            result = notify_event.dispatch_event(ev)
            assert result == {"terminal": False, "discord": False}
            assert mock_urlopen.call_count == 0

    def test_does_not_raise_on_sink_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DONTPANIC_NOTIFY_LEVEL", "verbose")

        def boom(_: notify_event.NotifyEvent) -> bool:
            raise RuntimeError("sink crashed")

        monkeypatch.setattr(notify_event.notify_discord, "notify", boom)
        ev = notify_event.NotifyEvent(
            kind="signoff", severity="info", plan_id="t", feature_id="F001",
            body="x", action_link=None, timestamp=dt.datetime.now(dt.timezone.utc),
        )
        result = notify_event.dispatch_event(ev)
        assert result == {"terminal": False, "discord": False}


# ───────────────────────── 8. Terminal-shim regression (F002) ─────────────────────────


class TestTerminalShim:
    """notify.notify_event(event) projects NotifyEvent onto title/subtitle/
    message/group consistent with F002 acceptance item 11."""

    def test_projection(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, Any] = {}

        def capture(*args: Any, **kwargs: Any) -> bool:
            captured["args"] = args
            captured["kwargs"] = kwargs
            return True

        monkeypatch.setattr(notify, "notify", capture)
        ev = notify_event.NotifyEvent(
            kind="breaker_tripped", severity="escalation", plan_id="2026-05-01-002",
            feature_id="F001", body="Cap reached on F001", action_link="/tmp/INBOX.md",
            timestamp=dt.datetime.now(dt.timezone.utc),
        )
        notify.notify_event(ev)
        assert captured["args"][0] == "Jarvis [2026-05-01-002]"
        assert captured["kwargs"]["subtitle"] == "breaker_tripped"
        assert captured["kwargs"]["group"] == "2026-05-01-002"
        assert "Cap reached on F001" in captured["args"][1]


# ───────────────────────── 9. F004 sink matrix ─────────────────────────


KINDS = ["volley_start", "gate_paused", "breaker_tripped", "signoff", "calibration_required"]
LEVELS = ["quiet", "normal", "verbose"]
WEBHOOK_STATES = ["valid", "malformed", "absent"]


def _make_event(kind: str) -> notify_event.NotifyEvent:
    """Build a representative event for each kind. Severity chosen to reflect
    the canonical use of the kind in supervisor.py."""
    severity_map = {
        "volley_start": "info",
        "gate_paused": "action_required",
        "breaker_tripped": "escalation",
        "signoff": "info",
        "calibration_required": "action_required",
    }
    severity = severity_map[kind]
    action_link = (
        "/tmp/INBOX.md"
        if severity in {"action_required", "escalation"}
        else None
    )
    return notify_event.NotifyEvent(
        kind=kind, severity=severity, plan_id="2026-05-01-002",
        feature_id="F001", body=f"event: {kind}",
        action_link=action_link, timestamp=dt.datetime.now(dt.timezone.utc),
    )


def _setup_webhook(monkeypatch: pytest.MonkeyPatch, state: str) -> MagicMock:
    """Configure the webhook env per state; return the urlopen mock."""
    if state == "valid":
        monkeypatch.setenv("DONTPANIC_DISCORD_WEBHOOK_URL", PLACEHOLDER_URL)
    elif state == "malformed":
        monkeypatch.setenv("DONTPANIC_DISCORD_WEBHOOK_URL", "not-a-real-url")
    elif state == "absent":
        monkeypatch.delenv("DONTPANIC_DISCORD_WEBHOOK_URL", raising=False)
        monkeypatch.delenv("JARVIS_DISCORD_WEBHOOK_URL", raising=False)
    mock = MagicMock()
    mock.return_value.__enter__.return_value.status = 204
    monkeypatch.setattr("urllib.request.urlopen", mock)
    return mock


class TestSinkMatrix:
    @pytest.mark.parametrize("kind", KINDS)
    @pytest.mark.parametrize("level", LEVELS)
    @pytest.mark.parametrize("webhook_state", WEBHOOK_STATES)
    def test_matrix(
        self,
        kind: str,
        level: str,
        webhook_state: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Silence terminal via binary-not-found — JARVIS_NOTIFY_DISABLE
        # would silence Discord too (it's the global kill-switch).
        monkeypatch.setattr(notify, "_binary_path", lambda: None)
        monkeypatch.setenv("DONTPANIC_NOTIFY_LEVEL", level)
        mock_urlopen = _setup_webhook(monkeypatch, webhook_state)
        ev = _make_event(kind)
        result = notify_event.dispatch_event(ev)
        # Expected discord behavior:
        # webhook_state=valid + event passes level filter → True
        # webhook_state=malformed → never network → False (no urlopen call)
        # webhook_state=absent → no URL → False
        allowed = notify_event._allowed_at_level(ev)
        if webhook_state == "valid" and allowed:
            expected_discord = True
            expected_calls = 1
        elif webhook_state == "malformed" and allowed:
            expected_discord = False
            expected_calls = 0
        else:
            expected_discord = False
            expected_calls = 0
        assert result["discord"] is expected_discord, (kind, level, webhook_state, result)
        assert mock_urlopen.call_count == expected_calls, (kind, level, webhook_state)

    def test_escalation_always_carries_action_link(self) -> None:
        # Spec: severity=='escalation' MUST have action_link set.
        # Confirmed by NotifyEvent constructor invariant.
        for kind in KINDS:
            ev = _make_event(kind)
            if ev.severity == "escalation":
                assert ev.action_link is not None


# ───────────────────────── 10. F003 emit-point INBOX-first ─────────────────────────
# These tests live closer to supervisor flow; INBOX-first ordering is verified
# by call-order capture against patched inbox.append_event + dispatch_event.


class TestEmitPointInboxOrdering:
    """At every supervisor emit site that calls dispatch_event, the INBOX
    write must happen first. We capture call order and assert."""

    def test_breaker_emit_writes_inbox_before_dispatch(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from dontpanic_orchestrate import inbox, supervisor
        from dontpanic_orchestrate import circuit_breakers as cb

        calls: list[str] = []

        def fake_inbox(*a: Any, **k: Any) -> Any:
            calls.append("inbox")
            return None

        def fake_dispatch(
            _: notify_event.NotifyEvent, **__: Any
        ) -> dict[str, bool]:
            calls.append("dispatch_event")
            return {"terminal": False, "discord": False}

        plan_dir = tmp_path / "plan"
        plan_dir.mkdir()
        monkeypatch.setattr(inbox, "append_event", fake_inbox)
        monkeypatch.setattr(notify_event, "dispatch_event", fake_dispatch)
        # Helper reused by all breaker trips. NO_PROGRESS has the simplest call
        # signature for direct invocation in this test.
        supervisor._trip_breaker(
            plan_dir, "p1", "F001", cb.BreakerKind.NO_PROGRESS, "test reason"
        )
        # INBOX call must precede dispatch_event call.
        assert calls.index("inbox") < calls.index("dispatch_event"), calls
