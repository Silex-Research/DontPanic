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
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

EVIDENCE_SUBDIR = "integrations/evidence"

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
