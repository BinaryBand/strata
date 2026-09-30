"""Thin bridges from the GUI's HTTP action routes onto existing strata functions.

`gui_server.py` owns the server and routing; every function here is the body
of one route, doing no more than the equivalent CLI path already does --
`post_device` is `inventory.add`, `post_secret` is `secrets.set_secret`,
`start_run` is `guard_executor.execute` in a thread. Kept separate from
`gui_server.py` to keep that module's job to serving and routing alone.

A route body takes a `Request` and returns the JSON payload for a 200. It
refuses a request by raising `ApiError`; `gui_server` turns that, and any
other failure, into the response.
"""

from __future__ import annotations

import dataclasses
import threading
import uuid
from typing import Any

from strata.adapters import guard_executor, guard_status, reachability
from strata.adapters.ansible import host_vars, inventory, runner, secrets, vault_pass
from strata.cli.gui_http import ApiError, Request, require
from strata.core import discovery, guard


def runbook_status(dotted_name: str, target: str | None) -> dict[str, Any]:
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
        raise ApiError(404, f"unknown runbook {dotted_name!r}")
    module = discovery.load(resolved)
    guards = [
        {"type": type(r).__name__, "status": guard_status.guard_status(r, target=target)}
        for r in guard.declared(module.main)
    ]
    installed = guard_status.check_result(module, target=target)
    return {"dotted_name": resolved, "guards": guards, "installed": installed}


@dataclasses.dataclass
class RunState:
    """The one in-flight (or just-finished) run the server remembers.

    Satisfies `ports.Reporter`, buffering reported lines in memory for an HTTP
    poller to read. A run's whole life -- one thread, one buffer -- lives as
    long as `_current_run` points at it; there is deliberately no persistence
    or multi-run history.
    """

    run_id: str
    exit_code: int | None = None
    lines: list[str] = dataclasses.field(default_factory=list)

    @property
    def status(self) -> str:
        """`running` until an exit code is recorded, then `succeeded` or `failed`."""
        if self.exit_code is None:
            return "running"
        return "succeeded" if self.exit_code == 0 else "failed"

    def info(self, message: str) -> None:
        """Append `message` to the buffer."""
        self.lines.append(message)


_run_lock = threading.Lock()
_current_run: RunState | None = None


def start_run(dotted_name: str, target: str | None, tags: list[str] | None) -> dict[str, Any]:
    """Start a runbook in a background thread, refusing a second concurrent run.

    Only one run is tracked at a time -- a documented limitation, not an
    oversight: this is a single-operator tool, and a run registry would be
    machinery this project doesn't need yet.
    """
    global _current_run  # noqa: PLW0603 -- the single in-flight run *is* the state being guarded
    with _run_lock:
        if _current_run is not None and _current_run.status == "running":
            raise ApiError(409, "a run is already in progress")
        resolved = discovery.resolve_name(dotted_name)
        if resolved is None:
            raise ApiError(400, f"unknown runbook {dotted_name!r}")
        module = discovery.load(resolved)
        state = RunState(run_id=uuid.uuid4().hex)
        _current_run = state

        def _run() -> None:
            runner.set_reporter(state)
            try:
                exit_code = guard_executor.execute(module, target=target, tags=tags, reporter=state)
            except Exception as exc:  # noqa: BLE001 -- a background thread has no caller to raise to; record the failure so the poller sees it instead of the run silently hanging
                state.info(f"error: {exc}")
                state.exit_code = 1
                return
            state.exit_code = exit_code

        threading.Thread(target=_run, daemon=True).start()
        return {"run_id": state.run_id}


def get_run(run_id: str) -> RunState | None:
    """Return the tracked run's state if `run_id` matches it, else None."""
    if _current_run is not None and _current_run.run_id == run_id:
        return _current_run
    return None


def get_runbook_status(request: Request) -> dict[str, Any]:
    """Handle `GET /api/runbook-status`."""
    (dotted_name,) = require(request.query, "dotted_name")
    return runbook_status(dotted_name, request.query.get("target"))


def get_vault_status(_request: Request) -> dict[str, Any]:
    """Handle `GET /api/vault-status`."""
    return {"has_vault_password": vault_pass.has_vault_password()}


def get_reachable(request: Request) -> dict[str, Any]:
    """Handle `GET /api/reachable?host=&port=`.

    Takes a bare host/port rather than a registered device name so the
    Machines screen can test reachability *before* adding one -- the point
    of testing first.
    """
    (host,) = require(request.query, "host")
    port_str = request.query.get("port", "22")
    port = int(port_str) if port_str.isdigit() else 22
    return {"reachable": reachability.tcp_reachable(host, port)}


def get_run_status(request: Request) -> dict[str, Any]:
    """Handle `GET /api/run/<run_id>`."""
    state = get_run(request.args["run_id"])
    if state is None:
        raise ApiError(404, "unknown run id")
    return {"status": state.status, "exit_code": state.exit_code, "lines": list(state.lines)}


def post_vault_password(request: Request) -> dict[str, Any]:
    """Handle `POST /api/vault-password`."""
    (value,) = require(request.body, "value")
    vault_pass.set_vault_password(value)
    return {"ok": True}


def post_secret(request: Request) -> dict[str, Any]:
    """Handle `POST /api/secrets`."""
    vault_key, value = require(request.body, "vault_key", "value")
    if not vault_pass.has_vault_password():
        raise ApiError(400, "set the vault password first")
    secrets.set_secret(vault_key, value)
    return {"ok": True}


def post_device(request: Request) -> dict[str, Any]:
    """Handle `POST /api/devices`."""
    name, host = require(request.body, "name", "host")
    device = inventory.add(
        name,
        host,
        user=request.body.get("user", "root"),
        connection=request.body.get("connection", "ssh"),
        port=request.body.get("port"),
    )
    return device.model_dump()


def post_run(request: Request) -> dict[str, Any]:
    """Handle `POST /api/run`.

    `target` and `tags` come straight off the wire, so they are checked here the
    way the CLI checks them (`_helpers.require_host` refuses an unknown host),
    rather than reaching the executor as whatever JSON happened to hold.
    """
    (dotted_name,) = require(request.body, "dotted_name")
    target = request.body.get("target")
    if target is not None:
        if not isinstance(target, str) or not target:
            raise ApiError(400, "target must be a host name")
        if inventory.get(target) is None:
            raise ApiError(400, f"unknown host {target!r}")
    tags = request.body.get("tags")
    if tags is not None and not (isinstance(tags, list) and all(isinstance(t, str) for t in tags)):
        raise ApiError(400, "tags must be a list of strings")
    return start_run(dotted_name, target, tags)


def delete_device(request: Request) -> dict[str, Any]:
    """Handle `DELETE /api/devices/<name>`."""
    name = request.args["name"]
    if not inventory.remove(name):
        raise ApiError(404, "unknown device")
    host_vars.discard(name)
    return {"ok": True}
