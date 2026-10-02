"""The runbook built from an app spec declares what a hand-written one would."""

from __future__ import annotations

import inspect
from typing import Any

from strata.core import app_runbook, guard, runbook_module
from strata.core import requirements as req
from strata.core.models import AppSpec
from tests._fakes import RecordingPlaybookRunner

_SPEC: dict[str, Any] = {
    "name": "demo",
    "alias": "install Demo",
    "description": "Demo server",
    "image": "docker.io/demo/demo:1",
    "dirs": [{"path": "/srv/demo"}, {"path": "/srv/demo/cache", "mode": "2777"}],
    "volumes": [{"host": "/srv/demo", "container": "/data"}],
    "mount": {"remote": "pcloud:Media", "container": "/media"},
    "ports": [{"host": 8000, "container": 80}],
    "env": {"MODE": "prod"},
    "command": "serve /data",
    "secrets": [
        {"name": "demo_user", "kind": "text", "prompt": "User", "default": "admin", "env": "USER"},
        {"name": "demo_note", "prompt": "Note", "generate": True},
    ],
    "backup": {"tag": "demo", "path": "/srv/demo"},
}


def _build(**overrides: Any) -> Any:
    return app_runbook.build(AppSpec.model_validate({**_SPEC, **overrides}))


def test_the_module_is_named_and_documented_like_a_runbook() -> None:
    module = _build()
    assert module.__name__ == "strata.core.runbooks.services.install_demo"
    assert module.__doc__ == (
        "Runbook: deploy Demo server as a rootless Podman container owned by diot."
    )
    assert runbook_module.dotted_name("demo") == "services.install_demo"


def test_main_keeps_the_signature_the_executor_injects_into() -> None:
    params = inspect.signature(_build().main).parameters
    assert list(params) == ["target", "runner"]
    assert params["runner"].kind is inspect.Parameter.KEYWORD_ONLY


def test_guards_run_in_the_order_the_host_needs() -> None:
    declared = guard.declared(_build().main)
    assert declared == [
        req.Prerequisite("sudo_password"),
        req.UpstreamRunbook("infrastructure.install_podman"),
        req.LocalPath("/srv/demo", "diot", "demo", "2770", "directory"),
        req.LocalPath("/srv/demo/cache", "diot", "demo", "2777", "directory"),
        req.Mount("pcloud:Media", writable=False),
        req.Secret("demo_user", "User", "text", "admin", generate=False),
        req.Secret("demo_note", "Note", "password", None, generate=True),
    ]


def test_alias_and_backup_tag_are_declared_on_main() -> None:
    module = _build()
    assert guard.alias_of(module.main) == "install Demo"
    assert guard.backup_tags_of(module.main) == (("demo", "/srv/demo"),)


def test_an_app_without_a_backup_or_mount_declares_neither() -> None:
    spec = {k: v for k, v in _SPEC.items() if k not in ("backup", "mount", "secrets")}
    module = app_runbook.build(AppSpec.model_validate(spec))
    kinds = {type(r) for r in guard.declared(module.main)}
    assert kinds == {req.Prerequisite, req.UpstreamRunbook, req.LocalPath}
    assert guard.backup_tags_of(module.main) == ()


def test_main_runs_the_generic_playbook_with_the_resolved_app() -> None:
    module = _build()
    runner = RecordingPlaybookRunner(rc=7)
    assert module.main("nas", runner=runner) == 7
    ((playbook, extravars, target),) = runner.calls
    assert (playbook, target) == (app_runbook.PLAYBOOK, "nas")
    assert module.PLAYBOOK == app_runbook.PLAYBOOK
    assert extravars["podman_app"] == {
        "name": "demo",
        "description": "Demo server",
        "image": "docker.io/demo/demo:1",
        "volumes": [{"host": "/srv/demo", "container": "/data"}],
        "mount": {"host": "/mnt/rclone/pcloud/Media", "container": "/media"},
        "ports": [{"host": 8000, "container": 80, "bind": None}],
        "tailnet": None,
        "userns": None,
        "capabilities": [],
        "env": {"MODE": "prod"},
        "secret_env": [{"name": "demo_user", "env": "USER"}],
        "command": "serve /data",
        "unit_mode": "0600",
        "no_log": True,
    }


def test_a_unit_holding_no_secret_is_public_and_logged() -> None:
    module = _build(secrets=[{"name": "demo_note", "prompt": "Note"}])
    runner = RecordingPlaybookRunner(rc=7)
    module.main(runner=runner)
    app = runner.calls[0][1]["podman_app"]
    assert (app["unit_mode"], app["no_log"], app["secret_env"]) == ("0644", False, [])


def test_tailnet_guard_runs_before_state_and_only_for_published_apps() -> None:
    module = _build(
        ports=[{"host": 3001, "container": 3001, "bind": "127.0.0.1"}],
        tailnet={"port": 3001, "https_port": 3001},
        files=[{"path": "/srv/demo/.env", "mode": "0660"}],
    )
    declared = guard.declared(module.main)
    assert declared[2] == req.UpstreamRunbook("infrastructure.enable_tailscale")
    assert req.LocalPath("/srv/demo/.env", "diot", "demo", "0660", "touch") in declared
    assert req.UpstreamRunbook("infrastructure.enable_tailscale") not in guard.declared(
        _build().main
    )
