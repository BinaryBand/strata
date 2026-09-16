"""Each playbook and role task file registers every variable name once.

A skipped task still registers its variable, replacing an earlier result with
one that has no `rc` or `stdout`. Re-registering a name under a condition
therefore breaks every later task that reads it, but only on the runs where
that task is skipped. enable_wireguard.yml shipped exactly that bug.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest
import yaml

from tests._ansible import ANSIBLE_DIR, TASK_FILES, iter_tasks


@pytest.mark.parametrize(
    "path", TASK_FILES, ids=[str(p.relative_to(ANSIBLE_DIR)) for p in TASK_FILES]
)
def test_no_variable_is_registered_twice(path: Path) -> None:
    counts = Counter(
        name
        for task in iter_tasks(yaml.safe_load(path.read_text()))
        if isinstance(name := task.get("register"), str)
    )
    repeated = sorted(name for name, count in counts.items() if count > 1)
    assert not repeated, (
        f"{path.name} registers {repeated} more than once; give each check its own name"
    )
