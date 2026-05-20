"""Fixture tests for plan 2026-05-19-004 F001 — dontpanic architecture.

Covers the acceptance criteria:
  (a) regen produces JSON that validates against the snapshot schema
  (b) regen is idempotent (same source → byte-identical bytes)
  (c) source fingerprint changes when any tracked file content changes
  (d) source fingerprint stable when nothing changes (no false drift)
  (e) plan inventory captures expected plans
  (f) status + diff subcommands work without paid LLM calls

Tests build a small synthetic repo tree in tmp_path so we never touch the
real DontPanic source layout. The Crawler accepts repo_root override
specifically for this — see scripts/dontpanic_orchestrate/architecture.py.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from dontpanic_orchestrate import architecture as arch

REPO_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_PATH = REPO_ROOT / "claude" / "shared" / "schemas" / "v1.0" / "architecture-snapshot.schema.json"


def _build_repo(root: Path) -> None:
    """Lay down a synthetic DontPanic-shaped tree under ``root``."""
    modules = root / "scripts" / "dontpanic_orchestrate"
    modules.mkdir(parents=True)
    (modules / "__init__.py").write_text(
        '"""Synthetic package for architecture tests."""\n__version__ = "0.0.1"\n',
        encoding="utf-8",
    )
    (modules / "supervisor.py").write_text(
        (
            '"""Supervisor orchestration entry point."""\n'
            "from __future__ import annotations\n"
            "import json\n"
            "from dontpanic_orchestrate import audit_writer\n"
            "\n"
            "class Supervisor:\n"
            "    def dispatch(self):\n"
            "        return True\n"
            "\n"
            "def helper():\n"
            "    return 1\n"
            "\n"
            "def _private():\n"
            "    return 0\n"
        ),
        encoding="utf-8",
    )
    (modules / "audit_writer.py").write_text(
        (
            '"""Audit writer."""\n'
            "import os\n"
            "\n"
            "def write_audit(path):\n"
            "    return path\n"
        ),
        encoding="utf-8",
    )

    # Schemas + VERSION
    schemas = root / "claude" / "shared" / "schemas" / "v1.0"
    schemas.mkdir(parents=True)
    (root / "claude" / "shared" / "VERSION").write_text("1.0.0\n", encoding="utf-8")
    (schemas / "plan.schema.json").write_text(
        json.dumps({"$id": "plan", "type": "object"}, sort_keys=True), encoding="utf-8"
    )
    (schemas / "features.schema.json").write_text(
        json.dumps({"$id": "features", "type": "object"}, sort_keys=True), encoding="utf-8"
    )
    (schemas / "validate.py").write_text("# stub validator\n", encoding="utf-8")

    # Plans (two distinct plans)
    plans_root = root / "docs" / "plans"
    plans_root.mkdir(parents=True)
    p1 = plans_root / "2026-05-19-100-feat-alpha"
    p1.mkdir()
    (p1 / "plan.md").write_text(
        (
            "---\n"
            "id: 2026-05-19-100-feat-alpha\n"
            "title: Alpha plan\n"
            "status: active\n"
            "---\n"
            "# body\n"
        ),
        encoding="utf-8",
    )
    (p1 / "features.json").write_text(
        json.dumps({"task_id": "2026-05-19-100-feat-alpha", "features": [{"id": "F001"}]}),
        encoding="utf-8",
    )

    p2 = plans_root / "2026-05-19-200-fix-beta"
    p2.mkdir()
    (p2 / "plan.md").write_text(
        (
            "---\n"
            "id: 2026-05-19-200-fix-beta\n"
            "title: Beta plan\n"
            "status: completed\n"
            "---\n"
        ),
        encoding="utf-8",
    )
    (p2 / "features.json").write_text(
        json.dumps(
            {"task_id": "2026-05-19-200-fix-beta", "features": [{"id": "F001"}, {"id": "F002"}]}
        ),
        encoding="utf-8",
    )


@pytest.fixture()
def synthetic_repo(tmp_path: Path) -> Path:
    _build_repo(tmp_path)
    return tmp_path


# ── Helpers ─────────────────────────────────────────────────────────────


def _load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _validate_against_schema(snap: dict) -> None:
    """Use jsonschema when available; otherwise assert required keys.

    jsonschema is part of the dev environment (4.26+); we still degrade
    cleanly so fresh-clone CI without it doesn't break this whole module.
    """
    try:
        import jsonschema
    except ImportError:  # pragma: no cover - environment-specific
        for key in ("schema_version", "generated_at", "source_fingerprint", "modules", "schemas", "plans"):
            assert key in snap
        return
    jsonschema.validate(snap, _load_schema())


# ── Tests ──────────────────────────────────────────────────────────────


def test_a_regen_produces_schema_valid_json(synthetic_repo: Path) -> None:
    out = arch.regen(synthetic_repo)
    assert out.exists()
    snap = json.loads(out.read_text(encoding="utf-8"))
    assert snap["schema_version"] == "1.0"
    _validate_against_schema(snap)
    # Sanity: source fingerprint root is a sha256 hex.
    assert len(snap["source_fingerprint"]["file_hashes_root"]) == 64
    # Sanity: modules section discovered our synthetic supervisor.
    module_names = {m["name"] for m in snap["modules"]}
    assert "dontpanic_orchestrate.supervisor" in module_names


def test_b_regen_is_idempotent(synthetic_repo: Path) -> None:
    first = arch.regen(synthetic_repo)
    first_bytes = first.read_bytes()
    # Sleep so a naive clock-based `generated_at` would differ across runs.
    # Idempotency depends on the fingerprint match, not the wall clock.
    time.sleep(1.05)
    second = arch.regen(synthetic_repo)
    second_bytes = second.read_bytes()
    assert first_bytes == second_bytes, "regen must produce byte-identical JSON when source is unchanged"


def test_c_fingerprint_changes_when_file_content_changes(synthetic_repo: Path) -> None:
    out = arch.regen(synthetic_repo)
    first = json.loads(out.read_text(encoding="utf-8"))
    first_root = first["source_fingerprint"]["file_hashes_root"]

    # Mutate a single tracked source file.
    target = synthetic_repo / "scripts" / "dontpanic_orchestrate" / "supervisor.py"
    target.write_text(target.read_text(encoding="utf-8") + "\n# tiny diff\n", encoding="utf-8")

    arch.regen(synthetic_repo)
    second = json.loads(out.read_text(encoding="utf-8"))
    second_root = second["source_fingerprint"]["file_hashes_root"]
    assert first_root != second_root, "fingerprint must change when any tracked file content changes"


def test_d_fingerprint_stable_when_no_changes(synthetic_repo: Path) -> None:
    """Two back-to-back fingerprints over an unchanged tree match exactly —
    proves no embedded clock / random IDs leak into the hash root."""
    crawler = arch.Crawler(synthetic_repo)
    first = crawler.fingerprint()
    time.sleep(1.05)
    second = crawler.fingerprint()
    assert first["file_hashes_root"] == second["file_hashes_root"]
    assert first["files_count"] == second["files_count"]


def test_e_plan_inventory_captures_expected_plans(synthetic_repo: Path) -> None:
    out = arch.regen(synthetic_repo)
    snap = json.loads(out.read_text(encoding="utf-8"))
    plans_by_id = {p["id"]: p for p in snap["plans"]}
    assert "2026-05-19-100-feat-alpha" in plans_by_id
    assert plans_by_id["2026-05-19-100-feat-alpha"]["status"] == "active"
    assert plans_by_id["2026-05-19-100-feat-alpha"]["features_count"] == 1
    assert "2026-05-19-200-fix-beta" in plans_by_id
    assert plans_by_id["2026-05-19-200-fix-beta"]["status"] == "completed"
    assert plans_by_id["2026-05-19-200-fix-beta"]["features_count"] == 2


def test_f_status_and_diff_subcommands(synthetic_repo: Path, capsys) -> None:
    # Status BEFORE regen: absent state.
    rc = arch.cli_main(["status", "--repo-root", str(synthetic_repo), "--json"])
    assert rc == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["state"] == "absent"

    # Regen → status should now report fresh.
    arch.regen(synthetic_repo)
    rc = arch.cli_main(["status", "--repo-root", str(synthetic_repo), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["state"] == "fresh"
    assert payload["stored_fingerprint"] == payload["current_fingerprint"]

    # Mutate a single tracked file → diff must list ONLY that file as
    # modified, with empty added/removed (i0 audit finding #2: prior
    # implementation listed every tracked file in `modified`).
    target_rel = "scripts/dontpanic_orchestrate/audit_writer.py"
    target = synthetic_repo / target_rel
    target.write_text(target.read_text(encoding="utf-8") + "\n# drift\n", encoding="utf-8")

    rc = arch.cli_main(["status", "--repo-root", str(synthetic_repo), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["state"] == "stale"
    assert payload["stored_fingerprint"] != payload["current_fingerprint"]

    rc = arch.cli_main(["diff", "--repo-root", str(synthetic_repo)])
    assert rc == 0
    diff_payload = json.loads(capsys.readouterr().out)
    assert diff_payload["state"] == "stale"
    assert diff_payload["modified"] == [target_rel], (
        "diff.modified must list exactly the changed file"
    )
    assert diff_payload["added"] == []
    assert diff_payload["removed"] == []


def test_g_diff_added_and_removed_files(synthetic_repo: Path) -> None:
    """A new tracked file shows up as `added`; a deleted one as `removed`."""
    arch.regen(synthetic_repo)

    # Add a new module (tracked) and delete an existing one.
    modules_root = synthetic_repo / "scripts" / "dontpanic_orchestrate"
    new_file = modules_root / "new_module.py"
    new_file.write_text('"""new tracked module."""\n', encoding="utf-8")
    removed_file = modules_root / "audit_writer.py"
    removed_rel = "scripts/dontpanic_orchestrate/audit_writer.py"
    new_rel = "scripts/dontpanic_orchestrate/new_module.py"
    removed_file.unlink()

    result = arch.diff(synthetic_repo)
    assert result["state"] == "stale"
    assert result["added"] == [new_rel]
    assert result["removed"] == [removed_rel]
    assert result["modified"] == []


def test_h_audit_and_evidence_artifacts_do_not_cause_drift(synthetic_repo: Path) -> None:
    """Audit, evidence, INBOX, events, and gate-state files under a plan
    directory must NOT contribute to the fingerprint. Regression for
    i0 audit finding #1: status flipped to stale the moment the next
    audit landed because the fingerprint hashed everything under
    docs/plans/."""
    arch.regen(synthetic_repo)
    before = arch.status(synthetic_repo)
    assert before["state"] == "fresh"

    plan_dir = synthetic_repo / "docs" / "plans" / "2026-05-19-100-feat-alpha"
    # Files the inventory does NOT consume — all should be ignored.
    audit_dir = plan_dir / "audit"
    audit_dir.mkdir()
    (audit_dir / "claude-implementer-F001-i0.json").write_text(
        json.dumps({"audit_status": "passed"}), encoding="utf-8"
    )
    evidence_dir = plan_dir / "evidence"
    evidence_dir.mkdir()
    (evidence_dir / "F001.json").write_text(json.dumps({"x": 1}), encoding="utf-8")
    (plan_dir / "INBOX.md").write_text("# events\n- entry\n", encoding="utf-8")
    (plan_dir / "events.jsonl").write_text('{"t":"start"}\n', encoding="utf-8")
    (plan_dir / "decisions.jsonl").write_text('{"id":"D001"}\n', encoding="utf-8")
    (audit_dir / "gate-state.json").write_text(json.dumps({"gates": []}), encoding="utf-8")

    after = arch.status(synthetic_repo)
    assert after["state"] == "fresh", (
        "audit/evidence/INBOX/events/decisions/gate-state under a plan dir "
        "must not change the fingerprint"
    )
    assert after["stored_fingerprint"] == before["stored_fingerprint"]
    assert after["current_fingerprint"] == before["current_fingerprint"]

    # And diff confirms zero drift even with all that churn.
    diff_result = arch.diff(synthetic_repo)
    assert diff_result["state"] == "fresh"
    assert diff_result["added"] == []
    assert diff_result["removed"] == []
    assert diff_result["modified"] == []


def test_i_plan_md_or_features_json_change_does_trigger_drift(synthetic_repo: Path) -> None:
    """The two whitelisted plan files MUST still drive drift — that's the
    inventory contract. Catches the inverse failure mode of the fix in
    test_h (if someone overshoots and excludes all of docs/plans/)."""
    arch.regen(synthetic_repo)
    plan_md = synthetic_repo / "docs" / "plans" / "2026-05-19-100-feat-alpha" / "plan.md"
    plan_md.write_text(
        plan_md.read_text(encoding="utf-8") + "\n## new section\n", encoding="utf-8"
    )
    result = arch.diff(synthetic_repo)
    assert result["state"] == "stale"
    assert result["modified"] == ["docs/plans/2026-05-19-100-feat-alpha/plan.md"]
    assert result["added"] == []
    assert result["removed"] == []
