---
globs: "*.sh,*.bash,*.zsh"
description: Shell script conventions for build scripts, CI/CD, hooks, deploy scripts
---

# Shell Rules

## Header
- Always start with `#!/bin/bash` (or `#!/bin/zsh` if zsh-specific)
- Use `set -euo pipefail` for scripts (not for interactive or sourced files)
- Add a one-line comment describing what the script does

## Naming
- Files: `kebab-case.sh` (e.g., `build-and-deploy.sh`)
- Variables: `UPPER_SNAKE_CASE` for exported/environment, `lower_snake_case` for local
- Functions: `snake_case`

## Safety
- Always quote variables: `"$VAR"` not `$VAR` — prevents word splitting
- Use `[[ ]]` over `[ ]` for conditionals (safer, more features)
- Use `$(command)` over backticks for command substitution
- Check command existence before using: `command -v jq >/dev/null 2>&1 || { echo "jq required"; exit 1; }`
- Use `mktemp` for temporary files, clean up in a trap
- Trap EXIT for cleanup: `trap 'rm -f "$tmpfile"' EXIT`

## Error Handling
- Exit with meaningful codes: 0=success, 1=general error, 2=usage error
- Print errors to stderr: `echo "Error: ..." >&2`
- Use `|| { echo "Failed"; exit 1; }` for critical commands
- No silent failures — if a command can fail, handle it

## Input/Output
- Use `jq` for JSON processing (the hooks use this heavily)
- Use `getopts` or manual parsing for flags, not positional args for complex scripts
- Default variables with `${VAR:-default}` pattern
- Read stdin with `INPUT=$(cat)` when piping JSON (as in hooks)

## Portability (macOS focus)
- Use `brew`-installed GNU tools when needed (`gawk`, `gsed`)
- macOS `sed` is BSD — use `sed -i ''` not `sed -i` for in-place edits
- macOS `date` differs from GNU — use `date -u +%Y-%m-%dT%H:%M:%SZ` for ISO format
- Prefer `printf` over `echo -e` for portability

## Security
- No secrets in script source — use environment variables
- No `eval` on untrusted input
- No `curl | bash` without verification
- Validate all external input before using in commands
- Use `--` to terminate flag parsing before user-provided arguments

## Patterns to Avoid
- Parsing `ls` output — use globs or `find`
- `cat file | grep` — use `grep pattern file` directly
- `cd` without checking success — use `cd dir || exit 1`
- Pipes that hide exit codes — use `set -o pipefail` or `PIPESTATUS`
