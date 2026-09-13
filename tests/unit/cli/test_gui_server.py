"""Unit tests for strata.cli.gui_server -- the GUI's data snapshot and server.

The snapshot is a wire format: gui/lib/data/strata_cli.dart parses it by key and
maps the guard `type` strings onto a Dart enum, falling back silently when it
meets one it doesn't know. Nothing but these tests keeps the two sides in step,
so the contract tests below assert the key set and that every requirement
dataclass has a label.
"""

from __future__ import annotations

import json
import threading
import typing
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from strata.cli import gui_server
from strata.core import requirements as req

# The keys gui/lib/data/strata_cli.dart reads out of each object. Changing a
# name here without changing the Dart side makes the GUI fall back to sample
# data at runtime, with no error anywhere.
_RUNBOOK_KEYS = {
    "dotted_name",
    "leaf",
    "category",
    "alias",
    "description",
    "accepts_tags",
    "has_check",
    "guards",
}
_DEVICE_KEYS = {"name", "host", "user", "connection", "port", "is_controller"}


# -- the snapshot --------------------------------------------------------


@pytest.fixture(scope="module")
def snapshot() -> dict:
    """The real snapshot, built once -- it imports every runbook module."""
    return gui_server.build_gui_data()


def test_snapshot_has_the_three_top_level_sections(snapshot: dict) -> None:
    assert set(snapshot) == {"runbooks", "import_failures", "devices"}


def test_snapshot_is_json_serializable(snapshot: dict) -> None:
    """The whole point is that it survives json.dumps for both consumers."""
    assert json.loads(json.dumps(snapshot)) == snapshot


def test_snapshot_finds_runbooks(snapshot: dict) -> None:
    dotted = {r["dotted_name"] for r in snapshot["runbooks"]}
    assert "services.install_jellyfin" in dotted


def test_every_runbook_carries_exactly_the_dart_keys(snapshot: dict) -> None:
    for runbook in snapshot["runbooks"]:
        assert set(runbook) == _RUNBOOK_KEYS, runbook["dotted_name"]


def test_every_device_carries_exactly_the_dart_keys(snapshot: dict) -> None:
    for device in snapshot["devices"]:
        assert set(device) == _DEVICE_KEYS, device


def test_guards_are_type_and_label_pairs(snapshot: dict) -> None:
    for runbook in snapshot["runbooks"]:
        for guard in runbook["guards"]:
            assert set(guard) == {"type", "label"}
            assert guard["label"], f"empty label for {guard['type']}"


def test_jellyfin_guard_chain_is_reported_in_declaration_order(snapshot: dict) -> None:
    """Order matters: the GUI renders the chain as the sequence it will run."""
    jellyfin = next(
        r for r in snapshot["runbooks"] if r["dotted_name"] == "services.install_jellyfin"
    )
    types = [g["type"] for g in jellyfin["guards"]]
    assert types, "install_jellyfin declares guards"
    assert types.index("Prerequisite") < types.index("LocalPath")


# -- the guard-label contract -------------------------------------------


def test_every_requirement_type_has_a_label() -> None:
    """A new @guard.* with no labeler silently renders as its class name.

    _guard_label falls back to type(r).__name__, and the Dart side falls back to
    GuardType.requires for an unknown type string -- two silent degradations
    that would let a new requirement reach the GUI looking like a dependency on
    another runbook. Driven off the Requirement union itself, so adding a member
    there without a label fails here.
    """
    declared = set(typing.get_args(req.Requirement))
    assert declared, "Requirement is a union; get_args should not be empty"
    missing = sorted(t.__name__ for t in declared - set(gui_server._GUARD_LABELERS))
    assert not missing, (
        f"requirement types with no gui_server label: {missing}. "
        "Add one to _GUARD_LABELERS and a GuardType to gui/lib/data/strata_cli.dart."
    )


def test_no_stale_labelers() -> None:
    """The inverse: a labeler for a type no longer in the union is dead code."""
    stale = sorted(
        t.__name__ for t in set(gui_server._GUARD_LABELERS) - set(typing.get_args(req.Requirement))
    )
    assert not stale, f"labelers for types no longer in Requirement: {stale}"


def test_sudo_password_prerequisite_gets_the_friendly_label() -> None:
    assert gui_server._guard_label(req.Prerequisite("sudo_password")) == "Sudo password"


def test_other_prerequisites_keep_their_name() -> None:
    assert gui_server._guard_label(req.Prerequisite("podman")) == "Prerequisite: podman"


# -- description formatting ---------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Runbook: install jellyfin.", "Install jellyfin."),
        ("Runbook:install jellyfin.", "Install jellyfin."),
        ("install jellyfin.", "Install jellyfin."),
        ("", ""),
        ("Runbook:", ""),
    ],
)
def test_description_strips_prefix_and_capitalizes(raw: str, expected: str) -> None:
    assert gui_server._description(raw) == expected


# -- the server ---------------------------------------------------------


@pytest.fixture
def served(tmp_path: Path) -> str:
    """Run `serve` on an ephemeral port in a thread; yield its base URL.

    Port 0 lets the kernel pick, so a developer already running `strata gui`
    doesn't collide with the suite. The daemon thread dies with the session;
    ThreadingHTTPServer has no clean cross-version shutdown from inside a
    KeyboardInterrupt-suppressing serve().
    """
    (tmp_path / "index.html").write_text("<!doctype html><title>stub</title>")
    urls: list[str] = []
    ready = threading.Event()

    def announce(line: str) -> None:
        urls.append(line.rsplit(" on ", 1)[1].split(" ", maxsplit=1)[0])
        ready.set()

    thread = threading.Thread(
        target=gui_server.serve,
        args=(tmp_path,),
        kwargs={"port": 0, "open_browser": False, "announce": announce},
        daemon=True,
    )
    thread.start()
    assert ready.wait(timeout=5), "server never announced its URL"
    return urls[0]


def test_serve_hands_out_the_data_endpoint(served: str) -> None:
    with urllib.request.urlopen(f"{served}/api/gui-data", timeout=5) as response:
        assert response.headers["Content-Type"] == "application/json"
        payload = json.loads(response.read())
    assert set(payload) == {"runbooks", "import_failures", "devices"}


def test_serve_hands_out_static_files(served: str) -> None:
    with urllib.request.urlopen(f"{served}/index.html", timeout=5) as response:
        assert b"stub" in response.read()


def test_serve_404s_an_unknown_path(served: str) -> None:
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        urllib.request.urlopen(f"{served}/nope.js", timeout=5)
    assert excinfo.value.code == 404


def test_serve_announces_the_port_it_actually_bound(served: str) -> None:
    """With port 0 the kernel picks; the announced URL has to be the real one."""
    assert served.startswith("http://127.0.0.1:")
    assert int(served.rsplit(":", 1)[1]) > 0
