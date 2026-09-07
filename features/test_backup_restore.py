"""pytest-bdd binding for features/backup_restore.feature (Stage 4).

What is real here: the CLI entry point, name resolution, `--tags` parsing, the
real `guard_executor`, and both runbooks' own `selected_backup_paths()` walk
over the `@guard.backup_tag` declarations on the services runbooks. That walk
is the thing under test -- which tags exist, what each maps to, and that the
static `config` tag survives every selection.

What is faked, at the same seams the rest of the suite uses: the adapter
fakes from `_guard_harness` (runner, secrets, prompts, passwd, inventory), so
no playbook, vault or container is touched. The one upstream guard
(`infrastructure.install_restic`) is satisfied honestly rather than stubbed --
its real `check()` returns True once the vaulted repository path holds a
`config` file, so the Background seeds exactly that.

Deliberately not asserted here: that the config tag is captured as root while
app tags run as diot, that the tag is skipped where the path is absent, and
restic's overwrite-but-never-delete semantics. All three are properties of
backup.yml / restore.yml, invisible from Python, and belong to the @integration
scenario at the foot of the feature.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

# Adapter fakes: imported for their autouse fixture, same seam layer the
# guard_resolution binding drives.
from features._guard_harness import _isolate_guards  # noqa: F401
from strata.adapters import state
from strata.adapters.ansible import secrets
from strata.cli import dispatch
from strata.core import paths
from strata.core.models import Device

scenarios("backup_restore.feature")


@pytest.fixture(autouse=True)
def _isolate_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect the XDG state file into tmp.

    cli.dispatch.run_runbook persists `last_target` on every run with an
    explicit --target, and falls back to the stored value without one. Without
    this the suite would both read and overwrite the operator's real
    ~/.local/state/strata/state.json.
    """
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setattr(state, "_OLD_CONFIG_FILE", tmp_path / "no-legacy.json")


_BACKUP = "playbooks/backup.yml"
_RESTORE = "playbooks/restore.yml"


def _runs(ctx: dict[str, Any], playbook: str) -> list[dict[str, Any]]:
    return [p for p in ctx["playbooks"] if p["playbook"] == playbook]


def _paths_of(ctx: dict[str, Any], playbook: str) -> dict[str, str]:
    """The backup_paths extravar the named playbook was handed."""
    runs = _runs(ctx, playbook)
    assert runs, f"{playbook} was never run; ran: {[p['playbook'] for p in ctx['playbooks']]}"
    return dict(runs[-1]["extravars"]["backup_paths"])


def _last_paths(ctx: dict[str, Any]) -> dict[str, str]:
    for playbook in (_BACKUP, _RESTORE):
        if _runs(ctx, playbook):
            return _paths_of(ctx, playbook)
    msg = "neither backup.yml nor restore.yml was run"
    raise AssertionError(msg)


# ── Given ─────────────────────────────────────────────────────────────────


@given("restic is already initialized for the host")
def restic_initialized(ctx: dict[str, Any], tmp_path: Path) -> None:
    """Satisfy @guard.requires("infrastructure.install_restic") through its real check().

    install_restic.check() reads `restic_repository` from the vault and looks
    for a `config` file at that path -- restic writes one on init. Seeding both
    makes the upstream genuinely satisfied, so the executor short-circuits it
    instead of us stubbing the dependency away.
    """
    repo = tmp_path / "restic-repo"
    repo.mkdir()
    (repo / "config").write_text("")
    ctx["vault"]["restic_repository"] = str(repo)
    ctx["vault"]["restic_password"] = "pw"
    ctx["vault"]["sudo_password"] = "sudo-pw"
    # The upstream fast path is gated on _is_controller(target): an unknown
    # host is not the controller, so without this the executor skips check()
    # and provisions the whole restic chain instead of short-circuiting it.
    ctx["device_for"] = {
        "localhost": Device(name="localhost", host="127.0.0.1", user="operator", connection="local")
    }
    # check() resolves the vaulted value through remote_paths.resolve; a plain
    # local path passes through unchanged, so no rclone fake is involved.
    assert secrets.get_secret("restic_repository") == str(repo)


@given("the target is a remote ssh host")
def target_is_remote(ctx: dict[str, Any]) -> None:
    """A host the inventory reports as ansible_connection=ssh.

    Remote targeting is the point of `strata device add` + `--target`, so the
    backup path has to be exercised against one. It also turns every local
    fast path off, which is why the upstream restic chain provisions here
    instead of short-circuiting the way it does on the controller.
    """
    ctx["device_for"] = {
        "nas": Device(name="nas", host="192.168.1.20", user="nas", connection="ssh")
    }


