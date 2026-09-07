"""Runs real runbooks against a disposable Podman container standing in for
a fresh machine, via real ansible-runner/ansible-vault (see conftest.py).

check() can't be reused to verify success here -- every check() in this
codebase inspects the *local* machine (shutil.which, pwd.getpwnam), which is
only meaningful for the real ansible_connection=local host. Each case below
instead supplies its own `podman exec <container> <probe>` command.
"""

from __future__ import annotations

import importlib
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field

import pytest

from strata.adapters.ansible import runner

pytestmark = pytest.mark.integration


@dataclass
class RunbookCase:
    module: str
    expect_success: bool
    secrets: dict[str, str] = field(default_factory=dict)
    verify: list[str] | None = None  # podman exec argv, run only on success


CASES = [
    RunbookCase(
        module="package_managers.install_flatpak",
        expect_success=True,
        verify=["which", "flatpak"],
    ),
    RunbookCase(
        module="package_managers.install_homebrew",
        expect_success=True,
        verify=["test", "-x", "/home/linuxbrew/.linuxbrew/bin/brew"],
    ),
    RunbookCase(
        module="infrastructure.install_podman",
        expect_success=True,
        verify=["which", "podman"],
    ),
]


@pytest.mark.parametrize("case", CASES, ids=[c.module for c in CASES])
def test_runbook_against_fresh_container(
    case: RunbookCase, podman_container: str, vault_seed: Callable[..., None]
) -> None:
    vault_seed(**case.secrets)
    module = importlib.import_module(f"strata.core.runbooks.{case.module}")

    # `runner` is keyword-only and required since adapters became injected;
    # calling main() with target alone -- as this did -- is a TypeError. The
    # executor supplies it by inspecting the signature, but this suite bypasses
    # the executor deliberately (it wants the playbook to really run), so it
    # has to hand the adapter in itself.
    exit_code = module.main(target=podman_container, runner=runner)

    if case.expect_success:
        assert exit_code == 0, f"{case.module} failed against a fresh container"
        if case.verify:
            subprocess.run(["podman", "exec", podman_container, *case.verify], check=True)
    else:
        assert exit_code != 0, (
            f"{case.module} unexpectedly succeeded -- if a guard was added to "
            f"close this gap, remove its KNOWN_GAPS entry in "
            f"tests/test_guard_completeness.py and flip expect_success here"
        )
