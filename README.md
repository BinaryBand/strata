# strata

A small Ansible config manager for provisioning a personal Linux machine. Playbooks do the work; a thin Python layer (`ansible-runner` plus a `strata` CLI) wraps them so that prerequisites -- sudo passwords, vault secrets, SSH keys, system users, data directories -- are resolved declaratively before a playbook runs, prompting only when something is genuinely missing.

The managed host defaults to the local machine itself (`ansible_connection=local`), so the controller and the target are usually the same box -- which is why interactive prompts (vault password, rclone authorization) work directly during a run. Additional machines can be registered with `strata device add` and targeted with `--target <hostname>`.

## Layout

The package is a three-layer scaffold, and an import-linter contract enforces it: `cli`, `adapters` and `core` are the only top-level packages, and imports may only point downward (`cli` -> `adapters` -> `core`).

- `src/strata/cli/` -- the `strata` CLI entrypoint (Typer) and the composition root: `main.py` assembles the app tree, `commands/` holds one module per command group, `dispatch.py` resolves and runs a runbook.
- `src/strata/core/` -- runbooks, models, guards, and the `Protocol` ports adapters satisfy. No I/O. `core/runbooks/` is grouped by category (`system/`, `package_managers/`, `development/`, `infrastructure/`, `services/`); each module exposes `main(target, *, runner)` and an optional `check()`, decorated with guards that *declare* requirements rather than satisfying them.
- `src/strata/adapters/` -- everything that touches the outside world: `guard_executor.py` (satisfies what the guards declared, then calls `main()`), `ansible/` (runner, vault secrets, host_vars/group_vars, SSH keys, rclone, inventory), `proc.py`, `state.py`, `fs.py`.
- `ansible/playbooks/` -- the actual playbooks. Paths resolve relative to `ansible/`, independent of where the runbook module lives. Sequences more than one playbook needs live in `ansible/roles/`.
- `ansible/inventory/` -- `hosts.ini`, `host_vars/<host>.yml` (per-host plain variables, e.g. rclone synced remotes and published SSH keys) and `group_vars/all/managed.yml` (every-host rclone remotes and serves) are yours and gitignored, each with a `.example` template beside it; the CLI creates the variable files on first write. `group_vars/all/server_apps_defaults.yml` holds shared server-app defaults, and `group_vars/secrets/all.yml` the vault-encrypted secrets (gitignored).

`docs/ARCHITECTURE.md` is the full structural reference -- the layer scaffold, the guard flow, the call chain from CLI to playbook, and the conventions a change is expected to hold to. `docs/LEDGER.md` records known asymmetries and refactor opportunities.

## Getting started

Install uv, which fetches a suitable Python itself:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

After that, everything runs through uv:

```bash
uv sync
uv run strata --help
```

The inventory is not shipped with the repository -- it names your own machines, addresses and accounts. Start from the template and edit it for your setup:

```bash
cp ansible/inventory/hosts.ini.example ansible/inventory/hosts.ini
```

The vault password is stored once in the OS keychain and reused for every encrypted secret:

```bash
uv run strata config vault-password
```

## The `strata` CLI

- `strata config var NAME [--value V]` -- set a plain variable in `group_vars/all/managed.yml`.
- `strata config secret NAME [--value V]` -- vault-encrypt a secret into `group_vars/secrets/all.yml`.
- `strata config vault-password` -- store or reset the vault master password in the keychain.
- `strata config key LABEL` -- generate an SSH keypair at `~/.ssh/<label>` and publish its public half as the `<label>_authorized_key` group var.
- `strata rclone add NAME` / `strata rclone list` / `strata rclone remove NAME` -- register rclone remotes for auto-mounting (see below).
- `strata rclone serve add NAME PATH --port PORT` / `strata rclone serve list` / `strata rclone serve remove NAME` -- register an rclone path to be served over local HTTP instead of mounted (see "Serving rclone paths over local HTTP" below).
- `strata rclone sync add NAME` / `strata rclone sync list` / `strata rclone sync remove NAME` -- register a remote whose credentials `infrastructure.sync_rclone_remote` copies onto a target host.
- `strata device add NAME --host ADDR` / `strata device list` / `strata device show NAME` / `strata device remove NAME` -- manage remote hosts in the `[remote]` group of `hosts.ini`, which `--target` then addresses.
- `strata runbook NAME [--target HOST]` -- run a runbook, e.g. `strata runbook services.install_jellyfin`. Omit NAME on a terminal for a type-ahead picker over every runbook, matching anywhere in the name and showing each one-line summary alongside it; omit `--target` and you are asked which host, defaulting to the last one used so Enter reuses it. Ctrl-C aborts either. `strata runbook --list` browses them as plain text instead. Piped and scripted invocations never prompt: without NAME they error, and without `--target` they fall back to the stored target.
- `strata gui [--port PORT] [--allow-origin ORIGIN]` -- serve the runbook catalog and action API on loopback for the Flutter app, which lives in its own repository. Prints the URL and the bearer token the mutating routes require. It serves no web app.

