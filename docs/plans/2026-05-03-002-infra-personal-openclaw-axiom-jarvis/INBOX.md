# INBOX

- 2026-05-03: Plan created from operator decision to simplify Axiom into a personal OpenClaw + DontPanic + dashboard system.
- 2026-05-03: Installed Homebrew `node@24` and `openclaw@2026.5.2`.
- 2026-05-03: Initialized `~/.openclaw/workspace` and replaced default workspace docs with trimmed personal Axiom/OpenClaw operating docs.
- 2026-05-03: Applied local secure OpenClaw baseline: loopback gateway, token auth, messaging tool profile, workspace-only filesystem, host exec denied, elevated tools disabled, group channels allowlist-only.
- 2026-05-03: Disabled optional discovery/control plugins for first baseline: `bonjour`, `browser`, `device-pair`, `phone-control`, `file-transfer`, `talk-voice`.
- 2026-05-03: Verified live gateway health and deep security audit. Final live audit: 0 critical, 1 warning for reverse-proxy trusted headers; warning only matters if Control UI is exposed through a reverse proxy.
- 2026-05-03: Updated plan language from Jarvis to DontPanic after the first rename slice. Historical repo/path references may still use `Jarvis`; preferred command in new docs is `dontpanic`, with `jarvis` treated as a legacy alias.
- 2026-05-03: Incorporated commit `1db2464` future shape. New integration work should prefer `~/.dontpanic/config.json`, `~/.dontpanic/projects.json`, per-project `.dontpanic/dontpanic.json`, `DONTPANIC_*` env vars, and `python -m dontpanic_orchestrate`. Legacy Jarvis paths/env/module names are compatibility fallbacks.
- Pending human action: provide Discord bot token/application id/guild id/channel ids, Telegram bot token/user id, and preferred model/auth route for OpenClaw.
