"""Plan 2026-05-30-001 F015 — skill auto-run ALLOWLIST artifact + approval gating.

Coverage map to acceptance (D060 split):

  AC4   read-only bounded skills become auto-run-eligible ONLY when required
        inputs exist AND the EXACT command is on the versioned auto-run
        allowlist — proven both at the predicate level (exact/prefix match vs
        absent vs prefix-mismatch) and end-to-end through the F011 evaluator.
  AC5   the allowlist carries owner/approval metadata, version/content_hash,
        rationale, and command template/prefix fields; doctor/reconcile AND the
        F008 config inventory expose missing/stale/conflicting state.
  AC7   mutating/credentialed/networked/paid/external-write/indefinite-loop
        skills are never silently auto-run — the allowlist refuses to authorize
        a risk-flagged entry and the recommender never emits auto_run for them.
  AC14b tests prove command-allowlist enforcement, doctor/reconcile allowlist
        visibility, and that approval-required skills are never invoked by the
        recommender.

Run: PYTHONPATH=scripts pytest \\
  scripts/dontpanic_orchestrate/tests/test_skill_allowlist_f015.py -q
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from dontpanic_orchestrate import skill_allowlist as sa  # noqa: E402
from dontpanic_orchestrate.skill_invocation import (  # noqa: E402
    Recommendation,
    SkillInvocationContext,
    evaluate,
    load_rubric,
)

DOCTOR_PATH = SCRIPTS / "dontpanic_doctor.py"


@pytest.fixture
def doctor():
    spec = importlib.util.spec_from_file_location("dontpanic_doctor", DOCTOR_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["dontpanic_doctor"] = mod
    spec.loader.exec_module(mod)
    return mod


# ────────────────────────────  builders  ────────────────────────────


def _entry(**overrides):
    base = dict(
        skill_name="security-review",
        command_template="dontpanic skills run security-review",
        allowed_mode="auto_readonly",
        owner="platform-team",
        approved_by="operator",
        approved_at="2026-06-02T00:00:00Z",
        rationale="Read-only static scan; bounded; writes only to evidence dir.",
    )
    base.update(overrides)
    return base


def _write_allowlist(path: Path, *entries, stamp: bool = True) -> sa.AutoRunAllowlist:
    """Build an allowlist from entry dicts, stamp its hash, write it, return it."""
    allowlist = sa.AutoRunAllowlist(entries=[sa.AllowlistEntry(**e) for e in entries])
    if stamp:
        allowlist = allowlist.stamped()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(allowlist.model_dump_json(exclude_none=True))
    return allowlist


# ────────────────────────────  AC5: schema + metadata  ────────────────────────────


def test_entry_requires_owner_approval_rationale_and_command_shape():
    e = sa.AllowlistEntry(**_entry())
    assert e.owner and e.approved_by and e.approved_at and e.rationale
    assert e.command_template == "dontpanic skills run security-review"


def test_entry_rejects_both_command_shapes():
    with pytest.raises(ValueError, match="exactly one"):
        sa.AllowlistEntry(**_entry(command_prefix="dontpanic skills run"))


def test_entry_rejects_neither_command_shape():
    with pytest.raises(ValueError, match="exactly one"):
        sa.AllowlistEntry(**_entry(command_template=None, command_prefix=None))


@pytest.mark.parametrize("mode", ["suggest", "approval_required", "never_auto", "never_suggest"])
def test_entry_rejects_non_auto_modes(mode):
    # An allowlist authorizes the auto-run path; a human-driven mode never
    # reaches it, so allowlisting one is meaningless and is refused (AC7).
    with pytest.raises(ValueError, match="auto mode"):
        sa.AllowlistEntry(**_entry(allowed_mode=mode))


def test_allowlist_carries_version_and_hash():
    al = sa.AutoRunAllowlist(version=3, entries=[sa.AllowlistEntry(**_entry())]).stamped()
    assert al.version == 3
    assert al.content_hash and al.content_hash.startswith("sha256:")
    assert al.is_hash_fresh()


# ────────────────────────────  AC5: classification states  ────────────────────────────


def test_classify_missing(tmp_path):
    state = sa.classify_allowlist(tmp_path / "absent.json")
    assert state.status is sa.AllowlistStatus.MISSING
    assert "disabled" in state.detail


def test_classify_unloadable(tmp_path):
    p = tmp_path / "skill-autorun-allowlist.json"
    p.write_text("{ not json")
    state = sa.classify_allowlist(p)
    assert state.status is sa.AllowlistStatus.UNLOADABLE


def test_classify_stale_on_hash_mismatch(tmp_path):
    p = tmp_path / "skill-autorun-allowlist.json"
    _write_allowlist(p, _entry())
    # Hand-edit the entries AFTER stamping, leaving the recorded hash behind.
    data = json.loads(p.read_text())
    data["entries"][0]["command_template"] = "dontpanic skills run something-else"
    p.write_text(json.dumps(data))
    state = sa.classify_allowlist(p)
    assert state.status is sa.AllowlistStatus.STALE


def test_classify_conflicting_same_skill_two_modes(tmp_path):
    p = tmp_path / "skill-autorun-allowlist.json"
    _write_allowlist(
        p,
        _entry(allowed_mode="auto_readonly", command_template="cmd-a"),
        _entry(allowed_mode="auto_safe", command_template="cmd-b"),
    )
    state = sa.classify_allowlist(p)
    assert state.status is sa.AllowlistStatus.CONFLICTING
    assert any("multiple modes" in c for c in state.conflicts)


def test_classify_conflicting_same_command_two_skills(tmp_path):
    p = tmp_path / "skill-autorun-allowlist.json"
    _write_allowlist(
        p,
        _entry(skill_name="a", command_template="shared-cmd"),
        _entry(skill_name="b", command_template="shared-cmd"),
    )
    state = sa.classify_allowlist(p)
    assert state.status is sa.AllowlistStatus.CONFLICTING
    assert any("multiple skills" in c for c in state.conflicts)


def test_classify_ok(tmp_path):
    p = tmp_path / "skill-autorun-allowlist.json"
    _write_allowlist(p, _entry())
    state = sa.classify_allowlist(p)
    assert state.status is sa.AllowlistStatus.OK
    assert state.entry_count == 1
    assert state.is_trusted


# ────────────────────────────  AC4/AC14b: command-allowlist enforcement  ────────────────────────────


def test_predicate_allows_exact_command(tmp_path):
    p = tmp_path / "al.json"
    _write_allowlist(p, _entry(command_template="dontpanic skills run security-review"))
    pred = sa.build_predicate(path=p)
    assert pred("dontpanic skills run security-review") is True


def test_predicate_denies_absent_command(tmp_path):
    p = tmp_path / "al.json"
    _write_allowlist(p, _entry(command_template="dontpanic skills run security-review"))
    pred = sa.build_predicate(path=p)
    assert pred("dontpanic skills run NOT-listed") is False


def test_predicate_prefix_match_and_mismatch(tmp_path):
    p = tmp_path / "al.json"
    _write_allowlist(
        p,
        _entry(skill_name="test-runner", command_template=None, command_prefix="pytest "),
    )
    pred = sa.build_predicate(path=p)
    assert pred("pytest tests/test_x.py -q") is True   # prefix match
    assert pred("pytes") is False                       # prefix mismatch (shorter)
    assert pred("python -m pytest") is False            # prefix mismatch (different head)


def test_predicate_denies_everything_when_missing(tmp_path):
    pred = sa.build_predicate(path=tmp_path / "absent.json")
    assert pred("anything") is False


def test_predicate_denies_everything_when_stale(tmp_path):
    p = tmp_path / "al.json"
    _write_allowlist(p, _entry(command_template="cmd"))
    data = json.loads(p.read_text())
    data["entries"][0]["command_template"] = "cmd-tampered"
    p.write_text(json.dumps(data))  # hash now mismatched → STALE
    pred = sa.build_predicate(path=p)
    # Even the (now-present) tampered command is denied: a stale allowlist is
    # untrusted and authorizes nothing.
    assert pred("cmd-tampered") is False
    assert pred("cmd") is False


def test_predicate_denies_everything_when_conflicting(tmp_path):
    p = tmp_path / "al.json"
    _write_allowlist(
        p,
        _entry(skill_name="a", command_template="shared"),
        _entry(skill_name="b", command_template="shared"),
    )
    pred = sa.build_predicate(path=p)
    assert pred("shared") is False


def test_predicate_denies_risk_flagged_entry(tmp_path):
    # AC7: a risk-flagged entry never clears auto-run even if hand-written into
    # the allowlist for an auto mode.
    p = tmp_path / "al.json"
    _write_allowlist(
        p,
        _entry(command_template="dangerous-cmd", risk_flags=["repo_mutation"]),
    )
    pred = sa.build_predicate(path=p)
    assert pred("dangerous-cmd") is False


# ───────────────────  AC4/AC7: end-to-end through the F011 evaluator  ───────────────────


def _evaluate_one(rubric, *, allowlist_path, **ctx_kw):
    pred = sa.build_predicate(path=allowlist_path)
    base = dict(
        skills=(rubric,),
        provided_inputs=(),
        budget_ok=True,
        is_command_allowlisted=pred,
    )
    base.update(ctx_kw)
    actions = evaluate(SkillInvocationContext(**base))
    assert len(actions) == 1
    return actions[0]


def test_readonly_skill_auto_runs_only_when_allowlisted_and_inputs_present(tmp_path):
    p = tmp_path / "al.json"
    _write_allowlist(
        p, _entry(command_template="dontpanic skills run security-review")
    )
    rubric = load_rubric(
        "security-review",
        {
            "invocation": {
                "mode": "auto_readonly",
                "required_inputs": ["changed_files"],
                "evidence_target": "evidence/security.json",
                "command_template": "dontpanic skills run security-review",
            }
        },
    )
    action = _evaluate_one(
        rubric, allowlist_path=p, provided_inputs=("changed_files",)
    )
    assert action.recommendation is Recommendation.AUTO_RUN
    assert action.exact_command == "dontpanic skills run security-review"


def test_readonly_skill_blocked_when_inputs_missing_even_if_allowlisted(tmp_path):
    # AC4: required inputs must exist AND the command must be allowlisted.
    p = tmp_path / "al.json"
    _write_allowlist(
        p, _entry(command_template="dontpanic skills run security-review")
    )
    rubric = load_rubric(
        "security-review",
        {
            "invocation": {
                "mode": "auto_readonly",
                "required_inputs": ["changed_files"],
                "evidence_target": "evidence/security.json",
                "command_template": "dontpanic skills run security-review",
            }
        },
    )
    action = _evaluate_one(rubric, allowlist_path=p)  # no inputs
    assert action.recommendation is Recommendation.BLOCKED_MISSING_INPUTS
    assert action.exact_command is None


def test_readonly_skill_downgrades_to_suggest_when_not_allowlisted(tmp_path):
    # AC4: inputs present, but the command is absent from the allowlist.
    p = tmp_path / "al.json"
    _write_allowlist(p, _entry(command_template="some-other-command"))
    rubric = load_rubric(
        "security-review",
        {
            "invocation": {
                "mode": "auto_readonly",
                "required_inputs": ["changed_files"],
                "evidence_target": "evidence/security.json",
                "command_template": "dontpanic skills run security-review",
            }
        },
    )
    action = _evaluate_one(
        rubric, allowlist_path=p, provided_inputs=("changed_files",)
    )
    assert action.recommendation is Recommendation.SUGGEST
    assert action.exact_command is None


def test_missing_allowlist_means_no_skill_auto_runs(tmp_path):
    rubric = load_rubric(
        "security-review",
        {
            "invocation": {
                "mode": "auto_readonly",
                "required_inputs": ["changed_files"],
                "evidence_target": "evidence/security.json",
                "command_template": "dontpanic skills run security-review",
            }
        },
    )
    action = _evaluate_one(
        rubric, allowlist_path=tmp_path / "absent.json", provided_inputs=("changed_files",)
    )
    assert action.recommendation is Recommendation.SUGGEST


def test_approval_required_skills_never_invoked_by_recommender(tmp_path):
    # AC7 + AC14b: even with a permissive-looking allowlist that lists every
    # command, mutating/credentialed/networked/paid/external-write/looping skills
    # and approval_required skills NEVER resolve to auto_run and never surface a
    # runnable exact_command.
    risky_blocks = {
        "github-pr": {"mode": "approval_required", "command_template": "gh pr create"},
        "deploy": {
            "mode": "auto_safe",
            "evidence_target": "evidence/deploy.json",
            "command_template": "deploy prod",
            "risk_flags": ["external_writes"],
        },
        "pay": {
            "mode": "auto_safe",
            "evidence_target": "evidence/pay.json",
            "command_template": "charge card",
            "risk_flags": ["paid"],
        },
        "loop": {
            "mode": "auto_safe",
            "evidence_target": "evidence/loop.json",
            "command_template": "watch forever",
            "risk_flags": ["indefinite_loop"],
        },
        "prod-read": {
            "mode": "auto_safe",
            "evidence_target": "evidence/read.json",
            "command_template": "read prod secrets",
            "risk_flags": ["credentialed_production_read"],
        },
        "net": {
            "mode": "auto_safe",
            "evidence_target": "evidence/net.json",
            "command_template": "curl example.com",
            "risk_flags": ["network_access"],
        },
        "mutate": {
            "mode": "auto_safe",
            "evidence_target": "evidence/mut.json",
            "command_template": "git commit -am x",
            "risk_flags": ["repo_mutation"],
        },
    }
    # An allowlist that (incorrectly, were it honored) names every command. The
    # entries themselves must be risk-free auto entries to be writable, so we
    # allowlist the command strings under innocuous skill names — proving the
    # ENGINE, not just the allowlist, refuses to auto-run the risky declarations.
    p = tmp_path / "al.json"
    _write_allowlist(
        p,
        *[
            _entry(skill_name=f"al-{i}", command_template=block["command_template"])
            for i, block in enumerate(risky_blocks.values())
        ],
    )
    for name, block in risky_blocks.items():
        rubric = load_rubric(name, {"invocation": block})
        action = _evaluate_one(rubric, allowlist_path=p)
        assert action.recommendation is not Recommendation.AUTO_RUN, name
        assert action.exact_command is None, name


# ────────────────────────────  AC5/AC14b: doctor visibility  ────────────────────────────


def test_doctor_reports_missing_allowlist_as_ok(doctor):
    res = doctor.check_skill_allowlist()
    assert res.ok is True
    assert res.name == "agent:skill-allowlist"
    assert "disabled" in res.message


def test_doctor_reports_ok_allowlist(doctor):
    _write_allowlist(sa.allowlist_path(), _entry())
    res = doctor.check_skill_allowlist()
    assert res.ok is True
    assert "approved auto-run command" in res.message


def test_doctor_warns_on_stale_allowlist(doctor):
    p = sa.allowlist_path()
    _write_allowlist(p, _entry(command_template="cmd"))
    data = json.loads(p.read_text())
    data["entries"][0]["command_template"] = "tampered"
    p.write_text(json.dumps(data))
    res = doctor.check_skill_allowlist()
    assert res.ok is True and res.warn is True   # advisory WARN, not a hard FAIL
    assert "stale" in res.message
    assert res.remediation


def test_doctor_warns_on_conflicting_allowlist(doctor):
    _write_allowlist(
        sa.allowlist_path(),
        _entry(skill_name="a", command_template="shared"),
        _entry(skill_name="b", command_template="shared"),
    )
    res = doctor.check_skill_allowlist()
    assert res.warn is True
    assert "conflicting" in res.message


def test_doctor_fails_on_unloadable_allowlist(doctor):
    sa.allowlist_path().parent.mkdir(parents=True, exist_ok=True)
    sa.allowlist_path().write_text("{ broken")
    res = doctor.check_skill_allowlist()
    assert res.ok is False


def test_agent_onboarding_includes_allowlist_check(doctor):
    results = doctor.check_agent_onboarding(skip_auth=True)
    names = {r.name for r in results}
    assert "agent:skill-allowlist" in names


# ────────────────────────────  AC5/AC14b: reconcile visibility  ────────────────────────────


def test_reconcile_filenames_includes_allowlist():
    from dontpanic_orchestrate import home_reconcile as hr

    assert sa.ALLOWLIST_FILENAME in hr.RECONCILE_FILENAMES


def test_reconcile_surfaces_legacy_only_allowlist(tmp_path):
    from dontpanic_orchestrate import home_reconcile as hr

    canonical = tmp_path / "canonical"
    legacy = tmp_path / "legacy"
    canonical.mkdir()
    legacy.mkdir()
    _write_allowlist(legacy / sa.ALLOWLIST_FILENAME, _entry())  # legacy only
    states = hr.classify_homes(canonical=canonical, legacy=legacy)
    legacy_only, divergent = hr.split_brain_summary(states)
    assert sa.ALLOWLIST_FILENAME in legacy_only


def test_reconcile_surfaces_divergent_allowlist(tmp_path):
    from dontpanic_orchestrate import home_reconcile as hr

    canonical = tmp_path / "canonical"
    legacy = tmp_path / "legacy"
    canonical.mkdir()
    legacy.mkdir()
    _write_allowlist(canonical / sa.ALLOWLIST_FILENAME, _entry(command_template="cmd-a"))
    _write_allowlist(legacy / sa.ALLOWLIST_FILENAME, _entry(command_template="cmd-b"))
    states = hr.classify_homes(canonical=canonical, legacy=legacy)
    _legacy_only, divergent = hr.split_brain_summary(states)
    assert sa.ALLOWLIST_FILENAME in divergent


# ───────  AC5/AC14b: reconcile exposes stale/conflicting allowlist VALIDITY  ───────
# Byte-comparison (classify_homes) only catches split-brain; these prove reconcile
# also surfaces a single home's STALE/CONFLICTING allowlist (codex audit F015-i0).


def test_classify_allowlist_homes_reports_ok_and_missing(tmp_path):
    from dontpanic_orchestrate import home_reconcile as hr

    canonical = tmp_path / "canonical"
    legacy = tmp_path / "legacy"
    canonical.mkdir()
    legacy.mkdir()
    _write_allowlist(canonical / sa.ALLOWLIST_FILENAME, _entry())  # canonical only
    by_home = {a.home: a for a in hr.classify_allowlist_homes(canonical=canonical, legacy=legacy)}
    assert by_home["canonical"].status == "ok"
    assert by_home["canonical"].is_trusted is True
    assert by_home["legacy"].status == "missing"
    assert by_home["legacy"].is_present is False


def test_classify_allowlist_homes_surfaces_stale(tmp_path):
    from dontpanic_orchestrate import home_reconcile as hr

    canonical = tmp_path / "canonical"
    legacy = tmp_path / "legacy"
    canonical.mkdir()
    legacy.mkdir()
    p = canonical / sa.ALLOWLIST_FILENAME
    _write_allowlist(p, _entry(command_template="cmd"))
    data = json.loads(p.read_text())
    data["entries"][0]["command_template"] = "tampered"  # hash now mismatched → STALE
    p.write_text(json.dumps(data))
    by_home = {a.home: a for a in hr.classify_allowlist_homes(canonical=canonical, legacy=legacy)}
    assert by_home["canonical"].status == "stale"
    assert by_home["canonical"].is_present is True
    assert by_home["canonical"].is_trusted is False


def test_classify_allowlist_homes_surfaces_conflicting(tmp_path):
    from dontpanic_orchestrate import home_reconcile as hr

    canonical = tmp_path / "canonical"
    legacy = tmp_path / "legacy"
    canonical.mkdir()
    legacy.mkdir()
    _write_allowlist(
        legacy / sa.ALLOWLIST_FILENAME,
        _entry(skill_name="a", command_template="shared"),
        _entry(skill_name="b", command_template="shared"),
    )
    by_home = {a.home: a for a in hr.classify_allowlist_homes(canonical=canonical, legacy=legacy)}
    assert by_home["legacy"].status == "conflicting"
    assert by_home["legacy"].conflicts  # human-readable conflict descriptions present


def _run_reconcile_homes(monkeypatch, capsys, canonical, legacy, *, fmt):
    from dontpanic_orchestrate import reconcile

    monkeypatch.setenv(hr_env_canonical(), str(canonical))
    monkeypatch.setenv(hr_env_legacy(), str(legacy))
    code = reconcile.reconcile_main(["homes", "--format", fmt])
    return code, capsys.readouterr().out


def hr_env_canonical():
    from dontpanic_orchestrate import home_reconcile as hr

    return hr.CANONICAL_HOME_ENV


def hr_env_legacy():
    from dontpanic_orchestrate import home_reconcile as hr

    return hr.LEGACY_HOME_ENV


def test_reconcile_homes_json_exposes_stale_allowlist_validity(tmp_path, monkeypatch, capsys):
    canonical = tmp_path / "canonical"
    legacy = tmp_path / "legacy"
    canonical.mkdir()
    legacy.mkdir()
    p = canonical / sa.ALLOWLIST_FILENAME
    _write_allowlist(p, _entry(command_template="cmd"))
    data = json.loads(p.read_text())
    data["entries"][0]["command_template"] = "tampered"
    p.write_text(json.dumps(data))

    code, out = _run_reconcile_homes(monkeypatch, capsys, canonical, legacy, fmt="json")
    payload = json.loads(out)
    validity = {v["home"]: v for v in payload["allowlist_validity"]}
    assert validity["canonical"]["status"] == "stale"
    # A present-but-untrusted allowlist is a non-clean terminal → exit 1.
    assert code == 1


def test_reconcile_homes_text_exposes_conflicting_allowlist(tmp_path, monkeypatch, capsys):
    canonical = tmp_path / "canonical"
    legacy = tmp_path / "legacy"
    canonical.mkdir()
    legacy.mkdir()
    _write_allowlist(
        canonical / sa.ALLOWLIST_FILENAME,
        _entry(skill_name="a", command_template="shared"),
        _entry(skill_name="b", command_template="shared"),
    )
    code, out = _run_reconcile_homes(monkeypatch, capsys, canonical, legacy, fmt="text")
    assert "conflicting" in out
    assert "[allowlist]" in out
    assert code == 1


def test_reconcile_homes_clean_when_allowlists_ok_or_absent(tmp_path, monkeypatch, capsys):
    canonical = tmp_path / "canonical"
    legacy = tmp_path / "legacy"
    canonical.mkdir()
    legacy.mkdir()
    _write_allowlist(canonical / sa.ALLOWLIST_FILENAME, _entry())  # canonical only, valid
    code, out = _run_reconcile_homes(monkeypatch, capsys, canonical, legacy, fmt="json")
    payload = json.loads(out)
    validity = {v["home"]: v for v in payload["allowlist_validity"]}
    assert validity["canonical"]["status"] == "ok"
    assert validity["legacy"]["status"] == "missing"
    # legacy_only allowlist is still split-brain (a migration), but no untrusted
    # allowlist and no divergent conflict → the allowlist itself does not force
    # exit 1. The canonical-only file is a no-op migration here.
    assert code == 0


# ────────────────────────────  AC5/AC14b: F008 inventory visibility  ────────────────────────────


def test_inventory_includes_allowlist_item():
    from dontpanic_orchestrate import config_inventory as ci

    inv = ci.collect_inventory()
    item = next((i for i in inv.items if i.id == "skill_allowlist"), None)
    assert item is not None
    assert item.title == "Skill auto-run allowlist"


def test_inventory_missing_allowlist_is_optional_not_blocking():
    from dontpanic_orchestrate import config_inventory as ci

    inv = ci.collect_inventory()
    item = next(i for i in inv.items if i.id == "skill_allowlist")
    assert item.status is ci.Status.OPTIONAL_UNCONFIGURED
    assert item.optional is True


def test_inventory_ok_allowlist_reports_ok():
    from dontpanic_orchestrate import config_inventory as ci

    _write_allowlist(sa.allowlist_path(), _entry())
    item = next(
        i for i in ci.collect_inventory().items if i.id == "skill_allowlist"
    )
    assert item.status is ci.Status.OK


def test_inventory_stale_allowlist_reports_non_ok():
    from dontpanic_orchestrate import config_inventory as ci

    p = sa.allowlist_path()
    _write_allowlist(p, _entry(command_template="cmd"))
    data = json.loads(p.read_text())
    data["entries"][0]["command_template"] = "tampered"
    p.write_text(json.dumps(data))
    item = next(
        i for i in ci.collect_inventory().items if i.id == "skill_allowlist"
    )
    assert item.status is not ci.Status.OK


def test_inventory_conflicting_allowlist_reports_non_ok():
    from dontpanic_orchestrate import config_inventory as ci

    _write_allowlist(
        sa.allowlist_path(),
        _entry(skill_name="a", command_template="shared"),
        _entry(skill_name="b", command_template="shared"),
    )
    item = next(
        i for i in ci.collect_inventory().items if i.id == "skill_allowlist"
    )
    assert item.status is not ci.Status.OK
