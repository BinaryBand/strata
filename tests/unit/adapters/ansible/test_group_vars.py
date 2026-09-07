"""Unit tests for strata.adapters.ansible.group_vars.

Every read/write goes to a scratch all.yml via monkeypatched ``_GROUP_VARS``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from strata.adapters.ansible import group_vars


@pytest.fixture(autouse=True)
def all_yml(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Redirect group_vars reads/writes to a scratch all.yml."""
    path = tmp_path / "group_vars" / "all.yml"
    monkeypatch.setattr(group_vars, "_GROUP_VARS", path)
    return path


# ── load() ────────────────────────────────────────────────────────────


def test_load_missing_file_returns_empty_dict() -> None:
    assert group_vars.load() == {}


def test_load_empty_file_returns_empty_dict(all_yml: Path) -> None:
    all_yml.parent.mkdir(parents=True)
    all_yml.write_text("")
    assert group_vars.load() == {}


def test_load_comments_only_file_returns_empty_dict(all_yml: Path) -> None:
    all_yml.parent.mkdir(parents=True)
    all_yml.write_text("# nothing but a comment\n")
    assert group_vars.load() == {}


def test_load_parses_nested_yaml(all_yml: Path) -> None:
    all_yml.parent.mkdir(parents=True)
    all_yml.write_text("rclone_remotes:\n  - pcloud\nports:\n  jellyfin: 8096\n")

    assert group_vars.load() == {"rclone_remotes": ["pcloud"], "ports": {"jellyfin": 8096}}


# ── save() ────────────────────────────────────────────────────────────


def test_save_creates_parent_directories(all_yml: Path) -> None:
    group_vars.save({"a": 1})
    assert all_yml.exists()


def test_save_round_trips_through_load() -> None:
    data = {"rclone_remotes": ["pcloud", "backup"], "nested": {"k": [1, 2]}}
    group_vars.save(data)
    assert group_vars.load() == data


def test_save_uses_block_style_not_flow_style(all_yml: Path) -> None:
    group_vars.save({"rclone_remotes": ["pcloud", "backup"]})

    text = all_yml.read_text()
    assert "- pcloud" in text
    assert "[" not in text


def test_save_replaces_the_whole_document() -> None:
    group_vars.save({"a": 1})
    group_vars.save({"b": 2})
    assert group_vars.load() == {"b": 2}


def test_save_preserves_non_ascii(all_yml: Path) -> None:
    group_vars.save({"note": "café"})
    assert "café" in all_yml.read_text()
    assert group_vars.load()["note"] == "café"


# ── set_var() ─────────────────────────────────────────────────────────


def test_set_var_on_missing_file_creates_it() -> None:
    group_vars.set_var("rclone_remotes", ["pcloud"])
    assert group_vars.load() == {"rclone_remotes": ["pcloud"]}


def test_set_var_leaves_other_keys_intact() -> None:
    group_vars.save({"a": 1, "b": 2})
    group_vars.set_var("c", 3)
    assert group_vars.load() == {"a": 1, "b": 2, "c": 3}


def test_set_var_overwrites_an_existing_key() -> None:
    group_vars.save({"a": 1})
    group_vars.set_var("a", 99)
    assert group_vars.load()["a"] == 99


def test_set_var_accepts_structured_values(all_yml: Path) -> None:
    group_vars.set_var("rclone_http_serves", [{"name": "pod", "path": "pcloud:P", "port": 8080}])

    assert yaml.safe_load(all_yml.read_text())["rclone_http_serves"] == [
        {"name": "pod", "path": "pcloud:P", "port": 8080}
    ]


def test_set_var_none_is_stored_not_dropped() -> None:
    group_vars.set_var("maybe", None)
    assert "maybe" in group_vars.load()
    assert group_vars.load()["maybe"] is None
