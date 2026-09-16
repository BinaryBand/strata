# strata Architecture Ledger

This file is the running record of **known asymmetries and refactor opportunities** -- things worth doing, things deliberately not done, and why.

It used to also carry a directory tree, a layer diagram, a call chain and a guard-decorator table. All four duplicated `docs/ARCHITECTURE.md`, which is kept current; these copies were not, and drifted far enough to contradict the code (an obsolete `utils/` layout, a `main(target)` signature that had gained a parameter, a guard order stated backwards, a registry file that had been deleted). They were removed rather than re-synced for a third time.

**For how the code is actually shaped -- layers, guard flow, the call chain, where each package lives -- read `docs/ARCHITECTURE.md`.** Anything structural belongs there, not here.

## Asymmetries

**RESOLVED: Prerequisite registration** -- named prerequisites used to be registered at import time by `utils/prerequisites.py`, which meant `main.py` had to import that module for its side effect alone and every `@guard.prerequisite` carried a lazy import to guarantee it had happened. That module is gone; the registry is now a plain table (`_TABLE` in `adapters/prerequisites.py`) that needs neither.

**RESOLVED: Playbook parameterization is inconsistent** -- `ensure_path.yml` was fully parameterized via extravars while `install_jellyfin.yml` and `install_baikal.yml` hardcoded their data directories and image names. Each value now has one owner, split by what the value is:

- Data directories moved to the runbook. `install_jellyfin.py` and `install_baikal.py` each spell their data root once as a module constant, feed it to `guard.path`/`guard.backup_tag`, and pass it to the playbook as an extravar; the playbook asserts it arrived and declares it nowhere. The literals previously sat in three places per app -- the `guard.path` decorator, the `guard.backup_tag` decorator and the play's `vars:` -- across two languages, with the extravar silently winning at runtime, so a stale copy looked authoritative while changing nothing.
- Images moved the other way, to `server_apps_defaults` alongside the ports that were already there. They are deployment config with no Python counterpart, and the group_var is overridable per host through Ansible's precedence ladder. `ServerAppsDefaults` gained the matching `image` field the model docstring had been promising since it was written.

`tests/test_server_apps_defaults.py` (formerly `test_server_apps_ports.py`) enforces both directions, and additionally checks that every `server_apps_defaults.<app>.<field>` a playbook references exists on the model -- otherwise a typo there fails only at run time, on the target, mid-play.

