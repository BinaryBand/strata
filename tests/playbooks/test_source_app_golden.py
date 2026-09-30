"""Golden snapshot of what an external project deploys, independent of how it is declared.

The counterpart of test_server_app_golden.py for a project that ships a
strata.app.yml: the guards, backup tag, role vars and rendered systemd unit of a
fixed demo manifest, pinned so a change to the manifest model, the builder or
the unit template is a deliberate edit to a snapshot.

Regenerate the snapshot only for a change meant to alter the deployed unit:

    UPDATE_GOLDEN=1 uv run pytest tests/playbooks/test_source_app_golden.py
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import cast

import yaml

from strata.core import source_runbook
from strata.core.models import SourceAppSpec
from tests._fakes import SOURCE_MANIFEST, TAILNET_MANIFEST
from tests.playbooks._ansible import PLAYBOOKS_DIR, iter_tasks
from tests.playbooks._render import TEMPLATES_DIR
from tests.playbooks._render import snapshot as snapshot_of

GOLDEN = Path(__file__).parent / "golden" / "demo_source.json"
GOLDEN_TAILNET = Path(__file__).parent / "golden" / "demo_source_tailnet.json"
_SPEC = SourceAppSpec.model_validate(SOURCE_MANIFEST)
_TAILNET_SPEC = SourceAppSpec.model_validate(TAILNET_MANIFEST)
_PROJECT = Path("/home/you/Dev/demo")
# What the play reads from `tailscale status` on the host; a fixed stand-in for the snapshot.
_TAILNET_FACTS = {"tailnet_host": "demo-host.example.ts.net"}


def test_source_app_matches_golden() -> None:
    module = source_runbook.build(_SPEC, _PROJECT)
    snapshot = snapshot_of(module, content_var="service_content", content_key="unit")
    if os.environ.get("UPDATE_GOLDEN"):
        GOLDEN.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n")
    assert json.loads(GOLDEN.read_text()) == snapshot


def test_a_source_app_on_the_tailnet_matches_golden() -> None:
    module = source_runbook.build(_TAILNET_SPEC, _PROJECT)
    snapshot = snapshot_of(
        module, content_var="service_content", content_key="unit", facts=_TAILNET_FACTS
    )
    if os.environ.get("UPDATE_GOLDEN"):
        GOLDEN_TAILNET.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n")
    assert json.loads(GOLDEN_TAILNET.read_text()) == snapshot


def test_the_play_sets_the_facts_the_unit_reads() -> None:
    """The unit reads `tailnet_host`, which only the play can know; the golden fakes it."""
    tasks = iter_tasks(yaml.safe_load((PLAYBOOKS_DIR / "install_source_app.yml").read_text()))
    set_facts = {
        name
        for task in tasks
        for name in cast(
            "dict[str, object]", task.get("ansible.builtin.set_fact") or task.get("set_fact") or {}
        )
    }
    assert set(_TAILNET_FACTS) <= set_facts


def test_the_play_and_unit_read_only_what_the_builder_hands_them() -> None:
    """A key the play reads that the payload lacks fails on a host, not in the golden.

    The golden renders the role vars and the unit; the tasks around them (the
    archive, the build, the secret files) are never rendered here, so the keys
    they read are checked against the payload directly.
    """
    payload = source_runbook._payload(_SPEC, _PROJECT)
    text = (PLAYBOOKS_DIR / "install_source_app.yml").read_text()
    text += (TEMPLATES_DIR / "source_app.service.j2").read_text()
    read = set(re.findall(r"source_app\.(\w+)\b(?!\.j2)", text)) - {"items"}
    assert read <= set(payload), sorted(read - set(payload))


def test_only_a_project_on_the_tailnet_needs_tailscale_and_nothing_else_uses_it() -> None:
    """The tailscale tasks are all conditional on `tailnet`, which the completeness gate skips.

    An unconditional use would be seen by that gate and demand a guard of every project.
    """
    from tests.playbooks.test_guard_completeness import _tools_used  # noqa: PLC0415

    playbook = PLAYBOOKS_DIR / "install_source_app.yml"
    assert _tools_used(playbook) == set()
    assert "when: source_app.tailnet | default(none) is not none" in playbook.read_text()
