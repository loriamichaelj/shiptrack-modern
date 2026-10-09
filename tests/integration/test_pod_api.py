"""REM-05: proof of delivery lives in S3, and any pod can serve any upload."""

import hashlib
import uuid
from collections.abc import Callable
from typing import Any

import boto3
import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from shiptrack.config import Settings
from shiptrack.main import create_app

MakeShipment = Callable[..., dict[str, Any]]
PNG = b"\x89PNG\r\n\x1a\n" + b"pod" * 100
TEN_MIB = 10 * 1024 * 1024


def s3_client() -> Any:
    return boto3.client("s3", region_name="us-east-1")


def upload(
    client: TestClient,
    shipment_id: str,
    data: bytes = PNG,
    content_type: str = "image/png",
) -> Any:
    return client.post(
        f"/api/v1/shipments/{shipment_id}/pod",
        files={"file": ("pod.bin", data, content_type)},
    )


def keys(settings: Settings) -> list[str]:
    listing = s3_client().list_objects_v2(Bucket=settings.pod_bucket)
    return [o["Key"] for o in listing.get("Contents", [])]


def test_upload_response_shape_and_the_object_in_s3(
    client: TestClient, settings: Settings, make_shipment: MakeShipment
) -> None:
    sid = make_shipment()["id"]
    response = upload(client, sid)
    assert response.status_code == 201
    body = response.json()
    assert set(body) == {
        "document_id",
        "shipment_id",
        "content_type",
        "size_bytes",
        "sha256",
        "uploaded_at",
    }
    assert body["shipment_id"] == sid
    assert body["content_type"] == "image/png"
    assert body["size_bytes"] == len(PNG)
    assert body["sha256"] == hashlib.sha256(PNG).hexdigest()
    assert body["uploaded_at"].endswith("Z")

    key = f"pod/{sid}/{body['document_id']}"
    assert keys(settings) == [key]
    stored = s3_client().get_object(Bucket=settings.pod_bucket, Key=key)
    assert stored["Body"].read() == PNG
    assert stored["ContentType"] == "image/png"


def test_download_redirects_to_a_short_lived_presigned_url(
    client: TestClient, make_shipment: MakeShipment
) -> None:
    sid = make_shipment()["id"]
    document_id = upload(client, sid).json()["document_id"]

    redirect = client.get(f"/api/v1/shipments/{sid}/pod/{document_id}", follow_redirects=False)
    assert redirect.status_code == 302
    location = redirect.headers["location"]
    assert "X-Amz-Expires=300" in location
    assert "X-Amz-Signature=" in location

    fetched = httpx.get(location)
    assert fetched.status_code == 200
    assert fetched.content == PNG
    assert fetched.headers["content-type"] == "image/png"


def test_a_client_that_follows_redirects_gets_the_file(
    client: TestClient, make_shipment: MakeShipment
) -> None:
    """The contract: GET may answer 302 -> 200, and clients must follow it."""
    sid = make_shipment()["id"]
    document_id = upload(client, sid).json()["document_id"]
    redirect = client.get(f"/api/v1/shipments/{sid}/pod/{document_id}", follow_redirects=False)
    assert httpx.get(redirect.headers["location"], follow_redirects=True).content == PNG


def test_another_pod_serves_what_this_one_stored(
    settings: Settings, make_shipment: MakeShipment, client: TestClient
) -> None:
    """AP-05 is gone: no disk, no stickiness. One app reads what another stored."""
    sid = make_shipment()["id"]
    document_id = upload(client, sid).json()["document_id"]
    with TestClient(create_app(settings)) as other:
        redirect = other.get(f"/api/v1/shipments/{sid}/pod/{document_id}", follow_redirects=False)
    assert redirect.status_code == 302
    assert httpx.get(redirect.headers["location"]).content == PNG


def test_pdf_and_jpeg_are_accepted(client: TestClient, make_shipment: MakeShipment) -> None:
    sid = make_shipment()["id"]
    for content_type in ("application/pdf", "image/jpeg"):
        assert upload(client, sid, b"data", content_type).status_code == 201


