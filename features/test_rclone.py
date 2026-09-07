"""pytest-bdd binding for features/rclone.feature (mount remotes + HTTP serves).

Registration state is group_vars-backed, so the real adapter runs against a tmp
managed.yml. Two things are faked: rclone.has_remote (would shell out to
`rclone listremotes`) is driven by an in-memory authorized set, and
dispatch.run_runbook is stubbed so `--apply` records the call instead of running
Ansible.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pytest_bdd import given, parsers, scenarios, then

from strata.adapters.ansible import group_vars, rclone
from strata.cli import dispatch

scenarios("rclone.feature")


@pytest.fixture(autouse=True)
def _isolate_rclone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ctx: dict[str, Any]) -> None:
    monkeypatch.setattr(group_vars, "_GROUP_VARS", tmp_path / "group_vars" / "all" / "managed.yml")

    authorized: set[str] = set()
    monkeypatch.setattr(rclone, "has_remote", authorized.__contains__)
    ctx["authorized"] = authorized

    applied: list[tuple[str, str | None]] = []

    def fake_run_runbook(name: str, target: str | None = None) -> int:
        applied.append((name, target))
        return 0

    monkeypatch.setattr(dispatch, "run_runbook", fake_run_runbook)
    ctx["applied"] = applied


# ── Given ─────────────────────────────────────────────────────────────────


@given(parsers.parse('rclone has an authorized remote "{name}"'))
def authorize_remote(ctx: dict[str, Any], name: str) -> None:
    ctx["authorized"].add(name)


@given(parsers.parse('rclone has no remote named "{name}"'))
def unauthorized_remote(ctx: dict[str, Any], name: str) -> None:
    ctx["authorized"].discard(name)


@given("no remotes are registered")
def no_remotes() -> None:
    """No-op: the isolated managed.yml starts empty."""


@given(parsers.parse('remote "{name}" is registered read-only'))
def seed_remote_ro(name: str) -> None:
    rclone.add_to_config(name)


@given(parsers.parse('remote "{name}" is registered read-write'))
def seed_remote_rw(name: str) -> None:
    rclone.add_to_config(name, writable=True)


@given(parsers.parse('serve "{name}" is registered for "{path}" on port {port:d}'))
def seed_serve(name: str, path: str, port: int) -> None:
    rclone.add_http_serve(name, path, port)


# ── Then ──────────────────────────────────────────────────────────────────


@then(parsers.parse('remote "{name}" is registered read-only'))
def remote_registered_ro(name: str) -> None:
    assert name in rclone.list_remotes()
    assert not rclone.is_writable(name)


@then(parsers.parse('remote "{name}" is registered read-write'))
def remote_registered_rw(name: str) -> None:
    assert name in rclone.list_remotes()
    assert rclone.is_writable(name)


@then(parsers.parse('remote "{name}" is no longer registered'))
def remote_unregistered(name: str) -> None:
    assert name not in rclone.list_remotes()


@then(parsers.parse('"{runbook}" was run against "{target}"'))
def runbook_was_applied(ctx: dict[str, Any], runbook: str, target: str) -> None:
    assert (runbook, target) in ctx["applied"]


@then(parsers.parse('serve "{name}" maps "{path}" to port {port:d}'))
def serve_maps(name: str, path: str, port: int) -> None:
    match = next((s for s in rclone.list_http_serves() if s["name"] == name), None)
    assert match is not None
    assert match["path"] == path
    assert match["port"] == port


@then(parsers.parse('serve "{name}" records base_url "{base_url}"'))
def serve_records_base_url(name: str, base_url: str) -> None:
    match = next(s for s in rclone.list_http_serves() if s["name"] == name)
    assert match.get("base_url") == base_url


@then(parsers.parse('serve "{name}" is no longer registered'))
def serve_unregistered(name: str) -> None:
    assert name not in {s["name"] for s in rclone.list_http_serves()}
