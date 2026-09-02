"""Small, non-logging boundary around S3-compatible object storage."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import boto3
from botocore.client import BaseClient

from app.core.config import Settings, get_settings


@dataclass(frozen=True)
class ObjectHead:
    content_type: str
    content_length: int


class StorageObjectNotFound(Exception):
    pass


class S3Storage:
    def __init__(self, settings: Settings | None = None) -> None:
        settings = settings or get_settings()
        self.bucket = settings.storage_bucket
        self.expiry_seconds = settings.storage_presign_expiry_seconds
        self._internal = self._client(settings.storage_endpoint_url, settings)
        self._public = self._client(settings.storage_public_endpoint_url, settings)

    @staticmethod
    def _client(endpoint: str, settings: Settings) -> BaseClient:
        return boto3.client(
            "s3",
            endpoint_url=endpoint,
            region_name=settings.storage_region,
            aws_access_key_id=settings.storage_access_key_id,
            aws_secret_access_key=settings.storage_secret_access_key,
        )

    @staticmethod
    def build_presign_conditions(key: str, max_size: int) -> list[Any]:
        return [
            {"key": key},
            {"Content-Type": "application/pdf"},
            ["content-length-range", 1, max_size],
        ]

    def create_presigned_post(self, key: str, max_size: int) -> dict[str, Any]:
        return self._public.generate_presigned_post(
            Bucket=self.bucket,
            Key=key,
            Fields={"Content-Type": "application/pdf"},
            Conditions=self.build_presign_conditions(key, max_size),
            ExpiresIn=self.expiry_seconds,
        )

    def head(self, key: str) -> ObjectHead:
        try:
            result = self._internal.head_object(Bucket=self.bucket, Key=key)
        except Exception as exc:
            error = getattr(exc, "response", {}).get("Error", {})
            if error.get("Code") in {"404", "NoSuchKey", "NotFound"}:
                raise StorageObjectNotFound from exc
            raise
        return ObjectHead(
            content_type=str(result.get("ContentType", "")),
            content_length=int(result.get("ContentLength", 0)),
        )

    def get_bounded(self, key: str, max_size: int) -> bytes:
        try:
            result = self._internal.get_object(Bucket=self.bucket, Key=key)
        except Exception as exc:
            error = getattr(exc, "response", {}).get("Error", {})
            if error.get("Code") in {"404", "NoSuchKey", "NotFound"}:
                raise StorageObjectNotFound from exc
            raise
        body = result["Body"]
        try:
            data = body.read(max_size + 1)
        finally:
            body.close()
        return data
