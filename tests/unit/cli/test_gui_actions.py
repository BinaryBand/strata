"""Unit tests for strata.cli.gui_actions -- the GUI's action route bodies.

Each route body is a thin bridge onto an existing adapter function, so these
tests monkeypatch that adapter function directly rather than re-testing its
own behaviour (which has its own test module already).
"""

from __future__ import annotations

import threading
import time
from types import ModuleType
from typing import Any

import pytest

from strata.adapters.ansible import host_vars, inventory, secrets, vault_pass
from strata.cli import gui_actions
from strata.cli.gui_http import ApiError, Request
from strata.core import discovery
from strata.core.models import Device

# ── runbook_status / get_runbook_status ─────────────────────────────────


def test_runbook_status_unknown_runbook(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gui_actions.discovery, "resolve_name", lambda _n: None)
    with pytest.raises(ApiError) as excinfo:
        gui_actions.runbook_status("nope", None)
    assert excinfo.value.status == 404


def test_runbook_status_reports_guards_and_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_module = ModuleType("fake_runbook")
    fake_module.__dict__["main"] = lambda **_: 0
    fake_module.__dict__["check"] = lambda: True
    monkeypatch.setattr(gui_actions.discovery, "resolve_name", lambda _n: "services.fake")
    monkeypatch.setattr(discovery.importlib, "import_module", lambda _n: fake_module)

    payload = gui_actions.runbook_status("fake", None)

    assert payload == {"dotted_name": "services.fake", "guards": [], "installed": True}


def test_runbook_status_does_not_answer_installed_for_a_remote_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """check() reads the controller's filesystem, so it says nothing about a remote host.

    The guards half of this payload has always been target-aware. `installed`
    was not, so one response described two machines.
    """
    fake_module = ModuleType("fake_runbook")
    fake_module.__dict__["main"] = lambda **_: 0
    fake_module.__dict__["check"] = lambda: True
    monkeypatch.setattr(gui_actions.discovery, "resolve_name", lambda _n: "services.fake")
    monkeypatch.setattr(discovery.importlib, "import_module", lambda _n: fake_module)
    monkeypatch.setattr(
        inventory,
        "get",
        lambda name: Device(name=name, host="10.0.0.9", user="root", connection="ssh"),
    )

    payload = gui_actions.runbook_status("fake", "rpi4")

    assert payload == {"dotted_name": "services.fake", "guards": [], "installed": None}


def test_get_runbook_status_requires_dotted_name() -> None:
    with pytest.raises(ApiError) as excinfo:
        gui_actions.get_runbook_status(Request())
    assert excinfo.value.status == 400


# ── run lifecycle ────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_current_run() -> None:
    gui_actions._current_run = None


def test_start_run_unknown_runbook(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gui_actions.discovery, "resolve_name", lambda _n: None)
    with pytest.raises(ApiError) as excinfo:
        gui_actions.start_run("nope", None, None)
    assert excinfo.value.status == 400


def _fake_execute(_module: object, **kwargs: Any) -> int:
    kwargs["reporter"].info("done")
    return 0


def test_start_run_then_poll_until_done(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_module = ModuleType("fake_runbook")
    fake_module.__dict__["main"] = lambda **_: 0
    monkeypatch.setattr(gui_actions.discovery, "resolve_name", lambda _n: "services.fake")
    monkeypatch.setattr(discovery.importlib, "import_module", lambda _n: fake_module)
    monkeypatch.setattr(gui_actions.runner, "set_reporter", lambda _r: None)
    monkeypatch.setattr(gui_actions.guard_executor, "execute", _fake_execute)

    run_id = gui_actions.start_run("fake", None, None)["run_id"]

    deadline = time.monotonic() + 2
    state = gui_actions.get_run(run_id)
    while state is not None and state.status == "running" and time.monotonic() < deadline:
        time.sleep(0.01)
        state = gui_actions.get_run(run_id)

    assert state is not None
    assert state.status == "succeeded"
    assert state.exit_code == 0
    assert "done" in state.lines


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
    monkeypatch.setattr(discovery.importlib, "import_module", lambda _n: fake_module)
    monkeypatch.setattr(gui_actions.runner, "set_reporter", lambda _r: None)
    monkeypatch.setattr(gui_actions.guard_executor, "execute", slow_execute)

    gui_actions.start_run("fake", None, None)
    assert started.wait(timeout=2)

    with pytest.raises(ApiError) as excinfo:
        gui_actions.start_run("fake", None, None)
    assert excinfo.value.status == 409

    finish.set()


def _known_host(name: str) -> Device:
    return Device(name=name, host="10.0.0.9", user="root", connection="ssh")


@pytest.mark.parametrize("target", [5, "", ["rpi4"]])
def test_post_run_refuses_a_target_that_is_not_a_host_name(
    monkeypatch: pytest.MonkeyPatch, target: object
) -> None:
    monkeypatch.setattr(inventory, "get", _known_host)
    monkeypatch.setattr(gui_actions, "start_run", _refuse_to_start)
    with pytest.raises(ApiError) as excinfo:
        gui_actions.post_run(Request(body={"dotted_name": "fake", "target": target}))
    assert (excinfo.value.status, excinfo.value.message) == (400, "target must be a host name")


def test_post_run_refuses_an_unknown_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(inventory, "get", lambda _name: None)
    monkeypatch.setattr(gui_actions, "start_run", _refuse_to_start)
    with pytest.raises(ApiError) as excinfo:
        gui_actions.post_run(Request(body={"dotted_name": "fake", "target": "ghost"}))
    assert (excinfo.value.status, excinfo.value.message) == (400, "unknown host 'ghost'")


@pytest.mark.parametrize("tags", ["a,b", ["a", 1], {"a": "b"}, 7])
def test_post_run_refuses_tags_that_are_not_a_list_of_strings(
    monkeypatch: pytest.MonkeyPatch, tags: object
) -> None:
    monkeypatch.setattr(inventory, "get", _known_host)
    monkeypatch.setattr(gui_actions, "start_run", _refuse_to_start)
    with pytest.raises(ApiError) as excinfo:
        gui_actions.post_run(Request(body={"dotted_name": "fake", "tags": tags}))
    assert (excinfo.value.status, excinfo.value.message) == (400, "tags must be a list of strings")


def test_post_run_passes_a_known_target_and_good_tags_to_start_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str | None, list[str] | None]] = []

    def record(dotted_name: str, target: str | None, tags: list[str] | None) -> dict[str, Any]:
        calls.append((dotted_name, target, tags))
        return {"run_id": "r1"}

    monkeypatch.setattr(inventory, "get", _known_host)
    monkeypatch.setattr(gui_actions, "start_run", record)

    body = {"dotted_name": "fake", "target": "rpi4", "tags": ["jellyfin"]}
    assert gui_actions.post_run(Request(body=body)) == {"run_id": "r1"}
    assert gui_actions.post_run(Request(body={"dotted_name": "fake"})) == {"run_id": "r1"}
    assert calls == [("fake", "rpi4", ["jellyfin"]), ("fake", None, None)]


