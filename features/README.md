# User stories (Gherkin / BDD)

These `.feature` files are the user-story map for the `strata` CLI — the whole
user-facing surface of `strata`. Each file is one slice of the CLI; each
`Feature:` opens with an `As a / I want / So that` narrative and its `Scenario`s
are the concrete flows an operator hits, including the prompt/error paths that
*are* the UX of a provisioning tool.

## Personas

- **Operator** — the person provisioning a machine. Runs runbooks, registers
  remotes/devices, holds the vault password. The primary persona.
- **Maintainer** — works on `strata` itself (e.g. regenerates the schema
  after editing a model).

## Journey spine (read the features in this order)

1. `config.feature` — seed variables, secrets, the vault password, SSH keys
2. `device.feature` — register remote hosts to target
3. `rclone.feature` — register remotes to mount / serve
4. `runbook_dispatch.feature` — discover and launch runbooks
5. `guard_resolution.feature` — the declarative prerequisite/prompt engine
6. `server_app_journeys.feature` — the podman/diot dependency chain end-to-end
7. `backup_restore.feature` — restic snapshot / restore per app + config tag

Both 6 and 7 assert what the *runbook* decides — which playbooks run, in what
order, and which tag maps to which path. Guarantees that live in the playbooks
themselves (the config tag captured as root, skipped where absent; restic's
overwrite-but-never-delete) are called out in the feature files and verified
against a real host, not faked here.

Maintainer-only (off the operator spine): `dev.feature` — the hidden `strata
dev` namespace (schema regeneration).

## Running

`pytest-bdd` collects these as ordinary tests under the existing gate:

```bash
uv run pytest features/
```

Each bound feature has a `features/test_<name>.py` calling
`scenarios("<name>.feature")`; `tests/test_feature_bindings.py` enforces that
every feature is either bound that way or tagged `@wip`. Most bindings drive
the CLI through Typer's `CliRunner` with the adapters (`secrets`, `rclone`,
`inventory`, `runner`) faked — the same seams the unit suite already mocks.

`guard_resolution.feature` is the exception: its scenarios need runbooks
declaring particular guard combinations that no real runbook declares, so it
builds synthetic runbooks and drives `guard_executor.execute()` directly. Its
adapter fakes are factored into `features/_guard_harness.py`, and
`backup_restore` and `server_app_journeys` reuse that same fake layer while
driving the *real* runbooks through `cli.dispatch.run_runbook`.

All eight features are bound; nothing is `@wip`. Container-backed coverage is
not restated here as Gherkin — it lives in `tests/integration/`, which drives
real playbooks through real ansible-runner against a disposable Podman
container and is excluded by default (`pytest -m integration`).

Tags in use: `@controller-only` (asserts behaviour gated on
`ansible_connection=local`). `@wip` remains available for a feature written
before its step definitions, and `tests/test_feature_bindings.py` still
enforces bound-or-`@wip`.