def test_unsupported_media_type_stores_nothing(
    client: TestClient, settings: Settings, make_shipment: MakeShipment
) -> None:
    sid = make_shipment()["id"]
    response = upload(client, sid, b"hello", "text/plain")
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "UNSUPPORTED_MEDIA_TYPE"
    assert keys(settings) == []


def test_payload_too_large_leaves_nothing_behind(
    client: TestClient, settings: Settings, make_shipment: MakeShipment
) -> None:
    sid = make_shipment()["id"]
    assert upload(client, sid, b"x" * TEN_MIB, "application/pdf").status_code == 201
    too_big = upload(client, sid, b"x" * (TEN_MIB + 1), "application/pdf")
    assert too_big.status_code == 413
    assert too_big.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"
    assert len(keys(settings)) == 1  # only the accepted one


def test_upload_for_unknown_shipment(client: TestClient, settings: Settings) -> None:
    response = upload(client, str(uuid.uuid4()))
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"
    assert keys(settings) == []


def test_missing_file_part(client: TestClient, make_shipment: MakeShipment) -> None:
    sid = make_shipment()["id"]
    response = client.post(f"/api/v1/shipments/{sid}/pod")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_download_unknown_document(client: TestClient, make_shipment: MakeShipment) -> None:
    sid = make_shipment()["id"]
    for document_id in (str(uuid.uuid4()), "nope"):
        assert client.get(f"/api/v1/shipments/{sid}/pod/{document_id}").status_code == 404


def test_document_belongs_to_its_shipment(client: TestClient, make_shipment: MakeShipment) -> None:
    first, second = make_shipment()["id"], make_shipment()["id"]
    document_id = upload(client, first).json()["document_id"]
    assert client.get(f"/api/v1/shipments/{second}/pod/{document_id}").status_code == 404


def test_storage_uri_is_an_s3_uri(
    client: TestClient, settings: Settings, make_shipment: MakeShipment, engine: Engine
) -> None:
    sid = make_shipment()["id"]
    document_id = upload(client, sid).json()["document_id"]
    with engine.connect() as connection:
        uri = connection.scalar(text("SELECT storage_uri FROM shiptrack.pod_documents"))
    assert uri == f"s3://{settings.pod_bucket}/pod/{sid}/{document_id}"


def test_a_pod_still_on_a_legacy_disk_is_404_and_logged(
    client: TestClient,
    make_shipment: MakeShipment,
    engine: Engine,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Until the legacy sync copies it to S3, a file:// record is 'not migrated' (gate G-POD)."""
    sid = make_shipment()["id"]
    document_id = upload(client, sid).json()["document_id"]
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE shiptrack.pod_documents SET storage_uri = :uri"),
            {"uri": f"file:///var/lib/shiptrack/pod/{sid}/{document_id}"},
        )
    with caplog.at_level("WARNING", logger="shiptrack.pod"):
        response = client.get(f"/api/v1/shipments/{sid}/pod/{document_id}", follow_redirects=False)
    assert response.status_code == 404
    assert any("pod_not_migrated" in record.message for record in caplog.records)


def test_an_unknown_storage_scheme_is_an_internal_error(
    client: TestClient, make_shipment: MakeShipment, engine: Engine
) -> None:
    sid = make_shipment()["id"]
    document_id = upload(client, sid).json()["document_id"]
    with engine.begin() as connection:
        connection.execute(text("UPDATE shiptrack.pod_documents SET storage_uri = 'ftp://x/y'"))
    response = client.get(f"/api/v1/shipments/{sid}/pod/{document_id}", follow_redirects=False)
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL"


def test_an_object_is_removed_when_its_row_cannot_be_saved(
    settings: Settings, make_shipment: MakeShipment, monkeypatch: pytest.MonkeyPatch
) -> None:
    with TestClient(create_app(settings), raise_server_exceptions=False) as client:
        sid = make_shipment()["id"]

        def broken(self: Session) -> None:
            raise RuntimeError("commit failed")

        monkeypatch.setattr(Session, "commit", broken)
        response = upload(client, sid)
    assert response.status_code == 500
    assert keys(settings) == []
