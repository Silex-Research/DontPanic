"""Test isolation for dontpanic_orchestrate.

Five operator-state surfaces cross-pollute tests when not isolated:

  1. ~/.jarvis/breaker_history.jsonl (F006 global circuit breaker) —
     every iteration_cap hit writes a row; once any 24h window holds 3
     rows the global breaker trips and unrelated tests start returning
     stopped_global_breaker.

  2. ~/.jarvis/active_supervisors.jsonl (F023 EC13 registry) — register/
     unregister roundtrips on every dispatch_volley(). Tests running
     under sandboxes or read-only $HOME also fail outright trying to
     write the operator path.

  3. ~/.jarvis/interactive_state.json (F007 interactive backoff) —
     `claude-touch` and the supervisor's admission reconcile both
     read/write this; without isolation the operator's real touch state
     bleeds into tests (and vice versa).

  4. ~/.jarvis/quota_state.json (F020 quota gate, also read by F006
     budget_ceiling and F007 quota_threshold admission) — operator's
     real percent_weekly will trip defer:quota_threshold and
     breaker:budget_ceiling in unrelated tests if not isolated.

  5. Plan 2026-05-09-001 F001 — ~/.dontpanic/global_config.json (modern)
     and ~/.jarvis/config.json (legacy) carry operator role assignments
     read by sufficiency_auditor / completion_dispatch / completion_gate
     resolvers. Without redirecting DONTPANIC_HOME / JARVIS_HOME, these
     leak operator-specific roles.goal_auditor into ~50 tests that
     declare different agent pairings, producing SameVendorRefused-style
     failures that have nothing to do with the test's own assertions.

Solution: autouse fixture redirects all five surfaces to per-test
tmp_path entries via JARVIS_BREAKER_HISTORY_PATH /
JARVIS_ACTIVE_SUPERVISORS_PATH / JARVIS_INTERACTIVE_STATE_PATH /
JARVIS_QUOTA_STATE_PATH / JARVIS_QUOTA_CAPS_PATH plus the home-dir env
vars DONTPANIC_HOME and JARVIS_HOME. Honored by the corresponding
*_effective_*_path() helpers in each module and by
:func:`dontpanic_orchestrate.global_config.dontpanic_home`.

Tests that want a specific quota state can write to
$JARVIS_QUOTA_STATE_PATH explicitly (it's a known per-test path).
Tests that want a specific operator config can write to
$DONTPANIC_HOME/global_config.json or $JARVIS_HOME/config.json on the
redirected paths.
"""

from __future__ import annotations

import os
import re

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register `--snapshot-update` so pinned-fixture suites (currently the
    F005 cross-channel event-messaging snapshots) can be regenerated via the
    pytest CLI instead of an env var. Mirrors the convention used by snapshot
    plugins like syrupy / pytest-snapshot so the authoring workflow matches
    standard pytest muscle memory.

    The legacy `DONTPANIC_SNAPSHOT_UPDATE=1` env var still works (see
    :func:`snapshot_update`) so any in-flight scripts continue to function.
    """
    group = parser.getgroup("dontpanic", "DontPanic test options")
    group.addoption(
        "--snapshot-update",
        action="store_true",
        default=False,
        dest="snapshot_update",
        help=(
            "Regenerate pinned snapshot fixtures (writes JSON to "
            "tests/fixtures/event_messaging_snapshots/). Review the diff "
            "in code review before committing the new pin."
        ),
    )


@pytest.fixture(scope="session")
def snapshot_update(request: pytest.FixtureRequest) -> bool:
    """True when snapshot regeneration is requested, via either:

      - `pytest --snapshot-update` (preferred), or
      - `DONTPANIC_SNAPSHOT_UPDATE=1` env var (legacy, kept for
        scripts already wired to the old name).

    Tests should branch on this fixture (not read the env var directly)
    so both invocation styles stay in sync.
    """
    if request.config.getoption("snapshot_update"):
        return True
    return os.environ.get("DONTPANIC_SNAPSHOT_UPDATE") == "1"


# Plan 2026-05-09-002 F001 — keep test envelope summaries consistent with
# overridden audit_status. Tests that monkey-patch ``audit_status`` after
# ``audit_writer.build_audit`` derived it from a static `_summary` builder
# end up with envelopes whose narrative verdict line ("Overall verdict:
# signed_off.") disagrees with the structured field — exactly the
# regression F001 catches. This helper rewrites the canonical verdict
# line to match, so test fixtures don't trigger production fail-loud
# detection on what is just test-level drift.

_VERDICT_LINE_REWRITES: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(p, re.IGNORECASE | re.MULTILINE), r)
    for (p, r) in (
        (r"^(\s*\*{2}\s*verdict\s*:\s*)[a-z_]+(\s*\*{2}\s*\.?\s*)$", r"\g<1>{status}\g<2>"),
        (r"^(\s*overall\s+verdict\s*:\s*)[a-z_]+(\s*\.?\s*)$", r"\g<1>{status}\g<2>"),
        (r"^(\s*verdict\s*:\s*)[a-z_]+(\s*\.?\s*)$", r"\g<1>{status}\g<2>"),
    )
)


def _rewrite_summary_verdict(summary: str, status: str) -> str:
    """Replace the first canonical narrative verdict line in ``summary``
    with ``status``. Idempotent: returns ``summary`` unchanged when no
    canonical pattern matches. Used by test fixtures that override
    ``audit_status`` after the fact and need the summary to stay
    consistent so plan 2026-05-09-002 F001's verdict-mismatch detector
    doesn't fire on what is just test-fixture artifact."""
    if not isinstance(summary, str):
        return summary
    for pattern, repl_template in _VERDICT_LINE_REWRITES:
        new = pattern.sub(repl_template.format(status=status), summary, count=1)
        if new != summary:
            return new
    return summary


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "live_auditor: this test deliberately invokes a real (paid) cross-vendor "
        "auditor; exempts it from the offline-fixture guard. Use sparingly.",
    )


