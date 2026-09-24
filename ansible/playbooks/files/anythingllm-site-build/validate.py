"""Validate the agent's site data and translate it into Zola content.

The agent writes small TOML data files under its site folder; nothing it
writes reaches Zola directly. Each file is read without following symlinks,
checked against a fixed schema, and rewritten here as Zola content whose front
matter this module alone composes -- so the agent can never pick a template,
set a redirect or smuggle raw HTML into a page. Standard library only.

    news/editions/YYYY-MM-DD/NN-slug.toml   stories, one or several [[story]] tables
    news/editions/YYYY-MM-DD/edition.toml   date, feeds_total, feed_errors, briefs;
                                            written last: an edition is built only
                                            once it exists, so readers never see a
                                            half-written one
    news/style.css                          the paper's stylesheet
    <publication>/publication.toml          title, description
    <publication>/<slug>.md                 +++ title, description +++ Markdown body
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import stat
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

REGIONS = ("America", "Europe & Sweden", "World")
MAX_DATA_BYTES = 16 * 1024
MAX_PAGE_BYTES = 64 * 1024
MAX_CSS_BYTES = 128 * 1024
MAX_STORIES = 30
MAX_SOURCES = 10
MAX_EDITIONS = 1000
MAX_PUBLICATIONS = 20
MAX_PAGES = 200
STORY_FILE = re.compile(r"[0-9]{2}-[a-z0-9][a-z0-9-]{0,60}\.toml")
PAGE_FILE = re.compile(r"[a-z0-9][a-z0-9-]{0,60}\.md")
PUBLICATION = re.compile(r"[a-z0-9][a-z0-9-]{0,40}")
EDITION = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
URL = re.compile(r"https?://[^\s\"'<>\\]{1,2000}")
# A raw HTML tag, comment, declaration or autolink in a Markdown body.
RAW_HTML = re.compile(r"<\s*[A-Za-z!/?]")
# Template syntax: Zola is told never to template content, and this is a second wall.
TEMPLATE = re.compile(r"\{[{%#]")
# The scheme of an inline link or image target, or of a reference definition.
LINK_SCHEME = re.compile(
    r"\]\(\s*<?\s*([A-Za-z][A-Za-z0-9+.-]*)\s*:"  # [text](scheme:... and ![alt](scheme:...
    r"|^[ \t]*\[[^\]]+\]:\s*<?\s*([A-Za-z][A-Za-z0-9+.-]*)\s*:",  # [ref]: scheme:...
    re.MULTILINE,
)
SAFE_SCHEMES = {"http", "https", "mailto"}
RESERVED = {"news", "previous", "archive"}


class Invalid(Exception):  # noqa: N818 -- reads as "raise Invalid(...)"
    """A file that is skipped, with the reason to report."""


@dataclass
class Result:
    """Zola content to write, the stylesheet, and every skipped file with its reason."""

    files: dict[str, str] = field(default_factory=dict)
    css: bytes | None = None
    rejected: list[tuple[str, str]] = field(default_factory=list)
    waiting: list[str] = field(default_factory=list)
    editions: int = 0
    stories: dict[str, list[dict]] = field(default_factory=dict)


def read_no_follow(root: Path, rel: str, limit: int) -> bytes:
    """root/rel's bytes; refuses a symlink at any step, a non-regular file, excess size."""
    parts = rel.split("/")
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in parts[:-1]:
            nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = nxt
        leaf = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    except OSError as exc:
        msg = "cannot be opened (a link, or not a file)"
        raise Invalid(msg) from exc
    finally:
        os.close(fd)
    with os.fdopen(leaf, "rb") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            msg = "not a regular file"
            raise Invalid(msg)
        data = handle.read(limit + 1)
    if len(data) > limit:
        msg = f"over {limit} bytes"
        raise Invalid(msg)
    return data


