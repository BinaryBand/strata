"""Discover runbook modules under strata.core.runbooks.

Exposes ``iter_runbooks()`` which walks the runbook package, imports each
module, adds the runbook built from each app spec in ansible/apps/ and from each
project registered in ansible/projects.yml, and returns metadata the CLI uses
for ``--list``, autocompletion, and bare-leaf resolution.
"""

from __future__ import annotations

import difflib
import functools
import importlib
import inspect
import pkgutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import NamedTuple

import strata.core.runbooks as _runbook_pkg
from strata.core import (
    app_runbook,
    app_specs,
    guard,
    paths,
    projects,
    runbook_module,
    source_runbook,
)


@dataclass(frozen=True)
class RunbookInfo:
    """Metadata about a single discovered runbook module."""

    dotted_name: str  # relative to strata.core.runbooks, e.g. "services.install_jellyfin"
    leaf: str  # final segment, e.g. "install_jellyfin"
    category: str  # parent package, e.g. "services"
    docstring_first_line: str  # first line of the module docstring
    accepts_tags: bool  # True if main() has a ``tags`` parameter
    alias: str | None = None  # human-friendly display name from @guard.alias, or None

    @property
    def summary(self) -> str:
        """One-line description, without the 'Runbook:' prefix every module repeats."""
        return self.docstring_first_line.removeprefix("Runbook:").strip()


def accepts_tags(main: Callable[..., object]) -> bool:
    """Return True if a runbook's ``main()`` declares a ``tags`` parameter.

    Only two runbooks do (backup and restore), and `strata runbook --tags` is
    forwarded to those alone. cli/dispatch.py asks the same question of the
    module it is about to run, so the check lives here rather than in both.
    """
    try:
        return "tags" in inspect.signature(main).parameters
    except (ValueError, TypeError):
        return False


def forwarded_tags(module: ModuleType, tags: list[str] | None) -> list[str] | None:
    """Return the tags this runbook's main() is called with, or raise ValueError.

    Tags reach only a main() that declares a `tags` parameter; any other runbook
    gets None, since passing them would fail with a TypeError after the guard
    chain had already run. Both entry points -- `strata runbook --tags` and the
    GUI's `POST /api/run` -- go through here, so they cannot disagree.

    A runbook that can reject a selection outright says so with a module-level
    `validate_tags`, which raises the ValueError, and it is checked here rather
    than left to main(). By the time main() runs the guard chain has already been
    satisfied -- and since a satisfied upstream stopped skipping its own guards,
    that chain reconciles the diot account and the restic repository. A typo
    should not cost a sudo play.
    """
    selected = tags if accepts_tags(module.main) else None
    validate = getattr(module, "validate_tags", None)
    if validate is not None:
        validate(selected)
    return selected


@dataclass(frozen=True)
class ImportFailure:
    """A runbook module that could not be imported, and why."""

    dotted_name: str
    error: str


def _info(short: str, module: ModuleType) -> RunbookInfo | None:
    """Describe a runbook module, or return None for a helper module with no main()."""
    main = getattr(module, "main", None)
    if not callable(main):
        # A module under runbooks/ with no main() is a helper, not a
        # runbook. Appending it unconditionally put it in --list and the
        # picker, and then dispatch died on a bare AttributeError the
        # moment anyone selected it.
        return None
    docstring = (inspect.getdoc(module) or "").splitlines()
    parts = short.split(".")
    return RunbookInfo(
        dotted_name=short,
        leaf=parts[-1],
        category=parts[-2] if len(parts) > 1 else "",
        docstring_first_line=docstring[0].strip() if docstring else "",
        accepts_tags=accepts_tags(main),
        alias=guard.alias_of(main),
    )


@functools.cache
def _spec_runbooks(
    directory: Path,
) -> tuple[dict[str, ModuleType], tuple[ImportFailure, ...]]:
    """Build a runbook module from each spec under `directory`, once per process.

    A spec that cannot be read or built is recorded as a failure like an
    unimportable module, so one bad file does not take the others down. Cached
    so the YAML is read and validated once, not on every lookup.
    """
    modules: dict[str, ModuleType] = {}
    failures: list[ImportFailure] = []
    for path in app_specs.spec_files(directory):
        short = runbook_module.dotted_name(path.stem)
        try:
            modules[short] = app_runbook.build(app_specs.load(path))
        except Exception as exc:  # noqa: BLE001
            failures.append(ImportFailure(dotted_name=short, error=f"{type(exc).__name__}: {exc}"))
    return modules, tuple(failures)


@functools.cache
def _project_runbooks(
    file: Path,
) -> tuple[dict[str, ModuleType], tuple[ImportFailure, ...]]:
    """Build a runbook module from the manifest of each project listed in `file`, once per process.

    A project that cannot be read, or whose manifest is invalid, is a failure
    like a bad spec, keyed by its directory since it has no trustworthy name.
    """
    modules: dict[str, ModuleType] = {}
    failures: list[ImportFailure] = []
    try:
        directories = projects.registered(file)
    except projects.ProjectError as exc:
        return modules, (ImportFailure(dotted_name=str(file), error=str(exc)),)
    for directory in directories:
        try:
            spec = projects.load(directory)
            modules[runbook_module.dotted_name(spec.name)] = source_runbook.build(spec, directory)
        except Exception as exc:  # noqa: BLE001
            failures.append(ImportFailure(str(directory), f"{type(exc).__name__}: {exc}"))
    return modules, tuple(failures)


