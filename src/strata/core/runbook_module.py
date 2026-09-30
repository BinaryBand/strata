"""Assemble a runbook module from declarations, for the builders that have no file to import.

`app_runbook` (a Podman app from ansible/apps/) and `source_runbook` (an
external project's manifest) both produce what a hand-written runbook is: a
docstring, a `main(target, *, runner)` carrying declared guards, and the
playbook it runs. What differs is the guards each declares and the playbook
they hand the executor, so what they share lives here once: the account that
owns an app's state, the guards that provision that state and the secrets, and
the assembly itself.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from types import ModuleType

from strata.core import guard
from strata.core.models.app_spec import AppDir, AppSecret

OWNER = "diot"

type Main = Callable[..., int]
type Guard = Callable[[Main], Main]


def dotted_name(app: str) -> str:
    """The runbook of app `app`, relative to strata.core.runbooks: ``services.install_baikal``."""
    return f"services.install_{app}"


def state_guards(app: str, dirs: Iterable[AppDir]) -> list[Guard]:
    """One path guard per directory, owned by diot and the group named for `app`."""
    return [guard.path(d.path, owner=OWNER, group=app, mode=d.mode) for d in dirs]


def secret_guards(secrets: Iterable[AppSecret]) -> list[Guard]:
    """One secret guard per declared secret."""
    return [
        guard.secret(s.name, kind=s.kind, prompt=s.prompt, default=s.default, generate=s.generate)
        for s in secrets
    ]


def assemble(app: str, doc: str, main: Main, guards: list[Guard], playbook: str) -> ModuleType:
    """Return the runbook module of `app`, with `guards` declared on `main`, outermost first."""
    # Each decorator prepends, so applying the list from the end gives the order written.
    runbook = main
    for declare in reversed(guards):
        runbook = declare(runbook)
    module = ModuleType(f"strata.core.runbooks.{dotted_name(app)}", doc)
    vars(module).update(main=runbook, PLAYBOOK=playbook)
    return module
