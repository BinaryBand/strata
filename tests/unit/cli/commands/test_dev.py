"""Unit tests for the hidden `strata dev` maintainer group."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from strata.cli.commands import dev
from strata.cli.main import app
from strata.core.models import ServerAppsDefaults

runner = CliRunner()


def test_dev_exposes_schema_command() -> None:
    """The dev group exposes `schema`."""
    names = {c.name for c in dev.app.registered_commands}
    assert "schema" in names


def test_dev_schema_regenerates_and_reports_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """`dev schema` calls write_schema and echoes where it wrote, without touching disk."""
    monkeypatch.setattr(ServerAppsDefaults, "write_schema", lambda: Path("/tmp/out.json"))
    result = runner.invoke(app, ["dev", "schema"])
    assert result.exit_code == 0
    assert "/tmp/out.json" in result.output
