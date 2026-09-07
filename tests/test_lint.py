"""CI/CD gate: fail the suite when a linter, type checker, or dead-code scanner reports issues."""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "strata"
TESTS = ROOT / "tests"
# The mirrored, per-layer unit tests live under tests/unit/, leaving the rest of
# tests/ (e.g. tests/integration/) free for categories the mirror check does not
# police.
UNIT_TESTS = TESTS / "unit"

# No ruff rule caps file length; this is the single most effective knob for
# keeping modules navigable, so enforce it here.
MAX_MODULE_LINES = 400

# Source modules that never need a dedicated mirror test: the package/CLI entry
# shims and the pure Protocol interface module.
MIRROR_EXEMPT = {"__main__.py", "ports.py"}

# Package directories covered collectively rather than module-by-module.
# runbooks/: test_guard_completeness walks every runbook and cross-checks its
#   declared guard chain against the tools its playbook actually shells out to,
#   and test_discovery imports all of them. A per-runbook file would restate
#   the same two assertions 21 times.
# models/: single-field pydantic declarations. A test per model would assert
#   the field list back at itself; the one model with behaviour
#   (ServerAppsDefaults) is covered by test_server_apps_ports.
MIRROR_EXEMPT_DIRS = {"runbooks", "models"}
# Console scripts (ruff, ty, vulture, lint-imports) live alongside whatever
# interpreter is running pytest. Resolving them here instead of relying on a
# bare name via PATH means these tests work whether launched with
# `uv run pytest` (PATH has the venv's bin/) or by an editor's test
# runner invoking the venv's python directly (PATH may not).
_BIN = Path(sys.executable).parent


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(_BIN / cmd[0]), *cmd[1:]],
        capture_output=True,
        text=True,
        cwd=ROOT,
        env={**os.environ, "VIRTUAL_ENV": str(ROOT / ".venv")},
        check=False,
    )


def test_ruff_check() -> None:
    """ruff check must produce zero diagnostics after auto-fix."""
    result = _run(["ruff", "check", str(ROOT)])
    assert result.returncode == 0, (
        f"ruff check failed (exit {result.returncode}):\n\n{result.stdout}\n{result.stderr}"
    )


def test_ruff_format() -> None:
    """ruff format --check must report no reformats needed."""
    result = _run(["ruff", "format", "--check", str(ROOT)])
    assert result.returncode == 0, (
        f"ruff format --check found unformatted files "
        f"(exit {result.returncode}):\n\n{result.stdout}"
    )


def test_ty_check() -> None:
    """ty check must produce zero diagnostics."""
    result = _run(["ty", "check", str(ROOT)])
    assert result.returncode == 0, (
        f"ty check failed (exit {result.returncode}):\n\n{result.stdout}\n{result.stderr}"
    )


def test_import_linter() -> None:
    """import-linter contracts must all pass."""
    result = _run(["lint-imports", "--config", str(ROOT / "pyproject.toml")])
    assert result.returncode == 0, (
        f"import-linter failed (exit {result.returncode}):\n\n{result.stdout}\n{result.stderr}"
    )


def test_vulture() -> None:
    """vulture must report no dead code above the confidence threshold."""
    result = _run(["vulture", "--config", str(ROOT / "pyproject.toml")])
    assert result.returncode == 0, (
        f"vulture found dead code (exit {result.returncode}):\n\n{result.stdout}\n{result.stderr}"
    )


def test_astgrep() -> None:
    """ast-grep architectural rules must all pass.

    Installed via the `ast-grep-cli` dev dependency, which provides both the
    `ast-grep` and `sg` binaries. Resolved from the venv rather than PATH so
    this never silently skips -- these four rules are the only enforcement of
    the layering invariants ruff cannot express.
    """
    result = _run(["ast-grep", "scan", "--config", str(ROOT / "sgconfig.yml"), str(ROOT)])
    assert result.returncode == 0, (
        f"ast-grep found violations (exit {result.returncode}):\n\n{result.stdout}\n{result.stderr}"
    )


def test_module_length() -> None:
    """No source module may exceed MAX_MODULE_LINES lines.

    Test code is exempt, and "test code" means tests/ *and* features/ --
    pyproject already says the pytest-bdd suite gets the same allowances as
    tests/**, and this check was the one place that had not been told. The cap
    measures whether a module is navigable, which is a claim about code you
    read to understand the system; a pytest-bdd binding is a flat catalogue of
    three-line step definitions whose natural unit is its .feature file, and
    splitting one to hit a line count scatters a single scenario's steps across
    modules. tests/unit/adapters/test_guard_executor.py is already over the cap
    and exempt only for living under tests/.
    """
    exempt = {"tests", "features"}
    offenders: list[str] = []
    for path in sorted(ROOT.rglob("*.py")):
        parts = path.relative_to(ROOT).parts
        if any(part.startswith(".") for part in parts) or exempt & set(parts):
            continue
        line_count = path.read_text().count("\n") + 1
        if line_count > MAX_MODULE_LINES:
            offenders.append(f"{path.relative_to(ROOT)}: {line_count} lines")
    listing = "\n".join(offenders)
    assert not offenders, f"modules exceed {MAX_MODULE_LINES} lines; split them:\n\n{listing}"


def _has_top_level_definition(path: Path) -> bool:
    """Return True if the module defines any top-level function or class."""
    tree = ast.parse(path.read_text())
    return any(
        isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
        for node in tree.body
    )


def _expected_test(rel: Path) -> Path:
    """Map a source module (relative to PACKAGE) to its mirror test path."""
    if rel.name == "__init__.py":
        return UNIT_TESTS / rel.parent / f"test_{rel.parent.name}.py"
    return UNIT_TESTS / rel.parent / f"test_{rel.stem}.py"


def test_tests_mirror_package() -> None:
    """Every source module with logic must have a mirrored test under tests/unit/.

    tests/unit/ mirrors the package layout 1:1: a source module ``PKG/<path>.py``
    requires ``tests/unit/<path>/test_<name>.py`` (a package ``__init__.py`` maps
    to ``test_<dir>.py``). Pure namespace shells (no top-level def/class) and the
    entries in MIRROR_EXEMPT are skipped, so a test is required only once a
    module actually carries logic. Other tests/ subtrees (integration, ...) are
    free-form and not checked here.
    """
    offenders: list[str] = []
    for path in sorted(PACKAGE.rglob("*.py")):
        rel = path.relative_to(PACKAGE)
        if any(part.startswith(".") for part in rel.parts) or path.name in MIRROR_EXEMPT:
            continue
        if MIRROR_EXEMPT_DIRS & set(rel.parts):
            continue
        if not _has_top_level_definition(path):
            continue
        expected = _expected_test(rel)
        if not expected.exists():
            offenders.append(f"{path.relative_to(ROOT)} -> {expected.relative_to(ROOT)}")
    listing = "\n".join(offenders)
    assert not offenders, (
        f"source modules missing their mirror test (create each right-hand file):\n\n{listing}"
    )
