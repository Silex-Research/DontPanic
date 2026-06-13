"""Plan 2026-06-04-003 — integration operator-actions catalog + evidence reads.

The catalog below implements EXACTLY the literal table in the plan's
"Integration catalog (F001 literal rows)" section — commands, credential
env-var names, action ids, and evidence expectations are fixture-binding
and MUST NOT drift without a plan amendment.

Honest-commands split (CP-D008): external commands ride the display-only
``operator_command`` field; ``exact_command`` carries ONLY validated
dontpanic commands (the static smoke), else None.

Evidence files (F002 contract) are append-only JSONL, one per integration,
under ``$DONTPANIC_HOME/integrations/evidence/<integration_id>.jsonl``.
F001 only READS them (provider state derivation); the writer ships in F002.
"""

from __future__ import annotations

import dataclasses
import datetime as _dt
import json
import os
import re
import stat
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

EVIDENCE_SUBDIR = "integrations/evidence"
EVIDENCE_SCHEMA_VERSION = "1.0.0"
EVIDENCE_FILE_MODE = 0o600
EVIDENCE_DIR_MODE = 0o700
_VALID_EVIDENCE_OUTCOMES = ("passed", "failed")
_VALID_EVIDENCE_SOURCES = ("smoke", "attestation")

# Trigger attestations for the gated Firebase rows use this action id.
TRIGGER_ACTION_FIREBASE = "firebase-trigger"


@dataclasses.dataclass(frozen=True)
class IntegrationAction:
    """One catalog row — a single operator-owned integration step."""

    integration_id: str
    action_id: str
    what: str
    why: str
    # honest-commands split: exactly one of these is set (or neither).
    exact_command: str | None
    operator_command: str | None
    credential_env_vars: tuple[str, ...]
    evidence_expected: str
    reversible: bool
    trigger_condition: str | None = None


INTEGRATION_CATALOG: tuple[IntegrationAction, ...] = (
    IntegrationAction(
        integration_id="static-dashboard",
        action_id="static-dashboard-smoke",
        what="Run the static-dashboard smoke",
        why="Proves `state export-dashboard` output actually renders through the real dashboard build.",
        exact_command="dontpanic integrations smoke static-dashboard",
        operator_command=None,
        credential_env_vars=(),
        evidence_expected="smoke record outcome=passed",
        reversible=True,
    ),
    IntegrationAction(
        integration_id="firebase-functions-deploy",
        action_id="firebase-creds",
        what="Provision Firebase service credentials",
        why="Deploying dashboard/functions/ needs operator-held Firebase credentials.",
        exact_command=None,
        operator_command=(
            "provision Firebase service credentials, then "
            "`dontpanic integrations attest firebase-functions-deploy "
            "--action firebase-creds --outcome passed`"
        ),
        credential_env_vars=("FIREBASE_TOKEN",),
        evidence_expected="attestation record (action_id firebase-creds)",
        reversible=False,
        trigger_condition="multi-operator dashboard need",
    ),
    IntegrationAction(
        integration_id="firebase-functions-deploy",
        action_id="firebase-deploy",
        what="Deploy the shipped Cloud Functions",
        why="dashboard/functions/ is coded + tested; the live deploy is operator-owned.",
        exact_command=None,
        operator_command=(
            "`firebase deploy --only functions`, then "
            "`dontpanic integrations attest firebase-functions-deploy "
            "--action firebase-deploy --outcome passed`"
        ),
        credential_env_vars=("FIREBASE_TOKEN",),
        evidence_expected="attestation record (action_id firebase-deploy)",
        reversible=False,
        trigger_condition="multi-operator dashboard need",
    ),
    IntegrationAction(
        integration_id="firebase-realtime-smoke",
        action_id="firebase-realtime-smoke",
        what="Run the realtime dashboard smoke",
        why="Confirms the deployed functions serve the realtime dashboard end to end.",
        exact_command=None,
        operator_command=(
            "follow dashboard/functions/RUNBOOK.md smoke, then "
            "`dontpanic integrations attest firebase-realtime-smoke "
            "--action firebase-realtime-smoke --outcome passed`"
        ),
        credential_env_vars=("FIREBASE_TOKEN",),
        evidence_expected="attestation record outcome=passed",
        reversible=True,
        trigger_condition="multi-operator dashboard need",
    ),
    IntegrationAction(
        integration_id="discord-webhook",
        action_id="discord-webhook",
        what="Configure the Discord notification webhook",
        why="notify_discord.py is shipped; it only needs the webhook env var provisioned.",
        exact_command=None,
        operator_command=(
            "set the Discord webhook env var, then "
            "`dontpanic integrations attest discord-webhook "
            "--action discord-webhook --outcome passed`"
        ),
        credential_env_vars=("DONTPANIC_DISCORD_WEBHOOK_URL",),
        evidence_expected="attestation record (action_id discord-webhook)",
        reversible=True,
    ),
    IntegrationAction(
        integration_id="linear-credentials",
        action_id="linear-creds",
        what="Provision Linear API credentials",
        why="Capability-gates the future PM-sync work tracked in the ext-bridge plan.",
        exact_command=None,
        operator_command=(
            "provision Linear API credentials, then "
            "`dontpanic integrations attest linear-credentials "
            "--action linear-creds --outcome passed`"
        ),
        credential_env_vars=("LINEAR_API_KEY",),
        evidence_expected="attestation record (action_id linear-creds)",
        reversible=True,
    ),
)


