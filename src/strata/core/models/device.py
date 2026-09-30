"""Model for a remote device in the Ansible inventory's [remote] group."""

import re

from pydantic import BaseModel, Field, field_validator

_TOKEN = re.compile(r"[^\s=]*")


class Device(BaseModel):
    """An Ansible inventory host entry."""

    name: str  # inventory hostname (e.g. "Rpi4", "NasBox")
    host: str  # ansible_host IP or hostname
    user: str = "root"  # ansible_user
    connection: str = "ssh"  # ansible_connection
    port: int | None = Field(default=None, ge=1, le=65535)  # ansible_port (optional)

    @field_validator("name", "host", "user", "connection")
    @classmethod
    def _fits_a_host_line(cls, value: str) -> str:
        """Refuse a value that would split a host line into other tokens.

        A host line is whitespace-separated `key=value` tokens, so a field
        holding whitespace or `=` would read back as other tokens -- or,
        holding a newline, as other lines, a section header included.
        """
        if not _TOKEN.fullmatch(value):
            msg = "cannot contain whitespace or '='"
            raise ValueError(msg)
        return value

    @field_validator("name")
    @classmethod
    def _is_a_host_name(cls, value: str) -> str:
        """Refuse a name the INI would read as a comment or a section header."""
        if not value or value[0] in "#;[":
            msg = "cannot be empty or start with '#', ';' or '['"
            raise ValueError(msg)
        return value

    @property
    def is_controller(self) -> bool:
        """True for the machine strata itself runs on (a `local` connection)."""
        return self.connection == "local"
