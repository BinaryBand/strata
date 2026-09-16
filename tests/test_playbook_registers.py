"""Each playbook and role task file registers every variable name once.

A skipped task still registers its variable, replacing an earlier result with
one that has no `rc` or `stdout`. Re-registering a name under a condition
therefore breaks every later task that reads it, but only on the runs where
that task is skipped. enable_wireguard.yml shipped exactly that bug.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import cast

import pytest
import yaml

from tests._ansible import ANSIBLE_DIR, TASK_FILES

_TASK_LISTS = ("tasks", "pre_tasks", "post_tasks", "handlers", "block", "rescue", "always")


def _registers(node: object) -> list[str]:
    if isinstance(node, list):
        return [name for item in cast("list[object]", node) for name in _registers(item)]
    if not isinstance(node, dict):
        return []
    entry = cast("dict[str, object]", node)
    registered = entry.get("register")
    names = [registered] if isinstance(registered, str) else []
    for key in _TASK_LISTS:
        names.extend(_registers(entry.get(key)))
    return names


@pytest.mark.parametrize(
    "path", TASK_FILES, ids=[str(p.relative_to(ANSIBLE_DIR)) for p in TASK_FILES]
)
def test_no_variable_is_registered_twice(path: Path) -> None:
    counts = Counter(_registers(yaml.safe_load(path.read_text())))
    repeated = sorted(name for name, count in counts.items() if count > 1)
    assert not repeated, (
        f"{path.name} registers {repeated} more than once; give each check its own name"
    )