class _PaidAuditorInTest(BaseException):
    """Raised when a test reaches a real (paid) auditor dispatch without opting
    in via @pytest.mark.live_auditor. Subclasses BaseException so production
    ``except Exception`` swallow-paths cannot mask it — the test fails loudly
    instead of silently spending a Codex/Claude call."""


# Production (paid) auditor-dispatch entrypoint the guard MUST neutralize, as a
# (module import path, attribute) pair. Patched with raising=True so a RENAME
# fails the guard LOUDLY (every test errors in setup) instead of silently
# re-opening paid dispatch — the fail-open mode CodeRabbit flagged on PR #32.
#
# Scope is the SUFFICIENCY production-dispatch BUILDER only: offline sufficiency
# tests never call it (they inject `dispatch=` or reuse fingerprinted fixtures),
# so neutralizing it can only catch an accidental real-auditor call — exactly the
# regression this PR's regen path could introduce. The completion path is NOT
# listed on purpose: its offline tests legitimately route through
# ``completion_dispatch._dispatch_via_executor`` with a MOCKED ``get_executor``,
# so patching that function would block real offline tests (false positives); its
# paid boundary is the executor's network call, which those tests already avoid
# via the mock + the ``dispatch=`` seam. Add a symbol here only if it is a paid
# builder that NO offline test legitimately invokes.
_PAID_DISPATCH_ENTRYPOINTS: tuple[tuple[str, str], ...] = (
    ("dontpanic_orchestrate.sufficiency_auditor", "_production_sufficiency_dispatch"),
)


@pytest.fixture(autouse=True)
def _block_paid_auditor_dispatch(request, monkeypatch):
    """Offline-fixture protection (2026-06-09): governance regression tests must
    NEVER invoke a paid auditor. After the lock gate learned to regenerate stale
    sufficiency findings, a fixture that seeded fingerprint-less findings tripped
    the live ``generate_sufficiency_findings`` path and fired real Codex calls.

    Patches every production paid-dispatch entrypoint to raise loudly so any test
    that reaches one fails fast. FAIL-CLOSED: each symbol is patched with
    ``raising=True``, so if a paid path is renamed the guard errors in setup
    (alerting the maintainer to update :data:`_PAID_DISPATCH_ENTRYPOINTS`) rather
    than silently no-op'ing. Offline tests inject ``dispatch=`` or seed fresh
    (fingerprinted) fixtures; a deliberately live test opts in with
    ``@pytest.mark.live_auditor``."""
    if request.node.get_closest_marker("live_auditor"):
        return

    import importlib

    def _blocked(*_args, **_kwargs):
        raise _PaidAuditorInTest(
            "a test reached a real (paid) auditor dispatch — inject a fake "
            "`dispatch=`, seed fresh fingerprinted findings, or mark the test "
            "@pytest.mark.live_auditor. Governance regression tests stay offline."
        )

    for module_path, attr in _PAID_DISPATCH_ENTRYPOINTS:
        module = importlib.import_module(module_path)
        # raising=True (default): a missing/renamed symbol fails HERE, loudly.
        monkeypatch.setattr(module, attr, _blocked)


@pytest.fixture(autouse=True)
def _isolate_jarvis_state(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "JARVIS_BREAKER_HISTORY_PATH",
        str(tmp_path / "breaker_history.jsonl"),
    )
    monkeypatch.setenv(
        "JARVIS_ACTIVE_SUPERVISORS_PATH",
        str(tmp_path / "active_supervisors.jsonl"),
    )
    monkeypatch.setenv(
        "JARVIS_INTERACTIVE_STATE_PATH",
        str(tmp_path / "interactive_state.json"),
    )
    monkeypatch.setenv(
        "JARVIS_QUOTA_STATE_PATH",
        str(tmp_path / "quota_state.json"),
    )
    # F006a: caps file path isolation matches the four above. Plus reset the
    # circuit_breakers _warned_once dedup cache so warning assertions don't
    # become order-dependent across tests.
    monkeypatch.setenv(
        "JARVIS_QUOTA_CAPS_PATH",
        str(tmp_path / "quota_caps.json"),
    )
    # Plan 2026-05-09-001 F001 — redirect both home-dir env vars
    # consulted by global_config.dontpanic_home() so operator
    # ~/.dontpanic/global_config.json and ~/.jarvis/config.json cannot
    # leak roles.goal_auditor into resolver-driven tests. Each path
    # points at an empty per-test directory; tests that need a specific
    # operator config shape can write into the redirected dirs on
    # demand.
    monkeypatch.setenv("DONTPANIC_HOME", str(tmp_path / "dontpanic_home"))
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "jarvis_home"))
    # Relocate the dashboard state-output dir off the repo working tree. Without
    # this a test that runs dashboard.build() writes to `<cwd>/dashboard/state`
    # (the repo), leaving pytest-tmp-home state in the served dashboard. Honored
    # by dashboard.default_dashboard_dir().
    monkeypatch.setenv("DONTPANIC_DASHBOARD_DIR", str(tmp_path / "dashboard"))
    from dontpanic_orchestrate import circuit_breakers

    circuit_breakers.reset_warning_cache()
    yield
    circuit_breakers.reset_warning_cache()
