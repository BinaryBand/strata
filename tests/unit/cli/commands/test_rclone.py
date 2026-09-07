"""Unit tests for `strata rclone` (strata.cli.commands.rclone).

The rclone adapter is faked in-memory: no `rclone` binary is invoked and no
group_vars file is written. `guard_executor.execute` is stubbed so `--apply`
travels the real dispatch path without running a playbook.
"""

from __future__ import annotations

import types
from pathlib import Path

import pytest
from typer.testing import CliRunner

from strata.adapters import guard_executor
from strata.adapters import state as state_mod
from strata.adapters.ansible import inventory, rclone
from strata.cli.commands.rclone import _remote_completer, app

runner = CliRunner()


class _FakeRclone:
    """In-memory stand-in for the rclone adapter's module-level state."""

    def __init__(self) -> None:
        self.configured: set[str] = {"pcloud", "backupdrive"}
        self.registered: list[str] = []
        self.writable: set[str] = set()
        self.serves: list[dict[str, object]] = []
        self.synced: dict[str, list[str]] = {}

    def add_to_config(self, name: str, *, writable: bool = False) -> None:
        if name not in self.registered:
            self.registered.append(name)
        if writable:
            self.writable.add(name)
        else:
            self.writable.discard(name)

    def remove_from_config(self, name: str) -> bool:
        if name not in self.registered:
            return False
        self.registered.remove(name)
        self.writable.discard(name)
        return True

    def add_http_serve(self, name: str, path: str, port: int, base_url: str | None = None) -> None:
        entry: dict[str, object] = {"name": name, "path": path, "port": port}
        if base_url:
            entry["base_url"] = base_url
        self.serves = [s for s in self.serves if s["name"] != name]
        self.serves.append(entry)

    def remove_http_serve(self, name: str) -> bool:
        kept = [s for s in self.serves if s["name"] != name]
        if len(kept) == len(self.serves):
            return False
        self.serves = kept
        return True

    def add_synced_remote(self, host: str, name: str) -> None:
        remotes = self.synced.setdefault(host, [])
        if name not in remotes:
            remotes.append(name)

    def remove_synced_remote(self, host: str, name: str) -> bool:
        remotes = self.synced.get(host, [])
        if name not in remotes:
            return False
        remotes.remove(name)
        return True

    def list_synced_remotes(self, host: str) -> list[str]:
        return list(self.synced.get(host, []))


@pytest.fixture(autouse=True)
def fake(monkeypatch: pytest.MonkeyPatch) -> _FakeRclone:
    """Swap every rclone adapter seam the CLI touches for the in-memory fake."""
    state = _FakeRclone()
    monkeypatch.setattr(rclone, "has_remote", lambda n: n in state.configured)
    monkeypatch.setattr(rclone, "remote_completion", lambda: sorted(state.configured))
    monkeypatch.setattr(rclone, "add_to_config", state.add_to_config)
    monkeypatch.setattr(rclone, "remove_from_config", state.remove_from_config)
    monkeypatch.setattr(rclone, "list_remotes", lambda: list(state.registered))
    monkeypatch.setattr(rclone, "is_writable", lambda n: n in state.writable)
    monkeypatch.setattr(rclone, "add_http_serve", state.add_http_serve)
    monkeypatch.setattr(rclone, "remove_http_serve", state.remove_http_serve)
    monkeypatch.setattr(rclone, "list_http_serves", lambda: list(state.serves))
    monkeypatch.setattr(rclone, "add_synced_remote", state.add_synced_remote)
    monkeypatch.setattr(rclone, "remove_synced_remote", state.remove_synced_remote)
    monkeypatch.setattr(rclone, "list_synced_remotes", state.list_synced_remotes)
    return state


@pytest.fixture(autouse=True)
def _isolated_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setattr(state_mod, "_OLD_CONFIG_FILE", tmp_path / "absent.json")


_BASE_INI = (
    "[all]\n"
    "\n"
    "[local]\n"
    "workstation ansible_host=192.168.1.10 ansible_user=operator ansible_connection=local\n"
    "\n"
    "[remote]\n"
    "nas ansible_host=192.168.1.20 ansible_user=admin ansible_connection=ssh\n"
    "\n"
    "[secrets:children]\n"
    "local\n"
    "remote\n"
)


