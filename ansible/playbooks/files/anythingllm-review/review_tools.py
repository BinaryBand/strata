"""The Tools screen: everything the agent can call, with the parameters the model sees.

Built-in tools' descriptions and parameters come from review_builtins.json,
read out of the AnythingLLM image this runs against; which are on follows the
same settings AnythingLLM reads (utils/agents/defaults.js). A custom skill's
parameters are its manifest's `entrypoint.params`, sent with no required list.
An Agent Flow is offered as one tool whose parameters are its start block's
non-static variables. An MCP server's tools are known only to the running
server, so its config is shown instead. Setup values and MCP env and header
values are never shown. Standard library only.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

import review_content as content
import review_layout as ui

BUILTINS_FILE = Path(__file__).with_name("review_builtins.json")
SKILLS_DIR = "storage/plugins/agent-skills"
FLOWS_DIR = "storage/plugins/agent-flows"
# AnythingLLM 1.16: on unless listed in disabled_agent_skills.
DEFAULT_ON = ("rag-memory", "document-summarizer", "web-scraping", "web-browsing")
# Families whose sub-tools can be switched off one by one, and the setting that lists them.
SUB_SETTINGS = {
    "filesystem-agent": "disabled_filesystem_skills",
    "create-files-agent": "disabled_create_files_skills",
    "gmail-agent": "disabled_gmail_skills",
    "outlook-agent": "disabled_outlook_skills",
}
LABELS = {
    "filesystem-agent": "File System Access",
    "web-scraping": "Web Scraping",
    "web-browsing": "Web Browsing",
    "rag-memory": "Memory",
    "document-summarizer": "Document summarizer",
    "create-scheduled-job": "Create scheduled task",
    "create-files-agent": "Create files",
    "sql-agent": "SQL connections",
    "create-chart": "Charts",
    "generate-image": "Image generation",
    "gmail-agent": "Gmail",
    "outlook-agent": "Outlook",
    "google-calendar-agent": "Google Calendar",
}


@dataclass
class Tool:
    """One function the model can call."""

    name: str
    description: str
    params: list[dict] = field(default_factory=list)


@dataclass
class Skill:
    """A skill as the Tools screen lists it: one or more tools and a state."""

    id: str
    name: str
    source: str  # "Custom", "Built-in" or "Draft from strata-workshop"
    on: bool
    description: str = ""
    tools: list[Tool] = field(default_factory=list)
    settings: list[str] = field(default_factory=list)


def builtin_tools() -> dict[str, list[Tool]]:
    """Built-in tools by skill family, from the data file."""
    try:
        data = json.loads(BUILTINS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    families: dict[str, list[Tool]] = {}
    for name, tool in (data.get("tools") or {}).items():
        families.setdefault(tool["skill"], []).append(
            Tool(name, tool.get("description", ""), tool.get("params") or [])
        )
    return families


def built_in_skills() -> list[Skill]:
    """Every built-in skill with its state; switched-off sub-tools are left out."""
    disabled = content.setting_list("disabled_agent_skills")
    enabled = content.setting_list("default_agent_skills")
    found = []
    for family, tools in builtin_tools().items():
        on = family not in disabled if family in DEFAULT_ON else family in enabled
        off_subs = (
            set(content.setting_list(SUB_SETTINGS[family])) if family in SUB_SETTINGS else set()
        )
        kept = [t for t in tools if t.name not in off_subs]
        description = tools[0].description if len(tools) == 1 else f"{len(kept)} tools"
        found.append(Skill(family, LABELS.get(family, family), "Built-in", on, description, kept))
    return found


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
        raw = content.as_dict(content.as_dict(manifest.get("entrypoint")).get("params"))
        params = [
            {
                "name": k,
                "type": str(v.get("type", "")) if isinstance(v, dict) else "",
                "required": False,
                "description": str(v.get("description", "")) if isinstance(v, dict) else "",
            }
            for k, v in raw.items()
        ]
        hub = str(manifest.get("hubId") or entry.name)
        description = str(manifest.get("description") or "")
        # strata-workshop marks a draft whose code is still held back.
        mark = manifest.get("strataWorkshop")
        draft = isinstance(mark, dict) and bool(mark.get("pending"))
        setup = content.as_dict(manifest.get("setup_args"))
        found.append(
            Skill(
                hub,
                str(manifest.get("name") or entry.name),
                "Draft from strata-workshop" if draft else "Custom",
                manifest.get("active") is True,
                description,
                [Tool(hub, description, params)],
                sorted(str(k) for k in setup),
            )
        )
    return found


def skills() -> list[Skill]:
    """Custom skills first, then built-ins."""
    return custom_skills() + built_in_skills()


def flows() -> list[tuple[str, bool, Tool]]:
    """(flow name, on, the tool it is offered as) for every Agent Flow."""
    try:
        names = sorted(os.listdir(content.ROOT / FLOWS_DIR))  # noqa: PTH208
    except OSError:
        return []
    found = []
    for name in names:
        flow = content.read_json(f"{FLOWS_DIR}/{name}") if name.endswith(".json") else None
        if not isinstance(flow, dict):
            continue
        config = content.as_dict(flow.get("config"))
        steps = [content.as_dict(s) for s in content.as_list(config.get("steps"))]
        start = next((s for s in steps if s.get("type") == "start"), {})
        variables = content.as_list(content.as_dict(start.get("config")).get("variables"))
        params = [
            {
                "name": str(v.get("name")),
                "type": "string",
                "required": v.get("type") == "required",
                "description": str(v.get("description") or f"Value for variable {v.get('name')}"),
            }
            for v in variables
            if isinstance(v, dict) and v.get("name") and (v.get("type") or "optional") != "static"
        ]
        title = str(flow.get("name") or name)
        about = str(
            config.get("description") or flow.get("description") or f"Execute agent flow: {title}"
        )
        found.append((title, flow.get("active") is not False, Tool(title, about, params)))
    return found


def mcp_servers() -> list[tuple[str, bool]]:
    """(name, starts at boot) for every configured MCP server."""
    config = content.read_json("storage/plugins/anythingllm_mcp_servers.json")
    servers = config.get("mcpServers") if isinstance(config, dict) else None
    if not isinstance(servers, dict):
        return []
    return [
        (
            str(n),
            content.as_dict(content.as_dict(s).get("anythingllm")).get("autoStart") is not False,
        )
        for n, s in servers.items()
    ]


def params_markup(params: list[dict]) -> str:
    """A tool's parameters as the model sees them."""
    return (
        "".join(
            f'<div class="param">{ui.mono(p.get("name"))}'
            f"<small>{ui.esc(p.get('type') or 'any')}</small>"
            + (ui.pill("required", "accent") if p.get("required") else "")
            + f"<span>{ui.esc(p.get('description'))}</span></div>"
            for p in params
        )
        or '<span class="muted">No parameters.</span>'
    )


