"""The /review monitor's page shell and shared pieces, after the Claude Design mock-up.

A left sidebar with one entry per screen, cards, pills, on/off switches and
key-value rows, all plain HTML and CSS: the monitor's Content-Security-Policy
allows no scripts and no outside requests, so fonts fall back to the system's.
Every value passed in is escaped here unless a caller marks it as markup it
built itself. Standard library only.
"""

from __future__ import annotations

import html
import re

CONTROL = re.compile(r"[\x00-\x1f\x7f]")
SERIF = "Georgia,'Times New Roman',serif"
MONO = "ui-monospace,'SF Mono',Menlo,Consolas,monospace"
CSS = (
    ":root{--bg:#FAF9F5;--side:#F0EEE6;--line:#E3E0D6;--soft:#F0EEE6;--card:#FFFFFF;"
    "--ink:#141413;--ink2:#3D3D3A;--muted:#5E5D59;--accent:#B8532F;--on:#D97757;--off:#D1CEC4;"
    "--okbg:#E7EEE6;--ok:#2E5A36;--okbar:#7FA487;--warnbg:#F5E6DF;--warn:#9A4424;--active:#E6E3D9}"
    "@media (prefers-color-scheme:dark){:root{--bg:#1C1B19;--side:#23221F;--line:#3A3833;"
    "--soft:#2B2A26;--card:#262521;--ink:#F2F0EA;--ink2:#D6D3CA;--muted:#A6A298;--accent:#E0896F;"
    "--off:#55524B;--okbg:#26362A;--ok:#A9CFAF;--warnbg:#3D2A22;--warn:#F0B29B;--active:#33312C}}"
    "*{box-sizing:border-box}"
    "body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 system-ui,'Segoe UI',"
    "Roboto,Helvetica,Arial,sans-serif}"
    "a{color:var(--ink)}a:hover{color:var(--accent)}"
    ".app{display:flex;min-height:100vh}"
    ".side{width:260px;flex-shrink:0;background:var(--side);border-right:1px solid var(--line);"
    "padding:20px 12px;display:flex;flex-direction:column;gap:4px}"
    f".brand{{padding:8px 12px 20px;font-family:{SERIF};font-size:20px;font-weight:500}}"
    ".nav{display:flex;align-items:center;gap:12px;min-height:44px;padding:0 12px;"
    "border-radius:10px;text-decoration:none;font-size:15px;color:var(--ink2)}"
    ".nav.on{background:var(--active);color:var(--ink);font-weight:500}"
    ".who{margin-top:auto;display:flex;align-items:center;gap:12px;padding:12px;"
    "border-top:1px solid var(--line)}"
    ".avatar{width:32px;height:32px;border-radius:999px;background:var(--ink);color:var(--bg);"
    "display:flex;align-items:center;justify-content:center;font-size:13px;font-weight:500}"
    ".who div span{display:block}.who small{color:var(--muted);font-size:12px}"
    "main{flex-grow:1;min-width:0;max-width:1080px;padding:48px 56px;display:flex;"
    "flex-direction:column;gap:28px}"
    ".head{display:flex;justify-content:space-between;align-items:flex-end;gap:24px}"
    ".crumb{font-size:14px;color:var(--muted)}.crumb a{color:var(--muted)}"
    f"h1{{margin:0;font-family:{SERIF};font-weight:400;font-size:36px;line-height:1.2}}"
    f"h2{{margin:0;font-family:{SERIF};font-weight:500;font-size:24px}}"
    "h2 a{text-decoration:none}"
    ".lede{font-size:15px;color:var(--ink2)}.muted{color:var(--muted);font-size:14px}"
    ".small{font-size:13px;color:var(--muted)}"
    ".hello{display:flex;flex-direction:column;align-items:center;gap:14px;text-align:center;"
    "padding:12px 0 4px}.hello h1{font-size:38px}"
    ".status{display:flex;flex-wrap:wrap;justify-content:center;align-items:center;gap:10px;"
    "font-size:15px;color:var(--ink2)}"
    ".chip{display:inline-flex;align-items:center;gap:8px;padding:6px 12px;border-radius:999px;"
    "background:var(--card);border:1px solid var(--line)}"
    ".dot{width:8px;height:8px;border-radius:999px;background:#3D7A48}.dot.bad{background:var(--on)}"
    ".icon-btn{width:44px;height:44px;border-radius:10px;display:inline-flex;align-items:center;"
    "justify-content:center;color:var(--ink2)}"
    ".sec{display:flex;flex-direction:column;gap:12px}"
    ".sechead{display:flex;justify-content:space-between;align-items:baseline;gap:16px}"
    ".card{background:var(--card);border:1px solid var(--line);border-radius:16px}"
    ".pad{padding:20px}.stack{display:flex;flex-direction:column;gap:12px}"
    ".row{display:flex;align-items:center;gap:16px;padding:16px 20px;"
    "border-bottom:1px solid var(--soft)}.row:last-child{border-bottom:0}"
    ".row .grow{flex-grow:1;display:flex;flex-direction:column;gap:2px;min-width:0}"
    ".tile{width:36px;height:36px;border-radius:10px;background:var(--soft);color:var(--ink2);"
    "display:flex;align-items:center;justify-content:center;flex-shrink:0}"
    ".tile.custom{background:var(--warnbg);color:var(--accent)}"
    ".pill{font-size:12px;color:var(--muted);padding:3px 8px;border-radius:6px;"
    "background:var(--soft);white-space:nowrap}"
    ".pill.ok{background:var(--okbg);color:var(--ok)}.pill.warn{background:var(--warnbg);"
    "color:var(--warn)}"
    ".switch{width:36px;height:20px;border-radius:999px;background:var(--off);display:flex;"
    "align-items:center;padding:2px;flex-shrink:0}"
    ".switch.on{background:var(--on);justify-content:flex-end}"
    ".switch span{width:16px;height:16px;border-radius:999px;background:#fff}"
    ".grid2{display:grid;grid-template-columns:1fr 1fr;gap:16px}"
    ".grid3{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}"
    ".grid4{display:grid;grid-template-columns:repeat(4,1fr);gap:16px}"
    ".strip{display:flex;gap:4px;align-items:center}"
    ".strip i{width:10px;height:18px;border-radius:3px;background:var(--okbar)}"
    ".strip i.warn{background:var(--on)}"
    ".tbl{display:grid;gap:0}.tr{display:grid;gap:12px;align-items:center;min-height:48px;"
    "padding:8px 20px;border-bottom:1px solid var(--soft);font-size:14px}"
    ".tbl a{text-decoration:none}.tbl a:hover{text-decoration:underline}"
    ".tr svg{vertical-align:-3px;margin-right:6px}"
    ".tr:last-child{border-bottom:0}.th{min-height:0;padding:12px 20px;font-size:13px;"
    "color:var(--muted);border-bottom:1px solid var(--line)}"
    ".kv{display:flex;justify-content:space-between;gap:16px;padding:10px 0;"
    "border-bottom:1px solid var(--soft);font-size:14px}"
    ".kv span:first-child{color:var(--muted);white-space:nowrap}"
    ".kv span:last-child{text-align:right;overflow-wrap:anywhere}"
    f".mono{{font-family:{MONO};font-size:13px}}"
    ".stat{background:var(--bg);border-radius:12px;padding:14px 16px;display:flex;"
    f"flex-direction:column;gap:4px}}.stat b{{font-family:{SERIF};font-size:22px;font-weight:400}}"
    ".preview{background:var(--soft);display:flex;align-items:center;justify-content:center;"
    "color:var(--muted);font-size:13px;border-radius:10px}"
    ".art{display:flex;gap:20px;padding:16px;align-items:center}"
    ".art .preview{width:200px;height:120px;flex-shrink:0}"
    ".btn{display:inline-flex;align-items:center;min-height:44px;padding:0 16px;"
    "border:1px solid var(--line);border-radius:10px;text-decoration:none;font-size:14px;"
    "flex-shrink:0}"
    "details{font-size:14px;color:var(--ink2)}summary{cursor:pointer;min-height:28px}"
    f".log{{font-family:{MONO};font-size:13px;background:var(--soft);border-radius:8px;"
    "padding:12px;margin-top:6px;white-space:pre-wrap;overflow-x:auto}"
    ".folders{padding:10px;display:flex;flex-direction:column;gap:2px;align-self:start}"
    ".folders a{display:flex;align-items:center;min-height:40px;padding:0 10px;border-radius:8px;"
    "text-decoration:none;font-size:14px}.folders a.on{background:var(--soft);font-weight:500}"
    ".files{display:grid;grid-template-columns:220px 1fr;gap:20px}"
    ".agent{border-left:4px solid #b8860b;padding:.5rem 1rem;background:var(--warnbg);"
    "border-radius:0 8px 8px 0}"
    "pre{margin:0;white-space:pre-wrap;overflow-x:auto}"
    "table.plain{border-collapse:collapse;width:100%;font-size:13px}"
    "table.plain td,table.plain th{border-bottom:1px solid var(--soft);padding:.4rem .75rem;"
    "text-align:left;vertical-align:top}table.plain th{color:var(--muted);font-weight:500}"
    "@media (max-width:900px){.app{flex-direction:column}.side{width:auto;flex-direction:row;"
    "flex-wrap:wrap;padding:8px}.brand,.who{display:none}main{padding:24px 16px}"
    ".grid2,.grid3,.files{grid-template-columns:1fr}.grid4{grid-template-columns:1fr 1fr}"
    ".tr{grid-template-columns:1fr!important}"
    ".th{display:none}.art{flex-direction:column;align-items:stretch}.art .preview{width:auto}}"
)
ICONS = {
    "overview": '<path d="M3 11l9-7 9 7"/><path d="M5 10v10h14V10"/>',
    "skills": (
        '<path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4'
        'l-2.5 2.5-2.5-.5-.5-2.5z"/>'
    ),
    "tasks": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "artifacts": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 9h18"/>',
    "files": (
        '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>'
    ),
    "file": '<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/>'
    '<path d="M14 3v6h6"/>',
    "refresh": '<path d="M21 12a9 9 0 1 1-3-6.7L21 8"/><path d="M21 3v5h-5"/>',
    "globe": (
        '<circle cx="12" cy="12" r="9"/>'
        '<path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/>'
    ),
}
SCREENS = (
    ("overview", "Overview", ""),
    ("skills", "Skills", "skills"),
    ("tasks", "Scheduled tasks", "tasks"),
    ("artifacts", "Artifacts", "artifacts"),
    ("files", "Files", "files"),
)


