"""Unit tests for the hidden `strata dev` maintainer group."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from strata.cli.commands import dev
from strata.cli.main import app
from strata.core.models import AppSpec

runner = CliRunner()


def test_dev_exposes_schema_command() -> None:
    """The dev group exposes `schema`."""
    names = {c.name for c in dev.app.registered_commands}
    assert "schema" in names


def test_dev_schema_regenerates_and_reports_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`dev schema` writes the model's JSON Schema and echoes where it wrote."""
    out = tmp_path / "schema.json"
    monkeypatch.setattr(dev, "_SCHEMA_PATH", out)
    result = runner.invoke(app, ["dev", "schema"])
    assert result.exit_code == 0
    assert str(out) in result.output
    assert json.loads(out.read_text()) == AppSpec.model_json_schema()