def evidence_file(evidence_dir: Path, integration_id: str) -> Path:
    return Path(evidence_dir) / f"{integration_id}.jsonl"


def read_evidence(evidence_dir: Path, integration_id: str) -> list[dict[str, Any]]:
    """Read the append-only evidence history for one integration.

    Malformed lines are skipped rather than raised — evidence is advisory
    input to status derivation, and a torn append must not take down the
    whole provider. Missing file = empty history.
    """
    path = evidence_file(evidence_dir, integration_id)
    if not path.is_file():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict):
            records.append(rec)
    return records


def has_passed_evidence(
    records: Sequence[Mapping[str, Any]], action_id: str
) -> bool:
    """True iff any record for *action_id* has outcome=passed (the status
    FLOOR semantics — later failures never erase a prior pass)."""
    return any(
        r.get("action_id") == action_id and r.get("outcome") == "passed"
        for r in records
    )


def latest_outcome(
    records: Sequence[Mapping[str, Any]], action_id: str
) -> str | None:
    """The most recent record's outcome for *action_id* (file order), or None."""
    outcome: str | None = None
    for r in records:
        if r.get("action_id") == action_id:
            outcome = r.get("outcome")
    return outcome


# ── F002: append-only evidence writer ─────────────────────────────────────────
def _now_iso(now: _dt.datetime | None = None) -> str:
    ts = now if now is not None else _dt.datetime.now(_dt.timezone.utc)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=_dt.timezone.utc)
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe_integration_id(integration_id: str) -> str:
    """Neutralize path separators / dot-runs so a typo'd id cannot escape the
    evidence dir via the filename component (mirrors capabilities_setup_evidence)."""
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", integration_id)
    return safe.strip("_-") or "unknown"


def _sanitize_evidence(value: Any) -> Any:
    """Scrub obvious credential shapes from evidence detail before it lands on
    disk, reusing the shipped capabilities-setup secret patterns."""
    from dontpanic_orchestrate import capabilities_setup_evidence as _cse

    if isinstance(value, str):
        return _cse._apply_secret_patterns(value)
    if isinstance(value, Mapping):
        return {k: _sanitize_evidence(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize_evidence(v) for v in value]
    return value


def write_integration_evidence(
    evidence_dir: Path,
    integration_id: str,
    action_id: str,
    *,
    source: str,
    outcome: str,
    details: Mapping[str, Any] | None = None,
    now: _dt.datetime | None = None,
) -> Path:
    """Append one evidence record (JSONL) for an integration action.

    Append-only by construction: the file is opened in append mode and a
    single line is written, so a later record never rewrites or deletes a
    prior one (F002 floor-from-history). These files are the SOLE channel the
    F001 clears_when predicates and F004 status derivation consume.

    Sanitizes ``details`` through the shipped secret patterns before writing;
    dir 0700 / file 0600 to match the rest of the DontPanic state surface.
    """
    if outcome not in _VALID_EVIDENCE_OUTCOMES:
        raise ValueError(
            f"outcome={outcome!r} must be one of {_VALID_EVIDENCE_OUTCOMES}"
        )
    if source not in _VALID_EVIDENCE_SOURCES:
        raise ValueError(
            f"source={source!r} must be one of {_VALID_EVIDENCE_SOURCES}"
        )

    evidence_dir = Path(evidence_dir)
    evidence_dir.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(evidence_dir, EVIDENCE_DIR_MODE)
    except OSError:
        pass

    record: dict[str, Any] = {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "integration_id": integration_id,
        "action_id": action_id,
        "captured_at": _now_iso(now),
        "source": source,
        "outcome": outcome,
    }
    if details:
        record["details"] = _sanitize_evidence(dict(details))

    target = evidence_file(evidence_dir, _safe_integration_id(integration_id))
    with target.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True) + "\n")
    try:
        if stat.S_IMODE(target.stat().st_mode) != EVIDENCE_FILE_MODE:
            os.chmod(target, EVIDENCE_FILE_MODE)
    except OSError:
        pass
    return target


