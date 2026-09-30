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
token (`src/strata/adapters/gui_token.py`) that `strata gui` prints. The server
itself still only binds 127.0.0.1 -- reaching it from another device is still
`tailscale serve <port>`, never `tailscale funnel` -- so the token's job is to
stop anything else already on that tailnet from running a playbook against
this box, not to replace the loopback boundary.

This sits in `cli/` rather than `adapters/` for the same reason it always
has: it is a presentation-layer server with no domain logic of its own.
"""

from __future__ import annotations

import contextlib
import dataclasses
import http.server
import re
import traceback
from collections.abc import Callable, Sequence
from typing import Any, assert_never
from urllib.parse import parse_qs, urlsplit

from strata.adapters import gui_token
from strata.adapters.ansible import inventory
from strata.cli import gui_actions
from strata.cli.gui_http import ApiError, Request, read_json_body, send_json
from strata.core import discovery, guard
from strata.core import requirements as req


def _capitalize_first(text: str) -> str:
    """Upper-case the first character only; `str.capitalize` would lowercase the rest.

    Runbook summaries read "<lowercase sentence>." by convention (enforced by
    nothing but habit); the GUI wants a sentence on its own, matching how the
    mockup this ships from phrased it.
    """
    return text[:1].upper() + text[1:]


def _guard_label(r: req.Requirement) -> str:  # noqa: PLR0911, C901 -- one arm per Requirement variant
    """Human-readable label for one declared requirement.

    Mirrors the phrasing guard_executor's prompts and reporter use, so a GUI
    consuming this can show the same vocabulary an operator sees on the CLI.
    `assert_never` makes the type checker fail when a Requirement variant has
    no label, rather than the GUI silently rendering its class name.
    """
    match r:
        case req.Prerequisite():
            return "Sudo password" if r.name == "sudo_password" else f"Prerequisite: {r.name}"
        case req.Secret():
            return f"Secret: {r.vault_key}"
        case req.SystemUser():
            return f"System user: {r.username}"
        case req.LocalPath():
            return f"Path: {r.path}"
        case req.Mount():
            return f"Mount: {r.remote_path}"
        case req.Storage():
            return f"Storage: {r.vault_key}"
        case req.UpstreamRunbook():
            return f"Requires {r.dotted_name}"
        case req.ControllerOnly():
            return _capitalize_first(r.reason)
        case _:
            assert_never(r)


def build_gui_data() -> dict[str, Any]:
    """Build the JSON-able snapshot of the runbook catalog and device inventory.

    Read-only: no runbook's check() is invoked and nothing is executed. Shared
    by `strata dev gui-data` (prints it once, for the desktop build's dart:io
    shell-out) and `strata gui` (serves it live, for the web build's fetch).
    """
    runbooks = []
    for info in discovery.iter_runbooks():
        module = discovery.load(info.dotted_name)
        declared = guard.declared(module.main)
        guards = [{"type": type(r).__name__, "label": _guard_label(r)} for r in declared]
        runbooks.append(
            {
                "dotted_name": info.dotted_name,
                "leaf": info.leaf,
                "category": info.category,
                "alias": info.alias,
                "description": _capitalize_first(info.summary),
                "accepts_tags": info.accepts_tags,
                "has_check": hasattr(module, "check"),
                "guards": guards,
            }
        )

    import_failures = [
        {"dotted_name": f.dotted_name, "error": f.error} for f in discovery.import_failures()
    ]

    devices = [{**d.model_dump(), "is_controller": d.is_controller} for d in inventory.all_hosts()]

    return {"runbooks": runbooks, "import_failures": import_failures, "devices": devices}


@dataclasses.dataclass(frozen=True)
class Route:
    """One API route: where it is, what runs, and whether it needs the token."""

    method: str
    template: str  # a path with `{name}` segments captured into `Request.args`
    handler: Callable[[Request], dict[str, Any]]
    needs_token: bool = True  # a route is closed unless it says otherwise
    pattern: re.Pattern[str] = dataclasses.field(init=False)  # the template, as an anchored regex

    def __post_init__(self) -> None:
        """Compile the template once: one named group per `{name}`."""
        regex = "^" + re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", self.template) + "$"
        object.__setattr__(self, "pattern", re.compile(regex))


def _get_gui_data(_request: Request) -> dict[str, Any]:
    return build_gui_data()


# The read routes are open (the snapshot and the readiness probes leak nothing
# that running a playbook would); the run-status poll and every mutating route
# need the bearer token. docs/ARCHITECTURE.md carries the same table.
_ROUTES = (
    Route("GET", "/api/gui-data", _get_gui_data, needs_token=False),
    Route("GET", "/api/runbook-status", gui_actions.get_runbook_status, needs_token=False),
    Route("GET", "/api/vault-status", gui_actions.get_vault_status, needs_token=False),
    Route("GET", "/api/reachable", gui_actions.get_reachable, needs_token=False),
    Route("GET", "/api/run/{run_id}", gui_actions.get_run_status),
    Route("POST", "/api/run", gui_actions.post_run),
    Route("POST", "/api/devices", gui_actions.post_device),
    Route("DELETE", "/api/devices/{name}", gui_actions.delete_device),
    Route("POST", "/api/secrets", gui_actions.post_secret),
    Route("POST", "/api/vault-password", gui_actions.post_vault_password),
)


_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def _host_name(value: str) -> str | None:
    """Return the lower-cased host name in a `Host` header or an origin, without its port."""
    return urlsplit(value if "//" in value else f"//{value}").hostname


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
    return origin if _host_name(origin) in _LOOPBACK_HOSTS else None


def _allowed_hosts(allow_origins: Sequence[str], allow_hosts: Sequence[str]) -> frozenset[str]:
    """Return the `Host` names a request may carry: loopback, each named origin's, and any named.

    A named origin's host is allowed because `tailscale serve` forwards the
    tailnet name it was reached on as `Host`, which is that origin's host.
    """
    named = {_host_name(value) for value in (*allow_origins, *allow_hosts)}
    return _LOOPBACK_HOSTS | {name for name in named if name}


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
    _allowed_hosts: frozenset[str] = _LOOPBACK_HOSTS

    def end_headers(self) -> None:
        """Add the CORS headers to every response, then close the header block.

        Done here rather than at each call site because every response goes
        through `send_json`, and one missing these is one the browser discards
        before the app sees it.
        """
        origin = self.headers.get("Origin")
        allowed = _allowed_origin(origin, self._allow_origins) if origin else None
        if allowed is not None:
            self.send_header("Access-Control-Allow-Origin", allowed)
            self.send_header("Vary", "Origin")
        super().end_headers()

    def _authorized(self) -> bool:
        return self.headers.get("Authorization") == f"Bearer {self._token}"

    def do_OPTIONS(self) -> None:
        """Answer the preflight the Authorization header and JSON bodies trigger."""
        self.send_response(204)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Max-Age", "86400")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:
        """Serve a GET route."""
        self._dispatch("GET")

    def do_POST(self) -> None:
        """Serve a POST route."""
        self._dispatch("POST")

    def do_DELETE(self) -> None:
        """Serve a DELETE route."""
        self._dispatch("DELETE")

    def _dispatch(self, method: str) -> None:
        """Match the request to a route, check the token once, run it, send the result.

        An unknown mutating request is refused with 401 before 404, so an
        unauthenticated caller cannot probe which paths exist; an unknown GET
        is just a 404, since there is nothing behind it to hide. Anything a
        route body raises becomes a JSON response: without this the exception
        unwound out of the handler and the socket closed with nothing sent.
        """
        # DNS rebinding: a web page can point its own domain at 127.0.0.1, and
        # the browser then treats this server as same-origin with that page, so
        # CORS never applies and the open read routes -- every inventory host,
        # address and user -- are readable. The page cannot change the `Host`
        # it sends, which still names its own domain.
        if _host_name(self.headers.get("Host", "")) not in self._allowed_hosts:
            send_json(self, 403, {"error": "unrecognised Host; name it with --allow-host"})
            return
        parsed = urlsplit(self.path)
        matches = (
            (route, found)
            for route in _ROUTES
            if route.method == method and (found := route.pattern.match(parsed.path))
        )
        route, found = next(matches, (None, None))
        if (route.needs_token if route else method != "GET") and not self._authorized():
            send_json(self, 401, {"error": "missing or invalid access token"})
            return
        if route is None or found is None:
            send_json(self, 404, {"error": "not found"})
            return
        try:
            request = Request(
                body=read_json_body(self) if method != "GET" else {},
                query={key: values[0] for key, values in parse_qs(parsed.query).items()},
                args=found.groupdict(),
            )
            send_json(self, 200, route.handler(request))
        except ApiError as exc:
            send_json(self, exc.status, {"error": exc.message})
        except Exception:  # noqa: BLE001 -- the last line of defence: answer, do not drop the socket
            self.log_error(
                "unhandled error in %s %s:\n%s", method, parsed.path, traceback.format_exc()
            )
            send_json(self, 500, {"error": "internal error"})


def _request_handler(
    token: str, allow_origins: Sequence[str], allow_hosts: Sequence[str]
) -> type[http.server.BaseHTTPRequestHandler]:
    """Configure and return `GuiRequestHandler` for one `strata gui` process's lifetime."""
    GuiRequestHandler._token = token  # noqa: SLF001 -- this module owns GuiRequestHandler
    GuiRequestHandler._allow_origins = frozenset(allow_origins)  # noqa: SLF001
    GuiRequestHandler._allowed_hosts = _allowed_hosts(allow_origins, allow_hosts)  # noqa: SLF001
    return GuiRequestHandler


def serve(
    *,
    port: int,
    allow_origins: Sequence[str] = (),
    allow_hosts: Sequence[str] = (),
    announce: Callable[[str], None],
) -> None:
    """Serve the /api/* routes on loopback until interrupted.

    Binds 127.0.0.1 only. Raises OSError through the socket bind if the port is
    taken, which the caller turns into an operator-facing message.

    `allow_origins` names the non-loopback origins the app may be served from;
    loopback ones are allowed without being named. A request is answered only
    when its `Host` is loopback, one of those origins' hosts, or in
    `allow_hosts`.

    `announce` receives the lines to print; passing it in keeps this module
    free of Typer so the server can be exercised without a CLI runner.
    """
    token = gui_token.get_or_create_token()
    handler = _request_handler(token, allow_origins, allow_hosts)
    with http.server.ThreadingHTTPServer(("127.0.0.1", port), handler) as httpd:
        # Read the port back off the socket rather than echoing the argument:
        # port 0 means "let the kernel choose", and then the requested port is
        # not the one the app needs to be pointed at.
        url = f"http://127.0.0.1:{httpd.server_address[1]}"
        announce(f"Serving the strata API on {url} (Ctrl+C to stop)")
        announce(f"Access token: {token}")
        with contextlib.suppress(KeyboardInterrupt):
            httpd.serve_forever()
