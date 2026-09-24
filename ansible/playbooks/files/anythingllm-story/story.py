"""Full stories for The Daily Seek, written by DeepSeek when a headline is first opened.

Deployed by strata's services.enable_anythingllm_story runbook and mounted at
/story on the site's port by `tailscale serve`. Like /review it listens on an
owner-only Unix socket and serves only STORY_LOGIN, the one tailnet login
Tailscale stamps on the request. `/story/<day>/<n>` is the n-th story of that
day's edition in the list the site builder publishes. The first GET queues
the story: one of WORKERS workers reads two of its sources (story_sources
picks and fetches them, skipping outlets that keep failing), sends their text
to DeepSeek with thinking off (story_model) for a short story, and caches
the result with its timings; until then the reader sees a
page that refreshes itself. HEAD and prefetches never start a story, and at most DAILY_CAP stories
are written per UTC day, counted when a story is queued. Cached stories are
kept for KEEP_DAYS days. Standard library only.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import queue
import re
import socketserver
import threading
import time
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import story_model
import story_page
import story_sources

LOGIN = os.environ.get("STORY_LOGIN", "")
SOCKET = os.environ.get("STORY_SOCKET", "/run/anythingllm-story/story.sock")
INDEX = Path(os.environ.get("STORY_INDEX", "/srv/anythingllm/site-public/stories"))
CACHE = Path(os.environ.get("STORY_CACHE", "/srv/anythingllm/story-cache"))
DAILY_CAP = int(os.environ.get("STORY_DAILY_CAP", "30"))
KEEP_DAYS = 30
WORKERS = 2
MAX_QUEUE = 5
MAX_STORY_CHARS = 20_000
PATH = re.compile(r"/([0-9]{4}-[0-9]{2}-[0-9]{2})/([0-9]{1,2})/?")
THINKING = re.compile(r"<think>.*?</think>", re.DOTALL)
INSTRUCTIONS = """Write a news story of three or four short paragraphs, about 250 words in all,
from the source articles below.
- Use only facts the sources state. Where they differ, say so and name each outlet.
- Attribute claims to their outlet by name, for example "according to NPR".
- Write in your own words; quote at most a short phrase.
- Plain text only: no headline, no markdown, no lists, no links.
- Separate paragraphs with a blank line.
"""


class StoryError(Exception):
    """A story that could not be written, with the reason to show."""


class Desk:
    """Which stories are queued, which failed, and today's count, behind one lock."""

    def __init__(self) -> None:
        """Start idle."""
        self.lock = threading.Lock()
        self.work: queue.Queue[tuple[str, str, dict]] = queue.Queue(MAX_QUEUE)
        self.pending: set[str] = set()
        self.failed: dict[str, str] = {}

    def spent_today(self, *, add: bool) -> int:
        """Stories started today, counting one more when `add`; kept across restarts."""
        today = dt.datetime.now(dt.UTC).date().isoformat()
        path = CACHE / "spend.json"
        try:
            record = json.loads(path.read_text())
        except (OSError, ValueError):
            record = {}
        count = record.get("count", 0) if record.get("day") == today else 0
        if add:
            count += 1
            save(path, {"day": today, "count": count})
        return count

    def request(self, key: str, day: str, story: dict, *, retry: bool) -> tuple[str, str]:
        """('waiting' | 'failed', reason) after queueing the story if it may start now."""
        with self.lock:
            if key in self.pending:
                return "waiting", ""
            if retry:
                self.failed.pop(key, None)
            if key in self.failed:
                return "failed", self.failed[key]
            if self.spent_today(add=False) >= DAILY_CAP:
                return "failed", f"the daily limit of {DAILY_CAP} stories is reached"
            try:
                self.work.put_nowait((key, day, story))
            except queue.Full:
                return "failed", "too many stories are being written; try again shortly"
            self.pending.add(key)
            self.spent_today(add=True)
            return "waiting", ""

    def run(self) -> None:
        """Write queued stories one at a time, forever."""
        while True:
            key, day, story = self.work.get()
            try:
                save(CACHE / f"{key}.json", {"day": day, **write(story)})
                prune()
            except Exception as exc:  # noqa: BLE001 -- the worker must outlive any one story
                reason = str(exc) if isinstance(exc, StoryError) else exc.__class__.__name__
                with self.lock:
                    self.failed[key] = reason
            finally:
                with self.lock:
                    self.pending.discard(key)


DESK = Desk()
HEALTH = story_sources.Health(CACHE / "health.json")


def save(path: Path, data: dict) -> None:
    """Write JSON atomically."""
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def prune() -> None:
    """Remove cached stories older than KEEP_DAYS and temporary files left by a crash."""
    cutoff = dt.datetime.now(dt.UTC).timestamp() - KEEP_DAYS * 86400
    for path in CACHE.glob("*"):
        try:
            if path.name.endswith(".tmp") or (
                path.name not in ("spend.json", "health.json") and path.stat().st_mtime < cutoff
            ):
                path.unlink()
        except OSError:
            continue