## Guards

Guards are decorators on a runbook's `main()` that make a prerequisite hold before the body runs. They share one idea: a cheap local check, and only if it fails, do the privileged work (usually by running a small playbook).

- `@guard.prerequisite("sudo_password")` -- ensure a registered prerequisite (the vaulted sudo password) is present.
- `@guard.secret(vault_key, ...)` -- ensure a vault secret exists, prompting (and optionally generating) if absent.
- `@guard.user(name, playbook)` -- ensure a system user exists, running `playbook` to create it if not.
- `@guard.path(path, owner=, group=, mode=)` -- ensure a local filesystem path exists with the given ownership and mode, delegating to `ensure_path.yml`.
- `@guard.mount(remote:subpath)` -- ensure an rclone remote is registered and its mount point is live (creating the remote interactively if missing), running `enable_rclone.yml` if not.
- `@guard.storage(vault_key, owner=, group=, mode=, require_writable=)` -- ensure a vaulted storage location -- prompted for like `@guard.secret` -- is ready, dispatching to the `@guard.path` or `@guard.mount` flow at runtime depending on whether the stored value is a local path or a `remote:subpath`.
- `@guard.requires("category.runbook")` -- ensure an upstream runbook has run first.
- `@guard.controller_only(reason)` -- refuse a non-controller target outright, for workstation tooling whose playbook is deliberately `hosts: local`. Without it such a play matches no hosts under `--limit`, which ansible reports as success.
- `@guard.backup_tag(tag, path)` -- declare that `path` is snapshotted under restic tag `tag`; `infrastructure.backup` collects these by importing every runbook.
- `@guard.alias(display_name)` -- the friendly name shown in `--list` and the picker. Metadata only; a runbook is still invoked by its dotted or leaf name.

## System and package managers

These runbooks are simpler and independent of each other (no dependency chain), so they're listed flat rather than diagrammed:

- `system.enable_security_autoupdates` -- enable automatic security updates via unattended-upgrades.
- `package_managers.install_flatpak` -- install Flatpak and add the Flathub remote.
- `package_managers.install_homebrew` -- install Homebrew and core dev tools (node, pipx, uv, openjdk, rust). It installs to `/home/linuxbrew/.linuxbrew` and adds that prefix to no profile and no PATH, so invoke `brew` by its full path or put the prefix on your own PATH.
- `development.install_antigravity` -- install Google Antigravity CLI via the local Homebrew tap.
- `system.enable_crash_recovery` -- keep the machine up: mask the sleep, suspend and hibernate targets, recover from kernel panics and freezes, and keep crash evidence readable.
- `infrastructure.enable_tailscale` -- join this host to the Tailscale tailnet for off-LAN reachability.
- `infrastructure.enable_wireguard` -- route all of this host's traffic through a WireGuard VPN (any provider) while Tailscale keeps working. The prompted key belongs to one host at a time, and inbound router port-forwards to this host stop working while the tunnel is up.
- `infrastructure.install_restic` -- initialize the restic repository that `backup`/`restore` use.
- `infrastructure.backup` / `infrastructure.restore` -- snapshot each opted-in app's data under its own restic tag, and write the latest snapshot per tag back. Both accept `--tags` to narrow the set.
- `infrastructure.sync_rclone_remote` -- copy registered rclone remote credentials onto a target host.

