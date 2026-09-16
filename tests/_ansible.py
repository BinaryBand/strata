"""Where the Ansible sources live and how to walk them, for the gates that parse them.

Four test modules had each spelled the path to `ansible/` from their own
location, and two had each written their own task-tree walker. Both answers
are properties of the repository, not of any one gate, so they are stated once
here.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import cast

from strata.core import paths

ANSIBLE_DIR = paths.ANSIBLE_DIR
PLAYBOOKS_DIR = ANSIBLE_DIR / "playbooks"

# Every file that holds Ansible tasks: the playbooks and the roles' task,
# handler and default files.
TASK_FILES = sorted([*PLAYBOOKS_DIR.glob("*.yml"), *ANSIBLE_DIR.glob("roles/*/*/*.yml")])

# Every key whose value is a list of tasks: a play's sections and a task's
# nested blocks.
_TASK_LISTS = ("tasks", "pre_tasks", "post_tasks", "handlers", "block", "rescue", "always")


def iter_tasks(node: object) -> Iterator[dict[str, object]]:
    """Every task mapping under `node`, depth first, nested blocks included.

    `node` may be a whole loaded playbook (a list of plays), one play, one task
    list, or one task. A play is itself yielded, since it is a mapping like any
    other; callers read the keys they care about and ignore the rest.
    """
    if isinstance(node, list):
        for item in cast("list[object]", node):
            yield from iter_tasks(item)
        return
    if not isinstance(node, dict):
        return
    entry = cast("dict[str, object]", node)
    yield entry
    for key in _TASK_LISTS:
        yield from iter_tasks(entry.get(key))
