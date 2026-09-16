"""Unit tests for strata.cli.gui_http -- JSON request/response helpers."""

from __future__ import annotations

import io
import json

from strata.cli import gui_http


class FakeHandler:
    """Just enough of BaseHTTPRequestHandler's surface for these helpers."""

    def __init__(self, *, body: bytes = b"") -> None:
        self.headers = {"Content-Length": str(len(body))} if body else {}
        self.rfile = io.BytesIO(body)
        self.wfile = io.BytesIO()
        self.status: int | None = None
        self.response_headers: dict[str, str] = {}

    def send_response(self, status: int) -> None:
        self.status = status

    def send_header(self, name: str, value: str) -> None:
        self.response_headers[name] = value

    def end_headers(self) -> None:
        pass


def test_read_json_body_parses_the_body() -> None:
    handler = FakeHandler(body=json.dumps({"a": 1}).encode())
    assert gui_http.read_json_body(handler) == {"a": 1}


def test_read_json_body_empty_when_no_content_length() -> None:
    handler = FakeHandler()
    assert gui_http.read_json_body(handler) == {}


def test_send_json_writes_status_headers_and_body() -> None:
    handler = FakeHandler()
    gui_http.send_json(handler, 201, {"ok": True})
    assert handler.status == 201
    assert handler.response_headers["Content-Type"] == "application/json"
    body = handler.wfile.getvalue()
    assert handler.response_headers["Content-Length"] == str(len(body))
    assert json.loads(body) == {"ok": True}
