"""Adapter fakes and the synthetic-runbook runner for guard_resolution.feature.

Split from tests/features/test_guard_resolution.py so that file holds only the step
vocabulary. Nothing here is a step definition: this is the seam layer -- the
fakes standing in for the adapters `guard_executor` imports directly, plus the
machinery for building a runbook that declares an arbitrary set of guards and
running the real executor over it.

Every fake records into the shared `ctx` bag rather than asserting, so the
step definitions decide what a given scenario cares about. `ctx["events"]` is
the spine: prompts, playbooks, upstream runs and `main()` all append to it in
the order they happen, which is what lets the ordering and short-circuit
scenarios assert on sequence instead of on each fake in isolation.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable, Sequence
from types import ModuleType
from typing import Any

import pytest

from strata.adapters import guard_executor
from strata.adapters.ansible import host_scope, inventory, rclone, runner
from strata.cli import dispatch
from strata.core import discovery
from tests._fakes import FakePrompter, fake_vault

Runbook = Callable[..., int]

ENSURE_PATH = "playbooks/ensure_path.yml"
ENABLE_RCLONE = "playbooks/enable_rclone.yml"


def isolate_guards(monkeypatch: pytest.MonkeyPatch, ctx: dict[str, Any]) -> None:
    """Fake every adapter the executor reaches, recording what it asked for.

    conftest.py wraps this as the `_isolate_guards` fixture; a binding opts in
    with `pytest.mark.usefixtures`.
    """
    ctx.update(
        events=[],
        vault={},
        playbooks=[],
        playbook_rc=lambda _playbook: 0,
        decorators=[],
        target=None,
        rclone_known={"pcloud", "backup"},
        rclone_listed={"pcloud", "backup"},
        rclone_writable=set(),
        rclone_added=[],
        rclone_created=[],
        mounted=set(),
        users={"diot"},
        storage_writable=False,
    )

    _fake_secrets(monkeypatch, ctx)
    _fake_prompts(monkeypatch, ctx)
    _fake_runner(monkeypatch, ctx)
    _fake_rclone(monkeypatch, ctx)
    _fake_system(monkeypatch, ctx)


def _fake_secrets(monkeypatch: pytest.MonkeyPatch, ctx: dict[str, Any]) -> None:
    """An in-memory vault standing in for the ansible-vault secrets file."""
    fake_vault(monkeypatch, ctx["vault"])


class _HarnessPrompter(FakePrompter):
    """A FakePrompter that also feeds the event spine and answers the sudo prompt.

    The sudo password is asked for through the prerequisite table rather than a
    declared `@guard.secret`, so scenarios never queue an answer for it; it
    answers itself, and leaves whatever a scenario did queue for its own prompt.
    """

    def __init__(self, ctx: dict[str, Any]) -> None:
        super().__init__()
        self._ctx = ctx

    def ask(self, message: str, *, default: str | None = None, hidden: bool = False) -> str:
        if message.startswith("sudo password"):
            self._ctx["events"].append("prompt:sudo")
            self.answers.insert(0, "sudo-pw")
        return super().ask(message, default=default, hidden=hidden)


def _fake_prompts(monkeypatch: pytest.MonkeyPatch, ctx: dict[str, Any]) -> None:
    """One recording prompter, handed to the executor and to `run_runbook`.

    `run_runbook` builds its own terminal prompter, so the runs that go through
    it (`backup_restore`, `server_app_journeys`) are pointed at this one too.
    A scenario queues an answer with `ctx["prompter"].answers`; `ctx["prompts"]`
    is the list of what was asked, as `{"message", "default", "hidden"}`.
    """
    prompter = _HarnessPrompter(ctx)
    ctx["prompter"] = prompter
    ctx["prompts"] = prompter.asked
    monkeypatch.setattr(dispatch, "build_prompter", lambda: prompter)


def _fake_runner(monkeypatch: pytest.MonkeyPatch, ctx: dict[str, Any]) -> None:
    """Record every playbook the executor would have run."""

    def fake_run_playbook(
        playbook: str,
        extravars: Any = None,
        target: str | None = None,
        inventory: Any = None,  # noqa: ARG001
    ) -> int:
        ctx["playbooks"].append({"playbook": playbook, "extravars": extravars, "target": target})
        ctx["events"].append(f"playbook:{playbook}")
        return ctx["playbook_rc"](playbook)

    monkeypatch.setattr(runner, "run_playbook", fake_run_playbook)


def _fake_rclone(monkeypatch: pytest.MonkeyPatch, ctx: dict[str, Any]) -> None:
    """Two registrations, tracked separately.

    `_ensure_mount` asks rclone whether it knows a remote at all (an unknown
    one is offered for creation) and separately asks this tool whether it has
    the remote listed (an unlisted one is added, forcing a remount). Collapsing
    them would make the create-then-mount scenario pass for the wrong reason.
    """
    # No scenario sets a per-host override; reading one would read the
    # operator's real host_vars/<target>.yml.
    monkeypatch.setattr(host_scope.HostSecrets, "override", lambda _self, _name: None)
    monkeypatch.setattr(rclone, "has_remote", lambda name: name in ctx["rclone_known"])
    monkeypatch.setattr(rclone, "list_remotes", lambda: sorted(ctx["rclone_listed"]))
    monkeypatch.setattr(rclone, "is_writable", lambda name: name in ctx["rclone_writable"])
    monkeypatch.setattr(
        rclone, "is_remote_path", lambda value: ":" in value and not value.startswith("/")
    )
    monkeypatch.setattr(rclone, "resolve", lambda remote_path: _resolve(ctx, remote_path))
    # Stubbed outright, not left to read the stubbed resolve: the real one also
    # asks the kernel whether the mount root is mounted, which answers for
    # whatever this machine has mounted rather than for the scenario.
    monkeypatch.setattr(rclone, "is_mounted", lambda remote_path: remote_path in ctx["mounted"])

    def fake_add_to_config(name: str, *, writable: bool = False) -> None:
        ctx["rclone_added"].append({"name": name, "writable": writable})
        ctx["rclone_listed"].add(name)
        if writable:
            ctx["rclone_writable"].add(name)

    def fake_prompt_create_remote(name: str, _prompter: Any) -> None:
        ctx["rclone_created"].append(name)
        ctx["rclone_known"].add(name)

    monkeypatch.setattr(rclone, "add_to_config", fake_add_to_config)
    monkeypatch.setattr(rclone, "prompt_create_remote", fake_prompt_create_remote)


def _fake_system(monkeypatch: pytest.MonkeyPatch, ctx: dict[str, Any]) -> None:
    """The passwd lookup and the inventory, which together decide the fast paths."""

    def fake_getpwnam(name: str) -> object:
        if name not in ctx["users"]:
            raise KeyError(name)
        return object()

    monkeypatch.setattr(guard_executor.pwd, "getpwnam", fake_getpwnam)

    # An unknown host is not the controller, so a scenario that never registers
    # a device gets target=None and keeps the local fast paths.
    monkeypatch.setattr(inventory, "get", lambda name: ctx.get("device_for", {}).get(name))


def _resolve(ctx: dict[str, Any], remote_path: str) -> str:
    """Stand in for rclone.resolve: a mounted remote maps to a path that exists."""
    if remote_path in ctx["mounted"]:
        return str(ctx["mount_root"])
    return "/nonexistent/mountpoint"


def stub_module(main: Runbook) -> ModuleType:
    """Wrap `main` in a real module, which is what the executor is handed."""
    module = ModuleType("stub_runbook")
    # __dict__ rather than setattr: a bare ModuleType has no declared `main`
    # attribute, so assigning one directly is a type error even though it is
    # exactly what importing a real runbook produces.
    module.__dict__["main"] = main
    return module


def run_declared(ctx: dict[str, Any]) -> None:
    """Apply the accumulated decorators to a stub main(), then execute it.

    Decorators are applied in reverse so that ctx["decorators"] reads
    outermost-first, the order they appear reading down a real runbook -- which
    is also the order the executor satisfies them in.
    """

    def main(target: str | None = None) -> int:  # noqa: ARG001
        ctx["events"].append("main")
        return 0

    decorated: Runbook = main
    for decorator in reversed(ctx["decorators"]):
        decorated = decorator(decorated)

    try:
        ctx["exit_code"] = guard_executor.execute(
            stub_module(decorated),
            target=ctx["target"],
            reporter=_Recorder(ctx),
            prompter=ctx["prompter"],
        )
    except Exception as exc:  # noqa: BLE001 - the scenarios assert on what was raised
        ctx["error"] = exc


def install_upstream(
    ctx: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    *,
    check: Callable[[], bool] | None,
    decorators: Sequence[Callable[[Any], Any]] = (),
) -> None:
    """Make the upstream runbook importable as a stub with the given check().

    `_run_upstream` imports its dependency by dotted name, so an upstream that
    behaves a particular way has to be substituted at the import, not injected.

    `decorators` declares the upstream's own guards, which is what the real
    install_podman does with @guard.user("diot") -- needed to cover that a
    satisfied check() skips the upstream's play but not its guards.
    """

    def upstream_main(target: str | None = None) -> int:  # noqa: ARG001
        ctx["events"].append("upstream:install_podman")
        return 0

    decorated = upstream_main
    for decorator in reversed(decorators):
        decorated = decorator(decorated)
    stub = stub_module(decorated)
    if check is not None:
        stub.__dict__["check"] = check

    real_import = importlib.import_module
    dotted = "strata.core.runbooks.infrastructure.install_podman"

    def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == dotted:
            return stub
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(discovery.importlib, "import_module", fake_import)


class _Recorder:
    """Reporter that keeps what the executor told the operator."""

    def __init__(self, ctx: dict[str, Any]) -> None:
        self._ctx = ctx
        ctx["messages"] = []

    def info(self, message: str) -> None:
        self._ctx["messages"].append(message)
