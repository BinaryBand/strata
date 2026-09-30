"""The project list and the manifest at a project's root are read strictly."""

from __future__ import annotations

from pathlib import Path

import pytest

from strata.core import projects
from tests._fakes import write_project


def test_no_list_means_no_projects(projects_file: Path) -> None:
    assert not projects_file.exists()
    assert projects.registered(projects_file) == []


def test_the_listed_directories_come_back_in_order(projects_file: Path) -> None:
    projects_file.write_text("projects:\n  - /srv/b\n  - /srv/a\n")
    assert projects.registered(projects_file) == [Path("/srv/b"), Path("/srv/a")]


def test_a_relative_path_is_refused(projects_file: Path) -> None:
    projects_file.write_text("projects:\n  - nils\n")
    with pytest.raises(projects.ProjectError, match=r"projects\.yml.*absolute.*nils"):
        projects.registered(projects_file)


@pytest.mark.parametrize("text", ["projects: nils\n", "project: []\n", "projects: [\n"])
def test_a_malformed_list_names_its_file(projects_file: Path, text: str) -> None:
    projects_file.write_text(text)
    with pytest.raises(projects.ProjectError, match=r"projects\.yml"):
        projects.registered(projects_file)


def test_the_manifest_at_a_project_root_is_loaded(tmp_path: Path) -> None:
    project = write_project(tmp_path / "demo")
    assert projects.load(project).name == "demo"


def test_a_project_without_a_manifest_names_the_missing_file(tmp_path: Path) -> None:
    with pytest.raises(projects.ProjectError, match=r"strata\.app\.yml"):
        projects.load(tmp_path)


def test_an_invalid_manifest_names_its_file(tmp_path: Path) -> None:
    (tmp_path / "strata.app.yml").write_text("name: demo\n")
    with pytest.raises(projects.ProjectError, match=r"strata\.app\.yml"):
        projects.load(tmp_path)
