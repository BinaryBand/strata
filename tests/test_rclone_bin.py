"""The rclone units run whichever binary `rclone_bin` names.

The path used to be hard-coded as `/usr/bin/rclone` in both unit templates, so
a host that wanted a newer rclone than the distro's had to hand-edit the
generated units, and the next `enable_rclone` run rewrote them. The role
default keeps the distro path for every host that sets nothing; a host
overrides it in host_vars.
"""

from __future__ import annotations

import jinja2
import pytest
import yaml

from tests._ansible import ANSIBLE_DIR, PLAYBOOKS_DIR, iter_tasks

_ROLE = ANSIBLE_DIR / "roles" / "diot_systemd_units"
_BREW_RCLONE = "/home/linuxbrew/.linuxbrew/bin/rclone"
_ITEMS: dict[str, object] = {
    "rclone-mount.service.j2": "pcloud",
    "rclone-http.service.j2": {"path": "pcloud:Media", "port": 8083},
}


def _exec_start(template: str, variables: dict[str, object]) -> str:
    """Render a unit template and return its `ExecStart=` line."""
    source = (_ROLE / "templates" / template).read_text()
    rendered = jinja2.Template(source).render(item=_ITEMS[template], **variables)
    return next(line for line in rendered.splitlines() if line.startswith("ExecStart="))


def _installs_package(task: dict[str, object], name: str) -> bool:
    """Whether `task` is a package-module task installing exactly `name`."""
    args = task.get("ansible.builtin.package")
    return isinstance(args, dict) and args.get("name") == name


def _role_defaults() -> dict[str, object]:
    loaded = yaml.safe_load((_ROLE / "defaults" / "main.yml").read_text())
    assert isinstance(loaded, dict)
    return loaded


@pytest.mark.parametrize("template", sorted(_ITEMS))
def test_default_binary_is_the_distro_rclone(template: str) -> None:
    """A host that sets nothing keeps running /usr/bin/rclone."""
    line = _exec_start(template, _role_defaults())
    assert line.startswith("ExecStart=/usr/bin/rclone ")


@pytest.mark.parametrize("template", sorted(_ITEMS))
def test_override_reaches_the_unit(template: str) -> None:
    """A host_vars override replaces the binary in the written ExecStart."""
    line = _exec_start(template, {"rclone_bin": _BREW_RCLONE})
    assert line.startswith(f"ExecStart={_BREW_RCLONE} ")


def test_distro_package_is_installed_only_for_the_distro_binary() -> None:
    """enable_rclone must not reinstall the distro rclone on a host that overrides it."""
    play = yaml.safe_load((PLAYBOOKS_DIR / "enable_rclone.yml").read_text())
    installs = [task for task in iter_tasks(play) if _installs_package(task, "rclone")]
    assert len(installs) == 1
    condition = str(installs[0].get("when", ""))
    assert "rclone_bin" in condition
    evaluated = jinja2.Environment().from_string("{{ " + condition + " }}")
    assert evaluated.render(rclone_bin=_BREW_RCLONE) == "False"
