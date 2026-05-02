# F001 confirmation memo

**Plan:** `2026-05-01-003-feat-security-baseline`
**Feature:** F001 (`security baseline hardening`)
**Status:** `passes: true` (operator-accepted). Volley terminal state was `signoff: true`, `signed_off_count: 2`, `next_action: merge` at `2026-05-01T23:43:58Z`.

## What the close-out evidence covers

| Surface | Evidence | Captured |
|---|---|---|
| Secret-shape scanner | `scripts/sanitization_check.py` + `scripts/jarvis_orchestrate/tests/test_f001_secret_shapes.py` | 8 accepted regex families, each with synthetic positive and negative coverage |
| CI least privilege | `.github/workflows/ci.yml` | workflow-root `permissions: contents: read` |
| Security policy | `SECURITY.md` | Reporting a Vulnerability, Supported Versions, Response Timeline |
| SA-key age warning | `scripts/jarvis_doctor.py` + `evidence/f001/checks/doctor_synthetic_stale_key.txt` | 100-day synthetic key emits the rotation warning while doctor still passes |
| Full tests | `evidence/f001/checks/pytest.txt` | 333 passed, 6 skipped |
| Sanitization | `evidence/f001/checks/sanitization_check.txt` | no campaign IDs or secret shapes in sanitized surface |
| Iteration-1 boundary checks | `evidence/f001/checks/aws_placeholder_boundary_check.txt`, `evidence/f001/checks/pem_citation_immediately_above.txt` | placeholder and citation regressions from iter 0 closed |

## Audit interpretation

The volley converged in one remediation round:

| Iteration | Auditor verdict | Findings | Close-out read |
|---|---:|---:|---|
| 0 | `needs_changes` | 4 | EC5 prelude self-finding, AWS placeholder boundary, PEM citation placement, SA-key warning format |
| 1 | `signed_off` | 0 | All four iter-0 findings remediated |

The iter-0 EC5 prelude issue is the repeated auditor-prompt self-finding captured by the broader Plan A D009/D010 follow-up pattern. It is not a blocker for F001 behavior because the F001 auditor signed off after the mechanical remediation pass.

## Archived dispatch state

Volley artifacts that mutate during dispatch are archived under `evidence/f001/archive/` rather than staged as live plan state:

- `evidence/f001/archive/INBOX.md`
- `evidence/f001/archive/audit/`
- `evidence/f001/archive/iteration-0-raw/`
- `evidence/f001/archive/iteration-1-raw/`

The durable close-out surfaces are the implementation files, `features.json`, this memo, and the normalized check outputs under `evidence/f001/checks/`.
