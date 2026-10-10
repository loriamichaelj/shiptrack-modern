"""Proof-of-delivery storage in S3 (REM-05).

Objects live at `pod/{shipment_id}/{document_id}`, so any pod can serve any upload and nothing
depends on which host received it. The bucket's default encryption applies SSE-KMS. Downloads are a
redirect to a short-lived presigned URL, so the bytes never pass through the API.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from typing import Any, BinaryIO
from urllib.parse import urlparse

import boto3
from botocore.config import Config

PRESIGNED_TTL_SECONDS = 300
CHUNK_SIZE = 64 * 1024


class PayloadTooLargeError(Exception):
    pass


@dataclass(frozen=True)
class StoredObject:
    bucket: str
    key: str
    size_bytes: int
    sha256: str

    @property
    def uri(self) -> str:
        return f"s3://{self.bucket}/{self.key}"


def object_key(shipment_id: uuid.UUID, document_id: uuid.UUID) -> str:
    return f"pod/{shipment_id}/{document_id}"


def split_uri(uri: str) -> tuple[str, str] | None:
    """(bucket, key) for an s3:// URI, or None for any other scheme."""
    parsed = urlparse(uri)
    if parsed.scheme != "s3" or not parsed.netloc:
        return None
    return parsed.netloc, parsed.path.lstrip("/")


def is_legacy_file_uri(uri: str) -> bool:
    return urlparse(uri).scheme == "file"


class _CountingReader:
    """Hash and count what is read, and stop as soon as the limit is passed."""

    def __init__(self, stream: BinaryIO, max_bytes: int) -> None:
        self._stream = stream
        self._max_bytes = max_bytes
        self._digest = hashlib.sha256()
        self.size = 0

    def read(self, size: int = -1) -> bytes:
        chunk = self._stream.read(CHUNK_SIZE if size is None or size < 0 else size)
        self.size += len(chunk)
        if self.size > self._max_bytes:
            raise PayloadTooLargeError
        self._digest.update(chunk)
        return chunk

    @property
    def sha256(self) -> str:
        return self._digest.hexdigest()


class PodStore:
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
        reader = _CountingReader(stream, max_bytes)
        # upload_fileobj aborts a multipart upload itself if the reader raises.
        self._client.upload_fileobj(
            reader, self.bucket, key, ExtraArgs={"ContentType": content_type}
        )
        return StoredObject(self.bucket, key, reader.size, reader.sha256)

    def delete(self, key: str) -> None:
        self._client.delete_object(Bucket=self.bucket, Key=key)

    def presigned_url(self, bucket: str, key: str, content_type: str) -> str:
        return str(
            self._client.generate_presigned_url(
                "get_object",
                Params={"Bucket": bucket, "Key": key, "ResponseContentType": content_type},
                ExpiresIn=PRESIGNED_TTL_SECONDS,
            )
        )
