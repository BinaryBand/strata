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

from collections import Counter
from collections.abc import Hashable, Iterable
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Name = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*$")]
EnvName = Annotated[str, StringConstraints(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")]
# Quoted in YAML: an unquoted 2770 is read as the integer 2770, which is not a mode.
Mode = Annotated[str, StringConstraints(pattern=r"^[0-7]{4}$")]
Port = Annotated[int, Field(ge=1, le=65535)]


class _Strict(BaseModel):
    """A declaration with no room for a misspelt key."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class AppDir(_Strict):
    """A local directory the app needs, owned by diot and the group named for the app."""

    path: Annotated[str, StringConstraints(pattern=r"^/")]
    mode: Mode = "2770"


class AppVolume(_Strict):
    """A declared directory bound into the container."""

    host: str
    container: str


class AppMount(_Strict):
    """An rclone remote bound read-only into the container.

    The unit orders itself against the mounted path, since a user unit cannot
    order against the system unit that owns the rclone mount.
    """

    remote: str
    container: str


class AppPort(_Strict):
    """A port the container listens on and the host port it is published at."""

    host: Port
    container: Port


class AppSecret(_Strict):
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


class AppBackup(_Strict):
    """The restic tag that snapshots one of the app's directories."""

    tag: Name
    path: str


class AppSpec(_Strict):
    """One Podman server app: the runbook `services.install_<name>` and its unit."""

    name: Name
    alias: str
    description: str
    image: str
    dirs: Annotated[list[AppDir], Field(min_length=1)]
    volumes: list[AppVolume] = []
    mount: AppMount | None = None
    ports: list[AppPort] = []
    env: dict[EnvName, str] = {}
    command: str | None = None
    secrets: list[AppSecret] = []
    backup: AppBackup | None = None

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
        _require_unique("dirs", dirs)
        _require_unique("ports.host", [p.host for p in self.ports])
        _require_unique("ports.container", [p.container for p in self.ports])
        _require_unique("secrets.name", [s.name for s in self.secrets])
        envs = [s.env for s in self.secrets if s.env] + list(self.env)
        _require_unique("env (secrets included)", envs)
        for volume in self.volumes:
            _require_declared("volume", volume.host, dirs)
        if self.backup:
            _require_declared("backup", self.backup.path, dirs)
        containers = [v.container for v in self.volumes]
        if self.mount:
            containers.append(self.mount.container)
        _require_unique("container paths (volumes and mount)", containers)
        return self


def _require_unique(what: str, values: Iterable[Hashable]) -> None:
    repeated = sorted(str(value) for value, count in Counter(values).items() if count > 1)
    if repeated:
        msg = f"{what} must be unique; repeated: {', '.join(repeated)}"
        raise ValueError(msg)


def _require_declared(what: str, path: str, dirs: list[str]) -> None:
    if path not in dirs:
        msg = (
            f"{what} path {path} is not one of the declared dirs; the directory a "
            "guard provisions and the one the container or backup uses must be the same"
        )
        raise ValueError(msg)
