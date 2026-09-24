"""The /story service's section of the /review page: source health and timings.

Reads story-cache/health.json (per-host fetch outcomes) and the timing fields
of the most recently written stories -- never their text. Standard library only.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

RECENT = 10


def health_rows(cache: Path) -> list[tuple]:
    """One row per source host, the ones failing now first."""
    try:
        data = json.loads((cache / "health.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(data, dict):
        return []
    rows = [
        (
            host,
            e.get("ok", 0),
            e.get("failed", 0),
            e.get("streak", 0),
            e.get("last_ok", ""),
            e.get("last_error", "") if e.get("streak") else "",
        )
        for host, e in data.items()
        if isinstance(e, dict)
    ]
    return sorted(rows, key=lambda r: (-int(r[3] or 0), str(r[0])))


def timing_rows(cache: Path) -> list[tuple]:
    """Timings of the RECENT newest written stories."""
    rows = []
    stories = [p for p in cache.glob("*.json") if p.name not in ("spend.json", "health.json")]
    for path in sorted(stories, key=lambda p: p.stat().st_mtime, reverse=True)[:RECENT]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and "model_seconds" in data:
            rows.append(
                (
                    data.get("day", ""),
                    data.get("fetch_seconds", ""),
                    data.get("model_seconds", ""),
                    data.get("input_chars", ""),
                    data.get("output_chars", ""),
                    len(data.get("notes") or []),
                )
            )
    return rows


def section(cache: Path, table: Callable[[list[str], list[tuple]], str]) -> str:
    """Source health and recent timings, as HTML tables built by `table`."""
    health = health_rows(cache)
    timings = timing_rows(cache)
    return table(
        ["source host", "ok", "failed", "failing now", "last ok", "last error"],
        health or [("no fetches yet", "", "", "", "", "")],
    ) + table(
        ["edition", "fetch s", "model s", "chars in", "chars out", "sources not read"],
        timings or [("no timed stories yet", "", "", "", "", "")],
    )