def load_toml(data: bytes) -> dict:
    """Parse TOML, or Invalid with the parser's reason."""
    try:
        return tomllib.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        msg = f"not valid TOML: {exc}"
        raise Invalid(msg) from exc


def keys(data: dict, required: set[str], optional: frozenset[str] | set[str] = frozenset()) -> None:
    """Require exactly these fields: every required one, and nothing unknown."""
    missing = required - data.keys()
    extra = data.keys() - required - optional
    if missing:
        msg = f"missing {', '.join(sorted(missing))}"
        raise Invalid(msg)
    if extra:
        msg = f"unknown field {', '.join(sorted(extra))}"
        raise Invalid(msg)


def text(value: object, name: str, most: int) -> str:
    """A non-empty string of at most `most` characters, stripped."""
    if not isinstance(value, str) or not value.strip() or len(value) > most:
        msg = f"{name} must be text of 1-{most} characters"
        raise Invalid(msg)
    return value.strip()


def texts(value: object, name: str, count: int, most: int) -> list[str]:
    """A list of at most `count` such strings."""
    if not isinstance(value, list) or len(value) > count:
        msg = f"{name} must be a list of at most {count} texts"
        raise Invalid(msg)
    return [text(v, name, most) for v in value]


def whole(value: object, name: str, low: int, high: int) -> int:
    """An integer (not a boolean) from low to high."""
    if not isinstance(value, int) or isinstance(value, bool) or not low <= value <= high:
        msg = f"{name} must be a whole number from {low} to {high}"
        raise Invalid(msg)
    return value