def _declared() -> tuple[dict[str, ModuleType], list[ImportFailure]]:
    """The runbooks built from declarations, not imported: Podman specs, then projects.

    A name declared twice keeps the later one and records the clash, so the
    listing and `load` cannot disagree about which one runs.
    """
    modules: dict[str, ModuleType] = {}
    failures: list[ImportFailure] = []
    for built, errors in (
        _spec_runbooks(paths.APPS_DIR),
        _project_runbooks(paths.PROJECTS_FILE),
    ):
        failures.extend(errors)
        _merge(modules, failures, built)
    return modules, failures


def _merge(
    into: dict[str, ModuleType], failures: list[ImportFailure], built: dict[str, ModuleType]
) -> None:
    """Add `built` to `into`; on a name clash the later wins and the clash is recorded."""
    for short, module in built.items():
        if short in into:
            failures.append(ImportFailure(short, "declared by both, and only the later one runs"))
        into[short] = module


class _Walk(NamedTuple):
    """Everything one walk of the runbooks found."""

    runbooks: list[RunbookInfo]
    failures: list[ImportFailure]
    modules: dict[str, ModuleType]  # dotted name -> module, for each listed runbook


def _walk() -> _Walk:
    """Import every runbook module, returning what worked and what did not."""
    pkg = _runbook_pkg
    modules: dict[str, ModuleType] = {}
    failures: list[ImportFailure] = []
    for _importer, modname, ispkg in pkgutil.walk_packages(pkg.__path__, pkg.__name__ + "."):
        short = modname.removeprefix(pkg.__name__ + ".")
        if ispkg:
            continue
        try:
            modules[short] = importlib.import_module(modname)
        except Exception as exc:  # noqa: BLE001
            # One unimportable runbook must not take `--list` down for all the
            # others, so the failure is recorded rather than raised -- but it
            # is recorded, not discarded. Swallowing it entirely meant a
            # runbook with a typo'd import vanished from the listing *and*
            # from resolve_name, so `strata runbook install_jellyfin` reported
            # "Unknown runbook" with fuzzy suggestions, sending the operator
            # after an imaginary naming problem instead of the real
            # ImportError. import_failures() surfaces these to the CLI.
            failures.append(ImportFailure(dotted_name=short, error=f"{type(exc).__name__}: {exc}"))

    declared, declared_failures = _declared()
    failures.extend(declared_failures)
    # load() prefers a declaration over a module of the same name, so the listing does too.
    _merge(modules, failures, declared)

    infos = {short: info for short, module in modules.items() if (info := _info(short, module))}
    runbooks = sorted(infos.values(), key=lambda r: r.dotted_name)
    return _Walk(runbooks, failures, {short: modules[short] for short in infos})


def load(dotted_name: str) -> ModuleType:
    """Return the runbook module named `dotted_name`, relative to the runbook package.

    A Podman app declared in ansible/apps/, or a registered project, has no
    module to import; its runbook is the one built from its declaration.
    """
    declared_module = _declared()[0].get(dotted_name)
    if declared_module is not None:
        return declared_module
    return importlib.import_module(f"{_runbook_pkg.__name__}.{dotted_name}")


def iter_runbooks() -> list[RunbookInfo]:
    """Walk the runbook package and return metadata for every runbook module."""
    return _walk().runbooks


def import_failures() -> list[ImportFailure]:
    """Return the runbook modules that failed to import, with their errors."""
    return _walk().failures


def runbook_modules() -> tuple[dict[str, ModuleType], list[ImportFailure]]:
    """Return each listed runbook's module by dotted name, and what failed to load.

    For a caller that reads what the runbooks declare (infrastructure.backup
    reads their backup tags) and has to know whether it saw all of them.
    """
    walk = _walk()
    return walk.modules, walk.failures


def resolve_name(name: str) -> str | None:
    """Resolve *name* to a dotted runbook name.

    Returns the dotted form if *name* already contains a dot and matches a
    known runbook, or if *name* is a bare leaf that matches exactly one
    runbook.  Returns ``None`` when no match is found, including when a leaf
    is ambiguous -- the docstring has always promised "exactly one", but
    building a dict keyed by leaf silently resolved to whichever category
    happened to be walked last.
    """
    runbooks = iter_runbooks()

    if any(r.dotted_name == name for r in runbooks):
        return name

    matches = [r for r in runbooks if r.leaf == name]
    if len(matches) == 1:
        return matches[0].dotted_name

    return None


def suggest(name: str, limit: int = 5) -> list[str]:
    """Return up to *limit* close matches for *name* among known runbooks."""
    known = [r.dotted_name for r in iter_runbooks()]
    return difflib.get_close_matches(name, known, n=limit, cutoff=0.4)
