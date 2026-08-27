# Operator execution gaps

Inbox for gaps that make DontPanic hard to run for anyone who is not Anthony.
Prioritize here, then cut a plan. Do not open a pile of GitHub issues.

## Thesis

Most execution pain is not a missing supervisor feature. The supervisor already
hands implementer output to the other vendor. People do not know that, so they
become the clipboard between Claude and Codex.

The fix for other users is to make this obvious: sit an operator agent on top
of DontPanic (Grok Bot, Hermes, OpenClaw, or a thin CLI watcher) to approve
reversible gates, re-dispatch, and copy between harnesses only when the
supervisor did not. DontPanic stays the safety layer. It does not become a
hosted chat runtime. See `AGENT_QUICKSTART.md`.

Guardrails (global breaker, dirty-state, default feature) are to investigate.
Honor them when they are saving tokens or stopping a real mess. Do not honor
them blindly.

## Open (2026-08-26, photo-containment run)

| Pri | Gap | Why other users hit it |
|---|---|---|
| P0 | Operator story is missing | Users paste Codex into Claude. Document and demo: Grok/Hermes/OpenClaw sits `approve` / `dispatch-from-plan`. Clipboard is fallback, not the product. |
| P0 | `dispatch-from-plan` dry-run hides the global breaker | `--confirm` then dies at 0 rounds. Dry-run must print the hard stop. |
| P0 | Dispatch defaults to `F001` and the current project checkout | Easy to "resume" the wrong feature on the wrong worktree. Require `--feature` when more than one feature exists; resolve the plan worktree explicitly. |
| P1 | Global breaker relief time is 24h from the first of three `iteration_cap` hits | Operators read the last run's clock and think the window just started. Print both: last trip, and when the oldest cap ages out. |
| P1 | Global breaker blocks a correction after real progress | Tonight: contract + patch committed, correction never started. Investigate whether that saves tokens or is ceremony. If ceremony, allow one correction pass after a new contract SHA. |
| P1 | `passes=false` mixes code fail with missing signoff | DONE 2026-08-27: remaining-ceremony print on what-now / dry-run / post-volley. Ledger field unchanged. |
| P1 | Codex auditor auto-loads CodeRabbit review skill | Sitting `codex exec` as auditor pulled `coderabbit-review` and opened a browser login. Independent audit is the diff + tests, not a sixth vendor. Prompt must forbid CodeRabbit; do not make login a gate. |
| P1 | Split `~/.dontpanic` vs `~/.jarvis` (`projects.json` divergent) | `what-now` nags homes instead of the plan. One home. |
| P1 | Global breaker has no reset command | `dontpanic approve … breaker:global_circuit_breaker` is refused. Operators wait 24h or edit `~/.jarvis/breaker_history.jsonl`. Tonight Anthony authorized 3 resets after a source attempt; that is still a file edit, not a CLI. |
| P2 | Leftover DerivedData in the worktree poisons Codex grep | F004 left `F004Derived/` (4.3G) in `/private/tmp/Glam`. Next `codex exec` dumped 38MB manifest lines and burned a long F012 pass. Delete derived dirs after a pass; add them to the operator ignore list. |
| P2 | Grok Bot git commit cannot sign via `op-ssh-sign` | `error: 1Password: failed to fill whole buffer` / `fatal: failed to write commit object`. Codex `codex exec` on the same Mac can still commit. Operator should have Codex write ledger commits, or unlock 1Password SSH signing, not click a keychain dialog. |
| P2 | Mid-run machine move | Plan dir in git is portable. Breaker history, worktree paths, env files, and Xcode are not. Tell operators: push for receipt, resume on the same machine. |

## Rule for Thanos / any Grok operator

When you find a gap, append a row here the same day. Do not wait for a Styln
or Spin chat to remember it. Prioritize by whether a stranger would get stuck
the same way.

Do not wait for the human to continue a live plan. Heartbeat is when a feature
lands, or for a UX / token wall. After any implementer or auditor stop, start
the next mechanical step on the same wake. Idle after a finished pass is
operator failure, not a DontPanic product gap.
