"""Fixtures for the container-backed integration suite.

Both fixtures used to be unconditional skips, so `pytest -m integration`
reported "not implemented yet" and the three cases in
test_runbooks_container.py had never executed. They are real now.

The shape:

  * `podman_container` starts one disposable systemd-enabled container per
    session and writes a *scratch* inventory naming it. Nothing here touches
    ansible/inventory/hosts.ini -- a bug in this suite must not be able to
    rewrite the operator's real inventory or aim a playbook at a real host.
  * `vault_seed` writes vault-encrypted vars into that scratch inventory's
    group_vars/secrets/all.yml under a throwaway password, and points the
    runner's --vault-password-file at a temp script that echoes it. The real
    password lives in the OS keychain and is read by ansible/vault_pass.py in
    a *child* process, so it cannot be monkeypatched in-process -- redirecting
    the file the runner names is the seam that works.

The container is put in the `local` group because install_flatpak.yml is
`hosts: local`; the other two cases are `hosts: all`. It also joins
`secrets:children` so the vaulted vars load for it.

PID 1 is `sleep infinity`, not systemd: all three cases are package installs
and none needs a running init. A runbook that enables lingering or installs a
Quadlet unit (create_diot_user, the server apps) does need systemd as PID 1 and
a systemd-bearing image -- adding one of those to CASES means revisiting this
fixture, not just the case list.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from ansible.parsing.vault import VaultLib, VaultSecret

from strata.adapters.ansible import runner

# Debian-family: every playbook under test branches on
# `ansible_facts.pkg_mgr == 'apt'` for its cache refresh.
_IMAGE = "docker.io/library/ubuntu:24.04"
_VAULT_PASSWORD = "integration-suite-throwaway"
_CONTAINER_USER = "mrmgr"
# The fixture returns one name used as BOTH the inventory hostname and the
# podman container name -- test_runbooks_container.py verifies its result with
# `podman exec <podman_container> ...`, so the two cannot diverge.


def _podman(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["podman", *args], check=check, capture_output=True, text=True)


@pytest.fixture(scope="session")
def _container_id() -> Iterator[str]:
    """One disposable container for the whole session."""
    if shutil.which("podman") is None:
        pytest.skip("podman is not installed")

    name = f"strata-it-{uuid.uuid4().hex[:8]}"
    # PID 1 is sleep, not systemd: every case in CASES is a package install
    # and none needs a running init. See this module's docstring before adding
    # a case that does.
    created = _podman("run", "-d", "--name", name, _IMAGE, "sleep", "infinity", check=False)
    if created.returncode != 0:
        # A failed `podman run` still leaves a container record behind (Created
        # or Exited), and this skip is outside the try/finally below -- so tidy
        # up here or the strays accumulate one per failed run.
        _podman("rm", "-f", name, check=False)
        pytest.skip(f"could not start the {_IMAGE} container: {created.stderr.strip()}")

    try:
        # A non-root user with passwordless sudo, not root: this mirrors the
        # real targets (operator on workstation, nas on nas), makes `become: true`
        # mean something, and is required by install_homebrew -- Homebrew's
        # installer refuses to run as root. curl/git/file/procps are the
        # installer's own prerequisites; without curl the playbook's
        # `bash -c "$(curl ...)"` silently expands to nothing and the task
        # reports success having installed no brew.
        bootstrap = _podman(
            "exec",
            name,
            "bash",
            "-lc",
            "apt-get update -qq "
            "&& apt-get install -y -qq python3 sudo curl git ca-certificates file procps "
            ">/dev/null "
            f"&& useradd -m -s /bin/bash {_CONTAINER_USER} "
            f"&& echo '{_CONTAINER_USER} ALL=(ALL) NOPASSWD:ALL' "
            f">/etc/sudoers.d/{_CONTAINER_USER}",
            check=False,
        )
        if bootstrap.returncode != 0:
            pytest.skip(
                f"could not bootstrap python3/sudo in the container: {bootstrap.stderr[-400:]}"
            )
        yield name
    finally:
        _podman("rm", "-f", name, check=False)


@pytest.fixture(scope="session")
def _scratch_inventory(_container_id: str, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A throwaway inventory naming the container, never the real hosts.ini."""
    root = tmp_path_factory.mktemp("it-inventory")
    inventory = root / "inventory"
    (inventory / "group_vars" / "all").mkdir(parents=True)
    (inventory / "group_vars" / "secrets").mkdir(parents=True)

    (inventory / "hosts.ini").write_text(
        "[all]\n\n"
        "[local]\n"
        f"{_container_id} ansible_host={_container_id} "
        "ansible_connection=containers.podman.podman "
        f"ansible_user={_CONTAINER_USER} ansible_become=true\n\n"
        "[remote]\n\n"
        "[secrets:children]\n"
        "local\n"
        "remote\n"
    )
    # An empty managed.yml so playbooks that reference the CLI-maintained lists
    # (rclone_remotes and friends) see them absent rather than inheriting the
    # operator's real ones.
    (inventory / "group_vars" / "all" / "managed.yml").write_text("---\n")
    (inventory / "group_vars" / "secrets" / "all.yml").write_text("---\n")
    return inventory


@pytest.fixture
def podman_container(
    _container_id: str,
    _scratch_inventory: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> str:
    """Inventory hostname of a disposable container standing in for a fresh machine."""
    vault_pass_script = tmp_path / "vault_pass.py"
    vault_pass_script.write_text(f'#!/usr/bin/env python3\nprint("{_VAULT_PASSWORD}")\n')
    vault_pass_script.chmod(0o755)

    # Both are module-level in runner precisely so a suite can redirect them.
    monkeypatch.setattr(runner, "_DEFAULT_INVENTORY", _scratch_inventory / "hosts.ini")
    monkeypatch.setattr(runner, "_VAULT_PASS", vault_pass_script)
    # A private_data_dir of its own, so a run here cannot leave env/extravars
    # behind for the operator's next real run.
    private = tmp_path / "runner"
    (private / "env").mkdir(parents=True)
    monkeypatch.setattr(runner, "_DEFAULT_PRIVATE_DATA_DIR", private)
    monkeypatch.setenv("ANSIBLE_ROLES_PATH", str(Path.cwd() / "ansible" / "roles"))
    return _container_id


@pytest.fixture
def vault_seed(_scratch_inventory: Path) -> Callable[..., None]:
    """Seed the scratch vault with the secrets a case's guards will demand."""
    secrets_file = _scratch_inventory / "group_vars" / "secrets" / "all.yml"

    def seed(**values: str) -> None:
        vault = VaultLib([(_VAULT_PASSWORD, VaultSecret(_VAULT_PASSWORD.encode()))])
        lines = ["---"]
        for name, value in values.items():
            body = vault.encrypt(value.encode()).decode()
            indented = "\n".join(" " * 10 + line for line in body.splitlines())
            lines.append(f"{name}: !vault |\n{indented}")
        secrets_file.write_text("\n".join(lines) + "\n")

    return seed


def pytest_configure(config: pytest.Config) -> None:  # noqa: ARG001
    # ansible-runner shells out; keep its own venv discovery off our back.
    os.environ.setdefault("ANSIBLE_HOST_KEY_CHECKING", "False")
