"""Build the runbook module of an external project from its manifest.

`services.install_<name>` for a project registered in ansible/projects.yml is
this function applied to the strata.app.yml at that project's root. The module
is what `app_runbook` builds for a Podman app -- a `main(target, *, runner)`
carrying declared guards -- but the play it runs ships the project's committed
HEAD to the target, builds it there and runs it as a systemd user service of
diot, rather than pulling an image.
"""

from __future__ import annotations

from pathlib import Path
from types import ModuleType

from strata.core import guard
from strata.core.models import SourceAppSpec
from strata.core.models.source_app_spec import Toolchain
from strata.core.runbook_module import (
    OWNER,
    Guard,
    assemble,
    leading_guards,
    secret_guards,
    state_guards,
)

PLAYBOOK = "playbooks/install_source_app.yml"

# The runbook that puts each toolchain on a host. A new Toolchain value needs a row.
TOOLCHAIN_RUNBOOKS: dict[Toolchain, str] = {"uv": "infrastructure.install_uv"}


def build(spec: SourceAppSpec, project_dir: Path) -> ModuleType:
    """Return the runbook module for the project at `project_dir`, its guards declared."""
    return assemble(
        spec.name,
        f"Runbook: deploy {spec.description} from its own repository "
        "as a systemd user service owned by diot.",
        _guards(spec),
        PLAYBOOK,
        {"source_app": _payload(spec, project_dir)},
    )


def _guards(spec: SourceAppSpec) -> list[Guard]:
    """The guards, outermost first: the order the executor satisfies them in.

    A directory's owner is created by the user guard, so the paths follow it.
    The toolchain runbook runs before the play that builds with it.
    """
    guards = [
        *leading_guards(spec.alias, spec.backup),
        guard.user(OWNER, "playbooks/create_diot_user.yml"),
        guard.requires(TOOLCHAIN_RUNBOOKS[spec.toolchain]),
    ]
    guards += state_guards(spec.name, spec.dirs)
    return guards + secret_guards(spec.secrets)


def _payload(spec: SourceAppSpec, project_dir: Path) -> dict[str, object]:
    """The project as the playbook reads it."""
    return {
        "name": spec.name,
        "root": spec.root,
        "description": spec.description,
        "project_dir": str(project_dir),
        "build": spec.build,
        "command": spec.run.command,
        "env": dict(spec.run.env),
        "secret_env": [{"name": s.name, "env": s.env} for s in spec.secrets_in_unit],
        "secret_files": [{"name": s.name, "path": s.file} for s in spec.secrets if s.file],
    }
