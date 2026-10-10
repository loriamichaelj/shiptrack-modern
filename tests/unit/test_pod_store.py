import hashlib
import io
import uuid
from typing import Any

import pytest

from shiptrack.storage import s3
from shiptrack.storage.s3 import PodStore


class FakeS3:
    def __init__(self) -> None:
        self.uploaded: dict[str, bytes] = {}
        self.extra: dict[str, Any] = {}
        self.deleted: list[str] = []
        self.presigned: list[dict[str, Any]] = []

    def upload_fileobj(
        self, fileobj: Any, bucket: str, key: str, ExtraArgs: dict[str, Any]
    ) -> None:
        data = b""
        while chunk := fileobj.read(1024):
            data += chunk
        self.uploaded[f"{bucket}/{key}"] = data
        self.extra[f"{bucket}/{key}"] = ExtraArgs

    def delete_object(self, Bucket: str, Key: str) -> None:
        self.deleted.append(f"{Bucket}/{Key}")

    def generate_presigned_url(self, op: str, Params: dict[str, Any], ExpiresIn: int) -> str:
        self.presigned.append({"op": op, "params": Params, "ttl": ExpiresIn})
        return "https://example.test/signed"


SHIPMENT, DOCUMENT = uuid.uuid4(), uuid.uuid4()


def test_the_key_is_pod_shipment_document() -> None:
    assert s3.object_key(SHIPMENT, DOCUMENT) == f"pod/{SHIPMENT}/{DOCUMENT}"


def test_save_streams_hashes_and_counts() -> None:
    fake = FakeS3()
    data = b"proof of delivery" * 5000
    stored = PodStore("bucket", client=fake).save(
        SHIPMENT, DOCUMENT, io.BytesIO(data), "application/pdf", max_bytes=10**6
    )
    assert stored.size_bytes == len(data)
    assert stored.sha256 == hashlib.sha256(data).hexdigest()
    assert stored.uri == f"s3://bucket/pod/{SHIPMENT}/{DOCUMENT}"
    assert fake.uploaded[f"bucket/pod/{SHIPMENT}/{DOCUMENT}"] == data
    assert fake.extra[f"bucket/pod/{SHIPMENT}/{DOCUMENT}"] == {"ContentType": "application/pdf"}


def test_exactly_the_limit_is_accepted() -> None:
    stored = PodStore("b", client=FakeS3()).save(
        SHIPMENT, DOCUMENT, io.BytesIO(b"x" * 100), "image/png", 100
    )
    assert stored.size_bytes == 100


def test_one_byte_over_the_limit_is_refused_before_everything_is_read() -> None:
    fake = FakeS3()
    stream = io.BytesIO(b"x" * 10_000)
    with pytest.raises(s3.PayloadTooLargeError):
        PodStore("b", client=fake).save(SHIPMENT, DOCUMENT, stream, "image/png", 100)
    assert stream.tell() < 10_000, "the reader must stop early, not buffer the whole file"


def test_delete_removes_the_object() -> None:
    fake = FakeS3()
    PodStore("b", client=fake).delete("pod/a/b")
    assert fake.deleted == ["b/pod/a/b"]


def test_the_presigned_url_lasts_five_minutes_and_forces_the_content_type() -> None:
    fake = FakeS3()
    url = PodStore("b", client=fake).presigned_url("b", "pod/a/b", "image/png")
    assert url == "https://example.test/signed"
    assert fake.presigned[0]["ttl"] == 300
    assert fake.presigned[0]["params"]["ResponseContentType"] == "image/png"


@pytest.mark.parametrize(
    ("uri", "expected"),
    [
        ("s3://bucket/pod/a/b", ("bucket", "pod/a/b")),
        ("file:///var/lib/shiptrack/pod/a/b", None),
        ("https://example.test/x", None),
        ("s3:///nobucket", None),
    ],
)
def test_split_uri(uri: str, expected: tuple[str, str] | None) -> None:
    assert s3.split_uri(uri) == expected


def test_file_uris_are_recognised_as_legacy() -> None:
    assert s3.is_legacy_file_uri("file:///var/lib/shiptrack/pod/a/b")
    assert not s3.is_legacy_file_uri("s3://bucket/pod/a/b")
