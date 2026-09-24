"""The Files screen: the agent's file folder, one folder at a time.

Everything in the agent's folder opens in the viewer, since the agent can read
all of it. The rest of the data folder can be browsed from the Admin only
part: there, entries show name, size, owner and mode, and only an allowlist of
non-secret files opens. A folder is opened one component at a time with
O_NOFOLLOW, so no symlink is ever followed; links are listed as links.
Standard library only.
"""

from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path

import review_content as content
import review_layout as ui

MAX_LISTED = 2000
SHOWN = 200
SECRET_FILES = ("storage/.env",)
SECRET_DIRS = ("storage/comkey",)


class FolderError(Exception):
    """A folder that cannot be shown."""


def parts_of(rel: str) -> list[str]:
    """The path's components, refusing '.', '..' and empty paths inside."""
    parts = [p for p in rel.split("/") if p]
    if any(p in (".", "..") for p in parts):
        raise FolderError(rel)
    return parts


def open_folder(parts: list[str]) -> int:
    """A directory descriptor for ROOT/parts, refusing a symlink at any step."""
    fd = os.open(content.ROOT, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in parts:
            nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = nxt
    except OSError as exc:
        os.close(fd)
        raise FolderError("/".join(parts)) from exc
    return fd


def listing(parts: list[str]) -> list[tuple[str, os.stat_result]]:
    """(name, lstat) for each entry of the folder, folders first, bounded."""
    fd = open_folder(parts)
    try:
        try:
            # A no-follow directory descriptor: Path.iterdir cannot list one.
            names = sorted(os.listdir(fd))[:MAX_LISTED]  # noqa: PTH208
        except OSError as exc:
            raise FolderError("/".join(parts)) from exc
        found = []
        for name in names:
            try:
                found.append((name, os.stat(name, dir_fd=fd, follow_symlinks=False)))
            except OSError:
                continue
    finally:
        os.close(fd)
    return sorted(found, key=lambda e: (not stat.S_ISDIR(e[1].st_mode), e[0]))


def count(parts: list[str]) -> int:
    """How many entries a folder holds, or 0 when it cannot be read."""
    try:
        fd = open_folder(parts)
    except FolderError:
        return 0
    try:
        return len(os.listdir(fd))  # noqa: PTH208
    except OSError:
        return 0
    finally:
        os.close(fd)


def entry_row(prefix: str, parts: list[str], name: str, st: os.stat_result) -> str:
    """One entry as a row: folders and viewable files link, links are never followed."""
    rel = "/".join([*parts, name])
    changed = content.day_time(st.st_mtime * 1000)
    agent = content.in_agent_dir(rel)
    extra = "" if agent else f" · {content.owner(st)} · {stat.filemode(st.st_mode)}"
    if stat.S_ISLNK(st.st_mode):
        return ui.row(name, f"link, not followed{extra}")
    if stat.S_ISDIR(st.st_mode):
        items = count([*parts, name])
        return ui.row(
            f"{name}/",
            f"{items} item{'s' * (items != 1)} · {changed}{extra}",
            "",
            ui.href(prefix, "files", path=rel),
        )
    kind = rel[rel.rfind(".") + 1 :].upper() if "." in name else "File"
    sub = f"{kind} · {content.size_text(st.st_size)} · {changed}{extra}"
    pill = ui.pill("Agent-written", "accent") if content.AGENT_WRITTEN.fullmatch(rel) else ""
    if content.viewable(rel):
        return ui.row(name, sub, pill, ui.href(prefix, "file", path=rel))
    return ui.row(name, sub, ui.pill("Name and size only"))


def crumbs(prefix: str, parts: list[str]) -> str:
    """The trail from the agent folder, or from the data folder when outside it."""
    agent = content.AGENT_DIR.split("/")
    start = len(agent) if parts[: len(agent)] == agent else 0
    first = ("agent folder", content.AGENT_DIR) if start else ("data folder", "")
    trail = [f'<a href="{ui.href(prefix, "files", path=first[1])}">{ui.esc(first[0])}</a>']
    trail += [
        f'<a href="{ui.href(prefix, "files", path="/".join(parts[: i + 1]))}">{ui.esc(p)}</a>'
        for i, p in enumerate(parts[start:], start)
    ]
    return '<div class="crumb">' + " &rsaquo; ".join(trail) + "</div>"


def fingerprint(rel: str) -> str:
    """'sha256:3f9a…c21e' for a file, read without following links."""
    try:
        data, _ = content.read_bytes(rel, 1024 * 1024)
    except content.ViewError:
        return "unreadable"
    digest = hashlib.sha256(data).hexdigest()
    return f"sha256:{digest[:4]}…{digest[-4:]}"


def folder_size(top: str) -> int:
    """Bytes in regular files under ROOT/top, links never followed, bounded."""
    total, seen = 0, 0
    for dirpath, _, filenames in os.walk(content.ROOT / top, followlinks=False):
        for name in filenames:
            seen += 1
            if seen > 50_000:  # noqa: PLR2004
                return total
            try:
                st = (Path(dirpath) / name).lstat()
            except OSError:
                continue
            total += st.st_size if stat.S_ISREG(st.st_mode) else 0
    return total


def admin_part(prefix: str) -> str:
    """Secret files by fingerprint, the agent folder's size, and the whole data folder."""
    secret = list(SECRET_FILES)
    for top in SECRET_DIRS:
        try:
            secret += [f"{top}/{n}" for n in sorted(os.listdir(content.ROOT / top))]  # noqa: PTH208
        except OSError:
            continue
    items = []
    for rel in secret:
        try:
            st = (content.ROOT / rel).lstat()
        except OSError:
            continue
        items.append(
            ui.row(
                rel.removeprefix("storage/"),
                f"{content.size_text(st.st_size)} · fingerprint {fingerprint(rel)}",
            )
        )
    items.append(ui.row("Agent folder size", content.size_text(folder_size(content.AGENT_DIR))))
    items.append(
        ui.row(
            "The whole data folder",
            "Names, sizes, owners and modes; only non-secret files open",
            ui.icon("chevron"),
            ui.href(prefix, "files", path="-"),
        )
    )
    return ui.admin(ui.rows(items))


def screen(prefix: str, rel: str, *, show_all: bool = False) -> tuple[int, str]:
    """(status, main markup) for a folder: the agent's by default, '-' for the data folder."""
    rel = "" if rel == "-" else rel or content.AGENT_DIR
    try:
        parts = parts_of(rel)
        entries = listing(parts)
    except FolderError:
        return 404, ui.header("Files", "That folder cannot be shown.")
    agent = content.in_agent_dir(rel + "/")
    shown = entries if show_all else entries[:SHOWN]
    more = (
        ui.more(
            ui.href(prefix, "files", path=rel or "-", all=1),
            f"Show {len(entries) - len(shown)} more",
        )
        if len(shown) < len(entries)
        else ""
    )
    lede = (
        "The agent&rsquo;s file folder. Open any file to read it."
        if agent
        else f"The data folder outside the agent&rsquo;s reach. {ui.pill('Admin only', 'admin')}"
    )
    how = ui.card(
        "How files open",
        "<div>"
        + ui.kv("Text and Markdown", "Shown as written")
        + ui.kv("TOML and JSON", "Formatted")
        + ui.kv("Anything else", "Size, type and the first bytes in hex")
        + "</div>",
    )
    return 200, (
        ui.header("Files", lede)
        + crumbs(prefix, parts)
        + ui.rows([entry_row(prefix, parts, n, st) for n, st in shown], "Empty folder.")
        + more
        + (how if agent else "")
        + admin_part(prefix)
    )
