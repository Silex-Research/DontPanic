"""Plan 2026-05-03-001 F003 — per-project config + override precedence + doctor.

Covers the deterministic acceptance contract:
  AC1 — per-project ``.jarvis/jarvis.json`` validates + loads; missing OK,
        invalid degrades to None + WARN.
  AC2 — override precedence: per-project > global > hardcoded; tested as a
        parametric matrix over all four (per-project set/unset × global set/
        unset) cells, plus an 'all-None' cell that hits the hardcoded fallback.
  AC3 — ``jarvis doctor --include-projects --strict-codes`` runs global +
        per-registered-project preflight; non-zero exit on any FAIL.
  AC4 — ``jarvis projects add --init-config`` scaffolds the per-project
        config; default behavior leaves the project free of scaffolding.
  AC5 — bare ``scripts/jarvis_doctor.py`` invocation backwards-compatible
        (no per-project rows, legacy 0/1 exit code matrix).
  AC6 — plan_loader respects per-project ``plans_dir`` when set.

Audit-focus addendum coverage (Operator memo):
  (1) missed call sites: dispatch_single_agent now consults the resolver too.
  (2) wrong precedence: parametric matrix.
  (3) unsafe fallback to cwd: registry-only resolution; tested.
  (4) name vs path confusion: resolve_project_path covers both shapes.
  (5) None vs missing config values: pinned to the "no override" semantic.
  (6) edge cases: invalid JSON, extra fields, conflicting layers, all-None.
  (7) approve/resume parity isn't a separate code-path here — those CLI
      surfaces don't pick agents (they just clear gates). The dispatch_volley
      and dispatch_single_agent paths are the only agent-pickers and both
      are covered. Explicitly noted in test docstrings to make the
      no-coverage-needed decision auditable.
  (8) doctor exit-code matrix: parametric.

All tests redirect ``$JARVIS_HOME`` to ``tmp_path`` so the user's real
``~/.jarvis/`` is never touched.

Run: PYTHONPATH=scripts pytest scripts/jarvis_orchestrate/tests/test_f003_project_config.py
"""

from __future__ import annotations

import importlib.util
import json
import logging
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from jarvis_orchestrate import cli  # noqa: E402
from jarvis_orchestrate import global_config as gc  # noqa: E402
from jarvis_orchestrate import project_config as pc  # noqa: E402
from jarvis_orchestrate import projects_registry as pr  # noqa: E402

REPO_ROOT = HERE.parents[3]
DOCTOR_PATH = REPO_ROOT / "scripts" / "jarvis_doctor.py"


@pytest.fixture(autouse=True)
def _isolate_jarvis_home(tmp_path, monkeypatch):
    """Reroute ``$JARVIS_HOME`` to a tmp dir so the user's real
    ``~/.jarvis/{config,projects}.json`` is never touched. Autouse to
    protect every test in this module."""
    monkeypatch.setenv(gc.JARVIS_HOME_ENV, str(tmp_path / ".jarvis"))


@pytest.fixture
def project_dir(tmp_path):
    """A real directory we can register as a project path."""
    d = tmp_path / "some-project"
    d.mkdir()
    return d


