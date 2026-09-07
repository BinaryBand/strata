"""Runbook: install CLI apps from local git repos via pipx.

App locations are listed in static/git_apps.toml.  Running this runbook
reinstalls every listed app (clean rebuild each time, picking up source
changes from the sibling repo).

Only apps installed via pipx from a local git checkout belong here --
system packages, Flatpaks, and Homebrew formulae have their own runbooks.
"""

import shutil
import tomllib

from strata.core import guard, paths
from strata.core.ports import PlaybookRunner, Reporter

_APPS_TOML = paths.STATIC_DIR / "git_apps.toml"


def _load_apps() -> list[dict[str, str]]:
    """Return the list of app dicts from the TOML, or [] if absent/empty."""
    if not _APPS_TOML.exists():
        return []
    with _APPS_TOML.open("rb") as f:
        data = tomllib.load(f)
    return list(data.get("apps", []))


def check() -> bool:
    """Return True if every listed app's binary is already on PATH."""
    return all(shutil.which(app["name"]) is not None for app in _load_apps())


@guard.alias("install git apps")
@guard.controller_only(
    "these are the operator's own pipx-installed CLI apps, listed in static/git_apps.toml."
)
@guard.requires("package_managers.install_homebrew")
def main(
    target: str | None = None,
    *,
    runner: PlaybookRunner,
    reporter: Reporter,
) -> int:
    """Reinstall each app listed in static/git_apps.toml with pipx.

    Stops at the first failing app and returns that playbook's exit code; returns 0
    when the TOML lists no apps.
    """
    apps = _load_apps()
    if not apps:
        reporter.info(f"No apps listed in {_APPS_TOML}, nothing to install.")
        return 0

    for app in apps:
        exit_code = runner.run_playbook(
            "playbooks/install_from_git.yml",
            extravars={"app_name": app["name"], "app_repo": app["repo"]},
            target=target,
        )
        if exit_code != 0:
            return exit_code
    return 0
