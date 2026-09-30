"""Find the external projects registered on this machine and read their manifests.

`ansible/projects.yml` lists the checkouts, and each one ships a strata.app.yml
at its root. Reading them sits here beside `app_specs` for the same reason: it
enumerates what the machine declares, and discovery builds a runbook from each.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from strata.core.models import SourceAppSpec
from strata.core.models.app_spec import Strict

MANIFEST = "strata.app.yml"


class ProjectError(ValueError):
    """A project list or manifest that cannot be read as a declaration."""


class _ProjectList(Strict):
    projects: list[str]


def registered(file: Path) -> list[Path]:
    """The project directories listed in `file`, in order; none when the file is absent."""
    if not file.exists():
        return []
    try:
        listed = _ProjectList.model_validate(yaml.safe_load(file.read_text()))
    except (yaml.YAMLError, ValidationError) as exc:
        msg = f"{file.name}: {exc}"
        raise ProjectError(msg) from exc
    directories = [Path(entry).expanduser() for entry in listed.projects]
    relative = [str(d) for d in directories if not d.is_absolute()]
    if relative:
        msg = f"{file.name}: project paths must be absolute; got {', '.join(relative)}"
        raise ProjectError(msg)
    return directories


def load(directory: Path) -> SourceAppSpec:
    """Read the manifest at the root of `directory`."""
    manifest = directory / MANIFEST
    try:
        return SourceAppSpec.model_validate(yaml.safe_load(manifest.read_text()))
    except (OSError, yaml.YAMLError, ValidationError) as exc:
        msg = f"{manifest}: {exc}"
        raise ProjectError(msg) from exc
