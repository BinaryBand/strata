"""The GUI's data snapshot and the loopback server serving it plus the action API.

`gui/` is a Flutter app over the runbook catalog. It reads and drives strata
through one seam. `GET /api/gui-data` is read-only -- the declarations
`discovery`/`guard.declared()`/`inventory` produced, nothing executed. Every
other `/api/*` route's body lives in `gui_actions.py`, a thin bridge onto
something that already exists (`guard_executor.execute`, `inventory.add`,
`secrets.set_secret`, ...); this module's job is serving and routing only.
`strata gui` serves this alongside the built web app and opens a browser;
`strata dev gui-data` prints the read-only snapshot once for the desktop build.

Because the action routes can run privileged playbooks, they require a bearer
token (`strata/adapters/gui_token.py`) that `strata gui` prints and embeds in
the URL it opens locally. The server itself still only binds 127.0.0.1 --
reaching it from another device is still `tailscale serve <port>`, never
`tailscale funnel` -- so the token's job is to stop anything else already on
that tailnet from running a playbook against this box, not to replace the
loopback boundary.

This sits in `cli/` rather than `adapters/` for the same reason it always
has: it is a presentation-layer server with no domain logic of its own.
"""

from __future__ import annotations

import contextlib
import http.server
import importlib
import socket
import socketserver
import threading
import webbrowser
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from strata.adapters import gui_token
from strata.adapters.ansible import inventory, vault_pass
from strata.cli import gui_actions
from strata.cli.gui_http import read_json_body, send_json
from strata.core import discovery, guard
from strata.core import requirements as req

_DATA_ROUTE = "/api/gui-data"


def _description(docstring_first_line: str) -> str:
    """Strip the "Runbook: " convention prefix and capitalize, for display.

    Every runbook module docstring reads "Runbook: <lowercase sentence>." by
    convention (enforced by nothing but habit); the GUI wants a sentence on
    its own, matching how the mockup this ships from phrased it.
    """
    text = docstring_first_line.removeprefix("Runbook:").strip()
    return text[:1].upper() + text[1:] if text else text


def _prerequisite_label(r: req.Prerequisite) -> str:
    return "Sudo password" if r.name == "sudo_password" else f"Prerequisite: {r.name}"


_GUARD_LABELERS: dict[type, Callable[[Any], str]] = {
    req.Prerequisite: _prerequisite_label,
    req.Secret: lambda r: f"Secret: {r.vault_key}",
    req.SystemUser: lambda r: f"System user: {r.username}",
    req.LocalPath: lambda r: f"Path: {r.path}",
    req.Mount: lambda r: f"Mount: {r.remote_path}",
    req.Storage: lambda r: f"Storage: {r.vault_key}",
    req.UpstreamRunbook: lambda r: f"Requires {r.dotted_name}",
    req.ControllerOnly: lambda r: r.reason[:1].upper() + r.reason[1:],
}


def _guard_label(r: req.Requirement) -> str:
    """Human-readable label for one declared requirement.

    Mirrors the phrasing guard_executor's prompts and reporter use, so a GUI
    consuming this can show the same vocabulary an operator sees on the CLI.
    """
    labeler = _GUARD_LABELERS.get(type(r))
    return labeler(r) if labeler else type(r).__name__


def build_gui_data() -> dict[str, Any]:
    """Build the JSON-able snapshot of the runbook catalog and device inventory.

    Read-only: no runbook's check() is invoked and nothing is executed. Shared
    by `strata dev gui-data` (prints it once, for the desktop build's dart:io
    shell-out) and `strata gui` (serves it live, for the web build's fetch).
    """
    runbooks = []
    for info in discovery.iter_runbooks():
        module = importlib.import_module(f"strata.core.runbooks.{info.dotted_name}")
        declared = guard.declared(module.main)
        guards = [{"type": type(r).__name__, "label": _guard_label(r)} for r in declared]
        runbooks.append(
            {
                "dotted_name": info.dotted_name,
                "leaf": info.leaf,
                "category": info.category,
                "alias": info.alias,
                "description": _description(info.docstring_first_line),
                "accepts_tags": info.accepts_tags,
                "has_check": hasattr(module, "check"),
                "guards": guards,
            }
        )

    import_failures = [
        {"dotted_name": f.dotted_name, "error": f.error} for f in discovery.import_failures()
    ]

    devices = [
        {
            "name": d.name,
            "host": d.host,
            "user": d.user,
            "connection": d.connection,
            "port": d.port,
            "is_controller": d.connection == "local",
        }
        for d in inventory.all_hosts()
    ]

    return {"runbooks": runbooks, "import_failures": import_failures, "devices": devices}


