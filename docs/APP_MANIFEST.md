# The strata app manifest

A project that lives in its own repository declares how strata installs it in a file at its root, `strata.app.yml`. Strata puts the project's committed code on a device, builds it there and keeps it running as a systemd user service of the `diot` account. Nothing about the project is written in strata.

This is version 1 of the standard. It covers a long-running service built from source. It does not cover a container image, which `ansible/apps/*.yml` declares, or a command-line tool with no service.

## The contract

A project provides:

1. Its code, committed. Strata deploys `HEAD` of the checkout it is pointed at, and uncommitted changes are not shipped.
1. A `build` command that turns a fresh unpack of that commit into something runnable, using only the toolchain the manifest names and the network.
1. State outside the release. A release directory is replaced on every deploy, so anything a program writes must go to a directory the manifest declares.
1. Configuration through environment variables, declared secrets and the arguments in `run.command`.

Strata provides:

1. The `diot` account and its lingering user manager.
1. The toolchain, through the runbook that installs it.
1. The declared state directories, owned by `diot` and a group named for the app.
1. A release for each commit under `/srv/<name>/releases/<commit>`, and a `current` link to the one that runs. The three newest are kept.
1. The unit, its start at boot, and a restart when the commit, the unit or a secret file changes.
1. The runbook `services.install_<name>`, with the alias, the secrets prompts and the backup tag the manifest declares.

## Deploying

Running `strata runbook services.install_<name> --target <host>` does the following, in order.

1. Ensures the `diot` account, the toolchain and the declared directories, and prompts for any secret not yet in the vault.
1. Archives `HEAD` on the controller with `git archive`, so `export-ignore` in the project's `.gitattributes` applies.
1. Unpacks it to a new release directory and runs `build` there as `diot`. A commit that is already built is not built again.
1. Points `current` at the release, writes the secret files and the unit, and restarts the service if anything changed.

Deploying an unchanged commit changes nothing. Deploying a new commit is the update path, and the previous release stays on the device until three newer ones exist.

## Fields

| Field | Required | Meaning |
| --- | --- | --- |
| `schema` | yes | `1`. |
| `name` | yes | Lowercase letters, digits and `_`. Names the runbook, the unit, the group and `/srv/<name>`. |
| `alias` | yes | The display name in listings and the app. |
| `description` | yes | One line, used for the unit description and the runbook summary. |
| `toolchain` | yes | What `build` and `run` need on the host. One of the values below. |
| `build` | yes | A shell line run as `diot` in the unpacked release. |
| `run.command` | yes | The service's `ExecStart`, started in `/srv/<name>/current`. systemd expands `${VAR}` in it from the unit's environment. |
| `run.env` | no | Fixed environment variables. |
| `dirs` | yes | The state directories, each `path` and an optional quoted octal `mode` (default `"2770"`). Declare a parent before its children. |
| `secrets` | no | Values kept in strata's vault. Each has `name`, `prompt`, optional `kind` (`text` or `password`), `default` and `generate`, and at least one of `env` and `file`. |
| `backup` | no | `tag` and `path`. The path must be one of `dirs`. |

A secret with `env` is written into the unit, which is then mode `0600` and kept out of the run log. A secret with `file` is written to that path with mode `0600`, and the path must sit directly inside one of `dirs`. A deploy rewrites the file from the vault, so the vault owns the value.

The `dirs` may not lie under `/srv/<name>/releases` or `/srv/<name>/current`. Env names, secret names and directories must each be unique.

## Toolchains

| Value | Installed by | On the host |
| --- | --- | --- |
| `uv` | `infrastructure.install_uv` | A pinned release in `/usr/local/bin`, checked against a pinned checksum. |

A project that needs another toolchain, such as Go or Node, adds a value to the table above and the runbook that installs it in strata. The manifest fields do not change.

## Registering a project

List the checkout in `ansible/projects.yml`, which is gitignored:

```yaml
projects:
  - /home/you/Dev/example-project
```

`strata runbook --list` then shows the project's runbook beside the built-in ones. A project whose manifest cannot be read is reported as a failure and skipped, and `infrastructure.backup` refuses to run while it stays broken, since its data would be missing from the backup.

## Editor validation

`strata dev schema` writes `.vscode/source_app_schema.json`, the JSON Schema for this file. Point the editor's YAML schema mapping for `strata.app.yml` at it.

## Not in version 1

1. A container runtime for a project that cannot install its toolchain on the host.
1. Exposing the service beyond the device. The service listens where the program says it does, and reaching it from elsewhere is set up outside the manifest.
1. A command on the operator's path, or a scheduled job, with no service.
1. Rolling back to a kept release. The releases stay on disk, and `current` can be repointed by hand.
1. Sandboxing directives in the unit.
