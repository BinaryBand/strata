"""The /review monitor shows AnythingLLM's layout but never its secrets.

A fake data folder carries planted secrets -- a settings file with a key, a
database holding chat text, job prompts and error text, an MCP config with a
key -- and every test asserts they stay out of what the monitor serves, while
the allowlisted files, the tree and the status still show.
"""

from __future__ import annotations

import http.client
import importlib
import json
import os
import socket
import sqlite3
import sys
import threading
from pathlib import Path

import pytest

MONITOR = (
    Path(__file__).resolve().parents[1] / "ansible" / "playbooks" / "files" / "anythingllm-review"
)
SECRET = "sk-planted-secret-0123456789"
CHAT = "my private chat about the planted topic"
LOGIN = "admin@github"


def load(monkeypatch, root: Path):
    """The server module, fresh, with its content module reachable as `.content`."""
    monkeypatch.syspath_prepend(str(MONITOR))
    for name in ("review", "review_content"):
        sys.modules.pop(name, None)
    content = importlib.import_module("review_content")
    review = importlib.import_module("review")
    monkeypatch.setattr(content, "ROOT", root)
    monkeypatch.setattr(review, "LOGIN", LOGIN)
    monkeypatch.setattr(content, "service_state", lambda unit: f"active ({unit})")
    return review


@pytest.fixture
def root(tmp_path: Path) -> Path:
    storage = tmp_path / "storage"
    site = storage / "anythingllm-fs" / "site" / "news"
    skill = storage / "plugins" / "agent-skills" / "news-wire"
    for d in (
        site,
        skill,
        storage / "comkey",
        storage / "research-runs" / "q" / "sources",
        tmp_path / "site-nginx",
    ):
        d.mkdir(parents=True)
    (storage / ".env").write_text(f"OPEN_AI_KEY='{SECRET}'\n")
    (storage / "comkey" / "ipc-priv.pem").write_text(SECRET)
    (storage / "research-runs" / "q" / "sources" / "abc.txt").write_text(SECRET)
    (site / "index.html").write_text("<p>front page</p>")
    (skill / "handler.js").write_text("module.exports = {};")
    (skill / "plugin.json").write_text(
        json.dumps({"name": "News", "setup_args": {"api_key": {"type": "string", "value": SECRET}}})
    )
    (storage / "plugins" / "anythingllm_mcp_servers.json").write_text(
        json.dumps({"mcpServers": {"memory": {"command": "npx", "env": {"KEY": SECRET}}}})
    )
    (tmp_path / "site-nginx" / "default.conf").write_text("server { listen 8080; }")
    db = sqlite3.connect(storage / "anythingllm.db")
    db.executescript(
        f"""
        create table scheduled_jobs (id integer, name text, schedule text, enabled int,
                                     lastRunAt text, nextRunAt text, prompt text);
        insert into scheduled_jobs
            values (1, 'Daily news digest', '0 5 * * *', 1, 't1', 't2', 'PROMPT {SECRET}');
        create table scheduled_job_runs (id integer, jobId int, status text, startedAt text,
                                         completedAt text, error text);
        insert into scheduled_job_runs values (1, 1, 'failed', 's', 'c', 'boom {SECRET}');
        create table workspaces (id integer, name text, slug text);
        insert into workspaces values (1, 'Workshop test', 'workshop-test');
        create table workspace_chats (id integer, workspaceId int, prompt text, response text,
                                      createdAt text);
        insert into workspace_chats values (1, 1, '{CHAT}', '{CHAT}', 'when');
        create table system_settings (label text, value text);
        insert into system_settings values ('default_agent_skills', '["filesystem-agent"]');
        insert into system_settings values ('some_api_key', '{SECRET}');
        create table event_logs (id integer, event text, metadata text, occurredAt text);
        insert into event_logs values (1, 'sent_chat', '{CHAT}', 'when');
        """
    )
    db.commit()
    db.close()
    return tmp_path


def test_the_overview_shows_layout_and_status_but_no_secret(monkeypatch, root: Path) -> None:
    review = load(monkeypatch, root)
    page = review.content.overview(60)
    for shown in (
        "storage/.env",
        "storage/anythingllm.db",
        "Daily news digest",
        "workshop-test",
        "filesystem-agent",
        "memory",
        "sent_chat",
        "active (anythingllm.service)",
    ):
        assert shown in page
    for hidden in (SECRET, CHAT, "PROMPT", "boom"):
        assert hidden not in page
    assert "yes (" in page  # a job error is flagged without its text


