"""Render a play's role vars and template the way Ansible would, for the golden snapshots.

The behaviour that matters to the host is what the play hands its role: the
extravars a runbook passes, the group_vars, and the play's own role vars and
template, through Jinja with undefined names as errors. Two Ansible features are
all the plays use -- the template lookup and `vars` -- so those are the two
emulated.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import yaml
from jinja2 import Environment, StrictUndefined

from strata.core import guard, paths
from strata.core import requirements as req
from tests._fakes import RecordingPlaybookRunner
from tests.playbooks._ansible import PLAYBOOKS_DIR, iter_tasks

TEMPLATES_DIR = PLAYBOOKS_DIR / "templates"

# Ansible turns a templated "True"/"False" back into a bool.
_BOOLS = {"True": True, "False": False}


def render(value: object, context: dict[str, Any]) -> object:
    """Render a var the way Ansible templates it; a non-string passes through.

    Blocks trim their newline, as Ansible's templating does, and a list is
    rendered item by item.
    """
    if isinstance(value, list):
        return [render(item, context) for item in cast("list[object]", value)]
    if not isinstance(value, str):
        return value
    env = Environment(undefined=StrictUndefined, keep_trailing_newline=True, trim_blocks=True)
    cast("dict[str, Any]", env.globals)["lookup"] = lambda kind, name: _lookup(
        env, kind, name, context
    )
    rendered = env.from_string(value).render({**context, "vars": context})
    return _BOOLS.get(rendered, rendered)


def _lookup(env: Environment, kind: str, name: str, context: dict[str, Any]) -> str:
    assert kind == "ansible.builtin.template", f"unsupported lookup {kind!r}"
    return env.from_string((TEMPLATES_DIR / name).read_text()).render({**context, "vars": context})


def group_vars() -> dict[str, Any]:
    return yaml.safe_load((paths.GROUP_VARS_DIR / "all" / "common.yml").read_text())


def include_role_task(playbook: Path) -> dict[str, Any]:
    """The one task of `playbook` that includes a role."""
    tasks = [
        task
        for task in iter_tasks(yaml.safe_load(playbook.read_text()))
        if "include_role" in task or "ansible.builtin.include_role" in task
    ]
    assert len(tasks) == 1, f"{playbook.name}: expected one include_role, found {len(tasks)}"
    return tasks[0]


def snapshot(
    module: ModuleType,
    *,
    content_var: str,
    content_key: str,
    facts: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """What running `module` deploys: its declarations, the role vars and the unit it renders.

    `content_var` names the role var holding the unit text; it is rendered
    under `content_key` and left out of the role vars. `facts` stands in for what the
    play learns on the host with `set_fact` (a tailnet name), which no snapshot can.
    """
    runner = RecordingPlaybookRunner()
    assert module.main(runner=runner) == 0

    secrets = {
        r.vault_key: f"<vault:{r.vault_key}>"
        for r in guard.declared(module.main)
        if isinstance(r, req.Secret)
    }
    playbook_name, extravars, _target = runner.calls[0]
    context = {**group_vars(), **secrets, **extravars, **(facts or {})}
    task = include_role_task(PLAYBOOKS_DIR / Path(playbook_name).name)
    return {
        "alias": guard.alias_of(module.main),
        "guards": [repr(r) for r in guard.declared(module.main)],
        "backup": dict(guard.backup_tags_of(module.main)),
        "role_vars": {
            name: render(value, context)
            for name, value in task["vars"].items()
            if name != content_var
        },
        content_key: render(task["vars"][content_var], context),
    }
