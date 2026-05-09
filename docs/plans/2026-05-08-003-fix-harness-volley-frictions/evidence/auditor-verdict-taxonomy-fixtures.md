# F003 Auditor Verdict Taxonomy — Fixture-to-Decision Map

Plan `2026-05-08-003-fix-harness-volley-frictions` F003 ships a closed v0
classifier in `dontpanic_orchestrate/auditor_taxonomy.py`. This evidence
artifact maps every test fixture in `tests/test_auditor_taxonomy_f003.py`
to the taxonomy decision it pins, plus the rationale for why false
positives stay bounded — i.e. why an environmental / scope / shape label
cannot accidentally hide a real implementation defect.

## Test fixtures (19 cases)

### A. Pure classifier — single finding (10)

| # | Test | Input shape | Expected class | Why this finding lands here |
|---|------|-------------|----------------|---|
| A1 | `test_environmental_xcode_unavailable` | severity=high, category=test_coverage, issue mentions “Xcode unavailable in this sandbox host” | `environmental_reproduction_failure` | `_ENV_REPRO_PATTERNS` match on `\bxcode\b.*unavailable\b` |
| A2 | `test_environmental_jest_could_not_run` | severity=medium, test_coverage, “Could not run Jest test suite in the auditor sandbox” | `environmental_reproduction_failure` | matches `\b(could not|couldn't)\s+run\b` + `\bsandbox\b` |
| A3 | `test_environmental_permission_denied` | severity=high, security, “Permission denied invoking gcloud auth login from the sandbox” | `environmental_reproduction_failure` | matches `\bpermission\s+denied\b` |
| A4 | `test_evidence_shape_with_saved_evidence_flips` | severity=medium, documentation, “Expected a screenshot of the rendered UI; received only logs” + saved_evidence_paths=("evidence/ui-render.png", …) | `evidence_shape_disagreement` | matches `\bexpected\s+(?:a\s+)?screenshot\b` AND saved evidence is non-empty |
| A5 | `test_evidence_shape_without_saved_evidence_stays_blocking` | same issue text but saved_evidence_paths=() | `implementation_defect` | shape pattern matches but the saved-evidence gate REFUSES to flip; severity=high + category=correctness pushes the fallback to defect, NOT to advisory |
| A6 | `test_scope_overreach_via_feature_id_mismatch` | severity=high, security, finding.feature_id=F042, dispatched feature_id=F001 | `scope_overreach` | feature_id mismatch is the most-specific check — fires before any text pattern |
| A7 | `test_scope_overreach_via_text` | severity=medium, performance, “unrelated to this feature” | `scope_overreach` | matches `\bunrelated\s+to\s+(this|the)\s+feature\b` |
| A8 | `test_implementation_defect_substantive` | severity=high, correctness, “Race condition in auth listener…” | `implementation_defect` | severity=high AND category in `_DEFECT_CATEGORIES`; no env/shape/scope marker matched |
| A9 | `test_unknown_for_low_severity_no_pattern` | severity=low, style, “Minor quibble about variable naming” | `unknown` | severity not substantive AND category not defect AND no pattern matched — defaults to unknown (blocking) |
| A10 | `test_classifier_is_pure_and_deterministic` | same input twice | `==` equality on FindingClassification | confirms acceptance #1 (pure / deterministic) |

### B. Aggregate (terminal) classification (7)

| # | Test | Findings | Expected aggregate | Blocking? |
|---|------|---|---|---|
| B1 | `test_all_environmental_advisory` | 2 environmental | `environmental_reproduction_failure` | False — no defect/unknown present |
| B2 | `test_mixed_defect_plus_environmental_stays_blocking` | 1 critical correctness defect + 1 environmental | `implementation_defect` | True — defect class blocks the entire aggregate |
| B3 | `test_unknown_finding_present_remains_blocking` | 1 style/low (unknown) + 1 environmental | `unknown` | True — unknown ranks above advisory; aggregate is blocking |
| B4 | `test_empty_findings_collapse_to_unknown_blocking` | `[]` | `unknown` | True — defensive: a no-progress terminal with zero findings is opaque, operator must inspect |
| B5 | `test_evidence_shape_uses_prior_envelopes` | shape-disagreement finding + prior implementer envelope referencing `evidence/retry-trace.log` | `evidence_shape_disagreement` | False — saved-evidence gate flips on the prior-envelope path, not just the auditor's own envelope |
| B6 | `test_inbox_body_names_class_and_action` | environmental aggregate | `environmental_reproduction_failure` | INBOX body asserts the class label + recommended action are present |
| B7 | `test_sidecar_json_persists` | implementation_defect aggregate | sidecar JSON written under `audit/no_progress_classification_F001_iter2.json` | confirms acceptance #6 — F2 close gate has a citable artifact |

