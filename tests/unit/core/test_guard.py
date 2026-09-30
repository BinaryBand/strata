"""Unit tests for requirement declaration.

Guards only record data here; the executor that acts on it is tested in
tests/unit/adapters/test_guard_executor.py.
"""

from __future__ import annotations

from strata.core import guard


def _plain() -> int:
    return 0


def test_backup_tag_records_the_pair_without_wrapping() -> None:
    decorated = guard.backup_tag("app", "/srv/app")(_plain)
    assert decorated is _plain
    assert guard.backup_tags_of(_plain) == (("app", "/srv/app"),)


def test_backup_tags_accumulate_in_decorator_order() -> None:
    def fn() -> int:
        return 0

    guard.backup_tag("second", "/srv/two")(fn)
    guard.backup_tag("third", "/srv/three")(fn)
    assert guard.backup_tags_of(fn) == (("second", "/srv/two"), ("third", "/srv/three"))


def test_a_function_with_no_backup_tag_declares_none() -> None:
    assert guard.backup_tags_of(lambda: 0) == ()
