"""The /story service's part of the Artifacts screen: source health and timings.

Reads story-cache/health.json (per-host fetch outcomes) and the timing fields
of the most recently written stories -- never their text, which the agent
never sees either. Standard library only.
"""

from __future__ import annotations

import json
from pathlib import Path

import review_layout as ui

RECENT = 10
SLOW_SECONDS = 8


def health_rows(cache: Path) -> list[str]:
    """One row per source host, the ones failing now first."""
    try:
        data = json.loads((cache / "health.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(data, dict):
        return []
    hosts = sorted(
        ((h, e) for h, e in data.items() if isinstance(e, dict)),
        key=lambda item: (-int(item[1].get("streak") or 0), str(item[0])),
    )
    found = []
    for host, e in hosts:
        streak = int(e.get("streak") or 0)
        seconds = e.get("seconds")
        if streak:
            sub = f"Failed {streak} time{'s' * (streak != 1)} in a row: {e.get('last_error', '')}"
            sub += f" · last OK {e['last_ok']}" if e.get("last_ok") else ""
            pill = ui.pill("Failing", "bad")
        elif isinstance(seconds, int | float) and seconds > SLOW_SECONDS:
            sub, pill = f"Answered in {seconds:.1f} s", ui.pill("Slow", "warn")
        else:
            sub = f"{e.get('ok', 0)} fetched · last OK {e.get('last_ok') or 'never'}"
            pill = ui.pill("OK", "ok")
        found.append(ui.row(str(host), sub, pill))
    return found


def timing_rows(cache: Path) -> list[str]:
    """Timings of the RECENT newest written stories."""
    stories = [p for p in cache.glob("*.json") if p.name not in ("spend.json", "health.json")]
    found = []
    for path in sorted(stories, key=lambda p: p.stat().st_mtime, reverse=True)[:RECENT]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and "model_seconds" in data:
            skipped = len(data.get("notes") or [])
            got = {k: data.get(k, "?") for k in ("fetch_seconds", "model_seconds")}
            size = {k: data.get(k, "?") for k in ("input_chars", "output_chars")}
            line = (
                f"fetch {got['fetch_seconds']} s · write {got['model_seconds']} s"
                f" · {size['input_chars']} chars in, {size['output_chars']} out"
            )
            if skipped:
                line += f" · {skipped} source{'s' * (skipped != 1)} not read"
            found.append(ui.row(str(data.get("day", "")), line))
    return found


def section(cache: Path) -> str:
    """Source health, then recent story timings."""
    return (
        ui.rows(health_rows(cache), "No fetches yet.")
        + '<h3 style="margin-top:6px">Recent story timings</h3>'
        + ui.rows(timing_rows(cache), "No timed stories yet.")
    )