def esc(text: object) -> str:
    """HTML-escaped text with control characters shown as '?'."""
    return html.escape(CONTROL.sub("?", "" if text is None else str(text)))


def icon(name: str, stroke: str = "currentColor") -> str:
    """One of the design's line icons, 18 px."""
    return (
        f'<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="{stroke}" '
        'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
        f"{ICONS[name]}</svg>"
    )


def pill(text: str, kind: str = "") -> str:
    """A small label: kind '' (neutral), 'ok' or 'warn'."""
    return f'<span class="pill {kind}">{esc(text)}</span>'


def switch(on: bool) -> str:  # noqa: FBT001 -- mirrors the state it shows
    """A read-only on/off switch."""
    state = "On" if on else "Off"
    kind = "switch on" if on else "switch"
    return f'<span role="img" aria-label="{state}" class="{kind}"><span></span></span>'


def kv(label: str, value_html: str) -> str:
    """A key-value row; the value is markup the caller built and escaped."""
    return f'<div class="kv"><span>{esc(label)}</span><span>{value_html}</span></div>'


def grid_table(
    columns: str, headings: list[str], rows: list[list[str]], *, framed: bool = True
) -> str:
    """A table laid out on a CSS grid, in its own card when framed; cells are escaped markup."""
    style = f'style="grid-template-columns:{columns}"'
    head = f'<div class="tr th" {style}>' + "".join(f"<span>{esc(h)}</span>" for h in headings)
    body = "".join(
        f'<div class="tr" {style}>' + "".join(f"<span>{c}</span>" for c in row) + "</div>"
        for row in rows
    )
    tag = 'section class="card tbl"' if framed else 'div class="tbl"'
    return f"<{tag}>{head}</div>{body}</{tag.split(maxsplit=1)[0]}>"


