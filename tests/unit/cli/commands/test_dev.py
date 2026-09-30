"""Unit tests for the hidden `strata dev` maintainer group."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from strata.cli.commands import dev
from strata.cli.main import app
from strata.core.models import AppSpec, ServerAppsDefaults

runner = CliRunner()


def test_dev_exposes_schema_command() -> None:
    """The dev group exposes `schema`."""
    names = {c.name for c in dev.app.registered_commands}
    assert "schema" in names


def test_dev_schema_regenerates_and_reports_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`dev schema` writes each model's JSON Schema and echoes where it wrote."""
    monkeypatch.setattr(dev, "_VSCODE_DIR", tmp_path)
    result = runner.invoke(app, ["dev", "schema"])
    assert result.exit_code == 0
    for name, model in (
        ("server_apps_schema.json", ServerAppsDefaults),
        ("app_spec_schema.json", AppSpec),
    ):
        assert str(tmp_path / name) in result.output
        assert json.loads((tmp_path / name).read_text()) == model.model_json_schema()
