"""Plan 2026-07-27-001 F006 — Buzz notify sink tests.

Coverage per acceptance:
- Config resolution: env path override > $DONTPANIC_HOME/buzz.json > None;
  invalid / incomplete configs load as None.
- Fail-soft: unconfigured / disabled / missing buzz CLI / unresolvable key /
  nonzero exit / subprocess exception all return False and never raise —
  with NO subprocess attempt for the pre-delivery failure modes.
- Delivery: mocked `buzz messages send` invocation; relay URL and key
  material travel ONLY via the subprocess env (never argv, never content).
  No network, no real binary.
- Redaction: secret shapes scrubbed, home path collapsed to ``~``, content
  hard-capped (summary-only; no full transcripts).
- dispatch_event fans to buzz when configured and records False (without
  raising) when unconfigured.
- Docs copy steers operators to a PRIVATE community.

subprocess.run is mocked at the module boundary — no buzz binary and no
network under any test. The autouse conftest fixture redirects
DONTPANIC_HOME to a per-test tmp dir.
"""

from __future__ import annotations

import datetime as dt
import json
import subprocess
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import notify, notify_buzz, notify_event  # noqa: E402

ROOT = HERE.parents[3]

# Buzz channels are UUIDs; the relay URL is the private-community authority
# (the CLI selects the community via BUZZ_RELAY_URL, not argv).
CHANNEL_STATUS = "0f5e8a3c-9d41-4c7b-8a2e-1d3f5b7c9e01"
CHANNEL_GATES = "b2c4d6e8-1a3b-4c5d-8e7f-9a0b1c2d3e4f"
VALID_CONFIG = {
    "relay_url": "https://relay.example.invalid",
    "channels": [CHANNEL_STATUS, CHANNEL_GATES],
    "reporter_key_ref": "env:BUZZ_PRIVATE_KEY",
}
KEY_MATERIAL = "nsec1exampleprivatekeymaterial"


def _event(**overrides: Any) -> notify_event.NotifyEvent:
    base: dict[str, Any] = dict(
        kind="signoff",
        severity="info",
        plan_id="2026-07-27-001",
        feature_id="F006",
        body="plan reached signoff",
        action_link=None,
        timestamp=dt.datetime.now(dt.timezone.utc),
    )
    base.update(overrides)
    return notify_event.NotifyEvent(**base)


@pytest.fixture(autouse=True)
def _reset_warn_cache() -> None:
    notify_buzz.reset_warning_cache()


