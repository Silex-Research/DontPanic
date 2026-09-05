---
title: Explain autonomous operation in the README
date: "2026-09-04"
tier: local
status: completed
---

# Explain autonomous operation in the README

A new user can understand how DontPanic implements a well-developed plan,
choose direct operation or optional hands-free administration, and run the
documented feature loop without confusing gate clearance with execution.

The user authorized this documentation edit and requested review before publication.
Work starts from main at `a4ed6b6`. On 2026-09-05, after reviewing the draft,
the user supplied a replacement graphic and authorized publication of the changes.

- [x] Shorten README to roughly 250–350 lines, with an optional-operator use case,
  supported-worker table, explicit feature loop, and attributed ML case study.
- [x] Move client recipes into the agent guide and explain continuing work under
  an existing bounded authorization, with explicit human decision boundaries.
- [x] Align linked product/setup docs and license metadata; record the doc change.
- [x] Preserve the manifest safety rule and main's venv/intake corrections.
- [x] Run relevant existing doc/runtime checks, check links and diff, and prepare
  a local preview for the user.

No runtime behavior, permission policy, or production-readiness guarantee changes.
The previously observed test-status advisory bug remains a separate code task.
The ML case study is the author's report, not an independently audited benchmark.

Baseline: 40 existing discoverability, worker-doc-drift, and showcase tests passed.

Validation: 142 targeted documentation, worker-capability, dispatch, gate,
and package-metadata tests passed. Updated test file passes Ruff lint/format;
sanitization and whitespace checks passed. Relative documentation links resolve.
The isolated no-cost sample validated, locked, and closed as completed, with
the existing advisory warnings for its legacy local target. No paid run occurred.
The prepared README and complete patch are for user review before publication.

Publication follow-up: replace the overview PNG exactly with the supplied image,
export its JPEG social-preview companion without cropping, and retain the existing
asset paths. Publish the documentation and assets together after final checks.

Final validation: the full suite passed 6,444 tests with seven skips in the sandbox;
all 43 socket/signing-related failures and errors passed on an isolated rerun.
Repository-wide Ruff findings and formatting debt match the main baseline exactly
(300 lint findings, 354 files requiring formatting), with no new findings.
