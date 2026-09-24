"""The key check: does any stored credential appear anywhere the agent can read?

The credentials are the settings file's secret values, custom skills' setup
values and the MCP config's env and header values. The places searched are
everything in the agent's reach: its file folder, research runs, and the
database text it is given or wrote -- chats, prompts, job prompts and run
output, memories, prompt variables and presets. A finding names the setting and
where it appeared, never the value, and no value is kept beyond one check. The
work is bounded: at most MAX_FILES files and MAX_BYTES read per check.
Standard library only.
"""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path

import review_content as content

MIN_LENGTH = 12  # shorter values match ordinary text by chance
MAX_FILES = 20_000
MAX_BYTES = 64 * 1024 * 1024
MAX_FILE = 4 * 1024 * 1024
SEARCHED = ("storage/anythingllm-fs", "storage/research-runs")
DB_TEXT = (
    ("workspace_chats", "id", ("prompt", "response"), "chat"),
    ("scheduled_jobs", "id", ("prompt",), "scheduled task"),
    ("scheduled_job_runs", "id", ("result",), "task run"),
    ("workspaces", "slug", ("openAiPrompt",), "workspace prompt"),
    ("memories", "id", ("content",), "memory"),
    ("system_prompt_variables", "key", ("value",), "prompt variable"),
    ("slash_command_presets", "command", ("prompt",), "slash-command preset"),
    ("workspace_agent_invocations", "id", ("prompt",), "agent message"),
)


@dataclass
class Finding:
    """One place a credential turned up."""

    setting: str
    where: str
    line: int = 0
    path: str = ""  # a file under ROOT, for a link to the viewer


def credentials() -> list[tuple[str, bytes]]:
    """(setting name, value) for every stored credential long enough to search for."""
    found = [(k, v) for k, v in content.env().items() if content.is_secret(k)]
    found += _skill_settings() + _mcp_settings()
    return [(n, v.encode()) for n, v in found if len(v) >= MIN_LENGTH]


def _skill_settings() -> list[tuple[str, str]]:
    """Every custom skill's setup values."""
    found = []
    skills = content.ROOT / "storage" / "plugins" / "agent-skills"
    try:
        names = sorted(e.name for e in os.scandir(skills) if e.is_dir(follow_symlinks=False))
    except OSError:
        names = []
    for name in names:
        manifest = content.as_dict(
            content.read_json(f"storage/plugins/agent-skills/{name}/plugin.json")
        )
        for key, arg in content.as_dict(manifest.get("setup_args")).items():
            value = content.as_dict(arg).get("value")
            if isinstance(value, str):
                found.append((f"{name} setting {key}", value))
    return found


def _mcp_settings() -> list[tuple[str, str]]:
    """Every MCP server's env and header values."""
    found = []
    mcp = content.read_json("storage/plugins/anythingllm_mcp_servers.json")
    servers = mcp.get("mcpServers") if isinstance(mcp, dict) else None
    for server, conf in (servers if isinstance(servers, dict) else {}).items():
        for part in ("env", "headers"):
            values = conf.get(part) if isinstance(conf, dict) else None
            for key, value in (values if isinstance(values, dict) else {}).items():
                if isinstance(value, str):
                    found.append((f"MCP {server} {part} {key}", value))
    return found


def _files() -> list[str]:
    """Regular files under the searched folders, as paths under ROOT, links never followed."""
    found = []
    for top in SEARCHED:
        for dirpath, dirnames, filenames in os.walk(content.ROOT / top, followlinks=False):
            dirnames.sort()
            rel = os.path.relpath(dirpath, content.ROOT)
            for name in sorted(filenames):
                if len(found) >= MAX_FILES:
                    return found
                try:
                    mode = (Path(dirpath) / name).lstat().st_mode
                except OSError:
                    continue
                if stat.S_ISREG(mode):
                    found.append(f"{rel}/{name}")
    return found


def _search(
    secrets: list[tuple[str, bytes]], data: bytes, where: str, path: str = ""
) -> list[Finding]:
    """Every credential that occurs in data."""
    hits = []
    for name, value in secrets:
        at = data.find(value)
        if at >= 0:
            hits.append(Finding(name, where, data.count(b"\n", 0, at) + 1 if path else 0, path))
    return hits


def check() -> list[Finding]:
    """Where stored credentials appear in the agent's reach; [] when nowhere."""
    secrets = credentials()
    if not secrets:
        return []
    findings: list[Finding] = []
    budget = MAX_BYTES
    for rel in _files():
        if budget <= 0:
            break
        try:
            data, _ = content.read_bytes(rel, MAX_FILE)
        except content.ViewError:
            continue
        budget -= len(data)
        shown = rel.removeprefix("storage/anythingllm-fs/").removeprefix("storage/")
        findings += _search(secrets, data, shown, rel)
    for table, key, columns, label in DB_TEXT:
        for row in content.rows(f"select {key}, {', '.join(columns)} from {table}"):  # noqa: S608 -- fixed names
            data = "\n".join(str(v) for v in row[1:] if v is not None).encode()
            findings += _search(secrets, data, f"{label} {row[0]}")
    return findings