# ── When ──────────────────────────────────────────────────────────────────


# parsers.re, not parsers.parse: `{name}` is greedy enough that the plain form
# also matched the --tags form, swallowing "--tags jellyfin" into the runbook
# name. Constraining the name to dotted-identifier characters keeps the two
# step forms disjoint.
@when(parsers.re(r'I run "strata runbook (?P<name>[\w.]+) --target (?P<target>[\w.-]+)"$'))
def run_runbook(ctx: dict[str, Any], name: str, target: str) -> None:
    _dispatch(ctx, name, target=target, tags=None)


@when(
    parsers.re(
        r'I run "strata runbook (?P<name>[\w.]+) --tags (?P<tags>[\w,]+)'
        r' --target (?P<target>[\w.-]+)"$'
    )
)
def run_runbook_with_tags(ctx: dict[str, Any], name: str, tags: str, target: str) -> None:
    _dispatch(ctx, name, target=target, tags=tags)


@when("I run a backup and a restore with the same tags")
def run_both(ctx: dict[str, Any]) -> None:
    _dispatch(ctx, "infrastructure.backup", target="localhost", tags="jellyfin")
    _dispatch(ctx, "infrastructure.restore", target="localhost", tags="jellyfin")


def _dispatch(ctx: dict[str, Any], name: str, *, target: str, tags: str | None) -> None:
    """Drive the real cli.dispatch.run_runbook, capturing whatever it raises."""
    try:
        ctx["exit_code"] = dispatch.run_runbook(name, target=target, tags=tags)
    except Exception as exc:  # noqa: BLE001 - scenarios assert on what was raised
        ctx["error"] = exc


# ── Then ──────────────────────────────────────────────────────────────────


@then(parsers.re(r"(?P<playbook>[\w.]+\.yml) is run$"))
def playbook_is_run(ctx: dict[str, Any], playbook: str) -> None:
    assert _runs(ctx, f"playbooks/{playbook}"), (
        f"{playbook} not among {[p['playbook'] for p in ctx['playbooks']]}"
    )


@then(parsers.re(r'(?P<playbook>[\w.]+\.yml) is run against "(?P<target>[\w.-]+)"$'))
def playbook_run_against(ctx: dict[str, Any], playbook: str, target: str) -> None:
    """The --target must reach run_playbook, or a remote run would hit the controller."""
    runs = _runs(ctx, f"playbooks/{playbook}")
    assert runs, f"{playbook} not among {[p['playbook'] for p in ctx['playbooks']]}"
    assert runs[-1]["target"] == target, runs[-1]


@then(parsers.parse('the backup paths include "{tag}" at "{path}"'))
def paths_include(ctx: dict[str, Any], tag: str, path: str) -> None:
    assert _last_paths(ctx).get(tag) == path


@then(parsers.parse('the backup paths include the "{tag}" tag pointing at ansible/inventory'))
def paths_include_config(ctx: dict[str, Any], tag: str) -> None:
    assert _last_paths(ctx).get(tag) == str(paths.INVENTORY_DIR)


@then(parsers.parse('the backup paths cover exactly "{expected}"'))
def paths_cover_exactly(ctx: dict[str, Any], expected: str) -> None:
    wanted = sorted(t.strip() for t in expected.split(",") if t.strip())
    assert sorted(_last_paths(ctx)) == wanted


@then(parsers.parse('it fails reporting the unknown tag "{tag}"'))
def fails_unknown_tag(ctx: dict[str, Any], tag: str) -> None:
    error = ctx.get("error")
    assert isinstance(error, ValueError), f"expected ValueError, got {error!r}"
    assert tag in str(error)


@then("no playbook is run")
def no_playbook_run(ctx: dict[str, Any]) -> None:
    assert ctx["playbooks"] == [], ctx["playbooks"]


@then("no resolved repository path is passed as an extravar")
def no_repository_extravar(ctx: dict[str, Any]) -> None:
    """The repository is resolved per host inside the playbook, by design.

    Passing a controller-resolved path would silently point every remote host
    at the controller's repository.
    """
    extravars = _runs(ctx, _BACKUP)[-1]["extravars"]
    assert set(extravars) == {"backup_paths"}, extravars


@then("both playbooks receive identical backup paths")
def both_identical(ctx: dict[str, Any]) -> None:
    assert _paths_of(ctx, _BACKUP) == _paths_of(ctx, _RESTORE)
