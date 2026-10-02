"""The shipped specs load, and a spec file that lies about itself is refused."""

from __future__ import annotations

from pathlib import Path

import pytest

from strata.core import app_specs, paths


def _shipped() -> list[app_specs.AppSpec]:
    return [app_specs.load(path) for path in app_specs.spec_files(paths.APPS_DIR)]


def test_shipped_specs_are_the_server_apps() -> None:
    assert [spec.name for spec in _shipped()] == [
        "anythingllm",
        "baikal",
        "jellyfin",
        "minio",
        "ollama",
        "static_agent",
    ]


def test_only_minio_writes_a_secret_into_its_unit() -> None:
    modes = {spec.name: spec.unit_mode for spec in _shipped()}
    assert modes == {
        "anythingllm": "0644",
        "baikal": "0644",
        "jellyfin": "0644",
        "minio": "0600",
        "ollama": "0644",
        "static_agent": "0644",
    }


def test_spec_files_are_the_yaml_files_in_name_order(tmp_path: Path) -> None:
    for name in ("b.yml", "a.yml", "notes.txt"):
        (tmp_path / name).write_text("")
    assert [p.name for p in app_specs.spec_files(tmp_path)] == ["a.yml", "b.yml"]


def test_a_file_named_for_another_app_is_refused(tmp_path: Path) -> None:
    other = tmp_path / "other.yml"
    other.write_text((paths.APPS_DIR / "baikal.yml").read_text())
    with pytest.raises(app_specs.AppSpecError, match=r"other\.yml: declares name 'baikal'"):
        app_specs.load(other)


def test_an_invalid_spec_names_its_file(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yml"
    bad.write_text("name: bad\n")
    with pytest.raises(app_specs.AppSpecError, match=r"bad\.yml"):
        app_specs.load(bad)


def test_unparseable_yaml_names_its_file(tmp_path: Path) -> None:
    broken = tmp_path / "broken.yml"
    broken.write_text("name: [unclosed\n")
    with pytest.raises(app_specs.AppSpecError, match=r"broken\.yml"):
        app_specs.load(broken)


def _owned(owner: str, host: str = "/srv/other") -> app_specs.AppSpec:
    return app_specs.AppSpec.model_validate(
        {
            "name": "demo",
            "alias": "install Demo",
            "description": "Demo server",
            "image": "docker.io/demo/demo:1",
            "dirs": [{"path": "/srv/demo"}],
            "volumes": [{"host": host, "container": "/shared", "owner": owner}],
        }
    )


def test_shipped_owned_volumes_name_a_directory_their_owner_declares() -> None:
    specs = {spec.name: spec for spec in _shipped()}
    for spec in specs.values():
        app_specs.check_owners(spec, specs)
    assert app_specs.shared_dirs(specs.values()) == {
        "static_agent": frozenset({"/srv/static-agent"})
    }


@pytest.mark.parametrize("owner", ["missing", "ollama"])
def test_an_owner_that_does_not_declare_the_directory_is_refused(owner: str) -> None:
    specs = {spec.name: spec for spec in _shipped()}
    with pytest.raises(app_specs.AppSpecError, match="does not declare it"):
        app_specs.check_owners(_owned(owner), specs)