def skill_card(skill: Skill) -> str:
    """A skill: state, what it does, and each tool's parameters."""
    aside = ui.pill(skill.source) + ui.switch(skill.on)
    if len(skill.tools) == 1:
        inner = params_markup(skill.tools[0].params)
    else:
        inner = "".join(
            f"<details><summary>{ui.mono(t.name)}</summary>"
            f'<span class="muted">{ui.esc(t.description)}</span>{params_markup(t.params)}</details>'
            for t in skill.tools
        )
    off = (
        ""
        if skill.on
        else '<span class="muted">Off: the agent can&rsquo;t call it until it is switched on.'
        "</span>"
    )
    return (
        '<section class="card">'
        + ui.bar(f"<h3>{ui.mono(skill.name)}</h3>", aside)
        + f'<span class="lede" style="font-size:14px">{ui.esc(skill.description)}</span>'
        + off
        + f"<div>{inner}</div></section>"
    )


def screen(prefix: str) -> str:  # noqa: ARG001 -- every screen takes the prefix
    """The Tools screen."""
    found = skills()
    shown = [s for s in found if s.on or s.source != "Built-in"]
    off = [s.name for s in found if not s.on and s.source == "Built-in"]
    on = sum(1 for s in shown if s.on)
    settings = content.env()
    mcp = [
        '<section class="card">'
        + ui.bar(
            f"<h3>{ui.mono(name)}</h3>",
            ui.pill("Starts at boot" if boot else "Starts only when switched on"),
        )
        + '<span class="muted">Its tools are listed by the running server; the monitor '
        "cannot ask it. The agent can&rsquo;t call them while it is stopped.</span></section>"
        for name, boot in mcp_servers()
    ]
    flow_cards = [
        '<section class="card">'
        + ui.bar(f"<h3>{ui.mono(title)}</h3>", ui.pill("Agent Flow") + ui.switch(active))
        + f'<span class="lede" style="font-size:14px">{ui.esc(tool.description)}</span>'
        + f"<div>{params_markup(tool.params)}</div></section>"
        for title, active, tool in flows()
    ]
    web = {s.id: s.on for s in found}
    web_card = ui.card(
        "Web",
        "<div>"
        + ui.kv("Web Browsing", ui.switch(web.get("web-browsing", False)))
        + ui.kv("Search provider", ui.esc(content.setting("agent_search_provider") or "not set"))
        + ui.kv("Web Scraping", ui.switch(web.get("web-scraping", False)))
        + "</div>"
        + (
            ""
            if web.get("web-browsing")
            else '<span class="muted">While Web Browsing is off, the agent can&rsquo;t '
            "search the web.</span>"
        ),
    )
    admin_rows = [
        ui.kv(
            k,
            "&bull;&bull;&bull;&bull;&bull;&bull;&bull;&bull; set"
            if content.is_secret(k)
            else ui.mono(v),
        )
        for k, v in sorted(settings.items())
        if k.startswith(("LLM_", "AGENT_", "DEEPSEEK_", "EMBEDDING_", "VECTOR_"))
        or content.is_secret(k)
    ]
    admin_rows.append(
        ui.kv("MCP config file", ui.mono("storage/plugins/anythingllm_mcp_servers.json"))
    )
    admin_rows += [
        ui.kv(f"{s.name} settings", ui.esc(", ".join(s.settings) + " (values hidden)"))
        for s in found
        if s.settings
    ]
    return (
        ui.header("Tools", "Everything the agent can call, with the parameters the model sees.")
        + ui.section(
            "Skills", "".join(skill_card(s) for s in shown), ui.esc(f"{len(shown)} · {on} on")
        )
        + (
            f'<span class="muted">Built-in and switched off: {ui.esc(", ".join(off))}.</span>'
            if off
            else ""
        )
        + ui.section("MCP servers", "".join(mcp) or '<div class="muted">None configured.</div>')
        + ui.section("Agent flows", "".join(flow_cards) or '<div class="muted">None.</div>')
        + web_card
        + ui.admin(f'<section class="card"><div>{"".join(admin_rows)}</div></section>')
    )
