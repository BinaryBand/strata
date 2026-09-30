"""SourceAppSpec accepts a coherent manifest and refuses one whose parts disagree."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from strata.core.models import SourceAppSpec
from tests._fakes import SOURCE_MANIFEST, TAILNET_MANIFEST


def _manifest(**overrides: Any) -> dict[str, Any]:
    return {**SOURCE_MANIFEST, **overrides}


def test_a_coherent_manifest_is_accepted() -> None:
    spec = SourceAppSpec.model_validate(_manifest())
    assert (spec.name, spec.version, spec.toolchain) == ("demo", 1, "uv")
    assert spec.dirs[0].mode == "2770"


def test_the_manifest_is_keyed_by_schema_not_version() -> None:
    assert "schema" in SourceAppSpec.model_json_schema()["properties"]
    assert "version" not in SourceAppSpec.model_json_schema()["properties"]


def test_the_app_lives_under_srv_by_name() -> None:
    assert SourceAppSpec.model_validate(_manifest()).root == "/srv/demo"


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"colour": "red"}, "colour"),
        ({"schema": 2}, "schema"),
        ({"toolchain": "cargo"}, "toolchain"),
        ({"build": ""}, "build"),
        ({"run": {"command": ""}}, "command"),
        ({"name": "Demo"}, "name"),
        ({"dirs": []}, "dirs"),
        ({"dirs": [{"path": "/srv/demo"}, {"path": "/srv/demo"}]}, "dirs must be unique"),
        ({"dirs": [{"path": "/srv/demo/releases/x"}]}, "inside a release"),
        ({"dirs": [{"path": "/srv/demo/current"}]}, "inside a release"),
        ({"backup": {"tag": "demo", "path": "/srv/other"}}, "backup path /srv/other"),
        (
            {"secrets": [{"name": "demo_key", "prompt": "Key"}]},
            "delivered nowhere",
        ),
        (
            {"secrets": [{"name": "demo_key", "prompt": "Key", "file": "/etc/key"}]},
            "not directly inside a declared dir",
        ),
        (
            {"secrets": [{"name": "demo_key", "prompt": "Key", "file": "/srv/demo/config/a/key"}]},
            "not directly inside a declared dir",
        ),
        (
            {
                "secrets": [
                    {"name": "demo_key", "prompt": "Key", "env": "A"},
                    {"name": "demo_key", "prompt": "Key", "env": "B"},
                ]
            },
            "secrets.name must be unique",
        ),
        (
            {"run": {"command": "x", "env": {"DEMO_HOST": "y"}}},
            "env (secrets included) must be unique",
        ),
    ],
)
def test_an_inconsistent_manifest_is_refused(overrides: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError, match=message.replace("(", r"\(").replace(")", r"\)")):
        SourceAppSpec.model_validate(_manifest(**overrides))


def test_a_project_is_not_on_the_tailnet_unless_it_says_so() -> None:
    assert SourceAppSpec.model_validate(_manifest()).tailnet is None


def test_a_tailnet_mount_is_a_path_and_a_loopback_port() -> None:
    spec = SourceAppSpec.model_validate(TAILNET_MANIFEST)
    assert spec.tailnet is not None
    assert (spec.tailnet.path, spec.tailnet.port) == ("/demo", 8123)


@pytest.mark.parametrize(
    ("tailnet", "message"),
    [
        ({"path": "/", "port": 8123}, "path"),
        ({"path": "demo", "port": 8123}, "path"),
        ({"path": "/demo/", "port": 8123}, "path"),
        ({"path": "/a b", "port": 8123}, "path"),
        ({"path": "/demo", "port": 0}, "port"),
        ({"path": "/demo", "port": 70000}, "port"),
        ({"path": "/demo"}, "port"),
        ({"path": "/demo", "port": 8123, "funnel": True}, "funnel"),
    ],
)
def test_a_malformed_tailnet_mount_is_refused(tailnet: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        SourceAppSpec.model_validate({**TAILNET_MANIFEST, "tailnet": tailnet})


def test_a_tailnet_mount_needs_a_command_that_uses_the_host_name() -> None:
    manifest = {**TAILNET_MANIFEST, "run": {"command": "uv run demo serve", "env": {}}}
    with pytest.raises(ValidationError, match=r"never uses \$\{STRATA_TAILNET_HOST\}"):
        SourceAppSpec.model_validate(manifest)


def test_the_host_name_variable_is_strata_s_when_a_mount_is_declared() -> None:
    command = TAILNET_MANIFEST["run"]["command"]
    manifest = {
        **TAILNET_MANIFEST,
        "run": {"command": command, "env": {"STRATA_TAILNET_HOST": "x"}},
    }
    with pytest.raises(ValidationError, match="STRATA_TAILNET_HOST is set by strata"):
        SourceAppSpec.model_validate(manifest)
