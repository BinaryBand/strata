"""Unit tests for strata.adapters.ansible.inventory CRUD.

All tests write to a temporary ``hosts.ini`` via monkeypatched ``_INI_PATH``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from strata.adapters.ansible import inventory
from strata.core.models import Device


@pytest.fixture(autouse=True)
def ini_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Redirect every inventory read/write to a scratch ``hosts.ini``."""
    ini = tmp_path / "hosts.ini"
    monkeypatch.setattr(inventory, "_INI_PATH", ini)
    return ini


@pytest.fixture
def base_ini(ini_path: Path) -> Path:
    """Seed the scratch ``hosts.ini`` with the standard starter layout."""
    ini_path.write_text(
        "[all]\n"
        "\n"
        "[local]\n"
        "workstation ansible_host=192.168.1.10 ansible_user=operator ansible_connection=local\n"
        "\n"
        "[secrets:children]\n"
        "local\n"
    )
    return ini_path


# ── add() ─────────────────────────────────────────────────────────────


def test_add_first_device(base_ini: Path) -> None:
    device = inventory.add("Rpi4", "192.168.1.50", user="pi")
    assert device == Device(name="Rpi4", host="192.168.1.50", user="pi", connection="ssh")

    content = base_ini.read_text()
    assert "[remote]" in content
    assert "Rpi4 ansible_host=192.168.1.50 ansible_user=pi ansible_connection=ssh" in content
    assert "remote" in content.split("[secrets:children]")[1]


@pytest.mark.usefixtures("base_ini")
def test_add_multiple_devices() -> None:
    inventory.add("Rpi4", "192.168.1.50")
    inventory.add("NasBox", "192.168.1.100", port=2222)

    devices = inventory.list_all()
    assert len(devices) == 2
    assert devices[0].name == "Rpi4"
    assert devices[1].name == "NasBox"
    assert devices[1].port == 2222


@pytest.mark.usefixtures("base_ini")
def test_add_updates_existing_device() -> None:
    inventory.add("Rpi4", "192.168.1.50", user="pi")
    inventory.add("Rpi4", "192.168.1.51", user="admin", port=2222)

    devices = inventory.list_all()
    assert len(devices) == 1
    d = devices[0]
    assert d.host == "192.168.1.51"
    assert d.user == "admin"
    assert d.port == 2222


def test_add_preserves_local_host(base_ini: Path) -> None:
    inventory.add("Rpi4", "192.168.1.50")

    content = base_ini.read_text()
    assert (
        "workstation ansible_host=192.168.1.10 ansible_user=operator ansible_connection=local"
        in content
    )


# ── remove() ──────────────────────────────────────────────────────────


@pytest.mark.usefixtures("base_ini")
def test_remove_existing_device() -> None:
    inventory.add("Rpi4", "192.168.1.50")
    assert inventory.remove("Rpi4") is True
    assert inventory.list_all() == []


@pytest.mark.usefixtures("base_ini")
def test_remove_nonexistent_returns_false() -> None:
    assert inventory.remove("NoSuchDevice") is False


@pytest.mark.usefixtures("base_ini")
def test_remove_refuses_local_host() -> None:
    assert inventory.remove("workstation") is False
    # Verify workstation is still present.
    assert inventory.get("workstation") is not None


def test_remove_secrets_children_stays_synced(base_ini: Path) -> None:
    inventory.add("Rpi4", "192.168.1.50")
    inventory.remove("Rpi4")

    content = base_ini.read_text()
    secrets_section = content.split("[secrets:children]")[1]
    assert "remote" not in secrets_section


# ── list_all() ────────────────────────────────────────────────────────


@pytest.mark.usefixtures("base_ini")
def test_list_all_empty() -> None:
    assert inventory.list_all() == []


@pytest.mark.usefixtures("base_ini")
def test_list_all_returns_only_remote() -> None:
    inventory.add("Rpi4", "192.168.1.50")
    devices = inventory.list_all()
    names = [d.name for d in devices]
    assert "workstation" not in names
    assert "Rpi4" in names


# ── get() ─────────────────────────────────────────────────────────────


@pytest.mark.usefixtures("base_ini")
def test_get_local_host() -> None:
    device = inventory.get("workstation")
    assert device is not None
    assert device.name == "workstation"
    assert device.connection == "local"


@pytest.mark.usefixtures("base_ini")
def test_get_remote_host() -> None:
    inventory.add("Rpi4", "192.168.1.50", user="pi")
    device = inventory.get("Rpi4")
    assert device is not None
    assert device.host == "192.168.1.50"
    assert device.user == "pi"


@pytest.mark.usefixtures("base_ini")
def test_get_nonexistent_returns_none() -> None:
    assert inventory.get("NoSuchDevice") is None


# ── INI round-trip ────────────────────────────────────────────────────


def test_round_trip_preserves_comments_and_all_section(
    ini_path: Path,
) -> None:
    """Hand-written ``[all]`` comments survive a full add+remove cycle."""
    ini_path.write_text(
        "[all]\n"
        "# host1 ansible_host=192.168.1.1\n"
        "\n"
        "[local]\n"
        "workstation ansible_host=192.168.1.10 ansible_user=operator ansible_connection=local\n"
        "\n"
        "[secrets:children]\n"
        "local\n"
    )
    inventory.add("Rpi4", "192.168.1.50")
    inventory.remove("Rpi4")

    content = ini_path.read_text()
    assert "# host1 ansible_host=192.168.1.1" in content
    assert "workstation ansible_host=192.168.1.10" in content


