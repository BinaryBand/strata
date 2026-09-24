"""The Artifacts screen: what the site publishes, the last build, and /story's sources.

Publications are the top-level folders of the live site release that nginx
serves (site-public/current), which /review shares a port with, so each card
links straight to the page. Titles come from the agent's publication.toml,
parsed as data; nothing is followed through a symlink except `current`
itself, which must point at a release folder. Standard library only.
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
DAY = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


@dataclass
class Publication:
    """One published folder of the live site."""

    slug: str
    title: str
    files: int
    size: int
    updated: float


def release() -> Path | None:
    """The live release folder `current` points at, or None when it is not a release."""
    link = content.ROOT / "site-public" / "current"
    try:
        target = str(link.readlink())
    except OSError:
        return None
    return content.ROOT / "site-public" / target if RELEASE.fullmatch(target) else None


def measure(folder: Path) -> tuple[int, int, float]:
    """(files, bytes, newest mtime) under folder, without following links, bounded."""
    files, size, newest = 0, 0, 0.0
    for dirpath, dirnames, filenames in os.walk(folder, followlinks=False):
        dirnames.sort()
        for name in filenames:
            if files >= MAX_FILES:
                return files, size, newest
            try:
                st = (Path(dirpath) / name).lstat()
            except OSError:
                continue
            if stat.S_ISREG(st.st_mode):
                files, size, newest = files + 1, size + st.st_size, max(newest, st.st_mtime)
    return files, size, newest


def title_of(slug: str) -> str:
    """The publication's title from its publication.toml, else its folder name."""
    if slug == "news":
        return "The Daily Seek"
    try:
        fd = content.open_no_follow(f"storage/anythingllm-fs/site/{slug}/publication.toml")
    except OSError:
        return slug
    with os.fdopen(fd, "rb") as handle:
        try:
            data = tomllib.loads(handle.read(16 * 1024).decode("utf-8", errors="replace"))
        except tomllib.TOMLDecodeError:
            return slug
    title = data.get("title")
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
            files, size, updated = measure(Path(entry.path))
            found.append(Publication(entry.name, title_of(entry.name), files, size, updated))
    return found


def editions() -> list[str]:
    """Built news editions, newest first, from the builder's story lists."""
    try:
        names = [p.name for p in (content.ROOT / "site-public" / "stories").iterdir()]
    except OSError:
        return []
    days = [n.removesuffix(".json") for n in names if n.endswith(".json")]
    return sorted((d for d in days if DAY.fullmatch(d)), reverse=True)


def size_text(size: int) -> str:
    """Bytes as KB or MB."""
    return f"{size / 1024:.0f} KB" if size < 1024 * 1024 else f"{size / 1024 / 1024:.1f} MB"


def updated_text(mtime: float) -> str:
    """A file time as local 'YYYY-MM-DD HH:MM'."""
    return content.when(mtime * 1000) if mtime else "--"


def card(pub: Publication) -> str:
    """A publication's card for the Overview grid."""
    return (
        f'<a class="card" href="/{ui.esc(pub.slug)}/" target="_blank" rel="noopener noreferrer" '
        'style="overflow:hidden;display:flex;flex-direction:column;text-decoration:none">'
        '<div class="preview" style="height:130px;border-radius:0">page preview</div>'
        '<div class="stack" style="padding:14px 16px;gap:4px">'
        f'<span style="font-weight:500">{ui.esc(pub.title)}</span>'
        f'<span class="mono small">/{ui.esc(pub.slug)}/</span>'
        f'<span class="small">Updated {ui.esc(updated_text(pub.updated))}</span></div></a>'
    )


def build_status() -> str:
    """The site builder's last outcome, from the status file it writes."""
    status = content.read_json("site-public/status.json")
    if not isinstance(status, dict):
        return '<div class="small">No build status yet.</div>'
    ok = status.get("ok") is True
    rejected = status.get("rejected")
    rejected = rejected if isinstance(rejected, list) else []
    waiting_list = status.get("waiting")
    waiting_list = waiting_list if isinstance(waiting_list, list) else []
    skipped = [(r.get("file"), r.get("reason")) for r in rejected if isinstance(r, dict)]
    waiting = [(w, "no edition.toml yet") for w in waiting_list]
    return (
        '<div class="card pad stack">'
        f'<div class="sechead" style="align-items:center"><span style="font-weight:500">Last build'
        f"</span>{ui.pill('Published', 'ok') if ok else ui.pill('FAILED', 'warn')}</div>"
        f'<div class="muted">{ui.esc(status.get("time"))} · {ui.esc(status.get("editions"))} '
        f"editions built · release {ui.esc(status.get('release') or '--')}</div>"
        + ui.plain_table(["Skipped or waiting", "Why"], skipped + waiting or [("none", "")])
        + "</div>"
    )


def screen(prefix: str) -> str:
    """The Artifacts screen."""
    days = editions()
    cards = []
    for pub in publications():
        made = (
            "Built by the site builder from the daily news job's data"
            if pub.slug == "news"
            else "Built by the site builder from the agent's Markdown pages"
        )
        extra = ""
        if pub.slug == "news" and days:
            links = " · ".join(
                f'<a href="/news/{ui.esc(d)}/" target="_blank" rel="noopener noreferrer">'
                f"{ui.esc(d)}</a>"
                for d in days[:7]
            )
            extra = f'<span class="small">Editions: {links}</span>'
        cards.append(
            '<div class="card art"><div class="preview">page preview</div>'
            '<div class="stack" style="flex-grow:1;gap:6px;min-width:0">'
            f'<span style="font-size:16px;font-weight:500">{ui.esc(pub.title)}</span>'
            f'<span class="mono">/{ui.esc(pub.slug)}/</span>'
            f'<span class="small">{pub.files} file{"" if pub.files == 1 else "s"} · '
            f"{ui.esc(size_text(pub.size))} · "
            f"updated {ui.esc(updated_text(pub.updated))}</span>"
            f'<span class="small">{ui.esc(made)}</span>{extra}</div>'
            f'<a class="btn" href="/{ui.esc(pub.slug)}/" target="_blank" '
            'rel="noopener noreferrer">Open</a></div>'
        )
    return (
        ui.header(
            prefix,
            "Artifacts",
            "Pages the site publishes from the agent's data. They open in a new tab.",
            '<span class="muted">Served on this port at <span class="mono">/</span></span>',
        )
        + '<section class="stack" style="gap:14px">'
        + ("".join(cards) or '<div class="card pad small">Nothing is published yet.</div>')
        + "</section>"
        + '<section class="sec"><h2>Site build</h2>'
        + build_status()
        + "</section>"
        + '<section class="sec"><h2>Story sources</h2><div class="card pad stack">'
        + review_story.section(content.ROOT / "story-cache", ui.plain_table)
        + "</div></section>"
    )
