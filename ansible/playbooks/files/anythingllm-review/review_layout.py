"""The /review monitor's page shell and shared pieces, after the Claude Design mock-up.

Every screen splits into what the agent can see and a "Server details" part
marked Admin only. The shell is a sidebar ("Whole instance" screens, then the
selected workspace's) on desktop and a top bar with a bottom tab bar on a
phone. Plain HTML and CSS: the Content-Security-Policy allows no scripts.
Every value passed in is escaped here unless a caller marks it as markup it
built itself. Standard library only.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from urllib.parse import urlencode

from review_style import CSS

CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
ICONS = {
    "overview": '<path d="M3 11l9-7 9 7"/><path d="M5 10v10h14V10"/>',
    "tools": (
        '<path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4'
        'l-2.5 2.5-2.5-.5-.5-2.5z"/>'
    ),
    "tasks": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "artifacts": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 9h18"/>',
    "files": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5'
    'a2 2 0 0 1-2-2z"/>',
    "workspace": '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" '
    'height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" '
    'width="7" height="7" rx="1.5"/>',
    "knowledge": '<path d="M4 5a2 2 0 0 1 2-2h13v16H6a2 2 0 0 0-2 2z"/><path d="M4 21V5"/>',
    "more": '<circle cx="5" cy="12" r="1.5"/><circle cx="12" cy="12" r="1.5"/>'
    '<circle cx="19" cy="12" r="1.5"/>',
    "alert": '<path d="M12 3l10 18H2z"/><path d="M12 10v5M12 18v.5"/>',
    "check": '<circle cx="12" cy="12" r="9"/><path d="M8 12l3 3 5-6"/>',
    "dot": '<circle cx="12" cy="12" r="5" fill="currentColor"/>',
    "lock": '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>',
    "chevron": '<path d="M9 6l6 6-6 6"/>',
}
# (key, label, route): the whole-instance screens, then each workspace's.
INSTANCE = (
    ("overview", "Overview", ""),
    ("tools", "Tools", "tools"),
    ("tasks", "Scheduled tasks", "tasks"),
    ("artifacts", "Artifacts", "artifacts"),
    ("files", "Files", "files"),
)
WORKSPACE = (("workspace", "Workspace", "workspace"), ("knowledge", "Knowledge", "knowledge"))
TABS = (
    ("overview", "Home", ""),
    ("workspace", "Workspace", "workspace"),
    ("tasks", "Tasks", "tasks"),
    ("tools", "Tools", "tools"),
    ("more", "More", "more"),
)


@dataclass
class Page:
    """Who is looking and where: what the shell needs besides the screen itself."""

    prefix: str
    login: str
    active: str
    ws: tuple[str, str] | None = None  # (slug, name) of the selected workspace
    workspaces: tuple[tuple[str, str], ...] = ()


def esc(text: object) -> str:
    """HTML-escaped text with control characters other than tab and newline shown as '?'."""
    return html.escape(CONTROL.sub("?", "" if text is None else str(text)))


def href(prefix: str, route: str, **query: object) -> str:
    """An escaped link to one of the monitor's routes."""
    params = {k: v for k, v in query.items() if v is not None and v != ""}
    tail = f"?{urlencode(params)}" if params else ""
    return esc(f"{prefix}/{route}{tail}")


def icon(name: str, size: int = 18) -> str:
    """One of the design's line icons."""
    return (
        f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="1.8" stroke-linecap="round" '
        f'stroke-linejoin="round" aria-hidden="true">{ICONS[name]}</svg>'
    )


def pill(text: str, kind: str = "") -> str:
    """A small label: kind '', 'ok', 'warn', 'bad', 'accent' or 'lock'."""
    return f'<span class="pill {kind}">{esc(text)}</span>'


def switch(on: bool) -> str:  # noqa: FBT001 -- mirrors the state it shows
    """A read-only on/off indicator with its word beside it."""
    state = "On" if on else "Off"
    kind = "sw on" if on else "sw"
    return f'<span class="{kind}"><i role="img" aria-label="{state}"></i>{state}</span>'


def kv(label: str, value_html: str) -> str:
    """A key-value row; the value is markup the caller built and escaped."""
    return f'<div class="kv"><span>{esc(label)}</span><span>{value_html}</span></div>'


def mono(text: object) -> str:
    """Text in the monospace face."""
    return f'<span class="mono">{esc(text)}</span>'


def stat(label: str, value: object, note: str = "") -> str:
    """A number tile."""
    small = f"<small>{esc(note)}</small>" if note else ""
    return f'<div class="stat"><small>{esc(label)}</small><b>{esc(value)}</b>{small}</div>'


def stats(tiles: list[str]) -> str:
    """A wrapping row of number tiles."""
    return f'<div class="stats">{"".join(tiles)}</div>'


def bar(title_html: str, aside_html: str = "") -> str:
    """A card's heading line with a note or pill on the right."""
    return f'<div class="bar">{title_html}<span>{aside_html}</span></div>'


def card(title: str, body_html: str, aside_html: str = "", link: str = "") -> str:
    """A card with an h3 heading; the whole card is a link when `link` is given."""
    head = bar(f"<h3>{esc(title)}</h3>", aside_html)
    if link:
        return f'<a class="card" href="{link}">{head}{body_html}</a>'
    return f'<section class="card">{head}{body_html}</section>'


