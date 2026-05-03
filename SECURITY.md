# Security Policy

## Reporting a Vulnerability

If you believe you have found a security issue in DontPanic, **do not open a public
issue or pull request**. Instead, report it privately so we can investigate and
ship a fix before details become public.

Preferred channels (either is fine):

- **Email:** open a private report by emailing the maintainer at the address
  listed in `git log` for `main` (the GitHub-noreply alias is also accepted).
- **GitHub Security Advisory:** use [GitHub's "Report a vulnerability"](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)
  flow on this repository — that opens a private advisory thread visible only
  to maintainers.

When reporting, please include:

- A description of the issue and its impact (what an attacker can do).
- Steps to reproduce, or a minimal proof-of-concept.
- The commit SHA / tag where you observed the issue.
- Whether the issue has been disclosed elsewhere.

We will not pursue legal action against good-faith researchers who follow this
policy.

## Supported Versions

DontPanic is currently a single-operator tool with no published release tags. Only
the `main` branch receives security fixes; older clones must rebase onto `main`
to pick them up.

| Version | Supported |
| ------- | --------- |
| `main`  | ✅ — security fixes land here |
| Any tagged release | ❌ — no LTS branch yet |
| Forks   | ❌ — fork maintainers are responsible for their own backports |

This table will be revisited once DontPanic ships its first tagged release; until
then, "rebase onto `main`" is the only supported upgrade path.

## Response Timeline

- **Acknowledgement:** within **72 hours** of receiving the report.
- **Triage and severity assessment:** within **7 days** of acknowledgement.
- **Fix or coordinated disclosure:** within **90 days** of the initial report,
  per industry-standard responsible disclosure windows. If a fix needs longer
  (genuine architectural change), we will say so explicitly and agree a
  revised timeline with the reporter.

If we have not acknowledged a report within 72 hours, please escalate by
opening a public issue that links to your private report (without disclosing
the vulnerability details) so the maintainer is paged.

## Scope

The platform's own posture is in scope: bootstrap, orchestrator, sanitization,
doctor, dispatchers, and CI. Code that this platform _generates_ for downstream
projects (`/security-review`, plan output, etc.) is reviewed per-project; report
those issues against the consumer repository unless the root cause is a
platform defect.

Out of scope for this policy:

- Findings against deferred-by-design surfaces — see `docs/plans/2026-05-01-003-feat-security-baseline/decisions.jsonl` (D004) for the deferral list.
- Theoretical issues with no reproducible impact on a current `main` checkout.

## Security tooling baseline

The platform runs the following baseline checks; these are **not** a SAST
substitute, and the absence of a SAST plan is acknowledged in the deferral
list:

- `scripts/sanitization_check.py` — secret-shape regex scan over the committed
  surface (AWS, GitHub, Anthropic, OpenAI, Slack, PEM, JWT). Each pattern has
  a `# source:` citation per `decisions.jsonl` D005.
- `.github/workflows/ci.yml` — least-privilege `permissions: contents: read`
  at workflow root.
- `scripts/jarvis_doctor.py` — soft warning when service-account keys under
  `~/.jarvis/.secrets/` exceed 90 days, nudging `bootstrap.sh --create-key`
  rotation.
