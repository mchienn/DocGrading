"""Small, non-logging boundary around S3-compatible object storage."""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import boto3
from botocore.client import BaseClient

from app.core.config import Settings, get_settings


@dataclass(frozen=True)
class ObjectHead:
    content_type: str
    content_length: int
    etag: str = ""


class StorageObjectNotFound(Exception):
    pass


class StorageObjectChanged(Exception):
    pass


class S3Storage:
    def __init__(self, settings: Settings | None = None) -> None:
        settings = settings or get_settings()
        self.bucket = settings.storage_bucket
        self.expiry_seconds = settings.storage_presign_expiry_seconds
        self._internal = self._client(settings.storage_endpoint_url, settings)
        self._public = self._client(settings.storage_public_endpoint_url, settings)
        self._recovery_dir = (
            Path(settings.storage_recovery_dir).resolve()
            if settings.storage_recovery_dir
            else None
        )
        frontend_origin = settings.frontend_origin.rstrip("/")
        parsed_origin = urlsplit(frontend_origin)
        alternate_host = {
            "localhost": "127.0.0.1",
            "127.0.0.1": "localhost",
        }.get(parsed_origin.hostname or "")
        self._recovery_cors_origins = [frontend_origin]
        if alternate_host:
            port = f":{parsed_origin.port}" if parsed_origin.port else ""
            self._recovery_cors_origins.append(
                urlunsplit(parsed_origin._replace(netloc=f"{alternate_host}{port}"))
            )

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

    def create_presigned_get(self, key: str) -> str:
        return self._public.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": self.bucket,
                "Key": key,
                "ResponseContentType": "application/pdf",
                "ResponseContentDisposition": "inline",
            },
            ExpiresIn=self.expiry_seconds,
        )

    def seal_upload(
        self,
        source_key: str,
        destination_key: str,
        expected_etag: str,
    ) -> ObjectHead:
        if not expected_etag:
            raise RuntimeError("Object storage did not return an ETag")
        try:
            self._internal.copy_object(
                Bucket=self.bucket,
                Key=destination_key,
                CopySource={"Bucket": self.bucket, "Key": source_key},
                CopySourceIfMatch=expected_etag,
                ContentType="application/pdf",
                MetadataDirective="REPLACE",
            )
        except Exception as exc:
            response = getattr(exc, "response", {})
            error = response.get("Error", {})
            if (
                error.get("Code") in {"PreconditionFailed", "412"}
                or response.get("ResponseMetadata", {}).get("HTTPStatusCode") == 412
            ):
                raise StorageObjectChanged from exc
            raise
        sealed = self.head(destination_key)
        self._backup(destination_key)
        return sealed

    def _recovery_path(self, key: str) -> Path | None:
        recovery_dir = getattr(self, "_recovery_dir", None)
        if recovery_dir is None:
            return None
        relative = PurePosixPath(key)
        if (
            relative.is_absolute()
            or Path(key).is_absolute()
            or "\\" in key
            or any(part in {"", ".", ".."} for part in key.split("/"))
        ):
            raise ValueError("Storage key is not a safe relative path")
        return recovery_dir.joinpath(*relative.parts)

    def _backup(self, key: str) -> None:
        destination = self._recovery_path(key)
        if destination is None:
            return
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
        result = self._internal.get_object(Bucket=self.bucket, Key=key)
        body = result["Body"]
        try:
            with temporary.open("wb") as target:
                while chunk := body.read(1024 * 1024):
                    target.write(chunk)
            os.replace(temporary, destination)
        finally:
            body.close()
            temporary.unlink(missing_ok=True)

    def _create_recovery_bucket(self) -> None:
        self._internal.create_bucket(Bucket=self.bucket)
        self._internal.put_bucket_cors(
            Bucket=self.bucket,
            CORSConfiguration={
                "CORSRules": [
                    {
                        "AllowedHeaders": ["*"],
                        "AllowedMethods": ["GET", "HEAD", "POST"],
                        "AllowedOrigins": self._recovery_cors_origins,
                        "ExposeHeaders": [
                            "Accept-Ranges",
                            "Content-Length",
                            "Content-Range",
                            "ETag",
                        ],
                        "MaxAgeSeconds": 300,
                    }
                ]
            },
        )
        self._internal.put_bucket_lifecycle_configuration(
            Bucket=self.bucket,
            LifecycleConfiguration={
                "Rules": [
                    {
                        "ID": "expire-staging-uploads",
                        "Filter": {"Prefix": "uploads/"},
                        "Status": "Enabled",
                        "Expiration": {"Days": 1},
                    }
                ]
            },
        )

    def _restore(self, key: str) -> bool:
        source = self._recovery_path(key)
        if source is None or not source.is_file():
            return False
        with source.open("rb") as body:
            try:
                self._internal.put_object(
                    Bucket=self.bucket,
                    Key=key,
                    Body=body,
                    ContentType="application/pdf",
                )
            except Exception as exc:
                error = getattr(exc, "response", {}).get("Error", {})
                if error.get("Code") != "NoSuchBucket":
                    raise
                self._create_recovery_bucket()
                body.seek(0)
                self._internal.put_object(
                    Bucket=self.bucket,
                    Key=key,
                    Body=body,
                    ContentType="application/pdf",
                )
        return True

    def _head(self, key: str) -> dict[str, Any]:
        try:
            return self._internal.head_object(Bucket=self.bucket, Key=key)
        except Exception as exc:
            error = getattr(exc, "response", {}).get("Error", {})
            if error.get("Code") not in {
                "404",
                "NoSuchBucket",
                "NoSuchKey",
                "NotFound",
            }:
                raise
            if not self._restore(key):
                raise StorageObjectNotFound from exc
        return self._internal.head_object(Bucket=self.bucket, Key=key)

    def head(self, key: str) -> ObjectHead:
        result = self._head(key)
        return ObjectHead(
            content_type=str(result.get("ContentType", "")),
            content_length=int(result.get("ContentLength", 0)),
            etag=str(result.get("ETag", "")),
        )

    def get_bounded(self, key: str, max_size: int) -> bytes:
        try:
            result = self._internal.get_object(Bucket=self.bucket, Key=key)
        except Exception as exc:
            error = getattr(exc, "response", {}).get("Error", {})
            if error.get("Code") not in {
                "404",
                "NoSuchBucket",
                "NoSuchKey",
                "NotFound",
            }:
                raise
            if not self._restore(key):
                raise StorageObjectNotFound from exc
            result = self._internal.get_object(Bucket=self.bucket, Key=key)
        body = result["Body"]
        try:
            data = body.read(max_size + 1)
        finally:
            body.close()
        return data
