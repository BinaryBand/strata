"""The Files screen: one folder at a time, and the viewer for allowlisted files.

A folder is opened one component at a time with O_NOFOLLOW, so no symlink is
ever followed; links are listed as links. Every entry shows its name, size,
owner, mode and time. Only files on review_content's allowlist link to the
viewer; secret files stay name-and-size only. Standard library only.
"""

from __future__ import annotations

import html
import os
import pwd
import stat
import time
from urllib.parse import urlencode

import review_content as content
import review_layout as ui

MAX_LISTED = 2000


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


def owner(uid: int) -> str:
    """An account name, or the uid when unknown."""
    try:
        return pwd.getpwuid(uid).pw_name
    except KeyError:
        return str(uid)


def link(prefix: str, route: str, rel: str, label_html: str) -> str:
    """A link to one of the monitor's routes for the path rel."""
    return f'<a href="{prefix}/{route}?{ui.esc(urlencode({"path": rel}))}">{label_html}</a>'


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


def row(prefix: str, rel: str, name: str, st: os.stat_result) -> list[str]:
    """One entry's cells: linked name, size, owner and mode, changed."""
    path = f"{rel}/{name}" if rel else name
    when = time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime))
    meta = ui.esc(f"{owner(st.st_uid)} · {stat.filemode(st.st_mode)}")
    if stat.S_ISLNK(st.st_mode):
        note = "<span class=small>(link, not followed)</span>"
        label = f"{ui.icon('file', '#5E5D59')} {ui.esc(name)} {note}"
        return [label, "", meta, ui.esc(when)]
    if stat.S_ISDIR(st.st_mode):
        label = link(
            prefix, "files", path, f"{ui.icon('files', '#B8532F')} <strong>{ui.esc(name)}</strong>"
        )
        return [label, "folder", meta, ui.esc(when)]
    label = f"{ui.icon('file', '#5E5D59')} {ui.esc(name)}"
    if content.viewable(path):
        label = link(prefix, "file", path, label)
    return [label, ui.esc(f"{st.st_size:,} B"), meta, ui.esc(when)]


def folder_nav(prefix: str, parts: list[str], children: list[str]) -> str:
    """The folder column: every folder on the way down, then this folder's subfolders."""
    items = [link(prefix, "files", "", "srv/anythingllm")]
    for depth, name in enumerate(parts, 1):
        on = ' class="on"' if depth == len(parts) else ""
        target = "/".join(parts[:depth])
        items.append(
            link(prefix, "files", target, ui.esc(name)).replace(
                "<a ", f'<a{on} style="padding-left:{10 + 18 * depth}px" ', 1
            )
        )
    base = "/".join(parts)
    for name in children:
        target = f"{base}/{name}" if base else name
        items.append(
            link(prefix, "files", target, ui.esc(name)).replace(
                "<a ", f'<a style="padding-left:{10 + 18 * (len(parts) + 1)}px" ', 1
            )
        )
    return f'<section class="card folders" aria-label="Folders">{"".join(items)}</section>'


def crumbs(prefix: str, parts: list[str]) -> str:
    """The breadcrumb from the root to this folder."""
    trail = [link(prefix, "files", "", "srv/anythingllm")]
    trail += [
        link(prefix, "files", "/".join(parts[: i + 1]), ui.esc(p)) for i, p in enumerate(parts)
    ]
    return ' <span aria-hidden="true">&rsaquo;</span> '.join(trail)


def screen(prefix: str, rel: str) -> tuple[int, str]:
    """(status, main markup) for the folder rel under ROOT."""
    try:
        parts = parts_of(rel)
        entries = listing(parts)
    except FolderError:
        return 404, ui.header(prefix, "Files", "That folder cannot be shown.")
    base = "/".join(parts)
    children = [n for n, st in entries if stat.S_ISDIR(st.st_mode)]
    table = ui.grid_table(
        "1fr 110px 170px 150px",
        ["Name", "Size", "Owner · mode", "Changed"],
        [row(prefix, base, name, st) for name, st in entries] or [["Empty folder", "", "", ""]],
        framed=False,
    )
    return 200, (
        ui.header(
            prefix,
            "Files",
            "Browse the AnythingLLM folders. Allowlisted files open in the viewer; "
            "secret files show their name and size only.",
            f'<span class="muted">{len(entries)} items here</span>',
        )
        + f'<div class="files">{folder_nav(prefix, parts, children)}'
        + '<div class="stack" style="gap:20px;min-width:0"><section class="card">'
        + '<div class="crumb" style="padding:14px 20px;border-bottom:1px solid var(--soft)">'
        + f"{crumbs(prefix, parts)}</div>"
        + table
        + "</section></div></div>"
    )


def file_view(prefix: str, rel: str) -> tuple[int, str]:
    """(status, main markup) for the viewer: an allowlisted file's text, escaped."""
    try:
        text = content.read_allowed(rel)
    except content.ViewError as exc:
        return exc.status, ui.header(prefix, "Files", str(exc))
    if rel.endswith("/plugin.json"):
        text = content.redact_manifest(text)
    note = (
        '<p class="agent">Written by the AI agent: this is its text, not the monitor\'s.</p>'
        if content.AGENT_WRITTEN.fullmatch(rel)
        else ""
    )
    parts = [p for p in rel.split("/") if p]
    return 200, (
        ui.header(prefix, parts[-1] if parts else "File", "View only.")
        + f'<div class="crumb">{crumbs(prefix, parts[:-1])}</div>{note}'
        + '<section class="card"><div class="sechead" style="padding:14px 20px;'
        f'border-bottom:1px solid var(--soft)"><span style="font-weight:500">{ui.esc(rel)}</span>'
        f'<span class="small">{len(text):,} characters</span></div>'
        '<pre class="log" style="margin:0;border-radius:0 0 16px 16px">'
        f"{html.escape(text)}</pre></section>"
    )
