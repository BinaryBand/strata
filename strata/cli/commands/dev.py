"""`strata dev`: maintainer-only tooling, hidden from the top-level help.

Registered with ``hidden=True`` so it never clutters an operator's ``--help``;
it is still fully invokable as ``strata dev <command>`` for whoever works on
strata itself.
"""

from __future__ import annotations

import contextlib
import http.server
import importlib
import json
import socket
import socketserver
from collections.abc import Callable
from pathlib import Path
from typing import Any

import typer

from strata.adapters.ansible import inventory
from strata.core import discovery, guard
from strata.core import requirements as req
from strata.core.models import ServerAppsDefaults

app = typer.Typer(
    no_args_is_help=True,
    help="Maintainer tooling (not shown in the top-level help).",
)


@app.command("schema")
def dev_schema() -> None:
    """Write the JSON Schema for server_apps_defaults.yml to .vscode/.

    Regenerates .vscode/server_apps_schema.json from the Pydantic model at
    strata/core/models/server_apps_config.py.  VS Code yaml.schemas points at
    that file, so editing the YAML gets intellisense and validation.
    Run this any time you change the model structure.
    """
    out_path = ServerAppsDefaults.write_schema()
    typer.echo(f"Wrote schema to {out_path}")


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


def _build_gui_data() -> dict[str, Any]:
    """Build the JSON-able snapshot of the runbook catalog and device inventory.

    Read-only: no runbook's check() is invoked and nothing is executed. Shared
    by `gui-data` (prints it once, for the desktop build's dart:io shell-out)
    and `gui-serve` (serves it live, for the web build's HTTP fetch).
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


@app.command("gui-data")
def dev_gui_data() -> None:
    """Print a JSON snapshot of the runbook catalog and device inventory.

    This is what gui/ shells out to (`strata dev gui-data`) on desktop to
    replace its mock runbook/device lists with the real catalog -- install
    status and machine reachability are not in scope here, only the static
    declarations.
    """
    typer.echo(json.dumps(_build_gui_data(), indent=2))


def _gui_request_handler(web_dir: Path) -> type[http.server.SimpleHTTPRequestHandler]:
    """Build a request handler serving `web_dir` plus a live /api/gui-data.

    A closure rather than a module-level class because the static root is
    only known once `gui-serve` runs, and SimpleHTTPRequestHandler takes it
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
            if self.path == "/api/gui-data":
                body = json.dumps(_build_gui_data()).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            super().do_GET()

    return GuiRequestHandler


@app.command("gui-serve")
def dev_gui_serve(port: int = 8765) -> None:
    """Serve the built gui/ web app plus its data endpoint on loopback.

    Serves gui/build/web/ as static files and GET /api/gui-data as the same
    read-only snapshot `gui-data` prints, so the web build -- which has no
    dart:io and so cannot shell out -- gets the real catalog instead of
    gui/lib/mock_data.dart's sample data.

    Binds 127.0.0.1 only. Pair with `tailscale serve <port>` to reach it from
    the tailnet; not `tailscale funnel` -- this fronts a tool that reads the
    vault and drives ansible-runner against real machines, even though
    nothing served here executes anything yet.

    Run `flutter build web` in gui/ first; this command does not build it.
    """
    web_dir = Path(__file__).resolve().parents[3] / "gui" / "build" / "web"
    if not web_dir.is_dir():
        typer.echo(f"No build at {web_dir} -- run `flutter build web` in gui/ first.", err=True)
        raise typer.Exit(1)

    handler = _gui_request_handler(web_dir)
    with http.server.ThreadingHTTPServer(("127.0.0.1", port), handler) as httpd:
        typer.echo(f"Serving {web_dir} on http://127.0.0.1:{port} (Ctrl+C to stop)")
        with contextlib.suppress(KeyboardInterrupt):
            httpd.serve_forever()
