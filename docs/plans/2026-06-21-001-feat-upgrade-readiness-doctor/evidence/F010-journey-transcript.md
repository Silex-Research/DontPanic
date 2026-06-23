# F010 — after-git-pull update journey (real doctor CLI, out-of-process)

instance home: /Users/bayesian/.dontpanic-f010-e2e-74843/home
fixture project (cwd): /Users/bayesian/.dontpanic-f010-e2e-74843/fixture-project

## 1. Fresh update (no marker): plain `dontpanic doctor --skip-auth --json`
$ python -m dontpanic_orchestrate doctor --skip-auth --json
rc=1
stdout:
{
  "checks": [
    {
      "name": "python>=3.10",
      "ok": true,
      "message": "Python 3.10",
      "remediation": "",
      "warn": false
    },
    {
      "name": "cli:gcloud",
      "ok": true,
      "message": "gcloud found",
      "remediation": "",
      "warn": false
    },
    {
      "name": "cli:firebase",
      "ok": true,
      "message": "firebase found",
      "remediation": "",
      "warn": false
    },
    {
      "name": "cli:jq",
      "ok": true,
      "message": "jq found",
      "remediation": "",
      "warn": false
    },
    {
      "name": "cli:git",
      "ok": true,
      "message": "git found",
      "remediation": "",
      "warn": false
    },
    {
      "name": "target-project",
      "ok": true,
      "message": "environments.json dev=jarvis-a6ee1",
      "remediation": "",
      "warn": false
    },
    {
      "name": "secrets-dir",
      "ok": true,
      "message": ".secrets/ exists, gitignored",
      "remediation": "",
      "warn": false
    },
    {
      "name": "sa-key-age",
      "ok": true,
      "message": "/Users/bayesian/.dontpanic-f010-e2e-74843/home/.secrets not present (no SA keys to age-check)",
      "remediation": "",
      "warn": false
    },
    {
      "name": "py:pydantic",
      "ok": true,
      "message": "pydantic OK",
      "remediation": "",
      "warn": false
    },
    {
      "name": "py:yaml",
      "ok": true,
      "message": "yaml OK",
      "remediation": "",
      "warn": false
    },
    {
      "name": "py:firebase_admin",
      "ok": true,
      "message": "firebase_admin OK",
      "remediation": "",
      "warn": false
    },
    {
      "name": "schemas",
      "ok": true,
      "message": "5 core schemas present at claude/shared/schemas/v1.0",
      "remediation": "",
      "warn": false
    },
    {
      "name": "pydantic-models",
      "ok": true,
      "message": "plan/features/audit/environments/signoff models import clean",
      "remediation": "",
      "warn": false
    },
    {
      "name": "parent-plan",
      "ok": true,
      "message": "parent orchestration plan validates",
      "remediation": "",
      "warn": false
    },
    {
      "name": "quota-caps",
      "ok": true,
      "message": "/Users/bayesian/.dontpanic-f010-e2e-74843/home-env/.jarvis/quota_state.json not present \u2014 run `python3 scripts/quota_check.py` to populate",
      "remediation": "",
      "warn": false
    },
    {
      "name": "global-config",
      "ok": true,
      "message": "/Users/bayesian/.dontpanic-f010-e2e-74843/home/config.json not present (first-run zero state \u2014 defaults will fall through to hardcoded)",
      "remediation": "",
      "warn": false
    },
    {
      "name": "projects-registry",
      "ok": true,
      "message": "1 project(s) registered",
      "remediation": "",
      "warn": false
    },
    {
      "name": "project:fixture-project:path",
      "ok": true,
      "message": "path exists: /Users/bayesian/.dontpanic-f010-e2e-74843/fixture-project",
      "remediation": "",
      "warn": false
    },
    {
      "name": "project:fixture-project:config",
      "ok": true,
      "message": "/Users/bayesian/.dontpanic-f010-e2e-74843/fixture-project/.dontpanic/dontpanic.json not present (per-project config is optional)",
      "remediation": "",
      "warn": false
    },
    {
      "name": "project:fixture-project:plans-dir",
      "ok": true,
      "message": "declared plans dir not present: /Users/bayesian/.dontpanic-f010-e2e-74843/fixture-project/docs/plans (parent dir also missing)",
      "remediation": "create the directory or update plans_dir in /Users/bayesian/.dontpanic-f010-e2e-74843/fixture-project/.dontpanic/dontpanic.json",
      "warn": true
    },
    {
      "name": "project:fixture-project:agents",
      "ok": true,
      "message": "no per-project agent overrides (falls through to global / hardcoded)",
      "remediation": "",
      "warn": false
    },
    {
      "name": "project:fixture-project:gates",
      "ok": true,
      "message": "no per-project human_gates override",
      "remediation": "",
      "warn": false
    },
    {
      "name": "project:fixture-project:roles",
      "ok": true,
      "message": "no project roles.* overrides declared",
      "remediation": "",
      "warn": false
    },
    {
      "name": "config-home",
      "ok": true,
      "message": "canonical (~/.dontpanic) and legacy (~/.jarvis) homes are reconciled",
      "remediation": "",
      "warn": false
    },
    {
      "name": "validate-plans-strict",
      "ok": true,
      "message": "109 locked plan(s) under docs/plans validate clean against plan.schema.json",
      "remediation": "",
      "warn": false,
      "details": [
        {
          "plan_id": "2026-04-19-001-infra-cross-agent-orchestration",
          "path": "plans/2026-04-19-001-infra-cross-agent-orchestration/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-04-25-001-infra-jarvis-firebase-bootstrap",
          "path": "plans/2026-04-25-001-infra-jarvis-firebase-bootstrap/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-04-25-002-infra-trivial-orchestration-test",
          "path": "plans/2026-04-25-002-infra-trivial-orchestration-test/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-04-26-006-infra-f023-ec5-evidence",
          "path": "plans/2026-04-26-006-infra-f023-ec5-evidence/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-04-28-001-infra-financial-observability",
          "path": "plans/2026-04-28-001-infra-financial-observability/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-04-29-001-feat-changelog-skill",
          "path": "plans/2026-04-29-001-feat-changelog-skill/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-04-29-002-feat-agent-permission-wiring",
          "path": "plans/2026-04-29-002-feat-agent-permission-wiring/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-04-29-003-fix-f008-phased-gates",
          "path": "plans/2026-04-29-003-fix-f008-phased-gates/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-04-29-004-fix-f006-budget-semantics",
          "path": "plans/2026-04-29-004-fix-f006-budget-semantics/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-04-30-001-fix-quota-tracker-vendor-native",
          "path": "plans/2026-04-30-001-fix-quota-tracker-vendor-native/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-01-001-feat-onboarding-ux",
          "path": "plans/2026-05-01-001-feat-onboarding-ux/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-01-002-feat-discord-notification-sink",
          "path": "plans/2026-05-01-002-feat-discord-notification-sink/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-01-003-feat-security-baseline",
          "path": "plans/2026-05-01-003-feat-security-baseline/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-01-004-feat-patch-completeness-gate",
          "path": "plans/2026-05-01-004-feat-patch-completeness-gate/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-01-005-feat-target-context-platform-fix",
          "path": "plans/2026-05-01-005-feat-target-context-platform-fix/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-02-001-feat-resume-gate-discipline",
          "path": "plans/2026-05-02-001-feat-resume-gate-discipline/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-02-002-fix-audit-envelope-filename",
          "path": "plans/2026-05-02-002-fix-audit-envelope-filename/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-02-003-feat-nested-orchestration-v1",
          "path": "plans/2026-05-02-003-feat-nested-orchestration-v1/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-02-004-fix-diminishing-returns-signature-based",
          "path": "plans/2026-05-02-004-fix-diminishing-returns-signature-based/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-03-001-feat-global-install-project-registry",
          "path": "plans/2026-05-03-001-feat-global-install-project-registry/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-03-002-infra-personal-openclaw-axiom-jarvis",
          "path": "plans/2026-05-03-002-infra-personal-openclaw-axiom-jarvis/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-03-003-feat-agent-access-manifest-thin-mcp",
          "path": "plans/2026-05-03-003-feat-agent-access-manifest-thin-mcp/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-04-001-refactor-canonical-dontpanic-module",
          "path": "plans/2026-05-04-001-refactor-canonical-dontpanic-module/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-04-002-fix-supervisor-lifecycle-staged-gates",
          "path": "plans/2026-05-04-002-fix-supervisor-lifecycle-staged-gates/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-04-003-fix-subprocess-timeout-envelope-durability",
          "path": "plans/2026-05-04-003-fix-subprocess-timeout-envelope-durability/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-04-004-fix-ec5-classifier-purity",
          "path": "plans/2026-05-04-004-fix-ec5-classifier-purity/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-05-001-fix-plan-validator-audit-auxiliary-json",
          "path": "plans/2026-05-05-001-fix-plan-validator-audit-auxiliary-json/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-05-002-feat-goal-governance-nested-orchestration-config",
          "path": "plans/2026-05-05-002-feat-goal-governance-nested-orchestration-config/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-05-003-feat-objective-contract-and-sufficiency-audit",
          "path": "plans/2026-05-05-003-feat-objective-contract-and-sufficiency-audit/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-06-001-infra-runtime-evidence-harness",
          "path": "plans/2026-05-06-001-infra-runtime-evidence-harness/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-06-002-feat-post-impl-completion-audit",
          "path": "plans/2026-05-06-002-feat-post-impl-completion-audit/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-06-003-fix-live-cross-vendor-goal-audit-dogfood",
          "path": "plans/2026-05-06-003-fix-live-cross-vendor-goal-audit-dogfood/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-07-001-fix-completion-dispatch-codex-stream-parser",
          "path": "plans/2026-05-07-001-fix-completion-dispatch-codex-stream-parser/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-07-002-fix-cross-vendor-dogfood-fixture-runtime-artifacts",
          "path": "plans/2026-05-07-002-fix-cross-vendor-dogfood-fixture-runtime-artifacts/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-08-001-feat-ruff-s-remediation",
          "path": "plans/2026-05-08-001-feat-ruff-s-remediation/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-08-002-feat-skill-applicability-v0",
          "path": "plans/2026-05-08-002-feat-skill-applicability-v0/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-08-003-fix-harness-volley-frictions",
          "path": "plans/2026-05-08-003-fix-harness-volley-frictions/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-09-001-fix-conftest-global-config-isolation",
          "path": "plans/2026-05-09-001-fix-conftest-global-config-isolation/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-09-002-fix-verdict-status-environmental-frictions",
          "path": "plans/2026-05-09-002-fix-verdict-status-environmental-frictions/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-09-003-feat-state-projection-v0",
          "path": "plans/2026-05-09-003-feat-state-projection-v0/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-09-004-feat-firebase-dashboard-adapter-v0",
          "path": "plans/2026-05-09-004-feat-firebase-dashboard-adapter-v0/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-10-001-feat-printing-press-adapter-skill",
          "path": "plans/2026-05-10-001-feat-printing-press-adapter-skill/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-11-001-infra-state-projection-adapters-meta",
          "path": "plans/2026-05-11-001-infra-state-projection-adapters-meta/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-11-002-fix-harness-frictions-v3",
          "path": "plans/2026-05-11-002-fix-harness-frictions-v3/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-12-001-fix-harness-frictions-v4",
          "path": "plans/2026-05-12-001-fix-harness-frictions-v4/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-12-002-fix-harness-frictions-v4-1",
          "path": "plans/2026-05-12-002-fix-harness-frictions-v4-1/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-19-002-feat-install-ux-hardening-v0",
          "path": "plans/2026-05-19-002-feat-install-ux-hardening-v0/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-19-003-fix-plan-schema-orchestration-fields",
          "path": "plans/2026-05-19-003-fix-plan-schema-orchestration-fields/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-19-004-feat-architecture-map-with-drift-v0",
          "path": "plans/2026-05-19-004-feat-architecture-map-with-drift-v0/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-19-005-feat-dogfood-showcase-artifacts-v0",
          "path": "plans/2026-05-19-005-feat-dogfood-showcase-artifacts-v0/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-20-001-infra-external-integrations-bridge-v0",
          "path": "plans/2026-05-20-001-infra-external-integrations-bridge-v0/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-21-001-feat-capability-manifest-consumers-v0",
          "path": "plans/2026-05-21-001-feat-capability-manifest-consumers-v0/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-22-001-infra-external-capability-operations-roadmap-v0",
          "path": "plans/2026-05-22-001-infra-external-capability-operations-roadmap-v0/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-22-002-feat-capability-status-v0",
          "path": "plans/2026-05-22-002-feat-capability-status-v0/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-22-003-feat-capability-center-v1",
          "path": "plans/2026-05-22-003-feat-capability-center-v1/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-22-004-feat-capability-guided-setup-v2",
          "path": "plans/2026-05-22-004-feat-capability-guided-setup-v2/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-23-001-infra-install-lifecycle-reconciliation-roadmap-v0",
          "path": "plans/2026-05-23-001-infra-install-lifecycle-reconciliation-roadmap-v0/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-23-002-feat-install-reconcile-foundation-v0",
          "path": "plans/2026-05-23-002-feat-install-reconcile-foundation-v0/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-23-003-infra-visual-operating-console-roadmap-v0",
          "path": "plans/2026-05-23-003-infra-visual-operating-console-roadmap-v0/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-23-004-feat-operator-console-v0",
          "path": "plans/2026-05-23-004-feat-operator-console-v0/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-23-005-feat-dashboard-project-selector-v0",
          "path": "plans/2026-05-23-005-feat-dashboard-project-selector-v0/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-23-006-infra-planning-intelligence-roadmap-v0",
          "path": "plans/2026-05-23-006-infra-planning-intelligence-roadmap-v0/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-23-007-feat-plan-intake-readiness-v0",
          "path": "plans/2026-05-23-007-feat-plan-intake-readiness-v0/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-24-001-feat-dashboard-value-language-ia-v0",
          "path": "plans/2026-05-24-001-feat-dashboard-value-language-ia-v0/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-24-002-feat-dashboard-architecture-explorer-v1",
          "path": "plans/2026-05-24-002-feat-dashboard-architecture-explorer-v1/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-24-003-infra-dashboard-platform-roadmap-v1",
          "path": "plans/2026-05-24-003-infra-dashboard-platform-roadmap-v1/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-24-004-feat-event-messaging-v1",
          "path": "plans/2026-05-24-004-feat-event-messaging-v1/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-30-001-feat-universal-agent-repo-onboarding-v0",
          "path": "plans/2026-05-30-001-feat-universal-agent-repo-onboarding-v0/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-30-002-fix-orchestrator-convergence-bugs",
          "path": "plans/2026-05-30-002-fix-orchestrator-convergence-bugs/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-06-01-001-feat-plan-review-scope-validation",
          "path": "plans/2026-06-01-001-feat-plan-review-scope-validation/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-06-02-001-feat-control-plane-action-spine",
          "path": "plans/2026-06-02-001-feat-control-plane-action-spine/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-06-02-002-fix-orchestrator-convergence-and-close-friction",
          "path": "plans/2026-06-02-002-fix-orchestrator-convergence-and-close-friction/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-06-03-001-feat-agent-command-surface-hardening",
          "path": "plans/2026-06-03-001-feat-agent-command-surface-hardening/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-06-04-001-feat-ledger-reconciliation-operator-actions",
          "path": "plans/2026-06-04-001-feat-ledger-reconciliation-operator-actions/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-06-04-003-feat-integration-operator-actions",
          "path": "plans/2026-06-04-003-feat-integration-operator-actions/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-06-04-004-feat-dashboard-state-fidelity",
          "path": "plans/2026-06-04-004-feat-dashboard-state-fidelity/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-06-04-005-feat-render-truth-scope-contract",
          "path": "plans/2026-06-04-005-feat-render-truth-scope-contract/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-06-04-006-feat-dashboard-safe-repair-runner",
          "path": "plans/2026-06-04-006-feat-dashboard-safe-repair-runner/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-06-05-001-fix-capability-card-setup-clarity",
          "path": "plans/2026-06-05-001-fix-capability-card-setup-clarity/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-06-05-002-feat-dashboard-real-state-qa-contract-v0",
          "path": "plans/2026-06-05-002-feat-dashboard-real-state-qa-contract-v0/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-06-05-003-feat-dashboard-design-system-v0",
          "path": "plans/2026-06-05-003-feat-dashboard-design-system-v0/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-06-05-004-feat-applicable-conventions-disposition-gate-v0",
          "path": "plans/2026-06-05-004-feat-applicable-conventions-disposition-gate-v0/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-06-06-001-feat-operator-triage-surface-v0",
          "path": "plans/2026-06-06-001-feat-operator-triage-surface-v0/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-06-06-002-feat-governed-gui-action-channel-v1",
          "path": "plans/2026-06-06-002-feat-governed-gui-action-channel-v1/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-06-06-003-feat-architecture-auto-refresh",
          "path": "plans/2026-06-06-003-feat-architecture-auto-refresh/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-06-06-004-feat-operator-console-redesign",
          "path": "plans/2026-06-06-004-feat-operator-console-redesign/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-06-06-005-feat-cockpit-default-integration",
          "path": "plans/2026-06-06-005-feat-cockpit-default-integration/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-06-06-007-feat-architecture-render",
          "path": "plans/2026-06-06-007-feat-architecture-render/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-06-07-001-feat-architecture-evidence-contract-v0",
          "path": "plans/2026-06-07-001-feat-architecture-evidence-contract-v0/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-06-07-002-fix-plan-review-introduces-vocabulary",
          "path": "plans/2026-06-07-002-fix-plan-review-introduces-vocabulary/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-06-07-003-feat-operator-console-008-chrome-theming-state",
          "path": "plans/2026-06-07-003-feat-operator-console-008-chrome-theming-state/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-06-08-001-feat-architecture-intent-extractor-plan-b",
          "path": "plans/2026-06-08-001-feat-architecture-intent-extractor-plan-b/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-06-08-002-feat-architecture-js-extractor-plan-c",
          "path": "plans/2026-06-08-002-feat-architecture-js-extractor-plan-c/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-06-08-003-fix-audit-findings",
          "path": "plans/2026-06-08-003-fix-audit-findings/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-06-08-004-feat-architecture-reconciler-ui-plan-d",
          "path": "plans/2026-06-08-004-feat-architecture-reconciler-ui-plan-d/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-06-08-005-feat-architecture-ts-extractor-plan-c2",
          "path": "plans/2026-06-08-005-feat-architecture-ts-extractor-plan-c2/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-06-08-006-fix-preimpl-governance-loop",
          "path": "plans/2026-06-08-006-fix-preimpl-governance-loop/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-06-09-001-feat-architecture-c0-weak-graph",
          "path": "plans/2026-06-09-001-feat-architecture-c0-weak-graph/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-06-09-002-feat-sufficiency-gate-convergence",
          "path": "plans/2026-06-09-002-feat-sufficiency-gate-convergence/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-06-10-001-feat-convergence-policy-v1-1",
          "path": "plans/2026-06-10-001-feat-convergence-policy-v1-1/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-06-10-002-feat-worktree-isolation-v0",
          "path": "plans/2026-06-10-002-feat-worktree-isolation-v0/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-06-11-001-feat-worktree-guard-hardening",
          "path": "plans/2026-06-11-001-feat-worktree-guard-hardening/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-06-12-001-fix-audit-evidence-writer-hygiene",
          "path": "plans/2026-06-12-001-fix-audit-evidence-writer-hygiene/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-06-14-001-feat-agent-channel-interop-v0",
          "path": "plans/2026-06-14-001-feat-agent-channel-interop-v0/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-06-14-002-feat-experience-readiness-gate-v0",
          "path": "plans/2026-06-14-002-feat-experience-readiness-gate-v0/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-06-15-001-feat-experience-readiness-evidence-typing-v0",
          "path": "plans/2026-06-15-001-feat-experience-readiness-evidence-typing-v0/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-06-15-002-feat-experience-readiness-degraded-honesty-v0",
          "path": "plans/2026-06-15-002-feat-experience-readiness-degraded-honesty-v0/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-06-17-001-feat-canonical-repo-discovery",
          "path": "plans/2026-06-17-001-feat-canonical-repo-discovery/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-06-21-001-feat-upgrade-readiness-doctor",
          "path": "plans/2026-06-21-001-feat-upgrade-readiness-doctor/plan.md",
          "status": "clean"
        }
      ]
    },
    {
      "name": "architecture-drift",
      "ok": true,
      "message": "stale_major \u2014 407/771 files differ (52.8%): added=335 removed=0 modified=72",
      "remediation": "python -m dontpanic_orchestrate architecture regen",
      "warn": true,
      "details": [
        {
          "state": "stale_major",
          "architecture_path": "/Users/bayesian/Documents/GitHub/DontPanic/docs/architecture/architecture.json",
          "stored_fingerprint": "b3dc608f06b214efadeb9b17c1dba1f212100a4f606a7aef3019c39b08d41306",
          "current_fingerprint": "3b152cb29e0407af6fd93a0c0420e3001ba957997369e42864e0de8f96f8a68e",
          "changed_files": {
            "added": [
              "claude/shared/schemas/v1.0/models/experience_readiness.py",
              "claude/shared/schemas/v1.0/models/upgrade_releases_model.py",
              "claude/shared/schemas/v1.0/upgrade-releases.schema.json",
              "docs/plans/2026-05-30-002-fix-orchestrator-convergence-bugs/features.json",
              "docs/plans/2026-05-30-002-fix-orchestrator-convergence-bugs/plan.md",
              "docs/plans/2026-06-01-001-feat-plan-review-scope-validation/features.json",
              "docs/plans/2026-06-01-001-feat-plan-review-scope-validation/plan.md",
              "docs/plans/2026-06-02-001-feat-control-plane-action-spine/features.json",
              "docs/plans/2026-06-02-001-feat-control-plane-action-spine/plan.md",
              "docs/plans/2026-06-02-002-fix-orchestrator-convergence-and-close-friction/features.json",
              "docs/plans/2026-06-02-002-fix-orchestrator-convergence-and-close-friction/plan.md",
              "docs/plans/2026-06-03-001-feat-agent-command-surface-hardening/features.json",
              "docs/plans/2026-06-03-001-feat-agent-command-surface-hardening/plan.md",
              "docs/plans/2026-06-04-001-feat-ledger-reconciliation-operator-actions/features.json",
              "docs/plans/2026-06-04-001-feat-ledger-reconciliation-operator-actions/plan.md",
              "docs/plans/2026-06-04-002-feat-local-harness-adapter-runtime/features.json",
              "docs/plans/2026-06-04-002-feat-local-harness-adapter-runtime/plan.md",
              "docs/plans/2026-06-04-003-feat-integration-operator-actions/features.json",
              "docs/plans/2026-06-04-003-feat-integration-operator-actions/plan.md",
              "docs/plans/2026-06-04-004-feat-dashboard-state-fidelity/features.json",
              "\u2026 +315 more"
            ],
            "removed": [],
            "modified": [
              "claude/shared/VERSION",
              "claude/shared/schemas/v1.0/capability.schema.json",
              "claude/shared/schemas/v1.0/models/features_model.py",
              "claude/shared/schemas/v1.0/models/objective_contract_model.py",
              "docs/plans/2026-04-19-001-infra-cross-agent-orchestration/plan.md",
              "docs/plans/2026-04-29-001-feat-changelog-skill/features.json",
              "docs/plans/2026-04-29-001-feat-changelog-skill/plan.md",
              "docs/plans/2026-04-29-004-fix-f006-budget-semantics/plan.md",
              "docs/plans/2026-05-03-002-infra-personal-openclaw-axiom-jarvis/plan.md",
              "docs/plans/2026-05-24-001-feat-dashboard-value-language-ia-v0/plan.md",
              "docs/plans/2026-05-30-001-feat-universal-agent-repo-onboarding-v0/features.json",
              "docs/plans/2026-05-30-001-feat-universal-agent-repo-onboarding-v0/plan.md",
              "scripts/dontpanic_orchestrate/active_supervisors.py",
              "scripts/dontpanic_orchestrate/agent_brief.py",
              "scripts/dontpanic_orchestrate/agent_manifest.py",
              "scripts/dontpanic_orchestrate/agent_surface.py",
              "scripts/dontpanic_orchestrate/architecture_view_state.py",
              "scripts/dontpanic_orchestrate/capabilities.py",
              "scripts/dontpanic_orchestrate/circuit_breakers.py",
              "scripts/dontpanic_orchestrate/cli.py",
              "\u2026 +52 more"
            ]
          },
          "changed_files_list": [
            "added: claude/shared/schemas/v1.0/models/experience_readiness.py",
            "added: claude/shared/schemas/v1.0/models/upgrade_releases_model.py",
            "added: claude/shared/schemas/v1.0/upgrade-releases.schema.json",
            "added: docs/plans/2026-05-30-002-fix-orchestrator-convergence-bugs/features.json",
            "added: docs/plans/2026-05-30-002-fix-orchestrator-convergence-bugs/plan.md",
            "added: docs/plans/2026-06-01-001-feat-plan-review-scope-validation/features.json",
            "added: docs/plans/2026-06-01-001-feat-plan-review-scope-validation/plan.md",
            "added: docs/plans/2026-06-02-001-feat-control-plane-action-spine/features.json",
            "added: docs/plans/2026-06-02-001-feat-control-plane-action-spine/plan.md",
            "added: docs/plans/2026-06-02-002-fix-orchestrator-convergence-and-close-friction/features.json",
            "added: docs/plans/2026-06-02-002-fix-orchestrator-convergence-and-close-friction/plan.md",
            "added: docs/plans/2026-06-03-001-feat-agent-command-surface-hardening/features.json",
            "added: docs/plans/2026-06-03-001-feat-agent-command-surface-hardening/plan.md",
            "added: docs/plans/2026-06-04-001-feat-ledger-reconciliation-operator-actions/features.json",
            "added: docs/plans/2026-06-04-001-feat-ledger-reconciliation-operator-actions/plan.md",
            "added: docs/plans/2026-06-04-002-feat-local-harness-adapter-runtime/features.json",
            "added: docs/plans/2026-06-04-002-feat-local-harness-adapter-runtime/plan.md",
            "added: docs/plans/2026-06-04-003-feat-integration-operator-actions/features.json",
            "added: docs/plans/2026-06-04-003-feat-integration-operator-actions/plan.md",
            "added: docs/plans/2026-06-04-004-feat-dashboard-state-fidelity/features.json",
            "added: \u2026 +315 more",
            "modified: claude/shared/VERSION",
            "modified: claude/shared/schemas/v1.0/capability.schema.json",
            "modified: claude/shared/schemas/v1.0/models/features_model.py",
            "modified: claude/shared/schemas/v1.0/models/objective_contract_model.py",
            "modified: docs/plans/2026-04-19-001-infra-cross-agent-orchestration/plan.md",
            "modified: docs/plans/2026-04-29-001-feat-changelog-skill/features.json",
            "modified: docs/plans/2026-04-29-001-feat-changelog-skill/plan.md",
            "modified: docs/plans/2026-04-29-004-fix-f006-budget-semantics/plan.md",
            "modified: docs/plans/2026-05-03-002-infra-personal-openclaw-axiom-jarvis/plan.md",
            "modified: docs/plans/2026-05-24-001-feat-dashboard-value-language-ia-v0/plan.md",
            "modified: docs/plans/2026-05-30-001-feat-universal-agent-repo-onboarding-v0/features.json",
            "modified: docs/plans/2026-05-30-001-feat-universal-agent-repo-onboarding-v0/plan.md",
            "modified: scripts/dontpanic_orchestrate/active_supervisors.py",
            "modified: scripts/dontpanic_orchestrate/agent_brief.py",
            "modified: scripts/dontpanic_orchestrate/agent_manifest.py",
            "modified: scripts/dontpanic_orchestrate/agent_surface.py",
            "modified: scripts/dontpanic_orchestrate/architecture_view_state.py",
            "modified: scripts/dontpanic_orchestrate/capabilities.py",
            "modified: scripts/dontpanic_orchestrate/circuit_breakers.py",
            "modified: scripts/dontpanic_orchestrate/cli.py",
            "modified: \u2026 +52 more"
          ],
          "changed_files_total": 407,
          "unchanged_files": 364,
          "files_count_current": 771,
          "files_count_stored": 436,
          "drift_pct": 52.79,
          "missing_required": [],
          "recommendation": "major drift (\u22655% files changed). Run `python -m dontpanic_orchestrate architecture regen` before downstream consumers (Plan 4.5 `dontpanic new`, F004 supervisor regen hook) read a stale snapshot."
        }
      ]
    },
    {
      "name": "dashboard-files",
      "ok": true,
      "message": "static dashboard present at dashboard/index.html",
      "remediation": "",
      "warn": false
    },
    {
      "name": "dashboard-cache",
      "ok": true,
      "message": "what-now cache missing at /Users/bayesian/.dontpanic-f010-e2e-74843/home/dashboard/what-now.json",
      "remediation": "run: dontpanic dashboard build",
      "warn": true
    },
    {
      "name": "dashboard-state",
      "ok": true,
      "message": "dashboard/state has state-snapshot.json + what-now.json",
      "remediation": "",
      "warn": false
    },
    {
      "name": "skill-rubrics",
      "ok": true,
      "message": "5 high-value skill(s) lack an invocation rubric (advisory \u2014 core use is not blocked): agent-browser, cost-model, eval-harness, pr-reviewer, printing-press-adapter",
      "remediation": "run: dontpanic skills rubric --suggest agent-browser; dontpanic skills rubric --suggest cost-model; dontpanic skills rubric --suggest eval-harness; dontpanic skills rubric --suggest pr-reviewer; dontpanic skills rubric --suggest printing-press-adapter",
      "warn": true
    },
    {
      "name": "upgrade-readiness",
      "ok": true,
      "message": "1 required + 0 advisory upgrade action(s) pending",
      "remediation": "run `dontpanic doctor --upgrade` to see required actions + their commands (required actions clear only when their probe passes)",
      "warn": true
    }
  ],
  "passed": 31,
  "failed": 0,
  "warnings": 5,
  "architecture_drift": {
    "state": "stale_major",
    "changed_files": [
      "added: claude/shared/schemas/v1.0/models/experience_readiness.py",
      "added: claude/shared/schemas/v1.0/models/upgrade_releases_model.py",
      "added: claude/shared/schemas/v1.0/upgrade-releases.schema.json",
      "added: docs/plans/2026-05-30-002-fix-orchestrator-convergence-bugs/features.json",
      "added: docs/plans/2026-05-30-002-fix-orchestrator-convergence-bugs/plan.md",
      "added: docs/plans/2026-06-01-001-feat-plan-review-scope-validation/features.json",
      "added: docs/plans/2026-06-01-001-feat-plan-review-scope-validation/plan.md",
      "added: docs/plans/2026-06-02-001-feat-control-plane-action-spine/features.json",
      "added: docs/plans/2026-06-02-001-feat-control-plane-action-spine/plan.md",
      "added: docs/plans/2026-06-02-002-fix-orchestrator-convergence-and-close-friction/features.json",
      "added: docs/plans/2026-06-02-002-fix-orchestrator-convergence-and-close-friction/plan.md",
      "added: docs/plans/2026-06-03-001-feat-agent-command-surface-hardening/features.json",
      "added: docs/plans/2026-06-03-001-feat-agent-command-surface-hardening/plan.md",
      "added: docs/plans/2026-06-04-001-feat-ledger-reconciliation-operator-actions/features.json",
      "added: docs/plans/2026-06-04-001-feat-ledger-reconciliation-operator-actions/plan.md",
      "added: docs/plans/2026-06-04-002-feat-local-harness-adapter-runtime/features.json",
      "added: docs/plans/2026-06-04-002-feat-local-harness-adapter-runtime/plan.md",
      "added: docs/plans/2026-06-04-003-feat-integration-operator-actions/features.json",
      "added: docs/plans/2026-06-04-003-feat-integration-operator-actions/plan.md",
      "added: docs/plans/2026-06-04-004-feat-dashboard-state-fidelity/features.json",
      "added: \u2026 +315 more",
      "modified: claude/shared/VERSION",
      "modified: claude/shared/schemas/v1.0/capability.schema.json",
      "modified: claude/shared/schemas/v1.0/models/features_model.py",
      "modified: claude/shared/schemas/v1.0/models/objective_contract_model.py",
      "modified: docs/plans/2026-04-19-001-infra-cross-agent-orchestration/plan.md",
      "modified: docs/plans/2026-04-29-001-feat-changelog-skill/features.json",
      "modified: docs/plans/2026-04-29-001-feat-changelog-skill/plan.md",
      "modified: docs/plans/2026-04-29-004-fix-f006-budget-semantics/plan.md",
      "modified: docs/plans/2026-05-03-002-infra-personal-openclaw-axiom-jarvis/plan.md",
      "modified: docs/plans/2026-05-24-001-feat-dashboard-value-language-ia-v0/plan.md",
      "modified: docs/plans/2026-05-30-001-feat-universal-agent-repo-onboarding-v0/features.json",
      "modified: docs/plans/2026-05-30-001-feat-universal-agent-repo-onboarding-v0/plan.md",
      "modified: scripts/dontpanic_orchestrate/active_supervisors.py",
      "modified: scripts/dontpanic_orchestrate/agent_brief.py",
      "modified: scripts/dontpanic_orchestrate/agent_manifest.py",
      "modified: scripts/dontpanic_orchestrate/agent_surface.py",
      "modified: scripts/dontpanic_orchestrate/architecture_view_state.py",
      "modified: scripts/dontpanic_orchestrate/capabilities.py",
      "modified: scripts/dontpanic_orchestrate/circuit_breakers.py",
      "modified: scripts/dontpanic_orchestrate/cli.py",
      "modified: \u2026 +52 more"
    ],
    "changed_files_categorized": {
      "added": [
        "claude/shared/schemas/v1.0/models/experience_readiness.py",
        "claude/shared/schemas/v1.0/models/upgrade_releases_model.py",
        "claude/shared/schemas/v1.0/upgrade-releases.schema.json",
        "docs/plans/2026-05-30-002-fix-orchestrator-convergence-bugs/features.json",
        "docs/plans/2026-05-30-002-fix-orchestrator-convergence-bugs/plan.md",
        "docs/plans/2026-06-01-001-feat-plan-review-scope-validation/features.json",
        "docs/plans/2026-06-01-001-feat-plan-review-scope-validation/plan.md",
        "docs/plans/2026-06-02-001-feat-control-plane-action-spine/features.json",
        "docs/plans/2026-06-02-001-feat-control-plane-action-spine/plan.md",
        "docs/plans/2026-06-02-002-fix-orchestrator-convergence-and-close-friction/features.json",
        "docs/plans/2026-06-02-002-fix-orchestrator-convergence-and-close-friction/plan.md",
        "docs/plans/2026-06-03-001-feat-agent-command-surface-hardening/features.json",
        "docs/plans/2026-06-03-001-feat-agent-command-surface-hardening/plan.md",
        "docs/plans/2026-06-04-001-feat-ledger-reconciliation-operator-actions/features.json",
        "docs/plans/2026-06-04-001-feat-ledger-reconciliation-operator-actions/plan.md",
        "docs/plans/2026-06-04-002-feat-local-harness-adapter-runtime/features.json",
        "docs/plans/2026-06-04-002-feat-local-harness-adapter-runtime/plan.md",
        "docs/plans/2026-06-04-003-feat-integration-operator-actions/features.json",
        "docs/plans/2026-06-04-003-feat-integration-operator-actions/plan.md",
        "docs/plans/2026-06-04-004-feat-dashboard-state-fidelity/features.json",
        "\u2026 +315 more"
      ],
      "removed": [],
      "modified": [
        "claude/shared/VERSION",
        "claude/shared/schemas/v1.0/capability.schema.json",
        "claude/shared/schemas/v1.0/models/features_model.py",
        "claude/shared/schemas/v1.0/models/objective_contract_model.py",
        "docs/plans/2026-04-19-001-infra-cross-agent-orchestration/plan.md",
        "docs/plans/2026-04-29-001-feat-changelog-skill/features.json",
        "docs/plans/2026-04-29-001-feat-changelog-skill/plan.md",
        "docs/plans/2026-04-29-004-fix-f006-budget-semantics/plan.md",
        "docs/plans/2026-05-03-002-infra-personal-openclaw-axiom-jarvis/plan.md",
        "docs/plans/2026-05-24-001-feat-dashboard-value-language-ia-v0/plan.md",
        "docs/plans/2026-05-30-001-feat-universal-agent-repo-onboarding-v0/features.json",
        "docs/plans/2026-05-30-001-feat-universal-agent-repo-onboarding-v0/plan.md",
        "scripts/dontpanic_orchestrate/active_supervisors.py",
        "scripts/dontpanic_orchestrate/agent_brief.py",
        "scripts/dontpanic_orchestrate/agent_manifest.py",
        "scripts/dontpanic_orchestrate/agent_surface.py",
        "scripts/dontpanic_orchestrate/architecture_view_state.py",
        "scripts/dontpanic_orchestrate/capabilities.py",
        "scripts/dontpanic_orchestrate/circuit_breakers.py",
        "scripts/dontpanic_orchestrate/cli.py",
        "\u2026 +52 more"
      ]
    },
    "changed_files_total": 407,
    "unchanged_files": 364,
    "missing_required": [],
    "recommendation": "major drift (\u22655% files changed). Run `python -m dontpanic_orchestrate architecture regen` before downstream consumers (Plan 4.5 `dontpanic new`, F004 supervisor regen hook) read a stale snapshot.",
    "ok": true,
    "warn": true
  }
}

