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
import urllib.error
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
    for name in ("story", "story_fetch", "story_page", "story_sources", "story_model"):
        sys.modules.pop(name, None)
    story = importlib.import_module("story")
    index, cache = tmp_path / "stories", tmp_path / "cache"
    index.mkdir()
    cache.mkdir()
    (index / f"{DAY}.json").write_text(json.dumps([STORY]))
    for attr, value in (("INDEX", index), ("CACHE", cache), ("LOGIN", LOGIN)):
        monkeypatch.setattr(story, attr, value)
    monkeypatch.setattr(story, "DESK", story.Desk())
    monkeypatch.setattr(story, "HEALTH", sys.modules["story_sources"].Health(cache / "health.json"))
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


def test_sources_are_read_in_order_skipping_failing_outlets(mods, monkeypatch) -> None:
    story, fetch, _ = mods
    sources_mod = sys.modules["story_sources"]
    blocked = "https://blocked.example/a"
    for _ in range(sources_mod.FAILURES):
        story.HEALTH.record(blocked, "answered 403")
    sources = [
        {"name": "Blocked", "url": blocked},
        {"name": "Down", "url": "https://down.example/a"},
        {"name": "One", "url": "https://one.example/a"},
        {"name": "Two", "url": "https://two.example/a"},
        {"name": "Three", "url": "https://three.example/a"},
    ]

    def fake_fetch(url: str) -> str:
        if "down" in url:
            msg = "timed out"
            raise fetch.FetchError(msg)
        return f"text of {url}"

    monkeypatch.setattr(fetch, "fetch_text", fake_fetch)
    read, notes = sources_mod.gather(sources, story.HEALTH)
    assert [s["name"] for s, _ in read] == ["One", "Two"]
    assert any("Blocked (skipped" in n for n in notes)
    assert "Down (timed out)" in notes
    health = story.HEALTH.load()
    assert health["down.example"]["streak"] == 1
    assert health["one.example"]["ok"] == 1


def test_a_written_story_records_its_timings(mods, monkeypatch) -> None:
    story, fetch, _ = mods
    monkeypatch.setattr(fetch, "fetch_text", lambda url: f"text of {url}")
    model = sys.modules["story_model"]
    monkeypatch.setattr(model, "complete", lambda _m: ("First.\n\nSecond.", {"model": "m"}))
    written = story.write(STORY)
    assert written["paragraphs"] == ["First.", "Second."]
    assert {"fetch_seconds", "model_seconds", "input_chars", "output_chars"} <= written.keys()


def test_captions_and_calls_to_action_are_dropped(mods) -> None:
    _, fetch, _ = mods
    body = "word " * 20
    html = (
        f"<article><p>{body}news</p><p>Delegates arrive. Brendan Smialowski/AFP via Getty Images "
        f"hide caption</p><p>Sign up for our newsletter to get {body}</p>"
        f"<p>Voters were asked to sign up to vote early, {body}</p></article>"
    )
    kept = fetch.article_text(html.encode()).split("\n\n")
    assert kept == [
        f"{body.strip()} news",
        f"Voters were asked to sign up to vote early, {body.strip()}",
    ]


KEY = "sk-test-secret-key"


def reply(content: object = "A story.", finish: str = "stop", **message: object) -> bytes:
    """A chat-completions reply body."""
    body = {
        "choices": [{"finish_reason": finish, "message": {"content": content, **message}}],
        "usage": {"completion_tokens": 50, "completion_tokens_details": {"reasoning_tokens": 0}},
    }
    return json.dumps(body).encode()


@pytest.fixture
def model(mods, monkeypatch, tmp_path: Path):
    """story_model with a credential file and a scripted opener; `.sent` records requests."""
    del mods  # loaded for its side effect: fresh modules on sys.path
    module = sys.modules["story_model"]
    (tmp_path / "deepseek-api-key").write_text(KEY + "\n")
    monkeypatch.setenv("CREDENTIALS_DIRECTORY", str(tmp_path))
    monkeypatch.setattr(module, "RETRY_AFTER", 0)
    monkeypatch.setattr(module, "sent", [], raising=False)
    monkeypatch.setattr(module, "script", [], raising=False)

    class Opener:
        def open(self, request, timeout):
            module.sent.append((request, timeout))
            outcome = module.script.pop(0)
            if isinstance(outcome, int):
                raise urllib.error.HTTPError(request.full_url, outcome, "x", Message(), None)
            return io.BytesIO(outcome)

    monkeypatch.setattr(module, "OPENER", Opener())
    return module


def test_the_model_is_asked_with_thinking_off_and_the_key_from_the_credential(model) -> None:
    model.script = [reply()]
    text, facts = model.complete("Write it.")
    request, timeout = model.sent[0]
    body = json.loads(request.data)
    assert text == "A story."
    assert body["thinking"] == {"type": "disabled"}
    assert request.full_url == "https://api.deepseek.com/chat/completions"
    assert request.get_header("Authorization") == f"Bearer {KEY}"
    assert timeout == model.TIMEOUT
    assert facts["reasoning_tokens"] == 0
    assert facts["reasoning_returned"] is False


@pytest.mark.parametrize(
    ("script", "reason"),
    [
        ([reply(finish="length")], "cut off"),
        ([reply(content="  ")], "empty story"),
        ([reply(content=None)], "empty story"),
        ([b"not json"], "not JSON"),
        ([b'{"choices": []}'], "no choices"),
        ([401], "answered 401"),
        ([503, 503], "answered 503"),
    ],
    ids=["truncated", "blank", "null", "not-json", "no-choices", "unauthorised", "down-twice"],
)
def test_an_unusable_reply_is_an_error_that_never_shows_the_key(model, script, reason) -> None:
    model.script = list(script)
    with pytest.raises(model.ModelError, match=reason) as caught:
        model.complete("Write it.")
    assert KEY not in str(caught.value)


def test_a_transient_failure_is_retried_once_and_a_bad_request_is_not(model) -> None:
    model.script = [429, reply()]
    assert model.complete("Write it.")[0] == "A story."
    assert len(model.sent) == 2
    model.sent.clear()
    model.script = [400, reply()]
    with pytest.raises(model.ModelError):
        model.complete("Write it.")
    assert len(model.sent) == 1


def test_returned_reasoning_is_reported_and_not_served(model) -> None:
    model.script = [reply(content="The story.", reasoning_content="Let me think...")]
    text, facts = model.complete("Write it.")
    assert text == "The story."
    assert facts["reasoning_returned"] is True


@pytest.mark.usefixtures("mods")
def test_redirects_are_refused() -> None:
    module = sys.modules["story_model"]
    handler = module.NoRedirects()
    assert (
        handler.redirect_request(None, None, 302, "Found", {}, "https://elsewhere.example/") is None
    )
