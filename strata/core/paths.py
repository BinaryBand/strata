"""Filesystem anchors for the repo's non-Python assets.

Every module that needed to reach ansible/ or static/ used to recompute the
repo root itself as ``Path(__file__).resolve().parents[N]``. N depends on how
deep the module sits, so moving a file silently changed where it looked --
nothing type-checks an integer index, and most of these paths are only read at
runtime. Anchoring the root once here means a module can move between layers
without its asset paths quietly following it.
"""

from __future__ import annotations

from pathlib import Path

# strata/core/paths.py -> strata/core -> strata -> repo root.
PROJECT_ROOT = Path(__file__).resolve().parents[2]

ANSIBLE_DIR = PROJECT_ROOT / "ansible"
INVENTORY_DIR = ANSIBLE_DIR / "inventory"
GROUP_VARS_DIR = INVENTORY_DIR / "group_vars"
HOST_VARS_DIR = INVENTORY_DIR / "host_vars"
STATIC_DIR = PROJECT_ROOT / "static"
