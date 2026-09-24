"""The /review monitor shows everything the agent can see, and never a stored credential.

Credentials are planted where only the server keeps them -- the settings file,
a signing key, a skill's setup value, an MCP server's env -- and every page the
monitor serves is checked for them. The key check finds one when it turns up in
the agent's reach and names where, without the value. Files open without
following links, FIFOs are refused, and only the one tailnet login is served.
"""

from __future__ import annotations

import http.client
import os
import socket
import sqlite3
import sys
import threading
from pathlib import Path

import pytest

from tests._review import LOGIN, SECRET, SECRETS, build, load


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return build(tmp_path)


def every_page(review) -> dict[str, str]:
    """Every screen and a sample of every per-request page, whole."""
    pages = {s: review.render(s)[1] for s in review.TITLES}
    queries = {
        "/files": {"path": ""},
        "/files?-": {"path": "-"},
        "/files?storage": {"path": "storage"},
        "/files?comkey": {"path": "storage/comkey"},
        "/files?skill": {"path": "storage/plugins/agent-skills/news-wire"},
        "/file?plugin": {"path": "storage/plugins/agent-skills/news-wire/plugin.json"},
        "/file?toml": {
            "path": "storage/anythingllm-fs/site/news/editions/2026-09-24/001-harbour.toml"
        },
        "/run?1": {"id": "1"},
        "/run?2": {"id": "2"},
        "/thread": {"ws": "workshop-test", "id": "default"},
        "/doc": {"id": "1"},
        "/tasks?job": {"job": "1"},
    }
    for name, query in queries.items():
        found = review.dynamic(name.split("?")[0], lambda k, q=query: q.get(k, ""))
        assert found is not None, name
        pages[name] = found[1]
    return pages


def test_no_page_shows_a_stored_credential(monkeypatch, root: Path) -> None:
    review = load(monkeypatch, root)
    for name, page in every_page(review).items():
        for secret in SECRETS:
            assert secret not in page, (name, secret)
        assert "<script" not in page


def test_the_key_check_is_quiet_when_no_key_is_in_reach(monkeypatch, root: Path) -> None:
    review = load(monkeypatch, root)
    page = review.render("overview")[1]
    assert "No keys found in the agent&rsquo;s reach" in page
    assert 'role="alert"' not in page


def test_a_key_in_an_agent_file_or_a_chat_is_found_but_never_shown(monkeypatch, root: Path) -> None:
    review = load(monkeypatch, root)
    leak = root / "storage" / "anythingllm-fs" / "notes.md"
    leak.write_text(f"line one\nline two {SECRET}\n")
    db = sqlite3.connect(root / "storage" / "anythingllm.db")
    db.execute("update workspace_chats set prompt = ? where id = 2", (f"here {SECRET}",))
    db.commit()
    db.close()
    findings = review.review_overview.review_secrets.check()
    places = {(f.setting, f.where, f.line) for f in findings}
    assert ("DEEPSEEK_API_KEY", "notes.md", 2) in places
    assert ("DEEPSEEK_API_KEY", "chat 2", 0) in places
    page = review.render("overview")[1]
    assert 'role="alert"' in page
    assert ">notes.md<" in page
    assert "DEEPSEEK_API_KEY" in page
    assert "file?path=storage%2Fanythingllm-fs%2Fnotes.md" in page
    assert SECRET not in page


def test_skill_and_mcp_credentials_are_searched_for_too(monkeypatch, root: Path) -> None:
    review = load(monkeypatch, root)
    names = {n for n, _ in review.review_overview.review_secrets.credentials()}
    assert names == {"DEEPSEEK_API_KEY", "news-wire setting api_key", "MCP feed-cache env KEY"}


@pytest.mark.parametrize(
    "rel",
    [
        "storage/.env",
        "storage/anythingllm.db",
        "storage/comkey/ipc-priv.pem",
        "storage/plugins/anythingllm_mcp_servers.json",
        "storage/anythingllm-fs/../.env",
        "storage/anythingllm-fs/site/../../.env",
        "",
    ],
)
def test_the_viewer_refuses_secrets_and_escapes(monkeypatch, root: Path, rel: str) -> None:
    review = load(monkeypatch, root)
    status, body = review.review_viewer.file_view("", rel)
    assert status in (403, 404)
    assert SECRET not in body


def test_a_symlink_in_the_agent_folder_is_not_followed(monkeypatch, root: Path) -> None:
    review = load(monkeypatch, root)
    (root / "storage" / "anythingllm-fs" / "leak.md").symlink_to(root / "storage" / ".env")
    status, body = review.review_viewer.file_view("", "storage/anythingllm-fs/leak.md")
    assert status == 403
    assert SECRET not in body
    listing = review.review_files.screen("", "storage/anythingllm-fs")[1]
    assert "link, not followed" in listing
    assert "leak.md" in listing
    assert "file?path=storage%2Fanythingllm-fs%2Fleak.md" not in listing


