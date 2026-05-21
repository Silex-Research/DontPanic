# F002 close-out: agent-conventions publication

Date: 2026-05-21

## Operator decision

F002 is closed as an operator-handled cross-repo handoff. The missing upstream
repository was created at `Silex-Research/agent-conventions`, the local
`agent-conventions` checkout was wired to `git@github.com:Silex-Research/agent-conventions.git`,
and the schema history was pushed with tags.

The original F002 acceptance targeted the v1.9.0 orchestration schema release.
That tag is now visible on the remote:

- `v1.9.0` -> `834780496d3b3a534bc2eeed029916fcbba0d49d`

Because DontPanic's embedded `claude/shared` mirror had already advanced to
`VERSION=1.10.0`, the public repo was also synced forward and tagged so the new
public source of truth is not stale on its first day:

- `master` -> `024ecb614680c347bc329f3bc19be0f3a4644dcd`
- `v1.10.0` -> `024ecb614680c347bc329f3bc19be0f3a4644dcd`

## Verification

- `agent-conventions` remote: `git@github.com:Silex-Research/agent-conventions.git`
- `python3 scripts/test_validator_dispatch.py`: 4/4 passed
- `python3 scripts/test_objective_contract.py`: 7/7 passed
- `python3 scripts/roundtrip_test.py .../2026-05-19-003-fix-plan-schema-orchestration-fields`: schema-valid for `plan.md` and `features.json`; reports only the known compact-JSONL formatting drift in that plan's first two `decisions.jsonl` rows.
- `git ls-remote --tags origin refs/tags/v1.9.0 refs/tags/v1.10.0`: both tags present.
- `git ls-remote --heads origin master`: `master` present at `024ecb614680c347bc329f3bc19be0f3a4644dcd`.

## Notes

The first attempted operator close-out used `dontpanic close` and wrote to the
plan's generic closeout/signoff filenames, which are already owned by F003.
Those historical F003 artifacts were restored, and this feature-specific memo
is the F002 evidence record.
