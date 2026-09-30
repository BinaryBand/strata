"""Read and write values in ansible/inventory/group_vars/all/managed.yml."""

from strata.adapters import fs
from strata.core import paths

_GROUP_VARS = paths.GROUP_VARS_DIR / "all" / "managed.yml"


def load() -> dict:
    """Return the parsed group_vars/all/managed.yml mapping, or {} if absent/empty.

    Returns:
        The YAML document as a dict.
    """
    return fs.read_yaml(_GROUP_VARS)


def save(data: dict) -> None:
    """Write `data` to group_vars/all/managed.yml as block-style YAML.

    Args:
        data: The full replacement document for the `all` group.
    """
    fs.write_yaml(_GROUP_VARS, data)


def set_var(key: str, value: object) -> None:
    """Set one variable in group_vars/all/managed.yml, leaving the other keys intact.

    Args:
        key: Variable name to set.
        value: Value to store under `key`.
    """
    data = load()
    data[key] = value
    save(data)
