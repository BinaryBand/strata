"""Golden snapshots of what each server app deploys, independent of how it is declared.

The behaviour that matters to the host is narrower than the source that declares
it: which guards run in which order, which backup tag covers which path, and the
Quadlet unit the role writes. This module pins exactly those, so a change to a
spec or to the unit template shows up as a deliberate edit to a snapshot.

The Quadlet is rendered the way Ansible would render it (tests/playbooks/_render.py).

Regenerate a snapshot only for a change meant to alter the deployed unit:

    UPDATE_GOLDEN=1 uv run pytest tests/playbooks/test_server_app_golden.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from strata.core import discovery, runbook_module
from tests.playbooks._render import snapshot as snapshot_of

GOLDEN_DIR = Path(__file__).parent / "golden"
APPS = ("baikal", "jellyfin", "minio")


@pytest.mark.parametrize("app", APPS)
def test_server_app_matches_golden(app: str) -> None:
    snapshot = snapshot_of(
        discovery.load(runbook_module.dotted_name(app)),
        content_var="quadlet_content",
        content_key="quadlet",
    )
    golden = GOLDEN_DIR / f"{app}.json"
    if os.environ.get("UPDATE_GOLDEN"):
        GOLDEN_DIR.mkdir(exist_ok=True)
        golden.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n")
    assert json.loads(golden.read_text()) == snapshot
