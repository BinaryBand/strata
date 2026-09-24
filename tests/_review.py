"""A fake AnythingLLM data folder for the /review monitor's tests.

It holds what the agent can see -- a workspace prompt, chats, a job prompt,
runs with tool calls (one leaked as DSML text), agent files, a document, a
memory -- and credentials planted where only the server keeps them: the
settings file, a signing key, a skill's setup value and an MCP server's env.
"""

from __future__ import annotations

import importlib
import json
import sqlite3
import sys
from pathlib import Path

MONITOR = (
    Path(__file__).resolve().parents[1] / "ansible" / "playbooks" / "files" / "anythingllm-review"
)
MODULES = (
    "review",
    "review_artifacts",
    "review_content",
    "review_files",
    "review_knowledge",
    "review_layout",
    "review_overview",
    "review_run",
    "review_secrets",
    "review_story",
    "review_style",
    "review_tasks",
    "review_thread",
    "review_tools",
    "review_viewer",
    "review_workspace",
)
SECRET = "sk-planted-secret-0123456789"
SKILL_SECRET = "skill-setup-value-0123456789"
MCP_SECRET = "mcp-env-value-0123456789abc"
SECRETS = (SECRET, SKILL_SECRET, MCP_SECRET)
LOGIN = "admin@github"
SITE = "https://host.example.ts.net:8443"
DAY_MS = 1790238746913
PROMPT = "You are the <Workshop> agent."
JOB_PROMPT = "Use news-wire and write TOML stories."
CHAT = "What does FORMAT.md say about slugs?"
REPLY = "Slugs are lowercase words."
OUTPUT = "Fetched 38 items from 7 feeds."


def load(monkeypatch, root: Path):
    """The server module, fresh, pointed at root."""
    monkeypatch.syspath_prepend(str(MONITOR))
    for name in MODULES:
        sys.modules.pop(name, None)
    content = importlib.import_module("review_content")
    review = importlib.import_module("review")
    monkeypatch.setattr(content, "ROOT", root)
    monkeypatch.setattr(content, "PREFIX", "")
    monkeypatch.setattr(content, "SITE_URL", SITE)
    monkeypatch.setattr(review, "LOGIN", LOGIN)
    monkeypatch.setattr(content, "service_state", lambda *_, **__: "active")
    return review


def run_result(calls: list[tuple[str, dict]], text: str) -> str:
    """A scheduled_job_runs.result value as AnythingLLM stores it."""
    return json.dumps(
        {
            "text": text,
            "toolCalls": [
                {"toolName": t, "arguments": a, "result": OUTPUT, "timestamp": 1} for t, a in calls
            ],
            "thoughts": ["Checking the feeds first."],
            "outputs": [],
        }
    )


def files(tmp: Path) -> None:
    """The folders and files: agent-written, strata-owned and secret."""
    storage = tmp / "storage"
    agent = storage / "anythingllm-fs"
    edition = agent / "site" / "news" / "editions" / "2026-09-24"
    skill = storage / "plugins" / "agent-skills" / "news-wire"
    for d in (
        edition,
        agent / "site" / "trip-report",
        skill,
        storage / "comkey",
        storage / "plugins" / "agent-flows",
        storage / "documents" / "custom-documents",
        storage / "research-runs" / "q1" / "reports",
        tmp / "site-nginx",
        tmp / "site-public" / "releases" / "r1" / "news",
        tmp / "site-public" / "releases" / "r1" / "trip-report",
        tmp / "site-public" / "stories",
    ):
        d.mkdir(parents=True)
    (storage / ".env").write_text(
        f"LLM_PROVIDER='deepseek'\nDEEPSEEK_MODEL_PREF='deepseek-flash'\nDEEPSEEK_API_KEY='{SECRET}'\n"
    )
    (storage / "comkey" / "ipc-priv.pem").write_text(SECRET)
    (agent / "site" / "FORMAT.md").write_text("# Story format\n<b>bold</b>\n")
    (agent / "site" / "BUILD.md").write_text("Published.\n")
    (edition / "001-harbour.toml").write_text(
        'title = "Harbour <strike> ends"\nlead = true\n[summary]\ntext = "Dock workers vote."\n'
    )
    (edition / "002-bad.toml").write_text("title = \n")
    (agent / "logo.bin").write_bytes(b"\x89PNG\x00\x01\x02binary")
    (agent / "site" / "trip-report" / "publication.toml").write_text('title = "Trip <report>"\n')
    (storage / "research-runs" / "q1" / "reports" / "final.md").write_text("# Feed licences?\n")
    (agent / "research").mkdir()
    (agent / "research" / "q1.md").write_text("# Feed licences?\n")
    (skill / "handler.js").write_text("module.exports = {};")
    (skill / "plugin.json").write_text(
        json.dumps(
            {
                "name": "news-wire",
                "hubId": "news-wire",
                "active": True,
                "description": "Fetches news feeds",
                "entrypoint": {
                    "file": "handler.js",
                    "params": {"feeds": {"type": "string", "description": "Feed <list> path"}},
                },
                "setup_args": {"api_key": {"type": "string", "value": SKILL_SECRET}},
            }
        )
    )
    (storage / "plugins" / "anythingllm_mcp_servers.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "feed-cache": {
                        "command": "npx",
                        "env": {"KEY": MCP_SECRET},
                        "anythingllm": {"autoStart": False},
                    }
                }
            }
        )
    )
    (storage / "plugins" / "agent-flows" / "f1.json").write_text(
        json.dumps(
            {
                "name": "edition-check",
                "active": True,
                "config": {
                    "description": "Checks an edition",
                    "steps": [
                        {
                            "type": "start",
                            "config": {
                                "variables": [
                                    {"name": "day", "type": "required", "description": "Which day"},
                                    {"name": "fixed", "type": "static"},
                                ]
                            },
                        }
                    ],
                },
            }
        )
    )
    (storage / "documents" / "custom-documents" / "guide.json").write_text(
        json.dumps({"title": "Guide", "pageContent": "The whole <guide> text."})
    )
    (tmp / "site-nginx" / "default.conf").write_text("server { listen 8080; }")
    public = tmp / "site-public"
    (public / "releases" / "r1" / "news" / "index.html").write_text("<html>news</html>")
    (public / "releases" / "r1" / "trip-report" / "index.html").write_text("<html>trip</html>")
    (public / "current").symlink_to("releases/r1")
    (public / "status.json").write_text(
        json.dumps(
            {
                "time": "2026-09-24 06:07:00 UTC",
                "ok": True,
                "release": "r1",
                "editions": 14,
                "rejected": [
                    {"file": "news/editions/2026-09-24/002-bad.toml", "reason": "<b>bad</b> TOML"}
                ],
                "waiting": [],
            }
        )
    )


