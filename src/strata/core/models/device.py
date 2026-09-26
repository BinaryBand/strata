"""Model for a remote device in the Ansible inventory's [remote] group."""

from pydantic import BaseModel


class Device(BaseModel):
    """An Ansible inventory host entry."""

    name: str  # inventory hostname (e.g. "Rpi4", "NasBox")
    host: str  # ansible_host IP or hostname
    user: str = "root"  # ansible_user
    connection: str = "ssh"  # ansible_connection
    port: int | None = None  # ansible_port (optional)
