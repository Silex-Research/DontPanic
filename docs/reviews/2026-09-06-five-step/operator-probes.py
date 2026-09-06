import subprocess, tempfile, importlib.util, sys, datetime, json
from pathlib import Path

repo = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(repo / "scripts"))


def load(name, path):
    code = subprocess.run(
        ["git", "show", "438250e2a0504366d5456c44e7831a182285488d:" + path],
        cwd=repo,
        capture_output=True,
        check=True,
    ).stdout
    p = Path(tempfile.mkdtemp()) / (name + ".py")
    p.write_bytes(code)
    spec = importlib.util.spec_from_file_location(name, p)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


cb = load("operator_breaker_review", "scripts/dontpanic_orchestrate/circuit_breakers.py")
now = datetime.datetime(2026, 9, 6, 12, tzinfo=datetime.timezone.utc)
cb._now = lambda: now
cb._read_history = lambda: [
    {"at": now.replace(hour=h).isoformat(), "kind": "iteration_cap"} for h in [8, 9, 10, 11]
]
r = cb.evaluate_global(threshold=3)
print(
    json.dumps(
        {
            "case": "4 hits; threshold 3; 24h window",
            "reported_lifts_at": str(r.lifts_at),
            "threshold_expiry_boundary": str(now.replace(hour=9) + datetime.timedelta(days=1)),
            "hits": r.hits_in_window,
        }
    )
)
rc = load("operator_ceremony_review", "scripts/dontpanic_orchestrate/remaining_ceremony.py")
p = Path(tempfile.mkdtemp())
(p / "failed-test.txt").write_text("FAILED test_journey; exit status 1\n")
print(
    json.dumps(
        {
            "case": "existing test_output explicitly contains failure",
            "reported_status": rc._tests_status(
                p, {"evidence_refs": [{"type": "test_output", "uri": "failed-test.txt"}]}, []
            ),
        }
    )
)
