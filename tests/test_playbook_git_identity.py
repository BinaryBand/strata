"""Every `git commit` in a playbook must supply its own identity.

git refuses to commit when `user.name`/`user.email` are unset, and there is no
reason to assume a provisioned machine has them: install_antigravity.yml
committed to its local Homebrew tap and failed the whole play on any host
where the operator had never configured git globally.

Passing the identity with `git -c` keeps it per-invocation, so the play still
touches nothing outside the tap repository. This gate is written over every
task file rather than that one playbook, so the next play that commits
inherits the rule instead of rediscovering it.
"""

from __future__ import annotations

import yaml

from tests._ansible import TASK_FILES, iter_tasks

# The modules that can run a git commit. `command` cannot chain, but it can
# still invoke `git commit` directly.
_COMMAND_KEYS = (
    "ansible.builtin.shell",
    "shell",
    "ansible.builtin.command",
    "command",
)


def _command_text(task: dict[str, object]) -> str:
    """Return the command a task runs, whether given as a string or a mapping."""
    for key in _COMMAND_KEYS:
        value = task.get(key)
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            cmd = value.get("cmd")
            if isinstance(cmd, str):
                return cmd
    return ""


def test_every_git_commit_supplies_an_identity() -> None:
    offenders: list[str] = []
    for path in TASK_FILES:
        for task in iter_tasks(yaml.safe_load(path.read_text())):
            command = _command_text(task)
            if "git" not in command or "commit" not in command:
                continue
            if "user.name" not in command or "user.email" not in command:
                name = task.get("name", "<unnamed>")
                offenders.append(f"{path.name}: {name}")
    listing = "\n".join(offenders)
    assert not offenders, (
        "git commit without an identity fails outright on a machine with no global "
        f"user.name/user.email; pass it with `git -c`:\n\n{listing}"
    )
