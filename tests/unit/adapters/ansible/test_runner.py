"""Unit tests for strata.adapters.ansible.runner.

``ansible_runner.run`` is replaced with a fake that returns a canned
status/event stream, so no playbook is ever executed. Assertions are about the
arguments handed to ansible-runner, the exit code mapping, and where progress
is written.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any

import pytest

from strata.adapters.ansible import runner
from strata.core import ports


class FakeResult:
    def __init__(
        self,
        status: str = "successful",
        events: list[dict[str, Any]] | None = None,
        stats: dict[str, Any] | None = None,
    ):
        self.status = status
        self.events = events or []
        self.stats = stats


class FakeRunner:
    def __init__(self, result: FakeResult | None = None) -> None:
        self.kwargs: dict[str, Any] = {}
        self.result = result or FakeResult()
        self.calls = 0

    def __call__(self, **kwargs: Any) -> FakeResult:
        self.kwargs = kwargs
        self.calls += 1
        return self.result


class RecordingReporter:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def info(self, message: str) -> None:
        self.messages.append(message)


@pytest.fixture
def fake_ansible(monkeypatch: pytest.MonkeyPatch) -> FakeRunner:
    fake = FakeRunner()
    monkeypatch.setattr(runner.ansible_runner, "run", fake)
    return fake


@pytest.fixture(autouse=True)
def restore_reporter(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the module-level reporter from leaking between tests."""
    monkeypatch.setattr(runner, "_reporter", ports.NullReporter())


def _task_event(task: str, *, changed: bool) -> dict[str, Any]:
    return {"event_data": {"task": task, "res": {"changed": changed}}}


# ── arguments handed to ansible-runner ────────────────────────────────


def test_run_playbook_passes_playbook_and_dirs(fake_ansible: FakeRunner) -> None:
    runner.run_playbook("install_jellyfin.yml")

    assert fake_ansible.kwargs["playbook"] == "install_jellyfin.yml"
    assert fake_ansible.kwargs["project_dir"] == str(runner.ANSIBLE_DIR)
    assert fake_ansible.kwargs["private_data_dir"] == str(runner._DEFAULT_PRIVATE_DATA_DIR)


def test_run_playbook_always_supplies_the_vault_password_file(fake_ansible: FakeRunner) -> None:
    runner.run_playbook("p.yml")
    assert f"--vault-password-file={runner._VAULT_PASS}" in fake_ansible.kwargs["cmdline"]


def test_run_playbook_without_target_does_not_limit(fake_ansible: FakeRunner) -> None:
    runner.run_playbook("p.yml")
    assert "--limit" not in fake_ansible.kwargs["cmdline"]


def test_run_playbook_with_target_limits_to_it(fake_ansible: FakeRunner) -> None:
    runner.run_playbook("p.yml", target="Rpi4")
    assert "--limit Rpi4" in fake_ansible.kwargs["cmdline"]


def test_run_playbook_defaults_the_inventory(fake_ansible: FakeRunner) -> None:
    runner.run_playbook("p.yml")
    assert fake_ansible.kwargs["inventory"] == str(runner._DEFAULT_INVENTORY)


def test_run_playbook_honours_an_inventory_override(
    fake_ansible: FakeRunner, tmp_path: Path
) -> None:
    hosts = tmp_path / "hosts.ini"
    runner.run_playbook("p.yml", inventory=hosts)
    assert fake_ansible.kwargs["inventory"] == str(hosts)


