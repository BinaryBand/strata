"""Thin bridges from the GUI's HTTP action routes onto existing strata functions.

`gui_server.py` owns the server and routing; every function here is the body
of one route, doing no more than the equivalent CLI path already does --
`post_device` is `inventory.add`, `post_secret` is `secrets.set_secret`,
`start_run` is `guard_executor.execute` in a thread. Kept separate from
`gui_server.py` to keep that module's job to serving and routing alone.
"""

from __future__ import annotations

import dataclasses
import importlib
import threading
import uuid
from collections.abc import Callable
from typing import Any

from strata.adapters import guard_executor, guard_status, reachability
from strata.adapters.ansible import host_vars, inventory, runner, secrets, vault_pass
from strata.cli.gui_http import JsonHandler
from strata.cli.gui_http import send_json as _send_json
from strata.core import discovery, guard


def runbook_status(dotted_name: str, target: str | None) -> tuple[int, dict[str, Any]]:
    """Read-only readiness for one runbook: per-guard status plus check(), if any.

    Never prompts or mutates. Every guard's status comes from
    `guard_status.guard_status`, and `installed` from
    `guard_status.check_result` -- None when the runbook declares no check(),
    and also when `target` is not the controller, since every check() reads
    the local filesystem and would otherwise answer about this machine
    instead. The key is always present; only its value goes null.
    """
    resolved = discovery.resolve_name(dotted_name)
    if resolved is None:
        return 404, {"error": f"unknown runbook {dotted_name!r}"}
    module = importlib.import_module(f"strata.core.runbooks.{resolved}")
    guards = [
        {"type": type(r).__name__, "status": guard_status.guard_status(r, target=target)}
        for r in guard.declared(module.main)
    ]
    installed = guard_status.check_result(module, target=target)
    return 200, {"dotted_name": resolved, "guards": guards, "installed": installed}


class QueueReporter:
    """Buffers reported lines in memory for an HTTP poller to read.

    Satisfies `ports.Reporter`. A run's whole life -- one thread, one buffer --
    lives as long as `_current_run` points at it; there is deliberately no
    persistence or multi-run history.
    """

    def __init__(self) -> None:
        """Start with an empty buffer."""
        self.lines: list[str] = []

    def info(self, message: str) -> None:
        """Append `message` to the buffer."""
        self.lines.append(message)


@dataclasses.dataclass
class RunState:
    """The one in-flight (or just-finished) run the server remembers."""

    run_id: str
    reporter: QueueReporter
    status: str = "running"
    exit_code: int | None = None


_run_lock = threading.Lock()
_current_run: RunState | None = None


def start_run(
    dotted_name: str, target: str | None, tags: list[str] | None
) -> tuple[int, dict[str, Any]]:
    """Start a runbook in a background thread, refusing a second concurrent run.

    Only one run is tracked at a time -- a documented limitation, not an
    oversight: this is a single-operator tool, and a run registry would be
    machinery this project doesn't need yet.
    """
    global _current_run  # noqa: PLW0603 -- the single in-flight run *is* the state being guarded
    with _run_lock:
        if _current_run is not None and _current_run.status == "running":
            return 409, {"error": "a run is already in progress"}
        resolved = discovery.resolve_name(dotted_name)
        if resolved is None:
            return 400, {"error": f"unknown runbook {dotted_name!r}"}
        module = importlib.import_module(f"strata.core.runbooks.{resolved}")
        reporter = QueueReporter()
        state = RunState(run_id=uuid.uuid4().hex, reporter=reporter)
        _current_run = state

        def _run() -> None:
            runner.set_reporter(reporter)
            try:
                exit_code = guard_executor.execute(
                    module, target=target, tags=tags, reporter=reporter
                )
            except Exception as exc:  # noqa: BLE001 -- a background thread has no caller to raise to; record the failure so the poller sees it instead of the run silently hanging
                reporter.info(f"error: {exc}")
                state.status = "failed"
                state.exit_code = 1
                return
            state.exit_code = exit_code
            state.status = "succeeded" if exit_code == 0 else "failed"

        threading.Thread(target=_run, daemon=True).start()
        return 200, {"run_id": state.run_id}


