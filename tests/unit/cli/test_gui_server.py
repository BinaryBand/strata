"""Unit tests for strata.cli.gui_server -- the GUI's data snapshot and server.

The snapshot is a wire format: the GUI app's lib/data/strata_cli.dart parses it by key and
maps the guard `type` strings onto a Dart enum, falling back silently when it
meets one it doesn't know. Nothing but these tests keeps the two sides in step,
so the contract tests below assert the key set and that every requirement
dataclass has a label.
"""

from __future__ import annotations

import http.client
import json
import threading
import urllib.error
import urllib.request

import pytest

from strata.cli import gui_server
from strata.core import requirements as req
from strata.core.discovery import RunbookInfo

# The keys the GUI app's lib/data/strata_cli.dart reads out of each object. Changing a
# name here without changing the Dart side makes the GUI fall back to sample
# data at runtime, with no error anywhere.
_RUNBOOK_KEYS = {
    "dotted_name",
    "leaf",
    "category",
    "alias",
    "description",
    "accepts_tags",
    "has_check",
    "guards",
}
_DEVICE_KEYS = {"name", "host", "user", "connection", "port", "is_controller"}


# -- the snapshot --------------------------------------------------------


@pytest.fixture(scope="module")
def snapshot() -> dict:
    """The real snapshot, built once -- it imports every runbook module."""
    return gui_server.build_gui_data()


def test_snapshot_has_the_three_top_level_sections(snapshot: dict) -> None:
    assert set(snapshot) == {"runbooks", "import_failures", "devices"}


def test_snapshot_is_json_serializable(snapshot: dict) -> None:
    """The whole point is that it survives json.dumps for both consumers."""
    assert json.loads(json.dumps(snapshot)) == snapshot


def test_snapshot_finds_runbooks(snapshot: dict) -> None:
    dotted = {r["dotted_name"] for r in snapshot["runbooks"]}
    assert "services.install_jellyfin" in dotted


def test_every_runbook_carries_exactly_the_dart_keys(snapshot: dict) -> None:
    for runbook in snapshot["runbooks"]:
        assert set(runbook) == _RUNBOOK_KEYS, runbook["dotted_name"]


def test_every_device_carries_exactly_the_dart_keys(snapshot: dict) -> None:
    for device in snapshot["devices"]:
        assert set(device) == _DEVICE_KEYS, device


def test_guards_are_type_and_label_pairs(snapshot: dict) -> None:
    for runbook in snapshot["runbooks"]:
        for guard in runbook["guards"]:
            assert set(guard) == {"type", "label"}
            assert guard["label"], f"empty label for {guard['type']}"


def test_jellyfin_guard_chain_is_reported_in_declaration_order(snapshot: dict) -> None:
    """Order matters: the GUI renders the chain as the sequence it will run."""
    jellyfin = next(
        r for r in snapshot["runbooks"] if r["dotted_name"] == "services.install_jellyfin"
    )
    types = [g["type"] for g in jellyfin["guards"]]
    assert types, "install_jellyfin declares guards"
    assert types.index("Prerequisite") < types.index("LocalPath")


# -- the guard-label contract -------------------------------------------


def test_sudo_password_prerequisite_gets_the_friendly_label() -> None:
    assert gui_server._guard_label(req.Prerequisite("sudo_password")) == "Sudo password"


def test_other_prerequisites_keep_their_name() -> None:
    assert gui_server._guard_label(req.Prerequisite("podman")) == "Prerequisite: podman"


# -- description formatting ---------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Runbook: install jellyfin.", "Install jellyfin."),
        ("Runbook:install jellyfin.", "Install jellyfin."),
        ("install jellyfin.", "Install jellyfin."),
        ("", ""),
        ("Runbook:", ""),
    ],
)
def test_description_strips_prefix_and_capitalizes(raw: str, expected: str) -> None:
    info = RunbookInfo(
        dotted_name="x", leaf="x", category="", docstring_first_line=raw, accepts_tags=False
    )
    assert gui_server._capitalize_first(info.summary) == expected


# -- the server ---------------------------------------------------------


_TOKEN = "test-token"


@pytest.fixture
def served(monkeypatch: pytest.MonkeyPatch) -> str:
    """Run `serve` on an ephemeral port in a thread; yield its base URL.

    Port 0 lets the kernel pick, so a developer already running `strata gui`
    doesn't collide with the suite. The daemon thread dies with the session;
    ThreadingHTTPServer has no clean cross-version shutdown from inside a
    KeyboardInterrupt-suppressing serve().
    """
    monkeypatch.setattr(gui_server.gui_token, "get_or_create_token", lambda: _TOKEN)
    urls: list[str] = []
    ready = threading.Event()

    def announce(line: str) -> None:
        if " on " not in line:
            return
        urls.append(line.rsplit(" on ", 1)[1].split(" ", maxsplit=1)[0])
        ready.set()

    thread = threading.Thread(
        target=gui_server.serve,
        kwargs={"port": 0, "allow_origins": ["https://box.example.ts.net"], "announce": announce},
        daemon=True,
    )
    thread.start()
    assert ready.wait(timeout=5), "server never announced its URL"
    return urls[0]


def _get(url: str, origin: str | None = None) -> http.client.HTTPResponse:
    request = urllib.request.Request(url)
    if origin is not None:
        request.add_header("Origin", origin)
    return urllib.request.urlopen(request, timeout=5)