def section(title: str, body_html: str, aside_html: str = "") -> str:
    """An h2 heading with a note on the right, then its body."""
    return bar(f"<h2>{esc(title)}</h2>", aside_html) + body_html


def row(title: str, sub: str = "", end_html: str = "", link: str = "") -> str:
    """A list row: title, a muted line under it, pills on the right."""
    inner = (
        f'<span class="grow"><span>{esc(title)}</span>'
        + (f"<span>{esc(sub)}</span>" if sub else "")
        + f'</span><span class="end">{end_html}</span>'
    )
    if link:
        return f'<a class="row" href="{link}">{inner}</a>'
    return f'<div class="row">{inner}</div>'


def rows(items: list[str], empty: str = "") -> str:
    """Rows in one flush card, or a muted line when there are none."""
    if not items:
        return f'<div class="muted">{esc(empty)}</div>' if empty else ""
    return f'<div class="card flush">{"".join(items)}</div>'


def code(text: str, *, big: bool = False) -> str:
    """Escaped text in a monospace block."""
    return f'<pre class="code{" big" if big else ""}">{esc(text)}</pre>'


def more(link: str, text: str) -> str:
    """An accent 'show more' link."""
    return f'<a class="more" href="{link}">{esc(text)}</a>'


def alert(kind: str, message_html: str) -> str:
    """A tinted notice: kind 'warn' or 'bad'. The message is markup the caller escaped."""
    role = ' role="alert"' if kind == "bad" else ""
    return f'<section class="alert {kind}"{role}>{icon("alert")}<div>{message_html}</div></section>'


def header(title: str, lede_html: str = "", crumb: tuple[str, str] | None = None) -> str:
    """A screen's optional breadcrumb, title and one-line description."""
    trail = ""
    if crumb:
        trail = (
            f'<div class="crumb"><a href="{crumb[1]}">{esc(crumb[0])}</a> '
            '<span aria-hidden="true">&rsaquo;</span></div>'
        )
    lede = f'<div class="lede">{lede_html}</div>' if lede_html else ""
    return f'<header class="head">{trail}<h1>{esc(title)}</h1>{lede}</header>'


def admin(body_html: str) -> str:
    """The Admin only part of a screen: what the monitor reads that the agent never sees."""
    return (
        '<section class="admin" aria-label="Admin only"><div class="bar" '
        'style="justify-content:flex-start"><h2>Server details</h2>'
        f'<span class="pill lock">{icon("lock", 12)}Admin only</span>'
        '<span class="muted">The agent can&rsquo;t see anything in this section.</span></div>'
        f"{body_html}</section>"
    )


def _nav(page: Page) -> str:
    """The desktop sidebar."""
    link = page.prefix
    ws = {"ws": page.ws[0]} if page.ws else {}
    items = [
        f'<a class="nav{" on" if key == page.active else ""}" href="{href(link, route)}">'
        f"{icon(key)}{esc(label)}</a>"
        for key, label, route in INSTANCE
    ]
    if page.ws:
        others = "".join(
            f'<a href="{href(link, "workspace", ws=slug)}">{esc(name)}</a>'
            for slug, name in page.workspaces
            if slug != page.ws[0]
        )
        items.append(
            '<div class="wsgroup"><span class="muted">Workspace</span>'
            f"<b>{icon('workspace')}{esc(page.ws[1])}</b>{others}</div>"
        )
        items += [
            f'<a class="nav{" on" if key == page.active else ""}" href="{href(link, route, **ws)}">'
            f"{icon(key)}{esc(label)}</a>"
            for key, label, route in WORKSPACE
        ]
    name = page.login.split("@", maxsplit=1)[0] or "Admin"
    return (
        '<nav class="side" aria-label="Sections"><div class="brand">AnythingLLM</div>'
        '<div class="group">Whole instance</div>'
        + "".join(items)
        + f'<div class="who"><span class="avatar">{esc(name[:1].upper())}</span>'
        f"<div><span>{esc(name)}</span><small>Read only</small></div></div></nav>"
    )


def _tabs(page: Page) -> str:
    """The phone's bottom tab bar."""
    ws = {"ws": page.ws[0]} if page.ws else {}
    on = page.active if page.active in {k for k, _, _ in TABS} else "more"
    links = "".join(
        f'<a class="{"on" if key == on else ""}" href="{href(page.prefix, route, **ws)}">'
        f"{icon(key)}{esc(label)}</a>"
        for key, label, route in TABS
    )
    return f'<nav class="tabs" aria-label="Sections">{links}</nav>'


def shell(page: Page, title: str, main_html: str) -> str:
    """A whole page: navigation, then `main_html`."""
    where = f"{page.ws[1]} · read only" if page.ws else "read only"
    return (
        '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta name="color-scheme" content="light dark">'
        f"<title>{esc(title)} - AnythingLLM Monitor</title><style>{CSS}</style></head><body>"
        f'<div class="app">{_nav(page)}<div class="col">'
        f'<header class="top"><b>AnythingLLM</b><span>{esc(where)}</span></header>'
        f'<main>{main_html}</main></div><div class="gutter" aria-hidden="true"></div></div>'
        f"{_tabs(page)}</body></html>"
    )