def test_a_fifo_is_refused_without_blocking(monkeypatch, root: Path) -> None:
    review = load(monkeypatch, root)
    os.mkfifo(root / "storage" / "anythingllm-fs" / "pipe.md")
    assert review.review_viewer.file_view("", "storage/anythingllm-fs/pipe.md")[0] == 403


def test_the_data_folder_lists_secret_files_by_name_only(monkeypatch, root: Path) -> None:
    review = load(monkeypatch, root)
    (root / "storage" / "escape").symlink_to("/")
    status, body = review.review_files.screen("", "storage")
    assert status == 200
    assert ".env" in body
    assert "file?path=storage%2F.env" not in body
    assert "Name and size only" in body
    assert review.review_files.screen("", "storage/escape")[0] == 404
    assert review.review_files.screen("", "storage/../..")[0] == 404


def test_secret_files_show_a_fingerprint_not_their_contents(monkeypatch, root: Path) -> None:
    review = load(monkeypatch, root)
    body = review.review_files.screen("", "")[1]
    assert ".env" in body
    assert "comkey/ipc-priv.pem" in body
    assert "fingerprint sha256:" in body
    assert SECRET not in body


def test_settings_show_secrets_as_set_and_other_values_as_written(monkeypatch, root: Path) -> None:
    review = load(monkeypatch, root)
    page = review.render("tools")[1]
    assert "DEEPSEEK_API_KEY" in page
    assert "set" in page
    assert "deepseek-flash" in page
    assert "api_key (values hidden)" in page


def test_each_screen_is_rebuilt_at_most_once_per_minute(monkeypatch, root: Path) -> None:
    review = load(monkeypatch, root)
    builds = []
    monkeypatch.setattr(
        review,
        "render",
        lambda screen, slug="": builds.append(screen) or (200, f"{screen}{slug} {len(builds)}"),
    )
    clock = [1000.0]
    monkeypatch.setattr(review.time, "monotonic", lambda: clock[0])
    cache = review.Cache()
    assert cache.get("overview") == (200, "overview 1")
    assert cache.get("workspace", "a") == (200, "workspacea 2")
    clock[0] += 59
    assert cache.get("overview") == (200, "overview 1")
    clock[0] += 1
    assert cache.get("overview") == (200, "overview 3")


def request(
    sock_path: str, path: str, headers: dict[str, list[str]], method: str = "GET"
) -> tuple[int, str, http.client.HTTPMessage]:
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
    return response.status, response.read().decode(), response.headers


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
@pytest.mark.parametrize("path", ["/", "/tasks", "/run?id=1", "/files", "/thread?id=default"])
def test_only_the_one_tailnet_login_is_served(server: str, logins: list[str], path: str) -> None:
    status, body, _ = request(server, path, {"Tailscale-User-Login": logins})
    assert status == 403
    assert "Workshop" not in body


@pytest.mark.parametrize(
    ("path", "status"),
    [
        ("/", 200),
        ("/tools", 200),
        ("/tasks/", 200),
        ("/tasks?job=1", 200),
        ("/artifacts", 200),
        ("/workspace?ws=workshop-test", 200),
        ("/knowledge", 200),
        ("/more", 200),
        ("/files", 200),
        ("/file?path=site-nginx/default.conf", 200),
        ("/file?path=storage/.env", 403),
        ("/run?id=2", 200),
        ("/run?id=99", 404),
        ("/run?id=x", 404),
        ("/thread?ws=workshop-test&id=7", 200),
        ("/thread?ws=workshop-test&id=x", 404),
        ("/doc?id=1", 200),
        ("/workspace?ws=nope", 404),
        ("/nowhere", 404),
    ],
)
def test_the_login_gets_each_page_over_the_socket(server: str, path: str, status: int) -> None:
    got, body, headers = request(server, path, {"Tailscale-User-Login": [LOGIN]})
    assert got == status
    assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]
    assert "script-src" not in headers["Content-Security-Policy"]  # default-src 'none' covers it
    assert headers["X-Frame-Options"] == "DENY"
    for secret in SECRETS:
        assert secret not in body


def test_writes_are_refused(server: str) -> None:
    assert request(server, "/", {"Tailscale-User-Login": [LOGIN]}, method="POST")[0] == 405


def test_a_broken_page_answers_500_and_the_monitor_stays_up(monkeypatch, server: str) -> None:
    review_run = sys.modules["review_run"]

    def broken(*_: object) -> tuple[int, str]:
        raise RuntimeError(SECRET)

    monkeypatch.setattr(review_run, "run_view", broken)
    status, body, _ = request(server, "/run?id=1", {"Tailscale-User-Login": [LOGIN]})
    assert status == 500
    assert SECRET not in body
    assert request(server, "/", {"Tailscale-User-Login": [LOGIN]})[0] == 200
