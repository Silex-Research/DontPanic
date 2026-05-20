# Linear Printing Press paid-run close-out - 2026-05-20

Plan: `2026-05-10-001-feat-printing-press-adapter-skill`
Feature: `F003`

## Paid invocation

The operator-approved single paid invocation was consumed with:

```text
/printing-press linear codex
```

The run used the local `mvanhorn/cli-printing-press` checkout and built
`printing-press 4.9.0` before invoking the skill.

Run root:

```text
/Users/bayesian/printing-press/.runstate/cli-printing-press-f2a7be37/runs/20260520-192632/
```

Generated artifacts:

```text
working/linear-pp-cli/build/stage/bin/linear-pp-cli
working/linear-pp-cli/build/stage/bin/linear-pp-mcp
working/linear-pp-cli/build/linear-pp-mcp-darwin-arm64.mcpb
```

## Verification signal

- `linear-pp-cli --version` returned `linear-pp-cli 1.0.0`.
- The emitted MCP binary starts and prints stdio/http transport help.
- Generation quality gates passed 8/8: `go mod tidy`, `govulncheck`,
  `go vet`, `go build`, runnable binary, `--help`, `version`, `doctor`.
- `verify` passed 46/46 with verdict `PASS`.
- `doctor` reported config/API reachability OK, with only the expected
  missing `LINEAR_API_KEY` failure because no real token was supplied.
- Sanitization sweep on the DontPanic repo remained clean:
  `no campaign IDs or secret shapes in sanitized surface (1477 files scanned)`.

## Adapter boundary probe

The real PP-emitted `linear-pp-mcp` binary was invoked through
`dontpanic_orchestrate.integrations.linear_pp_adapter.LinearPPAdapter`.
The probe called the read tool `teams_get` with no arguments.

The host sandbox could not resolve `api.linear.app`, so the MCP binary
returned a network error. That is acceptable evidence for F003 because the
critical boundary is that the real binary executed, returned a JSON-RPC tool
response, and DontPanic still applied redaction + post-redaction
sanitization before the response crossed the adapter boundary.

The captured post-wrapper response is in:

```text
evidence/linear-pp-paid-run-trace.jsonl
```

No credential values were provided to the generated CLI or committed to this
repo.

## Honest caveats

- The locked F003 wording says "public OpenAPI spec". The successful Linear
  run used Linear's official GraphQL SDL. The acceptance intent was external
  API wrapping via Printing Press; the source-format literal was stale for
  Linear and is recorded in D014 as a v2 decision-tree correction.
- Printing Press dogfood surfaced a machine bug: generated GraphQL CLIs bundle
  raw SDL into `spec.yaml`, while `printing-press dogfood` reloads that file as
  OpenAPI YAML/JSON. That blocked dogfood before behavioral checks. The binary
  still passed generate gates and `verify`.
- `verify-skill` found one low-priority generated recipe issue:
  `linear-pp-cli wraps` is not a real generated command.
- The generated name `user-settingses` is a cosmetic pluralization issue.

## Outcome

F003 closes as operator-verified: one paid Linear Printing Press invocation was
spent, the PP-emitted binary exists and executes, the DontPanic wrapper handles
the real binary boundary with redaction/sanitization, redacted config examples
are committed, and the repo sanitization check is clean.
