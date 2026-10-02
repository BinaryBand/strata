"""AppSpec accepts a coherent declaration and refuses one whose parts disagree."""

from __future__ import annotations

import re
from typing import Any

import pytest
from pydantic import ValidationError

from strata.core.models import AppSpec


def _spec(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "name": "demo",
        "alias": "install Demo",
        "description": "Demo server",
        "image": "docker.io/demo/demo:1",
        "dirs": [{"path": "/srv/demo"}],
        "volumes": [{"host": "/srv/demo", "container": "/data"}],
        "ports": [{"host": 8000, "container": 80}],
        "backup": {"tag": "demo", "path": "/srv/demo"},
    }
    return {**base, **overrides}


def test_minimal_spec_takes_its_defaults() -> None:
    spec = AppSpec.model_validate(_spec())
    assert spec.dirs[0].mode == "2770"
    assert spec.unit_mode == "0644"


@pytest.mark.parametrize(
    ("secret", "mode"),
    [
        ({"name": "demo_key", "prompt": "Key", "generate": True, "env": "DEMO_KEY"}, "0600"),
        ({"name": "demo_key", "prompt": "Key"}, "0644"),
    ],
    ids=["written-to-the-unit", "kept-out-of-the-unit"],
)
def test_unit_is_private_only_when_a_secret_is_written_into_it(
    secret: dict[str, Any], mode: str
) -> None:
    assert AppSpec.model_validate(_spec(secrets=[secret])).unit_mode == mode


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"colour": "red"}, "colour"),
        ({"name": "Demo"}, "name"),
        ({"dirs": []}, "dirs"),
        ({"dirs": [{"path": "srv/demo"}]}, "path"),
        ({"dirs": [{"path": "/srv/demo", "mode": 2770}]}, "mode"),
        ({"dirs": [{"path": "/srv/demo", "mode": "770"}]}, "mode"),
        ({"dirs": [{"path": "/srv/demo"}, {"path": "/srv/demo"}]}, "dirs must be unique"),
        ({"volumes": [{"host": "/srv/other", "container": "/data"}]}, "volume path /srv/other"),
        ({"backup": {"tag": "demo", "path": "/srv/other"}}, "backup path /srv/other"),
        (
            {"ports": [{"host": 8000, "container": 80}, {"host": 8000, "container": 81}]},
            "ports.host must be unique",
        ),
        ({"ports": [{"host": 0, "container": 80}]}, "host"),
        ({"tailnet": {"port": 8000, "https_port": 3001}}, "published on 127.0.0.1"),
        ({"files": [{"path": "/other/.env"}]}, "file parent"),
        ({"files": [{"path": "/srv/demo"}]}, "state paths"),
        (
            {
                "volumes": [{"host": "/srv/demo", "container": "/data"}],
                "mount": {"remote": "pcloud:Media", "container": "/data"},
            },
            "container paths",
        ),
        (
            {
                "env": {"DEMO_KEY": "x"},
                "secrets": [{"name": "k", "prompt": "Key", "env": "DEMO_KEY"}],
            },
            "env (secrets included) must be unique",
        ),
    ],
)
def test_incoherent_spec_is_refused(overrides: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError, match=re.escape(message)):
        AppSpec.model_validate(_spec(**overrides))


def test_settings_file_can_be_bound_only_when_its_parent_is_declared() -> None:
    spec = AppSpec.model_validate(
        _spec(
            files=[{"path": "/srv/demo/.env", "mode": "0660"}],
            volumes=[{"host": "/srv/demo/.env", "container": "/app/.env"}],
        )
    )
    assert spec.volumes[0].host == spec.files[0].path
