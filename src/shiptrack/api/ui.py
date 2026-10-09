"""The built UI, baked into the image and served by the API (REM-16).

URLs, cache headers, and HTML match what legacy's nginx served: hashed assets are immutable, and
every other path under /ui/ is the single-page app's shell, so a deep link survives a refresh.
The UI is served on port 8000 only, never on the operations port.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import structlog
from fastapi import FastAPI
from fastapi.responses import FileResponse
from starlette.staticfiles import StaticFiles

log = structlog.get_logger("shiptrack.ui")

IMMUTABLE = "public, max-age=31536000, immutable"


class ImmutableStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope: Any) -> Any:
        response = await super().get_response(path, scope)
        if response.status_code == 200:
            response.headers["Cache-Control"] = IMMUTABLE
        return response


def mount_ui(app: FastAPI, web_dist: Path) -> bool:
    """Serve the UI from `web_dist`; returns False (and says so) when it is not there."""
    index = web_dist / "index.html"
    assets = web_dist / "assets"
    if not index.is_file() or not assets.is_dir():
        log.warning("ui_not_found", web_dist=str(web_dist))
        return False

    # The assets mount comes first so that it wins over the catch-all below.
    app.mount("/ui/assets", ImmutableStaticFiles(directory=assets), name="ui-assets")

    def shell() -> FileResponse:
        return FileResponse(index, media_type="text/html", headers={"Cache-Control": "no-cache"})

    app.add_api_route("/ui", shell, methods=["GET"], include_in_schema=False)
    app.add_api_route("/ui/{path:path}", shell, methods=["GET"], include_in_schema=False)
    return True


def has_inline_code(html: str) -> list[str]:
    """Inline <script> or <style> would be blocked by the CSP; report any in the built shell."""
    import re

    problems = []
    for match in re.finditer(r"<script\b([^>]*)>", html, flags=re.IGNORECASE):
        if "src=" not in match.group(1).lower():
            problems.append("inline <script>")
    if re.search(r"<style\b", html, flags=re.IGNORECASE):
        problems.append("inline <style>")
    return problems
