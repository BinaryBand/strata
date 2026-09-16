"""JSON request/response helpers shared by gui_server.py and gui_actions.py.

Split out on its own so neither module has to import the other just for this:
gui_server.py routes to gui_actions.py's route bodies, and both need to read a
JSON request body and write a JSON response.
"""

from __future__ import annotations

import json
from typing import Any, Protocol


class JsonHandler(Protocol):
    """The slice of BaseHTTPRequestHandler these helpers need.

    A Protocol rather than `http.server.BaseHTTPRequestHandler` itself so a
    test double can satisfy it structurally without going through that
    class's real `__init__` (which wants a live socket). `rfile`/`wfile` stay
    `Any`: the real handler's are `io.BufferedIOBase`, a test double's a bare
    `io.BytesIO`, and typing them as `IO[bytes]` here would demand invariant
    agreement neither one owes -- only `.read()`/`.write()` matter.
    """

    headers: Any
    rfile: Any
    wfile: Any

    def send_response(self, _code: int, /) -> None:
        """Write the status line."""
        ...

    def send_header(self, _keyword: str, _value: str, /) -> None:
        """Write one response header."""
        ...

    def end_headers(self) -> None:
        """Write the blank line ending the headers."""
        ...


def read_json_body(handler: JsonHandler) -> dict[str, Any]:
    """Parse the request body as a JSON object, or {} if there is none."""
    length = int(handler.headers.get("Content-Length", 0) or 0)
    if length == 0:
        return {}
    raw = handler.rfile.read(length)
    return json.loads(raw) if raw else {}


def send_json(handler: JsonHandler, status: int, payload: dict[str, Any]) -> None:
    """Write `payload` as the JSON response body with `status`."""
    body = json.dumps(payload).encode()
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)
