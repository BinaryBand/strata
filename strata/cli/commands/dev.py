"""`strata dev`: maintainer-only tooling, hidden from the top-level help.

Registered with ``hidden=True`` so it never clutters an operator's ``--help``;
it is still fully invokable as ``strata dev <command>`` for whoever works on
strata itself.
"""

from __future__ import annotations

import json

import typer

from strata.cli import gui_server
from strata.core.models import ServerAppsDefaults

app = typer.Typer(
    no_args_is_help=True,
    help="Maintainer tooling (not shown in the top-level help).",
)


@app.command("schema")
def dev_schema() -> None:
    """Write the JSON Schema for server_apps_defaults.yml to .vscode/.

    Regenerates .vscode/server_apps_schema.json from the Pydantic model at
    strata/core/models/server_apps_config.py.  VS Code yaml.schemas points at
    that file, so editing the YAML gets intellisense and validation.
    Run this any time you change the model structure.
    """
    out_path = ServerAppsDefaults.write_schema()
    typer.echo(f"Wrote schema to {out_path}")


@app.command("gui-data")
def dev_gui_data() -> None:
    """Print a JSON snapshot of the runbook catalog and device inventory.

    This is what gui/ shells out to (`strata dev gui-data`) on desktop to
    replace its mock runbook/device lists with the real catalog -- install
    status and machine reachability are not in scope here, only the static
    declarations. `strata gui` serves the same snapshot over HTTP for the web
    build; both read it from strata.cli.gui_server.
    """
    typer.echo(json.dumps(gui_server.build_gui_data(), indent=2))