def _refuse_to_start(*_args: object) -> dict[str, Any]:
    pytest.fail("start_run must not be reached with an invalid request")


def test_get_run_status_unknown_id() -> None:
    with pytest.raises(ApiError) as excinfo:
        gui_actions.get_run_status(Request(args={"run_id": "nope"}))
    assert excinfo.value.status == 404


# ── vault password / secrets ─────────────────────────────────────────────


def test_post_vault_password_requires_a_value() -> None:
    with pytest.raises(ApiError) as excinfo:
        gui_actions.post_vault_password(Request())
    assert excinfo.value.status == 400


def test_post_vault_password_sets_it(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    monkeypatch.setattr(vault_pass, "set_vault_password", calls.append)
    assert gui_actions.post_vault_password(Request(body={"value": "hunter2"})) == {"ok": True}
    assert calls == ["hunter2"]


def test_post_secret_requires_vault_password_first(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(vault_pass, "has_vault_password", lambda: False)
    with pytest.raises(ApiError) as excinfo:
        gui_actions.post_secret(Request(body={"vault_key": "tailscale_auth_key", "value": "x"}))
    assert excinfo.value.status == 400


def test_post_secret_sets_it_once_vault_is_unlocked(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(vault_pass, "has_vault_password", lambda: True)
    calls = []
    monkeypatch.setattr(secrets, "set_secret", lambda k, v: calls.append((k, v)))
    body = {"vault_key": "tailscale_auth_key", "value": "x"}
    assert gui_actions.post_secret(Request(body=body)) == {"ok": True}
    assert calls == [("tailscale_auth_key", "x")]


# ── devices ───────────────────────────────────────────────────────────────


def test_post_device_requires_name_and_host() -> None:
    with pytest.raises(ApiError) as excinfo:
        gui_actions.post_device(Request(body={"name": "rpi4"}))
    assert excinfo.value.status == 400


def test_post_device_adds_it(monkeypatch: pytest.MonkeyPatch) -> None:
    device = Device(name="rpi4", host="10.0.0.9", user="pi", connection="ssh")
    monkeypatch.setattr(inventory, "add", lambda *_a, **_kw: device)
    body = {"name": "rpi4", "host": "10.0.0.9", "user": "pi"}
    assert gui_actions.post_device(Request(body=body))["name"] == "rpi4"


def test_delete_device_unknown_is_404(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(inventory, "remove", lambda _n: False)
    with pytest.raises(ApiError) as excinfo:
        gui_actions.delete_device(Request(args={"name": "nope"}))
    assert excinfo.value.status == 404


def test_delete_device_removes_host_vars_too(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(inventory, "remove", lambda _n: True)
    calls = []
    monkeypatch.setattr(host_vars, "discard", lambda n: calls.append(n) or True)
    assert gui_actions.delete_device(Request(args={"name": "rpi4"})) == {"ok": True}
    assert calls == ["rpi4"]


def test_get_reachable_requires_a_host() -> None:
    with pytest.raises(ApiError) as excinfo:
        gui_actions.get_reachable(Request())
    assert excinfo.value.status == 400


def test_get_reachable_delegates_to_tcp_reachable(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = []

    def fake_tcp_reachable(host: str, port: int) -> bool:
        seen.append((host, port))
        return True

    monkeypatch.setattr(gui_actions.reachability, "tcp_reachable", fake_tcp_reachable)
    payload = gui_actions.get_reachable(Request(query={"host": "10.0.0.9", "port": "2222"}))
    assert payload == {"reachable": True}
    assert seen == [("10.0.0.9", 2222)]


def test_get_reachable_defaults_port_to_22(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = []

    def fake_tcp_reachable(host: str, port: int) -> bool:
        seen.append((host, port))
        return True

    monkeypatch.setattr(gui_actions.reachability, "tcp_reachable", fake_tcp_reachable)
    gui_actions.get_reachable(Request(query={"host": "10.0.0.9"}))
    assert seen == [("10.0.0.9", 22)]
