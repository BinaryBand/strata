"""core: runbooks, models, guards, and the port interfaces.

Bottom of the stack: no I/O and no imports from the other layers -- the
import-linter contract guarantees this. This package is a namespace shell;
logic lives in its modules, never in this __init__.

Cross-layer interfaces live in core/ports.py as typing.Protocol classes.
A port declares the shape an adapter must satisfy; the concrete
implementation lives in adapters, and cli -- the composition root --
constructs it and passes it in. Because core may not import adapters, the
dependency always points inward, and ty verifies structurally that each
adapter satisfies its port at the call site.
"""

from __future__ import annotations
