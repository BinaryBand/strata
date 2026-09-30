"""JSON request/response helpers shared by gui_server.py and gui_actions.py.

Split out on its own so neither module has to import the other just for this:
gui_server.py routes to gui_actions.py's route bodies, and both need to read a
JSON request body and write a JSON response.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
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


class ApiError(Exception):
    """A request the API refuses, carrying the HTTP status and message to send back."""

    def __init__(self, status: int, message: str) -> None:
        """Record the status and the message that becomes the `error` field."""
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass(frozen=True)
class Request:
    """What a route body needs from one HTTP request, already parsed."""

    body: dict[str, Any] = field(default_factory=dict)
    query: dict[str, str] = field(default_factory=dict)  # first value per key
    args: dict[str, str] = field(default_factory=dict)  # `{name}` captures from the path


def require(data: Mapping[str, Any], *keys: str) -> tuple[Any, ...]:
    """Return the values of `keys` in `data`, or raise a 400 naming the ones needed.

    A missing key and an empty value are the same refusal: none of the routes
    has a meaningful empty answer.
    """
    values = tuple(data.get(key) for key in keys)
    if not all(values):
        verb = "is" if len(keys) == 1 else "are"
        raise ApiError(400, f"{' and '.join(keys)} {verb} required")
    return values


def read_json_body(handler: JsonHandler) -> dict[str, Any]:
    """Parse the request body as a JSON object, or {} if there is none.

    A body that parses to anything but an object is refused here: every route
    reads it with `.get`, so a list or a bare scalar would otherwise surface as
    an AttributeError and a 500 for what is the client's mistake.
    """
    length = int(handler.headers.get("Content-Length", 0) or 0)
    if length == 0:
        return {}
    raw = handler.rfile.read(length)
    if not raw:
        return {}
    body = json.loads(raw)
    if not isinstance(body, dict):
        raise ApiError(400, "request body must be a JSON object")
    return body


def send_json(handler: JsonHandler, status: int, payload: dict[str, Any]) -> None:
    """Write `payload` as the JSON response body with `status`."""
    body = json.dumps(payload).encode()
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)
