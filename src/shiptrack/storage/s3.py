"""Proof-of-delivery storage in S3 (REM-05).

Objects live at `pod/{shipment_id}/{document_id}`, so any pod can serve any upload and nothing
depends on which host received it. The bucket's default encryption applies SSE-KMS. Downloads are a
redirect to a short-lived presigned URL, so the bytes never pass through the API.
"""

from __future__ import annotations

import uuid
from typing import Any, BinaryIO

import boto3
from botocore.config import Config

from shiptrack.ports import PayloadTooLargeError, StoredObject
from shiptrack.storage import common
from shiptrack.storage.common import CountingReader, is_legacy_file_uri

__all__ = [
    "PayloadTooLargeError",
    "ProofOfDeliveryStore",
    "StoredObject",
    "is_legacy_file_uri",
    "object_key",
    "split_uri",
]

PRESIGNED_TTL_SECONDS = 300


def object_key(shipment_id: uuid.UUID, document_id: uuid.UUID) -> str:
    return f"pod/{shipment_id}/{document_id}"


def split_uri(uri: str) -> tuple[str, str] | None:
    """(bucket, key) for an s3:// URI, or None for any other scheme."""
    return common.split_uri(uri, "s3")


class ProofOfDeliveryStore:
    def __init__(self, bucket: str, region: str | None = None, client: Any = None) -> None:
        self.bucket = bucket
        # Signature V4 is required: the bucket is encrypted with KMS, and S3 refuses V2 signatures
        # (which boto3 uses by default in us-east-1) for objects encrypted that way.
        self._client = client or boto3.client(
            "s3", region_name=region, config=Config(signature_version="s3v4")
        )

    def save(
        self,
        shipment_id: uuid.UUID,
        document_id: uuid.UUID,
        stream: BinaryIO,
        content_type: str,
        max_bytes: int,
    ) -> StoredObject:
        """Stream `stream` to S3 while hashing it; refuse anything over `max_bytes`."""
        key = object_key(shipment_id, document_id)
        reader = CountingReader(stream, max_bytes)
        # upload_fileobj aborts a multipart upload itself if the reader raises.
        self._client.upload_fileobj(
            reader, self.bucket, key, ExtraArgs={"ContentType": content_type}
        )
        return StoredObject(self.bucket, key, reader.size, reader.sha256)

    def delete(self, key: str) -> None:
        self._client.delete_object(Bucket=self.bucket, Key=key)

    def locate(self, uri: str) -> tuple[str, str] | None:
        return split_uri(uri)

    def presigned_url(self, bucket: str, key: str, content_type: str) -> str:
        return str(
            self._client.generate_presigned_url(
                "get_object",
                Params={"Bucket": bucket, "Key": key, "ResponseContentType": content_type},
                ExpiresIn=PRESIGNED_TTL_SECONDS,
            )
        )
