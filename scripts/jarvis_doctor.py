#!/usr/bin/env python3
"""Legacy alias for ``scripts/dontpanic_doctor.py``.

Kept for backward compatibility with operators / CI scripts that already
invoke ``python scripts/jarvis_doctor.py``. New invocations should call
``scripts/dontpanic_doctor.py`` directly. This alias is non-removing in
v1; removal is gated by plan
2026-05-04-001-refactor-canonical-dontpanic-module D006.
"""

import runpy
import sys

if __name__ == "__main__":
    print(
        "[notice] scripts/jarvis_doctor.py is now an alias for "
        "scripts/dontpanic_doctor.py — please update your invocation.",
        file=sys.stderr,
    )
    runpy.run_path("scripts/dontpanic_doctor.py", run_name="__main__")