@pytest.mark.parametrize(
    "rel",
    [
        "storage/.env",
        "storage/anythingllm.db",
        "storage/comkey/ipc-priv.pem",
        "storage/plugins/anythingllm_mcp_servers.json",
        "storage/research-runs/q/sources/abc.txt",
        "storage/anythingllm-fs/../../storage/.env.md",
        "storage/anythingllm-fs/site/../../.env",
    ],
)
def test_the_viewer_refuses_secrets_and_escapes(monkeypatch, root: Path, rel: str) -> None:
    review = load(monkeypatch, root)
    status, body = review.content.file_view(rel)
    assert status in (403, 404)
    assert SECRET not in body


def test_a_symlink_to_a_secret_is_refused_even_on_an_allowed_path(monkeypatch, root: Path) -> None:
    review = load(monkeypatch, root)
    (root / "storage" / "anythingllm-fs" / "leak.md").symlink_to(root / "storage" / ".env")
    status, body = review.content.file_view("storage/anythingllm-fs/leak.md")
    assert status == 403
    assert SECRET not in body


def test_a_fifo_is_refused_without_blocking(monkeypatch, root: Path) -> None:
    review = load(monkeypatch, root)
    os.mkfifo(root / "storage" / "anythingllm-fs" / "pipe.md")
    assert review.content.file_view("storage/anythingllm-fs/pipe.md")[0] == 403


def test_allowed_files_show_with_setup_values_redacted_and_agent_text_labelled(
    monkeypatch, root: Path
) -> None:
    review = load(monkeypatch, root)
    status, body = review.content.file_view("storage/plugins/agent-skills/news-wire/plugin.json")
    assert status == 200
    assert SECRET not in body
    assert "&lt;redacted&gt;" in body
    status, body = review.content.file_view("storage/anythingllm-fs/site/news/index.html")
    assert status == 200
    assert "&lt;p&gt;front page&lt;/p&gt;" in body
    assert "Written by the AI agent" in body
    assert "Written by the AI agent" not in review.content.file_view("site-nginx/default.conf")[1]


def test_the_overview_is_rebuilt_at_most_once_per_minute(monkeypatch, root: Path) -> None:
    review = load(monkeypatch, root)
    builds = []
    monkeypatch.setattr(
        review.content, "overview", lambda _ttl: builds.append(1) or f"page {len(builds)}"
    )
    clock = [1000.0]
    monkeypatch.setattr(review.time, "monotonic", lambda: clock[0])
    cache = review.Cache()
    assert cache.get() == "page 1"
    clock[0] += 59
    assert cache.get() == "page 1"
    clock[0] += 1
    assert cache.get() == "page 2"


def request(
    sock_path: str, path: str, headers: dict[str, list[str]], method: str = "GET"
) -> tuple[int, str]:
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.connect(sock_path)
    conn = http.client.HTTPConnection("review")
    conn.sock = sock
    conn.putrequest(method, path)
    for name, values in headers.items():
        for value in values:
            conn.putheader(name, value)
    conn.endheaders()
    response = conn.getresponse()
    return response.status, response.read().decode()


@pytest.fixture
def server(monkeypatch, root: Path, tmp_path_factory):
    review = load(monkeypatch, root)
    sock_path = str(tmp_path_factory.mktemp("sock") / "review.sock")
    monkeypatch.setattr(review, "SOCKET", sock_path)
    srv = review.UnixHTTPServer(sock_path, review.Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield sock_path
    srv.shutdown()
    srv.server_close()


@pytest.mark.parametrize(
    "logins",
    [[], ["someone@github"], [LOGIN, "someone@github"], ["someone@github", LOGIN]],
    ids=["missing", "other-user", "duplicate-first", "duplicate-last"],
)
def test_only_the_one_tailnet_login_is_served(server: str, logins: list[str]) -> None:
    status, body = request(server, "/", {"Tailscale-User-Login": logins})
    assert status == 403
    assert "storage" not in body


def test_the_login_gets_the_page_over_the_socket_and_writes_are_refused(server: str) -> None:
    status, body = request(server, "/", {"Tailscale-User-Login": [LOGIN]})
    assert status == 200
    assert "storage/anythingllm.db" in body
    assert SECRET not in body
    assert request(server, "/", {"Tailscale-User-Login": [LOGIN]}, method="POST")[0] == 405
