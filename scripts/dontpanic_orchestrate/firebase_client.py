"""Firebase Admin SDK wrapper for DontPanic.

Project, bucket, and SA key path are resolved from environment variables
(no hardcoded campaign defaults). Required:

    DONTPANIC_FIREBASE_PROJECT      — required
    DONTPANIC_FIREBASE_BUCKET       — optional, defaults to {project}-evidence
    DONTPANIC_SERVICE_ACCOUNT_KEY   — optional, defaults to
                                       <repo>/.secrets/{project}-orchestrator.json

Legacy JARVIS_* names remain read-compatible during the staged rename.

Used by:
- smoke_test_storage.py (F002 acceptance)
- supervisor.py (writes evidence > 100KB to Storage, embeds signed URLs in features.json)
"""

from __future__ import annotations

import datetime as dt
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import firebase_admin
from firebase_admin import credentials, storage
from google.cloud.storage import Blob, Bucket

_app: firebase_admin.App | None = None


def _required_project() -> str:
    project = os.environ.get("DONTPANIC_FIREBASE_PROJECT") or os.environ.get(
        "JARVIS_FIREBASE_PROJECT"
    )
    if not project:
        raise RuntimeError(
            "DONTPANIC_FIREBASE_PROJECT is not set. Set it explicitly, e.g.:\n"
            "    export DONTPANIC_FIREBASE_PROJECT=your-project-id\n"
            "Or run: scripts/bootstrap.sh --project your-project-id "
            "--billing-account XXXXXX-XXXXXX-XXXXXX"
        )
    return project


def _default_bucket(project: str) -> str:
    return (
        os.environ.get("DONTPANIC_FIREBASE_BUCKET")
        or os.environ.get("JARVIS_FIREBASE_BUCKET")
        or f"{project}-evidence"
    )


def _default_key_path(project: str) -> Path:
    explicit = os.environ.get("DONTPANIC_SERVICE_ACCOUNT_KEY") or os.environ.get(
        "JARVIS_SERVICE_ACCOUNT_KEY"
    )
    if explicit:
        return Path(explicit)
    return Path(__file__).resolve().parents[2] / ".secrets" / f"{project}-orchestrator.json"


def init_app(key_path: Path | None = None, bucket: str | None = None) -> firebase_admin.App:
    """Initialize the firebase_admin app once. Idempotent.

    Resolves project/bucket/key from DONTPANIC_* env vars, with legacy
    JARVIS_* fallback; raises with remediation if no project is set.
    """
    global _app
    if _app is not None:
        return _app

    project = _required_project()
    bucket = bucket or _default_bucket(project)
    key_path = key_path or _default_key_path(project)
    if not key_path.exists():
        raise FileNotFoundError(
            f"Service account key not found at {key_path}. "
            f"Run: gcloud iam service-accounts keys create {key_path} "
            f"--iam-account=orchestrator@{project}.iam.gserviceaccount.com\n"
            "Or re-run scripts/bootstrap.sh --create-key (loud, gitignore-verified)."
        )

    cred = credentials.Certificate(str(key_path))
    _app = firebase_admin.initialize_app(cred, {"storageBucket": bucket})
    return _app


def get_bucket(bucket_name: str | None = None) -> Bucket:
    init_app()
    return storage.bucket(bucket_name) if bucket_name else storage.bucket()


def upload_bytes(
    blob_path: str,
    data: bytes,
    content_type: str = "application/octet-stream",
    metadata: Mapping[str, Any] | None = None,
) -> Blob:
    """Upload raw bytes to {bucket}/{blob_path}. Returns the Blob."""
    bucket = get_bucket()
    blob = bucket.blob(blob_path)
    if metadata:
        blob.metadata = dict(metadata)
    blob.upload_from_string(data, content_type=content_type)
    return blob


def signed_url(blob_path: str, ttl_seconds: int = 3600) -> str:
    """Mint a v4 signed URL for {bucket}/{blob_path} valid for ttl_seconds."""
    blob = get_bucket().blob(blob_path)
    return blob.generate_signed_url(
        version="v4",
        expiration=dt.timedelta(seconds=ttl_seconds),
        method="GET",
    )


def upload_and_sign(
    blob_path: str,
    data: bytes,
    content_type: str = "application/octet-stream",
    ttl_seconds: int = 3600,
) -> tuple[str, str]:
    """Upload and immediately mint a signed URL. Returns (gs_uri, signed_url)."""
    blob = upload_bytes(blob_path, data, content_type=content_type)
    gs_uri = f"gs://{blob.bucket.name}/{blob.name}"
    return gs_uri, signed_url(blob_path, ttl_seconds=ttl_seconds)


__all__ = [
    "init_app",
    "get_bucket",
    "upload_bytes",
    "signed_url",
    "upload_and_sign",
]
