"""The Overview screen: health at a glance, then a section per screen.

The greeting names the one tailnet login the monitor serves. "More details"
keeps what the plain monitor showed -- services, workspaces, settings with
their values hidden, recent events, MCP server names -- none of it chat text,
prompts or keys. Standard library only.
"""

from __future__ import annotations

import json
import stat
import time
from urllib.parse import urlencode

import review_artifacts
import review_content as content
import review_layout as ui
import review_skills
import review_tasks

UNITS = ("anythingllm.service", "anythingllm-site.service")  # the diot user's units
WORKSPACES_SQL = (
    "select w.name, w.slug, count(c.id), max(c.createdAt) from workspaces w "
    "left join workspace_chats c on c.workspaceId = w.id group by w.id order by w.name"
)
SETTINGS_SQL = "select label, value from system_settings order by label"
EVENTS_SQL = "select event, occurredAt from event_logs order by id desc limit 30"


def greeting(login: str) -> str:
    """'Good morning, name' by the server's local hour."""
    hour = time.localtime().tm_hour
    part = "morning" if 5 <= hour < 12 else "afternoon" if 12 <= hour < 18 else "evening"  # noqa: PLR2004
    return f"Good {part}, {login.split('@', maxsplit=1)[0] or 'there'}"


def hello(prefix: str, login: str, jobs: list[review_tasks.Job]) -> str:
    """The centred header: instance state, task state, refresh link."""
    state = content.service_state("anythingllm.service")
    online = state == "active"
    look = sum(1 for j in jobs if j.runs and not j.runs[0].ok)
    tasks = (
        "All tasks ran as expected"
        if not look
        else f"{look} task{' needs' if look == 1 else 's need'} a look"
    )
    chip = (
        f'<span class="chip"><span class="dot{"" if online else " bad"}"></span>'
        f"Instance {'online' if online else ui.esc(state)}</span>"
    )
    return (
        f'<header class="hello"><h1>{ui.esc(greeting(login))}</h1><div class="status">{chip}'
        f"<span>{ui.esc(tasks)} · checked {time.strftime('%H:%M')}</span>"
        f'<a class="icon-btn" href="{prefix}/" aria-label="Refresh">{ui.icon("refresh")}</a>'
        "</div></header>"
    )


def section(prefix: str, path: str, title: str, aside: str, body: str) -> str:
    """One Overview section: linked heading, a note on the right, the body."""
    return (
        f'<section class="sec"><div class="sechead"><h2><a href="{prefix}/{path}">'
        f'{ui.esc(title)}</a></h2><span class="muted">{aside}</span></div>{body}</section>'
    )


def root_rows(prefix: str) -> str:
    """The top-level folders of the AnythingLLM root, each a link into Files."""
    try:
        names = sorted(p.name for p in content.ROOT.iterdir())
    except OSError:
        return '<div class="row small">The folder cannot be read.</div>'
    rows = []
    for name in names:
        try:
            st = (content.ROOT / name).lstat()
        except OSError:
            continue
        if stat.S_ISDIR(st.st_mode):
            when = time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime))
            rows.append(
                f'<a class="row" href="{prefix}/files?{ui.esc(urlencode({"path": name}))}" '
                'style="text-decoration:none">'
                f'{ui.icon("files", "#B8532F")}<span class="grow" style="font-weight:500">'
                f'{ui.esc(name)}</span><span class="small">{ui.esc(when)}</span></a>'
            )
    return "".join(rows)


def shown_setting(row: tuple) -> tuple:
    """A settings row with its value hidden unless it is on the allowlist."""
    if len(row) > 1 and row[0] not in content.SETTING_VALUES:
        return (row[0], "(not shown)")
    return row


def mcp_rows() -> list[tuple]:
    """MCP server names and autoStart only: the config itself can hold keys."""
    try:
        path = content.ROOT / "storage" / "plugins" / "anythingllm_mcp_servers.json"
        servers = json.loads(path.read_text()).get("mcpServers") or {}
    except (OSError, ValueError, AttributeError):
        return [("no MCP config", "")]
    rows = [(n, (s.get("anythingllm") or {}).get("autoStart", True)) for n, s in servers.items()]
    return rows or [("none", "")]


def details() -> str:
    """The plain monitor's remaining tables, folded away."""
    tables = (
        (
            "Services",
            ["service (diot user)", "state"],
            [(u, content.service_state(u)) for u in UNITS],
        ),
        ("Workspaces", ["name", "slug", "chats", "last chat"], content.rows(WORKSPACES_SQL)),
        ("Settings", ["label", "value"], [shown_setting(r) for r in content.rows(SETTINGS_SQL)]),
        ("Recent events", ["event", "at"], content.rows(EVENTS_SQL)),
        ("MCP servers (config not shown: it can hold keys)", ["name", "autoStart"], mcp_rows()),
    )
    body = "".join(
        f'<h3 style="font-size:15px;margin:16px 0 6px">{ui.esc(title)}</h3>'
        + ui.plain_table(heads, rows or [("none",)])
        for title, heads, rows in tables
    )
    return f'<details class="card pad"><summary>More details</summary>{body}</details>'


def screen(prefix: str, login: str) -> str:
    """The Overview screen."""
    jobs = review_tasks.jobs()
    skills = review_skills.skills()
    pubs = review_artifacts.publications()
    on = sum(1 for s in skills if s.on)
    skill_rows = "".join(review_skills.row(s, prefix) for s in skills[:6])
    task_cards = "".join(review_tasks.card(j) for j in jobs) or (
        '<div class="card pad small">No scheduled tasks.</div>'
    )
    art_cards = "".join(review_artifacts.card(p) for p in pubs[:3]) or (
        '<div class="card pad small">Nothing is published yet.</div>'
    )
    return (
        hello(prefix, login, jobs)
        + section(
            prefix,
            "skills",
            "Skills",
            f"{on} of {len(skills)} on",
            f'<div class="card">{skill_rows}</div>',
        )
        + section(prefix, "tasks", "Scheduled tasks", "", f'<div class="grid2">{task_cards}</div>')
        + section(
            prefix,
            "artifacts",
            "Artifacts",
            f"{len(pubs)} published",
            f'<div class="grid3">{art_cards}</div>'
            '<div class="small">Each card opens the live page in a new tab.</div>',
        )
        + section(prefix, "files", "Files", "", f'<div class="card">{root_rows(prefix)}</div>')
        + details()
        + '<div class="small" style="text-align:center">This page is view only. '
        "Changes happen in AnythingLLM itself.</div>"
    )
