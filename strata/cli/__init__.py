"""cli: command-line entry points, argument parsing, and wiring.

Top of the stack and the composition root: commands construct concrete
adapters and pass them into core's use-case functions. The one place print()
is allowed. This package is a namespace shell -- logic lives in modules like
cli.main, never in this __init__.
"""

from __future__ import annotations
