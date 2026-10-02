"""Static guard-completeness check.

Cross-references each runbook's declared guard.requires() chain against the
external tools its own playbook shells out to via command/shell tasks, so a
runbook can't silently ship an assumption that nothing in its guard chain
actually satisfies. This is deliberately narrow: it only sees tools invoked
through ansible.builtin.command/shell task literals (after resolving simple
play-level `vars:` substitutions), in either the `cmd:` or the `argv:` form,
in the playbook itself or in any role it includes, not tools consumed through
dedicated Ansible modules or tools assumed present on the base OS with no
runbook provider at all (e.g. git, rclone -- neither has an installing runbook
to point TOOL_PROVIDERS at).
Those are out of reach of this kind of static check and are tracked as prose
findings in the project plan instead.

KNOWN_GAPS documents today's real, un-guarded gaps: allowlisted entries are
reported but don't fail the suite, so this test both records current debt
and catches *new* regressions the moment a playbook starts relying on a tool
its guard chain doesn't provide.
"""

from __future__ import annotations

import inspect
import itertools
import re
from pathlib import Path, PurePosixPath
from typing import cast

import yaml

from strata.core import discovery, guard
from strata.core import requirements as req
from strata.core.runbooks.infrastructure import backup
from tests.playbooks._ansible import ANSIBLE_DIR, iter_tasks

# Binary name -> dotted runbook (relative to strata.core.runbooks) that
# installs it. Only tools actually observed as literal command/shell
# invocations in the playbooks belong here -- see module docstring.
TOOL_PROVIDERS: dict[str, str] = {
    "brew": "package_managers.install_homebrew",
    "pipx": "package_managers.install_homebrew",
    "tailscale": "infrastructure.enable_tailscale",
    "podman": "infrastructure.install_podman",
}

# runbook -> tools it references without a guard.requires() chain that
# provides them. Seeded from a codebase survey; see the project plan for
# each entry's origin. Remove an entry once its guard is actually fixed.
#
# Currently empty, and worth keeping that way rather than deleting: the two
# original entries were both one missing @guard.requires on Homebrew, not
# gaps this check cannot express, so they were closed rather than carried.
KNOWN_GAPS: dict[str, frozenset[str]] = {}

_PLAYBOOK_RE = re.compile(r'run_playbook\(\s*"(playbooks/[^"]+\.yml)"')
_COMMAND_KEYS = ("ansible.builtin.command", "command", "ansible.builtin.shell", "shell")
_ROLE_KEYS = (
    "ansible.builtin.include_role",
    "include_role",
    "ansible.builtin.import_role",
    "import_role",
)


def _runbook_names() -> list[str]:
    """Dotted runbook names, e.g. 'services.install_jellyfin'.

    Walks discovery, so the runbooks built from ansible/apps/ are checked like
    any other. A runbook that fails to load fails here rather than dropping out
    of every check below.
    """
    assert not discovery.import_failures(), discovery.import_failures()
    return [info.dotted_name for info in discovery.iter_runbooks()]


def _requires_map() -> dict[str, list[str]]:
    """Every runbook's declared upstream runbooks, by dotted name."""
    return {
        name: [r.dotted_name for r in _declared(name) if isinstance(r, req.UpstreamRunbook)]
        for name in _runbook_names()
    }


def _overlapping(tag_paths: dict[str, str]) -> list[tuple[str, str]]:
    """Every pair of tags whose backup paths contain one another.

    Only a tag declared for two paths is refused at discovery, so nothing stops
    two tags covering the same tree -- one rooted at a directory and another at
    a subdirectory of it means every backup stores the inner tree twice, and
    restoring the outer tag overwrites the inner one's content from its own copy.
    """
    return [
        (tag, other_tag)
        for (tag, path), (other_tag, other_path) in itertools.combinations(
            sorted(tag_paths.items()), 2
        )
        if PurePosixPath(path).is_relative_to(other_path)
        or PurePosixPath(other_path).is_relative_to(path)
    ]


def _playbook_for(runbook: str) -> Path | None:
    module = discovery.load(runbook)
    named = getattr(module, "PLAYBOOK", None)
    if named is not None:
        return ANSIBLE_DIR / named
    match = _PLAYBOOK_RE.search(inspect.getsource(module))
    return ANSIBLE_DIR / match.group(1) if match else None


