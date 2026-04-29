# INBOX — cost-guard

Operator-facing event log written by the supervisor.

---
timestamp: 2026-04-28T12:00:00Z
event: cost_breach
plan_id: cost-guard
scope: app:Styln
severity: action_required
ratio: 1.6071
---

GCP projection for Styln (1607.14 USD month-end) is at 160.7% of the configured monthly budget (1000.00 USD). Threshold: 100%.

===
---
timestamp: 2026-04-28T12:00:00Z
event: cost_breach
plan_id: cost-guard
scope: llm:claude
severity: action_required
ratio: 3.7333
---

LLM projection for claude (3733333333 tokens week-end) is at 373.3% of the configured weekly budget (1000000000). Threshold: 100%.

===
