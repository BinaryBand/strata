"""Fixtures every unit test gets."""

from __future__ import annotations

from pathlib import Path

import pytest

from strata.adapters.ansible import host_vars
from strata.core import guard


@pytest.fixture(autouse=True)
def _scratch_host_vars(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Point host_vars at a scratch directory.

    The guards read a target's host_vars override, so without this a test
    naming a target would read the operator's real host_vars/<target>.yml.
    """
    monkeypatch.setattr(host_vars, "_HOST_VARS_DIR", tmp_path / "host_vars")


@pytest.fixture
def isolated_guard_registries(monkeypatch: pytest.MonkeyPatch) -> None:
    """Empty the registries that building a runbook writes to (upstreams and backup tags).

    A test that builds a runbook from a spec of its own would otherwise leave
    that spec's entries in the process-wide registries the other tests read.
    """
    monkeypatch.setattr(guard, "_requires", {})
    monkeypatch.setattr(guard, "_backup_paths", {})