def test_round_trip_preserves_custom_section(
    ini_path: Path,
) -> None:
    """A section unrelated to devices is preserved."""
    ini_path.write_text(
        "[all]\n"
        "\n"
        "[local]\n"
        "workstation ansible_host=192.168.1.10 ansible_user=operator ansible_connection=local\n"
        "\n"
        "[custom_stuff]\n"
        "foo=bar\n"
        "\n"
        "[secrets:children]\n"
        "local\n"
    )
    inventory.add("Rpi4", "192.168.1.50")
    content = ini_path.read_text()
    assert "[custom_stuff]" in content
    assert "foo=bar" in content


# ── Device model ──────────────────────────────────────────────────────


def test_device_model_defaults() -> None:
    d = Device(name="test", host="1.2.3.4")
    assert d.user == "root"
    assert d.connection == "ssh"
    assert d.port is None


# ── round-trip fidelity ───────────────────────────────────────────────
#
# The parser modelled exactly four variables and _rewrite regenerated
# [remote] from those alone, so anything else on a host line -- and every
# comment in the group -- was destroyed by the next add()/remove(). hosts.ini
# already carries ansible_become_exe, and the module docstring claimed to be
# preserving comments the whole time.


def test_unmodelled_host_vars_survive_a_rewrite(ini_path: Path) -> None:
    ini_path.write_text(
        "[remote]\n"
        "nas ansible_host=10.0.0.1 ansible_user=nas "
        "ansible_become_exe=/usr/bin/sudo.ws ansible_ssh_private_key_file=~/.ssh/id_nas\n"
    )

    inventory.add("other", "10.0.0.2")

    text = ini_path.read_text()
    assert "ansible_become_exe=/usr/bin/sudo.ws" in text
    assert "ansible_ssh_private_key_file=~/.ssh/id_nas" in text


def test_unmodelled_vars_survive_updating_the_same_host(ini_path: Path) -> None:
    ini_path.write_text("[remote]\nnas ansible_host=10.0.0.1 ansible_become_exe=/usr/bin/sudo.ws\n")

    inventory.add("nas", "10.0.0.99")

    text = ini_path.read_text()
    assert "ansible_host=10.0.0.99" in text
    assert "ansible_become_exe=/usr/bin/sudo.ws" in text


def test_comments_inside_remote_survive_a_rewrite(ini_path: Path) -> None:
    ini_path.write_text("[remote]\n# nas is the media box\nnas ansible_host=10.0.0.1\n")

    inventory.add("other", "10.0.0.2")

    assert "# nas is the media box" in ini_path.read_text()


def test_a_leading_comment_does_not_produce_a_bogus_section(ini_path: Path) -> None:
    """The preamble was filed under "" and re-emitted as a literal "[]"."""
    ini_path.write_text("# my inventory\n\n[remote]\nnas ansible_host=10.0.0.1\n")

    inventory.add("other", "10.0.0.2")

    text = ini_path.read_text()
    assert "[]" not in text
    assert text.startswith("# my inventory")


def test_a_trailing_comment_is_not_parsed_as_configuration(ini_path: Path) -> None:
    ini_path.write_text("[remote]\nnas ansible_host=10.0.0.1  # was ansible_user=stale\n")

    device = inventory.get("nas")

    assert device is not None
    assert device.user == "root"


def test_a_bare_hostname_is_visible_and_survives(ini_path: Path) -> None:
    """A host line with no variables is valid inventory, and was invisible."""
    ini_path.write_text("[remote]\nplainhost\nnas ansible_host=10.0.0.1\n")

    assert inventory.get("plainhost") is not None

    inventory.add("other", "10.0.0.2")
    assert "plainhost" in ini_path.read_text()


def test_hosts_in_other_groups_are_not_swept_into_remote(ini_path: Path) -> None:
    """A user-defined group's hosts were collected and duplicated into [remote]."""
    ini_path.write_text(
        "[servers]\nweb ansible_host=10.0.0.5\n\n[remote]\nnas ansible_host=10.0.0.1\n"
    )

    inventory.add("other", "10.0.0.2")

    text = ini_path.read_text()
    assert text.count("web") == 1
    assert "[servers]" in text


def test_a_remote_host_without_an_explicit_connection_is_not_the_controller(
    ini_path: Path,
) -> None:
    """get() defaulted connection to "local" for hosts in any group.

    _is_controller() is built on this, so such a host made every guard fast
    path inspect the local machine and skip provisioning the remote one.
    """
    ini_path.write_text("[remote]\nnas ansible_host=10.0.0.1\n")

    device = inventory.get("nas")

    assert device is not None
    assert device.connection == "ssh"


def test_get_agrees_with_all_hosts_on_the_connection(ini_path: Path) -> None:
    ini_path.write_text(
        "[local]\nworkstation ansible_host=127.0.0.1 ansible_connection=local\n"
        "\n[remote]\nnas ansible_host=10.0.0.1\n"
    )

    by_name = {d.name: d for d in inventory.all_hosts()}
    for name, expected in by_name.items():
        found = inventory.get(name)
        assert found is not None
        assert found.connection == expected.connection
