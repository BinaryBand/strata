"""Unit tests for strata.cli.gui_actions -- the GUI's action route bodies.

Each route body is a thin bridge onto an existing adapter function, so these
tests monkeypatch that adapter function directly rather than re-testing its
own behaviour (which has its own test module already).
"""

from __future__ import annotations

import io
import json
import threading
import time
from types import ModuleType
from typing import Any

import pytest

from strata.adapters.ansible import host_vars, inventory, secrets, vault_pass
from strata.cli import gui_actions
from strata.core.models import Device


class FakeHandler:
    """Just enough of BaseHTTPRequestHandler's surface for these route bodies."""

    def __init__(self, *, body: bytes = b"") -> None:
        self.headers = {"Content-Length": str(len(body))} if body else {}
        self.rfile = io.BytesIO(body)
        self.wfile = io.BytesIO()
        self.status: int | None = None

    def send_response(self, status: int) -> None:
        self.status = status

    def send_header(self, _name: str, _value: str) -> None:
        pass

    def end_headers(self) -> None:
        pass

    def json(self) -> dict:
        return json.loads(self.wfile.getvalue())


# ── runbook_status / get_runbook_status ─────────────────────────────────


def test_runbook_status_unknown_runbook(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gui_actions.discovery, "resolve_name", lambda _n: None)
    status, payload = gui_actions.runbook_status("nope", None)
    assert status == 404
    assert "error" in payload


def test_runbook_status_reports_guards_and_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_module = ModuleType("fake_runbook")
    fake_module.__dict__["main"] = lambda **_: 0
    fake_module.__dict__["check"] = lambda: True
    monkeypatch.setattr(gui_actions.discovery, "resolve_name", lambda _n: "services.fake")
    monkeypatch.setattr(gui_actions.importlib, "import_module", lambda _n: fake_module)

    status, payload = gui_actions.runbook_status("fake", None)

    assert status == 200
    assert payload == {"dotted_name": "services.fake", "guards": [], "installed": True}


def test_get_runbook_status_requires_dotted_name() -> None:
    handler = FakeHandler()
    gui_actions.get_runbook_status(handler, {})
    assert handler.status == 400


# ── run lifecycle ────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_current_run() -> None:
    gui_actions._current_run = None


def test_start_run_unknown_runbook(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gui_actions.discovery, "resolve_name", lambda _n: None)
    status, payload = gui_actions.start_run("nope", None, None)
    assert status == 400
    assert "error" in payload


def _fake_execute(_module: object, **kwargs: Any) -> int:
    kwargs["reporter"].info("done")
    return 0


