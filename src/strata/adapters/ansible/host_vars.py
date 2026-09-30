"""Read and write values in ansible/inventory/host_vars/<host>.yml.

Mirrors group_vars.py, but scoped per host rather than the `all` group --
for facts that are true of one machine and must not leak to another (rclone
remotes, published SSH keys, ...). host_vars beats group_vars in Ansible's
precedence ladder, so relocating a var here overrides (rather than merges
with) any same-named group default.
"""

from pathlib import Path

from strata.adapters import fs
from strata.core import paths

_HOST_VARS_DIR = paths.HOST_VARS_DIR


def _path(host: str) -> Path:
    return _HOST_VARS_DIR / f"{host}.yml"


def load(host: str) -> dict:
    """Return the parsed host_vars file for `host`, or {} if it is absent or empty.

    Args:
        host: Inventory hostname whose host_vars file to read.

    Returns:
        The YAML document as a dict.
    """
    return fs.read_yaml(_path(host))


def save(host: str, data: dict) -> None:
    """Write `data` to `host`'s host_vars file as block-style YAML.

    Args:
        host: Inventory hostname the file belongs to.
        data: The full replacement document for that host.
    """
    fs.write_yaml(_path(host), data)


def discard(host: str) -> bool:
    """Delete `host`'s host_vars file. Returns False if there was none.

    Removing a device from the inventory used to leave its host_vars behind,
    so re-adding a hostname silently inherited the old host's rclone sync
    list and restic repository override.
    """
    path = _path(host)
    if not path.exists():
        return False
    path.unlink()
    return True


def set_var(host: str, key: str, value: object) -> None:
    """Set one variable in `host`'s host_vars file, leaving the other keys intact.

    Args:
        host: Inventory hostname to scope the variable to.
        key: Variable name to set.
        value: Value to store under `key`.
    """
    data = load(host)
    data[key] = value
    save(host, data)
