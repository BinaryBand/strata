"""Read-only admin monitor for AnythingLLM's data folder, served at /review.

Deployed by strata's services.enable_anythingllm_review runbook. It listens on
a Unix socket that only its own account and root can open -- no network port,
so no other local process can reach it and forge a login -- and `tailscale
serve` (root) mounts it at /review on the site's port. Tailscale stamps every
request with the viewer's tailnet login, overwriting any login a client sends,
and only REVIEW_LOGIN is served; everyone else gets 403.

Five screens, laid out after a Claude Design mock-up (review_layout): an
Overview, Skills, Scheduled tasks, Artifacts (the site's publications and
build), and Files (one folder at a time, plus a viewer for an allowlist of
non-secret files). Job runs are shown as safe summaries -- result, time,
counts of files written and tools called -- never their output. Nothing
shows the database file, the settings file with its keys, signing keys, the
MCP config, chat text, job prompts, job error text or fetched research pages.
Each fixed screen is rebuilt on a request once its cached copy is a minute
old. Standard library only.
"""

from __future__ import annotations

import os
import socketserver
import threading
import time
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import review_artifacts
import review_content as content
import review_files
import review_layout as ui
import review_overview
import review_skills
import review_tasks

LOGIN = os.environ.get("REVIEW_LOGIN", "")
SOCKET = os.environ.get("REVIEW_SOCKET", "/run/anythingllm-review/review.sock")
TTL_SECONDS = 60
# The socket sees paths without /review: tailscale serve strips the prefix.
ROUTES = {"": "overview", "/skills": "skills", "/tasks": "tasks", "/artifacts": "artifacts"}
SCREENS = {"skills": review_skills, "tasks": review_tasks, "artifacts": review_artifacts}
TITLES = {
    "overview": "Overview",
    "skills": "Skills",
    "tasks": "Scheduled tasks",
    "artifacts": "Artifacts",
}


class Cache:
    """Each fixed screen, rebuilt at most once per TTL however many requests arrive."""

    def __init__(self) -> None:
        """Start empty: the first request for a screen builds it."""
        self.lock = threading.Lock()
        self.pages: dict[str, tuple[float, str]] = {}

    def get(self, screen: str) -> str:
        """The cached page for `screen`, rebuilt first when it is TTL_SECONDS old."""
        with self.lock:
            built, body = self.pages.get(screen, (0.0, ""))
            if not body or time.monotonic() - built >= TTL_SECONDS:
                body = render(screen)
                self.pages[screen] = (time.monotonic(), body)
            return body


def render(screen: str) -> str:
    """A fixed screen, as a whole page."""
    prefix = content.PREFIX
    if screen == "overview":
        main = review_overview.screen(prefix, LOGIN)
    else:
        main = SCREENS[screen].screen(prefix)
    return ui.shell(prefix, screen, TITLES[screen], LOGIN, main)


CACHE = Cache()


class Handler(BaseHTTPRequestHandler):
    """GET and HEAD for the one allowed tailnet login; everything else refused."""

    server_version = "review"
    sys_version = ""

    def address_string(self) -> str:
        """A Unix socket has no client address."""
        return "unix"

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 -- http.server's name
        """Keep no access log."""
        del format, args

    def respond(self, status: int, body: str, *, send_body: bool = True) -> None:
        """Send `body` with the monitor's headers."""
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        for name, value in content.HEADERS.items():
            self.send_header(name, value)
        self.end_headers()
        if send_body:
            self.wfile.write(data)

    def route(self) -> tuple[int, str]:
        """(status, body) for this request, after the login check."""
        logins = self.headers.get_all("Tailscale-User-Login") or []
        if not LOGIN or logins != [LOGIN]:
            return 403, "Forbidden."
        url = urlparse(self.path)
        screen = ROUTES.get(url.path.rstrip("/"))
        if screen:
            return 200, CACHE.get(screen)
        path = (parse_qs(url.query).get("path") or [""])[0]
        if url.path == "/files":
            status, main = review_files.screen(content.PREFIX, path)
            return status, ui.shell(content.PREFIX, "files", "Files", LOGIN, main)
        if url.path == "/file":
            status, main = review_files.file_view(content.PREFIX, path)
            return status, ui.shell(content.PREFIX, "files", path or "File", LOGIN, main)
        return 404, ui.shell(content.PREFIX, "", "Not found", LOGIN, "<h1>Not found</h1>")

    def do_GET(self) -> None:
        """Serve a page."""
        self.respond(*self.route())

    def do_HEAD(self) -> None:
        """Serve a page's headers."""
        self.respond(*self.route(), send_body=False)

    def refuse(self) -> None:
        """Refuse every method that could change something."""
        self.respond(405, "Read-only.")

    do_POST = do_PUT = do_DELETE = do_PATCH = refuse  # noqa: N815 -- http.server's naming


class UnixHTTPServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    """A threaded HTTP server on a Unix socket."""

    daemon_threads = True

    def get_request(self) -> tuple:
        """Accept a connection, reporting a placeholder client address."""
        request, _ = super().get_request()
        return request, ("unix", 0)


def main() -> None:
    """Serve on SOCKET until stopped."""
    if not LOGIN:
        message = "REVIEW_LOGIN is not set; refusing to serve."
        raise SystemExit(message)
    Path(SOCKET).unlink(missing_ok=True)
    old = os.umask(0o177)  # the socket is created 0600: this account and root only
    try:
        server = UnixHTTPServer(SOCKET, Handler)
    finally:
        os.umask(old)
    server.serve_forever()


if __name__ == "__main__":
    main()
