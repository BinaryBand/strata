# TODO

## Batch adjacent `@guard.path` requirements into one play

`guard_executor._ensure_local_path` runs `ansible/playbooks/ensure_path.yml` once per unsatisfied `LocalPath`, and each run is a separate ansible-playbook process costing at least 0.7 s with fact gathering off. On a remote target the controller-only fast path never applies, so every declared path runs on every run. `install_baikal` declares 3 paths and `install_jellyfin` declares 2.

The change:

1. `_satisfy_all` looks ahead and groups consecutive `LocalPath` requirements that are unsatisfied, keeping declaration order.
1. The group goes to `ensure_path.yml` as one `guard_paths` extravar: a list of `{path, state, owner, group, mode}` items.
1. `ensure_path.yml` loops over `guard_paths`, creating the owning group first for each item that names one.

This changes the extravar contract of `ensure_path.yml`, which today takes `guard_path`, `guard_state`, `guard_owner`, `guard_group` and `guard_mode`. Only the Podman integration suite (`uv run pytest -m integration`) runs that playbook for real, so run it before merging.
