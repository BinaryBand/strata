"""The pieces both runbook builders share."""

from __future__ import annotations

import inspect

from strata.core import guard, runbook_module
from strata.core import requirements as req
from strata.core.models.app_spec import AppBackup, AppDir, AppSecret
from tests._fakes import RecordingPlaybookRunner


def _main() -> runbook_module.Main:
    """A fresh main: guards are declared on the function itself, so none may be shared."""

    def main(target: str | None = None, *, runner: object) -> int:  # noqa: ARG001
        return 0

    return main


def test_an_app_is_named_for_its_install_runbook() -> None:
    assert runbook_module.dotted_name("demo") == "services.install_demo"


def test_every_chain_opens_with_the_alias_the_backup_tag_and_sudo() -> None:
    backup = AppBackup(tag="demo", path="/srv/demo")
    (alias, tag, sudo) = runbook_module.leading_guards("install Demo", backup)
    runbook = sudo(tag(alias(_main())))
    assert guard.alias_of(runbook) == "install Demo"
    assert guard.backup_tags_of(runbook) == (("demo", "/srv/demo"),)
    assert guard.declared(runbook) == [req.Prerequisite("sudo_password")]


def test_an_app_without_a_backup_has_no_tag_guard() -> None:
    assert len(runbook_module.leading_guards("install Demo", None)) == 2


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


def test_the_module_runs_its_playbook_with_its_extravars_under_its_guards() -> None:
    module = runbook_module.assemble(
        "demo",
        "Runbook: demo.",
        [guard.prerequisite("first"), guard.prerequisite("second")],
        "playbooks/demo.yml",
        {"demo": {"k": "v"}},
    )
    assert module.__name__ == "strata.core.runbooks.services.install_demo"
    assert module.__doc__ == "Runbook: demo."
    assert module.PLAYBOOK == "playbooks/demo.yml"
    assert guard.declared(module.main) == [req.Prerequisite("first"), req.Prerequisite("second")]
    params = inspect.signature(module.main).parameters
    assert list(params) == ["target", "runner"]
    assert params["runner"].kind is inspect.Parameter.KEYWORD_ONLY

    runner = RecordingPlaybookRunner(rc=7)
    assert module.main("owen", runner=runner) == 7
    assert runner.calls == [("playbooks/demo.yml", {"demo": {"k": "v"}}, "owen")]
