# agent-conventions changelog

This file tracks DontPanic's subtree mirror of `agent-conventions`. The upstream
canonical history lives in `agent-conventions` itself; entries here record what
landed in the DontPanic subtree first (and that the operator subsequently
pushed upstream out-of-band).

## 1.8.0 — 2026-05-12

### Added
- `audit.schema.json`: `parsing` added as a 10th value to the
  `finding.category` enum. Strictly additive; the existing nine values
  (`correctness`, `security`, `performance`, `architecture`, `style`,
  `currency`, `redaction`, `test_coverage`, `documentation`) are unchanged.
- `models/audit_model.py`: `Category` enum gains `parsing = 'parsing'` to
  mirror the JSON schema.

### Motivation
DontPanic plan `2026-05-12-001-fix-harness-frictions-v4` F003 emitted advisory
findings for shlex parse failures inside `commands_run`. The F003 spec text
called for `severity=advisory category=parsing`, but the v1.7.0 enum did not
include `parsing`, so the F003 implementer fell back to `correctness` and
v4 D008 documented the deviation as a spec_ambiguity. v4.1 F001
(plan `2026-05-12-002-fix-harness-frictions-v4-1`) closes that gap by making
the new enum value real.

### Notes
- Backward compatible: validators that accept the old 9-value enum will fail
  closed on a `parsing` finding (the desired strict behavior); validators
  pinned to v1.8.0 schemas accept it.
- DontPanic-side change only. The operator cherry-picks this into
  `agent-conventions`, tags `v1.8.0`, and pushes the subtree separately
  (per plan D003).
