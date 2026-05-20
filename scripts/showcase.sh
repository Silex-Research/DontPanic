#!/bin/bash
# Operator one-line wrapper for the dogfood showcase regen.
# Plan 2026-05-19-005 F002. Forwards any extra args to the CLI.
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

exec python -m dontpanic_orchestrate showcase regen --all "$@"
