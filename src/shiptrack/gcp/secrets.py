"""Database credentials from Secret Manager."""

from __future__ import annotations

from typing import Any

import google.cloud.secretmanager


class SecretManagerSource:
    """`name` is the short secret name; the project comes from the setting. Always the latest
    version, so a rotated password is picked up the next time the cache is invalidated."""

    def __init__(self, project: str, client: Any = None) -> None:
        self._project = project
        self._client = client

    def fetch(self, name: str) -> str:
        if self._client is None:
            self._client = google.cloud.secretmanager.SecretManagerServiceClient()
        path = f"projects/{self._project}/secrets/{name}/versions/latest"
        response = self._client.access_secret_version(request={"name": path})
        return str(response.payload.data.decode("utf-8"))
