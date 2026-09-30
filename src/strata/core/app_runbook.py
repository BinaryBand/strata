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

from collections.abc import Callable
from types import ModuleType

from strata.core import guard
from strata.core.models import AppSpec
from strata.core.ports import PlaybookRunner
from strata.core.remote_paths import resolve

PLAYBOOK = "playbooks/install_podman_app.yml"
PACKAGE = "strata.core.runbooks"

_OWNER = "diot"

type _Main = Callable[..., int]
type _Guard = Callable[[_Main], _Main]


def dotted_name(app: str) -> str:
    """The runbook of app `app`, relative to strata.core.runbooks: ``services.install_baikal``."""
    return f"services.install_{app}"


def build(spec: AppSpec) -> ModuleType:
    """Return the runbook module for `spec`, its guards declared and its backup tag registered."""
    extravars = {"podman_app": _payload(spec)}

    def main(target: str | None = None, *, runner: PlaybookRunner) -> int:
        """Deploy the container and its Quadlet unit."""
        return runner.run_playbook(PLAYBOOK, extravars=extravars, target=target)

    module_name = f"{PACKAGE}.{dotted_name(spec.name)}"
    main.__module__ = module_name
    # `guard.requires` reads the module name off the function, so it is set first.
    # Each decorator prepends, so applying the list from the end gives the order written.
    runbook: _Main = main
    for declare in reversed(_guards(spec)):
        runbook = declare(runbook)
    module = ModuleType(
        module_name,
        f"Runbook: deploy {spec.description} as a rootless Podman container owned by diot.",
    )
    vars(module).update(main=runbook, PLAYBOOK=PLAYBOOK)
    return module


def _guards(spec: AppSpec) -> list[_Guard]:
    """The guards, outermost first: the order the executor satisfies them in.

    A directory's owner is created by an earlier guard, so the paths follow the
    user and podman guards.
    """
    guards: list[_Guard] = [guard.alias(spec.alias)]
    if spec.backup:
        guards.append(guard.backup_tag(spec.backup.tag, spec.backup.path))
    guards += [
        guard.prerequisite("sudo_password"),
        guard.requires("infrastructure.install_podman"),
    ]
    guards += [guard.path(d.path, owner=_OWNER, group=spec.name, mode=d.mode) for d in spec.dirs]
    if spec.mount:
        guards.append(guard.mount(spec.mount.remote))
    guards += [
        guard.secret(s.name, kind=s.kind, prompt=s.prompt, default=s.default, generate=s.generate)
        for s in spec.secrets
    ]
    return guards


def _payload(spec: AppSpec) -> dict[str, object]:
    """The app as the playbook's template reads it."""
    volumes = [{"host": v.host, "container": v.container, "options": "Z"} for v in spec.volumes]
    mounted = None
    if spec.mount:
        mounted = resolve(spec.mount.remote)
        volumes.append({"host": mounted, "container": spec.mount.container, "options": "ro"})
    return {
        "name": spec.name,
        "group": spec.name,
        "description": spec.description,
        "image": spec.image,
        "volumes": volumes,
        "requires_mounts_for": mounted,
        "ports": [{"host": p.host, "container": p.container} for p in spec.ports],
        "env": dict(spec.env),
        "secret_env": [{"name": s.name, "env": s.env} for s in spec.secrets_in_unit],
        "command": spec.command,
        "unit_mode": spec.unit_mode,
        "no_log": bool(spec.secrets_in_unit),
    }
