"""Unit tests for strata.adapters.ansible.rclone.

rclone is never invoked: ``proc.run`` is replaced with a fake that answers the
handful of subcommands this module uses. group_vars is exercised for real
against a scratch all.yml, so registration is asserted through the public
readers rather than through mock call counts.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from strata.adapters.ansible import group_vars, host_vars, rclone
from strata.core import remote_paths


class FakeRclone:
    """Answers `rclone listremotes|config show|config providers|config create`."""

    def __init__(self, remotes: dict[str, str] | None = None) -> None:
        self.remotes: dict[str, str] = dict(remotes or {})
        self.providers: list[str] | None = ["pcloud", "drive", "s3"]
        self.calls: list[list[str]] = []
        self.create_succeeds = True

    def __call__(self, argv, **kwargs) -> subprocess.CompletedProcess[str]:  # noqa: ARG002, PLR0911
        argv = list(argv)
        self.calls.append(argv)
        rest = argv[1:]
        if rest == ["listremotes"]:
            out = "".join(f"{n}:\n" for n in self.remotes)
            return subprocess.CompletedProcess(argv, 0, stdout=out, stderr="")
        if rest[:2] == ["config", "providers"]:
            if self.providers is None:
                return subprocess.CompletedProcess(argv, 1, stdout="", stderr="unsupported")
            body = json.dumps([{"Name": n} for n in self.providers])
            return subprocess.CompletedProcess(argv, 0, stdout=body, stderr="")
        if rest[:2] == ["config", "show"]:
            name = rest[2]
            if name not in self.remotes:
                return subprocess.CompletedProcess(argv, 1, stdout="", stderr="not found")
            out = f"[{name}]\ntype = {self.remotes[name]}\ntoken = xxx\n"
            return subprocess.CompletedProcess(argv, 0, stdout=out, stderr="")
        if rest[:2] == ["config", "create"]:
            name, backend = rest[2], rest[3]
            if not self.create_succeeds:
                return subprocess.CompletedProcess(argv, 1, stdout="", stderr="aborted")
            self.remotes[name] = backend
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
        msg = f"unexpected argv: {argv}"
        raise AssertionError(msg)


@pytest.fixture(autouse=True)
def all_yml(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setattr(group_vars, "_GROUP_VARS", tmp_path / "all.yml")
    return tmp_path / "all.yml"


@pytest.fixture(autouse=True)
def host_vars_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setattr(host_vars, "_HOST_VARS_DIR", tmp_path / "host_vars")
    return tmp_path / "host_vars"


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeRclone:
    fake = FakeRclone({"pcloud": "pcloud"})
    monkeypatch.setattr(rclone.proc, "run", fake)
    return fake


# ── has_remote() / remote_completion() / remote_type() ────────────────


def test_has_remote_true_for_a_configured_remote(fake: FakeRclone) -> None:
    assert rclone.has_remote("pcloud") is True
    assert fake.calls == [["rclone", "listremotes"]]


def test_has_remote_false_for_an_unknown_remote(fake: FakeRclone) -> None:  # noqa: ARG001
    assert rclone.has_remote("nope") is False


def test_remote_completion_strips_the_trailing_colon(fake: FakeRclone) -> None:
    fake.remotes["backup"] = "s3"
    assert rclone.remote_completion() == ["pcloud", "backup"]


def test_remote_completion_empty_when_rclone_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    def failing(argv, **kwargs) -> subprocess.CompletedProcess[str]:  # noqa: ARG001
        return subprocess.CompletedProcess(list(argv), 1, stdout="", stderr="boom")

    monkeypatch.setattr(rclone.proc, "run", failing)
    assert rclone.remote_completion() == []


@pytest.mark.usefixtures("fake")
def test_remote_type_returns_the_backend() -> None:
    assert rclone.remote_type("pcloud") == "pcloud"


def test_remote_type_none_for_unknown_remote(fake: FakeRclone) -> None:  # noqa: ARG001
    assert rclone.remote_type("nope") is None


def test_remote_type_none_when_config_has_no_type(monkeypatch: pytest.MonkeyPatch) -> None:
    def no_type(argv, **kwargs) -> subprocess.CompletedProcess[str]:  # noqa: ARG001
        return subprocess.CompletedProcess(list(argv), 0, stdout="[x]\ntoken = y\n", stderr="")

    monkeypatch.setattr(rclone.proc, "run", no_type)
    assert rclone.remote_type("x") is None


# ── add_to_config() / remove_from_config() ────────────────────────────


def test_add_registers_the_remote() -> None:
    rclone.add_to_config("pcloud")
    assert rclone.list_remotes() == ["pcloud"]
    assert rclone.is_writable("pcloud") is False


def test_add_is_idempotent() -> None:
    rclone.add_to_config("pcloud")
    rclone.add_to_config("pcloud")
    assert rclone.list_remotes() == ["pcloud"]


def test_add_writable_records_it_separately() -> None:
    rclone.add_to_config("backup", writable=True)
    assert rclone.list_remotes() == ["backup"]
    assert rclone.list_writable_remotes() == ["backup"]
    assert rclone.is_writable("backup") is True


def test_readding_read_only_demotes_a_writable_remote() -> None:
    rclone.add_to_config("backup", writable=True)
    rclone.add_to_config("backup")

    assert rclone.list_remotes() == ["backup"]
    assert rclone.is_writable("backup") is False


def test_promoting_an_existing_remote_to_writable() -> None:
    rclone.add_to_config("backup")
    rclone.add_to_config("backup", writable=True)
    assert rclone.is_writable("backup") is True


def test_demotion_leaves_other_writable_remotes_alone() -> None:
    rclone.add_to_config("backup", writable=True)
    rclone.add_to_config("scratch", writable=True)
    rclone.add_to_config("backup")

    assert rclone.list_writable_remotes() == ["scratch"]


def test_lists_are_empty_when_nothing_registered() -> None:
    assert rclone.list_remotes() == []
    assert rclone.list_writable_remotes() == []
    assert rclone.is_writable("pcloud") is False


def test_remove_unregisters_and_returns_true() -> None:
    rclone.add_to_config("pcloud")
    assert rclone.remove_from_config("pcloud") is True
    assert rclone.list_remotes() == []


def test_remove_also_drops_the_writable_flag() -> None:
    rclone.add_to_config("backup", writable=True)
    rclone.remove_from_config("backup")
    assert rclone.list_writable_remotes() == []


def test_remove_unknown_returns_false() -> None:
    rclone.add_to_config("pcloud")
    assert rclone.remove_from_config("nope") is False
    assert rclone.list_remotes() == ["pcloud"]


def test_registration_does_not_touch_rclone_itself(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(argv, **kwargs) -> None:  # noqa: ARG001
        msg = "rclone must not be invoked to record a remote"
        raise AssertionError(msg)

    monkeypatch.setattr(rclone.proc, "run", boom)
    rclone.add_to_config("pcloud", writable=True)
    rclone.remove_from_config("pcloud")


# ── HTTP serves ───────────────────────────────────────────────────────


def test_http_serves_empty_by_default() -> None:
    assert rclone.list_http_serves() == []


def test_add_http_serve_records_the_entry() -> None:
    rclone.add_http_serve("podcasts", "pcloud:Media/Podcasts", 8080)
    assert rclone.list_http_serves() == [
        {"name": "podcasts", "path": "pcloud:Media/Podcasts", "port": 8080}
    ]


def test_add_http_serve_includes_base_url_only_when_given() -> None:
    rclone.add_http_serve("podcasts", "pcloud:Media/Podcasts", 8080, base_url="/media/podcasts")
    assert rclone.list_http_serves()[0]["base_url"] == "/media/podcasts"


def test_add_http_serve_replaces_by_name() -> None:
    rclone.add_http_serve("podcasts", "pcloud:A", 8080)
    rclone.add_http_serve("podcasts", "pcloud:B", 8081)

    serves = rclone.list_http_serves()
    assert len(serves) == 1
    assert serves[0]["path"] == "pcloud:B"
    assert serves[0]["port"] == 8081


def test_add_http_serve_replacement_drops_a_stale_base_url() -> None:
    rclone.add_http_serve("podcasts", "pcloud:A", 8080, base_url="/old")
    rclone.add_http_serve("podcasts", "pcloud:A", 8080)
    assert "base_url" not in rclone.list_http_serves()[0]


def test_add_http_serve_keeps_other_serves() -> None:
    rclone.add_http_serve("podcasts", "pcloud:A", 8080)
    rclone.add_http_serve("books", "pcloud:B", 8081)
    rclone.add_http_serve("podcasts", "pcloud:C", 8082)

    names = [s["name"] for s in rclone.list_http_serves()]
    assert sorted(names) == ["books", "podcasts"]


def test_remove_http_serve_returns_true_and_drops_it() -> None:
    rclone.add_http_serve("podcasts", "pcloud:A", 8080)
    assert rclone.remove_http_serve("podcasts") is True
    assert rclone.list_http_serves() == []


def test_remove_http_serve_unknown_returns_false() -> None:
    rclone.add_http_serve("podcasts", "pcloud:A", 8080)
    assert rclone.remove_http_serve("books") is False
    assert len(rclone.list_http_serves()) == 1


def test_serves_and_remotes_are_stored_independently() -> None:
    rclone.add_to_config("pcloud")
    rclone.add_http_serve("podcasts", "pcloud:A", 8080)

    rclone.remove_http_serve("podcasts")
    assert rclone.list_remotes() == ["pcloud"]


# ── synced remotes ───────────────────────────────────────────────────


def test_synced_remotes_empty_by_default() -> None:
    assert rclone.list_synced_remotes("nas") == []


def test_add_synced_remote_registers_it() -> None:
    rclone.add_synced_remote("nas", "pcloud")
    assert rclone.list_synced_remotes("nas") == ["pcloud"]


def test_add_synced_remote_is_idempotent() -> None:
    rclone.add_synced_remote("nas", "pcloud")
    rclone.add_synced_remote("nas", "pcloud")
    assert rclone.list_synced_remotes("nas") == ["pcloud"]


def test_synced_remotes_are_scoped_per_host() -> None:
    rclone.add_synced_remote("nas", "pcloud")
    assert rclone.list_synced_remotes("workstation") == []


def test_remove_synced_remote_unregisters_and_returns_true() -> None:
    rclone.add_synced_remote("nas", "pcloud")
    assert rclone.remove_synced_remote("nas", "pcloud") is True
    assert rclone.list_synced_remotes("nas") == []


def test_remove_synced_remote_unknown_returns_false() -> None:
    rclone.add_synced_remote("nas", "pcloud")
    assert rclone.remove_synced_remote("nas", "nope") is False
    assert rclone.list_synced_remotes("nas") == ["pcloud"]


def test_synced_remotes_does_not_touch_rclone_itself(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(argv, **kwargs) -> None:  # noqa: ARG001
        msg = "rclone must not be invoked to record a synced remote"
        raise AssertionError(msg)

    monkeypatch.setattr(rclone.proc, "run", boom)
    rclone.add_synced_remote("nas", "pcloud")
    rclone.remove_synced_remote("nas", "pcloud")


# ── path translation re-exports ───────────────────────────────────────


def test_path_helpers_are_re_exported_from_core() -> None:
    assert rclone.resolve is remote_paths.resolve
    assert rclone.is_remote_path is remote_paths.is_remote_path
    assert rclone.mount_root is remote_paths.mount_root
    assert rclone.REMOTE_MOUNT_BASE == remote_paths.REMOTE_MOUNT_BASE


# ── _known_backend_types() ────────────────────────────────────────────


@pytest.mark.usefixtures("fake")
def test_known_backend_types_parses_the_provider_list() -> None:
    assert rclone._known_backend_types() == {"pcloud", "drive", "s3"}


def test_known_backend_types_empty_when_unsupported(fake: FakeRclone) -> None:
    fake.providers = None
    assert rclone._known_backend_types() == set()


def test_known_backend_types_empty_on_bad_json(monkeypatch: pytest.MonkeyPatch) -> None:
    def garbage(argv, **kwargs) -> subprocess.CompletedProcess[str]:  # noqa: ARG001
        return subprocess.CompletedProcess(list(argv), 0, stdout="not json", stderr="")

    monkeypatch.setattr(rclone.proc, "run", garbage)
    assert rclone._known_backend_types() == set()


# ── _guess_default_backend_type() ─────────────────────────────────────


def test_guess_prefers_pcloud(fake: FakeRclone) -> None:
    fake.remotes["other"] = "s3"
    assert rclone._guess_default_backend_type("new") == "pcloud"


def test_guess_falls_back_to_the_sole_other_remote(fake: FakeRclone) -> None:
    fake.remotes = {"backup": "s3"}
    assert rclone._guess_default_backend_type("new") == "s3"


def test_guess_is_none_with_no_other_remotes(fake: FakeRclone) -> None:
    fake.remotes = {}
    assert rclone._guess_default_backend_type("new") is None


def test_guess_ignores_the_remote_being_created(fake: FakeRclone) -> None:
    fake.remotes = {"pcloud": "pcloud"}
    assert rclone._guess_default_backend_type("pcloud") is None


def test_guess_is_none_with_several_ambiguous_remotes(fake: FakeRclone) -> None:
    fake.remotes = {"a": "s3", "b": "drive"}
    assert rclone._guess_default_backend_type("new") is None


# ── prompt_create_remote() ────────────────────────────────────────────


def _answers(monkeypatch: pytest.MonkeyPatch, values: list[str]) -> list[str]:
    remaining = list(values)

    def prompt(_message: str, default: str | None = None) -> str:  # noqa: ARG001
        return remaining.pop(0)

    monkeypatch.setattr(rclone.click, "prompt", prompt)
    monkeypatch.setattr(rclone.click, "echo", lambda *_a, **_k: None)
    return remaining


def test_prompt_create_remote_is_a_noop_when_configured(
    fake: FakeRclone, monkeypatch: pytest.MonkeyPatch
) -> None:
    _answers(monkeypatch, [])
    rclone.prompt_create_remote("pcloud")
    assert fake.calls == [["rclone", "listremotes"]]


def test_prompt_create_remote_creates_a_missing_remote(
    fake: FakeRclone, monkeypatch: pytest.MonkeyPatch
) -> None:
    _answers(monkeypatch, ["s3"])

    rclone.prompt_create_remote("backup")

    assert ["rclone", "config", "create", "backup", "s3"] in fake.calls
    assert fake.remotes["backup"] == "s3"


def test_prompt_create_remote_reprompts_on_an_unknown_backend(
    fake: FakeRclone, monkeypatch: pytest.MonkeyPatch
) -> None:
    remaining = _answers(monkeypatch, ["nosuchbackend", "s3"])

    rclone.prompt_create_remote("backup")

    assert remaining == []
    creates = [c for c in fake.calls if c[1:3] == ["config", "create"]]
    assert creates == [["rclone", "config", "create", "backup", "s3"]]


def test_prompt_create_remote_strips_whitespace_from_the_answer(
    fake: FakeRclone, monkeypatch: pytest.MonkeyPatch
) -> None:
    _answers(monkeypatch, ["  s3  "])
    rclone.prompt_create_remote("backup")
    assert fake.remotes["backup"] == "s3"


def test_prompt_create_remote_retries_when_create_fails(
    fake: FakeRclone, monkeypatch: pytest.MonkeyPatch
) -> None:
    remaining = _answers(monkeypatch, ["s3", "drive"])
    calls = {"n": 0}
    original = fake.__call__

    def flaky(argv, **kwargs) -> subprocess.CompletedProcess[str]:
        argv = list(argv)
        if argv[1:3] == ["config", "create"]:
            calls["n"] += 1
            if calls["n"] == 1:
                fake.calls.append(argv)
                return subprocess.CompletedProcess(argv, 1, stdout="", stderr="aborted")
        return original(argv, **kwargs)

    monkeypatch.setattr(rclone.proc, "run", flaky)

    rclone.prompt_create_remote("backup")

    assert remaining == []
    assert fake.remotes["backup"] == "drive"


def test_prompt_create_remote_skips_validation_when_providers_unavailable(
    fake: FakeRclone, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake.providers = None
    _answers(monkeypatch, ["anything"])

    rclone.prompt_create_remote("backup")
    assert fake.remotes["backup"] == "anything"


def test_has_remote_does_not_match_a_suffix(monkeypatch: pytest.MonkeyPatch) -> None:
    """`f"{name}:" in stdout` matched any remote *ending* in that name.

    With `pcloud` configured, has_remote("cloud") was True -- so the guard
    executor skipped creating the remote and `strata rclone add` registered a
    name rclone had never heard of, failing later at mount time.
    """
    monkeypatch.setattr(
        rclone.proc,
        "run",
        lambda *_a, **_kw: subprocess.CompletedProcess([], 0, stdout="pcloud:\n", stderr=""),
    )

    assert rclone.has_remote("pcloud") is True
    assert rclone.has_remote("cloud") is False


def test_has_remote_is_false_when_rclone_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """A non-zero exit was ignored, so a broken rclone read as 'absent'."""
    monkeypatch.setattr(
        rclone.proc,
        "run",
        lambda *_a, **_kw: subprocess.CompletedProcess([], 1, stdout="", stderr="boom"),
    )

    assert rclone.has_remote("pcloud") is False
