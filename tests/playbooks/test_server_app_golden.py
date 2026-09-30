"""Golden snapshots of what each server app deploys, independent of how it is declared.

The behaviour that matters to the host is narrower than the source that declares
it: which guards run in which order, which backup tag covers which path, and the
Quadlet unit the role writes. This module pins exactly those, so a change to a
spec or to the unit template shows up as a deliberate edit to a snapshot.

The Quadlet is rendered the way Ansible would render it: the extravars the
runbook hands the generic playbook, the group_vars, and the playbook's own role
vars and template, through Jinja with undefined names as errors.

Regenerate a snapshot only for a change meant to alter the deployed unit:

    UPDATE_GOLDEN=1 uv run pytest tests/playbooks/test_server_app_golden.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, cast

import pytest
import yaml
from jinja2 import Environment, StrictUndefined

from strata.core import app_runbook, discovery, guard, paths
from strata.core import requirements as req
from tests._fakes import RecordingPlaybookRunner
from tests.playbooks._ansible import PLAYBOOKS_DIR, iter_tasks

GOLDEN_DIR = Path(__file__).parent / "golden"
TEMPLATES_DIR = PLAYBOOKS_DIR / "templates"
APPS = ("baikal", "jellyfin", "minio")

# Ansible turns a templated "True"/"False" back into a bool.
_BOOLS = {"True": True, "False": False}


def _render(value: object, context: dict[str, Any]) -> object:
    """Render a string the way Ansible templates a var; anything else passes through.

    The template lookup and `vars` are the two Ansible features the play and its
    template use. Blocks trim their newline, as Ansible's templating does.
    """
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


def _group_vars() -> dict[str, Any]:
    return yaml.safe_load((paths.GROUP_VARS_DIR / "all" / "common.yml").read_text())


def _quadlet_role_task(playbook: Path) -> dict[str, Any]:
    tasks = [
        task
        for task in iter_tasks(yaml.safe_load(playbook.read_text()))
        if "include_role" in task or "ansible.builtin.include_role" in task
    ]
    assert len(tasks) == 1, f"{playbook.name}: expected one include_role, found {len(tasks)}"
    return tasks[0]


def _snapshot(app: str) -> dict[str, Any]:
    module = discovery.load(app_runbook.dotted_name(app))
    runner = RecordingPlaybookRunner()
    assert module.main(runner=runner) == 0

    secrets = {
        r.vault_key: f"<vault:{r.vault_key}>"
        for r in guard.declared(module.main)
        if isinstance(r, req.Secret)
    }
    playbook_name, extravars, _target = runner.calls[0]
    context = {**_group_vars(), **secrets, **extravars}
    playbook = PLAYBOOKS_DIR / Path(playbook_name).name

    task = _quadlet_role_task(playbook)
    role_vars = {
        name: _render(value, context)
        for name, value in (task["vars"]).items()
        if name != "quadlet_content"
    }
    return {
        "alias": guard.alias_of(module.main),
        "guards": [repr(r) for r in guard.declared(module.main)],
        "backup": {tag: path for tag, path in guard.backup_paths().items() if tag == app},
        "role_vars": role_vars,
        "quadlet": _render(task["vars"]["quadlet_content"], context),
    }


@pytest.mark.parametrize("app", APPS)
def test_server_app_matches_golden(app: str) -> None:
    snapshot = _snapshot(app)
    golden = GOLDEN_DIR / f"{app}.json"
    if os.environ.get("UPDATE_GOLDEN"):
        GOLDEN_DIR.mkdir(exist_ok=True)
        golden.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n")
    assert json.loads(golden.read_text()) == snapshot
