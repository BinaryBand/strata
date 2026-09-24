"""The Skills screen: custom skills from their manifests, built-in skills from settings.

AnythingLLM records no per-skill usage, so "last used" and "calls" count only
the tool calls scheduled tasks made, read from their runs' tool-call lists.
Setup values are never shown: a skill's settings are listed by name only.
Standard library only.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from urllib.parse import urlencode

import review_content as content
import review_layout as ui
import review_tasks

# AnythingLLM 1.16 (utils/agents/defaults.js): on unless listed in disabled_agent_skills.
DEFAULT_ON = ("rag-memory", "document-summarizer", "web-scraping", "web-browsing")
BUILT_IN = {
    "rag-memory": "Remembers and recalls facts from documents",
    "document-summarizer": "Summarises documents",
    "web-scraping": "Reads a web page",
    "web-browsing": "Looks things up on the web",
    "filesystem-agent": "Reads and writes files in its folder",
    "create-scheduled-job": "Creates scheduled tasks from chat",
    "gmail-agent": "Works with Gmail",
}
SKILLS_DIR = "storage/plugins/agent-skills"


@dataclass
class Skill:
    """One skill as shown."""

    id: str
    name: str
    description: str
    custom: bool
    on: bool
    version: str = ""
    entry: str = ""
    settings: list[str] = field(default_factory=list)
    calls: int = 0
    last_used: object = None
    used_by: list[str] = field(default_factory=list)


def setting_list(label: str) -> list[str]:
    """A JSON list stored in AnythingLLM's system settings."""
    found = content.rows("select value from system_settings where label = ?", (label,))
    try:
        value = json.loads(found[0][0]) if found else []
    except (TypeError, ValueError):
        return []
    return [str(v) for v in value] if isinstance(value, list) else []


def custom_skills() -> list[Skill]:
    """Every custom skill folder with a readable plugin.json."""
    try:
        entries = sorted(os.scandir(content.ROOT / SKILLS_DIR), key=lambda e: e.name)
    except OSError:
        return []
    found = []
    for entry in entries:
        if not entry.is_dir(follow_symlinks=False):
            continue
        manifest = content.read_json(f"{SKILLS_DIR}/{entry.name}/plugin.json")
        if not isinstance(manifest, dict):
            continue
        point = manifest.get("entrypoint")
        point = point if isinstance(point, dict) else {}
        setup = manifest.get("setup_args")
        setup = setup if isinstance(setup, dict) else {}
        found.append(
            Skill(
                id=str(manifest.get("hubId") or entry.name),
                name=str(manifest.get("name") or entry.name),
                description=str(manifest.get("description") or ""),
                custom=True,
                on=manifest.get("active") is True,
                version=str(manifest.get("version") or ""),
                entry=f"{SKILLS_DIR}/{entry.name}/{point.get('file') or 'handler.js'}",
                settings=sorted(str(k) for k in setup),
            )
        )
    return found


def built_in_skills() -> list[Skill]:
    """The default built-ins with their state, then every other built-in switched on."""
    disabled = setting_list("disabled_agent_skills")
    enabled = setting_list("default_agent_skills")
    ids = list(DEFAULT_ON) + [s for s in enabled if s not in DEFAULT_ON]
    return [
        Skill(
            id=s,
            name=s,
            description=BUILT_IN.get(s, ""),
            custom=False,
            on=(s not in disabled) if s in DEFAULT_ON else True,
        )
        for s in ids
    ]


def owner_of(tool: str, skills: list[Skill]) -> Skill | None:
    """The skill a tool call belongs to: its own name, or a built-in's family prefix."""
    for skill in skills:
        stem = skill.id.removesuffix("-agent")
        if tool == skill.id or tool.startswith(f"{stem}-"):
            return skill
    return None


def skills() -> list[Skill]:
    """All skills, with task usage over the last seven days."""
    found = custom_skills() + built_in_skills()
    since = review_tasks.week_ago_ms()
    for job in review_tasks.jobs():
        for skill in found:
            if skill.id in job.skills:
                skill.used_by.append(job.name)
        for run in job.runs:
            for tool in run.tools:
                skill = owner_of(tool, found)
                if skill is None:
                    continue
                started = review_tasks.millis(run.started)
                skill.calls += 1 if started >= since else 0
                if started > review_tasks.millis(skill.last_used):
                    skill.last_used = run.started
    return found


def row(skill: Skill, prefix: str) -> str:
    """A skill's row for the Overview."""
    tile = "tile custom" if skill.custom else "tile"
    return (
        f'<div class="row"><span class="{tile}">{ui.icon("skills")}</span>'
        f'<div class="grow"><span style="font-weight:500">'
        f'<a href="{prefix}/skills#skill-{ui.esc(skill.id)}" style="text-decoration:none">'
        f"{ui.esc(skill.name)}</a></span>"
        f'<span class="muted">{ui.esc(skill.description)}</span></div>'
        f"{ui.pill('Custom' if skill.custom else 'Built-in')}{ui.switch(skill.on)}</div>"
    )


def detail(skill: Skill, prefix: str) -> str:
    """A custom skill's panel: version, entry file, tasks using it, setting names."""
    entry = ui.esc(skill.entry)
    if content.viewable(skill.entry):
        entry = f'<a href="{prefix}/file?{ui.esc(urlencode({"path": skill.entry}))}">{entry}</a>'
    used = ", ".join(ui.esc(n) for n in skill.used_by) or "No scheduled task"
    settings = "".join(ui.kv(name, "hidden") for name in skill.settings) or (
        '<div class="small">No settings.</div>'
    )
    return (
        f'<section class="card pad grid2" id="skill-{ui.esc(skill.id)}" style="gap:32px">'
        '<div class="stack" style="gap:8px">'
        '<div class="sechead" style="justify-content:flex-start">'
        f'<h2 style="font-size:22px">{ui.esc(skill.name)}</h2>{ui.pill("Custom")}</div>'
        f'<div class="lede" style="font-size:14px">{ui.esc(skill.description)}</div><div>'
        + ui.kv("Version", ui.esc(skill.version or "--"))
        + ui.kv("Status", "On" if skill.on else "Off")
        + ui.kv("Entry file", f'<span class="mono">{entry}</span>')
        + ui.kv("Used by", f'<a href="{prefix}/tasks">{used}</a>' if skill.used_by else used)
        + '</div></div><div class="stack">'
        '<div style="font-weight:500;font-size:14px">Settings</div>'
        '<div class="small">Names only: every value set in AnythingLLM stays hidden.</div>'
        f"{settings}</div></section>"
    )


def screen(prefix: str) -> str:
    """The Skills screen."""
    found = skills()
    on = sum(1 for s in found if s.on)
    table = ui.grid_table(
        "1fr 100px 150px 130px 60px",
        ["Skill", "Source", "Last used by a task", "Task calls (7 days)", "Status"],
        [
            [
                f'<span class="stack" style="gap:2px"><strong style="font-weight:500">'
                f"{ui.esc(s.name)}</strong>"
                f'<span class="small">{ui.esc(s.description)}</span></span>',
                ui.pill("Custom" if s.custom else "Built-in"),
                ui.esc(content.when(s.last_used) if s.last_used else "--"),
                ui.esc(s.calls),
                ui.switch(s.on),
            ]
            for s in found
        ],
    )
    return (
        ui.header(
            prefix,
            "Skills",
            "Every skill installed on the instance, and how often scheduled tasks use it.",
            f'<span class="muted">{on} of {len(found)} on</span>',
        )
        + table
        + "".join(detail(s, prefix) for s in found if s.custom)
    )