@pytest.fixture()
def configured_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Write a valid buzz.json under the conftest-redirected DONTPANIC_HOME
    and provide the reporter key env var."""
    import os

    home = Path(os.environ["DONTPANIC_HOME"])
    home.mkdir(parents=True, exist_ok=True)
    (home / "buzz.json").write_text(json.dumps(VALID_CONFIG))
    monkeypatch.setenv("BUZZ_PRIVATE_KEY", KEY_MATERIAL)
    monkeypatch.delenv("DONTPANIC_BUZZ_CONFIG", raising=False)
    monkeypatch.delenv("DONTPANIC_BUZZ_DISABLE", raising=False)
    monkeypatch.delenv("JARVIS_NOTIFY_DISABLE", raising=False)
    return home


def _ok_proc() -> MagicMock:
    proc = MagicMock()
    proc.returncode = 0
    return proc


# ───────────────────────── 1. Config resolution ─────────────────────────


class TestConfigResolution:
    def test_env_path_override_wins(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        override = tmp_path / "elsewhere" / "buzz.json"
        override.parent.mkdir(parents=True)
        override.write_text(json.dumps(VALID_CONFIG))
        monkeypatch.setenv("DONTPANIC_BUZZ_CONFIG", str(override))
        config = notify_buzz._load_config()
        assert config is not None
        assert config.relay_url == VALID_CONFIG["relay_url"]
        assert config.channel == CHANNEL_STATUS

    def test_home_file_used_when_no_override(self, configured_home: Path) -> None:
        config = notify_buzz._load_config()
        assert config is not None
        assert config.relay_url == VALID_CONFIG["relay_url"]

    def test_none_when_unconfigured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DONTPANIC_BUZZ_CONFIG", raising=False)
        assert notify_buzz._load_config() is None

    @pytest.mark.parametrize(
        "payload",
        [
            "not json at all",
            json.dumps(["a", "list"]),
            json.dumps({k: v for k, v in VALID_CONFIG.items() if k != "relay_url"}),
            json.dumps({**VALID_CONFIG, "relay_url": "   "}),
            json.dumps({**VALID_CONFIG, "channels": []}),
            json.dumps({**VALID_CONFIG, "channels": ["", "x"]}),
            json.dumps({**VALID_CONFIG, "reporter_key_ref": None}),
        ],
    )
    def test_invalid_or_incomplete_config_loads_as_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, payload: str
    ) -> None:
        bad = tmp_path / "bad-buzz.json"
        bad.write_text(payload)
        monkeypatch.setenv("DONTPANIC_BUZZ_CONFIG", str(bad))
        assert notify_buzz._load_config() is None


# ───────────────────────── 2. Fail-soft (never raise) ─────────────────────────


class TestFailSoft:
    def test_unconfigured_returns_false_without_subprocess(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("DONTPANIC_BUZZ_CONFIG", raising=False)
        with patch("subprocess.run") as mock_run:
            assert notify_buzz.notify(_event()) is False
            assert mock_run.call_count == 0

    def test_sink_disable_env_silences(
        self, configured_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DONTPANIC_BUZZ_DISABLE", "1")
        with patch("subprocess.run") as mock_run:
            assert notify_buzz.notify(_event()) is False
            assert mock_run.call_count == 0

    def test_global_disable_env_silences(
        self, configured_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("JARVIS_NOTIFY_DISABLE", "1")
        with patch("subprocess.run") as mock_run:
            assert notify_buzz.notify(_event()) is False
            assert mock_run.call_count == 0

    def test_missing_cli_returns_false_without_subprocess(
        self, configured_home: Path
    ) -> None:
        with patch.object(notify_buzz.shutil, "which", return_value=None), patch(
            "subprocess.run"
        ) as mock_run:
            assert notify_buzz.notify(_event()) is False
            assert mock_run.call_count == 0

    def test_unresolvable_key_returns_false_without_subprocess(
        self, configured_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("BUZZ_PRIVATE_KEY", raising=False)
        with patch.object(
            notify_buzz.shutil, "which", return_value="/usr/local/bin/buzz"
        ), patch("subprocess.run") as mock_run:
            assert notify_buzz.notify(_event()) is False
            assert mock_run.call_count == 0

    def test_nonzero_exit_returns_false(self, configured_home: Path) -> None:
        proc = MagicMock()
        proc.returncode = 3
        with patch.object(
            notify_buzz.shutil, "which", return_value="/usr/local/bin/buzz"
        ), patch.object(notify_buzz.subprocess, "run", return_value=proc):
            assert notify_buzz.notify(_event()) is False

    @pytest.mark.parametrize(
        "exc",
        [
            OSError("boom"),
            subprocess.TimeoutExpired(cmd="buzz", timeout=10),
        ],
    )
    def test_subprocess_exception_returns_false_never_raises(
        self, configured_home: Path, exc: Exception
    ) -> None:
        with patch.object(
            notify_buzz.shutil, "which", return_value="/usr/local/bin/buzz"
        ), patch.object(notify_buzz.subprocess, "run", side_effect=exc):
            assert notify_buzz.notify(_event()) is False

    def test_is_available_reflects_config_and_cli(
        self, configured_home: Path
    ) -> None:
        with patch.object(
            notify_buzz.shutil, "which", return_value="/usr/local/bin/buzz"
        ):
            assert notify_buzz.is_available() is True
        with patch.object(notify_buzz.shutil, "which", return_value=None):
            assert notify_buzz.is_available() is False

    def test_is_available_false_when_unconfigured(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("DONTPANIC_BUZZ_CONFIG", raising=False)
        assert notify_buzz.is_available() is False


# ───────────────────────── 3. Delivery (mocked buzz CLI) ─────────────────────────


class TestDelivery:
    def _run_notify(self, event: notify_event.NotifyEvent) -> tuple[bool, Any]:
        with patch.object(
            notify_buzz.shutil, "which", return_value="/usr/local/bin/buzz"
        ), patch.object(
            notify_buzz.subprocess, "run", return_value=_ok_proc()
        ) as mock_run:
            result = notify_buzz.notify(event)
        return result, mock_run

    def test_success_returns_true_with_expected_argv(
        self, configured_home: Path
    ) -> None:
        result, mock_run = self._run_notify(_event())
        assert result is True
        assert mock_run.call_count == 1
        # Official Buzz CLI contract: `buzz messages send --channel <uuid>
        # --content -`; relay selection travels via BUZZ_RELAY_URL, never argv.
        argv = mock_run.call_args.args[0]
        assert argv == [
            "/usr/local/bin/buzz",
            "messages",
            "send",
            "--channel",
            CHANNEL_STATUS,
            "--content",
            "-",
        ]
        kwargs = mock_run.call_args.kwargs
        assert kwargs.get("shell") is not True
        assert kwargs["env"]["BUZZ_RELAY_URL"] == VALID_CONFIG["relay_url"]
        assert VALID_CONFIG["relay_url"] not in argv

    def test_key_material_only_in_env_never_argv_or_content(
        self, configured_home: Path
    ) -> None:
        result, mock_run = self._run_notify(_event())
        assert result is True
        argv = mock_run.call_args.args[0]
        kwargs = mock_run.call_args.kwargs
        assert KEY_MATERIAL not in " ".join(argv)
        assert KEY_MATERIAL not in kwargs["input"]
        assert kwargs["env"]["BUZZ_PRIVATE_KEY"] == KEY_MATERIAL

    def test_whitespace_only_body_never_raises(
        self, configured_home: Path
    ) -> None:
        # Regression (codex-auditor F006 i1): a configured event whose body
        # strips to empty used to raise IndexError inside _format_content.
        # Fail-soft contract: notify() returns a bool, never raises, and the
        # posted content is the header projection alone.
        result, mock_run = self._run_notify(_event(body="   \n\t\n  "))
        assert result is True
        content = mock_run.call_args.kwargs["input"]
        assert "[2026-07-27-001] F006 signoff" in content

    def test_file_key_ref_resolves(
        self, configured_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        key_file = tmp_path / "reporter.key"
        key_file.write_text(KEY_MATERIAL + "\n")
        (configured_home / "buzz.json").write_text(
            json.dumps({**VALID_CONFIG, "reporter_key_ref": str(key_file)})
        )
        monkeypatch.delenv("BUZZ_PRIVATE_KEY", raising=False)
        result, mock_run = self._run_notify(_event())
        assert result is True
        assert mock_run.call_args.kwargs["env"]["BUZZ_PRIVATE_KEY"] == KEY_MATERIAL


# ───────────────────────── 4. Redaction (summary-only) ─────────────────────────


class TestRedaction:
    def test_secret_shapes_scrubbed_from_content(self, configured_home: Path) -> None:
        token = "ghp_" + "a1B2" * 9  # matches the GitHub PAT secret regex
        event = _event(body=f"push failed with token {token} retrying")
        with patch.object(
            notify_buzz.shutil, "which", return_value="/usr/local/bin/buzz"
        ), patch.object(
            notify_buzz.subprocess, "run", return_value=_ok_proc()
        ) as mock_run:
            assert notify_buzz.notify(event) is True
        content = mock_run.call_args.kwargs["input"]
        assert token not in content
        assert "[REDACTED]" in content

    def test_secret_crossing_truncation_boundary_never_leaks_prefix(
        self, configured_home: Path
    ) -> None:
        # Regression (codex-auditor F006 i2): truncating BEFORE scrubbing
        # sliced a credential at the detail cap so its prefix (`ghp_a1B2...`)
        # leaked unredacted. Scrubbing must run on the untruncated source.
        token = "ghp_" + "a1B2" * 9
        padding = "x" * (notify_buzz._DETAIL_LIMIT - 10)
        event = _event(body=f"{padding} {token} trailing")
        with patch.object(
            notify_buzz.shutil, "which", return_value="/usr/local/bin/buzz"
        ), patch.object(
            notify_buzz.subprocess, "run", return_value=_ok_proc()
        ) as mock_run:
            assert notify_buzz.notify(event) is True
        content = mock_run.call_args.kwargs["input"]
        assert "ghp_" not in content
        # The placeholder itself may be sliced by the cap ("[REDAC...") —
        # that's fine; what matters is scrub ran on the untruncated source.
        assert "[REDAC" in content

    def test_home_path_collapsed(self, configured_home: Path) -> None:
        import os

        home = os.path.expanduser("~")
        event = _event(body=f"see {home}/some/plan/dir/INBOX.md for details")
        with patch.object(
            notify_buzz.shutil, "which", return_value="/usr/local/bin/buzz"
        ), patch.object(
            notify_buzz.subprocess, "run", return_value=_ok_proc()
        ) as mock_run:
            assert notify_buzz.notify(event) is True
        content = mock_run.call_args.kwargs["input"]
        assert home not in content
        assert "~/some/plan/dir/INBOX.md" in content

    def test_other_users_home_paths_redacted(self, configured_home: Path) -> None:
        # Regression (codex-auditor F006 i2): only the current process home
        # was collapsed — other users' macOS/Linux/Windows home paths leaked
        # usernames onto the relay.
        event = _event(
            body=(
                "see /Users/otherperson/private/repo/transcript.md and "
                "/home/svcacct/deploy.log and C:\\Users\\Someone\\notes.txt "
                "and /root/secrets.env"
            )
        )
        with patch.object(
            notify_buzz.shutil, "which", return_value="/usr/local/bin/buzz"
        ), patch.object(
            notify_buzz.subprocess, "run", return_value=_ok_proc()
        ) as mock_run:
            assert notify_buzz.notify(event) is True
        content = mock_run.call_args.kwargs["input"]
        assert "otherperson" not in content
        assert "svcacct" not in content
        assert "Someone" not in content
        assert "/root/" not in content
        assert "~/private/repo/transcript.md" in content

    def test_content_is_summary_only_first_line_and_capped(
        self, configured_home: Path
    ) -> None:
        transcript = "first summary line\n" + "\n".join(
            f"transcript line {i} " + "x" * 80 for i in range(200)
        )
        event = _event(body=transcript)
        with patch.object(
            notify_buzz.shutil, "which", return_value="/usr/local/bin/buzz"
        ), patch.object(
            notify_buzz.subprocess, "run", return_value=_ok_proc()
        ) as mock_run:
            assert notify_buzz.notify(event) is True
        content = mock_run.call_args.kwargs["input"]
        assert "first summary line" in content
        assert "transcript line 5" not in content  # body beyond line 1 never posts
        assert len(content) <= notify_buzz._CONTENT_TOTAL_LIMIT


# ───────────────────────── 5. dispatch_event fan-out ─────────────────────────


class TestDispatchFanout:
    def test_dispatch_fans_to_buzz_when_configured(
        self, configured_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DONTPANIC_NOTIFY_LEVEL", "verbose")
        # Silence terminal + discord so the assertion isolates buzz.
        monkeypatch.setattr(notify, "_binary_path", lambda: None)
        monkeypatch.delenv("DONTPANIC_DISCORD_WEBHOOK_URL", raising=False)
        monkeypatch.delenv("JARVIS_DISCORD_WEBHOOK_URL", raising=False)
        with patch.object(
            notify_buzz.shutil, "which", return_value="/usr/local/bin/buzz"
        ), patch.object(notify_buzz.subprocess, "run", return_value=_ok_proc()):
            # kind=signoff has no DISPOSITION_TABLE entry → legacy fan-out path.
            result = notify_event.dispatch_event(_event())
        assert result["buzz"] is True

    def test_dispatch_records_false_and_does_not_raise_when_unconfigured(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DONTPANIC_NOTIFY_LEVEL", "verbose")
        monkeypatch.setattr(notify, "_binary_path", lambda: None)
        monkeypatch.delenv("DONTPANIC_BUZZ_CONFIG", raising=False)
        monkeypatch.delenv("DONTPANIC_DISCORD_WEBHOOK_URL", raising=False)
        monkeypatch.delenv("JARVIS_DISCORD_WEBHOOK_URL", raising=False)
        result = notify_event.dispatch_event(_event())
        assert result["buzz"] is False

    def test_buzz_sink_exception_is_suppressed_by_dispatcher(
        self, configured_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DONTPANIC_NOTIFY_LEVEL", "verbose")
        monkeypatch.setattr(notify, "_binary_path", lambda: None)
        monkeypatch.delenv("DONTPANIC_DISCORD_WEBHOOK_URL", raising=False)
        monkeypatch.delenv("JARVIS_DISCORD_WEBHOOK_URL", raising=False)
        monkeypatch.setattr(
            notify_buzz,
            "notify",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("sink bug")),
        )
        result = notify_event.dispatch_event(_event())
        assert result["buzz"] is False


# ───────────────────────── 6. Config docs copy ─────────────────────────


class TestConfigDocsCopy:
    """F006 acceptance: example/config copy steers operators to a PRIVATE
    community and never seeds a public support community as the default."""

    def test_getting_started_example_is_private_and_secret_free(self) -> None:
        text = (ROOT / "docs" / "GETTING_STARTED.md").read_text(encoding="utf-8")
        section = text.split(
            "## Buzz (Strongly Recommended): Private Community Setup", 1
        )[1].split("\n## ", 1)[0]
        assert "buzz.json" in section
        assert "private" in section.lower()
        # relay_url is the authoritative private-community selector (the CLI
        # has no separate community key/flag) — the unsupported `community`
        # config key must not reappear in the example.
        assert "relay_url" in section
        assert '"community"' not in section
        # Never a concrete public community destination in config copy.
        assert "buzz.xyz/c/" not in section
        # reporter_key_ref stays a reference, never key material.
        assert "env:BUZZ_PRIVATE_KEY" in section
