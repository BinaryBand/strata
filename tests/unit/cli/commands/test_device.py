"""Unit tests for `strata device` (strata.cli.commands.device).

The inventory adapter is pointed at a scratch hosts.ini, so the real
ansible/inventory/hosts.ini is never read or written.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from strata.adapters.ansible import inventory
from strata.cli.commands.device import app

runner = CliRunner()

_BASE_INI = (
    "[all]\n"
    "\n"
    "[local]\n"
    "workstation ansible_host=192.168.1.10 ansible_user=operator ansible_connection=local\n"
    "\n"
    "[secrets:children]\n"
    "local\n"
)


@pytest.fixture(autouse=True)
def ini_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Redirect inventory read/write to a scratch hosts.ini."""
    ini = tmp_path / "hosts.ini"
    ini.write_text(_BASE_INI)
    monkeypatch.setattr(inventory, "_INI_PATH", ini)
    return ini


# -- add -----------------------------------------------------------------


def test_add_writes_device_into_the_inventory(ini_path: Path) -> None:
    result = runner.invoke(app, ["add", "Rpi4", "--host", "192.168.1.50", "--user", "pi"])
    assert result.exit_code == 0

    text = ini_path.read_text()
    assert "[remote]" in text
    assert "Rpi4" in text
    assert "ansible_host=192.168.1.50" in text
    assert "ansible_user=pi" in text


def test_add_echoes_the_target_hint(ini_path: Path) -> None:
    result = runner.invoke(app, ["add", "Rpi4", "-H", "192.168.1.50"])
    assert result.exit_code == 0
    assert "Device 'Rpi4' -> 192.168.1.50 (ssh)" in result.output
    assert "--target Rpi4" in result.output
    assert ini_path.read_text().count("Rpi4") >= 1


def test_add_defaults_user_root_and_connection_ssh() -> None:
    runner.invoke(app, ["add", "Rpi4", "--host", "10.0.0.9"])
    device = inventory.get("Rpi4")
    assert device is not None
    assert device.user == "root"
    assert device.connection == "ssh"
    assert device.port is None


def test_add_stores_optional_port() -> None:
    runner.invoke(app, ["add", "Rpi4", "--host", "10.0.0.9", "--port", "2222"])
    device = inventory.get("Rpi4")
    assert device is not None
    assert device.port == 2222


def test_add_is_an_upsert() -> None:
    runner.invoke(app, ["add", "Rpi4", "--host", "10.0.0.9"])
    runner.invoke(app, ["add", "Rpi4", "--host", "10.0.0.10", "--user", "pi"])

    devices = [d for d in inventory.list_all() if d.name == "Rpi4"]
    assert len(devices) == 1
    assert devices[0].host == "10.0.0.10"
    assert devices[0].user == "pi"


def test_add_requires_host() -> None:
    result = runner.invoke(app, ["add", "Rpi4"])
    assert result.exit_code != 0


# -- list ----------------------------------------------------------------


def test_list_empty_suggests_add() -> None:
    result = runner.invoke(app, ["list"])
    assert result.exit_code == 0
    assert "No remote devices registered" in result.output
    assert "strata device add" in result.output


def test_list_shows_each_device_with_its_attributes() -> None:
    runner.invoke(app, ["add", "Rpi4", "--host", "10.0.0.9", "--user", "pi", "--port", "2222"])
    runner.invoke(app, ["add", "Nas", "--host", "10.0.0.20"])

    result = runner.invoke(app, ["list"])
    assert result.exit_code == 0
    assert "Rpi4" in result.output
    assert "10.0.0.9" in result.output
    assert "user=pi" in result.output
    assert ":2222" in result.output
    assert "Nas" in result.output


def test_list_excludes_local_hosts() -> None:
    """Only the [remote] group is listed; the controller stays out of it."""
    runner.invoke(app, ["add", "Rpi4", "--host", "10.0.0.9"])
    result = runner.invoke(app, ["list"])
    assert "workstation" not in result.output


# -- show ----------------------------------------------------------------


def test_show_prints_all_fields() -> None:
    runner.invoke(app, ["add", "Rpi4", "--host", "10.0.0.9", "--user", "pi", "--port", "2222"])
    result = runner.invoke(app, ["show", "Rpi4"])
    assert result.exit_code == 0
    assert "Name:       Rpi4" in result.output
    assert "Host:       10.0.0.9" in result.output
    assert "User:       pi" in result.output
    assert "Connection: ssh" in result.output
    assert "Port:       2222" in result.output


def test_show_renders_default_port_placeholder() -> None:
    runner.invoke(app, ["add", "Rpi4", "--host", "10.0.0.9"])
    result = runner.invoke(app, ["show", "Rpi4"])
    assert "Port:       (default)" in result.output


def test_show_not_found_exits_1() -> None:
    result = runner.invoke(app, ["show", "NoSuchDevice"])
    assert result.exit_code == 1
    assert "device 'NoSuchDevice' not found." in result.output


# -- remove --------------------------------------------------------------


def test_remove_deletes_from_the_inventory(ini_path: Path) -> None:
    runner.invoke(app, ["add", "Rpi4", "--host", "10.0.0.9"])
    assert "Rpi4" in ini_path.read_text()

    result = runner.invoke(app, ["remove", "Rpi4"])
    assert result.exit_code == 0
    assert "Removed device 'Rpi4' from inventory." in result.output
    assert "Rpi4" not in ini_path.read_text()
    assert inventory.get("Rpi4") is None


def test_remove_not_found_exits_1() -> None:
    result = runner.invoke(app, ["remove", "NoSuchDevice"])
    assert result.exit_code == 1
    assert "device 'NoSuchDevice' not found." in result.output


def test_remove_leaves_other_devices_alone() -> None:
    runner.invoke(app, ["add", "Rpi4", "--host", "10.0.0.9"])
    runner.invoke(app, ["add", "Nas", "--host", "10.0.0.20"])

    runner.invoke(app, ["remove", "Rpi4"])
    assert [d.name for d in inventory.list_all()] == ["Nas"]
