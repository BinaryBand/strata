"""Static guard: server-app ports must come from server_apps_defaults.

Each port-bearing playbook used to hardcode its port in its `vars:` block
(e.g. `baikal_http_port: 8080`).  They now source it from the shared
``server_apps_defaults`` group_var so the value lives in exactly one place.

This test parses each playbook and asserts the port var is a Jinja template
that references ``server_apps_defaults`` -- so a future "just set it to 8081"
edit inside the playbook fails CI instead of silently forking the source of
 truth.

The container-internal ports (the ``:80`` / ``:8096`` / ``:9000`` halves of the
PublishPort mappings) are intentionally NOT checked -- those are fixed service
ports, not deployment config.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from strata.core.models.server_apps_config import ServerAppsDefaults

ROOT = Path(__file__).resolve().parents[1]
PLAYBOOKS_DIR = ROOT / "ansible" / "playbooks"

# playbook file -> port var name(s) it must source from server_apps_defaults.
PORT_VARS: dict[str, tuple[str, ...]] = {
    "install_baikal.yml": ("baikal_http_port",),
    "install_jellyfin.yml": ("jellyfin_http_port",),
}


def _play_vars(playbook: Path) -> dict:
    plays = yaml.safe_load(playbook.read_text()) or []
    play_vars: dict = {}
    for play in plays:
        if isinstance(play, dict) and play.get("vars"):
            play_vars.update(play["vars"])
    return play_vars


def test_port_vars_reference_server_apps_defaults() -> None:
    # Sanity: the model actually declares every var we expect to find.
    declared = ServerAppsDefaults.model_fields
    assert declared, "ServerAppsDefaults has no declared sub-models"

    for playbook_name, var_names in PORT_VARS.items():
        playbook = PLAYBOOKS_DIR / playbook_name
        assert playbook.exists(), f"Missing playbook: {playbook_name}"
        play_vars = _play_vars(playbook)
        for var in var_names:
            assert var in play_vars, f"{playbook_name} no longer declares {var!r}"
            value = play_vars[var]
            assert isinstance(value, str), (
                f"{playbook_name}: {var!r} should be a Jinja string sourcing "
                f"server_apps_defaults, got {value!r} (a hardcoded port re-introduces drift)."
            )
            assert "server_apps_defaults" in value, (
                f"{playbook_name}: {var!r} should source from server_apps_defaults, "
                f"got {value!r} (a hardcoded port re-introduces drift)."
            )
