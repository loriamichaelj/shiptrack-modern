"""What every object store shares: hashing and counting a stream, and the legacy URI check."""

from __future__ import annotations

import hashlib
from typing import BinaryIO
from urllib.parse import urlparse

from shiptrack.ports import PayloadTooLargeError

CHUNK_SIZE = 64 * 1024


def split_uri(uri: str, scheme: str) -> tuple[str, str] | None:
    """(bucket, key) for a URI with `scheme`, or None for any other scheme."""
    parsed = urlparse(uri)
    if parsed.scheme != scheme or not parsed.netloc:
        return None
    return parsed.netloc, parsed.path.lstrip("/")


def is_legacy_file_uri(uri: str) -> bool:
    return urlparse(uri).scheme == "file"


class CountingReader:
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