def _one_command(value: object) -> str:
    """Flatten a single command/shell task value to a command line.

    The free-form dict form accepts either `cmd:` (a string) or `argv:` (a
    list). Reading only `cmd` made every argv-form task look like an empty
    command, so the raw podman/restic/rclone calls in backup.yml,
    install_restic.yml and sync_rclone_remote.yml were invisible to this
    check rather than deliberately excluded.
    """
    if not isinstance(value, dict):
        return str(value)
    entry = cast("dict[str, object]", value)
    argv = entry.get("argv")
    if isinstance(argv, list):
        return " ".join(str(arg) for arg in cast("list[object]", argv))
    return str(entry.get("cmd", ""))


# A task that runs only for a project that declares a feature is not evidence that every
# runbook on the play needs that feature's tool. The guard such a project declares is
# pinned where the runbook is built (tests/unit/core/test_source_runbook.py), and a task
# that uses the tool with no condition is still seen here.
_FEATURE_CONDITIONS = ("source_app.tailnet", "podman_app.tailnet")


def _for_a_declared_feature(task: dict[str, object]) -> bool:
    conditions = task.get("when")
    parts = conditions if isinstance(conditions, list) else [conditions]
    return any(feature in str(part) for part in parts for feature in _FEATURE_CONDITIONS)


def _command_strings(tasks: object) -> list[str]:
    return [
        _one_command(value)
        for task in iter_tasks(tasks)
        if not _for_a_declared_feature(task)
        for key in _COMMAND_KEYS
        if (value := task.get(key)) is not None
    ]


def _role_names(tasks: object) -> set[str]:
    """Roles `tasks` pulls in, by `roles:` entry or include_role/import_role task."""
    names: set[str] = set()
    for task in iter_tasks(tasks):
        for key in _ROLE_KEYS:
            spec = task.get(key)
            if isinstance(spec, dict) and isinstance(name := spec.get("name"), str):
                names.add(name)
        for entry in cast("list[object]", task.get("roles") or []):
            name = entry.get("role") if isinstance(entry, dict) else entry
            if isinstance(name, str):
                names.add(name)
    return names


def _role_tasks(names: set[str]) -> list[object]:
    """Every task file of the named roles, and of the roles those include."""
    seen: set[str] = set()
    task_files: list[object] = []
    pending = set(names)
    while pending:
        name = pending.pop()
        seen.add(name)
        for path in sorted((ANSIBLE_DIR / "roles" / name / "tasks").glob("*.yml")):
            tasks = yaml.safe_load(path.read_text())
            task_files.append(tasks)
            pending |= _role_names(tasks) - seen
    return task_files


def _tools_used(playbook_path: Path) -> set[str]:
    plays = yaml.safe_load(playbook_path.read_text())
    tools: set[str] = set()
    for play in plays or []:
        if not isinstance(play, dict):
            continue
        play_vars = {k: v for k, v in (play.get("vars") or {}).items() if isinstance(v, str)}
        sections = [play.get(s) for s in ("pre_tasks", "tasks", "post_tasks")]
        sections += _role_tasks(_role_names(play))
        for section in sections:
            for raw_cmd in _command_strings(section):
                cmd = raw_cmd
                for name, value in play_vars.items():
                    cmd = cmd.replace("{{ " + name + " }}", value)
                tokens = [Path(tok).name for tok in cmd.split()]
                tools.update(tool for tool in TOOL_PROVIDERS if tool in tokens)
    return tools


def _transitive_requires(runbook: str, requires_map: dict[str, list[str]]) -> set[str]:
    seen: set[str] = set()
    stack = [runbook]
    while stack:
        current = stack.pop()
        for dep in requires_map.get(current, []):
            if dep not in seen:
                seen.add(dep)
                stack.append(dep)
    return seen


def _declared(runbook: str) -> list[req.Requirement]:
    main = getattr(discovery.load(runbook), "main", None)
    return guard.declared(main) if callable(main) else []


def _direct_users(runbook: str) -> set[str]:
    return {r.username for r in _declared(runbook) if isinstance(r, req.SystemUser)}


def _users_provided_by(runbook: str, requires_map: dict[str, list[str]]) -> set[str]:
    """Every system account `runbook` creates, directly or through its chain."""
    chain = {runbook} | _transitive_requires(runbook, requires_map)
    return {user for dep in chain for user in _direct_users(dep)}


