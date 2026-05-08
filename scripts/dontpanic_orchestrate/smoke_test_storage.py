"""F002 acceptance harness — uploads a fixture, retrieves via signed URL, asserts 200.

Acceptance per parent plan 2026-04-19-001 features.json F002:
  'Python script uploads fixture to {project}://evidence/test.json
   and retrieves via 1-hour signed URL'

Reads target project from DONTPANIC_FIREBASE_PROJECT, with legacy
JARVIS_FIREBASE_PROJECT fallback (see firebase_client.py).
Historical project ID notes are tracked in the bootstrap sub-plan's
decisions.jsonl, not in this file.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
import urllib.request
from pathlib import Path

from dontpanic_orchestrate.firebase_client import upload_and_sign


def main() -> int:
    timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    blob_path = f"evidence/smoke-test-{timestamp}.json"
    fixture = {
        "test": "F002 acceptance",
        "timestamp": timestamp,
        "purpose": "verify upload + signed-URL retrieval round-trip",
    }
    payload = json.dumps(fixture, indent=2).encode("utf-8")

    print(f"[1/3] Uploading {len(payload)} bytes to {blob_path}...")
    gs_uri, url = upload_and_sign(
        blob_path, payload, content_type="application/json", ttl_seconds=3600
    )
    print(f"      gs URI:     {gs_uri}")
    print(f"      signed URL: {url[:80]}...")

    print("[2/3] Fetching signed URL...")
    with urllib.request.urlopen(url, timeout=15) as resp:  # noqa: S310  # smoke-test fetch of operator-supplied signed URL
        status = resp.status
        body = resp.read()

    print(f"      HTTP {status}, {len(body)} bytes received")

    print("[3/3] Verifying round-trip...")
    received = json.loads(body)
    assert received == fixture, f"mismatch: sent {fixture}, got {received}"  # noqa: S101  # smoke-test script abort-fast on storage round-trip mismatch
    assert status == 200, f"expected 200, got {status}"  # noqa: S101  # smoke-test script abort-fast on non-200

    # Persist evidence log
    evidence_dir = (
        Path(__file__).resolve().parents[2]
        / "docs"
        / "plans"
        / "2026-04-25-001-infra-jarvis-firebase-bootstrap"
        / "evidence"
    )
    evidence_dir.mkdir(parents=True, exist_ok=True)
    log_path = evidence_dir / f"smoke-test-{timestamp}.log"
    log_path.write_text(
        f"timestamp: {timestamp}\ngs_uri: {gs_uri}\nhttp_status: {status}\nbytes: {len(body)}\nresult: PASS\n"
    )

    print(f"\n✓ F002 acceptance PASS — log: {log_path.relative_to(Path.cwd())}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
