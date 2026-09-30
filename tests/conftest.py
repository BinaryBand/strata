"""Fixtures every test gets."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from strata.core import paths


@pytest.fixture(scope="session", autouse=True)
def _no_registered_projects(tmp_path_factory: pytest.TempPathFactory) -> Iterator[None]:
    """Keep the operator's ansible/projects.yml out of every test.

    Discovery builds a runbook from each project registered there, so the real
    list would add runbooks to whatever a test enumerates. This is session
    scoped because a module-scoped fixture that lists the runbooks is set up
    before any function-scoped one.
    """
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(paths, "PROJECTS_FILE", tmp_path_factory.mktemp("projects") / "projects.yml")
        yield


@pytest.fixture(autouse=True)
def projects_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A project list that does not exist yet, private to the test.

    A test that wants registered projects writes them to the path this returns.
    """
    file = tmp_path / "projects.yml"
    monkeypatch.setattr(paths, "PROJECTS_FILE", file)
    return file
