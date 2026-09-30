"""The shipped specs load, and a spec file that lies about itself is refused."""

from __future__ import annotations

from pathlib import Path

import pytest

from strata.core import app_specs, paths


def test_shipped_specs_are_the_three_server_apps() -> None:
    assert [spec.name for spec in app_specs.load_all()] == ["baikal", "jellyfin", "minio"]


def test_only_minio_writes_a_secret_into_its_unit() -> None:
    modes = {spec.name: spec.unit_mode for spec in app_specs.load_all()}
    assert modes == {"baikal": "0644", "jellyfin": "0644", "minio": "0600"}


def test_a_file_named_for_another_app_is_refused(tmp_path: Path) -> None:
    source = (paths.APPS_DIR / "baikal.yml").read_text()
    (tmp_path / "other.yml").write_text(source)
    with pytest.raises(app_specs.AppSpecError, match=r"other\.yml: declares name 'baikal'"):
        app_specs.load_all(tmp_path)


def test_an_invalid_spec_names_its_file(tmp_path: Path) -> None:
    (tmp_path / "bad.yml").write_text("name: bad\n")
    with pytest.raises(app_specs.AppSpecError, match=r"bad\.yml"):
        app_specs.load_all(tmp_path)


def test_unparseable_yaml_names_its_file(tmp_path: Path) -> None:
    (tmp_path / "broken.yml").write_text("name: [unclosed\n")
    with pytest.raises(app_specs.AppSpecError, match=r"broken\.yml"):
        app_specs.load_all(tmp_path)