### C. End-to-end supervisor wiring (2)

| # | Test | Setup | Expected `final_status` | Expected aggregate |
|---|------|-------|-------------------------|---|
| C1 | `test_environmental_no_progress_emits_classification` | scripted volley, auditor returns `needs_changes` with environmental finding across two rounds | `stopped_no_progress` | `environmental_reproduction_failure`, blocking=False; sidecar JSON + INBOX `no_progress_classification` event present |
| C2 | `test_defect_no_progress_remains_blocking` | same volley shape but auditor returns critical correctness finding | `stopped_no_progress` | `implementation_defect`, blocking=True — terminal does NOT auto-advance |

## Why false positives stay bounded

The classifier's design specifically prevents the failure mode the
preserved evidence-shape overgating memory called out: an auditor
disagreement that masks a real defect.

1. **Severity floor** (`_SUBSTANTIVE_SEVERITIES`). Critical/high findings
   that don't match an environmental/shape/scope pattern fall through
   to `implementation_defect`, never to `unknown` or to an advisory
   class. A high-severity issue cannot be classified as advisory by
   accident — there is no path in the code that downgrades severity.

2. **Saved-evidence gate** (`evidence_shape_disagreement`). The shape
   pattern alone is NOT sufficient. The classifier checks the audit
   trail's prior envelopes for an `evidence/…` path that matches the
   `_SAVED_EVIDENCE_PATH_PATTERN`. If no such evidence is referenced,
   the classifier falls back to the substantive-severity rule (so
   high-severity findings stay blocking even when their text mentions
   "screenshot expected"). Test A5 pins this exact behavior.

3. **Scope-overreach via feature_id**. The most-specific scope check
   requires the auditor to have explicitly stamped a different
   `feature_id` on the finding — i.e. the auditor itself is declaring
   the concern out of scope. Text-pattern scope detection requires
   explicit "unrelated to this feature" / "out of scope" phrasing,
   not lexical similarity.

4. **Mixed-set escalation** (`_BLOCKING_CLASSES`). Any
   `implementation_defect` or `unknown` finding in a multi-finding set
   forces the aggregate to its own class AND sets `blocking=True`.
   There is no aggregation rule that downgrades a mixed set to
   advisory. Test B2 + B3 pin this exact behavior.

5. **Empty findings ≠ clean**. Zero findings on a `needs_changes`
   terminal collapses to `unknown` (blocking). The classifier never
   treats the absence of findings as "everything is fine"; it treats
   it as "auditor disagreed but did not enumerate why — operator must
   inspect." Test B4 pins this.

6. **No auto-advance**. The supervisor wiring (`supervisor.py` no-
   progress branch) only enriches the terminal `reason` and writes
   advisory artifacts; it never flips `result.final_status` away from
   `stopped_no_progress`. The terminal is preserved verbatim, so
   downstream consumers (signoff_writer, completion_gate) see the same
   non-success status they always saw. The classifier downgrades
   *operator burden*, not *terminal severity*. D006 is honored
   structurally.

## Closed taxonomy values (acceptance #2)

The five values in `auditor_taxonomy.FindingClass` are the only labels
emitted anywhere — sidecar JSON `aggregate`/`classification` fields,
INBOX `aggregate` header, terminal reason string, and the `findings[]`
entries in the sidecar all draw from the same enum. There is no
free-form classification path; if a finding cannot be placed, it lands
in `unknown` and stays blocking.
