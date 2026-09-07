"""pytest-bdd binding for features/guard_resolution.feature (the prompt engine).

Unlike the other feature bindings, these scenarios do not go through the
`strata` CLI. Almost every one needs a runbook declaring a *particular*
combination of guards -- three paths where the second fails, an unregistered
prerequisite name, a generate-on-blank secret -- and no real runbook declares
those. So each scenario builds a synthetic runbook and hands it to the real
`guard_executor.execute()`, which is exactly what `cli/dispatch.py` does with
an imported module. The CLI's own wiring is covered by runbook_dispatch.feature.

What is faked is the leaf adapters the executor imports directly -- `secrets`,
`rclone`, `runner`, `inventory` -- plus the two prompt calls. Everything
between (`declared()` ordering, `_is_controller` gating, `_path_satisfied`,
the dispatch table, upstream recursion) is the production code path. This is
the pattern from tests/unit/adapters/test_guard_executor.py rather than
Stage 2's, which fakes `execute` wholesale -- the very thing under test here.

The controller-only refusal message was checked against the real CLI by hand
(`strata runbook install_flatpak --target nas`) before these were written.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from features._guard_harness import (
    CREATE_DIOT,
    ENABLE_RCLONE,
    ENSURE_PATH,
    # Imported for its side effect: an autouse fixture only applies where its
    # name is bound, so this is what installs the adapter fakes here.
    _isolate_guards,  # noqa: F401
    install_upstream,
    run_declared,
)
from strata.core import guard
from strata.core.models import Device

scenarios("guard_resolution.feature")


# ── Given: target ─────────────────────────────────────────────────────────


@given("the target is the controller")
def target_is_controller(ctx: dict[str, Any]) -> None:
    """target=None is the pre-inventory controller default."""
    ctx["target"] = None


@given("the target is a remote ssh host")
def target_is_remote(ctx: dict[str, Any]) -> None:
    ctx["target"] = "nas"
    ctx["device_for"] = {"nas": Device(name="nas", host="10.0.0.9", user="nas", connection="ssh")}


# ── Given: ordering and short-circuit ─────────────────────────────────────


@given("a runbook declares a sudo prerequisite then an upstream runbook then a path")
def declares_three_kinds(ctx: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    install_upstream(ctx, monkeypatch, check=None)
    ctx["decorators"] = [
        guard.prerequisite("sudo_password"),
        guard.requires("infrastructure.install_podman"),
        guard.path("/srv/demo"),
    ]


@given("a runbook declares three path requirements")
def declares_three_paths(ctx: dict[str, Any]) -> None:
    ctx["decorators"] = [guard.path(f"/srv/demo/{n}") for n in ("one", "two", "three")]


@given(parsers.parse("the second path's playbook exits {code:d}"))
def second_path_fails(ctx: dict[str, Any], code: int) -> None:
    """Each path runs the same ensure_path.yml, so fail on its second call."""
    calls = {"n": 0}

    def rc_for(playbook: str) -> int:
        if playbook != ENSURE_PATH:
            return 0
        calls["n"] += 1
        return code if calls["n"] == 2 else 0

    ctx["playbook_rc"] = rc_for


# ── Given: controller-only ────────────────────────────────────────────────


@given(parsers.parse('a runbook is controller-only because "{reason}"'))
def declares_controller_only(ctx: dict[str, Any], reason: str) -> None:
    ctx["reason"] = reason
    ctx["decorators"] = [guard.controller_only(reason)]


# ── Given: prerequisites ──────────────────────────────────────────────────


@given(parsers.parse('"{key}" is not in the vault'))
@given(parsers.parse('the secret "{key}" is not in the vault'))
def secret_absent(ctx: dict[str, Any], key: str) -> None:
    ctx["vault"].pop(key, None)
    ctx["secret_key"] = key


@given(parsers.parse('"{key}" is already in the vault'))
def secret_present(ctx: dict[str, Any], key: str) -> None:
    ctx["vault"][key] = "already-set"
    ctx["secret_key"] = key


@given(parsers.parse('a runbook declares an unknown prerequisite "{name}"'))
def declares_unknown_prerequisite(ctx: dict[str, Any], name: str) -> None:
    ctx["unknown_prerequisite"] = name
    ctx["decorators"] = [guard.prerequisite(name)]


# ── Given: secrets ────────────────────────────────────────────────────────


@given(parsers.parse('it declares a default of "{default}"'))
def secret_default(ctx: dict[str, Any], default: str) -> None:
    ctx["secret_default"] = default


@given("it declares no default")
def secret_no_default(ctx: dict[str, Any]) -> None:
    ctx["secret_default"] = None


@given("it is a password-kind secret")
def secret_is_password(ctx: dict[str, Any]) -> None:
    ctx["secret_kind"] = "password"


@given("it declares generate-on-blank")
def secret_generates(ctx: dict[str, Any]) -> None:
    ctx["secret_generate"] = True


# ── Given: paths ──────────────────────────────────────────────────────────


@given(parsers.parse('"{path}" already exists with the right owner, group and mode'))
def path_satisfied(ctx: dict[str, Any], path: str, tmp_path: Path) -> None:
    """A real directory with no ownership constraints declared is satisfied."""
    real = tmp_path / path.lstrip("/")
    real.mkdir(parents=True)
    ctx["decorators"] = [guard.path(str(real))]


@given(parsers.parse('"{path}" exists but is owned by the wrong user'))
def path_wrong_owner(ctx: dict[str, Any], path: str, tmp_path: Path) -> None:
    real = tmp_path / path.lstrip("/")
    real.mkdir(parents=True)
    ctx["decorators"] = [guard.path(str(real), owner="root")]


# ── Given: mounts ─────────────────────────────────────────────────────────


@given(parsers.parse('the mount "{remote_path}" is required'))
def mount_required(ctx: dict[str, Any], remote_path: str) -> None:
    ctx["decorators"] = [guard.mount(remote_path)]


@given(parsers.parse('rclone does not know the remote "{name}"'))
def rclone_unknown(ctx: dict[str, Any], name: str) -> None:
    ctx["rclone_known"].discard(name)
    ctx["rclone_listed"].discard(name)


@given(parsers.parse('the remote "{name}" is registered read-only'))
def remote_read_only(ctx: dict[str, Any], name: str) -> None:
    ctx["rclone_known"].add(name)
    ctx["rclone_listed"].add(name)
    ctx["rclone_writable"].discard(name)


@given(parsers.parse('"{remote_path}" is already mounted'))
def already_mounted(ctx: dict[str, Any], remote_path: str, tmp_path: Path) -> None:
    ctx["mounted"].add(remote_path)
    ctx["mount_root"] = tmp_path / "mnt"
    ctx["mount_root"].mkdir()
    ctx["decorators"] = [guard.mount(remote_path)]


# ── Given: storage ────────────────────────────────────────────────────────


@given(parsers.re(r'^the storage secret "(?P<key>[^"]+)" holds "(?P<value>[^"]*)"$'))
def storage_holds(ctx: dict[str, Any], key: str, value: str) -> None:
    ctx["vault"][key] = value
    ctx["storage_key"] = key


@given(parsers.parse('the storage secret "{key}" holds a local directory'))
def storage_holds_local(ctx: dict[str, Any], key: str, tmp_path: Path) -> None:
    local = tmp_path / "repo"
    ctx["vault"][key] = str(local)
    ctx["storage_key"] = key


@given("the runbook requires that storage to be writable")
def storage_requires_writable(ctx: dict[str, Any]) -> None:
    ctx["storage_writable"] = True


# ── Given: system users ───────────────────────────────────────────────────


@given(parsers.parse('the "{username}" user already exists'))
def user_exists(ctx: dict[str, Any], username: str) -> None:
    ctx["users"].add(username)


@given(parsers.parse('the "{username}" user does not exist'))
def user_absent(ctx: dict[str, Any], username: str) -> None:
    ctx["users"].discard(username)


# ── Given: upstream runbooks ──────────────────────────────────────────────


@given("install_jellyfin requires install_podman upstream")
def jellyfin_requires_podman(ctx: dict[str, Any]) -> None:
    ctx["decorators"] = [guard.requires("infrastructure.install_podman")]


@given("install_podman's check() reports it is not satisfied")
def upstream_unsatisfied(ctx: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    install_upstream(ctx, monkeypatch, check=lambda: False)


@given("install_podman's check() reports it is satisfied on the controller")
def upstream_satisfied(ctx: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    install_upstream(ctx, monkeypatch, check=lambda: True)
    ctx["decorators"] = [guard.requires("infrastructure.install_podman")]


@given(parsers.parse("install_podman's check() raises {error}"))
def upstream_check_raises(ctx: dict[str, Any], monkeypatch: pytest.MonkeyPatch, error: str) -> None:
    exc_type = {"OSError": OSError, "RuntimeError": RuntimeError}[error]

    def boom() -> bool:
        msg = "cannot tell"
        raise exc_type(msg)

    install_upstream(ctx, monkeypatch, check=boom)
    ctx["decorators"] = [guard.requires("infrastructure.install_podman")]


# ── When ──────────────────────────────────────────────────────────────────


@when("I run that runbook")
@when("I run install_jellyfin")
def run_that_runbook(ctx: dict[str, Any]) -> None:
    run_declared(ctx)


@when("I run a runbook requiring the sudo prerequisite")
def run_requiring_sudo(ctx: dict[str, Any]) -> None:
    ctx["decorators"] = [guard.prerequisite("sudo_password")]
    run_declared(ctx)


@when(parsers.re(r'^I run a runbook requiring that secret and answer "(?P<answer>[^"]*)"$'))
def run_requiring_secret(ctx: dict[str, Any], answer: str) -> None:
    ctx["answers"] = [answer]
    _run_secret(ctx)


@when(
    parsers.re(
        r'^I run a runbook requiring that secret and answer "(?P<first>[^"]*)"'
        r' then "(?P<second>[^"]*)"$'
    )
)
def run_requiring_secret_twice(ctx: dict[str, Any], first: str, second: str) -> None:
    ctx["answers"] = [first, second]
    _run_secret(ctx)


def _run_secret(ctx: dict[str, Any]) -> None:
    ctx["decorators"] = [
        guard.secret(
            ctx["secret_key"],
            kind=ctx.get("secret_kind", "text"),
            default=ctx.get("secret_default"),
            generate=ctx.get("secret_generate", False),
        )
    ]
    run_declared(ctx)


@when("I run a runbook requiring that path")
def run_requiring_that_path(ctx: dict[str, Any]) -> None:
    run_declared(ctx)


@when("I run a runbook requiring a path")
def run_requiring_a_path(ctx: dict[str, Any]) -> None:
    ctx["decorators"] = [guard.path("/srv/demo")]
    run_declared(ctx)


@when("I run a runbook requiring that mount")
def run_requiring_mount(ctx: dict[str, Any]) -> None:
    run_declared(ctx)


@when("I run a runbook requiring that storage")
def run_requiring_storage(ctx: dict[str, Any]) -> None:
    ctx["decorators"] = [
        guard.storage(ctx["storage_key"], require_writable=ctx["storage_writable"])
    ]
    run_declared(ctx)


@when(parsers.parse('I run a runbook requiring the "{username}" user'))
def run_requiring_user(ctx: dict[str, Any], username: str) -> None:
    ctx["decorators"] = [guard.user(username, CREATE_DIOT)]
    run_declared(ctx)


# ── Then: ordering, main(), exit codes ────────────────────────────────────


@then("the requirements are satisfied in that order")
def satisfied_in_order(ctx: dict[str, Any]) -> None:
    assert ctx["events"][:3] == [
        "prompt:sudo",
        "upstream:install_podman",
        f"playbook:{ENSURE_PATH}",
    ], ctx["events"]


@then("main() runs only after all of them succeed")
def main_runs_last(ctx: dict[str, Any]) -> None:
    assert ctx["events"][-1] == "main"


@then("main() runs")
def main_ran(ctx: dict[str, Any]) -> None:
    assert "main" in ctx["events"]


@then("main() does not run")
def main_did_not_run(ctx: dict[str, Any]) -> None:
    assert "main" not in ctx["events"]


@then("no later requirement is attempted")
def no_later_requirement(ctx: dict[str, Any]) -> None:
    """Three paths were declared; the second failing means only two ran."""
    assert [e for e in ctx["events"] if e.startswith("playbook:")] == [
        f"playbook:{ENSURE_PATH}",
        f"playbook:{ENSURE_PATH}",
    ]


@then(parsers.parse("the run's exit code is {code:d}"))
def run_exit_code(ctx: dict[str, Any], code: int) -> None:
    assert ctx.get("exit_code") == code


# ── Then: controller-only ─────────────────────────────────────────────────


@then("it is refused naming the target and the reason")
def refused_naming_target(ctx: dict[str, Any]) -> None:
    message = "\n".join(ctx["messages"])
    assert ctx["target"] in message
    assert ctx["reason"] in message


# ── Then: prompts ─────────────────────────────────────────────────────────


@then("I am prompted for the sudo password with hidden input")
def prompted_for_sudo(ctx: dict[str, Any]) -> None:
    sudo_prompts = [p for p in ctx["prompts"] if p.get("via") == "getpass"]
    assert len(sudo_prompts) == 1, ctx["prompts"]
    assert "sudo password" in sudo_prompts[0]["message"]
    assert sudo_prompts[0]["hide_input"] is True


@then("it is stored vault-encrypted for next time")
def sudo_stored(ctx: dict[str, Any]) -> None:
    assert ctx["vault"].get("ansible_become_password") == "sudo-pw"


@then("I am not prompted")
def not_prompted(ctx: dict[str, Any]) -> None:
    assert ctx["prompts"] == []


@then(parsers.parse('I am prompted with the message showing "{text}"'))
def prompted_showing(ctx: dict[str, Any], text: str) -> None:
    """click renders the default itself, so the guard asks it to show one."""
    assert ctx["prompts"], "expected a prompt"
    first = ctx["prompts"][0]
    assert first["show_default"] is True
    assert first["default"] == text.strip("[]")


@then("I am prompted with hidden input")
def prompted_hidden(ctx: dict[str, Any]) -> None:
    assert ctx["prompts"][0]["hide_input"] is True


@then("I am told it cannot be empty")
def told_cannot_be_empty(ctx: dict[str, Any]) -> None:
    assert any("cannot be empty" in message for message in ctx["echoes"]), ctx["echoes"]


@then(parsers.parse('the secret "{key}" is stored as "{value}"'))
def secret_stored_as(ctx: dict[str, Any], key: str, value: str) -> None:
    assert ctx["vault"].get(key) == value


@then(parsers.parse('a random token is stored for "{key}"'))
def random_token_stored(ctx: dict[str, Any], key: str) -> None:
    stored = ctx["vault"].get(key)
    assert stored, "expected a generated value"
    assert len(stored) >= 20, stored


@then("it raises naming the unknown prerequisite and listing the registered ones")
def raises_unknown_prerequisite(ctx: dict[str, Any]) -> None:
    error = ctx.get("error")
    assert isinstance(error, KeyError), error
    message = str(error)
    assert ctx["unknown_prerequisite"] in message
    assert "sudo_password" in message
    assert "vault_password" in message


# ── Then: playbooks ───────────────────────────────────────────────────────


def _ran(ctx: dict[str, Any], playbook: str) -> bool:
    return any(call["playbook"] == playbook for call in ctx["playbooks"])


@then("ensure_path.yml is not run")
def ensure_path_not_run(ctx: dict[str, Any]) -> None:
    assert not _ran(ctx, ENSURE_PATH)


@then("ensure_path.yml runs to reconcile it")
def ensure_path_ran(ctx: dict[str, Any]) -> None:
    assert _ran(ctx, ENSURE_PATH)


@then("ensure_path.yml runs without consulting the controller's filesystem")
def ensure_path_ran_for_remote(ctx: dict[str, Any]) -> None:
    """The path does not exist locally, so a fast path would have to stat it."""
    call = next(c for c in ctx["playbooks"] if c["playbook"] == ENSURE_PATH)
    assert call["target"] == ctx["target"]


@then("enable_rclone.yml is not run")
def enable_rclone_not_run(ctx: dict[str, Any]) -> None:
    assert not _ran(ctx, ENABLE_RCLONE)


@then("enable_rclone.yml runs to mount it")
@then("once registered, enable_rclone.yml runs to mount it")
def enable_rclone_ran(ctx: dict[str, Any]) -> None:
    assert _ran(ctx, ENABLE_RCLONE)


@then("I am prompted to create the rclone remote")
def prompted_to_create_remote(ctx: dict[str, Any]) -> None:
    assert ctx["rclone_created"], "expected prompt_create_remote to be called"


@then(parsers.parse('"{name}" is re-registered read-write'))
def re_registered_writable(ctx: dict[str, Any], name: str) -> None:
    assert {"name": name, "writable": True} in ctx["rclone_added"]


@then("the user-creation playbook is not run")
def user_playbook_not_run(ctx: dict[str, Any]) -> None:
    assert not _ran(ctx, CREATE_DIOT)


@then("the user-creation playbook is run")
def user_playbook_ran(ctx: dict[str, Any]) -> None:
    assert _ran(ctx, CREATE_DIOT)


@then(parsers.parse('it fails telling me to re-set it with "{hint}"'))
def fails_with_reset_hint(ctx: dict[str, Any], hint: str) -> None:
    error = ctx.get("error")
    assert isinstance(error, RuntimeError), error
    assert hint in str(error)


# ── Then: upstream ────────────────────────────────────────────────────────


@then("install_podman is executed before install_jellyfin's main()")
def upstream_ran_first(ctx: dict[str, Any]) -> None:
    assert ctx["events"].index("upstream:install_podman") < ctx["events"].index("main")


@then("install_podman is not re-run")
def upstream_not_run(ctx: dict[str, Any]) -> None:
    assert "upstream:install_podman" not in ctx["events"]


@then("install_podman is run rather than treated as broken")
def upstream_ran_despite_error(ctx: dict[str, Any]) -> None:
    assert "upstream:install_podman" in ctx["events"]
    assert ctx.get("error") is None
