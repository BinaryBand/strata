"""The /story service writes a story only when its reader asks, and fetches only public pages.

These tests drive story.py, story_fetch.py and story_page.py without a network:
address lookups are stubbed, and the AnythingLLM call is replaced, so what is
checked is which requests may start a story, which addresses may be fetched,
and that nothing a source or the model returns reaches the page as markup.
"""

from __future__ import annotations

import importlib
import io
import json
import sys
from email.message import Message
from pathlib import Path

import pytest

SERVICE = (
    Path(__file__).resolve().parents[1] / "ansible" / "playbooks" / "files" / "anythingllm-story"
)
LOGIN = "reader@example.com"
DAY = "2026-09-25"
STORY = {
    "title": 'Talks <b>resume</b> & "hope"',
    "region": "World",
    "lead": True,
    "rank": 1,
    "summary": "One <i>sentence</i>.",
    "sources": [{"name": "NPR", "url": "https://www.npr.org/a"}],
}


@pytest.fixture
def mods(monkeypatch, tmp_path: Path):
    """story, story_fetch and story_page, fresh, with a temporary index and cache."""
    monkeypatch.syspath_prepend(str(SERVICE))
    for name in ("story", "story_fetch", "story_page"):
        sys.modules.pop(name, None)
    story = importlib.import_module("story")
    index, cache = tmp_path / "stories", tmp_path / "cache"
    index.mkdir()
    cache.mkdir()
    (index / f"{DAY}.json").write_text(json.dumps([STORY]))
    for attr, value in (("INDEX", index), ("CACHE", cache), ("LOGIN", LOGIN)):
        monkeypatch.setattr(story, attr, value)
    monkeypatch.setattr(story, "DESK", story.Desk())
    return story, sys.modules["story_fetch"], sys.modules["story_page"]


def call(story, path: str, *, method: str = "GET", login: str | None = LOGIN, **headers: str):
    """(status, body) for one request through the real handler, with no socket."""
    handler = story.Handler.__new__(story.Handler)
    handler.path = path
    msg = Message()
    if login is not None:
        msg["Tailscale-User-Login"] = login
    for name, value in headers.items():
        msg[name.replace("_", "-")] = value
    handler.headers = msg
    return handler.route(may_start=method == "GET")


def test_only_the_allowed_login_is_served(mods) -> None:
    story, _, _ = mods
    assert call(story, f"/{DAY}/1", login=None)[0] == 403
    assert call(story, f"/{DAY}/1", login="someone@example.com")[0] == 403


def test_head_and_prefetch_never_start_a_story(mods) -> None:
    story, _, _ = mods
    assert call(story, f"/{DAY}/1", method="HEAD")[0] == 503
    assert call(story, f"/{DAY}/1", Sec_Purpose="prefetch;prerender")[0] == 503
    assert story.DESK.work.empty()
    assert story.DESK.spent_today(add=False) == 0


def test_an_unknown_story_is_404(mods) -> None:
    story, _, _ = mods
    assert call(story, f"/{DAY}/2")[0] == 404
    assert call(story, "/story/2026-09-25/1")[0] == 404  # tailscale strips /story first
    assert call(story, "/../../etc/passwd")[0] == 404


def test_the_first_open_queues_once_and_the_page_refreshes_without_retry(mods) -> None:
    story, _, _ = mods
    status, body = call(story, f"/{DAY}/1?retry=1")
    assert status == 200
    assert f'content="5; url=/story/{DAY}/1"' in body
    call(story, f"/{DAY}/1")
    assert story.DESK.work.qsize() == 1
    assert story.DESK.spent_today(add=False) == 1


def test_the_daily_cap_and_a_full_queue_refuse_without_queueing(mods, monkeypatch) -> None:
    story, _, _ = mods
    monkeypatch.setattr(story, "DAILY_CAP", 0)
    status, body = call(story, f"/{DAY}/1")
    assert status == 200
    assert "daily limit" in body
    assert story.DESK.work.empty()
    assert not story.DESK.pending


