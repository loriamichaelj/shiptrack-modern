"""Proof-of-delivery storage in Cloud Storage (REM-05 on GCP).

Objects live at `proof-of-delivery/{shipment_id}/{document_id}` and are recorded as `gs://` URIs in
the shared `pod_documents` table (ADR-0023). Downloads redirect to a V4 signed URL that is signed
through the IAM signing API as the read-only proof-of-delivery service account, so the pod holds
no key and the bytes never pass through the API.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import timedelta
from typing import Any, BinaryIO

import google.auth
import google.cloud.storage
from google.auth.transport.requests import Request

from shiptrack.ports import StoredObject
from shiptrack.storage.common import CountingReader, split_uri

SIGNED_URL_TTL_SECONDS = 300
SCHEME = "gs"


def object_key(shipment_id: uuid.UUID, document_id: uuid.UUID) -> str:
    return f"proof-of-delivery/{shipment_id}/{document_id}"


class _SeekableCountingReader(CountingReader):
    """The resumable upload asks its stream for the position, so report the bytes read."""

    def tell(self) -> int:
        return self.size


def _iam_access_token() -> str:
    """A token for the pod's own identity, which the IAM signing call is made with."""
    credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    credentials.refresh(Request())  # type: ignore[no-untyped-call]
    return str(credentials.token)


class ProofOfDeliveryBucket:
    def __init__(
        self,
        project: str,
        bucket: str,
        signer_email: str,
        client: Any = None,
        token_source: Callable[[], str] = _iam_access_token,
    ) -> None:
        self.bucket = bucket
        self._signer_email = signer_email
        self._token_source = token_source
        self._client = client or google.cloud.storage.Client(project=project)

    def save(
        self,
        shipment_id: uuid.UUID,
        document_id: uuid.UUID,
        stream: BinaryIO,
        content_type: str,
        max_bytes: int,
    ) -> StoredObject:
        """Stream `stream` to the bucket while hashing it; refuse anything over `max_bytes`."""
        key = object_key(shipment_id, document_id)
        reader = _SeekableCountingReader(stream, max_bytes)
        # The upload is resumable, so a reader that raises ends it before the object is created.
        self._client.bucket(self.bucket).blob(key).upload_from_file(
            reader, content_type=content_type
        )
        return StoredObject(self.bucket, key, reader.size, reader.sha256, SCHEME)

    def delete(self, key: str) -> None:
        self._client.bucket(self.bucket).blob(key).delete()

    def locate(self, uri: str) -> tuple[str, str] | None:
        return split_uri(uri, SCHEME)

    def presigned_url(self, bucket: str, key: str, content_type: str) -> str:
        blob = self._client.bucket(bucket).blob(key)
        return str(
            blob.generate_signed_url(
                version="v4",
                expiration=timedelta(seconds=SIGNED_URL_TTL_SECONDS),
                method="GET",
                response_type=content_type,
                service_account_email=self._signer_email,
                access_token=self._token_source(),
            )
        )
