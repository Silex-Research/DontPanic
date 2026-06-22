"""Plan 2026-06-21-001 F003 — detection predicate registry tests.

Covers the full acceptance matrix:

* the registry resolves both status_probe and applies_when keys;
* ``canonical_discovery_registered_active`` is satisfied iff DontPanic reconciles to
  registered_active — INCLUDING when a stale/malformed evidence file is present
  (D019 dedicated test) — and false (with detail) for stale / missing / unresolved /
  read-error;
* evidence validity gates ONLY ``canonical_backfill_evidence_valid``, never the
  outcome probe;
* ``has_tracked_projects`` reflects registry presence (true / false / undeterminable);
* status_probe error -> not satisfied (fail-closed) while applies_when error ->
  applies true (fail-open);
* unknown status_probe key -> satisfied=false + error detail; unknown applies_when
  key -> applies=true + error detail; neither crashes resolution;
* NO-MUTATION (D028): running every predicate against a fixture HOME mutates nothing.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from dontpanic_orchestrate import projects_registry
from dontpanic_orchestrate import upgrade_predicates as up
from dontpanic_orchestrate.projects_registry import ProjectEntry, Registry

NOW = "2026-06-20T00:00:00Z"

#: The running instance's canonical_repo_key for tests — matches ``_active_row``'s
#: default key, so a probe injected with ``self_canonical_key=SELF_KEY`` treats that
#: row as DontPanic's OWN row.
SELF_KEY = "abc123"


# ─────────────────────────  helpers / fixtures  ─────────────────────────


def _projection(
    *,
    active: list | None = None,
    stale: list | None = None,
    path_missing: list | None = None,
    unresolved: list | None = None,
    used_unregistered: list | None = None,
) -> dict:
    return {
        "used_unregistered": used_unregistered or [],
        "registered_active": active or [],
        "registered_stale": stale or [],
        "registered_path_missing": path_missing or [],
        "registered_unresolved": unresolved or [],
    }


def _active_row(name: str = "dontpanic", key: str = SELF_KEY) -> dict:
    return {"canonical_repo_key": key, "registry_name": name, "observed_count": 5}


def _self_ctx(projection: dict, *, evidence_path=None) -> up.PredicateContext:
    """A context pinned to THIS instance's identity (``SELF_KEY``) so the OUTCOME
    probe filters the projection to DontPanic's own row, not any other project's."""
    return up.PredicateContext(
        projection=projection, self_canonical_key=SELF_KEY, evidence_path=evidence_path
    )


def _valid_evidence() -> dict:
    return {
        "schema_version": "1.0",
        "canonical_repos": {},
        "observation_path_key_to_canonical": {},
    }


# ─────────────────────  predicate_registry resolves both namespaces  ─────────────────────


def test_predicate_registry_covers_both_namespaces():
    assert "canonical_discovery_registered_active" in up.predicate_registry["status_probe"]
    assert "canonical_backfill_evidence_valid" in up.predicate_registry["status_probe"]
    assert "has_tracked_projects" in up.predicate_registry["applies_when"]


def test_resolve_status_probe_dispatches_known_key():
    ctx = _self_ctx(_projection(active=[_active_row()]))
    res = up.resolve_status_probe("canonical_discovery_registered_active", ctx)
    assert res.satisfied is True
    assert not res.error


def test_resolve_applies_when_dispatches_known_key():
    ctx = up.PredicateContext(registry=Registry(projects=[_entry()]))
    res = up.resolve_applies_when("has_tracked_projects", ctx)
    assert res.satisfied is True
    assert not res.error


def _entry(name: str = "dontpanic", path: str = "/repo/dontpanic") -> ProjectEntry:
    return ProjectEntry(name=name, path=path, created_at=NOW)


# ─────────────────────  canonical_discovery_registered_active (OUTCOME probe)  ─────────────────────


def test_outcome_probe_satisfied_when_registered_active():
    ctx = _self_ctx(_projection(active=[_active_row()]))
    res = up.canonical_discovery_registered_active(ctx)
    assert res.satisfied is True
    assert "registered_active" in res.detail


def test_outcome_probe_satisfied_even_with_stale_malformed_evidence_file(tmp_path: Path):
    """D019: evidence validity does NOT gate an already-proven outcome. A stale /
    malformed leftover backfill-evidence file must NOT flip registered_active ->
    pending. The outcome probe never reads the evidence file at all."""
    evidence = tmp_path / up.EVIDENCE_FILENAME
    evidence.write_text("{ this is not valid json at all ", encoding="utf-8")

    ctx = _self_ctx(_projection(active=[_active_row()]), evidence_path=evidence)
    res = up.canonical_discovery_registered_active(ctx)
    assert res.satisfied is True  # malformed evidence did NOT flip the outcome

    # ... and the SAME malformed evidence makes the evidence-consuming predicate fail,
    # proving evidence validity gates only that predicate, not the outcome.
    ev_res = up.canonical_backfill_evidence_valid(ctx)
    assert ev_res.satisfied is False


def test_outcome_probe_not_satisfied_when_self_stale():
    """DontPanic's OWN row is stale (matched by its canonical_repo_key)."""
    ctx = _self_ctx(_projection(stale=[_active_row()]))
    res = up.canonical_discovery_registered_active(ctx)
    assert res.satisfied is False
    assert "stale" in res.detail


