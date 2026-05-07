# Getting Started With DontPanic

This guide is for private-alpha users installing from source. It assumes you
are comfortable with a terminal and local agent CLIs, but it does not assume a
Firebase project or any cloud account for the first smoke test.

## Install

```bash
git clone https://github.com/Silex-Research/DontPanic.git
cd DontPanic
python3 -m pip install -e ".[dev]"
dontpanic --version
dontpanic --help
```

Required for the first smoke test: Python 3.10+, git, and a POSIX shell.
Claude, Codex, Firebase, Playwright, Xcode, Android, and backend providers are
only needed when you enable plans that use them.

## Configure Roles

Preview config writes first:

```bash
dontpanic setup --implementer claude --auditor codex --goal-auditor codex
```

Apply once the preview is correct:

```bash
dontpanic setup --implementer claude --auditor codex --goal-auditor codex --yes
dontpanic config show
```

DontPanic stores role names and runtime pointers, not API keys. Agent CLIs and
cloud CLIs keep their own credentials.

## Register a Project

```bash
dontpanic projects add myapp /absolute/path/to/myapp --init-config
cd /absolute/path/to/myapp
dontpanic project config set roles.implementer claude
dontpanic project config set roles.auditor codex
dontpanic project config set runtime_evidence.web.base_url http://localhost:3000
```

Runtime evidence defaults are project-local because base URLs, simulator
targets, Android package names, and backend projects are project-specific.

## Run Readiness Checks

```bash
dontpanic doctor --skip-auth
```

Use the full doctor only after authenticating the optional provider CLIs your
project actually needs:

```bash
gcloud auth login
gcloud auth application-default login
firebase login
dontpanic doctor
```

## Try A Safe Plan

The sample plan is exempt from goal governance and never dispatches agents.
Copy it to a temporary directory so your checkout stays clean:

```bash
python3 claude/shared/schemas/v1.0/validate.py examples/plans/hello-dontpanic
tmp_plan="$(mktemp -d)/hello-dontpanic"
cp -R examples/plans/hello-dontpanic "$tmp_plan"
dontpanic plan lock "$tmp_plan"
dontpanic plan close "$tmp_plan"
```

Expected result: `plan lock` flips `draft -> active`; `plan close` flips
`active -> completed` through the exempt infra path.

## Dispatch Real Work

For real work, create or choose a plan under `docs/plans/<plan-id>/`, validate
it, lock it, then preview dispatch:

```bash
python3 claude/shared/schemas/v1.0/validate.py docs/plans/<plan-id>/
dontpanic plan lock docs/plans/<plan-id>/
dontpanic dispatch-from-plan <plan-id>
```

`dispatch-from-plan` is dry-run by default. It prints the resolved context and
does not run agents until you add `--confirm`.

```bash
dontpanic dispatch-from-plan <plan-id> --confirm
dontpanic plan close docs/plans/<plan-id>/
```

Goal-gated plans run a sufficiency check at lock and a completion audit at
close. Blocking findings require an explicit operator override reason that is
recorded under the plan's evidence directory.
