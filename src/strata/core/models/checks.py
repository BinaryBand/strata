"""Consistency checks the app declarations share."""

from __future__ import annotations

from collections import Counter
from collections.abc import Hashable, Iterable


def require_unique(what: str, values: Iterable[Hashable]) -> None:
    """Raise ValueError naming each of `values` that appears more than once."""
    repeated = sorted(str(value) for value, count in Counter(values).items() if count > 1)
    if repeated:
        msg = f"{what} must be unique; repeated: {', '.join(repeated)}"
        raise ValueError(msg)


def require_declared(what: str, path: str, dirs: list[str]) -> None:
    """Raise ValueError unless `path` is one of the declared `dirs`."""
    if path not in dirs:
        msg = (
            f"{what} path {path} is not one of the declared dirs; the directory a "
            "guard provisions and the one the container or backup uses must be the same"
        )
        raise ValueError(msg)
