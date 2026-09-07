"""adapters: all I/O lives here.

ansible-runner, the vault, rclone, the inventory, subprocess, and the
filesystem. Each adapter is a concrete implementation of a Protocol declared
in core.ports. May import from core (to reference the ports); never from cli.
This package is a namespace shell; logic lives in its modules.
"""

from __future__ import annotations
