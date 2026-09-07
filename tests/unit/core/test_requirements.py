"""Unit tests for strata.core.requirements.

The module is plain frozen dataclasses plus a union alias, so there is little
behaviour to exercise. What these tests do protect are the two properties the
rest of the system relies on: the requirement records are immutable (a guard
decorator records one and the executor must not be able to mutate it), and the
``Requirement`` union stays in sync with the declared dataclasses -- a new
requirement type left out of the union would silently fail to type-check at the
executor's match statement.
"""

from __future__ import annotations

import dataclasses
import typing

import pytest

from strata.core import requirements

_DATACLASSES = [
    obj
    for obj in vars(requirements).values()
    if dataclasses.is_dataclass(obj) and isinstance(obj, type)
]


def test_module_declares_the_expected_requirement_types() -> None:
    assert {c.__name__ for c in _DATACLASSES} == {
        "Prerequisite",
        "Secret",
        "SystemUser",
        "LocalPath",
        "Mount",
        "Storage",
        "UpstreamRunbook",
        "ControllerOnly",
    }


@pytest.mark.parametrize("cls", _DATACLASSES, ids=lambda c: c.__name__)
def test_every_requirement_dataclass_is_frozen(cls: type) -> None:
    assert cls.__dataclass_params__.frozen is True  # ty: ignore[unresolved-attribute]


def test_requirement_union_covers_every_declared_dataclass() -> None:
    union_members = set(typing.get_args(requirements.Requirement))
    assert union_members == set(_DATACLASSES)


def test_frozen_instance_rejects_mutation() -> None:
    req = requirements.Prerequisite(name="sudo_password")
    with pytest.raises(dataclasses.FrozenInstanceError):
        req.name = "other"  # ty: ignore[invalid-assignment]


def test_requirements_attr_is_the_name_guards_attach() -> None:
    assert requirements.REQUIREMENTS_ATTR.startswith("__")

    def main() -> int:
        return 0

    setattr(main, requirements.REQUIREMENTS_ATTR, [requirements.Prerequisite(name="x")])
    assert getattr(main, requirements.REQUIREMENTS_ATTR) == [requirements.Prerequisite(name="x")]


def test_equality_is_by_value() -> None:
    a = requirements.Mount(remote_path="pcloud:Media", writable=False)
    b = requirements.Mount(remote_path="pcloud:Media", writable=False)
    c = requirements.Mount(remote_path="pcloud:Media", writable=True)
    assert a == b
    assert a != c


def test_frozen_requirements_are_hashable() -> None:
    reqs = {
        requirements.UpstreamRunbook(dotted_name="infrastructure.install_podman"),
        requirements.UpstreamRunbook(dotted_name="infrastructure.install_podman"),
    }
    assert len(reqs) == 1