def test_serve_hands_out_the_data_endpoint(served: str) -> None:
    with _get(f"{served}/api/gui-data") as response:
        assert response.headers["Content-Type"] == "application/json"
        payload = json.loads(response.read())
    assert set(payload) == {"runbooks", "import_failures", "devices"}


def test_serve_404s_an_unknown_path(served: str) -> None:
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        _get(f"{served}/nope.js")
    assert excinfo.value.code == 404


def test_serve_serves_no_static_files(served: str) -> None:
    """The app lives in its own repo now; a path that isn't a route is a 404."""
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        _get(f"{served}/index.html")
    assert excinfo.value.code == 404


def test_serve_announces_the_port_it_actually_bound(served: str) -> None:
    """With port 0 the kernel picks; the announced URL has to be the real one."""
    assert served.startswith("http://127.0.0.1:")
    assert int(served.rsplit(":", 1)[1]) > 0


# -- CORS ----------------------------------------------------------------


def test_a_loopback_origin_is_echoed_back(served: str) -> None:
    """`flutter run` picks a fresh port per launch, so any loopback port passes."""
    with _get(f"{served}/api/gui-data", origin="http://localhost:54321") as response:
        assert response.headers["Access-Control-Allow-Origin"] == "http://localhost:54321"


def test_a_named_origin_is_echoed_back(served: str) -> None:
    with _get(f"{served}/api/gui-data", origin="https://box.example.ts.net") as response:
        assert response.headers["Access-Control-Allow-Origin"] == "https://box.example.ts.net"


def test_an_unnamed_remote_origin_gets_no_cors_header(served: str) -> None:
    """Without the header the browser discards the response, which is the point."""
    with _get(f"{served}/api/gui-data", origin="https://evil.example") as response:
        assert response.headers["Access-Control-Allow-Origin"] is None


def test_preflight_allows_the_token_header(served: str) -> None:
    request = urllib.request.Request(
        f"{served}/api/run",
        method="OPTIONS",
        headers={"Origin": "http://localhost:54321"},
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        assert response.status == 204
        assert "Authorization" in response.headers["Access-Control-Allow-Headers"]
        assert response.headers["Access-Control-Allow-Origin"] == "http://localhost:54321"


# -- routing and auth ----------------------------------------------------


def _send(
    url: str,
    method: str,
    *,
    body: bytes | None = None,
    token: str | None = None,
) -> tuple[int, dict]:
    request = urllib.request.Request(url, data=body, method=method)
    if token is not None:
        request.add_header("Authorization", f"Bearer {token}")
    if body is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def test_a_read_route_is_open(served: str) -> None:
    status, payload = _send(f"{served}/api/vault-status", "GET")
    assert status == 200
    assert "has_vault_password" in payload


def test_a_mutating_route_without_the_token_is_401(served: str) -> None:
    status, _ = _send(f"{served}/api/run", "POST", body=b"{}")
    assert status == 401


def test_the_run_status_poll_needs_the_token(served: str) -> None:
    assert _send(f"{served}/api/run/abc", "GET")[0] == 401
    assert _send(f"{served}/api/run/abc", "GET", token=_TOKEN)[0] == 404


def test_an_unknown_mutating_path_is_401_before_404(served: str) -> None:
    """An unauthenticated caller cannot probe which mutating paths exist."""
    assert _send(f"{served}/api/nope", "POST", body=b"{}")[0] == 401
    assert _send(f"{served}/api/nope", "POST", body=b"{}", token=_TOKEN)[0] == 404


def test_a_route_is_only_reachable_by_its_own_method(served: str) -> None:
    assert _send(f"{served}/api/gui-data", "POST", body=b"{}", token=_TOKEN)[0] == 404


def test_a_missing_field_is_a_400_with_the_message(served: str) -> None:
    status, payload = _send(f"{served}/api/run", "POST", body=b"{}", token=_TOKEN)
    assert status == 400
    assert payload == {"error": "dotted_name is required"}


def test_a_malformed_json_body_is_a_400_not_a_dropped_connection(served: str) -> None:
    status, payload = _send(f"{served}/api/run", "POST", body=b"{not json", token=_TOKEN)
    assert status == 400
    assert "error" in payload


def test_a_non_object_json_body_is_a_400_not_a_500(served: str) -> None:
    status, payload = _send(f"{served}/api/run", "POST", body=b"[]", token=_TOKEN)
    assert (status, payload) == (400, {"error": "request body must be a JSON object"})


def test_an_unexpected_failure_is_a_500_not_a_dropped_connection(
    served: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(_request: object) -> dict:
        msg = "kaboom"
        raise RuntimeError(msg)

    monkeypatch.setattr(gui_server, "_ROUTES", (gui_server.Route("GET", "/api/boom", boom),))
    status, payload = _send(f"{served}/api/boom", "GET", token=_TOKEN)
    assert (status, payload) == (500, {"error": "internal error"})


def test_a_value_error_in_a_route_is_a_logged_500_not_a_400(
    served: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A bug that raises ValueError is the server's fault, not the client's."""

    def boom(_request: object) -> dict:
        msg = "internal detail"
        raise ValueError(msg)

    monkeypatch.setattr(gui_server, "_ROUTES", (gui_server.Route("GET", "/api/boom", boom),))
    status, payload = _send(f"{served}/api/boom", "GET", token=_TOKEN)
    assert (status, payload) == (500, {"error": "internal error"})