def test_outcome_probe_not_satisfied_when_self_path_missing():
    """DontPanic's own registered path is missing — matched by registry_name since
    a path-missing row carries no canonical_repo_key."""
    ctx = up.PredicateContext(
        projection=_projection(path_missing=[{"canonical_repo_key": None, "registry_name": "dontpanic"}]),
        self_canonical_key=SELF_KEY,
        self_registry_name="dontpanic",
    )
    res = up.canonical_discovery_registered_active(ctx)
    assert res.satisfied is False
    assert "missing" in res.detail


def test_outcome_probe_not_satisfied_when_self_unresolved():
    ctx = up.PredicateContext(
        projection=_projection(unresolved=[{"canonical_repo_key": None, "registry_name": "dontpanic"}]),
        self_canonical_key=SELF_KEY,
        self_registry_name="dontpanic",
    )
    res = up.canonical_discovery_registered_active(ctx)
    assert res.satisfied is False
    assert "unresolved" in res.detail


def test_outcome_probe_not_satisfied_when_nothing_registered():
    ctx = _self_ctx(_projection())
    res = up.canonical_discovery_registered_active(ctx)
    assert res.satisfied is False
    assert "no registered entry resolves to this DontPanic instance" in res.detail


def test_outcome_probe_not_satisfied_when_only_other_project_active():
    """REGRESSION (auditor finding 1): another project being registered_active must
    NOT satisfy THIS instance's probe. DontPanic's own key is absent from the
    registered_active bucket, so the outcome is NOT satisfied."""
    other = _active_row(name="other-app", key="other-key-999")
    ctx = up.PredicateContext(projection=_projection(active=[other]), self_canonical_key=SELF_KEY)
    res = up.canonical_discovery_registered_active(ctx)
    assert res.satisfied is False
    assert "no registered entry resolves to this DontPanic instance" in res.detail


def test_outcome_probe_not_satisfied_when_other_active_but_self_stale():
    """Mixed state: another project is active while DontPanic itself is stale.
    Satisfaction must reflect DontPanic's own (stale) row, not the other's active row."""
    other = _active_row(name="other-app", key="other-key-999")
    ctx = up.PredicateContext(
        projection=_projection(active=[other], stale=[_active_row(name="dontpanic")]),
        self_canonical_key=SELF_KEY,
    )
    res = up.canonical_discovery_registered_active(ctx)
    assert res.satisfied is False
    assert "stale" in res.detail


def test_outcome_probe_fails_closed_on_read_path_error():
    """A reconcile read-path failure (here an invalid `now`) fails CLOSED: not
    satisfied, flagged as a degraded/error result, never raising."""
    ctx = up.PredicateContext(now="not-a-timestamp", registry=Registry(projects=[]))
    res = up.canonical_discovery_registered_active(ctx)
    assert res.satisfied is False
    assert res.error is True


def test_outcome_probe_fails_closed_when_self_identity_undeterminable():
    """D026: when the running instance's canonical identity cannot be determined the
    probe fails CLOSED (never satisfied) — empty self_canonical_key + self_registry_name
    both resolve to None, so no row can be claimed as self."""
    ctx = up.PredicateContext(
        projection=_projection(active=[_active_row()]),
        self_canonical_key="",
        self_registry_name="",
    )
    res = up.canonical_discovery_registered_active(ctx)
    assert res.satisfied is False
    assert res.error is True
    assert "could not determine" in res.detail