**CLOSED (won't do): extravars are assembled ad-hoc** -- this described each guard building up its own dict and guards communicating through naming conventions, and proposed threading an explicit `ctx: dict` through the chain. The code does not work that way. Only `_ensure_local_path()` builds a nontrivial extravars dict; `_ensure_mount()` and `_ensure_user()` pass none at all. The remaining `extravars=` call sites live inside individual runbooks' `main()` -- a different mechanism on purpose, since a runbook owns its own playbook's inputs -- and a guard-chain context object would not reach them anyway. One call site is not a duplicated pattern, so a `GuardContext` abstraction would be machinery serving nothing.

## Organization Opportunities

**RESOLVED: Inputs co-location** -- `keys.py` and `rclone.py` sit under `adapters/ansible/` alongside the other Ansible adapters.

**RESOLVED: Guard method clarity** -- `guard.mount(remote:subpath)` is a separate decorator from `guard.path()` for local paths.

**RESOLVED: Always-False check() functions** -- removed from seven runbooks (then `server_apps/`, now `services/`) where state lives in systemd and cannot be read locally.

**RESOLVED: Guard logic triplication** -- `path()`, `mount()` and `storage()` each independently re-implemented the same local-directory (`ensure_path.yml`) and rclone-mount (`enable_rclone.yml`) provisioning logic. Extracted into shared helpers `_ensure_local_path()`/`_ensure_mount()` -- which now live in `adapters/guard_executor.py`, since the guards themselves became declarative -- that all three paths call; `storage()`'s runtime dispatch just picks which helper to invoke for the vault value it read. This also fixed a latent bug where `mount()` alone (unlike `path()`/`storage()`/`user()`/`requires()`) never forced a playbook re-run when a remote `target` was set.

**RESOLVED: Runbook naming is mixed** -- `install_*` and `enable_*` were used without a documented rule. The convention is now stated in `docs/ARCHITECTURE.md` and enforced by `tests/test_runbook_naming.py`: `install_*` for one-time binary/package installs, `enable_*` for services that run on a recurring basis (systemd units, mounts), with a small allowlist for the operations that are neither (`backup`, `restore`, `sync_rclone_remote`). The earlier note here also claimed a `remove_*` prefix was in use; none ever existed.

**RESOLVED: No roles in Ansible** -- this predicted that a shared Quadlet role would be worth extracting "once a third or fourth Quadlet playbook lands". It did, and two more followed once the same audit measured the duplication:

- `podman_quadlet_service` -- write + start a diot Quadlet unit, used by `install_jellyfin.yml` and `install_baikal.yml`. `deploy.yml`/`start.yml` are split so a caller can splice host-side prep between them via `tasks_from`; no caller does today, and both go through `main.yml`.
- `restic_container` -- the restic-through-podman machinery. `backup.yml` and `restore.yml` were ~76 identical lines differing only in the verb argv and whether each data volume is mounted `:ro`; both now set `restic_action` and include the role.
- `diot_systemd_units` -- the reconcile cycle for a family of diot `systemd --user` units (compute desired, find existing, stop/disable/delete strays, write, flush handlers, start/restart). `enable_rclone.yml` and `enable_rclone_http.yml` each carried their own ~79-line copy, and `docs/ARCHITECTURE.md` was telling future timer work to make a third.

The other 18 playbooks are flat under `playbooks/`, which is the right shape for one-off tasks. The restic repo-path regex, previously copied verbatim into `backup.yml`, `restore.yml` and `install_restic.yml`, now has a single definition in `inventory/group_vars/all/restic.yml`.

**`ansible/` at repo root vs. inside the package** -- the `ansible/` directory lives at repo root while all Python code is under `strata/`. This creates a split mental model.

- Decision: keep as-is. The separation has merit (Ansible content is not a Python package), and the boundary is now explicit: `core/paths.py` anchors the repo root once, so no module recomputes it with `parents[N]`.

## Simplification Opportunities

**RESOLVED: `secrets.py` shells out for vault operations** -- `ansible-vault encrypt_string` and `ansible-vault view` were invoked via `subprocess`, the latter round-tripping every secret's ciphertext through a tempfile in `/tmp` to read it. Both now use the `ansible.parsing.vault` Python API (`VaultLib`, `VaultSecret`) in-process: no subprocess per operation, no ciphertext on disk outside the secrets file, no dependence on `ansible-vault` being on `PATH`, and no argument vector for a plaintext to leak into.

The on-disk layout is unchanged and load-bearing -- `has_secret`, `get_secret` and `set_secret` parse the file by regex, and every block already stored was written by the CLI. `_encrypt` reproduces that block exactly (ten-space indent, `$ANSIBLE_VAULT;1.1;AES256` header, 80-column body); `encrypt()` is called without a `vault_id`, which would otherwise emit a 1.2 header. Two tests in `tests/unit/adapters/ansible/test_secrets.py` pin the format against the real `VaultLib` rather than the fake, in both directions.

Known trade, accepted: this swaps a stable CLI contract for a Python one that ansible-core does not support publicly and has been restructuring. If a future ansible-core moves `VaultLib`, this module is where it breaks -- loudly, at import, and covered by tests.

**CLOSED (won't do): guard registry auto-discovery** -- this proposed replacing `prerequisites.py`'s manual registration calls with a class-based or entry-point mechanism. `prerequisites.py` no longer exists, and what replaced it is a four-line dict with two entries (`sudo_password`, `vault_password`) in `adapters/guard_executor.py`. Auto-discovery machinery for two entries would add more boilerplate than it removes. Revisit only if the prerequisite set grows substantially.

**CLOSED (won't do): `_path_satisfied()` is imperative** -- this proposed extracting a `PathSpec(owner, group, mode)` dataclass with an `is_satisfied(stat_result) -> bool` method. The dataclass half already exists and arrived from the other direction: the function is now `path_satisfied(spec: req.LocalPath)`, taking the same frozen `core/requirements.py` record the guard declared. The method half is what the layer contract forbids. `req.LocalPath` lives in `core`, and answering "is this satisfied" means a `stat`, a `pwd.getpwuid` and a `grp.getgrgid` -- I/O, which is exactly what `core` holds none of. Moving it there to read better would put filesystem calls on a frozen declaration object and make the requirement types untestable without a real filesystem. It stays a function in `adapters`, where the eight tests that pin it can hand it a `tmp_path`.

**RESOLVED: The prerequisite set was enumerated twice** -- `guard_executor._PREREQUISITES` mapped each named prerequisite to the function that establishes it, while `guard_status._prerequisite_satisfied` re-listed the same two names in an `if name == ...` ladder to answer the GUI's readiness endpoint. Nothing tied them together, so a third prerequisite registered in the executor would have been satisfied correctly at run time and reported missing forever on the status display. Both halves now live on one entry in `adapters/prerequisites.py`, which owns the table and exposes `ensure()` and `satisfied()`; a test asserts every registered entry answers both. Splitting it into its own module also took `guard_executor` back under the 400-line cap. It is not the old `utils/prerequisites.py`: that was a runtime registry populated by import side effect, and this is a plain table with no registration step to sequence.

**State model is a singleton with no room to grow** -- `AppState` has one field. If a second stateful value is needed, adding it is trivial, and the file-per-model structure is already in place. No action needed yet.
