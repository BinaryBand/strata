"""Build the runbook module of a Podman server app from its spec.

`services.install_<name>` is not a file: it is this function applied to
ansible/apps/<name>.yml. The module it returns is what a hand-written runbook
is -- a docstring, a `main(target, *, runner)` carrying declared guards, and
the same alias and backup tag -- so the executor, discovery, the GUI and
infrastructure.backup treat it like any other. Every app runs the one playbook
below, which is handed the resolved app as an extravar and renders the Quadlet
unit from it.
"""

from __future__ import annotations

from types import ModuleType

from strata.core import guard
from strata.core.models import AppSpec
from strata.core.remote_paths import resolve
from strata.core.runbook_module import (
    Guard,
    assemble,
    leading_guards,
    secret_guards,
    state_guards,
)

PLAYBOOK = "playbooks/install_podman_app.yml"


def build(spec: AppSpec) -> ModuleType:
    """Return the runbook module for `spec`, its guards and backup tag declared."""
    return assemble(
        spec.name,
        f"Runbook: deploy {spec.description} as a rootless Podman container owned by diot.",
        _guards(spec),
        PLAYBOOK,
        {"podman_app": _payload(spec)},
    )


def _guards(spec: AppSpec) -> list[Guard]:
    """The guards, outermost first: the order the executor satisfies them in.

    A directory's owner is created by an earlier guard, so the paths follow the
    user and podman guards.
    """
    guards = [
        *leading_guards(spec.alias, spec.backup),
        guard.requires("infrastructure.install_podman"),
    ]
    guards += state_guards(spec.name, spec.dirs)
    if spec.mount:
        guards.append(guard.mount(spec.mount.remote))
    return guards + secret_guards(spec.secrets)


def _payload(spec: AppSpec) -> dict[str, object]:
    """The app as the playbook's template reads it."""
    mount = None
    if spec.mount:
        mount = {"host": resolve(spec.mount.remote), "container": spec.mount.container}
    return {
        "name": spec.name,
        "description": spec.description,
        "image": spec.image,
        "volumes": [{"host": v.host, "container": v.container} for v in spec.volumes],
        "mount": mount,
        "ports": [{"host": p.host, "container": p.container} for p in spec.ports],
        "env": dict(spec.env),
        "secret_env": [{"name": s.name, "env": s.env} for s in spec.secrets_in_unit],
        "command": spec.command,
        "unit_mode": spec.unit_mode,
        "no_log": bool(spec.secrets_in_unit),
    }
