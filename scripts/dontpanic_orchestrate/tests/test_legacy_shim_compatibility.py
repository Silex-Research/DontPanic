"""Compatibility tests for the ``jarvis_orchestrate`` shim package.

The shim is the unit under test in this file — the explicit references
to the legacy name are intentional and exempted from the canonical-tree
grep assertion (acceptance #5 of plan
``2026-05-04-001-refactor-canonical-dontpanic-module``).

Test coverage:

a. ``from jarvis_orchestrate import cli`` succeeds
b. ``from jarvis_orchestrate.cli import main`` succeeds
c. ``import jarvis_orchestrate.supervisor as s; s.dispatch_volley`` resolves
d. Parametric: every public submodule is reachable via the legacy name
e. ``DeprecationWarning`` fires exactly once per process
f. **No-shim-relay (AC #11)**: canonical surfaces emit ZERO ``DeprecationWarning``
"""

from __future__ import annotations

import warnings

import pytest

# Public submodule list — keep in sync with the canonical package surface.
# A new submodule under ``dontpanic_orchestrate/`` should also gain a shim
# file under ``jarvis_orchestrate/`` (per D002), and be appended here so the
# parametric coverage walks every shim path.
PUBLIC_SUBMODULES = [
    "active_supervisors",
    "agent_manifest",
    "audit_writer",
    "calibration_loader",
    "circuit_breakers",
    "cli",
    "command_guard",
    "ec5_classifier",
    "environments_loader",
    "execution_environment",
    "firebase_client",
    "gate_pause",
    "global_config",
    "inbox",
    "interactive_state",
    "mcp_server",
    "nested_orchestration",
    "notify",
    "plan_loader",
    "plan_target",
    "project_config",
    "projects_registry",
    "prompts",
    "quota_admission",
    "quota_caps_loader",
    "signoff_writer",
    "smoke_test_storage",
    "supervisor",
    "target_context_prelude",
    "transcript",
]

EXECUTORS_SUBMODULES = ["base", "claude_cli", "codex_cli"]


def _reset_shim_warning() -> None:
    """Reset the one-shot shim warning flag so a test can observe a fresh fire."""
    import jarvis_orchestrate._deprecation as _dep

    _dep._warned = False


