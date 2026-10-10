"""Proof-of-delivery upload and download (REM-05)."""

from __future__ import annotations

import uuid
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from shiptrack import metrics
from shiptrack.api.deps import get_shipment_or_404, parse_uuid
from shiptrack.api.errors import ApiError, not_found
from shiptrack.db.models import PodDocument
from shiptrack.db.session import get_session
from shiptrack.domain.models import PodOut
from shiptrack.storage import s3
from shiptrack.storage.s3 import PodStore

log = structlog.get_logger("shiptrack.pod")

router = APIRouter(prefix="/api/v1")

MAX_POD_BYTES = 10 * 1024 * 1024
ALLOWED_CONTENT_TYPES = frozenset({"application/pdf", "image/png", "image/jpeg"})

SessionDep = Annotated[Session, Depends(get_session)]


@router.post("/shipments/{shipment_id}/pod", status_code=201, response_model=PodOut)
def upload_pod(
    shipment_id: str,
    request: Request,
    session: SessionDep,
    file: Annotated[UploadFile, File()],
) -> PodOut:
    shipment = get_shipment_or_404(session, shipment_id)
    content_type = (file.content_type or "").split(";")[0].strip().lower()
    if content_type not in ALLOWED_CONTENT_TYPES:
        metrics.POD_UPLOADS.labels(result="rejected").inc()
        raise ApiError(
            415, "UNSUPPORTED_MEDIA_TYPE", "Only application/pdf, image/png, image/jpeg allowed"
        )

    store: PodStore = request.app.state.pod_store
    document_id = uuid.uuid4()
    try:
        stored = store.save(shipment.id, document_id, file.file, content_type, MAX_POD_BYTES)
    except s3.PayloadTooLargeError as exc:
        metrics.POD_UPLOADS.labels(result="rejected").inc()
        raise ApiError(413, "PAYLOAD_TOO_LARGE", "POD files are limited to 10 MiB") from exc
    except Exception:
        metrics.POD_UPLOADS.labels(result="failed").inc()
        raise

    document = PodDocument(
        id=document_id,
        shipment_id=shipment.id,
        storage_uri=stored.uri,
        content_type=content_type,
        size_bytes=stored.size_bytes,
        sha256=stored.sha256,
    )
    session.add(document)
    try:
        session.commit()
    except Exception:
        session.rollback()
        store.delete(stored.key)  # do not leave an object that no row points to
        metrics.POD_UPLOADS.labels(result="failed").inc()
        raise
    session.refresh(document)
    metrics.POD_UPLOADS.labels(result="ok").inc()
    return PodOut(
        document_id=document.id,
        shipment_id=document.shipment_id,
        content_type=document.content_type,
        size_bytes=document.size_bytes,
        sha256=document.sha256,
        uploaded_at=document.uploaded_at,
    )


@router.get("/shipments/{shipment_id}/pod/{document_id}")
def download_pod(
    shipment_id: str, document_id: str, request: Request, session: SessionDep
) -> RedirectResponse:
    document = session.scalar(
        select(PodDocument).where(
            PodDocument.id == parse_uuid(document_id, "Document"),
            PodDocument.shipment_id == parse_uuid(shipment_id),
        )
    )
    if document is None:
        raise not_found("Document not found")

    location = s3.split_uri(document.storage_uri)
    if location is not None:
        store: PodStore = request.app.state.pod_store
        url = store.presigned_url(location[0], location[1], document.content_type)
        return RedirectResponse(url, status_code=302)

    if s3.is_legacy_file_uri(document.storage_uri):
        # Uploaded to a legacy host and not yet copied to S3 by the sync (cutover gate G-POD).
        metrics.POD_NOT_MIGRATED.inc()
        log.warning(
            "pod_not_migrated",
            document_id=str(document.id),
            shipment_id=str(document.shipment_id),
            uploaded_at=document.uploaded_at.isoformat(),
        )
        raise not_found("Document not found")

    log.error("pod_unsupported_storage_uri", document_id=str(document.id))
    raise ApiError(500, "INTERNAL", "Unsupported storage location")
