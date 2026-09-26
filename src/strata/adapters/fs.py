"""Filesystem writes that cannot leave a file half-written.

Every persistent file this project owns was written with Path.write_text,
which truncates before it writes. Interrupt it -- SIGINT at a prompt, a full
disk, a crash -- and the file is left empty or partial with no way back. That
is survivable for the XDG state file, which only caches the last target, and
not at all for ansible/inventory/group_vars/secrets/all.yml: that directory is
gitignored, so the vault file is the only copy of every credential the tool
has ever stored.

write_text renames a completed temporary file over the target instead, which
is atomic within a filesystem: a reader sees either the old contents or the
new ones, never a truncated file. The temporary is created in the target's own
directory precisely so the rename stays within one filesystem -- /tmp is
frequently a different one, where os.replace would fall back to a copy and
give the guarantee up.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def _mode_for(path: Path) -> int:
    """Mode the replacement should carry: the existing one, else a fresh create's."""
    if path.exists():
        return path.stat().st_mode & 0o7777
    umask = os.umask(0)
    os.umask(umask)
    return 0o666 & ~umask


def write_text(path: Path, text: str) -> None:
    """Write `text` to `path` atomically, creating parent directories.

    Args:
        path: Destination file. Its parent is created if absent.
        text: Full contents to write.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    # mkstemp rather than NamedTemporaryFile: the file has to outlive the
    # handle (it is renamed away, not deleted), and fdopen gives the fd a
    # context manager without the delete-on-close semantics to suppress.
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    tmp_path = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            # Flush through Python's buffer and then the OS cache, so the
            # rename cannot expose a file whose contents are still in flight
            # if the machine loses power immediately after.
            handle.flush()
            os.fsync(handle.fileno())
        # mkstemp creates with 0600, but write_text() replaces a file rather
        # than creating one, so the mode has to be carried across or a
        # rewrite would silently tighten permissions on hosts.ini and the
        # group_vars files. A file that does not exist yet gets what an
        # ordinary create would have given it.
        tmp_path.chmod(_mode_for(path))
        tmp_path.replace(path)
    finally:
        tmp_path.unlink(missing_ok=True)
