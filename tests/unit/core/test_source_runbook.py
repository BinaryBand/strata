"""The runbook built from a project's manifest declares what a hand-written one would."""

from __future__ import annotations

import typing
from pathlib import Path
from typing import Any

from strata.core import guard, source_runbook
from strata.core import requirements as req
from strata.core.models import SourceAppSpec
from strata.core.models.source_app_spec import Toolchain
from tests._fakes import SOURCE_MANIFEST, RecordingPlaybookRunner

_PROJECT = Path("/home/you/Dev/demo")


def _build(**overrides: Any) -> Any:
    spec = SourceAppSpec.model_validate({**SOURCE_MANIFEST, **overrides})
    return source_runbook.build(spec, _PROJECT)


def test_the_module_is_documented_like_a_runbook() -> None:
    assert _build().__doc__ == (
        "Runbook: deploy Demo service from its own repository "
        "as a systemd user service owned by diot."
    )


def test_every_toolchain_has_a_runbook_that_installs_it() -> None:
    assert set(source_runbook.TOOLCHAIN_RUNBOOKS) == set(typing.get_args(Toolchain))


def test_guards_run_in_the_order_the_host_needs() -> None:
    assert guard.declared(_build().main) == [
        req.Prerequisite("sudo_password"),
        req.SystemUser("diot", "playbooks/create_diot_user.yml"),
        req.UpstreamRunbook("infrastructure.install_uv"),
        req.LocalPath("/srv/demo", "diot", "demo", "2770", "directory"),
        req.LocalPath("/srv/demo/data", "diot", "demo", "2770", "directory"),
        req.LocalPath("/srv/demo/config", "diot", "demo", "2750", "directory"),
        req.Secret("demo_host", "Host", "text", None, generate=False),
        req.Secret("demo_key", "API key", "password", None, generate=False),
    ]


def test_a_project_without_a_backup_declares_no_tag() -> None:
    manifest = {k: v for k, v in SOURCE_MANIFEST.items() if k != "backup"}
    module = source_runbook.build(SourceAppSpec.model_validate(manifest), _PROJECT)
    assert guard.backup_tags_of(module.main) == ()


def test_main_runs_the_source_playbook_with_the_resolved_project() -> None:
    module = _build()
    runner = RecordingPlaybookRunner(rc=7)
    assert module.main("owen", runner=runner) == 7
    ((playbook, extravars, target),) = runner.calls
    assert (playbook, target) == (source_runbook.PLAYBOOK, "owen")
    assert module.PLAYBOOK == source_runbook.PLAYBOOK
    assert extravars["source_app"] == {
        "name": "demo",
        "root": "/srv/demo",
        "description": "Demo service",
        "project_dir": str(_PROJECT),
        "build": "uv sync --frozen",
        "command": "uv run --no-sync demo serve --host ${DEMO_HOST}",
        "env": {"MODE": "prod"},
        "secret_env": [{"name": "demo_host", "env": "DEMO_HOST"}],
        "secret_files": [{"name": "demo_key", "path": "/srv/demo/config/key"}],
    }


def test_only_a_secret_with_an_env_name_reaches_the_unit() -> None:
    module = _build(secrets=[{"name": "demo_key", "prompt": "Key", "file": "/srv/demo/config/key"}])
    runner = RecordingPlaybookRunner()
    module.main(runner=runner)
    app = runner.calls[0][1]["source_app"]
    assert app["secret_env"] == []
    assert app["secret_files"] == [{"name": "demo_key", "path": "/srv/demo/config/key"}]
