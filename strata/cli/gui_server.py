"""The GUI's data snapshot and the loopback API server serving it.

The GUI is a separate Flutter app, in its own repository, that reads and
drives strata through this one seam. `GET /api/gui-data` is read-only -- the
declarations `discovery`/`guard.declared()`/`inventory` produced, nothing
executed. Every other `/api/*` route's body lives in `gui_actions.py`, a thin
bridge onto something that already exists (`guard_executor.execute`,
`inventory.add`, `secrets.set_secret`, ...); this module's job is serving and
routing only. `strata gui` runs the server; `strata dev gui-data` prints the
read-only snapshot once.

This serves the API and nothing else: no static files, no built web bundle.
The app is served by its own tooling, so it reaches this from a different
origin, and every response therefore carries CORS headers. Loopback origins
are echoed back automatically (that is `flutter run`, on whatever port it
picked); any other origin has to be named with `--allow-origin`.

Because the action routes can run privileged playbooks, they require a bearer
token (`strata/adapters/gui_token.py`) that `strata gui` prints. The server
itself still only binds 127.0.0.1 -- reaching it from another device is still
`tailscale serve <port>`, never `tailscale funnel` -- so the token's job is to
stop anything else already on that tailnet from running a playbook against
this box, not to replace the loopback boundary.

This sits in `cli/` rather than `adapters/` for the same reason it always
has: it is a presentation-layer server with no domain logic of its own.
"""

from __future__ import annotations

import contextlib
import http.server
import importlib
from collections.abc import Callable, Sequence
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


def _allowed_origin(origin: str, extra: frozenset[str]) -> str | None:
    """Return the value to echo in Access-Control-Allow-Origin, or None to send none.

    Loopback origins are allowed whatever port they picked: the app is served
    by `flutter run`, which chooses a fresh port per run, so pinning one would
    mean re-flagging the server on every launch. Anything else has to have
    been named on the command line -- a tailnet origin is a deliberate choice,
    not something to infer from the request asking for it.
    """
    if origin in extra:
        return origin
    host = urlsplit(origin).hostname
    return origin if host in {"127.0.0.1", "localhost", "::1"} else None


class GuiRequestHandler(http.server.BaseHTTPRequestHandler):
    """Serves the read-only snapshot and the action API. No static files.

    `_token`/`_allow_origins` are class attributes rather than instance state
    because `http.server` builds one instance per request and only lets a
    `ThreadingHTTPServer` hand it a `handler_class`, not an already-configured
    instance; `_request_handler` sets them once, before the server accepts
    its first request, and a process only ever runs one `strata gui` server.
    """

    _token: str
    _allow_origins: frozenset[str] = frozenset()

    def end_headers(self) -> None:
        """Add the CORS headers to every response, then close the header block.

        Done here rather than at each call site because the action routes in
        `gui_actions.py` write their own responses through `send_json`, and a
        response missing these is one the browser discards before the app
        sees it.
        """
        origin = self.headers.get("Origin")
        allowed = _allowed_origin(origin, self._allow_origins) if origin else None
        if allowed is not None:
            self.send_header("Access-Control-Allow-Origin", allowed)
            self.send_header("Vary", "Origin")
        super().end_headers()

    def _authorized(self) -> bool:
        return self.headers.get("Authorization") == f"Bearer {self._token}"

    def _unauthorized(self) -> None:
        send_json(self, 401, {"error": "missing or invalid access token"})

    def _not_found(self) -> None:
        send_json(self, 404, {"error": "not found"})

    def do_OPTIONS(self) -> None:
        """Answer the preflight the Authorization header and JSON bodies trigger."""
        self.send_response(204)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Max-Age", "86400")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:
        """Serve the read routes; only the run-status route needs the token."""
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
            self._not_found()

    def do_POST(self) -> None:
        """Handle the mutating routes; all require the access token."""
        if not self._authorized():
            self._unauthorized()
            return
        route = gui_actions.POST_ROUTES.get(self.path)
        if route is None:
            self._not_found()
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
            self._not_found()


def _request_handler(
    token: str, allow_origins: frozenset[str]
) -> type[http.server.BaseHTTPRequestHandler]:
    """Configure and return `GuiRequestHandler` for one `strata gui` process's lifetime."""
    GuiRequestHandler._token = token  # noqa: SLF001 -- this module owns GuiRequestHandler
    GuiRequestHandler._allow_origins = allow_origins  # noqa: SLF001
    return GuiRequestHandler


def serve(
    *,
    port: int,
    allow_origins: Sequence[str] = (),
    announce: Callable[[str], None],
) -> None:
    """Serve the /api/* routes on loopback until interrupted.

    Binds 127.0.0.1 only. Raises OSError through the socket bind if the port is
    taken, which the caller turns into an operator-facing message.

    `allow_origins` names the non-loopback origins the app may be served from;
    loopback ones are allowed without being named.

    `announce` receives the lines to print; passing it in keeps this module
    free of Typer so the server can be exercised without a CLI runner.
    """
    token = gui_token.get_or_create_token()
    handler = _request_handler(token, frozenset(allow_origins))
    with http.server.ThreadingHTTPServer(("127.0.0.1", port), handler) as httpd:
        # Read the port back off the socket rather than echoing the argument:
        # port 0 means "let the kernel choose", and then the requested port is
        # not the one the app needs to be pointed at.
        url = f"http://127.0.0.1:{httpd.server_address[1]}"
        announce(f"Serving the strata API on {url} (Ctrl+C to stop)")
        announce(f"Access token: {token}")
        with contextlib.suppress(KeyboardInterrupt):
            httpd.serve_forever()
