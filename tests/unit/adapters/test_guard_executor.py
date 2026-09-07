"""Unit tests for the executor that satisfies declared requirements.

Declaring with the real guard decorators and running the real executor keeps
these covering the path production takes, rather than requirement objects in
isolation.

rclone/runner/secrets are monkeypatched so these never shell out to rclone,
ansible-runner, or ansible-vault. target is left as None throughout, which
_is_controller() treats as the controller, so local fast paths apply.
"""

from __future__ import annotations

import grp
import os
import pwd
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest

from strata.adapters import guard_executor
from strata.adapters.ansible import inventory, rclone, runner, secrets
from strata.core import guard, ports
from strata.core import requirements as req
from strata.core.models import Device

_ME = pwd.getpwuid(os.getuid()).pw_name
_MY_GROUP = grp.getgrgid(os.getgid()).gr_name


def test_path_satisfied_missing_path_is_unsatisfied(tmp_path: Path) -> None:
    missing = tmp_path / "nope"
    assert not guard_executor._path_satisfied(
        req.LocalPath(path=str(missing), owner=None, group=None, mode=None, state="directory")
    )


def test_path_satisfied_wrong_type_is_unsatisfied(tmp_path: Path) -> None:
    file_path = tmp_path / "a_file"
    file_path.write_text("x")
    assert not guard_executor._path_satisfied(
        req.LocalPath(path=str(file_path), owner=None, group=None, mode=None, state="directory")
    )


def test_path_satisfied_directory_with_no_constraints() -> None:
    assert guard_executor._path_satisfied(
        req.LocalPath(path="/tmp", owner=None, group=None, mode=None, state="directory")
    )


def test_path_satisfied_owner_and_group_match(tmp_path: Path) -> None:
    assert guard_executor._path_satisfied(
        req.LocalPath(path=str(tmp_path), owner=_ME, group=_MY_GROUP, mode=None, state="directory")
    )


def test_path_satisfied_owner_mismatch(tmp_path: Path) -> None:
    assert not guard_executor._path_satisfied(
        req.LocalPath(path=str(tmp_path), owner="root", group=None, mode=None, state="directory")
    )


def test_path_satisfied_group_mismatch(tmp_path: Path) -> None:
    assert not guard_executor._path_satisfied(
        req.LocalPath(path=str(tmp_path), owner=None, group="root", mode=None, state="directory")
    )


def test_path_satisfied_mode_match_and_mismatch(tmp_path: Path) -> None:
    tmp_path.chmod(0o755)
    assert guard_executor._path_satisfied(
        req.LocalPath(path=str(tmp_path), owner=None, group=None, mode="0755", state="directory")
    )
    assert not guard_executor._path_satisfied(
        req.LocalPath(path=str(tmp_path), owner=None, group=None, mode="0700", state="directory")
    )


_Runbook = Callable[..., int]
_Guard = Callable[[_Runbook], _Runbook]


def _stub_module(main: _Runbook) -> ModuleType:
    """Wrap `main` in a real module, which is what the executor is handed."""
    module = ModuleType("stub_runbook")
    # __dict__ rather than setattr: a bare ModuleType has no declared `main`
    # attribute, so assigning one directly is a type error even though it is
    # exactly what importing a real runbook produces.
    module.__dict__["main"] = main
    return module


def _execute(*decorators: _Guard, target: str | None = None) -> int:
    """Declare requirements on a stub runbook, then run it through the executor.

    Mirrors production exactly: cli hands guard_executor.execute() a module, it
    satisfies whatever main() declared, then calls main(). Decorators are passed
    outermost-first, the order they would appear reading down a runbook.
    """

    def main(target: str | None = None) -> int:  # noqa: ARG001
        return 0

    decorated: _Runbook = main
    for decorator in reversed(decorators):
        decorated = decorator(decorated)
    return guard_executor.execute(_stub_module(decorated), target=target)


@pytest.fixture
def _no_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(secrets, "has_secret", lambda _key: True)


