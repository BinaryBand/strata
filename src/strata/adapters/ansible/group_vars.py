"""Read and write values in ansible/inventory/group_vars/all/managed.yml."""

import yaml

from strata.adapters import fs
from strata.core import paths

_GROUP_VARS = paths.GROUP_VARS_DIR / "all" / "managed.yml"


def load() -> dict:
    """Return the parsed group_vars/all/managed.yml mapping, or {} if absent/empty.

    Returns:
        The YAML document as a dict.
    """
    if not _GROUP_VARS.exists():
        return {}
    return yaml.safe_load(_GROUP_VARS.read_text()) or {}


def save(data: dict) -> None:
    """Write `data` to group_vars/all/managed.yml as block-style YAML, creating parent dirs.

    Args:
        data: The full replacement document for the `all` group.
    """
    _GROUP_VARS.parent.mkdir(parents=True, exist_ok=True)
    # sort_keys=False: yaml.dump sorts alphabetically by default, so every
    # single-key change rewrote the whole tracked file in a new order and
    # produced a full-file diff. Preserving insertion order keeps a set_var
    # to a one-line diff.
    fs.write_text(
        _GROUP_VARS,
        yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False),
    )


def set_var(key: str, value: object) -> None:
    """Set one variable in group_vars/all/managed.yml, leaving the other keys intact.

    Args:
        key: Variable name to set.
        value: Value to store under `key`.
    """
    data = load()
    data[key] = value
    save(data)
