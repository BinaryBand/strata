"""`strata dev`: maintainer-only tooling, hidden from the top-level help.

Registered with ``hidden=True`` so it never clutters an operator's ``--help``;
it is still fully invokable as ``strata dev <command>`` for whoever works on
strata itself.
"""

from __future__ import annotations

import json
from typing import Annotated

import typer

from strata.adapters import gui_token
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

    Read-only declarations only -- install status, guard readiness and
    machine reachability come from `strata gui`'s live /api/* routes instead.
    Useful for inspecting the catalog by hand; `strata.cli.gui_server` is the
    single source both this and `strata gui` read from.
    """
    typer.echo(json.dumps(gui_server.build_gui_data(), indent=2))


@app.command("gui-token")
def dev_gui_token(
    rotate: Annotated[
        bool,
        typer.Option("--rotate", help="Generate a new token, invalidating the old one."),
    ] = False,
) -> None:
    """Print the GUI's access token, generating one first if none exists.

    `strata gui`'s action routes (run a runbook, add a device, set a secret)
    require this as a bearer token. `strata gui` embeds it automatically when
    it opens a browser locally; this is for pasting it into a second device's
    GUI, e.g. one reached over `tailscale serve`.
    """
    token = gui_token.rotate_token() if rotate else gui_token.get_or_create_token()
    typer.echo(token)