# ─────────────────────  canonical_backfill_evidence_valid (evidence-consuming)  ─────────────────────


def test_evidence_predicate_satisfied_for_valid_file(tmp_path: Path):
    evidence = tmp_path / up.EVIDENCE_FILENAME
    evidence.write_text(json.dumps(_valid_evidence()), encoding="utf-8")
    ctx = up.PredicateContext(evidence_path=evidence)
    res = up.canonical_backfill_evidence_valid(ctx)
    assert res.satisfied is True
    assert res.evidence_uri == str(evidence)


def test_evidence_predicate_not_satisfied_when_missing(tmp_path: Path):
    ctx = up.PredicateContext(evidence_path=tmp_path / up.EVIDENCE_FILENAME)
    res = up.canonical_backfill_evidence_valid(ctx)
    assert res.satisfied is False
    assert "missing" in res.detail


def test_evidence_predicate_not_satisfied_for_malformed_json(tmp_path: Path):
    evidence = tmp_path / up.EVIDENCE_FILENAME
    evidence.write_text("{ not json", encoding="utf-8")
    ctx = up.PredicateContext(evidence_path=evidence)
    res = up.canonical_backfill_evidence_valid(ctx)
    assert res.satisfied is False


def test_evidence_predicate_not_satisfied_for_wrong_schema_version(tmp_path: Path):
    evidence = tmp_path / up.EVIDENCE_FILENAME
    bad = _valid_evidence()
    bad["schema_version"] = "9.9"
    evidence.write_text(json.dumps(bad), encoding="utf-8")
    ctx = up.PredicateContext(evidence_path=evidence)
    res = up.canonical_backfill_evidence_valid(ctx)
    assert res.satisfied is False
    assert "wrong_schema_version" in res.detail


# ─────────────────────  has_tracked_projects (applies_when)  ─────────────────────


def test_has_tracked_projects_applies_when_registry_non_empty():
    ctx = up.PredicateContext(registry=Registry(projects=[_entry()]))
    res = up.has_tracked_projects(ctx)
    assert res.satisfied is True
    assert not res.error


def test_has_tracked_projects_does_not_apply_when_registry_empty():
    ctx = up.PredicateContext(registry=Registry(projects=[]))
    res = up.has_tracked_projects(ctx)
    assert res.satisfied is False  # clean negative: action does not apply
    assert not res.error


def test_has_tracked_projects_fails_open_when_undeterminable(monkeypatch):
    """applies_when undeterminable -> applies true (fail-open), never silently
    hide a required action."""

    def _boom() -> Registry:
        raise RuntimeError("registry backend unavailable")

    monkeypatch.setattr(projects_registry, "load_registry_strict", _boom)
    res = up.has_tracked_projects(up.PredicateContext())  # registry=None -> loader called
    assert res.satisfied is True  # applies (fail-open)
    assert res.error is True


def test_has_tracked_projects_fails_open_on_real_malformed_registry(tmp_path, monkeypatch):
    """REGRESSION (auditor finding 2): a REAL malformed registry file on disk must
    fail OPEN (applies=True, error), not masquerade as "no tracked projects".

    The lenient ``load_registry`` swallows invalid JSON into an empty registry — the
    predicate must instead read it via the strict path so an unparseable file is
    surfaced as undeterminable rather than silently hiding the required action."""
    home = tmp_path / "dphome"
    home.mkdir()
    monkeypatch.setenv("DONTPANIC_HOME", str(home))
    (home / "projects.json").write_text("{ this is not valid json", encoding="utf-8")

    res = up.has_tracked_projects(up.PredicateContext())
    assert res.satisfied is True  # applies (fail-open)
    assert res.error is True
    assert "undeterminable" in res.detail


