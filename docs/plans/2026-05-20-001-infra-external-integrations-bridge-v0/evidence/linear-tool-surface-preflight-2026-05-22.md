# Linear generated MCP tool-surface preflight

Date: 2026-05-22

Context: P10 F003's paid `/printing-press linear` invocation already happened
and produced a generated MCP binary under Printing Press runstate. This preflight
checked whether the generated tool names satisfy the bridge plan's committed
Linear mapping example before any live `dontpanic plan resync` attempt.

## Command

```bash
rg 'NewTool\("' \
  $HOME/printing-press/.runstate/cli-printing-press-f2a7be37/runs/20260520-192632/working/linear-pp-cli/internal/mcp/tools.go
```

## Generated MCP tools

The generated MCP surface exposes:

- `attachments_get`
- `audit-entry-types_get`
- `auth-resolver-responses_get`
- `authentication-session-responses_get`
- `email-intake-addresses_get`
- `favorites_get`
- `initiative-relations_get`
- `initiative-to-projects_get`
- `initiatives_get`
- `integrations_create`
- `integrations_delete`
- `issue-priority-values_get`
- `organizations_get`
- `project-labels_get`
- `project-milestones_get`
- `project-relations_get`
- `project-statuses_get`
- `projects_get`
- `release-notes_get`
- `release-pipelines_get`
- `release-stages_get`
- `releases_get`
- `roadmap-to-projects_get`
- `roadmaps_get`
- `teams_get`
- `templates_get`
- `user-settingses_get`
- `users_get`
- `sql`
- `context`

## Mismatch

The bridge plan's committed mapping example currently names:

```json
{
  "read_issue_tool": "issue",
  "push_status_tool": "issueUpdate"
}
```

Neither `issue` nor `issueUpdate` exists in the generated MCP tool surface.
`linear-pp-cli which issue --agent` matched only `issue-priority-values get`,
which is not the issue read/update contract the bridge needs.

## Decision

Do not attempt a live Linear `push_status` / `resync` with this generated binary.
The existing F001/F002 fixture tests remain useful because they prove the
DontPanic-side category contract, evidence records, dry-run behavior, and
failure paths. The live Linear path needs a follow-up before real mutation:

1. regenerate or extend the PP Linear adapter so it exposes a read-one-issue
   tool and an explicit status-update tool; or
2. revise the Linear wrapper/mapping contract around the generated `sql` +
   read-only tools and keep `push_status` unsupported for Linear v0.

No additional paid Printing Press invocation was made for this preflight.