def toml_value(value: object) -> str:
    """A TOML literal for the plain values this module writes (JSON strings are TOML strings)."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        # Zola ends front matter at the next "+++", even inside a string; a "+"
        # written as an escape can never form one.
        return json.dumps(value, ensure_ascii=False).replace("+", "\\u002B")
    if isinstance(value, list):
        return "[" + ", ".join(toml_value(v) for v in value) + "]"
    if isinstance(value, dict):
        return "{ " + ", ".join(f"{k} = {toml_value(v)}" for k, v in value.items()) + " }"
    msg = f"cannot write {type(value).__name__}"
    raise TypeError(msg)


def front_matter(top: dict, extra: dict | None = None, body: str = "") -> str:
    """A Zola content file whose front matter this module alone composes."""
    lines = ["+++"] + [f"{k} = {toml_value(v)}" for k, v in top.items()]
    if extra:
        lines += ["[extra]"] + [f"{k} = {toml_value(v)}" for k, v in extra.items()]
    return "\n".join([*lines, "+++", body])


def table(value: object) -> dict:
    """`value` as a TOML table, or Invalid."""
    if not isinstance(value, dict):
        msg = "must be a [[story]] table"
        raise Invalid(msg)
    return value


def story(data: dict) -> dict:
    """A validated story, keyed the way the templates read it."""
    keys(data, {"headline", "region", "lead", "rank", "summary", "sources"})
    if data["region"] not in REGIONS:
        msg = f"region must be one of: {', '.join(REGIONS)}"
        raise Invalid(msg)
    if not isinstance(data["lead"], bool):
        msg = "lead must be true or false"
        raise Invalid(msg)
    sources = data["sources"]
    if not isinstance(sources, list) or not 1 <= len(sources) <= MAX_SOURCES:
        msg = f"sources must list 1-{MAX_SOURCES} sources"
        raise Invalid(msg)
    clean_sources = []
    for source in sources:
        if not isinstance(source, dict):
            msg = "each source must be { name = ..., url = ... }"
            raise Invalid(msg)
        keys(source, {"name", "url"})
        url = source["url"]
        if not isinstance(url, str) or not URL.fullmatch(url):
            msg = "each source url must be an http(s) address with no spaces or quotes"
            raise Invalid(msg)
        clean_sources.append({"name": text(source["name"], "source name", 80), "url": url})
    return {
        "title": text(data["headline"], "headline", 300),
        "region": data["region"],
        "lead": data["lead"],
        "rank": whole(data["rank"], "rank", 1, 99),
        "summary": text(data["summary"], "summary", 1000),
        "sources": clean_sources,
    }


def edition_meta(data: dict, day: str) -> dict:
    """A validated edition.toml for the folder named `day`."""
    keys(data, {"date", "feeds_total", "feed_errors"}, {"briefs"})
    if str(data["date"]) != day:
        msg = f"date must be {day}, the folder's name"
        raise Invalid(msg)
    return {
        "date": day,
        "feeds_total": whole(data["feeds_total"], "feeds_total", 0, 100),
        "feed_errors": texts(data["feed_errors"], "feed_errors", 50, 200),
        "briefs": texts(data.get("briefs", []), "briefs", 30, 300),
    }


def names(folder: Path) -> list[str]:
    """The entries of a folder, sorted."""
    return sorted(entry.name for entry in folder.iterdir())


def story_file(root: Path, rel: str, name: str) -> list[dict]:
    """The validated stories in root/rel -- one, or a [[story]] list -- or Invalid."""
    if not STORY_FILE.fullmatch(name):
        msg = "story files are named NN-slug.toml"
        raise Invalid(msg)
    data = load_toml(read_no_follow(root, rel, MAX_DATA_BYTES))
    if "story" not in data:
        return [story(data)]
    keys(data, {"story"})
    listed = data["story"]
    if not isinstance(listed, list) or not 1 <= len(listed) <= MAX_STORIES:
        msg = f"a file lists 1-{MAX_STORIES} [[story]] tables"
        raise Invalid(msg)
    found = []
    for number, entry in enumerate(listed, 1):
        try:
            found.append(story(table(entry)))
        except Invalid as exc:
            msg = f"story {number}: {exc}"
            raise Invalid(msg) from exc
    return found


def page_file(root: Path, rel: str, name: str) -> str:
    """The Zola content for the Markdown page at root/rel, or Invalid."""
    if not PAGE_FILE.fullmatch(name):
        msg = "pages are named slug.md"
        raise Invalid(msg)
    raw = read_no_follow(root, rel, MAX_PAGE_BYTES).decode("utf-8", errors="replace")
    _, sep, rest = raw.partition("+++")
    head, sep2, body = rest.partition("+++")
    if not raw.startswith("+++") or not sep or not sep2 or not head.strip():
        msg = 'a page starts with +++ title = "..." +++'
        raise Invalid(msg)
    meta = load_toml(head.encode())
    keys(meta, {"title"}, {"description"})
    why = unsafe_body(body)
    if why:
        raise Invalid(why)
    top = {"title": text(meta["title"], "title", 200), "template": "page.html"}
    if "description" in meta:
        top["description"] = text(meta["description"], "description", 300)
    return front_matter(top, None, body)


def unsafe_body(body: str) -> str | None:
    """Why a Markdown body is refused, or None when it is plain Markdown."""
    if RAW_HTML.search(body):
        return "raw HTML is not allowed in a page; use Markdown"
    if TEMPLATE.search(body):
        return "{{, {% and {# are not allowed in a page"
    for match in LINK_SCHEME.finditer(body):
        scheme = (match.group(1) or match.group(2) or "").lower()
        if scheme not in SAFE_SCHEMES:
            return f"links may only use http, https or mailto, not {scheme}:"
    return None


def edition(root: Path, day: str, result: Result, story_base: str) -> None:
    """Add the edition in news/editions/<day> to `result`, or record why it is skipped."""
    base = f"news/editions/{day}"
    if not (root / base / "edition.toml").exists():
        result.waiting.append(base)
        return
    try:
        dt.date.fromisoformat(day)
        meta = edition_meta(
            load_toml(read_no_follow(root, f"{base}/edition.toml", MAX_DATA_BYTES)), day
        )
    except (Invalid, ValueError) as exc:
        result.rejected.append((f"{base}/edition.toml", str(exc)))
        return
    stories: list[dict] = []
    for name in names(root / base):
        if name == "edition.toml":
            continue
        rel = f"{base}/{name}"
        try:
            stories += story_file(root, rel, name)
        except Invalid as exc:
            result.rejected.append((rel, str(exc)))
    leads = [s for s in stories if s["lead"]]
    if len(leads) != 1 or len(stories) > MAX_STORIES:
        why = f"needs exactly one lead story and at most {MAX_STORIES} stories"
        result.rejected.append((base, f"edition skipped: {why} (has {len(leads)} leads)"))
        return
    title = dt.date.fromisoformat(day).strftime("%A, %-d %B %Y")
    # Stories are data on the edition, not pages: an unrendered Zola page drops
    # out of its section, and a rendered one would be a stray page of its own.
    ordered = sorted(stories, key=lambda s: s["rank"])
    if story_base:  # the headline opens the story service's page instead of the source
        ordered = [{**s, "page": f"{story_base}/{day}/{n}"} for n, s in enumerate(ordered, 1)]
    result.stories[day] = ordered
    result.files[f"news/{day}/_index.md"] = front_matter(
        {"title": title, "template": "news/edition.html", "sort_by": "none"},
        {**meta, "stories": ordered},
    )
    result.editions += 1


def publication(root: Path, name: str, result: Result) -> None:
    """Add the publication folder `name` to `result`, recording every page it skips."""
    try:
        meta = load_toml(read_no_follow(root, f"{name}/publication.toml", MAX_DATA_BYTES))
        keys(meta, {"title"}, {"description"})
        top = {"title": text(meta["title"], "title", 120), "template": "section.html"}
        if "description" in meta:
            top["description"] = text(meta["description"], "description", 300)
    except Invalid as exc:
        result.rejected.append((f"{name}/publication.toml", str(exc)))
        return
    result.files[f"{name}/_index.md"] = front_matter(top)
    for page in names(root / name)[: MAX_PAGES + 1]:
        if page == "publication.toml":
            continue
        rel = f"{name}/{page}"
        try:
            result.files[rel] = page_file(root, rel, page)
        except Invalid as exc:
            result.rejected.append((rel, str(exc)))


def collect(root: Path, story_base: str = "") -> Result:
    """Everything valid under the agent's site folder, translated; the rest rejected."""
    result = Result()
    result.files["_index.md"] = front_matter({"title": "Publications", "template": "index.html"})
    result.files["news/_index.md"] = front_matter(
        {
            "title": "The Daily Seek",
            "description": "The day's news, each morning",
            "template": "news/front.html",
            "sort_by": "none",
        }
    )
    result.files["news/archive/_index.md"] = front_matter(
        {"title": "Archive", "template": "news/archive.html", "sort_by": "none"}
    )
    editions = root / "news" / "editions"
    if editions.is_dir() and not editions.is_symlink():
        for day in names(editions)[-MAX_EDITIONS:]:
            if (
                EDITION.fullmatch(day)
                and (editions / day).is_dir()
                and not (editions / day).is_symlink()
            ):
                edition(root, day, result, story_base)
            else:
                result.rejected.append(
                    (f"news/editions/{day}", "edition folders are named YYYY-MM-DD")
                )
    try:
        result.css = read_no_follow(root, "news/style.css", MAX_CSS_BYTES)
    except Invalid as exc:
        result.rejected.append(("news/style.css", str(exc)))
    publications = 0
    for name in names(root) if root.is_dir() else []:
        path = root / name
        if (
            name in RESERVED
            or not PUBLICATION.fullmatch(name)
            or path.is_symlink()
            or not path.is_dir()
        ):
            continue
        if (path / "publication.toml").exists() and publications < MAX_PUBLICATIONS:
            publication(root, name, result)
            publications += 1
    return result
