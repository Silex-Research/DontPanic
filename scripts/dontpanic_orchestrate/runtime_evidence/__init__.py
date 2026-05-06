"""Goal Governance V1 — runtime evidence harness (Plan G prerequisites for F2).

Capture-only adapters per source surface. F2 (the post-impl
completion-test auditor) consumes the harness; Plan G's adapters
write structured ``EvidenceRef`` artifacts into
``evidence/goal-governance/post_impl/<source>/<journey-id>/``.

Per Plan G's locked decisions:

- D002: capture only, never audit/score. No journey-walk semantics.
- D003: evidence path discipline via
  ``nested_orchestration.goal_governance_evidence_path()``.
- D004: project-agnostic; no project-name special cases.
- D005: no new credential storage.

G1 (web) ships first; G2 (iOS), G3 (android), G4 (backend), and
G5 (the integrating ``EvidenceCollector``) land in subsequent commits.
This package's public surface grows additively per feature commit.
"""
