from __future__ import annotations

import os
from pathlib import Path
from typing import BinaryIO

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from shared.logging import get_logger

logger = get_logger("shared.storage")

_ENDPOINT = os.getenv("R2_ENDPOINT_URL", "")
_ACCESS_KEY = os.getenv("R2_ACCESS_KEY_ID", "")
_SECRET_KEY = os.getenv("R2_SECRET_ACCESS_KEY", "")
_BUCKET = os.getenv("R2_BUCKET_NAME", "darkwater")
_PUBLIC_URL = os.getenv("R2_PUBLIC_URL", "").rstrip("/")


def _client() -> boto3.client:
    if not _ENDPOINT:
        raise RuntimeError("R2_ENDPOINT_URL is not set.")
    return boto3.client(
        "s3",
        endpoint_url=_ENDPOINT,
        aws_access_key_id=_ACCESS_KEY,
        aws_secret_access_key=_SECRET_KEY,
        config=Config(signature_version="s3v4"),
        region_name="auto",
    )


def upload_file(local_path: Path, key: str) -> str:
    """Upload a local file to R2. Returns the object key."""
    client = _client()
    client.upload_file(str(local_path), _BUCKET, key)
    logger.info("Uploaded %s → r2://%s/%s", local_path.name, _BUCKET, key)
    return key


def upload_fileobj(fileobj: BinaryIO, key: str, content_type: str = "application/octet-stream") -> str:
    client = _client()
    client.upload_fileobj(fileobj, _BUCKET, key, ExtraArgs={"ContentType": content_type})
    return key


def download_file(key: str, local_path: Path) -> Path:
    """Download an object from R2 to local_path. Returns local_path."""
    local_path.parent.mkdir(parents=True, exist_ok=True)
    client = _client()
    client.download_file(_BUCKET, key, str(local_path))
    logger.info("Downloaded r2://%s/%s → %s", _BUCKET, key, local_path)
    return local_path


def presigned_url(key: str, expires_in: int = 3600) -> str:
    """Return a presigned GET URL valid for expires_in seconds."""
    if _PUBLIC_URL:
        return f"{_PUBLIC_URL}/{key}"
    client = _client()
    return client.generate_presigned_url(
        "get_object",
        Params={"Bucket": _BUCKET, "Key": key},
        ExpiresIn=expires_in,
    )


def object_exists(key: str) -> bool:
    try:
        _client().head_object(Bucket=_BUCKET, Key=key)
        return True
    except ClientError as exc:
        if exc.response["Error"]["Code"] in ("404", "NoSuchKey"):
            return False
        raise


def list_keys(prefix: str) -> list[str]:
    client = _client()
    paginator = client.get_paginator("list_objects_v2")
    keys: list[str] = []
    for page in paginator.paginate(Bucket=_BUCKET, Prefix=prefix):
        for obj in page.get("Contents", []):
            keys.append(obj["Key"])
    return keys
