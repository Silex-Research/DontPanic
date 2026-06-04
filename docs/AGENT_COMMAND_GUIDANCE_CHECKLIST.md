# Adding or Changing an Agent-Facing Command

DontPanic's agent command surface is **self-describing**: root help, per-command
help footers, the machine guidance JSON (`dontpanic agent commands`), and the
local guide (`dontpanic agent guide`) are all projected from one place —
`scripts/dontpanic_orchestrate/command_guidance.py` — over the validator
vocabulary in `scripts/dontpanic_orchestrate/command_validation.py`.

Because everything is a projection over those two modules, adding a CLI command
without updating them produces **drift**: an agent sees a command in `--help`
with no safe operating policy, or the guidance inventory raises a `KeyError`.
The F007 gate (`tests/test_f007_command_guidance_gate.py`) turns that drift into
a loud test failure. This checklist is how you keep the gate green.

> TL;DR: a new top-level command needs (1) a validator spec, (2) a command
> class, (3) at least one validating example. A *workflow-critical* command also
> needs (4) a help epilog and (5) an entry in `WORKFLOW_CRITICAL_HELP_COMMANDS`.

## When you add or rename a top-level command

Do all of these in the **same PR** as the `cli.py` change (the validator's
purity contract, D021, makes drift detection a manual-review discipline):

1. **Validator vocabulary** — add a `SubcommandSpec` to `_VOCABULARY` in
   `command_validation.py` mirroring the real argparse shape (positionals,
   `bool_flags`, `value_flags`, `required_flags`, nested `subcommands`). This is
   what `command_validation.known_subcommands()` reports, and it is the source
   of truth the guidance inventory projects over.

2. **Command class** — add the command to `_CLASS_BY_COMMAND` in
   `command_guidance.py`, picking the closed `CommandClass` for its **most
   common entry point**. If its *riskiest* subcommand is more dangerous than
   that base (e.g. a read-only command with a hidden config write), add that
   subcommand to `_SUBCOMMAND_CLASS_OVERRIDES` so the inventory advertises the
   riskiest supported path via `_effective_class`. Never let a command look
   safer than one of its real subcommands.

3. **Example(s)** — add at least one safe `CommandExample` to
   `_EXAMPLES_BY_COMMAND`. Every example's `argv` must begin with the command
   path, and **must pass `command_validation.validate_command_tokens`** — the
   F007 gate validates every surfaced example, so a malformed or copy-paste-
   broken example fails the build. Use `<placeholder>` tokens for operator
   inputs (they validate as positionals / flag values).

4. **Optional honest text** — if the class-derived predecessor hints or
   escalation rule misdescribe the command (common for commands whose riskiest
   subcommand differs from the base), add a per-command override to
   `_PREDECESSORS_BY_COMMAND` and/or `_ESCALATION_BY_COMMAND`.

After steps 1–3, `command_guidance.missing_guidance_commands()` returns the
empty set and `command_guidance_inventory()` builds without raising.

## When the command is workflow-critical

A *workflow-critical* command is one an interactive agent routinely lands on and
must not auto-run blindly (lifecycle mutation, dispatch/paid work, etc.) or one
that anchors a class (read-only inspection, diagnostics, config, human handoff).
For those:

5. **Help epilog** — wire `command_guidance.command_help_agent_snippet("<cmd>")`
   as the argparse `epilog` for that command's parser (see existing wiring in
   `cli.py` for `doctor`, `dispatch-from-plan`, `plan`, `setup`, `next`, and in
   `dashboard.py` for `dashboard`). This renders the class-specific
   agent-guidance footer on `dontpanic <cmd> --help`.

6. **Coverage constant** — add the command to
   `command_guidance.WORKFLOW_CRITICAL_HELP_COMMANDS`, and register how to reach
   its help in the `_HELP_ARGV` map in
   `tests/test_f007_command_guidance_gate.py`. The gate asserts those two sets
   match and that every listed help page renders the footer, so neither can
   drift from the other.

## Verify

```bash
PYTHONPATH=scripts pytest \
  scripts/dontpanic_orchestrate/tests/test_f007_command_guidance_gate.py \
  scripts/dontpanic_orchestrate/tests/test_command_validation_f001.py \
  scripts/dontpanic_orchestrate/tests/test_f005_workflow_help_snippets.py \
  scripts/dontpanic_orchestrate/tests/test_agent_command_guidance.py -q
```

If `test_every_validator_command_has_guidance_today` fails, you added a command
to the validator without a class/example entry (step 2/3). If a
`test_workflow_critical_help_carries_agent_guidance_section` case fails, the help
epilog wiring is missing (step 5). If an example fails validation, fix the
example's shape against the real argparse surface (step 3).
