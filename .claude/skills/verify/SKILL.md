---
name: verify
description: Build, launch and drive strata's CLI and local GUI API server to capture runtime evidence.
---

# Verifying strata at runtime

Two surfaces. Pick the one the diff touches.

## 1. CLI

```bash
uv run strata --help
uv run strata dev gui-data      # read-only catalog snapshot as JSON
uv run strata dev gui-token     # print the GUI bearer token (--rotate to reissue)
```

Runbooks are never standalone scripts: `uv run strata runbook <name> --target <host>`.

**`guard_executor.execute()` does NOT short-circuit on a runbook's own `check()`** -- it always runs `main()` once guards pass. `/api/runbook-status` reporting `installed: true` does not make a run a no-op. To exercise the run machinery with zero side effects, aim a `@guard.controller_only` runbook at a non-controller target: `_satisfy_one` refuses, `main()` never runs, and you still get the full run lifecycle.

## 2. The local GUI server

```bash
uv run strata gui --port 8791 > gui.log 2>&1 &
TOKEN=$(grep -oP 'Access token: \K.*' gui.log)
```

Binds 127.0.0.1 only; prints the URL and token on two separate lines. It serves the `/api/*` routes and nothing else -- any other path is a 404, so there is no web app to drive from here. The Flutter app lives in its own repository at `~/Dev/apps/strata` and is built, analyzed and driven there.

Read routes are open; `POST`/`DELETE` need `Authorization: Bearer $TOKEN`:

```bash
curl -s "http://127.0.0.1:8791/api/gui-data"
curl -s "http://127.0.0.1:8791/api/runbook-status?dotted_name=X&target=Y"
curl -s "http://127.0.0.1:8791/api/vault-status"
curl -s "http://127.0.0.1:8791/api/reachable?host=H&port=22"
curl -s -H "Authorization: Bearer $TOKEN" -X POST http://127.0.0.1:8791/api/run \
     -d '{"dotted_name":"...","target":"..."}'
```

Only one run is tracked at a time; a second concurrent `POST /api/run` gets 409.

A cross-origin caller needs a CORS header back, so send an `Origin` when checking that:

```bash
curl -si -H "Origin: http://localhost:12345" http://127.0.0.1:8791/api/gui-data | grep -i access-control
```

Loopback origins are echoed automatically; anything else needs `--allow-origin <origin>` on the server.

## Safety

- `ansible/inventory/hosts.ini` is real and gitignored. Back it up before driving device add/remove, and restore after -- the add/remove round-trip is otherwise clean except that it normalises the file's missing trailing newline.
- `POST /api/vault-password` and `POST /api/secrets` write the real OS keychain and vault. Drive only their missing-field variants, which 400 before writing.
- Some app data dirs (`/srv/baikal`) are owned by the `diot` service user and are not statable by the operator's account.
