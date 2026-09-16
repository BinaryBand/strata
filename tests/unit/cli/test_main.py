"""Root-app CLI tests using typer.testing.CliRunner.

Covers the top-level runbook command and the shape of the app tree. Per-group
behaviour lives in tests/unit/cli/commands/test_<group>.py.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from strata.cli import main
from strata.cli.main import app
from strata.core.discovery import resolve_name

runner = CliRunner()


# -- runbook --list ------------------------------------------------------


def test_runbook_list_shows_categories() -> None:
    result = runner.invoke(app, ["runbook", "--list"])
    assert result.exit_code == 0
    assert "services" in result.output.lower()
    assert "infrastructure" in result.output.lower()
    assert "install_jellyfin" in result.output


def test_runbook_list_shows_docstrings() -> None:
    result = runner.invoke(app, ["runbook", "--list"])
    assert "Runbook:" in result.output


# -- bare-leaf resolution ------------------------------------------------


def test_runbook_bare_leaf_resolves() -> None:
    """A bare leaf name (no dots) resolves to the dotted form."""
    result = resolve_name("install_jellyfin")
    assert result == "services.install_jellyfin"


def test_runbook_dotted_name_resolves() -> None:
    """A dotted name resolves to itself."""
    result = resolve_name("services.install_jellyfin")
    assert result == "services.install_jellyfin"


def test_runbook_unknown_name_returns_none() -> None:
    """A bogus runbook name returns None."""
    assert resolve_name("install_jelyfin") is None


def test_runbook_missing_name_without_list() -> None:
    """Omitting NAME with no tty (CliRunner) still shows the error."""
    result = runner.invoke(app, ["runbook"])
    assert result.exit_code == 1
    assert "Missing argument" in result.output


# -- the interactive picker ----------------------------------------------


def test_runbook_without_name_dispatches_the_picked_runbook(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """On a tty, omitting NAME runs whatever the picker returned."""
    dispatched: list[str] = []
    monkeypatch.setattr(main, "pick_runbook", lambda: "services.install_jellyfin")
    monkeypatch.setattr(main, "run_runbook", lambda name, **_: dispatched.append(name) or 0)
    result = runner.invoke(app, ["runbook"])
    assert result.exit_code == 0
    assert dispatched == ["services.install_jellyfin"]


def test_runbook_aborted_picker_still_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """A picker that returns None falls through to the missing-argument error."""
    monkeypatch.setattr(main, "pick_runbook", lambda: None)
    result = runner.invoke(app, ["runbook"])
    assert result.exit_code == 1
    assert "Missing argument" in result.output


# -- help surface --------------------------------------------------------


def test_config_help_shows_var_secret_vault_password_key() -> None:
    """The config sub-group shows var/secret/vault-password/key."""
    result = runner.invoke(app, ["config", "--help"])
    assert result.exit_code == 0
    assert "var" in result.output.lower()
    assert "secret" in result.output.lower()
    assert "vault-password" in result.output.lower()
    assert "key" in result.output.lower()


def test_rclone_serve_help_shows_add_remove_list() -> None:
    """The rclone serve nested group shows add/remove/list."""
    result = runner.invoke(app, ["rclone", "serve", "--help"])
    assert result.exit_code == 0
    assert "add" in result.output.lower()
    assert "remove" in result.output.lower()
    assert "list" in result.output.lower()


# -- old command names should fail ---------------------------------------


def test_old_var_command_fails() -> None:
    """Old top-level 'var' command no longer exists."""
    result = runner.invoke(app, ["var", "foo"])
    assert result.exit_code != 0


def test_old_rclone_register_fails() -> None:
    """Old 'rclone register' command no longer exists."""
    result = runner.invoke(app, ["rclone", "register", "pcloud"])
    assert result.exit_code != 0


def test_old_rclone_serves_fails() -> None:
    """Old 'rclone serves' command no longer exists."""
    result = runner.invoke(app, ["rclone", "serves"])
    assert result.exit_code != 0


def test_old_rclone_unserve_fails() -> None:
    """Old 'rclone unserve' command no longer exists."""
    result = runner.invoke(app, ["rclone", "unserve", "media"])
    assert result.exit_code != 0


# -- gui -----------------------------------------------------------------


@pytest.fixture
def gui_calls(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    """Record gui_server.serve's kwargs instead of starting a real server."""
    calls: list[dict] = []
    monkeypatch.setattr(main.gui_server, "serve", lambda **kwargs: calls.append(kwargs))
    return calls


def test_gui_serves_the_api_on_the_default_port(gui_calls: list[dict]) -> None:
    result = runner.invoke(app, ["gui"])
    assert result.exit_code == 0
    assert gui_calls == [{"port": 8765, "allow_origins": [], "announce": main.typer.echo}]


def test_gui_forwards_a_custom_port(gui_calls: list[dict]) -> None:
    result = runner.invoke(app, ["gui", "--port", "9000"])
    assert result.exit_code == 0
    assert gui_calls[0]["port"] == 9000


def test_gui_collects_repeated_allow_origin_flags(gui_calls: list[dict]) -> None:
    """The app is served elsewhere now, so its origin is the operator's to name."""
    result = runner.invoke(
        app,
        ["gui", "--allow-origin", "http://box:3000", "--allow-origin", "http://box:4000"],
    )
    assert result.exit_code == 0
    assert gui_calls[0]["allow_origins"] == ["http://box:3000", "http://box:4000"]


def test_gui_reports_a_taken_port_without_a_traceback(monkeypatch: pytest.MonkeyPatch) -> None:
    def _in_use(**_kwargs: object) -> None:
        raise OSError(98, "Address already in use")

    monkeypatch.setattr(main.gui_server, "serve", _in_use)
    result = runner.invoke(app, ["gui", "--port", "9000"])
    assert result.exit_code == 1
    assert "9000" in result.output
    assert "Address already in use" in result.output
