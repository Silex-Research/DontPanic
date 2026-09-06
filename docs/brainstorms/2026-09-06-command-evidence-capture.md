# Command execution evidence and runtime capture — implemented design

Status: **SHIPPED per D002 ADOPT** (PR#74 branch `review/five-step-delivery`).
The explicit opt-in CLI path (Option 1) was selected and shipped.

Decision record: `docs/plans/2026-09-06-001-infra-delivery-integration-review/decisions.jsonl`
- D001: PROBE command-evidence design (original)
- D002: ADOPT opt-in evidence CLI (Thanos BUILD lock confirmation)

Shipped commands (2026-09-06):
- `dontpanic evidence run` — command recorder (LIFECYCLE_MUTATION with --confirm)
- `dontpanic evidence capture` — capture producer

Implementation:
- `scripts/dontpanic_orchestrate/evidence_cli.py` — CLI module
- `scripts/dontpanic_orchestrate/tests/test_evidence_cli_sep2026.py` — acceptance tests

Public-entry honesty: evidence does NOT grant agent dispatch authority —
operator must explicitly invoke. Classification is LIFECYCLE_MUTATION
(not CONFIG_MUTATION) because --confirm executes operator-provided argv.

This document does not authorize paid dispatch, live capture, cloud writes,
or fabricated execution proof.

## Options
1. **Recommended: explicit opt-in CLI producers.** Caller selects plan, feature,
   iteration and target. Works with multiple harnesses and preserves the audit
   reader boundary. Requires the caller to invoke the producer.
2. Supervisor-triggered capture. Less caller effort; requires dispatch lifecycle,
   cancellation and budget integration and may run unexpected extra tooling.
3. Design only. Leaves current external/operator capture supported while the
   integration remains explicitly incomplete.

## Command recorder contract
Proposed form: `dontpanic evidence run PLAN --feature F --iteration N --cwd ROOT
--timeout-seconds N --confirm -- COMMAND ARG...`. Dry-run without confirm.
This is a proposed API, not a runnable example for the current release.

- Resolve plan/feature and declared target before side effects; refuse unknown
  feature, undeclared target, path traversal, and malformed limits.
- Execute an argument vector with shell=False. No shell interpolation or command
  extraction from model prose. Explicit plan scope and operator authorization
  remain required; this recorder does not grant agent dispatch authority.
- Record invocation ID, canonical target cwd, argv digest/redacted display,
  feature/iteration, start/end time, code revision and dirty diff hash, exit code,
  timeout/cancel/spawn-error status, bounded stdout/stderr hashes and redacted
  excerpts. Never copy credentials from environment into the record.
- Append immutable invocation records; atomic final publication, journal a start
  before execution, recover interrupted runs as incomplete. Output caps and
  subprocess-group cancellation must bound both execution and evidence storage.
- A zero command exit is command success, not blanket named-test or journey
  success. Named-test claims require structured runner results or a known parser
  proving collection/execution, including no-tests-collected and deselection.
- Missing records mean unknown/not observed, not violated. Keep self-reported
  commands under target_context distinct from observed records. Link verified
  records to the audit envelope; fix the envelope path before enabling judges.
- Local records provide provenance under a trusted local operator; they are not
  tamper-proof attestations against that operator.

## Capture producer contract
Proposed form: `dontpanic evidence capture PLAN --journey NAME --source NAME
--config FILE --confirm`. Dry-run resolves the requested source and target.

- Validate that the journey exists; project-scoped configuration only. No URLs,
  simulator names, package IDs or credentials invented from ambient state.
- A new producer composes the existing EvidenceCollector with explicitly bound
  source adapters. The completion auditor remains a manifest reader and never
  instantiates sessions. Do not wire capture into the reviewer.
- Run in a unique capture directory; preserve earlier captures. Publish a
  versioned manifest atomically only after all requested sources return. Capture
  failures and unsupported targets remain typed skips; no execution satisfaction
  is minted merely because a screenshot or manifest exists.
- Validate path containment, concurrent runs, output/time budgets, credentials,
  artifact hashes and redaction before publication. Capture-only never mutates
  approvals, feature passes, plan status or signoff.
- Start with one operator-selected real surface, prove its full producer → disk
  manifest → reader path, then add each remaining adapter behind the same tests.
  Do not claim all platforms integrated after a fake-driver-only unit test.

## Public-entry acceptance
Subprocess CLI tests cover dry-run/no writes; exit 0 and nonzero commands;
spawn failure; timeout; cancellation; inherited-secret redaction; bounded output;
wrong feature/iteration/revision; concurrent publication; tampered hash; empty
runner collection; capture skip; and a complete reader round trip. One authorized
real target walk is required in addition to injected-driver integration tests.