def cached(key: str) -> dict | None:
    """The cached story for key, or None when it is missing or damaged."""
    try:
        data = json.loads((CACHE / f"{key}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    ok = (
        isinstance(data, dict)
        and isinstance(data.get("paragraphs"), list)
        and isinstance(data.get("notes"), list)
        and all(isinstance(p, str) for p in data["paragraphs"] + data["notes"])
    )
    return data if ok else None


def lookup(day: str, n: int) -> dict | None:
    """The n-th story of the day's edition, as the builder published it."""
    try:
        stories = json.loads((INDEX / f"{day}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return stories[n - 1] if 1 <= n <= len(stories) else None


def story_key(story: dict) -> str:
    """A cache key that changes when the headline or its sources do."""
    ident = json.dumps([story["title"], [s["url"] for s in story["sources"]]])
    return hashlib.sha256(ident.encode()).hexdigest()[:32]


def write(story: dict) -> dict:
    """The written story -- paragraphs, sources not read, timings -- or StoryError."""
    started = time.monotonic()
    read, notes = story_sources.gather(story["sources"], HEALTH)
    fetched = time.monotonic()
    if not read:
        msg = "no source could be read: " + "; ".join(notes)
        raise StoryError(msg)
    texts = [f"--- {source['name']} ({source['url']})\n{text}" for source, text in read]
    message = "\n\n".join(
        [INSTRUCTIONS, f"Headline: {story['title']}", f"Feed summary: {story['summary']}", *texts]
    )
    try:
        reply, facts = story_model.complete(message)
    except story_model.ModelError as exc:
        raise StoryError(str(exc)) from exc
    return {
        **facts,
        "paragraphs": paragraphs(reply),
        "notes": notes,
        "fetch_seconds": round(fetched - started, 1),
        "model_seconds": round(time.monotonic() - fetched, 1),
        "input_chars": len(message),
        "output_chars": len(reply),
    }


def paragraphs(text: str) -> list[str]:
    """The reply as plain paragraphs: reasoning, headings and emphasis marks removed."""
    text = THINKING.sub("", text)[:MAX_STORY_CHARS]
    out = []
    for block in re.split(r"\n\s*\n", text):
        line = " ".join(block.split()).replace("**", "")
        if line and not line.startswith("#"):
            out.append(line)
    if not out:
        msg = "DeepSeek returned an empty story"
        raise StoryError(msg)
    return out


class Handler(BaseHTTPRequestHandler):
    """GET and HEAD for the one allowed tailnet login; everything else refused."""

    server_version = "story"
    sys_version = ""

    def address_string(self) -> str:
        """A Unix socket has no client address."""
        return "unix"

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 -- http.server's name
        """Keep no access log."""
        del format, args

    def respond(self, status: int, body: str, *, send_body: bool = True) -> None:
        """Send `body` with the site's headers."""
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        for name, value in story_page.HEADERS.items():
            self.send_header(name, value)
        self.end_headers()
        if send_body:
            self.wfile.write(data)

    def route(self, *, may_start: bool) -> tuple[int, str]:
        """(status, body) for this request, after the login check."""
        logins = self.headers.get_all("Tailscale-User-Login") or []
        if not LOGIN or logins != [LOGIN]:
            return 403, "Forbidden."
        url = urlparse(self.path)
        match = PATH.fullmatch(url.path)
        story = lookup(match[1], int(match[2])) if match else None
        if not match or story is None:
            return 404, "No such story."
        day, key = match[1], story_key(story)
        here = f"/story/{day}/{int(match[2])}"
        written = cached(key)
        if written:
            return 200, story_page.story_page(day, story, written["paragraphs"], written["notes"])
        purpose = self.headers.get("Sec-Purpose", "") + self.headers.get("Purpose", "")
        if not may_start or "prefetch" in purpose:
            return 503, "Open the story to have it written."
        return self.start(day, story, here, retry="retry" in parse_qs(url.query))

    def start(self, day: str, story: dict, here: str, *, retry: bool) -> tuple[int, str]:
        """Queue an unwritten story and say how it stands."""
        state, reason = DESK.request(story_key(story), day, story, retry=retry)
        if state == "waiting":
            return 200, story_page.waiting_page(day, story, here)
        return 200, story_page.fallback_page(day, story, reason, f"{here}?retry=1")

    def do_GET(self) -> None:
        """Serve a story, starting it if needed."""
        self.respond(*self.route(may_start=True))

    def do_HEAD(self) -> None:
        """Serve a story's headers; never starts one."""
        self.respond(*self.route(may_start=False), send_body=False)

    def refuse(self) -> None:
        """Refuse every other method."""
        self.respond(405, "Read-only.")

    do_POST = do_PUT = do_DELETE = do_PATCH = refuse  # noqa: N815 -- http.server's naming


class UnixHTTPServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    """A threaded HTTP server on a Unix socket."""

    daemon_threads = True

    def get_request(self) -> tuple:
        """Accept a connection, reporting a placeholder client address."""
        request, _ = super().get_request()
        return request, ("unix", 0)


def main() -> None:
    """Serve on SOCKET until stopped."""
    if not LOGIN or not story_model.key_file().is_file():
        message = "STORY_LOGIN and the deepseek-api-key credential must be set; refusing to serve."
        raise SystemExit(message)
    CACHE.mkdir(parents=True, exist_ok=True)
    prune()
    for _ in range(WORKERS):
        threading.Thread(target=DESK.run, daemon=True).start()
    Path(SOCKET).unlink(missing_ok=True)
    old = os.umask(0o177)  # the socket is created 0600: this account and root only
    try:
        server = UnixHTTPServer(SOCKET, Handler)
    finally:
        os.umask(old)
    server.serve_forever()


if __name__ == "__main__":
    main()
