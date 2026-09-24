"""Shared helpers for the site validator: safe reads, TOML checks, front matter.

Standard library only.
"""

from __future__ import annotations

import json
import os
import stat
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


class Invalid(Exception):  # noqa: N818 -- reads as "raise Invalid(...)"
    """A file that is skipped, with the reason to report."""


@dataclass
class Result:
    """Zola content to write, the stylesheet, and every skipped file with its reason."""

    files: dict[str, str] = field(default_factory=dict)
    css: bytes | None = None
    rejected: list[tuple[str, str]] = field(default_factory=list)
    waiting: list[str] = field(default_factory=list)
    editions: int = 0
    stories: dict[str, list[dict]] = field(default_factory=dict)


def read_no_follow(root: Path, rel: str, limit: int) -> bytes:
    """root/rel's bytes; refuses a symlink at any step, a non-regular file, excess size."""
    parts = rel.split("/")
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in parts[:-1]:
            nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = nxt
        leaf = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    except OSError as exc:
        msg = "cannot be opened (a link, or not a file)"
        raise Invalid(msg) from exc
    finally:
        os.close(fd)
    with os.fdopen(leaf, "rb") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            msg = "not a regular file"
            raise Invalid(msg)
        data = handle.read(limit + 1)
    if len(data) > limit:
        msg = f"over {limit} bytes"
        raise Invalid(msg)
    return data


def load_toml(data: bytes) -> dict:
    """Parse TOML, or Invalid with the parser's reason."""
    try:
        return tomllib.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        msg = f"not valid TOML: {exc}"
        raise Invalid(msg) from exc


def keys(data: dict, required: set[str], optional: frozenset[str] | set[str] = frozenset()) -> None:
    """Require exactly these fields: every required one, and nothing unknown."""
    missing = required - data.keys()
    extra = data.keys() - required - optional
    if missing:
        msg = f"missing {', '.join(sorted(missing))}"
        raise Invalid(msg)
    if extra:
        msg = f"unknown field {', '.join(sorted(extra))}"
        raise Invalid(msg)


def text(value: object, name: str, most: int) -> str:
    """A non-empty string of at most `most` characters, stripped."""
    if not isinstance(value, str) or not value.strip() or len(value) > most:
        msg = f"{name} must be text of 1-{most} characters"
        raise Invalid(msg)
    return value.strip()


def texts(value: object, name: str, count: int, most: int) -> list[str]:
    """A list of at most `count` such strings."""
    if not isinstance(value, list) or len(value) > count:
        msg = f"{name} must be a list of at most {count} texts"
        raise Invalid(msg)
    return [text(v, name, most) for v in value]


def whole(value: object, name: str, low: int, high: int) -> int:
    """An integer (not a boolean) from low to high."""
    if not isinstance(value, int) or isinstance(value, bool) or not low <= value <= high:
        msg = f"{name} must be a whole number from {low} to {high}"
        raise Invalid(msg)
    return value


def toml_value(value: object) -> str:
    """A TOML literal for the plain values this module writes (JSON strings are TOML strings)."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        # Zola ends front matter at the next "+++", even inside a string; a "+"
        # written as an escape can never form one.
        return json.dumps(value, ensure_ascii=False).replace("+", "\\u002B")
    if isinstance(value, list):
        return "[" + ", ".join(toml_value(v) for v in value) + "]"
    if isinstance(value, dict):
        return "{ " + ", ".join(f"{k} = {toml_value(v)}" for k, v in value.items()) + " }"
    msg = f"cannot write {type(value).__name__}"
    raise TypeError(msg)


def front_matter(top: dict, extra: dict | None = None, body: str = "") -> str:
    """A Zola content file whose front matter this module alone composes."""
    lines = ["+++"] + [f"{k} = {toml_value(v)}" for k, v in top.items()]
    if extra:
        lines += ["[extra]"] + [f"{k} = {toml_value(v)}" for k, v in extra.items()]
    return "\n".join([*lines, "+++", body])


def names(folder: Path) -> list[str]:
    """The entries of a folder, sorted."""
    return sorted(entry.name for entry in folder.iterdir())