def _match(parts: list[str], pattern: tuple[str | None, ...]) -> bool:
    """Report whether `parts` (a path split on "/") matches `pattern`.

    `None` in `pattern` matches any single segment -- a tiny path-template
    matcher so a route's segment count never appears as a bare magic number
    at the call site.
    """
    return len(parts) == len(pattern) and all(
        expected is None or actual == expected
        for actual, expected in zip(parts, pattern, strict=True)
    )


_RUN_STATUS = ("api", "run", None)
_DEVICE = ("api", "devices", None)


class GuiRequestHandler(http.server.SimpleHTTPRequestHandler):
    """Serves the built Flutter web app, the read-only snapshot, and the action API.

    `_web_dir`/`_token` are class attributes rather than instance state
    because `http.server` builds one instance per request and only lets a
    `ThreadingHTTPServer` hand it a `handler_class`, not an already-configured
    instance; `_request_handler` sets them once, before the server accepts
    its first request, and a process only ever runs one `strata gui` server.
    """

    _web_dir: Path
    _token: str

    def __init__(
        self,
        request: socket.socket,
        client_address: tuple[str, int],
        server: socketserver.BaseServer,
    ) -> None:
        """Bind the static file root before delegating to the base handler."""
        super().__init__(request, client_address, server, directory=str(self._web_dir))

    def _authorized(self) -> bool:
        return self.headers.get("Authorization") == f"Bearer {self._token}"

    def _unauthorized(self) -> None:
        send_json(self, 401, {"error": "missing or invalid access token"})

    def do_GET(self) -> None:
        """Serve the action/read API live, everything else as a static file."""
        parsed = urlsplit(self.path)
        parts = parsed.path.strip("/").split("/")

        if parsed.path == _DATA_ROUTE:
            send_json(self, 200, build_gui_data())
        elif parsed.path == "/api/runbook-status":
            gui_actions.get_runbook_status(self, parse_qs(parsed.query))
        elif parsed.path == "/api/vault-status":
            send_json(self, 200, {"has_vault_password": vault_pass.has_vault_password()})
        elif parsed.path == "/api/reachable":
            gui_actions.get_reachable(self, parse_qs(parsed.query))
        elif _match(parts, _RUN_STATUS):
            if self._authorized():
                gui_actions.get_run_status(self, parts[2])
            else:
                self._unauthorized()
        else:
            super().do_GET()

    def do_POST(self) -> None:
        """Handle the mutating routes; all require the access token."""
        if not self._authorized():
            self._unauthorized()
            return
        route = gui_actions.POST_ROUTES.get(self.path)
        if route is None:
            send_json(self, 404, {"error": "not found"})
            return
        route(self, read_json_body(self))

    def do_DELETE(self) -> None:
        """Handle `DELETE /api/devices/<name>`; requires the access token."""
        if not self._authorized():
            self._unauthorized()
            return
        parts = urlsplit(self.path).path.strip("/").split("/")
        if _match(parts, _DEVICE):
            gui_actions.delete_device(self, parts[2])
        else:
            send_json(self, 404, {"error": "not found"})


def _request_handler(web_dir: Path, token: str) -> type[http.server.SimpleHTTPRequestHandler]:
    """Configure and return `GuiRequestHandler` for one `strata gui` process's lifetime."""
    GuiRequestHandler._web_dir = web_dir  # noqa: SLF001 -- this module owns GuiRequestHandler
    GuiRequestHandler._token = token  # noqa: SLF001
    return GuiRequestHandler


def serve(
    web_dir: Path,
    *,
    port: int,
    open_browser: bool,
    announce: Callable[[str], None],
) -> None:
    """Serve `web_dir` plus the /api/* routes on loopback until interrupted.

    Binds 127.0.0.1 only. The caller is responsible for having checked that
    `web_dir` exists -- this raises OSError through the socket bind if the port
    is taken, which the caller turns into an operator-facing message.

    `announce` receives the lines to print; passing it in keeps this module
    free of Typer so the server can be exercised without a CLI runner.
    """
    token = gui_token.get_or_create_token()
    handler = _request_handler(web_dir, token)
    with http.server.ThreadingHTTPServer(("127.0.0.1", port), handler) as httpd:
        # Read the port back off the socket rather than echoing the argument:
        # port 0 means "let the kernel choose", and then the requested port is
        # not the one a browser needs to be pointed at.
        url = f"http://127.0.0.1:{httpd.server_address[1]}"
        announce(f"Serving {web_dir} on {url} (Ctrl+C to stop)")
        announce(f"Access token: {token}")
        if open_browser:
            # Deferred to a timer thread: webbrowser.open can block for
            # seconds while it launches a browser, and on a cold start the
            # browser may request the page before serve_forever() is running.
            threading.Timer(0.3, lambda: webbrowser.open(f"{url}/?token={token}")).start()
        with contextlib.suppress(KeyboardInterrupt):
            httpd.serve_forever()
