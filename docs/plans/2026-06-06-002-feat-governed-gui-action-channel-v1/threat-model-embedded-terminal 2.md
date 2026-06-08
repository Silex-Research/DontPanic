# Threat model — embedded terminal execution surface (T-series)

The operator console (plan 2026-06-06-001) is read-only. The **embedded terminal**
adds a real login shell, reachable from the browser over a WebSocket, that becomes
the **execution plane for the GUI + agents**. This is a new trust boundary and the
single most sensitive capability in DontPanic, so it is governed here.

## Asset being protected
A real, **unrestricted** local shell running as the operator, cwd = the served
repo root. There is intentionally **no command allowlist** — a terminal is a full
shell by definition. The whole defense is *who is allowed to open one*.

## Default posture
**OFF.** A plain `dontpanic dashboard serve` (and the static file server, and every
test) never spawns a shell. The shell exists only when the operator passes the
explicit `--enable-terminal` flag. There is **no config/state key** that turns it
on — verified by `test_no_auto_enable_from_config_or_build`.

## Threats → mitigations (each has a test)
| Threat | Mitigation | Test |
|---|---|---|
| A remote/cross-site page opens a shell | bind is **loopback-only**; `/pty` checks the **Origin** header against the served origin | `test_loopback_only_enforced_even_with_terminal`, `test_origin_check_rejects_foreign_origin` |
| A drive-by request with no credential | `/pty` requires the **per-serve session token** (minted at serve start, 32 bytes urlsafe) | `test_token_required` |
| Terminal silently present | endpoints are **404 / `enabled:false`** unless `--enable-terminal`; an **audit line** is logged when armed; the dock shows a visible **warning + scope** | `test_off_by_default…`, `test_audit_line_names_the_boundary`, `terminal-dock.test.js` |
| Auto-enable creeping in via config | `enable_terminal` is a CLI/param only; not a `build()`/config field | `test_no_auto_enable_from_config_or_build` |
| Protocol/parsing bugs in the bridge | RFC-6455 handshake + framing unit-tested; PTY lifecycle reaps the shell on close; resize bounded | `test_pty_bridge_t.py` (handshake vector, frame round-trip, partial/extended frames, lifecycle, resize) |

## Residual risk (accepted for local-first v0)
Any process running **as the same user on this machine** can read the localhost
session token (e.g. by fetching `/terminal/session`) and then open a shell. This is
inherent to *any* localhost terminal: the token defends against cross-site and
no-credential drive-bys, not against a local process already running as you. It is
mitigated by **off-by-default** + the machine being the operator's own. Hardening
(e.g. a unix-socket handshake, OS keychain token, per-connection user confirm) is a
follow-on if/when DontPanic runs on shared/multi-user hosts.

## Visible UI contract (when armed)
- dock warning: `⚠ Terminal enabled · local shell · <repo> · unrestricted commands`
- dock scope: `Shell: <repo> · session active`
- server stderr audit: `TERMINAL ENABLED — local shell at <cwd>, unrestricted commands, guarded by loopback + Origin + per-serve token. …`
