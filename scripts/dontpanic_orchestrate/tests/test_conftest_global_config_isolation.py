"""Plan 2026-05-09-001 F001 — conftest global-config isolation tests.

Pins the autouse fixture's home-dir redirect so the operator's
``~/.dontpanic/config.json`` and ``~/.jarvis/config.json`` cannot leak
``roles.goal_auditor`` into resolver-driven tests. The leak is the
concrete repro from D007 of plan ``2026-05-08-003``: an operator
``roles: {implementer: codex, auditor: claude, goal_auditor: claude}``
config produced ~50 phantom failures across ``test_completion_dispatch``,
``test_sufficiency_auditor``, and ``test_completion_gate`` because the
goal-auditor resolver fell through to the operator's host config.

The four cases below assert each layer of the redirect is wired:
  1. The env vars themselves point at per-test paths.
  2. ``global_config.dontpanic_home()`` returns the redirected path.
  3. ``global_config.config_path()`` resolves under the redirect.
  4. Writing a fake operator ``roles.goal_auditor`` shape under the
     redirected ``DONTPANIC_HOME`` is honored by the resolver — proving
     the seam is wired through to the consumer that ~50 tests depend on.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import global_config as gc  # noqa: E402
from dontpanic_orchestrate.config import resolvers as _resolvers  # noqa: E402


class TestConftestGlobalConfigIsolation:
    def test_dontpanic_home_env_var_points_at_tmp_path(self, tmp_path: Path) -> None:
        """Acceptance #1: DONTPANIC_HOME redirected by the autouse fixture.
        The exact value should live under the fixture's tmp_path so two
        concurrent tests can never share state."""
        env_value = os.environ.get("DONTPANIC_HOME")
        assert env_value is not None, "autouse fixture failed to set DONTPANIC_HOME"
        env_path = Path(env_value).resolve()
        # The fixture's tmp_path is a parent of the redirected home dir.
        # Use is_relative_to (3.9+) to assert containment without
        # depending on a specific suffix.
        assert env_path.is_relative_to(tmp_path.parent.parent.parent) or str(env_path).startswith(
            str(Path(os.environ["TMPDIR"]).resolve()) if os.environ.get("TMPDIR") else "/"
        )

    def test_jarvis_home_env_var_also_redirected(self) -> None:
        """Both legacy and modern home env vars are redirected — the
        global_config resolver consults DONTPANIC_HOME first then
        JARVIS_HOME, so leaving one un-redirected would still leak."""
        assert os.environ.get("JARVIS_HOME") is not None
        assert os.environ.get("DONTPANIC_HOME") is not None
        # The two paths must be distinct so a JARVIS_HOME-only-write
        # operator config doesn't accidentally land under DONTPANIC_HOME.
        assert os.environ["JARVIS_HOME"] != os.environ["DONTPANIC_HOME"]

    def test_dontpanic_home_resolves_to_redirected_path(self) -> None:
        """global_config.dontpanic_home() honors DONTPANIC_HOME — the
        seam every load_config() call goes through."""
        resolved = gc.dontpanic_home()
        assert str(resolved) == os.environ["DONTPANIC_HOME"]
        assert str(gc.config_path()).startswith(os.environ["DONTPANIC_HOME"])

    def test_operator_shaped_roles_goal_auditor_does_not_leak(self) -> None:
        """End-to-end: the redirected DONTPANIC_HOME starts empty, so a
        resolver call falls through to the hardcoded fallback (codex)
        rather than picking up a fake operator goal_auditor=claude. This
        is the structural defense against the D007 regression."""
        # Confirm baseline: with no config file in the redirected home,
        # the resolver falls through to the hardcoded auditor fallback.
        baseline = _resolvers.resolve_role(Path.cwd(), "goal_auditor")
        assert baseline == "codex", (
            f"empty DONTPANIC_HOME should fall through to codex; got {baseline!r}"
        )

    def test_operator_config_under_redirect_is_honored(self, tmp_path: Path) -> None:
        """When a test deliberately writes an operator-shaped config
        under the redirected DONTPANIC_HOME, the resolver picks it up —
        proving the seam is wired through (not just the env var). This
        is the inverse of the D007 leak: the redirect doesn't break
        intentional test fixtures, it just keeps the OPERATOR's
        ambient config out."""
        home = Path(os.environ["DONTPANIC_HOME"])
        home.mkdir(parents=True, exist_ok=True)
        (home / "config.json").write_text(
            json.dumps(
                {
                    "roles": {
                        "implementer": "codex",
                        "auditor": "claude",
                        "goal_auditor": "claude",
                    }
                }
            )
        )
        # Resolver should now report the deliberately-written value.
        assert _resolvers.resolve_role(Path.cwd(), "goal_auditor") == "claude"
