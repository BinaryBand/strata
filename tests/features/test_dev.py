"""pytest-bdd binding for tests/features/dev.feature (the hidden `strata dev` group).

Steps here are specific to dev.feature; the reusable `I run "strata ..."` /
exit-code / output-contains steps come from tests/features/conftest.py.
"""

from __future__ import annotations

import json
import re
from typing import Any

from pytest_bdd import given, parsers, scenarios, then

from strata.core import paths
from strata.core.models import AppSpec, SourceAppSpec

scenarios("dev.feature")

_VSCODE_DIR = paths.PROJECT_ROOT / ".vscode"
_SCHEMA_PATH = _VSCODE_DIR / "app_spec_schema.json"


def _listed_as_word(output: str, name: str) -> bool:
    """Whether `name` appears as a whole word in help output.

    Word boundaries matter: a naive ``"dev" in output`` matches "device" and
    "devices", so a hidden `dev` command would look present when it is not.
    """
    return re.search(rf"\b{re.escape(name)}\b", output) is not None


@then(parsers.parse('the Commands panel does not list "{name}"'))
def commands_panel_excludes(ctx: dict[str, Any], name: str) -> None:
    assert not _listed_as_word(ctx["result"].output, name)


@then(parsers.parse('it does not list "{first}" or "{second}" either'))
def not_listed_either(ctx: dict[str, Any], first: str, second: str) -> None:
    out = ctx["result"].output
    assert not _listed_as_word(out, first)
    assert not _listed_as_word(out, second)


@then(parsers.parse('"{name}" is listed as a command'))
def listed_as_command(ctx: dict[str, Any], name: str) -> None:
    assert _listed_as_word(ctx["result"].output, name)


@given("I have not changed the AppSpec model")
def model_unchanged() -> None:
    """No-op: the committed model is the baseline this scenario compares against."""


@then(".vscode/app_spec_schema.json is written from the AppSpec model")
def schema_written_from_model(ctx: dict[str, Any]) -> None:
    assert ctx["result"].exit_code == 0
    assert json.loads(_SCHEMA_PATH.read_text()) == AppSpec.model_json_schema()


@then(".vscode/source_app_schema.json is written from the SourceAppSpec model")
def source_schema_written_from_model() -> None:
    written = json.loads((_VSCODE_DIR / "source_app_schema.json").read_text())
    assert written == SourceAppSpec.model_json_schema()


@then("the output reports the path it wrote")
def output_reports_path(ctx: dict[str, Any]) -> None:
    assert "app_spec_schema.json" in ctx["result"].output


@then("the written schema is byte-identical to the committed one")
def schema_byte_identical() -> None:
    expected = json.dumps(AppSpec.model_json_schema(), indent=2, sort_keys=True) + "\n"
    assert _SCHEMA_PATH.read_text() == expected