def test_owned_paths_are_declared_after_the_guard_that_creates_the_owner() -> None:
    """Ownership can only be applied once the account exists.

    Requirements are satisfied in declaration order, outermost decorator
    first. A @guard.path/@guard.storage carrying owner="diot" placed *above*
    the @guard.requires whose chain runs create_diot_user.yml sends
    ensure_path.yml to chown a user that does not exist yet, which fails with
    "failed to look up user diot" and leaves the runbook unable to bootstrap
    a clean host. Nothing about the decorator API prevents this, so it is
    checked here rather than left to each author to remember.
    """
    runbooks = _runbook_names()
    requires_map = _requires_map()
    known_users = {user for runbook in runbooks for user in _direct_users(runbook)}

    violations: dict[str, list[str]] = {}
    for runbook in runbooks:
        satisfied: set[str] = set()
        problems: list[str] = []
        for requirement in _declared(runbook):
            match requirement:
                case req.SystemUser(username=username):
                    satisfied.add(username)
                case req.UpstreamRunbook(dotted_name=dep):
                    satisfied |= _users_provided_by(dep, requires_map)
                case req.LocalPath() | req.Storage():
                    owned = {requirement.owner, requirement.group} & known_users
                    problems.extend(
                        f"{type(requirement).__name__} owned by {user!r} is "
                        f"declared before the guard that creates {user!r}"
                        for user in sorted(owned - satisfied)
                    )
                case _:
                    pass
        if problems:
            violations[runbook] = problems

    assert not violations, (
        f"Guards are declared in an order that cannot succeed on a fresh host: "
        f"{violations}. Move the @guard.requires(...) above the owned "
        f"@guard.path/@guard.storage -- decorators apply bottom-up, so the "
        f"one listed first is satisfied first."
    )


# Backup tags whose paths are known to overlap. An entry here is real debt:
# the nested path is snapshotted under both tags, and restoring the outer tag
# overwrites the inner one's content from its own copy. Resolving it is a
# decision about the data layout (split the directories, or drop the redundant
# tag), so it is recorded rather than guessed at.
KNOWN_OVERLAPPING_BACKUP_TAGS: set[tuple[str, str]] = set()


def test_no_backup_tag_covers_another_tags_path() -> None:
    overlaps = set(_overlapping(backup.declared_backup_paths()))

    unexpected = overlaps - KNOWN_OVERLAPPING_BACKUP_TAGS
    assert not unexpected, (
        f"These backup tags cover overlapping paths, so the nested one is "
        f"stored twice and restore order decides which copy wins: {unexpected}. "
        f"Give them disjoint directories."
    )
    stale = KNOWN_OVERLAPPING_BACKUP_TAGS - overlaps
    assert not stale, f"These overlaps no longer reproduce; remove them from the allowlist: {stale}"


def test_every_runbook_points_at_a_playbook_that_exists() -> None:
    """A runbook naming a playbook that isn't on disk fails only at run time.

    Until this existed, test_every_referenced_tool_is_guarded skipped such a
    runbook rather than failing it, so a runbook could be discoverable,
    aliased and listed while its playbook had never been written -- the
    operator found out from a bare `Playbook failed (status=...)`.
    """
    missing = {
        runbook: playbook_path
        for runbook in _runbook_names()
        if (playbook_path := _playbook_for(runbook)) is not None and not playbook_path.exists()
    }
    assert not missing, (
        f"Runbooks call run_playbook() on files that do not exist: {missing}. "
        f"Write the playbook, or remove the runbook."
    )


def test_every_referenced_tool_is_guarded() -> None:
    runbooks = _runbook_names()
    requires_map = _requires_map()
    unexpected_gaps: dict[str, set[str]] = {}
    stale_allowlist_entries: dict[str, set[str]] = {}

    for runbook in runbooks:
        playbook_path = _playbook_for(runbook)
        # A runbook with no run_playbook() call has nothing to inspect. One
        # that names a missing file is a real defect, caught separately by
        # test_every_runbook_points_at_a_playbook_that_exists -- skipping it
        # here would only duplicate that failure.
        if playbook_path is None or not playbook_path.exists():
            continue

        provided = _transitive_requires(runbook, requires_map)
        allowlisted = KNOWN_GAPS.get(runbook, frozenset())
        gaps: set[str] = set()

        for tool in _tools_used(playbook_path):
            provider = TOOL_PROVIDERS[tool]
            if provider == runbook or provider in provided:
                continue
            gaps.add(tool)

        if gaps - allowlisted:
            unexpected_gaps[runbook] = gaps - allowlisted
        if allowlisted - gaps:
            stale_allowlist_entries[runbook] = allowlisted - gaps

    assert not unexpected_gaps, (
        f"Runbooks reference tools their guard.requires() chain doesn't "
        f"provide: {unexpected_gaps}. Either add the missing "
        f"guard.requires(...), or if this is a known/accepted gap, add it "
        f"to KNOWN_GAPS in this file."
    )
    assert not stale_allowlist_entries, (
        f"KNOWN_GAPS entries no longer reproduce -- the underlying guard "
        f"appears fixed, remove these entries: {stale_allowlist_entries}"
    )
