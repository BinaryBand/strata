"""Pydantic model for ansible/apps/<name>.yml, the declaration of one Podman server app.

A server app is a rootless container owned by diot: an image, the local
directories it stores state in, the ports it publishes and, optionally, an
rclone media mount and vaulted secrets. Baikal, Jellyfin and MinIO are three
instances of that one shape, so each is a spec file instead of a runbook and a
playbook of its own. The model doubles as the JSON Schema source for editor
validation:

    strata dev schema  # writes .vscode/app_spec_schema.json

Everything an app needs is stated once. The directories a guard provisions, the
directories the container binds and the directory a backup tag covers must be
the same paths, so the volumes and the backup path are checked against `dirs`
rather than trusted to agree.
"""

from __future__ import annotations

import posixpath
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from strata.core.models.checks import require_declared, require_unique

Name = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*$")]
EnvName = Annotated[str, StringConstraints(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")]
# Quoted in YAML: an unquoted 2770 is read as the integer 2770, which is not a mode.
Mode = Annotated[str, StringConstraints(pattern=r"^[0-7]{4}$")]
Port = Annotated[int, Field(ge=1, le=65535)]


class Strict(BaseModel):
    """A declaration with no room for a misspelt key."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class AppDir(Strict):
    """A local directory the app needs, owned by diot and the group named for the app."""

    path: Annotated[str, StringConstraints(pattern=r"^/")]
    mode: Mode = "2770"


class AppVolume(Strict):
    """A declared directory bound into the container."""

    host: str
    container: str


class AppMount(Strict):
    """An rclone remote bound read-only into the container.

    The unit orders itself against the mounted path, since a user unit cannot
    order against the system unit that owns the rclone mount.
    """

    remote: str
    container: str


class AppPort(Strict):
    """A port the container listens on and the host port it is published at."""

    host: Port
    container: Port
    bind: Literal["127.0.0.1"] | None = None


class AppTailnet(Strict):
    """Publish a loopback port at the root of a private tailnet HTTPS listener."""

    port: Port
    https_port: Port


class AppSecret(Strict):
    """A vault key the operator is prompted for, or that is generated.

    With `env`, the value reaches the container as that environment variable,
    which puts it in the Quadlet unit: the unit is then written 0600 and its
    task is not logged.
    """

    name: Name
    prompt: str
    kind: Literal["text", "password"] = "password"
    default: str | None = None
    generate: bool = False
    env: EnvName | None = None


class AppBackup(Strict):
    """The restic tag that snapshots one of the app's directories."""

    tag: Name
    path: str


class AppSpec(Strict):
    """One Podman server app: the runbook `services.install_<name>` and its unit."""

    name: Name
    alias: str
    description: str
    image: str
    dirs: Annotated[list[AppDir], Field(min_length=1)]
    files: list[AppDir] = []
    volumes: list[AppVolume] = []
    mount: AppMount | None = None
    ports: list[AppPort] = []
    env: dict[EnvName, str] = {}
    command: str | None = None
    secrets: list[AppSecret] = []
    backup: AppBackup | None = None
    tailnet: AppTailnet | None = None
    userns: (
        Annotated[str, StringConstraints(pattern=r"^keep-id(:uid=[0-9]+,gid=[0-9]+)?$")] | None
    ) = None
    capabilities: list[Annotated[str, StringConstraints(pattern=r"^[A-Z_]+$")]] = []

    @property
    def secrets_in_unit(self) -> list[AppSecret]:
        """The secrets written into the Quadlet unit as environment variables."""
        return [secret for secret in self.secrets if secret.env]

    @property
    def unit_mode(self) -> str:
        """The mode of the Quadlet file: 0600 when a secret is written into it."""
        return "0600" if self.secrets_in_unit else "0644"

    @model_validator(mode="after")
    def _check_consistency(self) -> Self:
        """Reject a spec whose parts disagree, before any of it reaches a host."""
        dirs = [d.path for d in self.dirs]
        require_unique("dirs", dirs)
        state_paths = dirs + [f.path for f in self.files]
        require_unique("state paths", state_paths)
        for file in self.files:
            require_declared("file parent", posixpath.dirname(file.path), dirs)
        require_unique("ports.host", [p.host for p in self.ports])
        require_unique("ports.container", [p.container for p in self.ports])
        require_unique("secrets.name", [s.name for s in self.secrets])
        envs = [s.env for s in self.secrets if s.env] + list(self.env)
        require_unique("env (secrets included)", envs)
        for volume in self.volumes:
            require_declared("volume", volume.host, state_paths)
        if self.backup:
            require_declared("backup", self.backup.path, dirs)
        containers = [v.container for v in self.volumes]
        if self.mount:
            containers.append(self.mount.container)
        require_unique("container paths (volumes and mount)", containers)
        if self.tailnet and not any(
            p.host == self.tailnet.port and p.bind == "127.0.0.1" for p in self.ports
        ):
            msg = "tailnet.port must name a port published on 127.0.0.1"
            raise ValueError(msg)
        return self
