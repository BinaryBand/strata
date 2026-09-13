# strata_gui

A Flutter GUI for [strata](../README.md), ported from the `design/gui`
Claude Design mockup. Three screens — Runbooks (browse, inspect guards, run),
Server apps, and Machines — sharing a dark IBM Plex theme and a single
`AppState` (`lib/app_state.dart`).

On startup the app loads the real runbook catalog and device inventory:
dotted names, categories, aliases, descriptions, and guard chains all come
straight from `discovery.py` and `guard.declared()`, and devices come from
`ansible/inventory/hosts.ini`. Nothing is executed and no `check()` is
invoked, so install status, guard "known" state, and machine reachability
are still simulated. On desktop this shells out to `strata dev gui-data` (a
hidden, read-only CLI command — see `strata/cli/commands/dev.py`), which only
works where `dart:io` can spawn a process and only from inside (or under) the
strata repo. On web there is no `dart:io`, so the app instead fetches
`GET /api/gui-data` on its own origin — see "Serving the web build" below. If
neither path is available, or it fails, the app falls back to the static
sample data in `lib/mock_data.dart` and shows a small "Sample data" notice in
the sidebar.

## Run

Only `lib/`, the pubspec pair, `analysis_options.yaml` and `.metadata` are
tracked -- the `linux/`, `macos/`, `windows/` and `web/` runner directories are
`flutter create` output with no hand-written code in them, so they are
gitignored and recreated on first checkout:

```bash
flutter create .        # regenerates the platform runners; safe to re-run
flutter pub get
flutter run -d linux    # or macos, windows, chrome (chrome uses sample data unless served per below)
```

`flutter create .` reads the project name from `pubspec.yaml` and will not
touch `lib/`. `.metadata` pins the Flutter revision the runners were first
generated from, so a regeneration matches what the app was written against.

## Serving the web build

`flutter run -d chrome` and a bare `flutter build web` opened as a file both
show sample data — nothing serves `/api/gui-data` for them to fetch. To get
the real catalog in a browser (including a phone's, over Tailscale):

```bash
flutter build web
uv run strata dev gui-serve   # from the repo root; binds 127.0.0.1:8765
```

`gui-serve` serves `gui/build/web/` as static files and `/api/gui-data` as
the same snapshot `gui-data` prints, both from one loopback port. Reach it
from another device on your tailnet with `tailscale serve 8765` — not
`tailscale funnel`, which would put it on the open internet; this fronts a
tool that reads the vault and drives ansible-runner, even though nothing
served today executes anything.

## Layout

- `lib/models.dart` — data classes and enums (`Runbook`, `Guard`, `MachineInfo`, ...)
- `lib/mock_data.dart` — the sample runbook/device/machine/app catalog and readiness logic, used as a fallback
- `lib/data/strata_cli.dart` — shells out to `strata dev gui-data` and parses its JSON into the model types
- `lib/app_state.dart` — the `ChangeNotifier` holding all UI and derived state, including `loadRealData()`
- `lib/theme.dart` — color palette and text styles
- `lib/screens/` — Runbooks, Server apps, Machines
- `lib/widgets/` — sidebar, header/target switcher, shared buttons/badges
