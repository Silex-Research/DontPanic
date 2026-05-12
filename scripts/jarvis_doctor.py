#!/usr/bin/env python3
"""Legacy alias for ``scripts/dontpanic_doctor.py``.

Kept for backward compatibility with operators / CI scripts that already
invoke ``python scripts/jarvis_doctor.py``. New invocations should call
``scripts/dontpanic_doctor.py`` directly. This alias is non-removing in
v1; removal is gated by plan
2026-05-04-001-refactor-canonical-dontpanic-module D006.

In addition to the ``python scripts/jarvis_doctor.py`` operator path,
``import jarvis_doctor`` must yield the same public API as
``import dontpanic_doctor`` so downstream callers (notably the
``dontpanic doctor`` CLI wrapper) keep working through the rename window.
"""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

# Re-export the canonical doctor API. scripts/ may not yet be on sys.path
# (e.g. when this file is imported by a console-script entry point), so
# add it for the duration of the import.
_SCRIPTS_DIR = Path(__file__).resolve().parent
_added_path = False
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))
    _added_path = True
try:
    from dontpanic_doctor import *  # noqa: F401,F403  # legacy alias re-export
    from dontpanic_doctor import (  # noqa: F401  # explicit re-export for tooling
        CheckResult,
        check_plan_cohesion,
        check_quota_caps,
        compute_strict_exit,
        main,
        render_json,
        render_text,
        run_all_checks,
        validate_plan_cohesion,
    )
finally:
    if _added_path:
        sys.path.remove(str(_SCRIPTS_DIR))

if __name__ == "__main__":
    print(
        "[notice] scripts/jarvis_doctor.py is now an alias for "
        "scripts/dontpanic_doctor.py — please update your invocation.",
        file=sys.stderr,
    )
    runpy.run_path(str(_SCRIPTS_DIR / "dontpanic_doctor.py"), run_name="__main__")