## 2. `dontpanic doctor --upgrade --json` (before)
$ python -m dontpanic_orchestrate doctor --upgrade --json
rc=0
stdout:
{
  "summary": {
    "installed_commit": "unknown",
    "latest_release_id": "2026-06-17-001-canonical-discovery",
    "last_seen_release": null,
    "last_seen_commit": null,
    "pending_required": 1,
    "pending_advisory": 0,
    "update_state": "required_pending",
    "marker_state": "absent",
    "upstream": {
      "fetched_upstream_commit": null,
      "upstream_status": "unknown",
      "remediation": "Upstream position unknown: not a git checkout, so the newest DontPanic cannot be compared here.",
      "upstream_ref": null
    }
  },
  "required": [
    {
      "item_id": "upgrade:2026-06-17-001-canonical-discovery:backfill-canonical-discovery",
      "release_id": "2026-06-17-001-canonical-discovery",
      "action_id": "backfill-canonical-discovery",
      "kind": "required",
      "severity": "recommended",
      "title": "Backfill canonical-repo discovery for tracked projects",
      "detail": "Canonical-repo discovery records the durable project identity at invocation time. Projects tracked before this release have no canonical_repo until a one-time backfill reconciles their historical invocation-ledger records.",
      "applies": true,
      "applies_when_key": "has_tracked_projects",
      "applies_detail": "1 tracked project(s) in registry",
      "applies_error": false,
      "status_probe_key": "canonical_discovery_registered_active",
      "commands": [
        {
          "label": "preview",
          "command": "dontpanic projects backfill-canonical --dry-run",
          "description": "Preview the backfill: shows which tracked projects would gain a canonical_repo, mutating nothing."
        },
        {
          "label": "apply",
          "command": "dontpanic projects backfill-canonical",
          "description": "Apply the one-time backfill, writing canonical_repo for confirmed historical records."
        },
        {
          "label": "verify",
          "command": "dontpanic projects discover --json",
          "description": "Verify discovery now reports the canonical projects."
        }
      ],
      "success_message": "Tracked projects are reconciled into canonical-repo discovery; `dontpanic projects discover --json` reports them.",
      "failure_message": "Canonical-repo discovery backfill is still pending: tracked projects have no canonical_repo yet.",
      "human_next_step": "Run the preview, then apply the backfill, then re-run `dontpanic doctor --upgrade` to confirm the probe clears.",
      "docs_url": "CHANGELOG.md",
      "introduced_commands": [
        "dontpanic projects discover",
        "dontpanic projects backfill-canonical"
      ],
      "satisfied": false,
      "probe_detail": "DontPanic is registered but stale (no recent qualifying usage); not registered_active",
      "probe_error": false,
      "probe_evidence_uri": null
    }
  ],
  "advisory": [],
  "migration_status": [
    {
      "release_id": "2026-06-17-001-canonical-discovery",
      "action_id": "backfill-canonical-discovery",
      "applies": true,
      "status_probe_key": "canonical_discovery_registered_active",
      "satisfied": false,
      "state": "pending",
      "detail": "DontPanic is registered but stale (no recent qualifying usage); not registered_active",
      "evidence_uri": null
    }
  ]
}

