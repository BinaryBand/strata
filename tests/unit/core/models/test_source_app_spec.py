"""SourceAppSpec accepts a coherent manifest and refuses one whose parts disagree."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from strata.core.models import SourceAppSpec
from tests._fakes import SOURCE_MANIFEST


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