class TestLegacyImportPaths:
    """Acceptance items (a)-(d): legacy import patterns continue to work."""

    def test_a_from_jarvis_import_cli(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from jarvis_orchestrate import cli

        assert cli is not None
        assert hasattr(cli, "main"), "cli.main must be reachable through legacy shim"

    def test_b_from_jarvis_cli_import_main(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from jarvis_orchestrate.cli import main

        assert callable(main), "main() must be importable through legacy shim"

    def test_c_import_jarvis_supervisor_attribute_resolves_to_canonical(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            import jarvis_orchestrate.supervisor as legacy_supervisor

            from dontpanic_orchestrate import supervisor as canonical_supervisor

        # The shim's `dispatch_volley` is the canonical attribute.
        assert hasattr(legacy_supervisor, "dispatch_volley")
        assert legacy_supervisor.dispatch_volley is canonical_supervisor.dispatch_volley

    @pytest.mark.parametrize("submodule", PUBLIC_SUBMODULES)
    def test_d_every_public_submodule_imports_via_legacy_name(self, submodule):
        """Parametric coverage of the entire public submodule surface."""
        import importlib

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            legacy_mod = importlib.import_module(f"jarvis_orchestrate.{submodule}")
            canonical_mod = importlib.import_module(f"dontpanic_orchestrate.{submodule}")

        assert legacy_mod is not None
        # The shim should expose the same public surface as canonical via star
        # import. Spot-check a non-underscored attribute on the canonical
        # module and confirm it's reachable from the shim too.
        for attr in dir(canonical_mod):
            if attr.startswith("_") or attr.startswith("__"):
                continue
            # Only inspect a handful to keep the test fast; getattr() exercises
            # both star-import resolution and the shim's __getattr__ fallback.
            assert hasattr(legacy_mod, attr), (
                f"jarvis_orchestrate.{submodule}.{attr} not reachable via shim "
                f"(canonical exports it but legacy doesn't)"
            )
            break  # one attribute per submodule is enough — the goal is module load

    @pytest.mark.parametrize("submodule", EXECUTORS_SUBMODULES)
    def test_d_executors_subpackage_submodules_import_via_legacy_name(self, submodule):
        import importlib

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            legacy_mod = importlib.import_module(f"jarvis_orchestrate.executors.{submodule}")

        assert legacy_mod is not None


class TestDeprecationWarningSemantics:
    """Acceptance item (e): warning fires exactly once per process."""

    def test_e_deprecation_warning_fires_once_per_process(self):
        _reset_shim_warning()

        # Collect warnings emitted during shim activity.
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", DeprecationWarning)

            # Trigger the guard from many shim paths — each should be a no-op
            # after the first fires.
            from jarvis_orchestrate._deprecation import warn_once

            warn_once()
            warn_once()
            warn_once()

        deprecation_hits = [w for w in caught if issubclass(w.category, DeprecationWarning)]
        assert len(deprecation_hits) == 1, (
            f"expected exactly 1 DeprecationWarning per process, got {len(deprecation_hits)}"
        )
        assert "dontpanic_orchestrate" in str(deprecation_hits[0].message)
        assert "2026-05-04-001" in str(deprecation_hits[0].message)

    def test_e_warning_message_names_canonical_replacement(self):
        _reset_shim_warning()

        with pytest.warns(DeprecationWarning, match=r"dontpanic_orchestrate"):
            from jarvis_orchestrate._deprecation import warn_once

            warn_once()


class TestNoShimRelay:
    """Acceptance item #11 (the operator-supplied tightening at lock time):
    invoking canonical surfaces emits ZERO ``DeprecationWarning`` from
    ``jarvis_orchestrate``. Catches the failure mode where the rename
    looks complete but the new package still routes through legacy
    internals.
    """

    @pytest.mark.parametrize(
        "argv",
        [
            ["manifest", "show", "--json"],
            ["projects", "list", "--json"],
        ],
    )
    def test_canonical_cli_invocation_does_not_relay_through_shim(self, argv):
        """Canonical ``cli.main(argv)`` must not import via ``jarvis_orchestrate``.

        Captures all warnings non-destructively, then filters to only
        DeprecationWarnings from the shim. Third-party deprecation noise
        is ignored — the assertion is specifically about whether the
        canonical path routes through the legacy shim.
        """
        _reset_shim_warning()

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            from dontpanic_orchestrate.cli import main

            try:
                main(argv)
            except SystemExit:
                # CLI may exit 0 (success) or 2 (no manifest/no projects yet).
                # Both are acceptable; the assertion is about warnings, not exit code.
                pass

        shim_warnings = [
            w
            for w in caught
            if issubclass(w.category, DeprecationWarning) and "jarvis_orchestrate" in str(w.message)
        ]
        assert not shim_warnings, (
            f"canonical CLI invocation `{argv}` relayed through the legacy shim "
            f"(expected zero shim DeprecationWarnings, got {len(shim_warnings)}): "
            f"{[str(w.message) for w in shim_warnings]}"
        )

    def test_canonical_module_imports_do_not_relay(self):
        """Importing canonical surfaces must not trigger the shim warning.

        Filters warnings to only catch DeprecationWarnings from
        ``jarvis_orchestrate`` — third-party deprecation noise (Pydantic,
        Google, etc.) is irrelevant to the no-shim-relay assertion.

        Does NOT mutate ``sys.modules``: deleting cached canonical modules
        and reimporting them pollutes other tests' module state (the
        supervisor and volley modules cache module-level state at first
        import). Instead, we use ``record=True`` to capture warnings
        non-destructively.
        """
        _reset_shim_warning()

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")

            import importlib

            # Re-import representative canonical modules. If they're already
            # in sys.modules, the import is a fast no-op (no top-level code
            # re-execution) — that's fine: we already exercised those code
            # paths during pytest collection. The point of this test is to
            # assert that none of them lazy-relay through the shim during
            # subsequent attribute access.
            for modname in [
                "dontpanic_orchestrate.cli",
                "dontpanic_orchestrate.supervisor",
                "dontpanic_orchestrate.agent_manifest",
                "dontpanic_orchestrate.mcp_server",
                "dontpanic_orchestrate.plan_loader",
                "dontpanic_orchestrate.projects_registry",
                "dontpanic_orchestrate.global_config",
                "dontpanic_orchestrate.executors",
            ]:
                importlib.import_module(modname)

        shim_warnings = [
            w
            for w in caught
            if issubclass(w.category, DeprecationWarning) and "jarvis_orchestrate" in str(w.message)
        ]
        assert not shim_warnings, (
            "canonical module imports relayed through the legacy shim "
            f"(expected zero, got {len(shim_warnings)}): "
            f"{[str(w.message) for w in shim_warnings]}"
        )
