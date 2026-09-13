"""The GUI's data snapshot and the loopback server that hands it to a browser.

`gui/` is a Flutter app over the runbook catalog. It reads strata through one
seam: the JSON snapshot `build_gui_data()` produces. Two commands consume that
seam -- `strata gui` serves it alongside the built web app and opens a browser,
and the hidden `strata dev gui-data` prints it once for the desktop build to
shell out to.

Everything here is read-only. No runbook's `main()` or `check()` is invoked and
no playbook runs; the snapshot is the declarations only -- what `discovery`
found and what `guard.declared()` recorded.

This sits in `cli/` rather than `adapters/` because it is a presentation-layer
server: it holds no domain logic, and the I/O it does is serving files and
reading a catalog that `adapters` already gathered.
"""

from __future__ import annotations

import contextlib
import http.server
import importlib
import json
import socket
import socketserver
import threading
import webbrowser
from collections.abc import Callable
from pathlib import Path
from typing import Any

from strata.adapters.ansible import inventory
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


def _request_handler(web_dir: Path) -> type[http.server.SimpleHTTPRequestHandler]:
    """Build a request handler serving `web_dir` plus a live /api/gui-data.

    A closure rather than a module-level class because the static root is
    only known once the server starts, and SimpleHTTPRequestHandler takes it
    via an __init__ kwarg that ThreadingHTTPServer's handler_class slot
    doesn't otherwise let us thread through.
    """

    class GuiRequestHandler(http.server.SimpleHTTPRequestHandler):
        """Serves the built Flutter web app and its JSON data endpoint."""

        def __init__(
            self,
            request: socket.socket,
            client_address: tuple[str, int],
            server: socketserver.BaseServer,
        ) -> None:
            """Bind the static file root before delegating to the base handler."""
            super().__init__(request, client_address, server, directory=str(web_dir))

        def do_GET(self) -> None:
            """Serve /api/gui-data live, everything else as a static file."""
            if self.path == _DATA_ROUTE:
                body = json.dumps(build_gui_data()).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            super().do_GET()

    return GuiRequestHandler


def serve(
    web_dir: Path,
    *,
    port: int,
    open_browser: bool,
    announce: Callable[[str], None],
) -> None:
    """Serve `web_dir` plus /api/gui-data on loopback until interrupted.

    Binds 127.0.0.1 only. The caller is responsible for having checked that
    `web_dir` exists -- this raises OSError through the socket bind if the port
    is taken, which the caller turns into an operator-facing message.

    `announce` receives the URL line to print; passing it in keeps this module
    free of Typer so the server can be exercised without a CLI runner.
    """
    handler = _request_handler(web_dir)
    with http.server.ThreadingHTTPServer(("127.0.0.1", port), handler) as httpd:
        # Read the port back off the socket rather than echoing the argument:
        # port 0 means "let the kernel choose", and then the requested port is
        # not the one a browser needs to be pointed at.
        url = f"http://127.0.0.1:{httpd.server_address[1]}"
        announce(f"Serving {web_dir} on {url} (Ctrl+C to stop)")
        if open_browser:
            # Deferred to a timer thread: webbrowser.open can block for
            # seconds while it launches a browser, and on a cold start the
            # browser may request the page before serve_forever() is running.
            threading.Timer(0.3, lambda: webbrowser.open(url)).start()
        with contextlib.suppress(KeyboardInterrupt):
            httpd.serve_forever()
