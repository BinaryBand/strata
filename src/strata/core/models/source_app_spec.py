"""Pydantic model for strata.app.yml, the manifest an external project ships.

An external project is a repository strata does not own: its code reaches the
target as a `git archive` of the committed HEAD, is built there by the
project's own command, and runs as a systemd user service of diot. The project
declares that contract here, in its own root, so strata holds no fact about any
one app. Where `AppSpec` describes a container image, this describes source.

    strata dev schema  # writes .vscode/source_app_schema.json

The vocabulary for state, secrets and backup is the one `AppSpec` uses. State
lives in `dirs`, outside every release, and the backup path and any secret file
must sit in declared dirs, so what a guard provisions is what the service
and the backup use.
"""

from __future__ import annotations

import posixpath
from typing import Annotated, Literal, Self

from pydantic import Field, StringConstraints, model_validator

from strata.core.models.app_spec import (
    AppBackup,
    AppDir,
    AppSecret,
    EnvName,
    Name,
    Strict,
)
from strata.core.models.checks import require_declared, require_unique

Toolchain = Literal["uv"]


class SourceSecret(AppSecret):
    """A vault key delivered to the service as an environment variable, a file, or both.

    With `env` the value is written into the unit; with `file` it is written to
    that path, mode 0600, for a program that reads a credential file rather
    than its environment.
    """

    file: Annotated[str, StringConstraints(pattern=r"^/")] | None = None

    @model_validator(mode="after")
    def _delivered(self) -> Self:
        if not (self.env or self.file):
            msg = f"secret {self.name} is delivered nowhere; give it an env or a file"
            raise ValueError(msg)
        return self


class SourceRun(Strict):
    """The service: one command, and the environment it starts with.

    systemd expands `${VAR}` in the command from the environment, so a value the
    operator supplies (a secret with `env`) can appear in it with no templating.
    """

    command: Annotated[str, StringConstraints(min_length=1)]
    env: dict[EnvName, str] = Field(default_factory=dict)


class SourceAppSpec(Strict):
    """One external project: the runbook `services.install_<name>` and its unit.

    `build` is a shell line run as diot in the freshly unpacked release, and
    only once per commit. It is where a project reaches state it keeps in its
    tree, such as linking a directory the program insists on into `dirs`.
    """

    version: Literal[1] = Field(alias="schema")
    name: Name
    alias: str
    description: str
    toolchain: Toolchain
    build: Annotated[str, StringConstraints(min_length=1)]
    run: SourceRun
    dirs: Annotated[list[AppDir], Field(min_length=1)]
    secrets: list[SourceSecret] = Field(default_factory=list)
    backup: AppBackup | None = None

    @property
    def secrets_in_unit(self) -> list[SourceSecret]:
        """The secrets written into the unit as environment variables."""
        return [secret for secret in self.secrets if secret.env]

    @property
    def unit_mode(self) -> str:
        """The mode of the unit file: 0600 when a secret is written into it."""
        return "0600" if self.secrets_in_unit else "0644"

    @model_validator(mode="after")
    def _check_consistency(self) -> Self:
        """Reject a manifest whose parts disagree, before any of it reaches a host."""
        dirs = [d.path for d in self.dirs]
        require_unique("dirs", dirs)
        require_unique("secrets.name", [s.name for s in self.secrets])
        envs = [s.env for s in self.secrets if s.env] + list(self.run.env)
        require_unique("env (secrets included)", envs)
        reserved = (f"/srv/{self.name}/releases", f"/srv/{self.name}/current")
        for path in dirs:
            if path.startswith(reserved):
                msg = f"dir {path} is inside a release; state must live outside the releases"
                raise ValueError(msg)
        if self.backup:
            require_declared("backup", self.backup.path, dirs)
        for secret in self.secrets:
            if secret.file and posixpath.dirname(secret.file) not in dirs:
                msg = (
                    f"secret {secret.name} file {secret.file} is not directly inside a declared dir"
                )
                raise ValueError(msg)
        return self