# ── F002: render-proof static-dashboard smoke ─────────────────────────────────
@dataclasses.dataclass(frozen=True)
class SmokeResult:
    """Outcome of run_static_dashboard_smoke."""

    outcome: str  # "passed" | "failed"
    detail: str
    evidence_path: Path | None


def run_static_dashboard_smoke(
    *,
    plans_root: Path,
    build_dir: Path,
    evidence_dir: Path,
    now: _dt.datetime | None = None,
) -> SmokeResult:
    """Render-proof smoke for the static dashboard (F002).

    Runs the REAL dashboard build over the exported state, then asserts the
    exported state's identifying values (plan ids that should surface as cards)
    appear in the BUILT dashboard artifact (what-now.json) — NOT merely in the
    copied state JSON. A parseable-but-unrenderable or silently-empty render
    therefore fails the smoke. Always records evidence via the F002 writer.

    The integration/action ids match the catalog so the F001 clears_when
    predicate (integration_evidence_present) resolves the smoke item.
    """
    from dontpanic_orchestrate import dashboard as _dash
    from dontpanic_orchestrate import state_projection as _sp

    integration_id = "static-dashboard"
    action_id = "static-dashboard-smoke"

    def _record(outcome: str, detail: str) -> SmokeResult:
        path = write_integration_evidence(
            evidence_dir,
            integration_id,
            action_id,
            source="smoke",
            outcome=outcome,
            details={"detail": detail},
            now=now,
        )
        return SmokeResult(outcome=outcome, detail=detail, evidence_path=path)

    # 1. Build the dashboard over the exported state (export + render in one pass).
    #    write_what_now_cache=True is required to emit the rendered
    #    <out_dir>/what-now.json artifact; the operator-global home cache write
    #    is redirected into build_dir so the smoke never mutates ~/.dontpanic.
    build_dir = Path(build_dir)
    build_dir.mkdir(parents=True, exist_ok=True)
    try:
        _dash.build(
            plans_root=plans_root,
            out_dir=build_dir,
            check_reconcile=False,
            check_architecture=False,
            write_what_now_cache=True,
            write_capabilities_cache=False,
            what_now_cache_path_override=build_dir / "_home-what-now.json",
        )
    except Exception as exc:  # noqa: BLE001 — any build failure = smoke failure
        return _record("failed", f"dashboard build raised: {type(exc).__name__}: {exc}")

    snapshot_path = build_dir / "state-snapshot.json"
    what_now_path = build_dir / "what-now.json"
    if not snapshot_path.is_file():
        return _record("failed", "export produced no state-snapshot.json")
    if not what_now_path.is_file():
        return _record("failed", "build produced no rendered what-now.json artifact")

    # 2. Render-proof (NOT parse-proof): the cards the producer emits MUST reach
    #    the BUILT what-now.json artifact. Re-running the real provider gives the
    #    "should render" truth; comparing dedupe_keys against the rendered items
    #    catches a parseable-but-unrenderable or silently-empty render. Matching
    #    in the snapshot's copied state JSON would NOT count (finding #3) — we
    #    match against what-now.json, the rendered card set the operator sees.
    try:
        rendered = json.loads(what_now_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return _record("failed", f"rendered what-now.json unreadable: {exc}")
    rendered_items = rendered.get("items") if isinstance(rendered, Mapping) else rendered
    if not isinstance(rendered_items, list):
        return _record("failed", "rendered what-now.json has no items array")
    rendered_keys = {
        it.get("dedupe_key") or it.get("id")
        for it in rendered_items
        if isinstance(it, Mapping)
    }

    expected = _dash._gather_action_items(
        plans_root=plans_root,
        capability_envelope=None,
        reconcile_result=None,
        arch_status=None,
        plan_id=None,
    )
    expected_keys = {c.dedupe_key or c.id for c in expected}
    if not expected_keys:
        return _record("passed", "empty ledger: export + render pipeline ran clean")

    missing = expected_keys - rendered_keys
    if missing:
        return _record(
            "failed",
            f"render dropped {len(missing)} producer card(s) — possible "
            "silently-empty render: " + ", ".join(sorted(missing)[:5]),
        )
    return _record(
        "passed",
        f"render-proof: all {len(expected_keys)} producer card(s) present in built artifact",
    )
