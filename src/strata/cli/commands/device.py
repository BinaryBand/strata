"""`strata device`: remote hosts in the inventory's [remote] group."""

from __future__ import annotations

import typer

from strata.adapters.ansible import host_vars, inventory
from strata.cli._helpers import not_found

app = typer.Typer(no_args_is_help=True, help="Manage remote Ansible inventory devices.")


@app.command("add")
def device_add(
    name: str = typer.Argument(..., help="Inventory hostname (e.g. 'Rpi4')."),
    host: str = typer.Option(..., "--host", "-H", help="IP or hostname for ansible_host."),
    user: str = typer.Option("root", "--user", "-u", help="SSH user (ansible_user)."),
    connection: str = typer.Option(
        "ssh",
        "--connection",
        "-c",
        help="ansible_connection type (ssh, local, ...).",
    ),
    port: int | None = typer.Option(None, "--port", "-p", help="SSH port (ansible_port)."),
) -> None:
    """Add or update a remote device in the Ansible inventory."""
    device = inventory.add(name, host, user=user, connection=connection, port=port)
    typer.echo(f"Device {device.name!r} -> {device.host} ({device.connection})")
    typer.echo(f"Ensure SSH access is configured, then run playbooks with --target {device.name}")


@app.command("remove")
def device_remove(
    name: str = typer.Argument(..., help="Hostname to remove."),
) -> None:
    """Remove a remote device from the Ansible inventory."""
    if not inventory.remove(name):
        not_found("device", name)
    typer.echo(f"Removed device {name!r} from inventory.")
    # Its per-host vars go too, otherwise re-adding the same hostname later
    # silently inherits the old host's rclone sync list and restic override.
    if host_vars.discard(name):
        typer.echo(f"Removed {name!r}'s host_vars.")


@app.command("list")
def device_list() -> None:
    """List all registered remote devices."""
    devices = inventory.list_all()
    if not devices:
        typer.echo("No remote devices registered. Use `strata device add` to add one.")
        return
    for d in devices:
        port_str = f":{d.port}" if d.port else ""
        typer.echo(f"  {d.name:20s} {d.host}{port_str:10s} user={d.user}  conn={d.connection}")


@app.command("show")
def device_show(
    name: str = typer.Argument(..., help="Hostname to inspect."),
) -> None:
    """Show details for a single device."""
    device = inventory.get(name)
    if device is None:
        not_found("device", name)
    typer.echo(f"Name:       {device.name}")
    typer.echo(f"Host:       {device.host}")
    typer.echo(f"User:       {device.user}")
    typer.echo(f"Connection: {device.connection}")
    typer.echo(f"Port:       {device.port or '(default)'}")