def test_has_tracked_projects_fails_open_on_schema_violating_registry(tmp_path, monkeypatch):
    """A registry whose JSON parses but violates the schema (extra='forbid' /
    wrong shape) is equally undeterminable -> fail open."""
    home = tmp_path / "dphome"
    home.mkdir()
    monkeypatch.setenv("DONTPANIC_HOME", str(home))
    # `projects` must be a list of entries; a string violates the schema.
    (home / "projects.json").write_text('{"projects": "not-a-list"}', encoding="utf-8")

    res = up.has_tracked_projects(up.PredicateContext())
    assert res.satisfied is True
    assert res.error is True


def test_has_tracked_projects_does_not_apply_when_registry_file_missing(tmp_path, monkeypatch):
    """A MISSING registry file is the clean zero state (not undeterminable): the
    action does not apply, and this is NOT flagged as an error."""
    home = tmp_path / "dphome"
    home.mkdir()
    monkeypatch.setenv("DONTPANIC_HOME", str(home))  # no projects.json written

    res = up.has_tracked_projects(up.PredicateContext())
    assert res.satisfied is False  # clean negative: does not apply
    assert res.error is False


# ─────────────────────  unknown-key fail directions (D026)  ─────────────────────


def test_unknown_status_probe_key_fails_closed():
    res = up.resolve_status_probe("typo_probe_key")
    assert res.satisfied is False
    assert res.error is True
    assert "unknown status_probe key" in res.detail


def test_unknown_applies_when_key_fails_open():
    res = up.resolve_applies_when("typo_applies_key")
    assert res.satisfied is True
    assert res.error is True
    assert "unknown applies_when key" in res.detail


def test_none_applies_when_key_applies_cleanly():
    res = up.resolve_applies_when(None)
    assert res.satisfied is True
    assert res.error is False


# ─────────────────────  a raising predicate never crashes resolution  ─────────────────────


def test_resolve_status_probe_catches_raising_predicate(monkeypatch):
    def _boom(_ctx):
        raise RuntimeError("predicate blew up")

    monkeypatch.setitem(up.STATUS_PROBES, "boom", _boom)
    res = up.resolve_status_probe("boom")
    assert res.satisfied is False  # fail-closed
    assert res.error is True


def test_resolve_applies_when_catches_raising_predicate(monkeypatch):
    def _boom(_ctx):
        raise RuntimeError("predicate blew up")

    monkeypatch.setitem(up.APPLIES_WHEN, "boom", _boom)
    res = up.resolve_applies_when("boom")
    assert res.satisfied is True  # fail-open
    assert res.error is True


# ─────────────────────  NO-MUTATION contract (D028)  ─────────────────────


def _snapshot_tree(root: Path) -> dict[str, str]:
    """Map every file under ``root`` to a sha256 of its bytes (path + content fingerprint)."""
    snap: dict[str, str] = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            snap[str(p.relative_to(root))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return snap


def test_every_predicate_is_read_only(tmp_path, monkeypatch):
    """D028: running EVERY predicate against a fixture HOME/registry mutates no
    registry / evidence / config / ledger / state on disk."""
    home = tmp_path / "dphome"
    home.mkdir()
    monkeypatch.setenv("DONTPANIC_HOME", str(home))

    # Seed a registry pointing at a real (non-temp-prefixed) repo dir, a ledger, and
    # a valid evidence file under HOME.
    repo = tmp_path / "repo"
    repo.mkdir()
    reg = Registry(projects=[ProjectEntry(name="dontpanic", path=str(repo), created_at=NOW)])
    (home / "projects.json").write_text(
        json.dumps(reg.model_dump(exclude_none=True), indent=2), encoding="utf-8"
    )
    (home / "invocations.jsonl").write_text("", encoding="utf-8")
    (home / up.EVIDENCE_FILENAME).write_text(
        json.dumps(_valid_evidence()), encoding="utf-8"
    )

    before = _snapshot_tree(home)

    # Run every predicate through the REAL read path (ctx defaults resolve from HOME).
    ctx = up.PredicateContext()
    up.canonical_discovery_registered_active(ctx)
    up.canonical_backfill_evidence_valid(ctx)
    up.has_tracked_projects(ctx)
    up.resolve_status_probe("canonical_discovery_registered_active", ctx)
    up.resolve_status_probe("canonical_backfill_evidence_valid", ctx)
    up.resolve_applies_when("has_tracked_projects", ctx)

    after = _snapshot_tree(home)
    assert before == after, "a predicate mutated on-disk state (no-mutation contract D028)"
