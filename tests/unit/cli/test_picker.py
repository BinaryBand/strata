"""Unit tests for strata.cli.picker.

`_autocomplete` is the only seam over questionary, so every test replaces it
with a scripted fake that records each (message, choices, meta) call and pops a
queued answer. Nothing here touches prompt_toolkit or a real terminal. stdin is
forced to look like a tty because pytest's captured stdin is not one.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from strata.cli import picker
from strata.core.discovery import RunbookInfo, iter_runbooks
from strata.core.models import Device


@dataclass
class Picks:
    """A scripted stand-in for picker._autocomplete."""

    answers: list[str | None]
    calls: list[tuple[str, list[str], dict[str, str]]] = field(default_factory=list)

    def autocomplete(self, message: str, choices: list[str], meta: dict[str, str]) -> str | None:
        self.calls.append((message, list(choices), dict(meta)))
        return self.answers.pop(0)


@pytest.fixture
def picks(monkeypatch: pytest.MonkeyPatch) -> Picks:
    """Install a scripted _autocomplete on a pretend tty.

    The tty patch lives here rather than in its own fixture so tests do not
    have to carry an argument they never reference; the two non-interactive
    tests re-patch isatty in their own body, which runs after this.
    """
    monkeypatch.setattr(picker.sys.stdin, "isatty", lambda: True)
    scripted = Picks(answers=[])
    monkeypatch.setattr(picker, "_autocomplete", scripted.autocomplete)
    return scripted


# -- the non-interactive guard -------------------------------------------


def test_returns_none_when_stdin_is_not_a_tty(
    monkeypatch: pytest.MonkeyPatch, picks: Picks
) -> None:
    monkeypatch.setattr(picker.sys.stdin, "isatty", lambda: False)
    assert picker.pick_runbook() is None
    assert picks.calls == []


def test_returns_none_when_there_are_no_runbooks(
    monkeypatch: pytest.MonkeyPatch, picks: Picks
) -> None:
    monkeypatch.setattr(picker, "iter_runbooks", list)
    assert picker.pick_runbook() is None
    assert picks.calls == []


# -- the flat autocomplete flow ------------------------------------------


def test_flat_flow_maps_the_chosen_alias_back_to_the_dotted_name(picks: Picks) -> None:
    jellyfin = next(rb for rb in iter_runbooks() if rb.leaf == "install_jellyfin")
    picks.answers = [jellyfin.alias]
    assert picker.pick_runbook() == "services.install_jellyfin"
    assert len(picks.calls) == 1


def test_offers_every_runbook_alias_in_one_prompt(picks: Picks) -> None:
    jellyfin = next(rb for rb in iter_runbooks() if rb.leaf == "install_jellyfin")
    picks.answers = [jellyfin.alias]
    picker.pick_runbook()
    message, choices, _meta = picks.calls[0]
    assert message == "Runbook:"
    assert choices == [(rb.alias or rb.leaf) for rb in iter_runbooks()]


def test_meta_maps_each_alias_to_its_summary(picks: Picks) -> None:
    jellyfin = next(rb for rb in iter_runbooks() if rb.leaf == "install_jellyfin")
    picks.answers = [jellyfin.alias]
    picker.pick_runbook()
    _message, _choices, meta = picks.calls[0]
    assert meta.get(jellyfin.alias) == picker._summary(jellyfin)


def test_abort_returns_none(picks: Picks) -> None:
    picks.answers = [None]
    assert picker.pick_runbook() is None
    assert len(picks.calls) == 1


# -- choice rendering -----------------------------------------------------


def test_summary_drops_the_runbook_prefix() -> None:
    jellyfin = next(rb for rb in iter_runbooks() if rb.leaf == "install_jellyfin")
    assert jellyfin.docstring_first_line.startswith("Runbook:")
    assert picker._summary(jellyfin).startswith("deploy Jellyfin")


def test_summary_handles_a_root_level_runbook() -> None:
    root = RunbookInfo(
        dotted_name="loose",
        leaf="loose",
        category="",
        docstring_first_line="Runbook: a runbook with no category.",
        accepts_tags=False,
    )
    assert picker._summary(root) == "a runbook with no category."


# -- the host picker ------------------------------------------------------


@pytest.fixture
def host_select(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    """Install a scripted _select on a pretend tty and record what it was offered."""
    monkeypatch.setattr(picker.sys.stdin, "isatty", lambda: True)
    recorded: dict[str, object] = {}

    def fake_select(message: str, choices: list, default: str | None) -> str | None:
        recorded["message"] = message
        recorded["values"] = [str(c.value) for c in choices]
        recorded["default"] = default
        answer = recorded.get("answer")
        if answer is None:
            return None
        return str(answer) if answer is not None else None

    monkeypatch.setattr(picker, "_select", fake_select)
    return recorded


def test_pick_host_offers_every_inventory_host_with_the_default(
    monkeypatch: pytest.MonkeyPatch, host_select: dict[str, object]
) -> None:
    hosts = [
        Device(name="workstation", host="1.1.1.1", connection="local"),
        Device(name="nas", host="2.2.2.2", connection="ssh"),
    ]
    monkeypatch.setattr(picker.inventory, "all_hosts", lambda: hosts)
    host_select["answer"] = "nas"
    assert picker.pick_host(default="nas") == "nas"
    assert host_select["values"] == ["workstation", "nas"]
    assert host_select["default"] == "nas"


def test_pick_host_returns_none_off_a_tty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(picker.sys.stdin, "isatty", lambda: False)
    assert picker.pick_host() is None


def test_pick_host_returns_none_when_inventory_is_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(picker.inventory, "all_hosts", list)
    assert picker.pick_host() is None


def test_pick_host_ignores_a_default_not_in_inventory(
    monkeypatch: pytest.MonkeyPatch, host_select: dict[str, object]
) -> None:
    monkeypatch.setattr(
        picker.inventory, "all_hosts", lambda: [Device(name="workstation", host="1.1.1.1")]
    )
    host_select["answer"] = "workstation"
    picker.pick_host(default="ghost")
    assert host_select["default"] is None
