"""Project-root conftest: auto-fix lint before each test session.

Deliberately does NOT run `ruff format`. It used to, and because
pytest_configure fires before any test collects, tests/test_lint.py's
`ruff format --check` was only ever checking formatting this hook had just
applied -- a gate in the file described as the CI/CD gate that could not
fail. Auto-fixing lint is still worth it (the diagnostics that survive
--fix are the ones worth a human's attention), but formatting is left to
`ruff format`, the editor, or CI, so the check that polices it means
something.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def pytest_configure(config: object) -> None:  # noqa: ARG001 -- pytest hook signature
    # Invoke ruff as a module of the interpreter running pytest, not a bare
    # "ruff" on PATH -- PATH only has it when launched via `uv run`, so
    # e.g. VS Code's Python extension running pytest through the venv
    # interpreter directly would otherwise hit FileNotFoundError here.
    subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--fix", str(ROOT)], cwd=ROOT, check=False
    )