def test_a_failed_story_stays_failed_until_retried(mods, monkeypatch) -> None:
    story, _, _ = mods

    def fail(_story: dict) -> tuple[list[str], list[str]]:
        msg = "no source could be read"
        raise story.StoryError(msg)

    class OneShot:
        """Hands the worker the queued story, then ends its loop."""

        def __init__(self, items: list) -> None:
            self.items = items

        def get(self) -> tuple:
            if not self.items:
                raise LookupError
            return self.items.pop()

    monkeypatch.setattr(story, "write", fail)
    call(story, f"/{DAY}/1")
    real = story.DESK.work
    story.DESK.work = OneShot([real.get_nowait()])
    with pytest.raises(LookupError):
        story.DESK.run()
    story.DESK.work = real
    assert "no source could be read" in call(story, f"/{DAY}/1")[1]
    assert not story.DESK.pending
    call(story, f"/{DAY}/1?retry=1")
    assert story.DESK.work.qsize() == 1


def test_source_and_model_text_render_as_text(mods) -> None:
    story, _, _ = mods
    reply = (
        "<think>plan</think>First <script>alert(1)</script> para.\n\n## Heading\n\n**Second** para."
    )
    paragraphs = story.paragraphs(reply)
    assert paragraphs == ["First <script>alert(1)</script> para.", "Second para."]
    key = story.story_key(STORY)
    story.save(story.CACHE / f"{key}.json", {"day": DAY, "paragraphs": paragraphs, "notes": []})
    body = call(story, f"/{DAY}/1")[1]
    assert "<script>" not in body
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in body
    assert "&lt;b&gt;resume&lt;/b&gt; &amp; &quot;hope&quot;" in body


def test_a_damaged_cache_entry_is_ignored(mods) -> None:
    story, _, _ = mods
    (story.CACHE / f"{story.story_key(STORY)}.json").write_text('{"paragraphs": 3}')
    assert story.cached(story.story_key(STORY)) is None


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://127.0.0.1:3001/api",
        "https://example.com:8443/",
        "https://user:pw@example.com/",
        "gopher://example.com/",
        "https://" + "a" * 2100 + ".com/",
    ],
)
def test_only_plain_http_urls_are_accepted(mods, url: str) -> None:
    _, fetch, _ = mods
    with pytest.raises(fetch.FetchError):
        fetch.checked(url)


@pytest.mark.parametrize(
    "addresses",
    [["127.0.0.1"], ["10.1.2.3"], ["100.100.100.100"], ["93.184.215.14", "192.168.0.5"], ["::1"]],
)
def test_a_host_with_any_non_public_address_is_refused(mods, monkeypatch, addresses) -> None:
    _, fetch, _ = mods
    monkeypatch.setattr(
        fetch.socket, "getaddrinfo", lambda *_a, **_k: [(0, 0, 0, "", (a, 0)) for a in addresses]
    )
    with pytest.raises(fetch.FetchError, match="not a public"):
        fetch.public_address("news.example", 443)


def test_a_redirect_to_a_file_url_is_refused(mods, monkeypatch) -> None:
    _, fetch, _ = mods
    real_checked = fetch.checked
    seen = []

    def get_checking(url: str, deadline: float):
        del deadline
        seen.append(url)
        real_checked(url)
        return 302, {"location": "file:///etc/passwd"}, b""

    monkeypatch.setattr(fetch, "get", get_checking)
    with pytest.raises(fetch.FetchError):
        fetch.page("https://www.npr.org/a")
    assert seen == ["https://www.npr.org/a", "file:///etc/passwd"]


def test_article_text_keeps_article_paragraphs_only(mods) -> None:
    _, fetch, _ = mods
    long = "word " * 20
    html = (
        f"<html><nav><p>{long}menu</p></nav><article><p>{long}one</p>"
        f"<script>var x = '<p>{long}</p>';</script><p>{long}two &amp; more</p></article></html>"
    )
    text = fetch.article_text(html.encode())
    assert text.split("\n\n") == [f"{long.strip()} one", f"{long.strip()} two & more"]


def test_a_slow_body_is_abandoned_at_the_deadline(mods) -> None:
    _, fetch, _ = mods
    with pytest.raises(fetch.FetchError, match="timed out"):
        fetch.read(io.BytesIO(b"x" * 10), deadline=0)
