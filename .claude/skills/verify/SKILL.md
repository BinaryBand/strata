---
name: verify
description: Build, launch and drive strata's CLI, local GUI server and Flutter web app to capture runtime evidence.
---

# Verifying strata at runtime

Three surfaces. Pick the one the diff touches.

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
uv run strata gui --no-browser --port 8791 > gui.log 2>&1 &
TOKEN=$(grep -oP 'Access token: \K.*' gui.log)
```

Binds 127.0.0.1 only; prints the URL and token on two separate lines. Serves `gui/build/web` from disk per request, so rebuilding the web app does **not** need a server restart.

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

## 3. The Flutter web app

**`strata gui` serves whatever is already in `gui/build/web` and never rebuilds it.** A stale bundle looks like a working app while silently exercising none of your Dart changes. Always confirm before trusting a UI observation:

```bash
grep -c "runbook-status" gui/build/web/main.dart.js   # 0 => stale
cd gui && flutter build web                            # ~40s; build/ is gitignored
cd gui && flutter analyze
```

Drive it headlessly -- Playwright browsers are already installed (`install-deps` fails without sudo; you don't need it):

```bash
cd <scratchpad> && npm install playwright@1.63.0
```

```js
import { chromium } from 'playwright';
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1400, height: 900 } });
p.on('response', r => { if (r.url().includes('/api/')) console.log(r.status(), r.url()); });
p.on('requestfailed', r => console.log('FAILED', r.url()));   // catches server-side crashes
await p.goto('http://127.0.0.1:8791/?token=' + TOKEN, { waitUntil: 'load' });
await p.waitForTimeout(9000);        // CanvasKit needs ~8s before anything renders
await p.screenshot({ path: 'shot.png' });
```

It renders to canvas, so there is no DOM to query -- click by coordinate off a screenshot and verify by screenshot. Logging `/api/*` responses is the reliable signal for what the client actually did; a `requestfailed` / `net::ERR_EMPTY_RESPONSE` means a handler raised and the connection dropped.

Sidebar coordinates at 1400x900: Runbooks (49, 91), Server apps (57, 332), Machines (49, 383).

## Safety

- `ansible/inventory/hosts.ini` is real and gitignored. Back it up before driving device add/remove, and restore after -- the add/remove round-trip is otherwise clean except that it normalises the file's missing trailing newline.
- `POST /api/vault-password` and `POST /api/secrets` write the real OS keychain and vault. Drive only their missing-field variants, which 400 before writing.
- Some app data dirs (`/srv/baikal`) are owned by the `diot` service user and are not statable by the operator's account.
