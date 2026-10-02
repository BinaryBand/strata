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
from strata.core.models import AppSpec, AppVolume
from strata.core.remote_paths import resolve
from strata.core.runbook_module import (
    TAILNET_RUNBOOK,
    Guard,
    assemble,
    dotted_name,
    leading_guards,
    secret_guards,
    state_guards,
)

PLAYBOOK = "playbooks/install_podman_app.yml"


def build(spec: AppSpec, shared: frozenset[str] = frozenset()) -> ModuleType:
    """Return the runbook module for `spec`, its guards and backup tag declared.

    `shared` holds the directories of `spec` that another app binds as `owner`.
    """
    return assemble(
        spec.name,
        f"Runbook: deploy {spec.description} as a rootless Podman container owned by diot.",
        _guards(spec),
        PLAYBOOK,
        {"podman_app": _payload(spec, shared)},
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
    if spec.tailnet:
        guards.append(guard.requires(TAILNET_RUNBOOK))
    guards += [
        guard.requires(dotted_name(owner))
        for owner in dict.fromkeys(v.owner for v in spec.volumes if v.owner)
    ]
    guards += state_guards(spec.name, spec.dirs)
    guards += state_guards(spec.name, [f for f in spec.files if f.content is None], state="touch")
    if spec.mount:
        guards.append(guard.mount(spec.mount.remote))
    return guards + secret_guards(spec.secrets)


def _payload(spec: AppSpec, shared: frozenset[str]) -> dict[str, object]:
    """The app as the playbook's template reads it."""
    mount = None
    if spec.mount:
        mount = {"host": resolve(spec.mount.remote), "container": spec.mount.container}
    return {
        "name": spec.name,
        "description": spec.description,
        "image": spec.image,
        "volumes": [
            {
                "host": v.host,
                "container": v.container,
                "options": _volume_options(v, shared),
            }
            for v in spec.volumes
        ],
        "mount": mount,
        "managed_files": [
            {"path": f.path, "mode": f.mode, "content": f.content}
            for f in spec.files
            if f.content is not None
        ],
        "ports": [p.model_dump() for p in spec.ports],
        "tailnet": spec.tailnet.model_dump() if spec.tailnet else None,
        "userns": spec.userns,
        "capabilities": spec.capabilities,
        "env": dict(spec.env),
        "secret_env": [{"name": s.name, "env": s.env} for s in spec.secrets_in_unit],
        "command": spec.command,
        "unit_mode": spec.unit_mode,
        "no_log": bool(spec.secrets_in_unit),
    }


def _volume_options(volume: AppVolume, shared: frozenset[str]) -> str:
    """The Quadlet volume options: `ro` if read-only, and the SELinux label.

    `z` shares the label between containers, `Z` keeps it private to one.
    """
    label = "z" if volume.owner or volume.host in shared else "Z"
    return f"ro,{label}" if volume.readonly else label
