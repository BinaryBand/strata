"""The /review monitor shows AnythingLLM's layout but never its secrets.

A fake data folder carries planted secrets -- a settings file with a key, a
database holding chat text, job prompts, run output and error text, an MCP
config with a key -- and every test asserts they stay out of every screen the
monitor serves, while skills, tasks, publications and files still show. Job
runs appear only as safe summaries: counts and flags, never their text.
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
MODULES = (
    "review",
    "review_content",
    "review_story",
    "review_layout",
    "review_tasks",
    "review_skills",
    "review_artifacts",
    "review_files",
    "review_overview",
)
SECRET = "sk-planted-secret-0123456789"
CHAT = "my private chat about the planted topic"
OUTPUT = "private run output quoting a fetched page"
LOGIN = "admin@github"
DAY_MS = 1790238746913


def load(monkeypatch, root: Path):
    """The server module, fresh, with its content module reachable as `.content`."""
    monkeypatch.syspath_prepend(str(MONITOR))
    for name in MODULES:
        sys.modules.pop(name, None)
    content = importlib.import_module("review_content")
    review = importlib.import_module("review")
    monkeypatch.setattr(content, "ROOT", root)
    monkeypatch.setattr(review, "LOGIN", LOGIN)
    monkeypatch.setattr(content, "service_state", lambda unit: f"active ({unit})")
    return review


def run_result(tools: list[str], text: str) -> str:
    """A scheduled_job_runs.result value as AnythingLLM stores it."""
    calls = [
        {"toolName": t, "arguments": {"content": OUTPUT}, "result": OUTPUT, "timestamp": 1}
        for t in tools
    ]
    return json.dumps({"text": text, "toolCalls": calls, "thoughts": [OUTPUT], "outputs": []})


@pytest.fixture
def root(tmp_path: Path) -> Path:
    storage = tmp_path / "storage"
    site = storage / "anythingllm-fs" / "site"
    skill = storage / "plugins" / "agent-skills" / "news-wire"
    for d in (
        site / "news",
        site / "trip-report",
        skill,
        storage / "comkey",
        storage / "research-runs" / "q" / "sources",
        tmp_path / "site-nginx",
        tmp_path / "site-public" / "releases" / "r1" / "news",
        tmp_path / "site-public" / "releases" / "r1" / "trip-report",
        tmp_path / "site-public" / "stories",
    ):
        d.mkdir(parents=True)
    (storage / ".env").write_text(f"OPEN_AI_KEY='{SECRET}'\n")
    (storage / "comkey" / "ipc-priv.pem").write_text(SECRET)
    (storage / "research-runs" / "q" / "sources" / "abc.txt").write_text(SECRET)
    (site / "news" / "index.html").write_text("<p>front page</p>\nsecond line")
    (site / "trip-report" / "publication.toml").write_text('title = "Trip <report>"\n')
    (skill / "handler.js").write_text("module.exports = {};")
    (skill / "plugin.json").write_text(
        json.dumps(
            {
                "name": "News <wire>",
                "hubId": "news-wire",
                "active": True,
                "version": "1.2.0",
                "description": "Reads the news feeds",
                "setup_args": {"api_key": {"type": "string", "value": SECRET}},
            }
        )
    )
    (storage / "plugins" / "anythingllm_mcp_servers.json").write_text(
        json.dumps({"mcpServers": {"memory": {"command": "npx", "env": {"KEY": SECRET}}}})
    )
    (tmp_path / "site-nginx" / "default.conf").write_text("server { listen 8080; }")
    public = tmp_path / "site-public"
    (public / "releases" / "r1" / "news" / "index.html").write_text("<html>news</html>")
    (public / "releases" / "r1" / "trip-report" / "index.html").write_text("<html>trip</html>")
    (public / "current").symlink_to("releases/r1")
    (public / "stories" / "2026-09-24.json").write_text("[]")
    (public / "status.json").write_text(
        json.dumps(
            {
                "time": "t",
                "ok": False,
                "release": None,
                "editions": 2,
                "rejected": [{"file": "news/x.toml", "reason": "<b>bad</b>"}],
                "waiting": [],
            }
        )
    )
    good = run_result(
        ["news-wire", "filesystem-create-directory"]
        + ["filesystem-write-text-file"] * 4
        + ["filesystem-read-text-file", "filesystem-move-file"],
        f"Top headlines {OUTPUT}",
    )
    leaked = run_result(["news-wire", "filesystem-list-directory"], f"<DSML invoke> {OUTPUT}")
    db = sqlite3.connect(storage / "anythingllm.db")
    db.executescript(
        f"""
        create table scheduled_jobs (id integer, name text, prompt text, tools text, schedule text,
                                     enabled int, lastRunAt int, nextRunAt int);
        create table scheduled_job_runs (id integer, jobId int, status text, result text,
                                         error text, startedAt int, completedAt int);
        create table workspaces (id integer, name text, slug text);
        insert into workspaces values (1, 'Workshop test', 'workshop-test');
        create table workspace_chats (id integer, workspaceId int, prompt text, response text,
                                      createdAt text);
        insert into workspace_chats values (1, 1, '{CHAT}', '{CHAT}', 'when');
        create table system_settings (label text, value text);
        insert into system_settings values ('default_agent_skills', '["filesystem-agent"]');
        insert into system_settings values ('disabled_agent_skills', '["web-browsing"]');
        insert into system_settings values ('some_api_key', '{SECRET}');
        create table event_logs (id integer, event text, metadata text, occurredAt text);
        insert into event_logs values (1, 'sent_chat', '{CHAT}', 'when');
        """
    )
    tools = json.dumps(["@@news-wire", "filesystem-agent#filesystem-write-text-file"])
    db.execute(
        "insert into scheduled_jobs values (1, 'Daily news digest', ?, ?, '0 5 * * *', 1, ?, ?)",
        (f"PROMPT {SECRET}", tools, DAY_MS, DAY_MS + 86_400_000),
    )
    db.execute(
        "insert into scheduled_jobs values "
        "(2, 'Weekly <check>', 'PROMPT', '[]', '0 6 * * 0', 1, 0, 0)"
    )
    runs = [
        (1, 1, "completed", leaked, None, DAY_MS - 3_000_000, DAY_MS - 2_900_000),
        (2, 1, "completed", good, None, DAY_MS, DAY_MS + 57_000),
        (3, 2, "failed", None, f"boom {SECRET}", DAY_MS, DAY_MS + 1_000),
    ]
    db.executemany("insert into scheduled_job_runs values (?, ?, ?, ?, ?, ?, ?)", runs)
    db.commit()
    db.close()
    return tmp_path


HIDDEN = (SECRET, CHAT, OUTPUT, "PROMPT", "boom", "DSML invoke")


def all_pages(review) -> dict[str, str]:
    """Every screen, whole pages, as the socket would serve them."""
    pages = {s: review.render(s) for s in ("overview", "skills", "tasks", "artifacts")}
    for rel in ("", "storage", "storage/plugins/agent-skills/news-wire"):
        status, main = review.review_files.screen("/review", rel)
        assert status == 200
        pages[f"files:{rel}"] = main
    return pages


def test_no_screen_shows_a_secret_chat_prompt_or_run_output(monkeypatch, root: Path) -> None:
    review = load(monkeypatch, root)
    for name, page in all_pages(review).items():
        for hidden in HIDDEN:
            assert hidden not in page, (name, hidden)


def test_the_overview_shows_health_skills_tasks_artifacts_and_files(
    monkeypatch, root: Path
) -> None:
    review = load(monkeypatch, root)
    page = review.render("overview")
    for shown in (
        "Good ",
        "admin",
        "Instance",
        "1 task needs a look",
        "News &lt;wire&gt;",
        "Daily news digest",
        "Weekly &lt;check&gt;",
        "Every day at 05:00 UTC",
        "Sundays at 06:00 UTC",
        "The Daily Seek",
        "Trip &lt;report&gt;",
        "storage",
        "workshop-test",
        "filesystem-agent",
        "memory",
        "sent_chat",
        "active (anythingllm.service)",
        'href="/review/skills"',
    ):
        assert shown in page, shown
    assert "<script" not in page


def test_runs_are_safe_summaries_and_leaks_need_a_look(monkeypatch, root: Path) -> None:
    review = load(monkeypatch, root)
    page = review.render("tasks")
    assert "wrote 4 files · 8 tool calls" in page
    assert "tool calls leaked as text and did not run" in page
    assert "recorded an error (not shown)" in page
    assert "Needs a look" in page
    assert "Ran fine" in page
    assert "0m 57s" in page
    tasks = review.review_tasks
    run = tasks.safe_run("completed", run_result(["a"], "text DSML here"), None, 1, 2)
    assert not run.ok
    assert "DSML" not in run.summary


def test_skills_show_state_usage_and_setting_names_only(monkeypatch, root: Path) -> None:
    review = load(monkeypatch, root)
    page = review.render("skills")
    assert "News &lt;wire&gt;" in page
    assert "1.2.0" in page
    assert "api_key" in page
    assert 'aria-label="Off"' in page  # web-browsing is disabled
    found = {s.id: s for s in review.review_skills.skills()}
    assert found["news-wire"].on
    assert not found["web-browsing"].on
    assert found["filesystem-agent"].on
    assert found["news-wire"].used_by == ["Daily news digest"]
    assert found["filesystem-agent"].last_used == DAY_MS


def test_artifacts_list_publications_build_status_and_editions(monkeypatch, root: Path) -> None:
    review = load(monkeypatch, root)
    page = review.render("artifacts")
    assert 'href="/news/"' in page
    assert 'href="/news/2026-09-24/"' in page
    assert "Trip &lt;report&gt;" in page
    assert "FAILED" in page
    assert "&lt;b&gt;bad&lt;/b&gt;" in page


def test_a_current_link_outside_the_releases_is_not_followed(monkeypatch, root: Path) -> None:
    review = load(monkeypatch, root)
    current = root / "site-public" / "current"
    current.unlink()
    current.symlink_to(root / "storage")
    assert review.review_artifacts.publications() == []


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
    status, body = review.review_files.file_view("/review", rel)
    assert status in (403, 404)
    assert SECRET not in body


def test_a_symlink_to_a_secret_is_refused_even_on_an_allowed_path(monkeypatch, root: Path) -> None:
    review = load(monkeypatch, root)
    (root / "storage" / "anythingllm-fs" / "leak.md").symlink_to(root / "storage" / ".env")
    status, body = review.review_files.file_view("/review", "storage/anythingllm-fs/leak.md")
    assert status == 403
    assert SECRET not in body


def test_a_fifo_is_refused_without_blocking(monkeypatch, root: Path) -> None:
    review = load(monkeypatch, root)
    os.mkfifo(root / "storage" / "anythingllm-fs" / "pipe.md")
    assert review.review_files.file_view("/review", "storage/anythingllm-fs/pipe.md")[0] == 403


def test_allowed_files_show_with_setup_values_redacted_and_agent_text_labelled(
    monkeypatch, root: Path
) -> None:
    review = load(monkeypatch, root)
    view = review.review_files.file_view
    status, body = view("/review", "storage/plugins/agent-skills/news-wire/plugin.json")
    assert status == 200
    assert SECRET not in body
    assert "&lt;redacted&gt;" in body
    status, body = view("/review", "storage/anythingllm-fs/site/news/index.html")
    assert status == 200
    assert "&lt;p&gt;front page&lt;/p&gt;\nsecond line" in body  # newlines kept
    assert "Written by the AI agent" in body
    assert "Written by the AI agent" not in view("/review", "site-nginx/default.conf")[1]


def test_files_browse_one_folder_without_following_links(monkeypatch, root: Path) -> None:
    review = load(monkeypatch, root)
    screen = review.review_files.screen
    (root / "storage" / "escape").symlink_to("/")
    status, body = screen("/review", "storage")
    assert status == 200
    assert "(link, not followed)" in body
    assert "files?path=storage%2Fescape" not in body
    assert ".env" in body
    assert "file?path=storage%2F.env" not in body  # secret: name and size only
    assert screen("/review", "storage/escape")[0] == 404
    assert screen("/review", "storage/../..")[0] == 404
    status, body = screen("/review", "storage/plugins/agent-skills/news-wire")
    assert "file?path=storage%2Fplugins%2Fagent-skills%2Fnews-wire%2Fplugin.json" in body


def test_each_screen_is_rebuilt_at_most_once_per_minute(monkeypatch, root: Path) -> None:
    review = load(monkeypatch, root)
    builds = []
    monkeypatch.setattr(
        review, "render", lambda screen: builds.append(screen) or f"{screen} {len(builds)}"
    )
    clock = [1000.0]
    monkeypatch.setattr(review.time, "monotonic", lambda: clock[0])
    cache = review.Cache()
    assert cache.get("overview") == "overview 1"
    assert cache.get("skills") == "skills 2"
    clock[0] += 59
    assert cache.get("overview") == "overview 1"
    clock[0] += 1
    assert cache.get("overview") == "overview 3"


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
@pytest.mark.parametrize(
    "path", ["/", "/tasks", "/files?path=storage", "/file?path=site-nginx/default.conf"]
)
def test_only_the_one_tailnet_login_is_served(server: str, logins: list[str], path: str) -> None:
    status, body = request(server, path, {"Tailscale-User-Login": logins})
    assert status == 403
    assert "storage" not in body


@pytest.mark.parametrize(
    ("path", "status"),
    [
        ("/", 200),
        ("/skills", 200),
        ("/tasks/", 200),
        ("/artifacts", 200),
        ("/files?path=storage", 200),
        ("/file?path=site-nginx/default.conf", 200),
        ("/file?path=storage/.env", 403),
        ("/nowhere", 404),
    ],
)
def test_the_login_gets_each_screen_over_the_socket(server: str, path: str, status: int) -> None:
    got, body = request(server, path, {"Tailscale-User-Login": [LOGIN]})
    assert got == status
    for hidden in HIDDEN:
        assert hidden not in body


def test_writes_are_refused(server: str) -> None:
    assert request(server, "/", {"Tailscale-User-Login": [LOGIN]}, method="POST")[0] == 405


def test_story_sources_show_failing_hosts_first_and_timings_but_no_story_text(
    monkeypatch, root: Path
) -> None:
    review = load(monkeypatch, root)
    cache = root / "story-cache"
    cache.mkdir()
    (cache / "health.json").write_text(
        json.dumps(
            {
                "npr.org": {"ok": 4, "failed": 0, "streak": 0, "last_ok": "2026-09-24T09:00:00"},
                "pbs.org": {"ok": 0, "failed": 3, "streak": 3, "last_error": "<i>403</i>"},
            }
        )
    )
    (cache / "abc.json").write_text(
        json.dumps(
            {
                "day": "2026-09-24",
                "paragraphs": ["SECRET STORY TEXT"],
                "notes": [],
                "fetch_seconds": 2.1,
                "model_seconds": 18.4,
                "input_chars": 9000,
                "output_chars": 1500,
            }
        )
    )
    page = review.render("artifacts")
    assert page.index("pbs.org") < page.index("npr.org")
    assert "&lt;i&gt;403&lt;/i&gt;" in page
    assert "18.4" in page
    assert "SECRET STORY TEXT" not in page