def test_start_run_then_poll_until_done(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_module = ModuleType("fake_runbook")
    fake_module.__dict__["main"] = lambda **_: 0
    monkeypatch.setattr(gui_actions.discovery, "resolve_name", lambda _n: "services.fake")
    monkeypatch.setattr(gui_actions.importlib, "import_module", lambda _n: fake_module)
    monkeypatch.setattr(gui_actions.runner, "set_reporter", lambda _r: None)
    monkeypatch.setattr(gui_actions.guard_executor, "execute", _fake_execute)

    status, payload = gui_actions.start_run("fake", None, None)
    assert status == 200
    run_id = payload["run_id"]

    deadline = time.monotonic() + 2
    state = gui_actions.get_run(run_id)
    while state is not None and state.status == "running" and time.monotonic() < deadline:
        time.sleep(0.01)
        state = gui_actions.get_run(run_id)

    assert state is not None
    assert state.status == "succeeded"
    assert state.exit_code == 0
    assert "done" in state.reporter.lines


def test_a_second_run_is_refused_while_one_is_in_flight(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_module = ModuleType("fake_runbook")
    started = threading.Event()
    finish = threading.Event()

    def slow_execute(_module: object, **_kwargs: object) -> int:
        started.set()
        finish.wait(timeout=2)
        return 0

    fake_module.__dict__["main"] = lambda **_: 0
    monkeypatch.setattr(gui_actions.discovery, "resolve_name", lambda _n: "services.fake")
    monkeypatch.setattr(gui_actions.importlib, "import_module", lambda _n: fake_module)
    monkeypatch.setattr(gui_actions.runner, "set_reporter", lambda _r: None)
    monkeypatch.setattr(gui_actions.guard_executor, "execute", slow_execute)

    first_status, _ = gui_actions.start_run("fake", None, None)
    assert first_status == 200
    assert started.wait(timeout=2)

    second_status, second_payload = gui_actions.start_run("fake", None, None)
    assert second_status == 409
    assert "error" in second_payload

    finish.set()


def test_get_run_status_unknown_id() -> None:
    handler = FakeHandler()
    gui_actions.get_run_status(handler, "nope")
    assert handler.status == 404


# ── vault password / secrets ─────────────────────────────────────────────


def test_post_vault_password_requires_a_value() -> None:
    handler = FakeHandler(body=b"{}")
    gui_actions.post_vault_password(handler, {})
    assert handler.status == 400


def test_post_vault_password_sets_it(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    monkeypatch.setattr(vault_pass, "set_vault_password", calls.append)
    handler = FakeHandler()
    gui_actions.post_vault_password(handler, {"value": "hunter2"})
    assert handler.status == 200
    assert calls == ["hunter2"]


def test_post_secret_requires_vault_password_first(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(vault_pass, "has_vault_password", lambda: False)
    handler = FakeHandler()
    gui_actions.post_secret(handler, {"vault_key": "tailscale_auth_key", "value": "x"})
    assert handler.status == 400


def test_post_secret_sets_it_once_vault_is_unlocked(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(vault_pass, "has_vault_password", lambda: True)
    calls = []
    monkeypatch.setattr(secrets, "set_secret", lambda k, v: calls.append((k, v)))
    handler = FakeHandler()
    gui_actions.post_secret(handler, {"vault_key": "tailscale_auth_key", "value": "x"})
    assert handler.status == 200
    assert calls == [("tailscale_auth_key", "x")]


# ── devices ───────────────────────────────────────────────────────────────


def test_post_device_requires_name_and_host() -> None:
    handler = FakeHandler()
    gui_actions.post_device(handler, {"name": "rpi4"})
    assert handler.status == 400


def test_post_device_adds_it(monkeypatch: pytest.MonkeyPatch) -> None:
    device = Device(name="rpi4", host="10.0.0.9", user="pi", connection="ssh")
    monkeypatch.setattr(inventory, "add", lambda *_a, **_kw: device)
    handler = FakeHandler()
    gui_actions.post_device(handler, {"name": "rpi4", "host": "10.0.0.9", "user": "pi"})
    assert handler.status == 200
    assert handler.json()["name"] == "rpi4"


def test_delete_device_unknown_is_404(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(inventory, "remove", lambda _n: False)
    handler = FakeHandler()
    gui_actions.delete_device(handler, "nope")
    assert handler.status == 404


def test_delete_device_removes_host_vars_too(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(inventory, "remove", lambda _n: True)
    calls = []
    monkeypatch.setattr(host_vars, "discard", lambda n: calls.append(n) or True)
    handler = FakeHandler()
    gui_actions.delete_device(handler, "rpi4")
    assert handler.status == 200
    assert calls == ["rpi4"]


def test_get_reachable_requires_a_host() -> None:
    handler = FakeHandler()
    gui_actions.get_reachable(handler, {})
    assert handler.status == 400


def test_get_reachable_delegates_to_tcp_reachable(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = []

    def fake_tcp_reachable(host: str, port: int) -> bool:
        seen.append((host, port))
        return True

    monkeypatch.setattr(gui_actions.reachability, "tcp_reachable", fake_tcp_reachable)
    handler = FakeHandler()
    gui_actions.get_reachable(handler, {"host": ["10.0.0.9"], "port": ["2222"]})
    assert handler.status == 200
    assert handler.json() == {"reachable": True}
    assert seen == [("10.0.0.9", 2222)]


def test_get_reachable_defaults_port_to_22(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = []

    def fake_tcp_reachable(host: str, port: int) -> bool:
        seen.append((host, port))
        return True

    monkeypatch.setattr(gui_actions.reachability, "tcp_reachable", fake_tcp_reachable)
    handler = FakeHandler()
    gui_actions.get_reachable(handler, {"host": ["10.0.0.9"]})
    assert seen == [("10.0.0.9", 22)]
