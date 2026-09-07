"""pytest-bdd binding for features/server_app_journeys.feature (Stage 4).

The journey question is *which* playbooks a leaf runbook pulls in, in what
order, and which of them a satisfied fast path removes. So the whole guard
chain is the real one: real runbook modules, real `guard_executor.execute`,
real `declared()` ordering and upstream recursion. Only the adapters are faked,
via `_guard_harness` -- the runner records playbooks instead of running them.

Two extra seams beyond the shared harness, both because these runbooks name
absolute host paths this suite must not touch or need root to create:

  * `shutil.which` decides install_podman's check(); a scenario says whether
    podman is present rather than depending on the machine running the tests.
  * `_path_satisfied` is answered from a per-scenario set, so "already
    provisioned" does not mean chown-ing /srv/jellyfin. Whether a stat result
    actually satisfies a LocalPath is guard_resolution.feature's job, and is
    covered there against real directories.

Everything else -- ordering, `_is_controller` gating, upstream check()
short-circuits -- runs unfaked.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from features._guard_harness import _isolate_guards  # noqa: F401
from strata.adapters import guard_executor, state
from strata.cli import dispatch
from strata.core.models import Device

scenarios("server_app_journeys.feature")


@pytest.fixture(autouse=True)
def _isolate_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect the XDG state file into tmp.

    cli.dispatch.run_runbook persists `last_target` on every run with an
    explicit --target, and falls back to the stored value without one. Without
    this the suite would both read and overwrite the operator's real
    ~/.local/state/strata/state.json.
    """
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setattr(state, "_OLD_CONFIG_FILE", tmp_path / "no-legacy.json")


_ENSURE_PATH = "playbooks/ensure_path.yml"


@pytest.fixture(autouse=True)
def _journey_seams(monkeypatch: pytest.MonkeyPatch, ctx: dict[str, Any]) -> None:
    ctx.setdefault("satisfied_paths", set())
    ctx.setdefault("podman_installed", False)

    monkeypatch.setattr(
        guard_executor,
        "_path_satisfied",
        lambda spec: spec.path in ctx["satisfied_paths"],
    )

    real_which = shutil.which

    def fake_which(cmd: str, *args: Any, **kwargs: Any) -> str | None:
        if cmd == "podman":
            return "/usr/bin/podman" if ctx["podman_installed"] else None
        return real_which(cmd, *args, **kwargs)

    monkeypatch.setattr(shutil, "which", fake_which)


def _ran(ctx: dict[str, Any]) -> list[str]:
    return [p["playbook"] for p in ctx["playbooks"]]


def _index(ctx: dict[str, Any], playbook: str) -> int:
    ran = _ran(ctx)
    assert playbook in ran, f"{playbook} not among {ran}"
    return ran.index(playbook)


# ── Given ─────────────────────────────────────────────────────────────────


@given("the target is the local controller")
def target_is_controller(ctx: dict[str, Any]) -> None:
    """A named host the inventory reports as ansible_connection=local.

    Not target=None: the CLI always resolves a target (falling back to the
    stored last_target), so None never reaches the executor. What actually
    turns the local fast paths on is the inventory saying the host is local.
    """
    ctx["target"] = "workstation"
    ctx["device_for"] = {
        "workstation": Device(
            name="workstation", host="127.0.0.1", user="operator", connection="local"
        )
    }


@given("the target is a remote ssh host")
def target_is_remote(ctx: dict[str, Any]) -> None:
    ctx["target"] = "nas"
    ctx["device_for"] = {"nas": Device(name="nas", host="10.0.0.9", user="nas", connection="ssh")}


@given("the sudo password is already in the vault")
def sudo_stored(ctx: dict[str, Any]) -> None:
    ctx["vault"]["ansible_become_password"] = "sudo-pw"


@given("neither the diot user, Podman nor Jellyfin are installed")
def nothing_installed(ctx: dict[str, Any]) -> None:
    ctx["users"] = set()
    ctx["podman_installed"] = False
    ctx["satisfied_paths"] = set()
    ctx["mounted"] = set()