@pytest.fixture
def doctor():
    """Load jarvis_doctor.py as a module without going through PYTHONPATH —
    matches the F022 test pattern."""
    spec = importlib.util.spec_from_file_location("jarvis_doctor", DOCTOR_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["jarvis_doctor"] = mod
    spec.loader.exec_module(mod)
    return mod


# ───────────────────  AC1: per-project config load + schema  ───────────────────


class TestProjectConfigLoad:
    def test_missing_file_returns_none(self, project_dir):
        # The valid zero state: no jarvis.json at all → None, no warn.
        assert pc.load_project_config(project_dir) is None

    def test_empty_object_loads_with_defaults(self, project_dir):
        cfg_path = pc.project_config_path(project_dir)
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        cfg_path.write_text("{}\n")
        cfg = pc.load_project_config(project_dir)
        assert cfg is not None
        assert cfg.implementer is None
        assert cfg.auditor is None
        # plans_dir + default_target_env have non-None defaults baked in.
        assert cfg.plans_dir == pc.DEFAULT_PLANS_DIR
        assert cfg.default_target_env == pc.DEFAULT_TARGET_ENV

    def test_full_config_loads(self, project_dir):
        cfg_path = pc.project_config_path(project_dir)
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        cfg_path.write_text(
            json.dumps(
                {
                    "implementer": "codex",
                    "auditor": "claude",
                    "plans_dir": "plans",
                    "default_target_env": "staging",
                    "human_gates": ["pre_impl", "pre_merge"],
                    "protected_paths": ["secrets/", "config/"],
                }
            )
        )
        cfg = pc.load_project_config(project_dir)
        assert cfg is not None
        assert cfg.implementer == "codex"
        assert cfg.auditor == "claude"
        assert cfg.plans_dir == "plans"
        assert cfg.default_target_env == "staging"
        assert cfg.human_gates == ["pre_impl", "pre_merge"]
        assert cfg.protected_paths == ["secrets/", "config/"]

    def test_invalid_json_warns_returns_none(self, project_dir, caplog):
        # AC1: invalid JSON degrades to None + WARN. The supervisor never
        # raises during dispatch because of a malformed per-project file.
        cfg_path = pc.project_config_path(project_dir)
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        cfg_path.write_text("not json {{{")
        with caplog.at_level(logging.WARNING, logger="jarvis_orchestrate.project_config"):
            cfg = pc.load_project_config(project_dir)
        assert cfg is None
        assert any("invalid JSON" in m or "unreadable" in m for m in caplog.messages)

    def test_extra_field_warns_returns_none(self, project_dir, caplog):
        # AC1: pydantic extra='forbid' on the schema → unknown fields fail
        # validation → degrade to None so dispatch doesn't break.
        cfg_path = pc.project_config_path(project_dir)
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        cfg_path.write_text(json.dumps({"rogue_field": "x"}))
        with caplog.at_level(logging.WARNING, logger="jarvis_orchestrate.project_config"):
            cfg = pc.load_project_config(project_dir)
        assert cfg is None
        assert any("schema validation" in m for m in caplog.messages)

    def test_unknown_human_gate_warns_returns_none(self, project_dir, caplog):
        # AC1 cross-validation: a name that isn't a HumanGate enum value
        # fails the field validator → degrade to None.
        cfg_path = pc.project_config_path(project_dir)
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        cfg_path.write_text(json.dumps({"human_gates": ["pre_impl", "made_up_gate"]}))
        with caplog.at_level(logging.WARNING, logger="jarvis_orchestrate.project_config"):
            cfg = pc.load_project_config(project_dir)
        assert cfg is None
        assert any("schema validation" in m for m in caplog.messages)

    def test_explicit_null_implementer_treated_as_no_override(self, project_dir):
        # Audit-focus addendum (5): pin the resolver semantic — JSON null
        # and field-absent both mean "no override at this layer". A test
        # for both side-by-side prevents future drift.
        cfg_path = pc.project_config_path(project_dir)
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        cfg_path.write_text(json.dumps({"implementer": None, "auditor": None}))
        cfg = pc.load_project_config(project_dir)
        assert cfg is not None
        assert cfg.implementer is None
        assert cfg.auditor is None
        # And the resolver must treat both None and missing the same way.
        defaults = pc.resolve_dispatch_defaults(project_dir)
        assert defaults["implementer"] == pc.FALLBACK_IMPLEMENTER
        assert defaults["auditor"] == pc.FALLBACK_AUDITOR


# ─────────────────────  AC4: scaffold_empty_config behavior  ────────────────────


class TestScaffold:
    def test_scaffold_creates_dir_and_empty_file(self, project_dir):
        path = pc.scaffold_empty_config(project_dir)
        assert path == pc.project_config_path(project_dir)
        assert path.is_file()
        assert path.read_text().strip() == "{}"
        # Loadable round-trip.
        cfg = pc.load_project_config(project_dir)
        assert cfg is not None

    def test_scaffold_refuses_to_overwrite(self, project_dir):
        cfg_path = pc.project_config_path(project_dir)
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        cfg_path.write_text(json.dumps({"implementer": "codex"}))
        with pytest.raises(FileExistsError):
            pc.scaffold_empty_config(project_dir)
        # Pre-existing content is preserved.
        assert json.loads(cfg_path.read_text())["implementer"] == "codex"

    def test_projects_add_init_config_scaffolds(self, project_dir, capsys):
        # AC4 via the CLI surface: --init-config flag creates the file.
        rc = cli.main(["projects", "add", "alpha", str(project_dir), "--init-config"])
        assert rc == 0
        assert pc.project_config_path(project_dir).is_file()

    def test_projects_add_default_does_not_scaffold(self, project_dir):
        # Default behavior: no scaffold. Operators opt in explicitly.
        rc = cli.main(["projects", "add", "alpha", str(project_dir)])
        assert rc == 0
        assert not pc.project_config_path(project_dir).is_file()

    def test_projects_add_init_config_skipped_when_existing(self, project_dir, capsys):
        # Pre-existing per-project config: --init-config no-ops + reports
        # 'skipped'. The add itself still succeeds.
        cfg_path = pc.project_config_path(project_dir)
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        cfg_path.write_text(json.dumps({"implementer": "codex"}))
        rc = cli.main(["projects", "add", "alpha", str(project_dir), "--init-config"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "left untouched" in out or "already exists" in out.lower()
        # Pre-existing content preserved.
        assert json.loads(cfg_path.read_text())["implementer"] == "codex"


# ──────────────────  AC2: precedence matrix (per-project > global > fallback)  ──────────────────


def _write_global_config(implementer=None, auditor=None):
    """Helper: stamp ``$JARVIS_HOME/config.json`` for a precedence test."""
    home = gc.ensure_jarvis_home()
    payload: dict[str, str] = {}
    if implementer is not None:
        payload["default_implementer"] = implementer
    if auditor is not None:
        payload["default_auditor"] = auditor
    (home / "config.json").write_text(json.dumps(payload))


def _write_project_config(project_dir, implementer=None, auditor=None):
    """Helper: stamp ``<project>/.jarvis/jarvis.json`` for a precedence test."""
    cfg_path = pc.project_config_path(project_dir)
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, str] = {}
    if implementer is not None:
        payload["implementer"] = implementer
    if auditor is not None:
        payload["auditor"] = auditor
    cfg_path.write_text(json.dumps(payload))


class TestPrecedenceMatrix:
    """Audit-focus addendum (2): the four-cell parametric matrix.

    Each cell exercises (per-project set/unset × global set/unset). The
    fifth case (all-None across both layers) is included so the hardcoded
    fallback is also validated explicitly.
    """

    def test_per_project_unset_global_unset(self, project_dir):
        # No layers set → hardcoded fallback wins.
        defaults = pc.resolve_dispatch_defaults(project_dir)
        assert defaults["implementer"] == pc.FALLBACK_IMPLEMENTER
        assert defaults["auditor"] == pc.FALLBACK_AUDITOR

    def test_per_project_unset_global_set(self, project_dir):
        # Only global set → global wins.
        _write_global_config(implementer="codex", auditor="claude")
        defaults = pc.resolve_dispatch_defaults(project_dir)
        assert defaults["implementer"] == "codex"
        assert defaults["auditor"] == "claude"

    def test_per_project_set_global_unset(self, project_dir):
        # Only per-project set → per-project wins.
        _write_project_config(project_dir, implementer="codex", auditor="claude")
        defaults = pc.resolve_dispatch_defaults(project_dir)
        assert defaults["implementer"] == "codex"
        assert defaults["auditor"] == "claude"

    def test_per_project_set_global_set_per_project_wins(self, project_dir):
        # The keystone D004 case: BOTH layers set, with conflicting values.
        # Per-project must win or else operators silently get the wrong
        # agent. This is the parametric anchor preventing the silent-drift
        # bug class called out in the audit-focus addendum.
        _write_global_config(implementer="claude", auditor="codex")
        _write_project_config(project_dir, implementer="codex", auditor="claude")
        defaults = pc.resolve_dispatch_defaults(project_dir)
        assert defaults["implementer"] == "codex"
        assert defaults["auditor"] == "claude"

    def test_per_project_partial_falls_through_per_field(self, project_dir):
        # Per-project sets only implementer; auditor falls through to
        # global. Pins the field-by-field independence (vs all-or-nothing).
        _write_global_config(implementer="claude", auditor="codex")
        _write_project_config(project_dir, implementer="codex")  # no auditor
        defaults = pc.resolve_dispatch_defaults(project_dir)
        assert defaults["implementer"] == "codex"  # per-project
        assert defaults["auditor"] == "codex"  # global

    def test_invalid_per_project_falls_through_to_global(self, project_dir, caplog):
        # Per-project file unparseable → degrades to None → global wins.
        # Exact behavior in audit-focus addendum (6).
        _write_global_config(implementer="codex", auditor="claude")
        cfg_path = pc.project_config_path(project_dir)
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        cfg_path.write_text("{ broken json")
        with caplog.at_level(logging.WARNING, logger="jarvis_orchestrate.project_config"):
            defaults = pc.resolve_dispatch_defaults(project_dir)
        assert defaults["implementer"] == "codex"  # global
        assert defaults["auditor"] == "claude"  # global

    def test_no_project_path_walks_only_global_and_fallback(self):
        # Host-local plans (no registered project) must still walk the
        # remaining layers — global + fallback.
        _write_global_config(implementer="codex")
        defaults = pc.resolve_dispatch_defaults(None)
        assert defaults["implementer"] == "codex"
        assert defaults["auditor"] == pc.FALLBACK_AUDITOR  # fallback


# ──────────────────  audit-focus (4): name vs path resolution  ──────────────────


class TestResolveProjectPath:
    def test_registered_name_wins(self, project_dir):
        pr.add_project(name="alpha", path=str(project_dir))
        result = pc.resolve_project_path("alpha")
        assert result is not None
        path, name = result
        assert path == project_dir.resolve()
        assert name == "alpha"

    def test_absolute_path_resolves(self, project_dir):
        # No registry entry — absolute path with separator works.
        result = pc.resolve_project_path(str(project_dir))
        assert result is not None
        path, name = result
        assert path == project_dir.resolve()
        assert name is None  # not registered

    def test_unknown_bare_name_refuses(self):
        # Audit-focus addendum (3): the resolver must NOT default to cwd
        # for an unknown bare name. None means the CLI hard-refuses.
        assert pc.resolve_project_path("ghost") is None

    def test_registered_name_wins_over_coincident_directory(
        self, project_dir, monkeypatch, tmp_path
    ):
        # Audit-focus addendum (4): the name regex matches a string that
        # could ALSO be a relative directory under cwd. Registry must win.
        coincident = tmp_path / "alpha"
        coincident.mkdir()
        pr.add_project(name="alpha", path=str(project_dir))
        monkeypatch.chdir(tmp_path)  # cwd contains a dir named 'alpha'
        result = pc.resolve_project_path("alpha")
        assert result is not None
        path, name = result
        # Registered project path wins, NOT the cwd-relative directory.
        assert path == project_dir.resolve()
        assert name == "alpha"


# ──────────────────  AC6 + audit-focus (1): plans_dir wiring  ──────────────────


class TestPlansDirWiring:
    def test_resolve_plan_dir_honors_per_project_plans_dir(self, project_dir, monkeypatch, capsys):
        # AC6: when a project sets plans_dir, plan resolution under that
        # project must use the override, not the hardcoded 'docs/plans'.
        custom_plans = project_dir / "my-plans"
        custom_plans.mkdir()
        plan_dir = custom_plans / "2026-05-03-001-test-plan"
        plan_dir.mkdir()
        _write_project_config(project_dir, implementer=None)
        # Add plans_dir override after _write_project_config helper.
        cfg_path = pc.project_config_path(project_dir)
        cfg_path.write_text(json.dumps({"plans_dir": "my-plans"}))
        pr.add_project(name="alpha", path=str(project_dir))
        # Bare plan-id must resolve via the registered project's plans_dir.
        # Run from an unrelated cwd to prove the registry wins.
        monkeypatch.chdir(project_dir.parent)
        resolved = cli._resolve_plan_dir("2026-05-03-001-test-plan")
        assert resolved == plan_dir.resolve()

    def test_resolve_plan_dir_refuses_unknown(self, monkeypatch, tmp_path):
        # Audit-focus addendum (3): unknown plan id with no registered
        # project context AND no docs/plans/<id> in cwd → SystemExit.
        unrelated = tmp_path / "nowhere"
        unrelated.mkdir()
        monkeypatch.chdir(unrelated)
        with pytest.raises(SystemExit):
            cli._resolve_plan_dir("ghost-plan-id")

    def test_resolve_plan_dir_falls_back_to_cwd_docs_plans(self, monkeypatch, tmp_path):
        # The legacy fallback for un-registered repos must still work
        # for the historical bare-jarvis usage.
        plan_dir = tmp_path / "docs" / "plans" / "legacy-plan"
        plan_dir.mkdir(parents=True)
        monkeypatch.chdir(tmp_path)
        resolved = cli._resolve_plan_dir("legacy-plan")
        assert resolved == plan_dir.resolve()


# ──────────────────  AC3 + AC5 + AC8: doctor preflight  ──────────────────


class TestDoctorPerProject:
    def test_legacy_invocation_skips_per_project(self, doctor):
        # AC5: bare scripts/jarvis_doctor.py keeps the legacy contract —
        # no per-project rows when --include-projects is omitted.
        names = {r.name for r in doctor.run_all_checks(skip_auth=True)}
        assert not any(n.startswith("project:") for n in names)
        assert "global-config" not in names
        assert "projects-registry" not in names

    def test_include_projects_adds_global_config_check(self, doctor):
        names = {r.name for r in doctor.run_all_checks(skip_auth=True, include_projects=True)}
        assert "global-config" in names
        assert "projects-registry" in names

    def test_empty_registry_pass_with_zero_state_message(self, doctor):
        # AC3 zero state: empty registry is PASS, not a false failure.
        results = doctor.run_all_checks(skip_auth=True, include_projects=True)
        registry_check = next(r for r in results if r.name == "projects-registry")
        assert registry_check.ok and not registry_check.warn
        assert "no projects registered" in registry_check.message

    def test_registered_project_no_jarvis_json_passes(self, doctor, project_dir):
        # AC3: registered project with no per-project config → no FAILs.
        # The plans-dir check WARNs (docs/plans not authored yet) — that's
        # the documented soft signal, NOT a failure. We assert here that no
        # check returned ok=False.
        pr.add_project(name="alpha", path=str(project_dir))
        # Author the default plans dir so even the WARN doesn't fire — the
        # zero-state for an actively-used project.
        (project_dir / "docs" / "plans").mkdir(parents=True)
        results = doctor.run_all_checks(skip_auth=True, include_projects=True)
        proj_results = [r for r in results if r.name.startswith("project:alpha:")]
        assert proj_results
        assert all(r.ok for r in proj_results), [
            (r.name, r.message) for r in proj_results if not r.ok
        ]
        # And specifically: when docs/plans exists, no warnings either.
        assert all(not r.warn for r in proj_results), [
            (r.name, r.message) for r in proj_results if r.warn
        ]

    def test_registered_project_invalid_json_fails(self, doctor, project_dir):
        # AC3: invalid JSON must be a FAIL with line/field detail surfaced.
        pr.add_project(name="alpha", path=str(project_dir))
        cfg_path = pc.project_config_path(project_dir)
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        cfg_path.write_text("{ this is not json")
        results = doctor.run_all_checks(skip_auth=True, include_projects=True)
        config_check = next((r for r in results if r.name == "project:alpha:config"), None)
        assert config_check is not None
        assert not config_check.ok, config_check.message
        # The "line N col M" detail must be in the message so the
        # operator can find it without re-running.
        assert "line" in config_check.message.lower()

    def test_registered_project_missing_path_fails(self, doctor, tmp_path):
        # The registry entry points at a path that no longer exists. Doctor
        # must FAIL with the broken path so the operator can rebind.
        # Bypass add_project's path-exists validator — it would refuse.
        ghost_dir = tmp_path / "exists-temporarily"
        ghost_dir.mkdir()
        pr.add_project(name="alpha", path=str(ghost_dir))
        ghost_dir.rmdir()  # now the registered path is broken
        results = doctor.run_all_checks(skip_auth=True, include_projects=True)
        path_check = next((r for r in results if r.name == "project:alpha:path"), None)
        assert path_check is not None
        assert not path_check.ok
        assert str(ghost_dir) in path_check.message

    def test_registered_project_missing_plans_dir_warns(self, doctor, project_dir):
        # AC3: missing plans_dir is WARN (a fresh project may not have
        # authored any plans yet — not a hard FAIL).
        pr.add_project(name="alpha", path=str(project_dir))
        # No 'docs/plans' subdir in the project — declared via default.
        results = doctor.run_all_checks(skip_auth=True, include_projects=True)
        plans_check = next((r for r in results if r.name == "project:alpha:plans-dir"), None)
        assert plans_check is not None
        # ok=True with warn=True per the _warn() helper convention.
        assert plans_check.ok and plans_check.warn

    def test_registered_project_unknown_agent_fails(self, doctor, project_dir):
        # AC3: declared agent must be in AGENT_REGISTRY. Typos there silently
        # break dispatch otherwise — doctor must catch them.
        pr.add_project(name="alpha", path=str(project_dir))
        cfg_path = pc.project_config_path(project_dir)
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        cfg_path.write_text(json.dumps({"implementer": "made-up-agent"}))
        results = doctor.run_all_checks(skip_auth=True, include_projects=True)
        agents_check = next((r for r in results if r.name == "project:alpha:agents"), None)
        assert agents_check is not None
        assert not agents_check.ok
        assert "made-up-agent" in agents_check.message

    def test_global_config_invalid_fails(self, doctor):
        # global-config check FAILs (not warns) when ~/.jarvis/config.json
        # is broken. Operator must see it explicitly so they don't silently
        # lose their declared defaults.
        gc.ensure_jarvis_home()
        gc.config_path().write_text("{ broken")
        results = doctor.run_all_checks(skip_auth=True, include_projects=True)
        gc_check = next((r for r in results if r.name == "global-config"), None)
        assert gc_check is not None
        assert not gc_check.ok
        assert "line" in gc_check.message.lower()


class TestDoctorExitCodeMatrix:
    """Audit-focus addendum (8): the 0/1/2 strict-codes matrix is parametric.

    0 if all PASS, 1 if any WARN, 2 if any FAIL.
    """

    @pytest.mark.parametrize(
        "results,expected_code",
        [
            ([("ok1", True, False), ("ok2", True, False)], 0),
            ([("ok1", True, False), ("warn1", True, True)], 1),
            ([("ok1", True, False), ("fail1", False, False)], 2),
            ([("warn1", True, True), ("fail1", False, False)], 2),  # FAIL wins
        ],
    )
    def test_compute_strict_exit(self, doctor, results, expected_code):
        check_results = [
            doctor.CheckResult(name=name, ok=ok, message="x", warn=warn)
            for name, ok, warn in results
        ]
        assert doctor.compute_strict_exit(check_results) == expected_code

    def test_jarvis_doctor_subcommand_uses_strict_codes(self, project_dir, capsys, monkeypatch):
        # AC3: `jarvis doctor` (the new console-script subcommand) must use
        # the 0/1/2 matrix. We patch the plan/auth-dependent checks to a
        # known-WARN state so the test is deterministic.
        # Force include_projects path and assert exit 1 when ONLY warnings.
        pr.add_project(name="alpha", path=str(project_dir))
        # Stub the doctor's heavyweight checks so this test can run in any
        # environment (no gcloud, no firebase). We only care about the
        # exit-code matrix shape — see TestDoctorPerProject for the full
        # checks.
        # Inject a fake jarvis_doctor module that returns a controlled
        # results list so the strict-code wrapper is exercised end-to-end.
        import importlib.util as _util

        from jarvis_orchestrate import cli as cli_mod

        spec = _util.spec_from_file_location("jarvis_doctor", DOCTOR_PATH)
        assert spec and spec.loader
        fake = _util.module_from_spec(spec)
        sys.modules["jarvis_doctor"] = fake
        spec.loader.exec_module(fake)
        monkeypatch.setattr(
            fake,
            "run_all_checks",
            lambda **kw: [
                fake.CheckResult("ok", True, "x"),
                fake.CheckResult("warn", True, "y", warn=True),
            ],
        )
        rc = cli_mod._doctor_main(["--json"])
        assert rc == 1

    def test_jarvis_doctor_subcommand_exits_2_on_fail(self, project_dir, monkeypatch):
        import importlib.util as _util

        from jarvis_orchestrate import cli as cli_mod

        spec = _util.spec_from_file_location("jarvis_doctor", DOCTOR_PATH)
        assert spec and spec.loader
        fake = _util.module_from_spec(spec)
        sys.modules["jarvis_doctor"] = fake
        spec.loader.exec_module(fake)
        monkeypatch.setattr(
            fake,
            "run_all_checks",
            lambda **kw: [
                fake.CheckResult("fail", False, "x", remediation="y"),
            ],
        )
        rc = cli_mod._doctor_main(["--json"])
        assert rc == 2

    def test_legacy_script_keeps_0_1_contract(self, doctor, monkeypatch):
        # AC5: the bare `python3 scripts/jarvis_doctor.py` invocation still
        # uses the legacy 0/1 matrix. Without --strict-codes, a WARN-only
        # state must STILL exit 0 (legacy contract).
        monkeypatch.setattr(
            doctor,
            "run_all_checks",
            lambda **kw: [doctor.CheckResult("warn", True, "x", warn=True)],
        )
        rc = doctor.main(["--json", "--include-projects"])
        assert rc == 0  # legacy: warn does not fail

        # And --strict-codes WITH a WARN-only state exits 1.
        rc = doctor.main(["--json", "--include-projects", "--strict-codes"])
        assert rc == 1


# ──────────────────  audit-focus (1): single-agent dispatch parity  ──────────────────


class TestSingleAgentResolverParity:
    """Audit-focus addendum (1): dispatch_single_agent must consult the same
    resolver as dispatch_volley. Pre-F003 it hardcoded Claude.

    These tests don't actually dispatch (no real Claude / Codex CLI in
    test env) — they assert the resolver was wired in. The resolver
    selection happens before _resolve_executor is called, so we can
    verify by patching _resolve_executor to capture what name was
    requested.
    """

    def test_dispatch_single_agent_uses_per_project_implementer(
        self, project_dir, tmp_path, monkeypatch
    ):
        from jarvis_orchestrate import supervisor as sv

        # Build a real registered-project + plan layout. Plan schema
        # mirrors test_dispatch_from_plan's _write_plan template — minimum
        # frontmatter that satisfies plan_loader.load.
        plan_id = "2026-05-03-001-feat-x"
        plan_dir = project_dir / "docs" / "plans" / plan_id
        plan_dir.mkdir(parents=True)
        (plan_dir / "plan.md").write_text(
            f"""---
id: {plan_id}
title: x
type: feat
tier: trivial
status: active
date: "2026-05-03"
description: Synthetic plan exercising single-agent dispatch resolver wiring.
agents_required: []
loop_caps:
  max_iterations: 1
  hard_stop: false
privacy_tier: internal
links:
  features: ./features.json
---

## Target

```yaml
target_env: dev
target_project: none
```
"""
        )
        (plan_dir / "features.json").write_text(
            json.dumps(
                {
                    "task_id": plan_id,
                    "schema_version": "1.0",
                    "features": [
                        {
                            "id": "F001",
                            "category": "test",
                            "phase": 0,
                            "description": "Synthetic feature for parity test.",
                            "acceptance": "Resolver wires to per-project implementer.",
                            "steps": ["resolve agent", "dispatch"],
                            "passes": False,
                            "depends_on": [],
                        }
                    ],
                }
            )
        )
        pr.add_project(name="alpha", path=str(project_dir))
        # Per-project config picks codex as the implementer.
        cfg_path = pc.project_config_path(project_dir)
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        cfg_path.write_text(json.dumps({"implementer": "codex"}))

        captured: dict[str, str] = {}

        def fake_resolve(name: str):
            captured["name"] = name
            raise RuntimeError("stop here — we only need to confirm name was resolved")

        monkeypatch.setattr(sv, "_resolve_executor", fake_resolve)
        # Force the quota gate to a no-op so we don't depend on quota
        # state to reach the executor-resolution call site.
        monkeypatch.setattr(sv, "_quota_gate", lambda agent: (None, "[quota] noop"))
        # Also stub the admission evaluate to avoid hitting
        # external interactive_state fixtures.
        from jarvis_orchestrate import quota_admission as qa

        class _FakeAdmission:
            class _Quota:
                over_threshold = False
                observed_pct = None
                threshold = 90.0
                offending_agent = None
                cause = None

            class _Interactive:
                within_backoff = False
                minutes_remaining = 0.0

            dispatch_class = qa.DispatchClass.AUTONOMOUS
            quota = _Quota()
            interactive = _Interactive()
            active_gates: list[str] = []

        monkeypatch.setattr(qa, "evaluate", lambda *a, **kw: _FakeAdmission())

        with pytest.raises(RuntimeError, match="stop here"):
            sv.dispatch_single_agent(plan_dir, "F001", agent_role="implementer")

        assert captured["name"] == "codex"