def test_monkeypatched_default_inventory_is_used(
    fake_ansible: FakeRunner, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Tests redirect guard-internal runs by patching the module-level default."""
    monkeypatch.setattr(runner, "_DEFAULT_INVENTORY", tmp_path / "scratch.ini")
    runner.run_playbook("p.yml")
    assert fake_ansible.kwargs["inventory"] == str(tmp_path / "scratch.ini")


def test_extravars_default_to_an_empty_mapping(fake_ansible: FakeRunner) -> None:
    runner.run_playbook("p.yml")
    assert fake_ansible.kwargs["extravars"] == {}


def test_extravars_are_forwarded_including_nested_values(fake_ansible: FakeRunner) -> None:
    extravars = {"media_path": "/mnt/rclone/pcloud/Media", "ports": {"http": 8096}}
    runner.run_playbook("p.yml", extravars=extravars)
    assert fake_ansible.kwargs["extravars"] == extravars


# ── exit code ─────────────────────────────────────────────────────────


def test_successful_status_returns_zero(fake_ansible: FakeRunner) -> None:
    fake_ansible.result = FakeResult(status="successful")
    assert runner.run_playbook("p.yml") == 0


@pytest.mark.parametrize("status", ["failed", "timeout", "canceled", "unknown", ""])
def test_non_successful_status_returns_one(fake_ansible: FakeRunner, status: str) -> None:
    fake_ansible.result = FakeResult(status=status)
    assert runner.run_playbook("p.yml") == 1


def test_no_matched_hosts_is_not_success(fake_ansible: FakeRunner) -> None:
    """A `hosts:` that never intersects --limit exits 0 in ansible; not here.

    This is the mechanism-level guard against a runbook reporting success
    having provisioned nothing -- see runner._matched_no_hosts.
    """
    fake_ansible.result = FakeResult(
        status="successful",
        stats={"ok": {}, "changed": {}, "failures": {}, "dark": {}, "processed": {}},
    )
    assert runner.run_playbook("install_adb.yml", target="Rpi4") == 1


def test_no_matched_hosts_names_the_limit_that_excluded_them(fake_ansible: FakeRunner) -> None:
    fake_ansible.result = FakeResult(status="successful", stats={"processed": {}})
    reporter = RecordingReporter()
    runner.set_reporter(reporter)

    runner.run_playbook("install_adb.yml", target="Rpi4")
    assert any("matched no hosts" in m and "Rpi4" in m for m in reporter.messages)


def test_one_matched_host_is_success_even_when_every_task_skipped(
    fake_ansible: FakeRunner,
) -> None:
    """Skipping every task is a legitimate no-op; matching no host is not."""
    fake_ansible.result = FakeResult(
        status="successful", stats={"ok": {}, "skipped": {"Rpi4": 4}, "processed": {"Rpi4": 1}}
    )
    assert runner.run_playbook("p.yml", target="Rpi4") == 0


def test_absent_stats_leaves_the_exit_code_mapping_alone(fake_ansible: FakeRunner) -> None:
    """A result this cannot judge must not be failed on suspicion."""
    fake_ansible.result = FakeResult(status="successful", stats=None)
    assert runner.run_playbook("p.yml") == 0


def test_failure_is_reported_with_the_status(fake_ansible: FakeRunner) -> None:
    fake_ansible.result = FakeResult(status="failed")
    reporter = RecordingReporter()
    runner.set_reporter(reporter)

    runner.run_playbook("p.yml")
    assert any("status=failed" in m for m in reporter.messages)


# ── reporter ──────────────────────────────────────────────────────────


def test_default_reporter_is_silent(fake_ansible: FakeRunner, capsys: Any) -> None:
    fake_ansible.result = FakeResult(
        status="failed", events=[_task_event("Install jellyfin", changed=True)]
    )
    runner.run_playbook("p.yml")
    assert capsys.readouterr().out == ""


def test_set_reporter_routes_task_progress_to_it(fake_ansible: FakeRunner) -> None:
    fake_ansible.result = FakeResult(
        events=[
            _task_event("Install jellyfin", changed=True),
            _task_event("Check jellyfin", changed=False),
        ]
    )
    reporter = RecordingReporter()
    runner.set_reporter(reporter)

    runner.run_playbook("p.yml")
    assert reporter.messages == ["  [changed] Install jellyfin", "  [ok] Check jellyfin"]


def test_events_without_a_task_or_result_are_skipped(fake_ansible: FakeRunner) -> None:
    fake_ansible.result = FakeResult(
        events=[
            {},
            {"event_data": {}},
            {"event_data": {"task": "No result yet", "res": {}}},
            {"event_data": {"res": {"changed": True}}},
            _task_event("Real task", changed=False),
        ]
    )
    reporter = RecordingReporter()
    runner.set_reporter(reporter)

    runner.run_playbook("p.yml")
    assert reporter.messages == ["  [ok] Real task"]


@pytest.mark.parametrize(
    ("res", "expected"),
    [
        ({"changed": False}, "ok"),
        ({"changed": True}, "changed"),
        ({"skipped": True}, "skipped"),
        ({"failed": True}, "failed"),
        ({"unreachable": True}, "unreachable"),
        # A failed task can still report changed; the failure is what matters.
        ({"failed": True, "changed": True}, "failed"),
        ({"unreachable": True, "failed": True}, "unreachable"),
    ],
)
def test_task_status_distinguishes_outcomes(
    fake_ansible: FakeRunner, res: dict[str, Any], expected: str
) -> None:
    """Every non-changed outcome used to print as [ok], including failures."""
    fake_ansible.result = FakeResult(events=[{"event_data": {"task": "t", "res": res}}])
    reporter = RecordingReporter()
    runner.set_reporter(reporter)

    runner.run_playbook("p.yml")
    assert reporter.messages == [f"  [{expected}] t"]


def test_set_reporter_replaces_the_previous_one(fake_ansible: FakeRunner) -> None:
    fake_ansible.result = FakeResult(events=[_task_event("t", changed=False)])
    first, second = RecordingReporter(), RecordingReporter()
    runner.set_reporter(first)
    runner.set_reporter(second)

    runner.run_playbook("p.yml")
    assert first.messages == []
    assert second.messages == ["  [ok] t"]


def test_module_structurally_satisfies_the_playbook_runner_port() -> None:
    """The executor passes this module in wherever a PlaybookRunner is wanted."""

    port_params = inspect.signature(ports.PlaybookRunner.run_playbook).parameters
    actual = inspect.signature(runner.run_playbook).parameters
    for name in port_params:
        if name != "self":
            assert name in actual


def test_silent_reporter_accepts_a_message_and_returns_none() -> None:
    assert ports.NullReporter().info("anything") is None
