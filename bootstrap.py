#!/usr/bin/env python3
"""Bootstrap a fresh device so the rest of the pipeline can run.

This is the one script that may NOT assume uv or Ansible exist yet — its
job is to install them. It therefore uses only the Python standard library.

Order of operations:
  1. Ensure a recent enough Python (>= 3.12, required by ansible-core).
  2. Ensure pipx.
  3. Ensure uv (installed via pipx, preferred over a global pip install).
  4. `uv sync` the project (pulls ansible-core + ansible-runner).

Everything *after* bootstrap is plain Python + Ansible (see the runbook
subpackages: infrastructure, services, system, etc.).

Usage:
    python bootstrap.py                    # install all prerequisites

It lives at the repo root rather than inside the package because it is not
part of the layered application: it is excluded from runbook discovery, takes
no --target, and must run before the package is installable at all.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, TypedDict

REPO_DIR = Path(__file__).resolve().parent
PYTHON_MIN = (3, 12)  # ansible-core 2.21 requires Python >= 3.12


class PkgManagerSpec(TypedDict):
    """Command vectors for one OS package manager."""

    install: list[str]
    refresh: list[str] | None
    python: list[str]
    pipx: list[str]


PKG_MANAGERS: dict[str, PkgManagerSpec] = {
    "apt": {
        "install": ["sudo", "apt-get", "install", "-y"],
        "refresh": ["sudo", "apt-get", "update", "-qq"],
        "python": ["python3", "python3-venv", "python3-pip"],
        "pipx": ["pipx"],
    },
    "dnf": {
        "install": ["sudo", "dnf", "install", "-y"],
        "refresh": None,
        "python": ["python3", "python3-pip"],
        "pipx": ["pipx"],
    },
    "pacman": {
        "install": ["sudo", "pacman", "-S", "--noconfirm"],
        "refresh": ["sudo", "pacman", "-Sy", "--noconfirm"],
        "python": ["python", "python-pip"],
        "pipx": ["python-pipx"],
    },
    "brew": {
        "install": ["brew", "install"],
        "refresh": None,
        "python": ["python@3.14"],
        "pipx": ["pipx"],
    },
}


def log(msg: str) -> None:
    """Print a progress line."""
    print(f"\033[1;34m==>\033[0m {msg}")


def warn(msg: str) -> None:
    """Print a warning to stderr."""
    print(f"\033[1;33m[warn]\033[0m {msg}", file=sys.stderr)


def die(msg: str) -> None:
    """Print an error to stderr and exit non-zero."""
    print(f"\033[1;31m[error]\033[0m {msg}", file=sys.stderr)
    raise SystemExit(1)


def run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:  # noqa: ANN401
    """Run a command, echoing it first so the bootstrap is auditable."""
    log("$ " + " ".join(cmd))
    return subprocess.run(cmd, check=True, **kwargs)


def have(binary: str) -> bool:
    """Report whether `binary` is already on PATH."""
    return shutil.which(binary) is not None


def detect_pkg_mgr() -> str:
    """Return the name of the host's OS package manager."""
    for mgr in ("apt-get", "dnf", "pacman", "brew"):
        if have(mgr):
            return "apt" if mgr == "apt-get" else mgr
    die("No supported package manager found (need apt, dnf, pacman, or brew).")
    raise AssertionError  # unreachable, keeps type checkers happy


def pkg_install(mgr: str, packages: list[str]) -> None:
    """Install `packages` using package manager `mgr`."""
    spec = PKG_MANAGERS[mgr]
    if spec["refresh"]:
        run(spec["refresh"])
    run([*spec["install"], *packages])


def ensure_python(mgr: str) -> None:
    """Ensure the interpreter is at least PYTHON_MIN, installing it if not."""
    if have("python3"):
        out = subprocess.run(
            [
                "python3",
                "-c",
                "import sys; print(sys.version_info[0], sys.version_info[1])",
            ],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.split()
        version = (int(out[0]), int(out[1]))
        if version >= PYTHON_MIN:
            log(f"Python {version[0]}.{version[1]} OK")
            return
        warn(f"python3 is older than {PYTHON_MIN[0]}.{PYTHON_MIN[1]}; installing a newer one.")
    pkg_install(mgr, PKG_MANAGERS[mgr]["python"])


def ensure_pipx(mgr: str) -> None:
    """Ensure pipx is installed, via the OS package manager."""
    if have("pipx"):
        log("pipx OK")
        return
    pkg_install(mgr, PKG_MANAGERS[mgr]["pipx"])
    run(["pipx", "ensurepath"])
    _add_local_bin_to_path()


def ensure_uv() -> None:
    """Ensure uv is installed, preferring pipx over a global pip install."""
    if have("uv"):
        log("uv OK")
        return
    log("Installing uv via pipx")
    run(["pipx", "install", "uv"])
    _add_local_bin_to_path()
    if not have("uv"):
        die("uv installed but not on PATH. Open a new shell and re-run.")


def _add_local_bin_to_path() -> None:
    """Put ~/.local/bin on PATH for the rest of this process."""
    local_bin = str(Path.home() / ".local" / "bin")
    if local_bin not in os.environ.get("PATH", "").split(os.pathsep):
        os.environ["PATH"] = local_bin + os.pathsep + os.environ.get("PATH", "")


def install_project_deps() -> None:
    """Run `uv sync` to install ansible-core and ansible-runner."""
    log("Installing project dependencies with uv")
    run(["uv", "sync"], cwd=REPO_DIR)


def disable_sleep() -> None:
    """Stop the machine suspending mid-provision."""
    if not have("systemctl"):
        return
    log("Masking sleep/suspend/hibernate targets")
    run(
        [
            "sudo",
            "systemctl",
            "mask",
            "sleep.target",
            "suspend.target",
            "hibernate.target",
            "hybrid-sleep.target",
        ]
    )


def main() -> int:
    """Install every prerequisite the rest of the pipeline assumes."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()

    mgr = detect_pkg_mgr()
    log(f"Detected package manager: {mgr}")

    ensure_python(mgr)
    ensure_pipx(mgr)
    ensure_uv()
    install_project_deps()
    disable_sleep()

    log("Bootstrap complete. The pipeline is ready.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