def plain_table(headings: list[str], rows: list[tuple]) -> str:
    """A simple table with every cell escaped, for the detail sections."""
    head = "".join(f"<th>{esc(h)}</th>" for h in headings)
    body = "".join("<tr>" + "".join(f"<td>{esc(v)}</td>" for v in row) + "</tr>" for row in rows)
    return f'<table class="plain"><tr>{head}</tr>{body}</table>'


def header(prefix: str, title: str, lede: str, aside_html: str = "") -> str:
    """A screen's breadcrumb, title and one-line description."""
    return (
        '<header class="head"><div class="stack" style="gap:6px">'
        f'<div class="crumb"><a href="{prefix}/">Overview</a> '
        '<span aria-hidden="true">&rsaquo;</span> '
        f'{esc(title)}</div><h1>{esc(title)}</h1><div class="lede">{esc(lede)}</div></div>'
        f"{aside_html}</header>"
    )


def shell(prefix: str, active: str, title: str, login: str, main_html: str) -> str:
    """A whole page: sidebar with `active` highlighted, then `main_html`."""
    nav = "".join(
        f'<a class="nav{" on" if key == active else ""}" href="{prefix}/{path}">'
        f"{icon(key)}{esc(label)}</a>"
        for key, label, path in SCREENS
    )
    name = login.split("@", maxsplit=1)[0] or "Admin"
    return (
        '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta name="color-scheme" content="light dark">'
        f"<title>{esc(title)} - AnythingLLM Monitor</title><style>{CSS}</style></head><body>"
        '<div class="app"><nav class="side" aria-label="Sections">'
        '<div class="brand">AnythingLLM</div>'
        f'{nav}<div class="who"><span class="avatar">{esc(name[:1].upper())}</span>'
        f"<div><span>{esc(name)}</span><small>View only</small></div></div></nav>"
        f"<main>{main_html}</main></div></body></html>"
    )
