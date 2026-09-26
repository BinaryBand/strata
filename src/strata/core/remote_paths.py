"""Translate rclone ``remote:subpath`` notation to local mountpoints.

Pure string manipulation over the agreed mount layout -- no rclone process, no
filesystem access. It lived in the rclone adapter next to the functions that do
shell out, which forced core code needing only a path translation to import an
adapter. Nothing here touches the outside world, so it belongs in core.
"""

from __future__ import annotations

import re

REMOTE_MOUNT_BASE = "/mnt/rclone"

_REMOTE_PATH_RE = re.compile(r"^([A-Za-z0-9_-]+):(.*)$")


def is_remote_path(path: str) -> bool:
    """Return True if *path* looks like ``remote:subpath``."""
    return bool(_REMOTE_PATH_RE.match(path))


def remote_name(path: str) -> str:
    """Return the remote portion of ``remote:subpath``, or the path unchanged."""
    return path.split(":", 1)[0]


def mount_root(remote: str) -> str:
    """Return the local mountpoint for *remote*, e.g. ``/mnt/rclone/pcloud``."""
    return f"{REMOTE_MOUNT_BASE}/{remote}"


def resolve(path: str) -> str:
    """Resolve a path to a local filesystem path.

    ``pcloud:Media/X`` -> ``/mnt/rclone/pcloud/Media/X``.
    Local paths pass through unchanged.
    """
    m = _REMOTE_PATH_RE.match(path)
    if not m:
        return path
    remote, subpath = m.group(1), m.group(2).lstrip("/")
    if subpath:
        return f"{mount_root(remote)}/{subpath}"
    return mount_root(remote)
