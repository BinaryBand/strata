"""Choose, fetch and keep score of a story's sources.

A story lists up to ten sources. The first USE of them that can be read are
sent to the model: up to TRY candidates are fetched at once, skipping any
outlet whose last FAILURES fetches all failed within RETRY_DAYS, and the
readable ones are taken in the story's order. Every outcome is recorded per
host in health.json, which /review shows so a failing feed can be replaced.
Standard library only.
"""

from __future__ import annotations

import datetime as dt
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

import story_fetch

USE = 2
TRY = 4
FAILURES = 3
RETRY_DAYS = 7


class Health:
    """Per-host fetch outcomes, persisted as JSON, safe across worker threads."""

    def __init__(self, path: Path) -> None:
        """Keep the record at `path`."""
        self.path = path
        self.lock = threading.Lock()

    def load(self) -> dict:
        """The record, or an empty one when missing or damaged."""
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def skipped(self, url: str) -> bool:
        """Whether url's host failed its last FAILURES fetches, the latest within RETRY_DAYS."""
        entry = self.load().get(host(url), {})
        if entry.get("streak", 0) < FAILURES:
            return False
        try:
            last = dt.datetime.fromisoformat(entry["last_failure"])
        except (KeyError, TypeError, ValueError):
            return False
        return dt.datetime.now(dt.UTC) - last < dt.timedelta(days=RETRY_DAYS)

    def record(self, url: str, error: str | None) -> None:
        """Count one fetch of url: a success when error is None."""
        now = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
        with self.lock:
            data = self.load()
            entry = data.setdefault(host(url), {"ok": 0, "failed": 0, "streak": 0})
            if error is None:
                entry.update(ok=entry.get("ok", 0) + 1, streak=0, last_ok=now)
            else:
                entry.update(
                    failed=entry.get("failed", 0) + 1,
                    streak=entry.get("streak", 0) + 1,
                    last_failure=now,
                    last_error=error[:200],
                )
            tmp = self.path.with_name(f".{self.path.name}.tmp")
            tmp.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")
            tmp.replace(self.path)


def host(url: str) -> str:
    """The URL's host, without a leading www."""
    name = (urlsplit(url).hostname or "").lower()
    return name.removeprefix("www.")


def gather(sources: list[dict], health: Health) -> tuple[list[tuple[dict, str]], list[str]]:
    """([(source, text)] for up to USE readable sources in order, [notes on the rest])."""
    candidates, notes = [], []
    for source in sources:
        if len(candidates) == TRY:
            break
        if health.skipped(source["url"]):
            notes.append(f"{source['name']} (skipped: failed {FAILURES} times running)")
        else:
            candidates.append(source)

    def fetch(source: dict) -> tuple[dict, str | None, str]:
        try:
            text = story_fetch.fetch_text(source["url"])
        except story_fetch.FetchError as exc:
            health.record(source["url"], str(exc))
            return source, None, str(exc)
        health.record(source["url"], None)
        return source, text, ""

    with ThreadPoolExecutor(max_workers=TRY) as pool:
        results = list(pool.map(fetch, candidates))
    read = [(source, text) for source, text, _ in results if text is not None][:USE]
    notes += [f"{source['name']} ({error})" for source, text, error in results if text is None]
    return read, notes
