"""`strata dev`: maintainer-only tooling, hidden from the top-level help.

Registered with ``hidden=True`` so it never clutters an operator's ``--help``;
it is still fully invokable as ``strata dev <command>`` for whoever works on
strata itself.
"""

from __future__ import annotations

import typer

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