extracted apply command:  'dontpanic projects backfill-canonical'
extracted verify command: 'dontpanic projects discover --json'

## 2b. VERIFY-alone before any apply (must NOT satisfy)
$ python -m dontpanic_orchestrate projects discover --json  (pre-apply)
rc=0
stdout:
{
  "used_unregistered": [],
  "registered_active": [],
  "registered_stale": [
    {
      "canonical_repo_key": "21bb34ac465755aa",
      "registry_name": "fixture-project",
      "path_display": "/Users/<operator>/.dontpanic-f010-e2e-74843/fixture-project",
      "observed_count": 0,
      "last_seen": null,
      "registry_conflict": false,
      "conflicting_registry_names": []
    }
  ],
  "registered_path_missing": [],
  "registered_unresolved": []
}
$ python -m dontpanic_orchestrate doctor --upgrade --json  (after verify-alone)
rc=0
stdout:
{
  "summary": {
    "installed_commit": "unknown",
    "latest_release_id": "2026-06-17-001-canonical-discovery",
    "last_seen_release": null,
    "last_seen_commit": null,
    "pending_required": 1,
    "pending_advisory": 0,
    "update_state": "required_pending",
    "marker_state": "absent",
    "upstream": {
      "fetched_upstream_commit": null,
      "upstream_status": "unknown",
      "remediation": "Upstream position unknown: not a git checkout, so the newest DontPanic cannot be compared here.",
      "upstream_ref": null
    }
  },
  "required": [
    {
      "item_id": "upgrade:2026-06-17-001-canonical-discovery:backfill-canonical-discovery",
      "release_id": "2026-06-17-001-canonical-discovery",
      "action_id": "backfill-canonical-discovery",
      "kind": "required",
      "severity": "recommended",
      "title": "Backfill canonical-repo discovery for tracked projects",
      "detail": "Canonical-repo discovery records the durable project identity at invocation time. Projects tracked before this release have no canonical_repo until a one-time backfill reconciles their historical invocation-ledger records.",
      "applies": true,
      "applies_when_key": "has_tracked_projects",
      "applies_detail": "1 tracked project(s) in registry",
      "applies_error": false,
      "status_probe_key": "canonical_discovery_registered_active",
      "commands": [
        {
          "label": "preview",
          "command": "dontpanic projects backfill-canonical --dry-run",
          "description": "Preview the backfill: shows which tracked projects would gain a canonical_repo, mutating nothing."
        },
        {
          "label": "apply",
          "command": "dontpanic projects backfill-canonical",
          "description": "Apply the one-time backfill, writing canonical_repo for confirmed historical records."
        },
        {
          "label": "verify",
          "command": "dontpanic projects discover --json",
          "description": "Verify discovery now reports the canonical projects."
        }
      ],
      "success_message": "Tracked projects are reconciled into canonical-repo discovery; `dontpanic projects discover --json` reports them.",
      "failure_message": "Canonical-repo discovery backfill is still pending: tracked projects have no canonical_repo yet.",
      "human_next_step": "Run the preview, then apply the backfill, then re-run `dontpanic doctor --upgrade` to confirm the probe clears.",
      "docs_url": "CHANGELOG.md",
      "introduced_commands": [
        "dontpanic projects discover",
        "dontpanic projects backfill-canonical"
      ],
      "satisfied": false,
      "probe_detail": "DontPanic is registered but stale (no recent qualifying usage); not registered_active",
      "probe_error": false,
      "probe_evidence_uri": null
    }
  ],
  "advisory": [],
  "migration_status": [
    {
      "release_id": "2026-06-17-001-canonical-discovery",
      "action_id": "backfill-canonical-discovery",
      "applies": true,
      "status_probe_key": "canonical_discovery_registered_active",
      "satisfied": false,
      "state": "pending",
      "detail": "DontPanic is registered but stale (no recent qualifying usage); not registered_active",
      "evidence_uri": null
    }
  ]
}

