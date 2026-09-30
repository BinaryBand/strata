"""The pieces both runbook builders share."""

from __future__ import annotations

import inspect

from strata.core import guard, runbook_module
from strata.core import requirements as req
from strata.core.models.app_spec import AppDir, AppSecret


def _main() -> runbook_module.Main:
    """A fresh main: guards are declared on the function itself, so none may be shared."""

    def main(target: str | None = None, *, runner: object) -> int:  # noqa: ARG001
        return 0

    return main


def test_an_app_is_named_for_its_install_runbook() -> None:
    assert runbook_module.dotted_name("demo") == "services.install_demo"


def test_state_is_owned_by_diot_and_the_apps_group() -> None:
    guards = runbook_module.state_guards("demo", [AppDir(path="/srv/demo", mode="2750")])
    assert guard.declared(guards[0](_main())) == [
        req.LocalPath("/srv/demo", "diot", "demo", "2750", "directory")
    ]


def test_each_secret_is_declared_with_its_prompt_and_default() -> None:
    secret = AppSecret(name="demo_user", prompt="User", kind="text", default="admin")
    (declare,) = runbook_module.secret_guards([secret])
    assert guard.declared(declare(_main())) == [
        req.Secret("demo_user", "User", "text", "admin", generate=False)
    ]


def test_the_guards_apply_in_the_order_written() -> None:
    module = runbook_module.assemble(
        "demo",
        "Runbook: demo.",
        _main(),
        [guard.prerequisite("first"), guard.prerequisite("second")],
        "playbooks/demo.yml",
    )
    assert module.__name__ == "strata.core.runbooks.services.install_demo"
    assert module.__doc__ == "Runbook: demo."
    assert module.PLAYBOOK == "playbooks/demo.yml"
    assert guard.declared(module.main) == [req.Prerequisite("first"), req.Prerequisite("second")]
    assert list(inspect.signature(module.main).parameters) == ["target", "runner"]