@pytest.fixture(autouse=True)
def _isolated_inventory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Point `require_host` at a scratch inventory.

    The `--target` checks read ansible/inventory/hosts.ini, which is gitignored
    and absent from a fresh clone. Without this these tests pass only when the
    developer's own inventory happens to name the hosts they target -- which is
    how they were passing before the real inventory stopped being committed.
    """
    ini = tmp_path / "hosts.ini"
    ini.write_text(_BASE_INI)
    monkeypatch.setattr(inventory, "_INI_PATH", ini)


@pytest.fixture
def executions(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str | None]]:
    calls: list[tuple[str, str | None]] = []

    def fake_execute(module: types.ModuleType, *, target: str | None, **_kw: object) -> int:
        calls.append((module.__name__, target))
        return 0

    monkeypatch.setattr(guard_executor, "execute", fake_execute)
    return calls


_ENABLE_RCLONE = "strata.core.runbooks.infrastructure.enable_rclone"
_ENABLE_RCLONE_HTTP = "strata.core.runbooks.infrastructure.enable_rclone_http"
_SYNC_RCLONE_REMOTE = "strata.core.runbooks.infrastructure.sync_rclone_remote"


# -- rclone add ----------------------------------------------------------


def test_add_registers_a_known_remote(fake: _FakeRclone) -> None:
    result = runner.invoke(app, ["add", "pcloud"])
    assert result.exit_code == 0
    assert fake.registered == ["pcloud"]
    assert "Registered 'pcloud'" in result.output
    assert "(read-only)" in result.output


def test_add_writable_flag_reaches_the_adapter(fake: _FakeRclone) -> None:
    result = runner.invoke(app, ["add", "backupdrive", "--writable"])
    assert result.exit_code == 0
    assert fake.writable == {"backupdrive"}
    assert "(read-write)" in result.output


def test_add_rejects_a_remote_rclone_does_not_know(fake: _FakeRclone) -> None:
    result = runner.invoke(app, ["add", "dropbox"])
    assert result.exit_code == 1
    assert "not found in rclone config" in result.output
    assert "rclone config create dropbox" in result.output
    assert fake.registered == []


def test_add_without_apply_prints_hint(
    fake: _FakeRclone, executions: list[tuple[str, str | None]]
) -> None:
    result = runner.invoke(app, ["add", "pcloud"])
    assert "Run `strata runbook infrastructure.enable_rclone` to apply." in result.output
    assert executions == []
    assert fake.registered == ["pcloud"]


def test_add_with_apply_runs_enable_rclone(
    fake: _FakeRclone, executions: list[tuple[str, str | None]]
) -> None:
    result = runner.invoke(app, ["add", "pcloud", "--apply", "--target", "workstation"])
    assert result.exit_code == 0
    assert executions == [(_ENABLE_RCLONE, "workstation")]
    assert fake.registered == ["pcloud"]


# -- rclone remove -------------------------------------------------------


def test_remove_unregisters(fake: _FakeRclone) -> None:
    runner.invoke(app, ["add", "pcloud"])
    result = runner.invoke(app, ["remove", "pcloud"])
    assert result.exit_code == 0
    assert "Removed 'pcloud'." in result.output
    assert fake.registered == []


def test_remove_not_found_exits_1(fake: _FakeRclone) -> None:
    result = runner.invoke(app, ["remove", "pcloud"])
    assert result.exit_code == 1
    assert "remote 'pcloud' not found." in result.output
    assert fake.registered == []


def test_remove_with_apply_runs_enable_rclone(executions: list[tuple[str, str | None]]) -> None:
    runner.invoke(app, ["add", "pcloud"])
    result = runner.invoke(app, ["remove", "pcloud", "--apply", "-t", "workstation"])
    assert result.exit_code == 0
    assert executions == [(_ENABLE_RCLONE, "workstation")]


# -- rclone list ---------------------------------------------------------


def test_list_empty_suggests_add(fake: _FakeRclone) -> None:
    result = runner.invoke(app, ["list"])
    assert result.exit_code == 0
    assert "No remotes registered" in result.output
    assert fake.registered == []


def test_list_shows_mount_root_and_flags_writable() -> None:
    runner.invoke(app, ["add", "pcloud"])
    runner.invoke(app, ["add", "backupdrive", "--writable"])

    result = runner.invoke(app, ["list"])
    assert result.exit_code == 0
    assert f"pcloud -> {rclone.mount_root('pcloud')}" in result.output
    assert "pcloud -> /mnt/rclone/pcloud\n" in result.output
    assert "backupdrive -> /mnt/rclone/backupdrive (read-write)" in result.output


# -- rclone serve add ----------------------------------------------------


def test_serve_add_registers_the_serve(fake: _FakeRclone) -> None:
    result = runner.invoke(app, ["serve", "add", "media-store", "pcloud:Media", "--port", "8083"])
    assert result.exit_code == 0
    assert fake.serves == [{"name": "media-store", "path": "pcloud:Media", "port": 8083}]
    assert "Registered serve 'media-store': pcloud:Media -> http://127.0.0.1:8083" in result.output


def test_serve_add_forwards_base_url(fake: _FakeRclone) -> None:
    runner.invoke(
        app,
        [
            "serve",
            "add",
            "pods",
            "pcloud:Podcasts",
            "--port",
            "8084",
            "--base-url",
            "/media/podcasts",
        ],
    )
    assert fake.serves[0]["base_url"] == "/media/podcasts"


def test_serve_add_empty_base_url_is_not_stored(fake: _FakeRclone) -> None:
    runner.invoke(app, ["serve", "add", "pods", "pcloud:Podcasts", "-p", "8084"])
    assert "base_url" not in fake.serves[0]


def test_serve_add_validates_the_remote_half_of_the_path(fake: _FakeRclone) -> None:
    result = runner.invoke(app, ["serve", "add", "x", "dropbox:Media", "--port", "8083"])
    assert result.exit_code == 1
    assert "Remote 'dropbox' not found in rclone config" in result.output
    assert fake.serves == []


def test_serve_add_requires_a_port(fake: _FakeRclone) -> None:
    result = runner.invoke(app, ["serve", "add", "x", "pcloud:Media"])
    assert result.exit_code != 0
    assert fake.serves == []


def test_serve_add_with_apply_runs_enable_rclone_http(
    fake: _FakeRclone, executions: list[tuple[str, str | None]]
) -> None:
    result = runner.invoke(
        app,
        ["serve", "add", "media", "pcloud:Media", "-p", "8083", "--apply", "-t", "workstation"],
    )
    assert result.exit_code == 0
    assert executions == [(_ENABLE_RCLONE_HTTP, "workstation")]
    assert fake.serves


def test_serve_add_without_apply_prints_hint(executions: list[tuple[str, str | None]]) -> None:
    result = runner.invoke(app, ["serve", "add", "media", "pcloud:Media", "-p", "8083"])
    assert "Run `strata runbook infrastructure.enable_rclone_http` to apply." in result.output
    assert executions == []


# -- rclone serve remove / list -----------------------------------------


def test_serve_remove_deletes_the_entry(fake: _FakeRclone) -> None:
    runner.invoke(app, ["serve", "add", "media", "pcloud:Media", "-p", "8083"])
    result = runner.invoke(app, ["serve", "remove", "media"])
    assert result.exit_code == 0
    assert "Removed 'media'." in result.output
    assert fake.serves == []


def test_serve_remove_not_found_exits_1() -> None:
    result = runner.invoke(app, ["serve", "remove", "media"])
    assert result.exit_code == 1
    assert "HTTP serve 'media' not found." in result.output


def test_serve_list_empty(fake: _FakeRclone) -> None:
    result = runner.invoke(app, ["serve", "list"])
    assert result.exit_code == 0
    assert "No HTTP serves registered" in result.output
    assert fake.serves == []


def test_serve_list_renders_url_and_base_url() -> None:
    runner.invoke(app, ["serve", "add", "media", "pcloud:Media", "-p", "8083"])
    runner.invoke(
        app,
        ["serve", "add", "pods", "pcloud:Podcasts", "-p", "8084", "--base-url", "/pods"],
    )

    result = runner.invoke(app, ["serve", "list"])
    assert result.exit_code == 0
    assert "media: pcloud:Media -> http://127.0.0.1:8083" in result.output
    assert "pods: pcloud:Podcasts -> http://127.0.0.1:8084 (base_url=/pods)" in result.output


# -- rclone sync add ------------------------------------------------------


def test_sync_add_registers_the_remote_for_the_target(fake: _FakeRclone) -> None:
    result = runner.invoke(app, ["sync", "add", "pcloud", "--target", "nas"])
    assert result.exit_code == 0
    assert fake.synced == {"nas": ["pcloud"]}
    assert "Registered 'pcloud' to sync onto 'nas'." in result.output


def test_sync_add_rejects_a_remote_rclone_does_not_know(fake: _FakeRclone) -> None:
    result = runner.invoke(app, ["sync", "add", "dropbox", "--target", "nas"])
    assert result.exit_code == 1
    assert "not found in rclone config" in result.output
    assert fake.synced == {}


def test_sync_add_requires_a_target(fake: _FakeRclone) -> None:  # noqa: ARG001
    result = runner.invoke(app, ["sync", "add", "pcloud"])
    assert result.exit_code != 0


def test_sync_add_without_apply_prints_hint(
    fake: _FakeRclone, executions: list[tuple[str, str | None]]
) -> None:
    result = runner.invoke(app, ["sync", "add", "pcloud", "--target", "nas"])
    assert "Run `strata runbook infrastructure.sync_rclone_remote --target nas` to apply." in (
        result.output
    )
    assert executions == []
    assert fake.synced == {"nas": ["pcloud"]}


def test_sync_add_with_apply_runs_sync_rclone_remote(
    fake: _FakeRclone, executions: list[tuple[str, str | None]]
) -> None:
    result = runner.invoke(app, ["sync", "add", "pcloud", "--target", "nas", "--apply"])
    assert result.exit_code == 0
    assert executions == [(_SYNC_RCLONE_REMOTE, "nas")]
    assert fake.synced == {"nas": ["pcloud"]}


# -- rclone sync remove / list ---------------------------------------------


def test_sync_remove_unregisters(fake: _FakeRclone) -> None:
    runner.invoke(app, ["sync", "add", "pcloud", "--target", "nas"])
    result = runner.invoke(app, ["sync", "remove", "pcloud", "--target", "nas"])
    assert result.exit_code == 0
    assert "Removed 'pcloud' from 'nas'" in result.output
    assert fake.synced == {"nas": []}


def test_sync_remove_not_found_exits_1(fake: _FakeRclone) -> None:  # noqa: ARG001
    result = runner.invoke(app, ["sync", "remove", "pcloud", "--target", "nas"])
    assert result.exit_code == 1
    assert "synced remote 'pcloud' not found." in result.output


def test_sync_remove_with_apply_runs_sync_rclone_remote(
    executions: list[tuple[str, str | None]],
) -> None:
    runner.invoke(app, ["sync", "add", "pcloud", "--target", "nas"])
    result = runner.invoke(app, ["sync", "remove", "pcloud", "--target", "nas", "--apply"])
    assert result.exit_code == 0
    assert executions == [(_SYNC_RCLONE_REMOTE, "nas")]


def test_sync_list_empty_suggests_add(fake: _FakeRclone) -> None:  # noqa: ARG001
    result = runner.invoke(app, ["sync", "list", "--target", "nas"])
    assert result.exit_code == 0
    assert "No remotes registered to sync onto 'nas'" in result.output


def test_sync_list_shows_registered_remotes(fake: _FakeRclone) -> None:  # noqa: ARG001
    runner.invoke(app, ["sync", "add", "pcloud", "--target", "nas"])
    result = runner.invoke(app, ["sync", "list", "--target", "nas"])
    assert result.exit_code == 0
    assert "pcloud" in result.output


def test_sync_list_is_scoped_per_target(fake: _FakeRclone) -> None:  # noqa: ARG001
    runner.invoke(app, ["sync", "add", "pcloud", "--target", "nas"])
    result = runner.invoke(app, ["sync", "list", "--target", "workstation"])
    assert "No remotes registered to sync onto 'workstation'" in result.output


# -- completion ----------------------------------------------------------


def test_remote_completer_suffixes_a_colon() -> None:
    assert _remote_completer("pc") == ["pcloud:"]
    assert set(_remote_completer("")) == {"pcloud:", "backupdrive:"}


def test_remote_completer_matches_on_the_remote_half_only() -> None:
    assert _remote_completer("pcloud:Med") == ["pcloud:"]
