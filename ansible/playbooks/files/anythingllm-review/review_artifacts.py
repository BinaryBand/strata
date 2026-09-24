"""The Artifacts screen: what the agent publishes, its research runs, and /story's sources.

Publications are the top-level folders of the live site release
(site-public/current), served on the site's own origin, so each card links
there in a new tab. Titles come from the agent's publication.toml, parsed as
data; nothing is followed through a symlink except `current` itself, which
must point at a release folder. A research run passed when the research skill
published its report into the agent's folder. The event log is the server's,
so it is Admin only. Standard library only.
"""

from __future__ import annotations

import os
import re
import stat
import tomllib
from dataclasses import dataclass
from pathlib import Path

import review_content as content
import review_layout as ui
import review_story

MAX_FILES = 5000
RELEASE = re.compile(r"releases/[0-9A-Za-z]{1,40}")
RUNS = "storage/research-runs"
TITLE = re.compile(r"^#\s+(.+)$", re.MULTILINE)


@dataclass
class Publication:
    """One published folder of the live site."""

    slug: str
    title: str
    pages: int
    updated: float


def release() -> Path | None:
    """The live release folder `current` points at, or None when it is not a release."""
    link = content.ROOT / "site-public" / "current"
    try:
        target = str(link.readlink())
    except OSError:
        return None
    return content.ROOT / "site-public" / target if RELEASE.fullmatch(target) else None


def measure(folder: Path) -> tuple[int, float]:
    """(HTML pages, newest mtime) under folder, without following links, bounded."""
    pages, newest, seen = 0, 0.0, 0
    for dirpath, dirnames, filenames in os.walk(folder, followlinks=False):
        dirnames.sort()
        for name in filenames:
            seen += 1
            if seen > MAX_FILES:
                return pages, newest
            try:
                st = (Path(dirpath) / name).lstat()
            except OSError:
                continue
            if stat.S_ISREG(st.st_mode):
                pages += name.endswith(".html")
                newest = max(newest, st.st_mtime)
    return pages, newest


def title_of(slug: str) -> str:
    """The publication's title from its publication.toml, else its folder name."""
    if slug == "news":
        return "The Daily Seek"
    try:
        data, _ = content.read_bytes(f"{content.AGENT_DIR}/site/{slug}/publication.toml", 16 * 1024)
        parsed = tomllib.loads(data.decode("utf-8", errors="replace"))
    except (content.ViewError, tomllib.TOMLDecodeError):
        return slug
    title = parsed.get("title")
    return str(title)[:200] if isinstance(title, str) and title.strip() else slug


def publications() -> list[Publication]:
    """Every top-level folder of the live release, news first."""
    live = release()
    if live is None:
        return []
    try:
        entries = sorted(os.scandir(live), key=lambda e: (e.name != "news", e.name))
    except OSError:
        return []
    found = []
    for entry in entries:
        if entry.is_dir(follow_symlinks=False) and entry.name != "archive":
            pages, updated = measure(Path(entry.path))
            found.append(Publication(entry.name, title_of(entry.name), pages, updated))
    return found


def build_status() -> dict:
    """The site builder's last outcome, or {} before its first build."""
    status = content.read_json("site-public/status.json")
    return status if isinstance(status, dict) else {}


def site_link(path: str) -> str:
    """An absolute link to a page on the site's own origin."""
    return ui.esc(f"{content.SITE_URL}{path}")


def pub_card(pub: Publication, ok: bool) -> str:  # noqa: FBT001 -- the build's outcome
    """A publication: where it is, how big, when it changed."""
    return ui.card(
        pub.title,
        "<div>"
        + ui.kv("Path", ui.mono(f"/{pub.slug}/"))
        + ui.kv("Pages", ui.esc(pub.pages))
        + ui.kv("Last updated", ui.esc(content.day_time(pub.updated * 1000)))
        + "</div>"
        + f'<a class="more" href="{site_link(f"/{pub.slug}/")}" target="_blank" '
        f'rel="noopener noreferrer">Open {ui.esc(pub.title)}</a>',
        ui.pill("Published", "ok") if ok else ui.pill("Last build failed", "bad"),
    )


def research_runs(prefix: str) -> list[str]:
    """One row per research run, newest first: its question, date and outcome."""
    try:
        runs = sorted(
            (e for e in os.scandir(content.ROOT / RUNS) if e.is_dir(follow_symlinks=False)),
            key=lambda e: e.stat(follow_symlinks=False).st_mtime,
            reverse=True,
        )
    except OSError:
        return []
    found = []
    for run in runs[:50]:
        final = f"{RUNS}/{run.name}/reports/final.md"
        published = f"{content.AGENT_DIR}/research/{run.name}.md"
        try:
            text = content.read_bytes(final, 16 * 1024)[0].decode("utf-8", errors="replace")
        except content.ViewError:
            text = ""
        heading = TITLE.search(text)
        question = heading.group(1).strip() if heading else run.name
        day = content.day_time(run.stat(follow_symlinks=False).st_mtime * 1000)
        if (content.ROOT / published).is_file():
            found.append(
                ui.row(
                    question,
                    f"{day} · check passed",
                    ui.pill("Passed", "ok"),
                    ui.href(prefix, "file", path=published),
                )
            )
        elif text:
            found.append(
                ui.row(
                    question,
                    f"{day} · report not passed yet",
                    ui.pill("Not finished", "warn"),
                    ui.href(prefix, "file", path=final),
                )
            )
        else:
            found.append(ui.row(question, f"{day} · no report yet", ui.pill("In progress")))
    return found


def screen(prefix: str) -> str:
    """The Artifacts screen."""
    status = build_status()
    ok = status.get("ok") is not False
    cards = "".join(pub_card(p, ok) for p in publications())
    events = content.rows("select event, occurredAt from event_logs order by id desc limit 30")
    return (
        ui.header("Artifacts", "What the agent publishes. Pages open in a new tab.")
        + (cards or '<div class="muted">Nothing is published yet.</div>')
        + ui.section("Research runs", ui.rows(research_runs(prefix), "No research runs yet."))
        + ui.section(
            "/story",
            review_story.section(content.ROOT / "story-cache"),
            "Source health, failing first",
        )
        + ui.admin(
            ui.card(
                "Event log",
                ui.code("\n".join(f"{content.when(t)}  {e}" for e, t in events) or "No events."),
            )
        )
    )