def get_run(run_id: str) -> RunState | None:
    """Return the tracked run's state if `run_id` matches it, else None."""
    if _current_run is not None and _current_run.run_id == run_id:
        return _current_run
    return None


def get_runbook_status(handler: JsonHandler, query: dict[str, list[str]]) -> None:
    """Handle `GET /api/runbook-status`."""
    dotted_name = (query.get("dotted_name") or [None])[0]
    if dotted_name is None:
        _send_json(handler, 400, {"error": "dotted_name is required"})
        return
    target = (query.get("target") or [None])[0]
    status, payload = runbook_status(dotted_name, target)
    _send_json(handler, status, payload)


def get_reachable(handler: JsonHandler, query: dict[str, list[str]]) -> None:
    """Handle `GET /api/reachable?host=&port=`.

    Takes a bare host/port rather than a registered device name so the
    Machines screen can test reachability *before* adding one -- the point
    of testing first.
    """
    host = (query.get("host") or [None])[0]
    if not host:
        _send_json(handler, 400, {"error": "host is required"})
        return
    port_str = (query.get("port") or ["22"])[0]
    port = int(port_str) if port_str.isdigit() else 22
    reachable = reachability.tcp_reachable(host, port)
    _send_json(handler, 200, {"reachable": reachable})


def get_run_status(handler: JsonHandler, run_id: str) -> None:
    """Handle `GET /api/run/<run_id>`."""
    state = get_run(run_id)
    if state is None:
        _send_json(handler, 404, {"error": "unknown run id"})
        return
    _send_json(
        handler,
        200,
        {"status": state.status, "exit_code": state.exit_code, "lines": list(state.reporter.lines)},
    )


def post_vault_password(handler: JsonHandler, body: dict[str, Any]) -> None:
    """Handle `POST /api/vault-password`."""
    value = body.get("value")
    if not value:
        _send_json(handler, 400, {"error": "value is required"})
        return
    vault_pass.set_vault_password(value)
    _send_json(handler, 200, {"ok": True})


def post_secret(handler: JsonHandler, body: dict[str, Any]) -> None:
    """Handle `POST /api/secrets`."""
    vault_key, value = body.get("vault_key"), body.get("value")
    if not vault_key or not value:
        _send_json(handler, 400, {"error": "vault_key and value are required"})
        return
    if not vault_pass.has_vault_password():
        _send_json(handler, 400, {"error": "set the vault password first"})
        return
    secrets.set_secret(vault_key, value)
    _send_json(handler, 200, {"ok": True})


def post_device(handler: JsonHandler, body: dict[str, Any]) -> None:
    """Handle `POST /api/devices`."""
    name, host = body.get("name"), body.get("host")
    if not name or not host:
        _send_json(handler, 400, {"error": "name and host are required"})
        return
    device = inventory.add(
        name,
        host,
        user=body.get("user", "root"),
        connection=body.get("connection", "ssh"),
        port=body.get("port"),
    )
    _send_json(
        handler,
        200,
        {
            "name": device.name,
            "host": device.host,
            "user": device.user,
            "connection": device.connection,
            "port": device.port,
        },
    )


def post_run(handler: JsonHandler, body: dict[str, Any]) -> None:
    """Handle `POST /api/run`."""
    dotted_name = body.get("dotted_name")
    if not dotted_name:
        _send_json(handler, 400, {"error": "dotted_name is required"})
        return
    status, payload = start_run(dotted_name, body.get("target"), body.get("tags"))
    _send_json(handler, status, payload)


def delete_device(handler: JsonHandler, name: str) -> None:
    """Handle `DELETE /api/devices/<name>`."""
    if not inventory.remove(name):
        _send_json(handler, 404, {"error": "unknown device"})
        return
    host_vars.discard(name)
    _send_json(handler, 200, {"ok": True})


POST_ROUTES: dict[str, Callable[[JsonHandler, dict[str, Any]], None]] = {
    "/api/vault-password": post_vault_password,
    "/api/secrets": post_secret,
    "/api/devices": post_device,
    "/api/run": post_run,
}
