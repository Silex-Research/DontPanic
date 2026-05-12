# Firebase sync daemon — operator runbook

Plan 2026-05-09-004 F002. Local-side bridge that mirrors the DontPanic
state projection (`dontpanic state snapshot --json`) into Firestore so
the opt-in realtime dashboard (F001) sees live state.

This document covers running the daemon persistently. The real
`jarvis-a6ee1` deploy + the Cloud Functions mutation path are deferred
to F003-F005 per parent_acceptance_item (plan D007).

## Adapter boundary (D001)

This adapter consumes the projection. It does **not** import
`dontpanic_orchestrate.*`. Snapshots are read via subprocess to the
public `dontpanic state` CLI. State changes ALWAYS flow the other way
through MCP (plan D003) — this daemon is one-way.

## Quick start (foreground, for testing)

```bash
# Default: poll every 10s, sync every stream, write to real Firestore.
python -m firebase_adapter.dontpanic_sync start \
    --project-id <your_project_id> \
    --plans-root /path/to/repo/docs/plans

# Dry-run mode uses an in-memory stub. No Firestore credentials needed.
python -m firebase_adapter.dontpanic_sync start \
    --project-id demo \
    --once --dry-run --verbose

# Only sync the streams the dashboard cares about (skip heavy
# evidence_refs + decisions streams).
python -m firebase_adapter.dontpanic_sync start \
    --project-id <pid> \
    --include plans,gates,inbox,supervisors,quota
```

CLI flags:

| flag | default | purpose |
| --- | --- | --- |
| `--project-id` | (required) | Becomes the Firestore parent doc: `projects/<id>/<stream>`. |
| `--interval` | `10` | Poll cadence in seconds. Plan D004 budget: 5–15s. |
| `--include` | (all) | Comma-separated subset of streams. Excluded streams are NOT deleted from Firestore. |
| `--plan` | (all) | If set, scope the projection to a single plan_id. |
| `--plans-root` | `<cwd>/docs/plans` | Forwarded to the snapshot CLI. |
| `--redact-level` | `operator` | `public` / `operator` / `full`. |
| `--once` | off | Run one cycle and exit. Useful for cron. |
| `--max-iterations` | (unlimited) | Stop after N cycles. |
| `--dry-run` | off | Use the in-memory Firestore stub. No network. |
| `--verbose` | off | DEBUG log level. |

## Credentials (F005 deferred)

The default Firestore client is initialized with Application Default
Credentials. Real `jarvis-a6ee1` writes are deferred to F005; until the
SA key is provisioned, run with `--dry-run`.

## launchd (macOS — recommended)

Save to `~/Library/LaunchAgents/com.dontpanic.firebase-sync.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
 "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.dontpanic.firebase-sync</string>

  <key>ProgramArguments</key>
  <array>
    <string>/usr/local/bin/python3</string>
    <string>-m</string>
    <string>firebase_adapter.dontpanic_sync</string>
    <string>start</string>
    <string>--project-id</string>
    <string>YOUR_PROJECT_ID</string>
    <string>--plans-root</string>
    <string>/Users/YOU/path/to/DontPanic/docs/plans</string>
    <string>--interval</string>
    <string>10</string>
  </array>

  <key>EnvironmentVariables</key>
  <dict>
    <key>PYTHONPATH</key>
    <string>/Users/YOU/path/to/DontPanic/scripts</string>
    <key>GOOGLE_APPLICATION_CREDENTIALS</key>
    <string>/Users/YOU/.config/dontpanic/firebase-sa.json</string>
  </dict>

  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key>
  <string>/Users/YOU/Library/Logs/dontpanic-firebase-sync.log</string>
  <key>StandardErrorPath</key>
  <string>/Users/YOU/Library/Logs/dontpanic-firebase-sync.err</string>
</dict>
</plist>
```

Load / unload:

```bash
launchctl load   ~/Library/LaunchAgents/com.dontpanic.firebase-sync.plist
launchctl unload ~/Library/LaunchAgents/com.dontpanic.firebase-sync.plist
tail -f ~/Library/Logs/dontpanic-firebase-sync.log
```

## systemd (Linux)

Save to `~/.config/systemd/user/dontpanic-firebase-sync.service`:

```ini
[Unit]
Description=DontPanic Firebase sync daemon (plan 2026-05-09-004 F002)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
Environment=PYTHONPATH=%h/code/DontPanic/scripts
Environment=GOOGLE_APPLICATION_CREDENTIALS=%h/.config/dontpanic/firebase-sa.json
ExecStart=/usr/bin/python3 -m firebase_adapter.dontpanic_sync start \
    --project-id YOUR_PROJECT_ID \
    --plans-root %h/code/DontPanic/docs/plans \
    --interval 10
Restart=on-failure
RestartSec=5s

[Install]
WantedBy=default.target
```

Enable + start:

```bash
systemctl --user daemon-reload
systemctl --user enable --now dontpanic-firebase-sync.service
journalctl --user -u dontpanic-firebase-sync.service -f
```

## Operational notes

- **No persisted cache.** The daemon's `last_written` hash cache is
  process-local. On restart the first poll re-upserts every doc; this
  is idempotent on the consumer side, so it's safe — just one extra
  write batch per restart.
- **Failure backoff.** Per-doc errors are logged and counted; the daemon
  keeps polling. Snapshot-CLI errors trigger a one-interval sleep.
- **No deletes on stream toggle.** Dropping a stream from `--include`
  leaves its docs untouched in Firestore. To wipe them, run a one-off
  pass against an empty fixture or clean via the Firebase console.
- **Real-Firestore latency** (≤30s end-to-end target) is verified in
  F005 once credentials are reactivated. Local-fixture verification
  lives in `scripts/firebase_adapter/tests/test_dontpanic_sync.py`.
