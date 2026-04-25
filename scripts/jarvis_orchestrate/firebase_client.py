"""Firebase Admin SDK wrapper for Jarvis orchestrator (<firebase-project-id>).

Loads service account credentials from Jarvis/.secrets/, exposes a small
upload + signed-URL-mint API for the supervisor and audit pipelines.

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

PROJECT_ID = "<firebase-project-id>"
DEFAULT_BUCKET = "<firebase-project-id>-evidence"  # vanilla GCS bucket; IAM-controlled (no Firebase Storage rules)
DEFAULT_KEY_PATH = (
    Path(__file__).resolve().parents[2]
    / ".secrets"
    / "<firebase-project-id>-orchestrator.json"
)

_app: firebase_admin.App | None = None


def init_app(key_path: Path | None = None, bucket: str = DEFAULT_BUCKET) -> firebase_admin.App:
    """Initialize the firebase_admin app once. Idempotent."""
    global _app
    if _app is not None:
        return _app

    key_path = key_path or DEFAULT_KEY_PATH
    if not key_path.exists():
        raise FileNotFoundError(
            f"Service account key not found at {key_path}. "
            f"Run: gcloud iam service-accounts keys create {key_path} "
            f"--iam-account=orchestrator@{PROJECT_ID}.iam.gserviceaccount.com"
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
    "PROJECT_ID",
    "DEFAULT_BUCKET",
    "init_app",
    "get_bucket",
    "upload_bytes",
    "signed_url",
    "upload_and_sign",
]