@pytest.mark.usefixtures("_no_prompt")
def test_storage_local_path_already_satisfied_skips_playbook(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(secrets, "get_secret", lambda _key: str(tmp_path))
    monkeypatch.setattr(rclone, "is_remote_path", lambda _value: False)

    def fail_if_called(*_args: object, **_kwargs: object) -> int:
        msg = "run_playbook should not run when the path is satisfied"
        raise AssertionError(msg)

    monkeypatch.setattr(runner, "run_playbook", fail_if_called)

    assert _execute(guard.storage("some_local_key")) == 0


@pytest.mark.usefixtures("_no_prompt")
def test_storage_local_path_missing_runs_playbook(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    missing = tmp_path / "not-yet-created"
    monkeypatch.setattr(secrets, "get_secret", lambda _key: str(missing))
    monkeypatch.setattr(rclone, "is_remote_path", lambda _value: False)

    calls = []

    def fake_run_playbook(*args: object, **kwargs: object) -> int:
        calls.append((args, kwargs))
        return 0

    monkeypatch.setattr(runner, "run_playbook", fake_run_playbook)

    assert _execute(guard.storage("some_local_key")) == 0
    assert len(calls) == 1
    assert calls[0][0][0] == "playbooks/ensure_path.yml"


@pytest.mark.usefixtures("_no_prompt")
def test_storage_remote_path_already_mounted_skips_playbook(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(secrets, "get_secret", lambda _key: "pcloud:backups")
    monkeypatch.setattr(rclone, "is_remote_path", lambda _value: True)
    monkeypatch.setattr(rclone, "has_remote", lambda _name: True)
    monkeypatch.setattr(rclone, "list_remotes", lambda: ["pcloud"])
    monkeypatch.setattr(rclone, "is_writable", lambda _name: True)
    monkeypatch.setattr(rclone, "resolve", lambda _value: str(tmp_path))

    def fail_if_called(*_args: object, **_kwargs: object) -> int:
        msg = "run_playbook should not run when the mount is live"
        raise AssertionError(msg)

    monkeypatch.setattr(runner, "run_playbook", fail_if_called)

    assert _execute(guard.storage("some_remote_key", require_writable=True)) == 0


@pytest.mark.usefixtures("_no_prompt")
def test_storage_remote_path_unregistered_creates_and_registers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A remote unknown to rclone is created interactively, then auto-registered
    (writable, since require_writable=True) instead of raising -- and a remount
    is forced even though the mountpoint doesn't exist yet either way."""
    monkeypatch.setattr(secrets, "get_secret", lambda _key: "ghost:backups")
    monkeypatch.setattr(rclone, "is_remote_path", lambda _value: True)
    monkeypatch.setattr(rclone, "has_remote", lambda _name: False)

    created: list[str] = []
    monkeypatch.setattr(rclone, "prompt_create_remote", created.append)
    monkeypatch.setattr(rclone, "list_remotes", list)
    registered: list[tuple[str, bool]] = []
    monkeypatch.setattr(
        rclone,
        "add_to_config",
        lambda name, *, writable=False: registered.append((name, writable)),
    )
    monkeypatch.setattr(rclone, "resolve", lambda _value: str(tmp_path / "mnt"))

    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
    monkeypatch.setattr(runner, "run_playbook", lambda *a, **k: calls.append((a, k)) or 0)

    assert _execute(guard.storage("some_remote_key", require_writable=True)) == 0
    assert created == ["ghost"]
    assert registered == [("ghost", True)]
    assert len(calls) == 1
    assert calls[0][0][0] == "playbooks/enable_rclone.yml"


@pytest.mark.usefixtures("_no_prompt")
def test_storage_remote_path_upgrades_read_only_to_writable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A remote already registered read-only is auto-upgraded to writable, and
    a remount is forced even though the (stale, read-only) mount already exists."""
    monkeypatch.setattr(secrets, "get_secret", lambda _key: "pcloud:backups")
    monkeypatch.setattr(rclone, "is_remote_path", lambda _value: True)
    monkeypatch.setattr(rclone, "has_remote", lambda _name: True)
    monkeypatch.setattr(rclone, "list_remotes", lambda: ["pcloud"])
    monkeypatch.setattr(rclone, "is_writable", lambda _name: False)
    registered: list[tuple[str, bool]] = []
    monkeypatch.setattr(
        rclone,
        "add_to_config",
        lambda name, *, writable=False: registered.append((name, writable)),
    )
    monkeypatch.setattr(rclone, "resolve", lambda _value: str(tmp_path))

    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
    monkeypatch.setattr(runner, "run_playbook", lambda *a, **k: calls.append((a, k)) or 0)

    assert _execute(guard.storage("some_remote_key", require_writable=True)) == 0
    assert registered == [("pcloud", True)]
    assert len(calls) == 1


def test_requirements_are_satisfied_in_decorator_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Guards must be satisfied top-down, and main() only after all of them.

    Under the old wrapper design the outermost decorator ran its guard first,
    then delegated inward. The declarative list has to reproduce that order,
    which is why guard._declare prepends: decorators apply bottom-up, so the
    outermost is recorded last but must run first. Getting this backwards still
    exits 0 while provisioning in the wrong order -- e.g. mounting a remote
    before the user owning the mountpoint exists.
    """
    calls: list[str] = []

    monkeypatch.setattr(
        guard_executor, "_PREREQUISITES", {"_test_marker": lambda: calls.append("prereq")}
    )
    monkeypatch.setattr(guard_executor, "_path_satisfied", lambda *_a, **_kw: False)
    monkeypatch.setattr(pwd, "getpwnam", lambda name: (_ for _ in ()).throw(KeyError(name)))

    def fake_run_playbook(playbook: str, **_kwargs: object) -> int:
        calls.append(f"playbook:{Path(playbook).name}")
        return 0

    monkeypatch.setattr(runner, "run_playbook", fake_run_playbook)

    exit_code = _execute(
        guard.prerequisite("_test_marker"),
        guard.user("someuser", "playbooks/create_user.yml"),
        guard.path("/srv/thing"),
    )

    assert exit_code == 0
    assert calls == ["prereq", "playbook:create_user.yml", "playbook:ensure_path.yml"]


def test_failing_requirement_short_circuits_before_main(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A guard that fails must return its exit code without main() running."""
    monkeypatch.setattr(guard_executor, "_path_satisfied", lambda *_a, **_kw: False)
    monkeypatch.setattr(runner, "run_playbook", lambda *_a, **_kw: 3)

    ran: list[str] = []

    def main(target: str | None = None) -> int:  # noqa: ARG001
        ran.append("main")
        return 0

    decorated = guard.path("/srv/thing")(main)
    exit_code = guard_executor.execute(_stub_module(decorated), target=None)

    assert exit_code == 3
    assert ran == []


# ── controller_only ────────────────────────────────────────────────────────


def _remote_device(name: str) -> Device:
    return Device(name=name, host="10.0.0.9", user="root", connection="ssh")


def test_controller_only_allows_the_controller(monkeypatch: pytest.MonkeyPatch) -> None:
    """target=None is the controller, so the runbook runs normally."""
    monkeypatch.setattr(runner, "run_playbook", lambda *_a, **_kw: 0)

    assert _execute(guard.controller_only("workstation tooling")) == 0


def test_controller_only_refuses_a_remote_target(monkeypatch: pytest.MonkeyPatch) -> None:
    """A hosts: local playbook matched nothing under --limit and exited 0.

    The runner now fails that, but only after ansible has been started; the
    guard refuses before any playbook runs, and can say why.
    """
    monkeypatch.setattr(inventory, "get", _remote_device)
    ran: list[str] = []
    monkeypatch.setattr(runner, "run_playbook", lambda *_a, **_kw: ran.append("playbook") or 0)

    exit_code = _execute(guard.controller_only("workstation tooling"), target="nas")

    assert exit_code == 1
    assert ran == []


def test_controller_only_reports_the_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(inventory, "get", _remote_device)
    messages: list[str] = []

    class Reporter:
        def info(self, message: str) -> None:
            messages.append(message)

    def main(target: str | None = None) -> int:  # noqa: ARG001
        return 0

    decorated = guard.controller_only("Flatpak here exists to install desktop applications")(main)
    guard_executor.execute(_stub_module(decorated), target="nas", reporter=Reporter())

    assert any("Flatpak here exists to install desktop applications" in m for m in messages)
    assert any("nas" in m for m in messages)


# ── unknown targets and empty secrets ──────────────────────────────────────


def test_an_unknown_target_is_not_treated_as_the_controller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A typo'd --target used to get every local fast path applied to it."""
    monkeypatch.setattr(inventory, "get", lambda _name: None)

    assert guard_executor._is_controller("typoed-host") is False


def test_no_target_at_all_is_still_the_controller() -> None:
    assert guard_executor._is_controller(None) is True


def test_a_blank_answer_is_re_prompted_rather_than_stored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty secret used to be written and never asked about again.

    has_secret() only checks that the key exists, so one stray Enter on e.g.
    tailscale_auth_key poisoned it permanently and every later run handed the
    playbook an empty key.
    """
    monkeypatch.setattr(secrets, "has_secret", lambda _key: False)
    stored: list[tuple[str, str]] = []
    monkeypatch.setattr(secrets, "set_secret", lambda k, v: stored.append((k, v)))

    answers = iter(["", "  ", "real-token"])
    monkeypatch.setattr(guard_executor.click, "prompt", lambda *_a, **_kw: next(answers))
    monkeypatch.setattr(guard_executor.click, "echo", lambda *_a, **_kw: None)

    guard_executor._ensure_secret(
        "tailscale_auth_key", "key", kind="password", default=None, generate=False
    )

    assert stored == [("tailscale_auth_key", "real-token")]


def test_a_blank_answer_still_generates_when_generate_is_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(secrets, "has_secret", lambda _key: False)
    stored: list[tuple[str, str]] = []
    monkeypatch.setattr(secrets, "set_secret", lambda k, v: stored.append((k, v)))
    monkeypatch.setattr(guard_executor.click, "prompt", lambda *_a, **_kw: "")

    guard_executor._ensure_secret(
        "restic_password", "pw", kind="password", default=None, generate=True
    )

    assert len(stored) == 1
    assert stored[0][1]


def test_check_receives_the_adapters_it_declares() -> None:
    """check() used to be called bare, so it could never read the vault.

    install_restic.check needs a SecretReader to find the repository path;
    without an injection point it could only return False, and backup re-ran
    the whole restic container every time.
    """
    seen: list[object] = []

    def check(secrets: object) -> bool:
        seen.append(secrets)
        return True

    assert guard_executor._checks_satisfied(check, ports.NullReporter()) is True
    assert seen == [secrets]


def test_a_check_that_cannot_reach_the_vault_is_not_fatal() -> None:
    """secrets.get_secret raises RuntimeError on a locked keychain."""

    def check() -> bool:
        msg = "ansible-vault view failed"
        raise RuntimeError(msg)

    assert guard_executor._checks_satisfied(check, ports.NullReporter()) is False