## Server apps

Server apps run as rootless Podman containers owned by a dedicated `diot` user (a container operator with a subuid/subgid range and systemd lingering, so its `--user` services persist without a login). Each container is a Quadlet unit under `~diot/.config/containers/systemd/`, which systemd turns into a managed service.

The dependency chain is enforced by guards, so running a leaf runbook pulls in everything beneath it:

```mermaid
flowchart TD
    diot[create_diot_user] --> podman[install_podman]
    podman --> jellyfin[install_jellyfin]
    rclone[enable_rclone] -. read-only media mount .-> jellyfin
    rclone --> rclone_http[enable_rclone_http]
    podman --> baikal[install_baikal]
    podman --> minio[install_minio]
    podman --> anythingllm[install_anythingllm]
    tailscale[enable_tailscale] --> anythingllm
    anythingllm --> anythingllm_plugins_access[enable_anythingllm_plugins_access]
    anythingllm --> anythingllm_site[enable_anythingllm_site]
    anythingllm_site --> anythingllm_review[enable_anythingllm_review]
    restic[install_restic] --> backup[backup]
    restic --> restore[restore]
```

- `install_podman` -- Podman and the rootless toolchain; ensures `diot` via `create_diot_user`. That account is reconciled on every server-app run, even when podman is already installed: a passwd entry is no evidence that its subuid range, subgid range and lingering survived, and those are what rootless containers actually need.
- `enable_rclone` -- install rclone and mount configured remotes (see below).
- `enable_rclone_http` -- serve registered rclone paths over local HTTP instead of mounting them (see "Serving rclone paths over local HTTP" below).
- `install_jellyfin` -- Jellyfin media server on port 8096; config and cache at `/srv/jellyfin/{config,cache}` (`diot:jellyfin`, setgid), with the read-only media library bound from `/mnt/rclone/pcloud/Media`.
- `install_baikal` -- Baikal CalDAV/CardDAV server on port 8080; data at `/srv/baikal/{config,Specific}` (`diot:baikal`, setgid).
- `install_anythingllm` -- AnythingLLM document-chat server on port 3001, published on loopback only and served to the tailnet over HTTPS with `tailscale serve` at `https://<host>.<tailnet>.ts.net:3001`, so no LAN device can reach it. It needs HTTPS Certificates enabled once in the Tailscale admin console, and fails with that instruction until they are; storage at `/srv/anythingllm/storage` (`diot:anythingllm`, setgid). The login password (`anythingllm_password`) and session-signing secret (`anythingllm_jwt_secret`) are vault secrets, prompted for or generated on the first run and written into `storage/.env`, which the unit binds onto the container's `/app/server/.env` so settings survive a restart; change the password with `strata config secret anythingllm_password` and re-run, because a password changed in AnythingLLM's own UI is reset on the next run. The LLM provider and its API keys are set through the web onboarding and land in that same file, so the unit pins `UserNS=keep-id` onto the image's uid/gid 1000 and the container writes as `diot` rather than the volume being opened to 2777. On a host that has `/usr/share/applications`, it also installs an `anythingllm.desktop` launcher that opens the served port in your browser; a headless target skips that task.
- AnythingLLM's content -- the system prompt, custom skills such as a skill-drafting workshop and a research tool, and the rules files in the agent's folder -- is not managed here. Strata installs the server and the services around it; the content is seeded once from a separate private repository and then belongs to AnythingLLM, the agent and the operator.
- `enable_anythingllm_plugins_access` -- give the account strata logs in as read-write access to AnythingLLM's `storage/plugins` folder (custom skills, agent flows, the MCP config), so skills can be written there directly, for example in an editor over SSH. The account gets POSIX ACLs on `plugins/` (for itself and for `diot`, including default ACLs for new files) and only traverse on the folders above it, so it cannot list storage or open `.env` or the chat database; every file in storage loses "other" access and every directory gets a default ACL that keeps new files closed. Skills written this way skip the `strata-workshop` review and run once switched on in Settings. A file saved with mode `0600` (an explicit restrictive create, a later `chmod 600`, or an `mv` from `/tmp`) is unreadable to AnythingLLM until you re-run this runbook, which repairs every file in `plugins/`; ordinary editor saves are unaffected. The account name is read at run time, so it never enters this repository.
- `enable_anythingllm_site` -- build the agent's website with Zola and serve it tailnet-only at `https://<host>.<tailnet>.ts.net:8443` (`server_apps_defaults.anythingllm.site_port`). The site builder runs as `anythingllm-site-build`, a sandboxed system unit with no network, and publishes each build as a release in `/srv/anythingllm/site-public`. Zola follows the `zola_series` (0.23): the newest release in the series is installed and checked against the SHA-256 GitHub publishes for it. A rootless nginx container (`nginxinc/nginx-unprivileged`, pinned to the 1.30 series, running as `diot` through `UserNS=keep-id:uid=101`) serves the output read-only on `127.0.0.1:8088` (`site_local_port`), and `tailscale serve` proxies the tailnet port to it. nginx's config lives in root-owned `/srv/anythingllm/site-nginx` and sends `Cache-Control: no-cache`, a `script-src 'none'` Content-Security-Policy, `Referrer-Policy: no-referrer` and `nosniff`, with directory listings and dotfiles refused. The play switches the port to nginx only after the builder has published and nginx answers with its headers, and refuses to take over a port another listener already serves.
- `enable_anythingllm_story` -- full stories for the site's headlines at `https://<host>.<tailnet>.ts.net:8443/story/<day>/<n>`, written by DeepSeek the first time one is opened. It installs `anythingllm-story`, a sandboxed system unit with its code root-owned in `/srv/anythingllm/story`, listening on a Unix socket that `tailscale serve --set-path=/story` mounts, and switches the site builder to link each headline there instead of to its first source. Only the tailnet login of the controller that ran the runbook may open it. The DeepSeek key and model are copied from AnythingLLM's settings into root-only `/etc/anythingllm-story/deepseek-api-key` and reach the service through systemd's `LoadCredential=`; a key rotated in AnythingLLM reaches `/story` on the next run. The unit hides AnythingLLM's storage, other processes and core dumps from the service and denies the LAN and tailnet address ranges.
- `enable_anythingllm_review` -- a read-only monitor of everything the AnythingLLM agent can see, at `https://<host>.<tailnet>.ts.net:8444` (`server_apps_defaults.anythingllm.review_port`), a separate origin from the site and `/story`. It installs `anythingllm-review`, a sandboxed system unit running as `diot` with the data read-only, no network namespace, no capabilities, and its code root-owned in `/srv/anythingllm/review`. The monitor listens on a Unix socket in a `0700` runtime directory rather than a port; `tailscale serve` serves it at the root of its port and stamps each request with the viewer's login, overwriting any a client sends. Only the tailnet login signed in on the controller when the runbook runs may open it, and credentials never leave it.
- The site builder, `/story` and `/review` are programs from the private anyllm repository, which also documents what each one shows and refuses. Their runbooks copy them from `services/` in the anyllm checkout at `anyllm_src`: by default a clone beside this repository, otherwise set per host with `strata config var anyllm_src <path> --target <host>`. A run stops before installing anything when that checkout is missing.
- `install_minio` -- MinIO object storage server, API on port 9000 and console on port 9001; data at `/srv/minio/data` (`diot:minio`, setgid). Root credentials are prompted for (or generated) and stored in the vault, never written to the playbook.

