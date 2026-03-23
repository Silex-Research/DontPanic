---
globs: "*.py,*.pyi"
description: Python conventions for scripts, Databricks notebooks, ML pipelines, tooling
---

# Python Rules

## Naming
- Files: `snake_case.py`
- Classes: `PascalCase`
- Functions/variables: `snake_case`
- Constants: `UPPER_SNAKE_CASE`
- Private: single underscore prefix `_internal_helper`
- No double underscore prefix (name mangling) unless intentional

## Error Handling
- Define custom exceptions inheriting from domain-specific base (`class PipelineError(Exception)`)
- Catch specific exceptions, never bare `except:`
- Use `contextlib.suppress(SpecificError)` over empty except blocks
- Log errors with structured context (`logger.error("msg", extra={...})`)
- No `sys.exit()` in library code — raise exceptions, let callers decide

## Types
- Type hints on all function signatures (args + return)
- Use `from __future__ import annotations` for forward references
- Prefer `collections.abc` types (`Sequence`, `Mapping`) over `list`, `dict` in signatures
- Use `TypedDict` for structured dicts, `dataclass` for data objects
- `Optional[X]` is `X | None` — use the `|` syntax on Python 3.10+

## Imports
- Group: stdlib → third-party → local, separated by blank lines
- Absolute imports only — no relative imports
- No `from module import *`

## Testing
- Framework: pytest
- Test files: `test_*.py` or `*_test.py`
- Use fixtures over setup/teardown methods
- Parametrize repetitive test cases with `@pytest.mark.parametrize`
- No mocking builtins (open, os.path) — use dependency injection or tmp_path fixture

## Tooling
- Package manager: `uv` (preferred) or `pip`
- Formatter: `ruff format`
- Linter: `ruff check`
- Type checker: `mypy` or `pyright`

## Security
- No `eval()`, `exec()`, or `pickle.loads()` on untrusted data
- Use `subprocess.run(..., shell=False)` — never `shell=True` with user input
- Parameterize all SQL queries — no f-string SQL
- No secrets in source — use environment variables or secret managers
- Pin dependency versions in requirements files

## Patterns to Avoid
- Mutable default arguments (`def f(x=[])`) — use `None` + assignment
- Global mutable state — pass state explicitly
- Deep inheritance hierarchies — prefer composition
- `type()` checks — use `isinstance()` or structural typing
