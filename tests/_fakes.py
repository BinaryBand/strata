"""Fakes shared across the unit and feature suites."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
import yaml

from strata.adapters.ansible import secrets
from strata.core import discovery
from strata.core.models import Device


class RecordingPlaybookRunner:
    """Records each `run_playbook` call instead of running Ansible (`ports.PlaybookRunner`)."""

    def __init__(self, rc: int = 0) -> None:
        self.rc = rc
        self.calls: list[tuple[str, dict[str, Any], str | None]] = []

    def run_playbook(
        self,
        playbook: str,
        extravars: Mapping[str, Any] | None = None,
        target: str | None = None,
    ) -> int:
        self.calls.append((playbook, dict(extravars or {}), target))
        return self.rc


SOURCE_MANIFEST: dict[str, Any] = {
    "schema": 1,
    "name": "demo",
    "alias": "install Demo",
    "description": "Demo service",
    "toolchain": "uv",
    "build": "uv sync --frozen",
    "run": {"command": "uv run --no-sync demo serve --host ${DEMO_HOST}", "env": {"MODE": "prod"}},
    "dirs": [
        {"path": "/srv/demo"},
        {"path": "/srv/demo/data"},
        {"path": "/srv/demo/config", "mode": "2750"},
    ],
    "secrets": [
        {"name": "demo_host", "kind": "text", "prompt": "Host", "env": "DEMO_HOST"},
        {"name": "demo_key", "prompt": "API key", "file": "/srv/demo/config/key"},
    ],
    "backup": {"tag": "demo", "path": "/srv/demo/data"},
}


# SOURCE_MANIFEST mounted on the tailnet: the command takes the host's name as strata hands it.
TAILNET_MANIFEST: dict[str, Any] = {
    **SOURCE_MANIFEST,
    "run": {
        "command": "uv run --no-sync demo serve --port 8123 --allow-host ${STRATA_TAILNET_HOST}",
        "env": {"MODE": "prod"},
    },
    "tailnet": {"path": "/demo", "port": 8123},
}


def write_project(directory: Path, **overrides: Any) -> Path:
    """Create a project at `directory` whose strata.app.yml is SOURCE_MANIFEST plus overrides."""
    directory.mkdir(parents=True, exist_ok=True)
    manifest = {**SOURCE_MANIFEST, **overrides}
    (directory / "strata.app.yml").write_text(yaml.safe_dump(manifest, sort_keys=False))
    return directory


def register_projects(file: Path, *directories: Path) -> None:
    """Write `directories` to the project list at `file`, as ansible/projects.yml holds them."""
    file.write_text("projects:\n" + "".join(f"  - {d}\n" for d in directories))


class FakePrompter:
    """Records every question and answers from a script, satisfying `ports.Prompter`.

    Answers are consumed in order; once they run out it behaves like a terminal
    where the operator just presses Enter, returning the default or "".
    """

    def __init__(self, answers: list[str] | None = None) -> None:
        self.answers = list(answers or [])
        self.asked: list[dict[str, object]] = []
        self.told: list[str] = []

    def ask(self, message: str, *, default: str | None = None, hidden: bool = False) -> str:
        self.asked.append({"message": message, "default": default, "hidden": hidden})
        if self.answers:
            return self.answers.pop(0)
        return default or ""

    def tell(self, message: str) -> None:
        self.told.append(message)


def remote_device(name: str) -> Device:
    """A registered ssh host that is not the controller, whatever it is called."""
    return Device(name=name, host="10.0.0.9", user="root", connection="ssh")


def fake_vault(
    monkeypatch: pytest.MonkeyPatch, store: dict[str, str] | None = None
) -> dict[str, str]:
    """Back the secrets adapter with an in-memory `store`, and return it.

    The vault password lives in the OS keychain, which no caller of this is
    about to test, so asking for a missing one is a no-op here.
    """
    vault = {} if store is None else store
    monkeypatch.setattr(secrets, "has_secret", vault.__contains__)
    monkeypatch.setattr(secrets, "get_secret", vault.get)
    monkeypatch.setattr(secrets, "set_secret", vault.__setitem__)
    monkeypatch.setattr(secrets, "ensure_vault_password", lambda _prompter: None)
    return vault


def fail_import(monkeypatch: pytest.MonkeyPatch, dotted: str) -> None:
    """Make importing the runbook module `dotted` (relative to strata.core.runbooks) raise."""
    real_import = discovery.importlib.import_module
    broken = f"strata.core.runbooks.{dotted}"

    def flaky(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == broken:
            msg = "simulated import failure"
            raise ImportError(msg)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(discovery.importlib, "import_module", flaky)
