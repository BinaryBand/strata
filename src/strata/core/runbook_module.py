"""Assemble a runbook module from declarations, for the builders that have no file to import.

`app_runbook` (a Podman app from ansible/apps/) and `source_runbook` (an
external project's manifest) both produce what a hand-written runbook is: a
docstring, a `main(target, *, runner)` carrying declared guards, and the
playbook it runs. What differs is the guards each declares, the playbook and
the extravar it is handed, so what they share lives here once: the account that
owns an app's state, the guards that open and close every chain, and the
assembly itself.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from types import ModuleType

from strata.core import guard
from strata.core.models.app_spec import AppBackup, AppDir, AppSecret
from strata.core.ports import PlaybookRunner

OWNER = "diot"
TAILNET_RUNBOOK = "infrastructure.enable_tailscale"

type Main = Callable[..., int]
type Guard = Callable[[Main], Main]


def dotted_name(app: str) -> str:
    """The runbook of app `app`, relative to strata.core.runbooks: ``services.install_baikal``."""
    return f"services.install_{app}"


def leading_guards(alias: str, backup: AppBackup | None) -> list[Guard]:
    """The guards every app chain starts with: its alias, its backup tag and sudo."""
    guards: list[Guard] = [guard.alias(alias)]
    if backup:
        guards.append(guard.backup_tag(backup.tag, backup.path))
    return [*guards, guard.prerequisite("sudo_password")]


def state_guards(app: str, dirs: Iterable[AppDir], *, state: str = "directory") -> list[Guard]:
    """One path guard per entry, owned by diot and the group named for `app`."""
    return [guard.path(d.path, owner=OWNER, group=app, mode=d.mode, state=state) for d in dirs]


def secret_guards(secrets: Iterable[AppSecret]) -> list[Guard]:
    """One secret guard per declared secret."""
    return [
        guard.secret(s.name, kind=s.kind, prompt=s.prompt, default=s.default, generate=s.generate)
        for s in secrets
    ]


def assemble(
    app: str, doc: str, guards: list[Guard], playbook: str, extravars: dict[str, object]
) -> ModuleType:
    """Return the runbook module of `app`: `main` runs `playbook` with `extravars`.

    `guards` are declared on `main`, outermost first.
    """

    def main(target: str | None = None, *, runner: PlaybookRunner) -> int:
        return runner.run_playbook(playbook, extravars=extravars, target=target)

    # Each decorator prepends, so applying the list from the end gives the order written.
    runbook: Main = main
    for declare in reversed(guards):
        runbook = declare(runbook)
    module = ModuleType(f"strata.core.runbooks.{dotted_name(app)}", doc)
    vars(module).update(main=runbook, PLAYBOOK=playbook)
    return module
