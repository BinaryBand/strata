"""Read-only admin monitor for everything the AnythingLLM agent can see, on its own origin.

Deployed by strata's services.enable_anythingllm_review runbook. It listens on
a Unix socket that only its own account and root can open -- no network port,
so no other local process can reach it and forge a login -- and `tailscale
serve` (root) mounts it at the root of its own tailnet port, apart from the
agent-built site. Tailscale stamps every request with the viewer's tailnet
login, overwriting any login a client sends, and only REVIEW_LOGIN is served;
everyone else gets 403.

Screens follow a Claude Design mock-up (review_layout). Each shows what the
agent can see in full -- prompts, chats, job prompts, run output, tool
schemas, every file in its folder -- and keeps what only the server sees in a
part marked Admin only. Credentials never leave the monitor: settings show as
"set", secret files as a fingerprint, and the key check (review_secrets) names
where a stored key turns up in the agent's reach without showing it. Fixed
screens are rebuilt on a request once their cached copy is a minute old.
Standard library only.
"""

from __future__ import annotations

import os
import socketserver
import sys
import threading
import time
import traceback
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import review_artifacts
import review_content as content
import review_files
import review_knowledge
import review_layout as ui
import review_overview
import review_run
import review_tasks
import review_thread
import review_tools
import review_viewer
import review_workspace

LOGIN = os.environ.get("REVIEW_LOGIN", "")
SOCKET = os.environ.get("REVIEW_SOCKET", "/run/anythingllm-review/review.sock")
TTL_SECONDS = 60
TITLES = {
    "overview": "Overview",
    "tools": "Tools",
    "tasks": "Scheduled tasks",
    "artifacts": "Artifacts",
    "workspace": "Workspace",
    "knowledge": "Knowledge",
    "more": "More",
}
# The fixed screens: cached, rebuilt at most once per TTL for each workspace.
FIXED = {
    "": "overview",
    "/tools": "tools",
    "/tasks": "tasks",
    "/artifacts": "artifacts",
    "/workspace": "workspace",
    "/knowledge": "knowledge",
    "/more": "more",
}


class Cache:
    """Each fixed screen, rebuilt at most once per TTL however many requests arrive."""

    def __init__(self) -> None:
        """Start empty: the first request for a screen builds it."""
        self.lock = threading.Lock()
        self.pages: dict[tuple[str, str], tuple[float, int, str]] = {}

    def get(self, screen: str, slug: str = "") -> tuple[int, str]:
        """(status, page) for `screen` in workspace `slug`, rebuilt when TTL_SECONDS old."""
        with self.lock:
            built, status, body = self.pages.get((screen, slug), (0.0, 0, ""))
            if not body or time.monotonic() - built >= TTL_SECONDS:
                status, body = render(screen, slug)
                self.pages[(screen, slug)] = (time.monotonic(), status, body)
            return status, body


def page_for(active: str, slug: str = "") -> ui.Page:
    """The shell's context: the login and the selected workspace (the first when none is named)."""
    spaces = tuple(content.workspaces())
    ws = next((w for w in spaces if w[0] == slug), spaces[0] if spaces else None)
    return ui.Page(content.PREFIX, LOGIN, active, ws, spaces)


def render(screen: str, slug: str = "") -> tuple[int, str]:
    """(status, whole page) for a fixed screen."""
    page = page_for(screen, slug)
    prefix, ws = content.PREFIX, page.ws[0] if page.ws else ""
    status, main = 200, ""
    if screen == "overview":
        main = review_overview.screen(prefix, LOGIN, page.ws)
    elif screen == "more":
        main = review_overview.more_screen(prefix, page.ws)
    elif screen == "tools":
        main = review_tools.screen(prefix)
    elif screen == "tasks":
        main = review_tasks.screen(prefix)
    elif screen == "artifacts":
        main = review_artifacts.screen(prefix)
    elif screen == "workspace":
        status, main = review_workspace.screen(prefix, ws)
    else:
        status, main = review_knowledge.screen(prefix, ws)
    return status, ui.shell(page, TITLES[screen], main)


def dynamic(path: str, q: Callable[[str], str]) -> tuple[int, str] | None:
    """(status, whole page) for a page built on each request, or None for an unknown path."""
    prefix = content.PREFIX
    views: dict[str, tuple[str, Callable[[], tuple[int, str]]]] = {
        "/files": (
            "files",
            lambda: review_files.screen(prefix, q("path"), show_all=bool(q("all"))),
        ),
        "/file": ("files", lambda: review_viewer.file_view(prefix, q("path"))),
        "/run": ("tasks", lambda: review_run.run_view(prefix, q("id"), q("start"))),
        "/thread": ("workspace", lambda: review_thread.view(prefix, q("ws"), q("id"), q("before"))),
        "/doc": ("knowledge", lambda: review_knowledge.doc_view(prefix, q("id"))),
        "/tasks": ("tasks", lambda: (200, review_tasks.screen(prefix, q("job")))),
    }
    if path not in views:
        return None
    active, build = views[path]
    status, main = build()
    title = q("path").rsplit("/", 1)[-1] or TITLES.get(active, "Files")
    return status, ui.shell(page_for(active, q("ws")), title, main)


CACHE = Cache()


def answer(path: str, q: Callable[[str], str]) -> tuple[int, str]:
    """(status, whole page) for a request that passed the login check."""
    if q("ws") and q("ws") not in {slug for slug, _ in content.workspaces()}:
        return 404, ui.shell(page_for(""), "Not found", ui.header("No such workspace"))
    if path in FIXED and not (path == "/tasks" and q("job")):
        return CACHE.get(FIXED[path], q("ws"))
    found = dynamic(path, q)
    return found or (404, ui.shell(page_for(""), "Not found", ui.header("Not found")))


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
        query = parse_qs(url.query)

        def q(name: str) -> str:
            return (query.get(name) or [""])[0]

        try:
            return answer(url.path.rstrip("/"), q)
        except Exception:  # noqa: BLE001 -- one broken page must not take the monitor down
            traceback.print_exc(file=sys.stderr)
            return 500, ui.shell(
                page_for(""),
                "Error",
                ui.header("This page could not be built", "The error is in the service's journal."),
            )

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
