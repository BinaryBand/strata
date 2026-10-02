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
import yaml
from jinja2 import Environment, StrictUndefined

from strata.core import discovery, runbook_module
from tests.playbooks._ansible import PLAYBOOKS_DIR
from tests.playbooks._render import snapshot as snapshot_of

GOLDEN_DIR = Path(__file__).parent / "golden"
APPS = ("baikal", "jellyfin", "minio", "anythingllm", "ollama", "static_agent")


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


@pytest.mark.parametrize(
    ("listener", "handler", "funnel", "allowed"),
    [
        ({}, {}, False, True),
        ({"HTTPS": True}, {"Proxy": "http://127.0.0.1:3001"}, False, True),
        ({"HTTPS": True}, {"Proxy": "http://127.0.0.1:8080"}, False, False),
        ({"HTTPS": True}, {"Path": "/srv/site"}, False, False),
        ({"TCPForward": "127.0.0.1:3001"}, {}, False, False),
        ({"HTTPS": True}, {"Proxy": "http://127.0.0.1:3001"}, True, False),
    ],
)
def test_tailnet_listener_ownership_and_privacy(listener, handler, funnel, allowed) -> None:
    plays = yaml.safe_load((PLAYBOOKS_DIR / "install_podman_app.yml").read_text())
    task = next(
        t
        for t in plays[0]["tasks"]
        if t["name"] == "Refuse another service's listener or a public Funnel"
    )
    env = Environment(undefined=StrictUndefined)
    context = {
        "podman_tailnet_listener": listener,
        "podman_tailnet_handler": handler,
        "podman_tailnet_funnel": funnel,
        "podman_tailnet_backend": "http://127.0.0.1:3001",
    }
    assert (
        all(
            env.compile_expression(condition)(**context)
            for condition in task["ansible.builtin.assert"]["that"]
        )
        is allowed
    )
