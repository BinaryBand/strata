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

from strata.core import source_runbook
from strata.core.models import SourceAppSpec
from tests._fakes import SOURCE_MANIFEST
from tests.playbooks._ansible import PLAYBOOKS_DIR
from tests.playbooks._render import TEMPLATES_DIR
from tests.playbooks._render import snapshot as snapshot_of

GOLDEN = Path(__file__).parent / "golden" / "demo_source.json"
_SPEC = SourceAppSpec.model_validate(SOURCE_MANIFEST)


def test_source_app_matches_golden() -> None:
    module = source_runbook.build(_SPEC, Path("/home/you/Dev/demo"))
    snapshot = snapshot_of(module, content_var="service_content", content_key="unit")
    if os.environ.get("UPDATE_GOLDEN"):
        GOLDEN.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n")
    assert json.loads(GOLDEN.read_text()) == snapshot


def test_the_play_and_unit_read_only_what_the_builder_hands_them() -> None:
    """A key the play reads that the payload lacks fails on a host, not in the golden.

    The golden renders the role vars and the unit; the tasks around them (the
    archive, the build, the secret files) are never rendered here, so the keys
    they read are checked against the payload directly.
    """
    payload = source_runbook._payload(_SPEC, Path("/home/you/Dev/demo"))
    text = (PLAYBOOKS_DIR / "install_source_app.yml").read_text()
    text += (TEMPLATES_DIR / "source_app.service.j2").read_text()
    read = set(re.findall(r"source_app\.(\w+)\b(?!\.j2)", text)) - {"items"}
    assert read <= set(payload), sorted(read - set(payload))
