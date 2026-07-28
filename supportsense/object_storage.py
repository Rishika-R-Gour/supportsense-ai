from __future__ import annotations

import hashlib
from pathlib import PurePath
from typing import Any

from supportsense.config import settings
from supportsense.errors import ServiceError


class ObjectStorage:
    def __init__(self, client: Any | None = None) -> None:
        self.client = client

    def store_csv(
        self,
        *,
        tenant_id: str,
        analysis_id: str,
        filename: str,
        content: bytes,
        content_sha256: str,
    ) -> str | None:
        if not settings.upload_bucket:
            return None
        safe_filename = PurePath(filename).name
        tenant_partition = hashlib.sha256(tenant_id.encode("utf-8")).hexdigest()[:24]
        key = f"tenant/{tenant_partition}/analyses/{analysis_id}/{safe_filename}"
        try:
            client = self.client
            if client is None:
                import boto3

                client = boto3.client("s3")
            client.put_object(
                Bucket=settings.upload_bucket,
                Key=key,
                Body=content,
                ContentType="text/csv",
                ServerSideEncryption="AES256",
                Metadata={"sha256": content_sha256},
            )
        except Exception as exc:
            raise ServiceError(
                "object_storage_unavailable",
                "The upload could not be stored safely.",
                503,
            ) from exc
        return f"s3://{settings.upload_bucket}/{key}"


object_storage = ObjectStorage()
