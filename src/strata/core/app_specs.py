"""Load the Podman server-app declarations from ansible/apps/.

One YAML file per app, validated against `AppSpec` on the way in. Reading them
sits here, beside `discovery`'s walk of the runbook package, because both
enumerate what the repository declares; the model itself stays pure.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path

import yaml
from pydantic import ValidationError

from strata.core.models import AppSpec


class AppSpecError(ValueError):
    """A spec file that cannot be read as an app declaration."""


def load(path: Path) -> AppSpec:
    """Read one spec file, refusing one whose `name` is not its file stem.

    The stem is what `strata` and the operator call the app, so a file that
    declares a different name would be found under one and run as another.
    """
    try:
        spec = AppSpec.model_validate(yaml.safe_load(path.read_text()))
    except (yaml.YAMLError, ValidationError) as exc:
        msg = f"{path.name}: {exc}"
        raise AppSpecError(msg) from exc
    if spec.name != path.stem:
        msg = f"{path.name}: declares name {spec.name!r}, but the file is named {path.stem!r}"
        raise AppSpecError(msg)
    return spec


def spec_files(directory: Path) -> list[Path]:
    """The spec files under `directory`, ordered by file name."""
    return sorted(directory.glob("*.yml"))


def check_owners(spec: AppSpec, specs: Mapping[str, AppSpec]) -> None:
    """Refuse a volume whose `owner` is not one of `specs` declaring that directory."""
    for volume in spec.volumes:
        owner = specs.get(volume.owner) if volume.owner else None
        if volume.owner and (owner is None or volume.host not in [d.path for d in owner.dirs]):
            msg = (
                f"{spec.name}: volume {volume.host} names owner {volume.owner!r}, "
                "which does not declare it in its dirs"
            )
            raise AppSpecError(msg)


def shared_dirs(specs: Iterable[AppSpec]) -> dict[str, frozenset[str]]:
    """The directories another app binds, keyed by the app whose `dirs` declare them."""
    shared: dict[str, set[str]] = {}
    for spec in specs:
        for volume in spec.volumes:
            if volume.owner:
                shared.setdefault(volume.owner, set()).add(volume.host)
    return {name: frozenset(hosts) for name, hosts in shared.items()}