## rclone mounts

`enable_rclone` mounts registered cloud-storage remotes under `diot`, one `systemd --user` FUSE mount per remote at `/mnt/rclone/<name>` (the remote root). Mounts are read-only unless the remote was registered with `strata rclone add --writable`, which a runbook needing a write destination (e.g. a restic repository) requires. Credentials come from rclone's own config file -- the project never touches them. The registered remote list lives in `group_vars/all/managed.yml` as `rclone_remotes`, with the writable subset in `rclone_writable_remotes`. The runbook is declarative: it prunes units for remotes you have removed from the list.

Mountpoints are under `/mnt/rclone/` which the `fusermount3` AppArmor profile permits for unprivileged FUSE mounts. Sub-paths within a mount are addressed with `remote:subpath` notation (e.g. `pcloud:Media`) and resolved to local paths (e.g. `/mnt/rclone/pcloud/Media`) by `rclone.resolve()` and `guard.mount`.

Authorize a remote directly with rclone, then register it:

```bash
rclone config create pcloud pcloud          # browser OAuth -- run once as yourself
strata rclone add pcloud                    # records 'pcloud' in rclone_remotes
strata rclone list                          # pcloud -> /mnt/rclone/pcloud
strata runbook infrastructure.enable_rclone   # copies rclone.conf to diot, starts mount unit
```

