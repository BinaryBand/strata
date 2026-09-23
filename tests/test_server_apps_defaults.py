"""Static guard: server-app deployment values must each have exactly one owner.

Two owners, split by what the value is:

* **Images and published ports** belong to the shared ``server_apps_defaults``
  group_var. Each port- or image-bearing playbook used to hardcode them in its
  own ``vars:`` block (e.g. ``baikal_http_port: 8080``,
  ``jellyfin_image: docker.io/...``); they now source both from the group_var,
  so the value lives in one place and stays overridable per host.
* **Data directories** belong to the runbook that provisions them. The
  directory a ``guard.path`` creates and the directory the container binds have
  to be the same object, so the runbook declares it once and passes it to the
  playbook as an extravar. A playbook re-declaring it in ``vars:`` would fork
  that ownership silently -- the extravar still wins at runtime, so the stale
  literal would sit there looking authoritative.

This test parses each playbook and asserts both halves: the image/port vars are
Jinja templates referencing ``server_apps_defaults``, and no data-directory var
is declared in the play at all.

The container-internal ports (the ``:80`` / ``:8096`` halves of the
PublishPort mappings) are intentionally NOT checked -- those are fixed service
ports, not deployment config.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from strata.core.models.server_apps_config import ServerAppsDefaults
from tests._ansible import PLAYBOOKS_DIR

# playbook file -> vars it must source from server_apps_defaults.
DEFAULTED_VARS: dict[str, tuple[str, ...]] = {
    "install_anythingllm.yml": ("anythingllm_http_port", "anythingllm_image"),
    "install_baikal.yml": ("baikal_http_port", "baikal_image"),
    "install_jellyfin.yml": ("jellyfin_http_port", "jellyfin_image"),
    "install_minio.yml": ("minio_api_port", "minio_console_port", "minio_image"),
}

# playbook file -> vars that must arrive as extravars from the runbook, and so
# must NOT appear in the play's own `vars:` block.
EXTRAVAR_ONLY: dict[str, tuple[str, ...]] = {
    "enable_anythingllm_workshop.yml": ("anythingllm_storage_dir",),
    "install_anythingllm.yml": ("anythingllm_storage_dir", "anythingllm_container_storage_dir"),
    "install_baikal.yml": ("baikal_data_dir",),
    "install_jellyfin.yml": ("jellyfin_config_dir", "jellyfin_cache_dir"),
    "install_minio.yml": ("minio_data_dir",),
}


def _play_vars(playbook: Path) -> dict:
    plays = yaml.safe_load(playbook.read_text()) or []
    play_vars: dict = {}
    for play in plays:
        if isinstance(play, dict) and play.get("vars"):
            play_vars.update(play["vars"])
    return play_vars


def test_defaulted_vars_reference_server_apps_defaults() -> None:
    # Sanity: the model actually declares every sub-model we expect to find.
    declared = ServerAppsDefaults.model_fields
    assert declared, "ServerAppsDefaults has no declared sub-models"

    for playbook_name, var_names in DEFAULTED_VARS.items():
        playbook = PLAYBOOKS_DIR / playbook_name
        assert playbook.exists(), f"Missing playbook: {playbook_name}"
        play_vars = _play_vars(playbook)
        for var in var_names:
            assert var in play_vars, f"{playbook_name} no longer declares {var!r}"
            value = play_vars[var]
            assert isinstance(value, str), (
                f"{playbook_name}: {var!r} should be a Jinja string sourcing "
                f"server_apps_defaults, got {value!r} (a hardcoded value re-introduces drift)."
            )
            assert "server_apps_defaults" in value, (
                f"{playbook_name}: {var!r} should source from server_apps_defaults, "
                f"got {value!r} (a hardcoded value re-introduces drift)."
            )


def test_model_declares_every_defaulted_field() -> None:
    """Every var sourced from server_apps_defaults must exist on the model.

    The playbooks reference `server_apps_defaults.<app>.<field>`; the model is
    what validates the YAML and generates the editor schema. Without this, a
    playbook could reference a field nobody declares and fail only at run time,
    on the target, mid-play.
    """
    for playbook_name, var_names in DEFAULTED_VARS.items():
        play_vars = _play_vars(PLAYBOOKS_DIR / playbook_name)
        for var in var_names:
            reference = play_vars[var]
            _, _, tail = reference.partition("server_apps_defaults.")
            app, _, field = tail.strip(" }").partition(".")
            app_model = ServerAppsDefaults.model_fields.get(app)
            assert app_model is not None, (
                f"{playbook_name}: {var!r} references unknown app {app!r} on ServerAppsDefaults"
            )
            assert field in app_model.annotation.model_fields, (
                f"{playbook_name}: {var!r} references {app}.{field!r}, "
                f"which {app_model.annotation.__name__} does not declare"
            )


def test_data_dirs_are_not_declared_in_playbooks() -> None:
    """Data directories arrive as extravars, so the play must not re-declare them."""
    for playbook_name, var_names in EXTRAVAR_ONLY.items():
        play_vars = _play_vars(PLAYBOOKS_DIR / playbook_name)
        for var in var_names:
            assert var not in play_vars, (
                f"{playbook_name}: {var!r} is declared in the play's vars, but it is owned "
                f"by the runbook and passed as an extravar. The extravar wins at runtime, so "
                f"this literal is a stale second spelling of the path the guard provisions."
            )