@given("the diot user and Podman are installed")
def diot_and_podman(ctx: dict[str, Any]) -> None:
    ctx["users"] = {"diot"}
    ctx["podman_installed"] = True


@given("Jellyfin and its whole chain are already installed")
def chain_installed(ctx: dict[str, Any]) -> None:
    ctx["users"] = {"diot"}
    ctx["podman_installed"] = True
    ctx["satisfied_paths"] = {"/srv/jellyfin/config", "/srv/jellyfin/cache"}
    ctx["mounted"] = {"pcloud:Media"}
    ctx["mount_root"] = "/"  # an existing path, so the mount check passes


# ── When ──────────────────────────────────────────────────────────────────


@when(parsers.parse('I run "strata runbook {name}"'))
def run_runbook(ctx: dict[str, Any], name: str) -> None:
    try:
        ctx["exit_code"] = dispatch.run_runbook(name, target=ctx.get("target"))
    except Exception as exc:  # noqa: BLE001 - scenarios assert on what was raised
        ctx["error"] = exc


# ── Then ──────────────────────────────────────────────────────────────────


@then("the diot user is created")
def diot_created(ctx: dict[str, Any]) -> None:
    assert "playbooks/create_diot_user.yml" in _ran(ctx), _ran(ctx)


@then("Podman is installed")
def podman_installed(ctx: dict[str, Any]) -> None:
    assert "playbooks/install_podman.yml" in _ran(ctx), _ran(ctx)


@then("the Jellyfin config and cache directories are ensured")
def jellyfin_dirs_ensured(ctx: dict[str, Any]) -> None:
    ensured = [
        p["extravars"]["guard_path"] for p in ctx["playbooks"] if p["playbook"] == _ENSURE_PATH
    ]
    assert ensured == ["/srv/jellyfin/config", "/srv/jellyfin/cache"], ensured


@then("the media mount is brought up")
def media_mount_up(ctx: dict[str, Any]) -> None:
    assert "playbooks/enable_rclone.yml" in _ran(ctx), _ran(ctx)


@then("Jellyfin is deployed last")
def jellyfin_last(ctx: dict[str, Any]) -> None:
    assert _ran(ctx)[-1] == "playbooks/install_jellyfin.yml", _ran(ctx)


@then(parsers.parse('only "{playbook}" is run'))
def only_one_playbook(ctx: dict[str, Any], playbook: str) -> None:
    assert _ran(ctx) == [playbook], _ran(ctx)


@then(parsers.parse('"{playbook}" is run'))
def playbook_ran(ctx: dict[str, Any], playbook: str) -> None:
    assert playbook in _ran(ctx), _ran(ctx)


@then(parsers.parse('"{playbook}" is not run'))
def playbook_not_run(ctx: dict[str, Any], playbook: str) -> None:
    assert playbook not in _ran(ctx), _ran(ctx)


@then(parsers.parse('{count:d} directories are ensured before "{playbook}"'))
def dirs_before(ctx: dict[str, Any], count: int, playbook: str) -> None:
    leaf = _index(ctx, playbook)
    ensured = [i for i, name in enumerate(_ran(ctx)) if name == _ENSURE_PATH]
    assert len(ensured) == count, _ran(ctx)
    assert all(i < leaf for i in ensured), _ran(ctx)


@then(parsers.parse('"{first}" runs before "{second}"'))
def runs_before(ctx: dict[str, Any], first: str, second: str) -> None:
    assert _index(ctx, first) < _index(ctx, second), _ran(ctx)


@then("the chain is provisioned anyway rather than skipped")
def chain_not_skipped(ctx: dict[str, Any]) -> None:
    """On a non-controller target every local fast path is off by design.

    _path_satisfied, the pwd lookup, the mount check and upstream check() all
    interrogate the controller, so on a remote host they would report another
    machine's state as this one's.
    """
    ran = _ran(ctx)
    assert _ENSURE_PATH in ran, ran
    assert "playbooks/enable_rclone.yml" in ran, ran
    assert ran[-1] == "playbooks/install_jellyfin.yml", ran