The mount and serve units run `/usr/bin/rclone` from the distro package. To run another build, set `rclone_bin` for the host in `inventory/host_vars/<host>.yml`, for example `rclone_bin: /home/linuxbrew/.linuxbrew/bin/rclone`. `enable_rclone` then skips the distro `rclone` package and both `enable_rclone` and `enable_rclone_http` write that path into their units. The path must be executable by `diot`. `fuse3` still comes from the distro, because `fusermount3` has to be setuid root.

## Jellyfin media pipeline

Jellyfin reads its library from `/mnt/rclone/pcloud/Media` (a subpath of the pcloud root mount). The Jellyfin Quadlet declares `RequiresMountsFor=/mnt/rclone/pcloud/Media` so systemd holds the service until that path is actually mounted. It does not use `BindsTo=rclone-pcloud.service`: Jellyfin runs as a diot *user* unit and the mount is a *system* unit, and a user unit cannot order against a system one.

A rootless container captures its bind mounts at start time in its own mount namespace, so the rclone mount must be live when the Jellyfin container starts. The setup order:

1. Authorize and register pcloud (see above) and run `enable_rclone`.
1. `strata runbook services.install_jellyfin` -- `guard.mount("pcloud:Media")` verifies the mount is live, then the playbook binds `/mnt/rclone/pcloud/Media` into the container at `/media:ro`.

Hardware transcoding (GPU passthrough via `/dev/dri`) is not configured; Jellyfin falls back to software transcoding.

## Serving rclone paths over local HTTP

Some rclone-backed content is meant to be published, not just read locally. `rclone serve http` serves a `remote:path` over HTTP with no local FUSE mount in the loop.

Register a path and apply it:

```bash
strata rclone serve add media-store pcloud:Media --port 8083
strata runbook infrastructure.enable_rclone_http
```

This writes a diot systemd --user service per registered entry, each running `rclone serve http` bound to `127.0.0.1:<port>` only -- nothing public listens directly. Front it with a local reverse proxy if it needs to be reachable outside the machine. `--vfs-cache-mode full` is enabled (same cache flags as `enable_rclone`'s FUSE mounts), so repeat reads are served from local disk cache instead of re-fetching from the cloud backend on every request. `strata rclone serve list` lists registered entries; `strata rclone serve remove NAME` removes one (re-run the runbook to stop and prune its service).

## Secrets

Secrets are encrypted with `ansible-vault` into `group_vars/secrets/all.yml`, which is gitignored and never committed. The vault password itself lives only in the OS keychain (retrieved at playbook time by `ansible/vault_pass.py`). Private SSH keys stay in `~/.ssh`; only public halves are published to group vars. Never hard-code a credential in a playbook -- declare it with `@guard.secret` and let the guard seed it into the vault. (SSH keypairs are not guards -- they are created out of band with `strata config key`.)

## Not yet automated

Provisioning steps that are still done by hand -- no runbook covers these yet. Lifted from the pre-project `docs/TODO` checklist when that file was retired; everything else on it has either shipped or was made obsolete by a later change.

- Remove Snap and the Ubuntu App Store.
- Install `libfuse2`, `fuse`, and `pcscd`.
- Install Bitwarden and Firefox (via Flatpak -- `package_managers.install_flatpak` sets up Flathub, but installs no apps).
- Install AppImageLauncher, then VSCodium and Joplin as AppImages.
- Enable SSH for a sandboxed, non-sudo account.