DB = """
create table scheduled_jobs (id integer, name text, prompt text, tools text, schedule text,
                             enabled int, lastRunAt int, nextRunAt int);
create table scheduled_job_runs (id integer, jobId int, status text, result text,
                                 error text, startedAt int, completedAt int);
create table workspaces (id integer, name text, slug text, openAiTemp real, openAiHistory int,
    openAiPrompt text, similarityThreshold real, chatModel text, topN int, chatMode text,
    chatProvider text, agentModel text, agentProvider text, vectorSearchMode text);
create table workspace_chats (id integer, workspaceId int, prompt text, response text,
    include int, thread_id int, api_session_id text, createdAt int);
create table workspace_threads (id integer, name text, slug text, workspace_id int);
create table workspace_documents (id integer, docId text, filename text, docpath text,
    workspaceId int, metadata text, createdAt int, pinned int);
create table document_vectors (id integer, docId text, vectorId text);
create table memories (id integer, user_id int, workspace_id int, scope text, content text,
    created_at int);
create table system_settings (label text, value text);
create table system_prompt_variables (key text, value text, description text);
create table slash_command_presets (command text, prompt text, description text);
create table prompt_history (id integer, workspaceId int, prompt text);
create table workspace_agent_invocations (id integer, prompt text);
create table event_logs (id integer, event text, metadata text, occurredAt text);
insert into system_settings values ('disabled_agent_skills', '["web-browsing"]');
insert into system_settings values ('default_agent_skills', '["filesystem-agent"]');
insert into system_settings values ('disabled_filesystem_skills', '["filesystem-move-file"]');
insert into system_settings values ('default_system_prompt', 'The default prompt.');
insert into system_prompt_variables values ('team', 'Night desk', 'Who runs it');
insert into slash_command_presets values ('/digest', 'Summarize today in five bullets.', '');
insert into event_logs values (1, 'sent_chat', '{}', '2026-09-24T06:00:00');
insert into workspace_threads values (7, 'Layout <ideas>', 'layout', 1);
insert into workspace_documents values (1, 'd1', 'guide.md', 'custom-documents/guide.json', 1,
    '{"title": "Guide"}', 1, 1);
insert into document_vectors values (1, 'd1', 'v1');
insert into document_vectors values (2, 'd1', 'v2');
insert into memories values (1, null, 1, 'workspace', 'The weather box stays left.', 1);
"""


def database(storage: Path) -> None:
    """The database: one workspace with two threads, one job with two runs."""
    db = sqlite3.connect(storage / "anythingllm.db")
    db.executescript(DB)
    db.execute(
        "insert into workspaces values (1, 'Workshop test', 'workshop-test', 0.7, 2, ?, 0.25,"
        " null, 4, 'chat', null, null, null, null)",
        (PROMPT,),
    )
    chats = [
        (i, 1, f"{CHAT} {i}", json.dumps({"text": f"{REPLY} {i}"}), 1, None, None, i)
        for i in (1, 2, 3)
    ]
    chats.append((4, 1, "In the thread", json.dumps({"text": "Thread reply"}), 1, 7, None, 4))
    db.executemany("insert into workspace_chats values (?, ?, ?, ?, ?, ?, ?, ?)", chats)
    tools = json.dumps(["@@news-wire", "filesystem-agent#filesystem-write-text-file"])
    db.execute(
        "insert into scheduled_jobs values (1, 'Daily news digest', ?, ?, '0 5 * * *', 1, ?, ?)",
        (JOB_PROMPT, tools, DAY_MS, DAY_MS + 86_400_000),
    )
    path = "site/news/editions/2026-09-24/001-harbour.toml"
    good = run_result(
        [
            ("news-wire", {"feeds": "sources.toml"}),
            ("filesystem-write-text-file", {"path": path, "content": "x" * 400}),
        ],
        "Wrote 1 story.",
    )
    leaked = run_result(
        [("news-wire", {"feeds": "sources.toml"})],
        'Writing.\n<DSML function_calls>\n<DSML invoke name="filesystem-write-text-file">',
    )
    runs = [
        (1, 1, "completed", good, None, DAY_MS - 90_000_000, DAY_MS - 89_000_000),
        (2, 1, "completed", leaked, "server <boom>", DAY_MS, DAY_MS + 252_000),
    ]
    db.executemany("insert into scheduled_job_runs values (?, ?, ?, ?, ?, ?, ?)", runs)
    db.commit()
    db.close()


def build(tmp: Path) -> Path:
    """The whole fake data folder."""
    files(tmp)
    database(tmp / "storage")
    return tmp
