"""pytest-bdd binding for features/device.feature (remote inventory devices).

The inventory adapter reads/writes a single INI file at ``inventory._INI_PATH``;
the autouse fixture redirects that anchor to a per-test tmp file, so scenarios
exercise the real adapter end-to-end against throwaway ``hosts.ini`` instead of
the committed inventory. Preconditions are seeded by calling the adapter
directly; assertions read it back or inspect the CLI output.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pytest_bdd import given, parsers, scenarios, then

from strata.adapters.ansible import inventory

scenarios("device.feature")


@pytest.fixture(autouse=True)
def _isolated_inventory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point the inventory adapter at a throwaway hosts.ini for each scenario."""
    monkeypatch.setattr(inventory, "_INI_PATH", tmp_path / "hosts.ini")


# ── Given: seed inventory state ──────────────────────────────────────────


@given(parsers.parse('a device "{name}" already exists'))
@given(parsers.parse('a device "{name}" is registered'))
def seed_device(name: str) -> None:
    inventory.add(name, "10.0.0.9")


@given(parsers.parse('devices "{first}" and "{second}" are registered'))
def seed_two_devices(first: str, second: str) -> None:
    inventory.add(first, "10.0.0.1")
    inventory.add(second, "10.0.0.2")


@given("no devices are registered")
def no_devices() -> None:
    """No-op: the isolated hosts.ini starts empty."""


# ── Then: assert inventory state or CLI output ───────────────────────────


@then(parsers.parse('a host "{name}" is added to the [remote] group in hosts.ini'))
def host_in_remote_group(name: str) -> None:
    assert name in {d.name for d in inventory.list_all()}


@then(parsers.parse('its user defaults to "{user}" and connection to "{connection}"'))
def defaults_user_connection(user: str, connection: str) -> None:
    # The scenario added exactly one device; re-resolve the sole remote host.
    device = inventory.list_all()[0]
    assert device.user == user
    assert device.connection == connection


@then(
    parsers.parse(
        'host "{name}" records user "{user}", connection "{connection}" and port {port:d}'
    )
)
def records_fields(name: str, user: str, connection: str, port: int) -> None:
    device = inventory.get(name)
    assert device is not None
    assert (device.user, device.connection, device.port) == (user, connection, port)


@then(parsers.parse('host "{name}" is updated rather than duplicated'))
def updated_not_duplicated(name: str) -> None:
    matches = [d for d in inventory.list_all() if d.name == name]
    assert len(matches) == 1


@then(parsers.parse('host "{name}" is removed from the inventory'))
def host_removed(name: str) -> None:
    assert inventory.get(name) is None


@then(parsers.parse('I am reminded to configure SSH access and use "{target_flag}"'))
def reminded_ssh_and_target(ctx: dict[str, Any], target_flag: str) -> None:
    out = ctx["result"].output
    assert "SSH" in out
    assert target_flag in out


@then("both device names, hosts, users and connections are listed")
def both_listed(ctx: dict[str, Any]) -> None:
    out = ctx["result"].output
    names = {d.name for d in inventory.list_all()}
    assert names, "expected seeded devices"
    assert all(n in out for n in names)
    assert "user=" in out
    assert "conn=" in out


@then("its name, host, user, connection and port are shown")
def details_shown(ctx: dict[str, Any]) -> None:
    out = ctx["result"].output
    assert "Name:" in out
    assert "Host:" in out
    assert "Connection:" in out


@then(parsers.parse('an unset port is displayed as "{placeholder}"'))
def unset_port_placeholder(ctx: dict[str, Any], placeholder: str) -> None:
    assert placeholder in ctx["result"].output
