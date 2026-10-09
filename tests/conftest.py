"""Shared fixtures: an AWS API emulator that every test talks to instead of AWS.

The tests take the endpoint from AWS_ENDPOINT_URL, so they run against LocalStack locally or a moto
server in CI. When it is not set, a moto server is started for the session. Fake credentials and an
endpoint are set for every test, so nothing can reach real AWS by accident.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Iterator

import pytest

REGION = "us-east-1"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for(url: str, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            urllib.request.urlopen(url, timeout=1)
            return
        except urllib.error.HTTPError:
            return  # it answered
        except OSError:
            time.sleep(0.2)
    raise RuntimeError(f"the AWS emulator did not start at {url}")


@pytest.fixture(scope="session")
def aws_endpoint() -> Iterator[str]:
    configured = os.environ.get("AWS_ENDPOINT_URL")
    if configured:
        yield configured
        return
    port = _free_port()
    server = subprocess.Popen(
        [sys.executable, "-m", "moto.server", "-H", "127.0.0.1", "-p", str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    url = f"http://127.0.0.1:{port}"
    try:
        _wait_for(url)
        yield url
    finally:
        server.terminate()
        server.wait(timeout=10)


@pytest.fixture(autouse=True)
def aws_environment(aws_endpoint: str, monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("AWS_PROFILE", "AWS_SESSION_TOKEN", "AWS_SECURITY_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AWS_ENDPOINT_URL", aws_endpoint)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    monkeypatch.setenv("AWS_DEFAULT_REGION", REGION)
    monkeypatch.setenv("AWS_REGION", REGION)
