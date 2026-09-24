"""The HTML pages of the /story service, in The Daily Seek's look.

Every value is escaped here, and links come only from the builder's validated
source list. The page uses the site's stylesheet and class names. Standard
library only.
"""

from __future__ import annotations

import datetime as dt
from html import escape

HEADERS = {
    "Cache-Control": "no-cache",
    "Content-Security-Policy": "script-src 'none'; object-src 'none'; base-uri 'none'",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}
NAV = (
    ("Front page", "/news/"),
    ("America", "/news/#america"),
    ("Europe & Sweden", "/news/#europe-sweden"),
    ("World", "/news/#world"),
    ("Archive", "/news/archive/"),
)
FONTS = (
    "https://fonts.googleapis.com/css2?family=Libre+Franklin:wght@500;600"
    "&family=Newsreader:ital,opsz,wght@0,6..72,400..700;1,6..72,400"
    "&family=Playfair+Display:wght@900&display=swap"
)


def frame(title: str, dateline: str, body: str, *, refresh: str = "") -> str:
    """A whole page around `body`, already escaped; `refresh` is a URL to reload."""
    wait = f'<meta http-equiv="refresh" content="5; url={escape(refresh)}">\n' if refresh else ""
    nav = "".join(f'<li><a href="{href}">{escape(name)}</a></li>' for name, href in NAV)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<meta name="referrer" content="no-referrer">
{wait}<title>{escape(title)} - The Daily Seek</title>
<link rel="stylesheet" href="{escape(FONTS)}">
<link rel="stylesheet" href="/news/layout.css">
<link rel="stylesheet" href="/news/style.css">
</head>
<body>
<header class="site-header">
<div class="topbar wrap"><span>{escape(dateline)}</span><span>Full story</span></div>
<div class="masthead wrap"><p class="masthead__name"><a href="/news/">The Daily Seek</a></p></div>
<nav class="nav-bar" aria-label="Sections"><ul class="wrap">{nav}</ul></nav>
</header>
<main class="wrap">
{body}
</main>
<footer class="site-footer">
<div class="wrap">
<div class="site-footer__about">
<p class="site-footer__name">The Daily Seek</p>
<p>Written on request by the AnythingLLM agent from the articles listed under Sources. \
It can be wrong: read the originals for anything that matters.</p>
</div>
<ul class="site-footer__links"><li><a href="/news/">Front page</a></li>\
<li><a href="/news/archive/">Archive</a></li></ul>
</div>
</footer>
</body>
</html>
"""


def sources(story: dict) -> str:
    """The story's source links."""
    links = " · ".join(
        f'<a href="{escape(s["url"])}">{escape(s["name"])}</a>' for s in story["sources"]
    )
    return f'<p class="sources">Sources: {links}</p>'


def dateline(day: str) -> str:
    """The edition's date, written out."""
    return dt.date.fromisoformat(day).strftime("%A, %-d %B %Y")


def story_page(day: str, story: dict, paragraphs: list[str], notes: list[str]) -> str:
    """The written story."""
    text = "\n".join(f"<p>{escape(p)}</p>" for p in paragraphs)
    missing = (
        f'<aside class="notice"><p>Not read: {escape("; ".join(notes))}.</p></aside>'
        if notes
        else ""
    )
    body = f"""<article class="story">
<div class="photo" aria-hidden="true"><span>{escape(story["region"])}</span></div>
<p class="kicker">{escape(story["region"])}</p>
<h1 class="headline">{escape(story["title"])}</h1>
{sources(story)}
<div class="story__body">
{text}
</div>
{missing}
</article>"""
    return frame(story["title"], dateline(day), body)


def waiting_page(day: str, story: dict, here: str) -> str:
    """Shown while the story is being written; reloads `here`, which never carries ?retry."""
    body = f"""<article class="story">
<p class="kicker">{escape(story["region"])}</p>
<h1 class="headline">{escape(story["title"])}</h1>
<aside class="notice"><p>Writing this story from its sources. \
This usually takes a minute or two; the page refreshes by itself.</p></aside>
<p class="dek">{escape(story["summary"])}</p>
{sources(story)}
</article>"""
    return frame(story["title"], dateline(day), body, refresh=here)


def fallback_page(day: str, story: dict, reason: str, retry: str | None) -> str:
    """The feed summary and links, when the story could not be written."""
    again = f' <a href="{escape(retry)}">Try again</a>.' if retry else ""
    body = f"""<article class="story">
<p class="kicker">{escape(story["region"])}</p>
<h1 class="headline">{escape(story["title"])}</h1>
<aside class="notice notice--error">\
<p>The full story could not be written: {escape(reason)}.{again}</p></aside>
<p class="dek">{escape(story["summary"])}</p>
{sources(story)}
</article>"""
    return frame(story["title"], dateline(day), body)