## 3. APPLY: `dontpanic projects backfill-canonical` (the real migration, from the report)
$ python -m dontpanic_orchestrate projects backfill-canonical
rc=0
stdout:
[projects backfill-canonical] mode: write
  ledger:   /Users/<operator>/.dontpanic-f010-e2e-74843/home/invocations.jsonl
  evidence: /Users/<operator>/.dontpanic-f010-e2e-74843/home/canonical-backfill-evidence.json
  stamped:         3
  already stamped: 1
  would skip:      0

## 4. VERIFY: `dontpanic projects discover --json` (proves the new state, from the report)
$ python -m dontpanic_orchestrate projects discover --json  (post-apply)
rc=0
stdout:
{
  "used_unregistered": [],
  "registered_active": [
    {
      "canonical_repo_key": "21bb34ac465755aa",
      "registry_name": "fixture-project",
      "path_display": "/Users/<operator>/.dontpanic-f010-e2e-74843/fixture-project",
      "observed_count": 5,
      "last_seen": "2026-06-23T04:59:12Z",
      "registry_conflict": false,
      "conflicting_registry_names": []
    }
  ],
  "registered_stale": [],
  "registered_path_missing": [],
  "registered_unresolved": []
}

## 5. Re-run `dontpanic doctor --upgrade --json` + plain doctor (after)
$ python -m dontpanic_orchestrate doctor --upgrade --json
rc=0
stdout:
{
  "summary": {
    "installed_commit": "unknown",
    "latest_release_id": "2026-06-17-001-canonical-discovery",
    "last_seen_release": null,
    "last_seen_commit": null,
    "pending_required": 0,
    "pending_advisory": 0,
    "update_state": "up_to_date",
    "marker_state": "absent",
    "upstream": {
      "fetched_upstream_commit": null,
      "upstream_status": "unknown",
      "remediation": "Upstream position unknown: not a git checkout, so the newest DontPanic cannot be compared here.",
      "upstream_ref": null
    }
  },
  "required": [],
  "advisory": [],
  "migration_status": [
    {
      "release_id": "2026-06-17-001-canonical-discovery",
      "action_id": "backfill-canonical-discovery",
      "applies": true,
      "status_probe_key": "canonical_discovery_registered_active",
      "satisfied": true,
      "state": "satisfied",
      "detail": "DontPanic is registered_active (canonical repo: fixture-project)",
      "evidence_uri": null
    }
  ]
}
$ python -m dontpanic_orchestrate doctor --skip-auth --json
rc=1
stdout:
{
  "checks": [
    {
      "name": "python>=3.10",
      "ok": true,
      "message": "Python 3.10",
      "remediation": "",
      "warn": false
    },
    {
      "name": "cli:gcloud",
      "ok": true,
      "message": "gcloud found",
      "remediation": "",
      "warn": false
    },
    {
      "name": "cli:firebase",
      "ok": true,
      "message": "firebase found",
      "remediation": "",
      "warn": false
    },
    {
      "name": "cli:jq",
      "ok": true,
      "message": "jq found",
      "remediation": "",
      "warn": false
    },
    {
      "name": "cli:git",
      "ok": true,
      "message": "git found",
      "remediation": "",
      "warn": false
    },
    {
      "name": "target-project",
      "ok": true,
      "message": "environments.json dev=jarvis-a6ee1",
      "remediation": "",
      "warn": false
    },
    {
      "name": "secrets-dir",
      "ok": true,
      "message": ".secrets/ exists, gitignored",
      "remediation": "",
      "warn": false
    },
    {
      "name": "sa-key-age",
      "ok": true,
      "message": "/Users/bayesian/.dontpanic-f010-e2e-74843/home/.secrets not present (no SA keys to age-check)",
      "remediation": "",
      "warn": false
    },
    {
      "name": "py:pydantic",
      "ok": true,
      "message": "pydantic OK",
      "remediation": "",
      "warn": false
    },
    {
      "name": "py:yaml",
      "ok": true,
      "message": "yaml OK",
      "remediation": "",
      "warn": false
    },
    {
      "name": "py:firebase_admin",
      "ok": true,
      "message": "firebase_admin OK",
      "remediation": "",
      "warn": false
    },
    {
      "name": "schemas",
      "ok": true,
      "message": "5 core schemas present at claude/shared/schemas/v1.0",
      "remediation": "",
      "warn": false
    },
    {
      "name": "pydantic-models",
      "ok": true,
      "message": "plan/features/audit/environments/signoff models import clean",
      "remediation": "",
      "warn": false
    },
    {
      "name": "parent-plan",
      "ok": true,
      "message": "parent orchestration plan validates",
      "remediation": "",
      "warn": false
    },
    {
      "name": "quota-caps",
      "ok": true,
      "message": "/Users/bayesian/.dontpanic-f010-e2e-74843/home-env/.jarvis/quota_state.json not present \u2014 run `python3 scripts/quota_check.py` to populate",
      "remediation": "",
      "warn": false
    },
    {
      "name": "global-config",
      "ok": true,
      "message": "/Users/bayesian/.dontpanic-f010-e2e-74843/home/config.json not present (first-run zero state \u2014 defaults will fall through to hardcoded)",
      "remediation": "",
      "warn": false
    },
    {
      "name": "projects-registry",
      "ok": true,
      "message": "1 project(s) registered",
      "remediation": "",
      "warn": false
    },
    {
      "name": "project:fixture-project:path",
      "ok": true,
      "message": "path exists: /Users/bayesian/.dontpanic-f010-e2e-74843/fixture-project",
      "remediation": "",
      "warn": false
    },
    {
      "name": "project:fixture-project:config",
      "ok": true,
      "message": "/Users/bayesian/.dontpanic-f010-e2e-74843/fixture-project/.dontpanic/dontpanic.json not present (per-project config is optional)",
      "remediation": "",
      "warn": false
    },
    {
      "name": "project:fixture-project:plans-dir",
      "ok": true,
      "message": "declared plans dir not present: /Users/bayesian/.dontpanic-f010-e2e-74843/fixture-project/docs/plans (parent dir also missing)",
      "remediation": "create the directory or update plans_dir in /Users/bayesian/.dontpanic-f010-e2e-74843/fixture-project/.dontpanic/dontpanic.json",
      "warn": true
    },
    {
      "name": "project:fixture-project:agents",
      "ok": true,
      "message": "no per-project agent overrides (falls through to global / hardcoded)",
      "remediation": "",
      "warn": false
    },
    {
      "name": "project:fixture-project:gates",
      "ok": true,
      "message": "no per-project human_gates override",
      "remediation": "",
      "warn": false
    },
    {
      "name": "project:fixture-project:roles",
      "ok": true,
      "message": "no project roles.* overrides declared",
      "remediation": "",
      "warn": false
    },
    {
      "name": "config-home",
      "ok": true,
      "message": "canonical (~/.dontpanic) and legacy (~/.jarvis) homes are reconciled",
      "remediation": "",
      "warn": false
    },
    {
      "name": "validate-plans-strict",
      "ok": true,
      "message": "109 locked plan(s) under docs/plans validate clean against plan.schema.json",
      "remediation": "",
      "warn": false,
      "details": [
        {
          "plan_id": "2026-04-19-001-infra-cross-agent-orchestration",
          "path": "plans/2026-04-19-001-infra-cross-agent-orchestration/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-04-25-001-infra-jarvis-firebase-bootstrap",
          "path": "plans/2026-04-25-001-infra-jarvis-firebase-bootstrap/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-04-25-002-infra-trivial-orchestration-test",
          "path": "plans/2026-04-25-002-infra-trivial-orchestration-test/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-04-26-006-infra-f023-ec5-evidence",
          "path": "plans/2026-04-26-006-infra-f023-ec5-evidence/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-04-28-001-infra-financial-observability",
          "path": "plans/2026-04-28-001-infra-financial-observability/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-04-29-001-feat-changelog-skill",
          "path": "plans/2026-04-29-001-feat-changelog-skill/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-04-29-002-feat-agent-permission-wiring",
          "path": "plans/2026-04-29-002-feat-agent-permission-wiring/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-04-29-003-fix-f008-phased-gates",
          "path": "plans/2026-04-29-003-fix-f008-phased-gates/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-04-29-004-fix-f006-budget-semantics",
          "path": "plans/2026-04-29-004-fix-f006-budget-semantics/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-04-30-001-fix-quota-tracker-vendor-native",
          "path": "plans/2026-04-30-001-fix-quota-tracker-vendor-native/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-01-001-feat-onboarding-ux",
          "path": "plans/2026-05-01-001-feat-onboarding-ux/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-01-002-feat-discord-notification-sink",
          "path": "plans/2026-05-01-002-feat-discord-notification-sink/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-01-003-feat-security-baseline",
          "path": "plans/2026-05-01-003-feat-security-baseline/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-01-004-feat-patch-completeness-gate",
          "path": "plans/2026-05-01-004-feat-patch-completeness-gate/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-01-005-feat-target-context-platform-fix",
          "path": "plans/2026-05-01-005-feat-target-context-platform-fix/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-02-001-feat-resume-gate-discipline",
          "path": "plans/2026-05-02-001-feat-resume-gate-discipline/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-02-002-fix-audit-envelope-filename",
          "path": "plans/2026-05-02-002-fix-audit-envelope-filename/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-02-003-feat-nested-orchestration-v1",
          "path": "plans/2026-05-02-003-feat-nested-orchestration-v1/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-02-004-fix-diminishing-returns-signature-based",
          "path": "plans/2026-05-02-004-fix-diminishing-returns-signature-based/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-03-001-feat-global-install-project-registry",
          "path": "plans/2026-05-03-001-feat-global-install-project-registry/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-03-002-infra-personal-openclaw-axiom-jarvis",
          "path": "plans/2026-05-03-002-infra-personal-openclaw-axiom-jarvis/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-03-003-feat-agent-access-manifest-thin-mcp",
          "path": "plans/2026-05-03-003-feat-agent-access-manifest-thin-mcp/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-04-001-refactor-canonical-dontpanic-module",
          "path": "plans/2026-05-04-001-refactor-canonical-dontpanic-module/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-04-002-fix-supervisor-lifecycle-staged-gates",
          "path": "plans/2026-05-04-002-fix-supervisor-lifecycle-staged-gates/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-04-003-fix-subprocess-timeout-envelope-durability",
          "path": "plans/2026-05-04-003-fix-subprocess-timeout-envelope-durability/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-04-004-fix-ec5-classifier-purity",
          "path": "plans/2026-05-04-004-fix-ec5-classifier-purity/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-05-001-fix-plan-validator-audit-auxiliary-json",
          "path": "plans/2026-05-05-001-fix-plan-validator-audit-auxiliary-json/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-05-002-feat-goal-governance-nested-orchestration-config",
          "path": "plans/2026-05-05-002-feat-goal-governance-nested-orchestration-config/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-05-003-feat-objective-contract-and-sufficiency-audit",
          "path": "plans/2026-05-05-003-feat-objective-contract-and-sufficiency-audit/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-06-001-infra-runtime-evidence-harness",
          "path": "plans/2026-05-06-001-infra-runtime-evidence-harness/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-06-002-feat-post-impl-completion-audit",
          "path": "plans/2026-05-06-002-feat-post-impl-completion-audit/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-06-003-fix-live-cross-vendor-goal-audit-dogfood",
          "path": "plans/2026-05-06-003-fix-live-cross-vendor-goal-audit-dogfood/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-07-001-fix-completion-dispatch-codex-stream-parser",
          "path": "plans/2026-05-07-001-fix-completion-dispatch-codex-stream-parser/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-07-002-fix-cross-vendor-dogfood-fixture-runtime-artifacts",
          "path": "plans/2026-05-07-002-fix-cross-vendor-dogfood-fixture-runtime-artifacts/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-08-001-feat-ruff-s-remediation",
          "path": "plans/2026-05-08-001-feat-ruff-s-remediation/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-08-002-feat-skill-applicability-v0",
          "path": "plans/2026-05-08-002-feat-skill-applicability-v0/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-08-003-fix-harness-volley-frictions",
          "path": "plans/2026-05-08-003-fix-harness-volley-frictions/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-09-001-fix-conftest-global-config-isolation",
          "path": "plans/2026-05-09-001-fix-conftest-global-config-isolation/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-09-002-fix-verdict-status-environmental-frictions",
          "path": "plans/2026-05-09-002-fix-verdict-status-environmental-frictions/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-09-003-feat-state-projection-v0",
          "path": "plans/2026-05-09-003-feat-state-projection-v0/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-09-004-feat-firebase-dashboard-adapter-v0",
          "path": "plans/2026-05-09-004-feat-firebase-dashboard-adapter-v0/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-10-001-feat-printing-press-adapter-skill",
          "path": "plans/2026-05-10-001-feat-printing-press-adapter-skill/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-11-001-infra-state-projection-adapters-meta",
          "path": "plans/2026-05-11-001-infra-state-projection-adapters-meta/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-11-002-fix-harness-frictions-v3",
          "path": "plans/2026-05-11-002-fix-harness-frictions-v3/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-12-001-fix-harness-frictions-v4",
          "path": "plans/2026-05-12-001-fix-harness-frictions-v4/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-12-002-fix-harness-frictions-v4-1",
          "path": "plans/2026-05-12-002-fix-harness-frictions-v4-1/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-19-002-feat-install-ux-hardening-v0",
          "path": "plans/2026-05-19-002-feat-install-ux-hardening-v0/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-19-003-fix-plan-schema-orchestration-fields",
          "path": "plans/2026-05-19-003-fix-plan-schema-orchestration-fields/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-19-004-feat-architecture-map-with-drift-v0",
          "path": "plans/2026-05-19-004-feat-architecture-map-with-drift-v0/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-19-005-feat-dogfood-showcase-artifacts-v0",
          "path": "plans/2026-05-19-005-feat-dogfood-showcase-artifacts-v0/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-20-001-infra-external-integrations-bridge-v0",
          "path": "plans/2026-05-20-001-infra-external-integrations-bridge-v0/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-21-001-feat-capability-manifest-consumers-v0",
          "path": "plans/2026-05-21-001-feat-capability-manifest-consumers-v0/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-22-001-infra-external-capability-operations-roadmap-v0",
          "path": "plans/2026-05-22-001-infra-external-capability-operations-roadmap-v0/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-22-002-feat-capability-status-v0",
          "path": "plans/2026-05-22-002-feat-capability-status-v0/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-22-003-feat-capability-center-v1",
          "path": "plans/2026-05-22-003-feat-capability-center-v1/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-22-004-feat-capability-guided-setup-v2",
          "path": "plans/2026-05-22-004-feat-capability-guided-setup-v2/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-23-001-infra-install-lifecycle-reconciliation-roadmap-v0",
          "path": "plans/2026-05-23-001-infra-install-lifecycle-reconciliation-roadmap-v0/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-23-002-feat-install-reconcile-foundation-v0",
          "path": "plans/2026-05-23-002-feat-install-reconcile-foundation-v0/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-23-003-infra-visual-operating-console-roadmap-v0",
          "path": "plans/2026-05-23-003-infra-visual-operating-console-roadmap-v0/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-23-004-feat-operator-console-v0",
          "path": "plans/2026-05-23-004-feat-operator-console-v0/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-23-005-feat-dashboard-project-selector-v0",
          "path": "plans/2026-05-23-005-feat-dashboard-project-selector-v0/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-23-006-infra-planning-intelligence-roadmap-v0",
          "path": "plans/2026-05-23-006-infra-planning-intelligence-roadmap-v0/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-23-007-feat-plan-intake-readiness-v0",
          "path": "plans/2026-05-23-007-feat-plan-intake-readiness-v0/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-24-001-feat-dashboard-value-language-ia-v0",
          "path": "plans/2026-05-24-001-feat-dashboard-value-language-ia-v0/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-24-002-feat-dashboard-architecture-explorer-v1",
          "path": "plans/2026-05-24-002-feat-dashboard-architecture-explorer-v1/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-24-003-infra-dashboard-platform-roadmap-v1",
          "path": "plans/2026-05-24-003-infra-dashboard-platform-roadmap-v1/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-24-004-feat-event-messaging-v1",
          "path": "plans/2026-05-24-004-feat-event-messaging-v1/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-30-001-feat-universal-agent-repo-onboarding-v0",
          "path": "plans/2026-05-30-001-feat-universal-agent-repo-onboarding-v0/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-05-30-002-fix-orchestrator-convergence-bugs",
          "path": "plans/2026-05-30-002-fix-orchestrator-convergence-bugs/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-06-01-001-feat-plan-review-scope-validation",
          "path": "plans/2026-06-01-001-feat-plan-review-scope-validation/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-06-02-001-feat-control-plane-action-spine",
          "path": "plans/2026-06-02-001-feat-control-plane-action-spine/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-06-02-002-fix-orchestrator-convergence-and-close-friction",
          "path": "plans/2026-06-02-002-fix-orchestrator-convergence-and-close-friction/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-06-03-001-feat-agent-command-surface-hardening",
          "path": "plans/2026-06-03-001-feat-agent-command-surface-hardening/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-06-04-001-feat-ledger-reconciliation-operator-actions",
          "path": "plans/2026-06-04-001-feat-ledger-reconciliation-operator-actions/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-06-04-003-feat-integration-operator-actions",
          "path": "plans/2026-06-04-003-feat-integration-operator-actions/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-06-04-004-feat-dashboard-state-fidelity",
          "path": "plans/2026-06-04-004-feat-dashboard-state-fidelity/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-06-04-005-feat-render-truth-scope-contract",
          "path": "plans/2026-06-04-005-feat-render-truth-scope-contract/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-06-04-006-feat-dashboard-safe-repair-runner",
          "path": "plans/2026-06-04-006-feat-dashboard-safe-repair-runner/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-06-05-001-fix-capability-card-setup-clarity",
          "path": "plans/2026-06-05-001-fix-capability-card-setup-clarity/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-06-05-002-feat-dashboard-real-state-qa-contract-v0",
          "path": "plans/2026-06-05-002-feat-dashboard-real-state-qa-contract-v0/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-06-05-003-feat-dashboard-design-system-v0",
          "path": "plans/2026-06-05-003-feat-dashboard-design-system-v0/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-06-05-004-feat-applicable-conventions-disposition-gate-v0",
          "path": "plans/2026-06-05-004-feat-applicable-conventions-disposition-gate-v0/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-06-06-001-feat-operator-triage-surface-v0",
          "path": "plans/2026-06-06-001-feat-operator-triage-surface-v0/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-06-06-002-feat-governed-gui-action-channel-v1",
          "path": "plans/2026-06-06-002-feat-governed-gui-action-channel-v1/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-06-06-003-feat-architecture-auto-refresh",
          "path": "plans/2026-06-06-003-feat-architecture-auto-refresh/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-06-06-004-feat-operator-console-redesign",
          "path": "plans/2026-06-06-004-feat-operator-console-redesign/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-06-06-005-feat-cockpit-default-integration",
          "path": "plans/2026-06-06-005-feat-cockpit-default-integration/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-06-06-007-feat-architecture-render",
          "path": "plans/2026-06-06-007-feat-architecture-render/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-06-07-001-feat-architecture-evidence-contract-v0",
          "path": "plans/2026-06-07-001-feat-architecture-evidence-contract-v0/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-06-07-002-fix-plan-review-introduces-vocabulary",
          "path": "plans/2026-06-07-002-fix-plan-review-introduces-vocabulary/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-06-07-003-feat-operator-console-008-chrome-theming-state",
          "path": "plans/2026-06-07-003-feat-operator-console-008-chrome-theming-state/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-06-08-001-feat-architecture-intent-extractor-plan-b",
          "path": "plans/2026-06-08-001-feat-architecture-intent-extractor-plan-b/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-06-08-002-feat-architecture-js-extractor-plan-c",
          "path": "plans/2026-06-08-002-feat-architecture-js-extractor-plan-c/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-06-08-003-fix-audit-findings",
          "path": "plans/2026-06-08-003-fix-audit-findings/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-06-08-004-feat-architecture-reconciler-ui-plan-d",
          "path": "plans/2026-06-08-004-feat-architecture-reconciler-ui-plan-d/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-06-08-005-feat-architecture-ts-extractor-plan-c2",
          "path": "plans/2026-06-08-005-feat-architecture-ts-extractor-plan-c2/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-06-08-006-fix-preimpl-governance-loop",
          "path": "plans/2026-06-08-006-fix-preimpl-governance-loop/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-06-09-001-feat-architecture-c0-weak-graph",
          "path": "plans/2026-06-09-001-feat-architecture-c0-weak-graph/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-06-09-002-feat-sufficiency-gate-convergence",
          "path": "plans/2026-06-09-002-feat-sufficiency-gate-convergence/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-06-10-001-feat-convergence-policy-v1-1",
          "path": "plans/2026-06-10-001-feat-convergence-policy-v1-1/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-06-10-002-feat-worktree-isolation-v0",
          "path": "plans/2026-06-10-002-feat-worktree-isolation-v0/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-06-11-001-feat-worktree-guard-hardening",
          "path": "plans/2026-06-11-001-feat-worktree-guard-hardening/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-06-12-001-fix-audit-evidence-writer-hygiene",
          "path": "plans/2026-06-12-001-fix-audit-evidence-writer-hygiene/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-06-14-001-feat-agent-channel-interop-v0",
          "path": "plans/2026-06-14-001-feat-agent-channel-interop-v0/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-06-14-002-feat-experience-readiness-gate-v0",
          "path": "plans/2026-06-14-002-feat-experience-readiness-gate-v0/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-06-15-001-feat-experience-readiness-evidence-typing-v0",
          "path": "plans/2026-06-15-001-feat-experience-readiness-evidence-typing-v0/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-06-15-002-feat-experience-readiness-degraded-honesty-v0",
          "path": "plans/2026-06-15-002-feat-experience-readiness-degraded-honesty-v0/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-06-17-001-feat-canonical-repo-discovery",
          "path": "plans/2026-06-17-001-feat-canonical-repo-discovery/plan.md",
          "status": "clean"
        },
        {
          "plan_id": "2026-06-21-001-feat-upgrade-readiness-doctor",
          "path": "plans/2026-06-21-001-feat-upgrade-readiness-doctor/plan.md",
          "status": "clean"
        }
      ]
    },
    {
      "name": "architecture-drift",
      "ok": true,
      "message": "stale_major \u2014 407/771 files differ (52.8%): added=335 removed=0 modified=72",
      "remediation": "python -m dontpanic_orchestrate architecture regen",
      "warn": true,
      "details": [
        {
          "state": "stale_major",
          "architecture_path": "/Users/bayesian/Documents/GitHub/DontPanic/docs/architecture/architecture.json",
          "stored_fingerprint": "b3dc608f06b214efadeb9b17c1dba1f212100a4f606a7aef3019c39b08d41306",
          "current_fingerprint": "3b152cb29e0407af6fd93a0c0420e3001ba957997369e42864e0de8f96f8a68e",
          "changed_files": {
            "added": [
              "claude/shared/schemas/v1.0/models/experience_readiness.py",
              "claude/shared/schemas/v1.0/models/upgrade_releases_model.py",
              "claude/shared/schemas/v1.0/upgrade-releases.schema.json",
              "docs/plans/2026-05-30-002-fix-orchestrator-convergence-bugs/features.json",
              "docs/plans/2026-05-30-002-fix-orchestrator-convergence-bugs/plan.md",
              "docs/plans/2026-06-01-001-feat-plan-review-scope-validation/features.json",
              "docs/plans/2026-06-01-001-feat-plan-review-scope-validation/plan.md",
              "docs/plans/2026-06-02-001-feat-control-plane-action-spine/features.json",
              "docs/plans/2026-06-02-001-feat-control-plane-action-spine/plan.md",
              "docs/plans/2026-06-02-002-fix-orchestrator-convergence-and-close-friction/features.json",
              "docs/plans/2026-06-02-002-fix-orchestrator-convergence-and-close-friction/plan.md",
              "docs/plans/2026-06-03-001-feat-agent-command-surface-hardening/features.json",
              "docs/plans/2026-06-03-001-feat-agent-command-surface-hardening/plan.md",
              "docs/plans/2026-06-04-001-feat-ledger-reconciliation-operator-actions/features.json",
              "docs/plans/2026-06-04-001-feat-ledger-reconciliation-operator-actions/plan.md",
              "docs/plans/2026-06-04-002-feat-local-harness-adapter-runtime/features.json",
              "docs/plans/2026-06-04-002-feat-local-harness-adapter-runtime/plan.md",
              "docs/plans/2026-06-04-003-feat-integration-operator-actions/features.json",
              "docs/plans/2026-06-04-003-feat-integration-operator-actions/plan.md",
              "docs/plans/2026-06-04-004-feat-dashboard-state-fidelity/features.json",
              "\u2026 +315 more"
            ],
            "removed": [],
            "modified": [
              "claude/shared/VERSION",
              "claude/shared/schemas/v1.0/capability.schema.json",
              "claude/shared/schemas/v1.0/models/features_model.py",
              "claude/shared/schemas/v1.0/models/objective_contract_model.py",
              "docs/plans/2026-04-19-001-infra-cross-agent-orchestration/plan.md",
              "docs/plans/2026-04-29-001-feat-changelog-skill/features.json",
              "docs/plans/2026-04-29-001-feat-changelog-skill/plan.md",
              "docs/plans/2026-04-29-004-fix-f006-budget-semantics/plan.md",
              "docs/plans/2026-05-03-002-infra-personal-openclaw-axiom-jarvis/plan.md",
              "docs/plans/2026-05-24-001-feat-dashboard-value-language-ia-v0/plan.md",
              "docs/plans/2026-05-30-001-feat-universal-agent-repo-onboarding-v0/features.json",
              "docs/plans/2026-05-30-001-feat-universal-agent-repo-onboarding-v0/plan.md",
              "scripts/dontpanic_orchestrate/active_supervisors.py",
              "scripts/dontpanic_orchestrate/agent_brief.py",
              "scripts/dontpanic_orchestrate/agent_manifest.py",
              "scripts/dontpanic_orchestrate/agent_surface.py",
              "scripts/dontpanic_orchestrate/architecture_view_state.py",
              "scripts/dontpanic_orchestrate/capabilities.py",
              "scripts/dontpanic_orchestrate/circuit_breakers.py",
              "scripts/dontpanic_orchestrate/cli.py",
              "\u2026 +52 more"
            ]
          },
          "changed_files_list": [
            "added: claude/shared/schemas/v1.0/models/experience_readiness.py",
            "added: claude/shared/schemas/v1.0/models/upgrade_releases_model.py",
            "added: claude/shared/schemas/v1.0/upgrade-releases.schema.json",
            "added: docs/plans/2026-05-30-002-fix-orchestrator-convergence-bugs/features.json",
            "added: docs/plans/2026-05-30-002-fix-orchestrator-convergence-bugs/plan.md",
            "added: docs/plans/2026-06-01-001-feat-plan-review-scope-validation/features.json",
            "added: docs/plans/2026-06-01-001-feat-plan-review-scope-validation/plan.md",
            "added: docs/plans/2026-06-02-001-feat-control-plane-action-spine/features.json",
            "added: docs/plans/2026-06-02-001-feat-control-plane-action-spine/plan.md",
            "added: docs/plans/2026-06-02-002-fix-orchestrator-convergence-and-close-friction/features.json",
            "added: docs/plans/2026-06-02-002-fix-orchestrator-convergence-and-close-friction/plan.md",
            "added: docs/plans/2026-06-03-001-feat-agent-command-surface-hardening/features.json",
            "added: docs/plans/2026-06-03-001-feat-agent-command-surface-hardening/plan.md",
            "added: docs/plans/2026-06-04-001-feat-ledger-reconciliation-operator-actions/features.json",
            "added: docs/plans/2026-06-04-001-feat-ledger-reconciliation-operator-actions/plan.md",
            "added: docs/plans/2026-06-04-002-feat-local-harness-adapter-runtime/features.json",
            "added: docs/plans/2026-06-04-002-feat-local-harness-adapter-runtime/plan.md",
            "added: docs/plans/2026-06-04-003-feat-integration-operator-actions/features.json",
            "added: docs/plans/2026-06-04-003-feat-integration-operator-actions/plan.md",
            "added: docs/plans/2026-06-04-004-feat-dashboard-state-fidelity/features.json",
            "added: \u2026 +315 more",
            "modified: claude/shared/VERSION",
            "modified: claude/shared/schemas/v1.0/capability.schema.json",
            "modified: claude/shared/schemas/v1.0/models/features_model.py",
            "modified: claude/shared/schemas/v1.0/models/objective_contract_model.py",
            "modified: docs/plans/2026-04-19-001-infra-cross-agent-orchestration/plan.md",
            "modified: docs/plans/2026-04-29-001-feat-changelog-skill/features.json",
            "modified: docs/plans/2026-04-29-001-feat-changelog-skill/plan.md",
            "modified: docs/plans/2026-04-29-004-fix-f006-budget-semantics/plan.md",
            "modified: docs/plans/2026-05-03-002-infra-personal-openclaw-axiom-jarvis/plan.md",
            "modified: docs/plans/2026-05-24-001-feat-dashboard-value-language-ia-v0/plan.md",
            "modified: docs/plans/2026-05-30-001-feat-universal-agent-repo-onboarding-v0/features.json",
            "modified: docs/plans/2026-05-30-001-feat-universal-agent-repo-onboarding-v0/plan.md",
            "modified: scripts/dontpanic_orchestrate/active_supervisors.py",
            "modified: scripts/dontpanic_orchestrate/agent_brief.py",
            "modified: scripts/dontpanic_orchestrate/agent_manifest.py",
            "modified: scripts/dontpanic_orchestrate/agent_surface.py",
            "modified: scripts/dontpanic_orchestrate/architecture_view_state.py",
            "modified: scripts/dontpanic_orchestrate/capabilities.py",
            "modified: scripts/dontpanic_orchestrate/circuit_breakers.py",
            "modified: scripts/dontpanic_orchestrate/cli.py",
            "modified: \u2026 +52 more"
          ],
          "changed_files_total": 407,
          "unchanged_files": 364,
          "files_count_current": 771,
          "files_count_stored": 436,
          "drift_pct": 52.79,
          "missing_required": [],
          "recommendation": "major drift (\u22655% files changed). Run `python -m dontpanic_orchestrate architecture regen` before downstream consumers (Plan 4.5 `dontpanic new`, F004 supervisor regen hook) read a stale snapshot."
        }
      ]
    },
    {
      "name": "dashboard-files",
      "ok": true,
      "message": "static dashboard present at dashboard/index.html",
      "remediation": "",
      "warn": false
    },
    {
      "name": "dashboard-cache",
      "ok": true,
      "message": "what-now cache missing at /Users/bayesian/.dontpanic-f010-e2e-74843/home/dashboard/what-now.json",
      "remediation": "run: dontpanic dashboard build",
      "warn": true
    },
    {
      "name": "dashboard-state",
      "ok": true,
      "message": "dashboard/state has state-snapshot.json + what-now.json",
      "remediation": "",
      "warn": false
    },
    {
      "name": "skill-rubrics",
      "ok": true,
      "message": "5 high-value skill(s) lack an invocation rubric (advisory \u2014 core use is not blocked): agent-browser, cost-model, eval-harness, pr-reviewer, printing-press-adapter",
      "remediation": "run: dontpanic skills rubric --suggest agent-browser; dontpanic skills rubric --suggest cost-model; dontpanic skills rubric --suggest eval-harness; dontpanic skills rubric --suggest pr-reviewer; dontpanic skills rubric --suggest printing-press-adapter",
      "warn": true
    },
    {
      "name": "upgrade-readiness",
      "ok": true,
      "message": "up to date (2026-06-17-001-canonical-discovery)",
      "remediation": "",
      "warn": false
    }
  ],
  "passed": 31,
  "failed": 0,
  "warnings": 4,
  "architecture_drift": {
    "state": "stale_major",
    "changed_files": [
      "added: claude/shared/schemas/v1.0/models/experience_readiness.py",
      "added: claude/shared/schemas/v1.0/models/upgrade_releases_model.py",
      "added: claude/shared/schemas/v1.0/upgrade-releases.schema.json",
      "added: docs/plans/2026-05-30-002-fix-orchestrator-convergence-bugs/features.json",
      "added: docs/plans/2026-05-30-002-fix-orchestrator-convergence-bugs/plan.md",
      "added: docs/plans/2026-06-01-001-feat-plan-review-scope-validation/features.json",
      "added: docs/plans/2026-06-01-001-feat-plan-review-scope-validation/plan.md",
      "added: docs/plans/2026-06-02-001-feat-control-plane-action-spine/features.json",
      "added: docs/plans/2026-06-02-001-feat-control-plane-action-spine/plan.md",
      "added: docs/plans/2026-06-02-002-fix-orchestrator-convergence-and-close-friction/features.json",
      "added: docs/plans/2026-06-02-002-fix-orchestrator-convergence-and-close-friction/plan.md",
      "added: docs/plans/2026-06-03-001-feat-agent-command-surface-hardening/features.json",
      "added: docs/plans/2026-06-03-001-feat-agent-command-surface-hardening/plan.md",
      "added: docs/plans/2026-06-04-001-feat-ledger-reconciliation-operator-actions/features.json",
      "added: docs/plans/2026-06-04-001-feat-ledger-reconciliation-operator-actions/plan.md",
      "added: docs/plans/2026-06-04-002-feat-local-harness-adapter-runtime/features.json",
      "added: docs/plans/2026-06-04-002-feat-local-harness-adapter-runtime/plan.md",
      "added: docs/plans/2026-06-04-003-feat-integration-operator-actions/features.json",
      "added: docs/plans/2026-06-04-003-feat-integration-operator-actions/plan.md",
      "added: docs/plans/2026-06-04-004-feat-dashboard-state-fidelity/features.json",
      "added: \u2026 +315 more",
      "modified: claude/shared/VERSION",
      "modified: claude/shared/schemas/v1.0/capability.schema.json",
      "modified: claude/shared/schemas/v1.0/models/features_model.py",
      "modified: claude/shared/schemas/v1.0/models/objective_contract_model.py",
      "modified: docs/plans/2026-04-19-001-infra-cross-agent-orchestration/plan.md",
      "modified: docs/plans/2026-04-29-001-feat-changelog-skill/features.json",
      "modified: docs/plans/2026-04-29-001-feat-changelog-skill/plan.md",
      "modified: docs/plans/2026-04-29-004-fix-f006-budget-semantics/plan.md",
      "modified: docs/plans/2026-05-03-002-infra-personal-openclaw-axiom-jarvis/plan.md",
      "modified: docs/plans/2026-05-24-001-feat-dashboard-value-language-ia-v0/plan.md",
      "modified: docs/plans/2026-05-30-001-feat-universal-agent-repo-onboarding-v0/features.json",
      "modified: docs/plans/2026-05-30-001-feat-universal-agent-repo-onboarding-v0/plan.md",
      "modified: scripts/dontpanic_orchestrate/active_supervisors.py",
      "modified: scripts/dontpanic_orchestrate/agent_brief.py",
      "modified: scripts/dontpanic_orchestrate/agent_manifest.py",
      "modified: scripts/dontpanic_orchestrate/agent_surface.py",
      "modified: scripts/dontpanic_orchestrate/architecture_view_state.py",
      "modified: scripts/dontpanic_orchestrate/capabilities.py",
      "modified: scripts/dontpanic_orchestrate/circuit_breakers.py",
      "modified: scripts/dontpanic_orchestrate/cli.py",
      "modified: \u2026 +52 more"
    ],
    "changed_files_categorized": {
      "added": [
        "claude/shared/schemas/v1.0/models/experience_readiness.py",
        "claude/shared/schemas/v1.0/models/upgrade_releases_model.py",
        "claude/shared/schemas/v1.0/upgrade-releases.schema.json",
        "docs/plans/2026-05-30-002-fix-orchestrator-convergence-bugs/features.json",
        "docs/plans/2026-05-30-002-fix-orchestrator-convergence-bugs/plan.md",
        "docs/plans/2026-06-01-001-feat-plan-review-scope-validation/features.json",
        "docs/plans/2026-06-01-001-feat-plan-review-scope-validation/plan.md",
        "docs/plans/2026-06-02-001-feat-control-plane-action-spine/features.json",
        "docs/plans/2026-06-02-001-feat-control-plane-action-spine/plan.md",
        "docs/plans/2026-06-02-002-fix-orchestrator-convergence-and-close-friction/features.json",
        "docs/plans/2026-06-02-002-fix-orchestrator-convergence-and-close-friction/plan.md",
        "docs/plans/2026-06-03-001-feat-agent-command-surface-hardening/features.json",
        "docs/plans/2026-06-03-001-feat-agent-command-surface-hardening/plan.md",
        "docs/plans/2026-06-04-001-feat-ledger-reconciliation-operator-actions/features.json",
        "docs/plans/2026-06-04-001-feat-ledger-reconciliation-operator-actions/plan.md",
        "docs/plans/2026-06-04-002-feat-local-harness-adapter-runtime/features.json",
        "docs/plans/2026-06-04-002-feat-local-harness-adapter-runtime/plan.md",
        "docs/plans/2026-06-04-003-feat-integration-operator-actions/features.json",
        "docs/plans/2026-06-04-003-feat-integration-operator-actions/plan.md",
        "docs/plans/2026-06-04-004-feat-dashboard-state-fidelity/features.json",
        "\u2026 +315 more"
      ],
      "removed": [],
      "modified": [
        "claude/shared/VERSION",
        "claude/shared/schemas/v1.0/capability.schema.json",
        "claude/shared/schemas/v1.0/models/features_model.py",
        "claude/shared/schemas/v1.0/models/objective_contract_model.py",
        "docs/plans/2026-04-19-001-infra-cross-agent-orchestration/plan.md",
        "docs/plans/2026-04-29-001-feat-changelog-skill/features.json",
        "docs/plans/2026-04-29-001-feat-changelog-skill/plan.md",
        "docs/plans/2026-04-29-004-fix-f006-budget-semantics/plan.md",
        "docs/plans/2026-05-03-002-infra-personal-openclaw-axiom-jarvis/plan.md",
        "docs/plans/2026-05-24-001-feat-dashboard-value-language-ia-v0/plan.md",
        "docs/plans/2026-05-30-001-feat-universal-agent-repo-onboarding-v0/features.json",
        "docs/plans/2026-05-30-001-feat-universal-agent-repo-onboarding-v0/plan.md",
        "scripts/dontpanic_orchestrate/active_supervisors.py",
        "scripts/dontpanic_orchestrate/agent_brief.py",
        "scripts/dontpanic_orchestrate/agent_manifest.py",
        "scripts/dontpanic_orchestrate/agent_surface.py",
        "scripts/dontpanic_orchestrate/architecture_view_state.py",
        "scripts/dontpanic_orchestrate/capabilities.py",
        "scripts/dontpanic_orchestrate/circuit_breakers.py",
        "scripts/dontpanic_orchestrate/cli.py",
        "\u2026 +52 more"
      ]
    },
    "changed_files_total": 407,
    "unchanged_files": 364,
    "missing_required": [],
    "recommendation": "major drift (\u22655% files changed). Run `python -m dontpanic_orchestrate architecture regen` before downstream consumers (Plan 4.5 `dontpanic new`, F004 supervisor regen hook) read a stale snapshot.",
    "ok": true,
    "warn": true
  }
}
