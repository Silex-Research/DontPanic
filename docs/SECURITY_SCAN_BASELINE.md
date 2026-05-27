# Security Scan Baseline

Last reviewed: 2026-05-20

This file documents gitleaks history findings that have been reviewed and
classified as non-secret false positives before public release. The matching
fingerprints live in `.gitleaksignore`; do not add new entries without a
reviewed rationale.

## Reviewed Findings

| Rule | Historical file | Classification |
| --- | --- | --- |
| `private-key` | `docs/plans/2026-05-09-003-feat-state-projection-v0/evidence/F003-redaction-tests.log` | Pytest parameter label containing the literal test fixture string `BEGIN RSA PRIVATE KEY`; no private key material. |
| `jwt` | `scripts/jarvis_orchestrate/tests/test_f001_secret_shapes.py` | Intentional synthetic JWT-shaped fixture for secret-shape scanner coverage. |
| `curl-auth-header` | `tracking/BLOCKED.md` | Placeholder documentation example using a bearer-token-shaped string, not a live credential. |
| `discord-api-token` / `generic-api-key` | `docs/architecture/architecture.json`, `docs/showcase/dontpanic-architecture.json` | SHA-256 file-hash map values in generated architecture snapshots; values are 64-character hex digests, not API tokens. |
| `generic-api-key` | `scripts/dontpanic_orchestrate/tests/test_event_messaging_sanitization_f004.py`, `scripts/dontpanic_orchestrate/tests/test_capabilities_setup_evidence_f003.py`, `docs/plans/2026-05-22-004-feat-capability-guided-setup-v2/audit/codex-auditor-F003-i*.json` | Sanitization-test fixtures and audit evidence where the matched value is the literal string `REDACTED`; no secret material. |

## Rule

Any future non-zero gitleaks finding blocks public release until it is either:

- confirmed as a real secret and remediated through rotation plus history
  rewrite or a rebuilt public branch; or
- added here with a concrete false-positive rationale and a matching
  `.gitleaksignore` fingerprint.
