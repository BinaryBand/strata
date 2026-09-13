"""cli.main: the command-line interface.

Keep it thin -- parse arguments, wire adapters into core use-cases, format results.
Typer is the standard framework: declare commands with @app.command() and describe
any arguments/options with typing.Annotated so `ty` sees real signatures.

Command groups live in cli/commands/, one module each; this file assembles them
and owns only the top-level commands.
"""

from __future__ import annotations

from typing import Annotated

import typer

from strata.cli import gui_server
from strata.cli.commands import config as config_cmds
from strata.cli.commands import dev as dev_cmds
from strata.cli.commands import device as device_cmds
from strata.cli.commands import rclone as rclone_cmds
from strata.cli.dispatch import run_runbook, runbook_completer, show_runbook_list
from strata.cli.picker import pick_runbook
from strata.core import paths

# -- App tree -----------------------------------------------------------

app = typer.Typer(no_args_is_help=True)
app.add_typer(config_cmds.app, name="config")
app.add_typer(rclone_cmds.app, name="rclone")
app.add_typer(device_cmds.app, name="device")
# Maintainer tooling: hidden so it never clutters an operator's --help.
app.add_typer(dev_cmds.app, name="dev", hidden=True)


# -- Callback -----------------------------------------------------------


@app.callback()
def main() -> None:
    """Strata -- Ansible config manager."""


# -- runbook ------------------------------------------------------------


@app.command()
def runbook(
    name: str | None = typer.Argument(
        None,
        help="Runbook module name (e.g. install_jellyfin). "
        "Omit for an interactive picker, or with --list.",
        autocompletion=runbook_completer,
    ),
    target: str | None = typer.Option(
        None,
        "--target",
        "-t",
        help="Ansible inventory hostname to target. Defaults to the last used target.",
    ),
    tags: str | None = typer.Option(
        None,
        "--tags",
        help="Comma-separated tags to narrow scope. Only forwarded to runbooks "
        "whose main() accepts a `tags` argument (e.g. infrastructure.backup).",
    ),
    list_runbooks: Annotated[
        bool,
        typer.Option("--list", "-l", help="List available runbooks grouped by category."),
    ] = False,
) -> None:
    """Run a runbook against a target machine."""
    if list_runbooks:
        show_runbook_list()
        return
    if name is None:
        # Interactive terminals get a category-then-runbook picker; pipes,
        # scripts and CI fall through to the error below unchanged.
        name = pick_runbook()
    if name is None:
        typer.echo(
            "Missing argument 'NAME'. Run with --list to browse available runbooks.",
            err=True,
        )
        raise typer.Exit(1)

    rc = run_runbook(name, target=target, tags=tags)
    raise typer.Exit(rc)


# -- gui ----------------------------------------------------------------


@app.command()
def gui(
    port: Annotated[
        int,
        typer.Option("--port", "-p", help="Loopback port to serve on."),
    ] = 8765,
    no_browser: Annotated[
        bool,
        typer.Option("--no-browser", help="Serve without opening a browser."),
    ] = False,
) -> None:
    """Open the GUI in a browser, serving the runbook catalog on loopback.

    Serves the built Flutter web app plus GET /api/gui-data -- the same
    read-only snapshot `strata dev gui-data` prints -- from one 127.0.0.1 port,
    then opens it. Runs until interrupted.

    Nothing served here executes a runbook: the GUI shows the catalog, its
    guard chains and the inventory, and simulates the rest. Reach it from
    another device on your tailnet with `tailscale serve <port>` -- not
    `tailscale funnel`, which would put a tool that reads the vault and drives
    ansible-runner on the open internet.

    Requires `flutter build web` in gui/ first; this does not build it.
    """
    web_dir = paths.GUI_WEB_BUILD_DIR
    if not web_dir.is_dir():
        typer.echo(
            f"No GUI build at {web_dir}.\n"
            "Build it first:  cd gui && flutter create . && flutter build web",
            err=True,
        )
        raise typer.Exit(1)

    try:
        gui_server.serve(
            web_dir,
            port=port,
            open_browser=not no_browser,
            announce=typer.echo,
        )
    except OSError as exc:
        # Almost always EADDRINUSE -- a second `strata gui`, or anything else
        # already on the port. Name the port rather than showing a traceback.
        typer.echo(f"Could not serve on 127.0.0.1:{port}: {exc}", err=True)
        raise typer.Exit(1) from exc


if __name__ == "__main__":
    app()
