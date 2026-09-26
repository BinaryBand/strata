"""Fetch a news article and keep only its paragraph text.

Only public internet hosts are fetched: every address a host name resolves to
must be global unicast, and so must any IPv4 address an IPv6 address embeds;
the connection goes to the address that was checked (so a second DNS answer
cannot swap in a private one), and every redirect hop is checked again.
Standard library only.
"""

from __future__ import annotations

import http.client
import ipaddress
import re
import socket
import ssl
import time
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

TIMEOUT = 15
MAX_BYTES = 2 * 1024 * 1024
MAX_REDIRECTS = 3
MAX_TEXT = 5_000  # news puts the facts first; the tail adds tokens, not substance
MAX_URL = 2000
DEADLINE = 45  # seconds for one source, all redirects and reads included
PORTS = {"http": 80, "https": 443}
USER_AGENT = "Mozilla/5.0 (compatible; DailySeekStoryDesk/1.0)"
# IPv6 prefixes whose low 32 bits are an IPv4 address: compatible, mapped,
# translated (SIIT) and the NAT64 well-known prefix. `is_global` passes some of
# them whatever IPv4 address they carry.
EMBEDS_V4 = tuple(
    ipaddress.ip_network(n) for n in ("::/96", "::ffff:0:0/96", "::ffff:0:0:0/96", "64:ff9b::/96")
)
# Never a public web host, though `is_global` passes each on some CPython
# release, 3.12.3 included: the deprecated 6to4 relay anycast, IETF protocol
# assignments, local-use NAT64, 6to4, documentation, deprecated site-local,
# SRv6 and the dummy prefix.
NOT_HOSTS = tuple(
    ipaddress.ip_network(n)
    for n in (
        *("192.88.99.0/24", "192.0.0.0/24", "64:ff9b:1::/48", "2002::/16", "3fff::/20"),
        *("fec0::/10", "5f00::/16", "100:0:0:1::/64"),
    )
)


class FetchError(Exception):
    """A source that could not be read, with the reason."""


def embedded_v4(ip: ipaddress.IPv6Address) -> ipaddress.IPv4Address | None:
    """The IPv4 address an IPv6 address carries, if it carries one."""
    if ip.sixtofour:
        return ip.sixtofour
    if ip.teredo:
        return ip.teredo[1]
    if any(ip in net for net in EMBEDS_V4):
        return ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
    return None


def public(address: str) -> bool:
    """True for a global unicast address whose embedded IPv4 address, if any, is one too."""
    ip = ipaddress.ip_address(address.split("%", 1)[0])
    if ip.is_multicast or not ip.is_global or any(ip in net for net in NOT_HOSTS):
        return False
    inner = embedded_v4(ip) if isinstance(ip, ipaddress.IPv6Address) else None
    return inner is None or public(str(inner))


def public_address(host: str, port: int) -> str:
    """One address for host, after checking that every address it resolves to is public."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        msg = f"cannot resolve {host}"
        raise FetchError(msg) from exc
    addresses = [str(info[4][0]) for info in infos]
    if not addresses or not all(public(a) for a in addresses):
        msg = f"{host} is not a public internet host"
        raise FetchError(msg)
    return addresses[0]


class PinnedHTTPS(http.client.HTTPSConnection):
    """HTTPS to a checked address, with the certificate verified for the host name."""

    def __init__(self, host: str, address: str) -> None:
        """Connect to `address`, presenting and verifying `host`."""
        super().__init__(
            host, PORTS["https"], timeout=TIMEOUT, context=ssl.create_default_context()
        )
        self.address = address

    def connect(self) -> None:
        """Open the socket to the checked address, then wrap it for the host name."""
        sock = socket.create_connection((self.address, self.port), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)  # ty: ignore[unresolved-attribute]


class PinnedHTTP(http.client.HTTPConnection):
    """Plain HTTP to a checked address."""

    def __init__(self, host: str, address: str) -> None:
        """Connect to `address`, sending `host` as the Host header."""
        super().__init__(host, PORTS["http"], timeout=TIMEOUT)
        self.address = address

    def connect(self) -> None:
        """Open the socket to the checked address."""
        self.sock = socket.create_connection((self.address, self.port), self.timeout)


def checked(url: str) -> tuple[str, str, str]:
    """(scheme, host, path and query) of an http(s) URL on its standard port, or FetchError."""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as exc:
        msg = "malformed address"
        raise FetchError(msg) from exc
    if (
        len(url) > MAX_URL
        or parts.scheme not in PORTS
        or not parts.hostname
        or "@" in parts.netloc
        or port not in (None, PORTS[parts.scheme])
    ):
        msg = "only http(s) on the standard port, with no login, is fetched"
        raise FetchError(msg)
    return (
        parts.scheme,
        parts.hostname,
        (parts.path or "/") + (f"?{parts.query}" if parts.query else ""),
    )


def read(resp: http.client.HTTPResponse, deadline: float) -> bytes:
    """The body, up to MAX_BYTES + 1 bytes, abandoned at the deadline."""
    chunks, size = [], 0
    while size <= MAX_BYTES:
        if time.monotonic() > deadline:
            msg = "timed out"
            raise FetchError(msg)
        chunk = resp.read(64 * 1024)
        if not chunk:
            break
        chunks.append(chunk)
        size += len(chunk)
    return b"".join(chunks)


def get(url: str, deadline: float) -> tuple[int, dict[str, str], bytes]:
    """(status, lower-cased headers, body) for one GET, no redirects followed."""
    scheme, host, path = checked(url)
    address = public_address(host, PORTS[scheme])
    conn = (PinnedHTTPS if scheme == "https" else PinnedHTTP)(host, address)
    try:
        conn.request("GET", path, headers={"User-Agent": USER_AGENT, "Accept": "text/html"})
        resp = conn.getresponse()
        headers = {k.lower(): v for k, v in resp.getheaders()}
        body = read(resp, deadline)
    except (OSError, http.client.HTTPException) as exc:
        msg = f"{host}: {exc.__class__.__name__}"
        raise FetchError(msg) from exc
    finally:
        conn.close()
    return resp.status, headers, body


def page(url: str) -> bytes:
    """The HTML at url, following up to MAX_REDIRECTS redirects, each one checked."""
    deadline = time.monotonic() + DEADLINE
    for _ in range(MAX_REDIRECTS + 1):
        status, headers, body = get(url, deadline)
        if status in (301, 302, 303, 307, 308) and "location" in headers:
            url = urljoin(url, headers["location"])
            continue
        if status != 200:  # noqa: PLR2004 -- HTTP OK
            msg = f"{urlsplit(url).hostname} answered {status}"
            raise FetchError(msg)
        if "html" not in headers.get("content-type", ""):
            msg = "not an HTML page"
            raise FetchError(msg)
        if len(body) > MAX_BYTES:
            msg = "page too large"
            raise FetchError(msg)
        return body
    msg = "too many redirects"
    raise FetchError(msg)


# Captions, credits and calls to action that sit in <p> elements beside the story.
JUNK = re.compile(
    r"hide caption|toggle caption|getty images|image source|advertisement|all rights reserved"
    r"|sign up (for|to) (our|the)|subscribe (to|now|today)|our newsletter|download (the|our) app"
    r"|^read more|^click here|^related:",
    re.IGNORECASE,
)


class Paragraphs(HTMLParser):
    """The text of every <p>, noting which ones sit inside an <article>."""

    SKIP = frozenset({"script", "style", "noscript", "template", "svg"})

    def __init__(self) -> None:
        """Start with no paragraphs."""
        super().__init__(convert_charrefs=True)
        self.all: list[str] = []
        self.in_article: list[str] = []
        self.article = 0
        self.skip = 0
        self.current: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list) -> None:
        """Track article, skipped and paragraph elements."""
        del attrs
        if tag == "article":
            self.article += 1
        elif tag in self.SKIP:
            self.skip += 1
        elif tag == "p":
            self.end_paragraph()
            self.current = []

    def handle_endtag(self, tag: str) -> None:
        """Close what the tag ends."""
        if tag == "article":
            self.end_paragraph()
            self.article = max(0, self.article - 1)
        elif tag in self.SKIP:
            self.skip = max(0, self.skip - 1)
        elif tag == "p":
            self.end_paragraph()

    def handle_data(self, data: str) -> None:
        """Collect text inside a paragraph."""
        if self.current is not None and not self.skip:
            self.current.append(data)

    def end_paragraph(self) -> None:
        """Finish the open paragraph, if any."""
        if self.current is not None:
            text = " ".join("".join(self.current).split())
            if len(text) > 40 and not JUNK.search(text):  # noqa: PLR2004 -- drop short bits
                self.all.append(text)
                if self.article:
                    self.in_article.append(text)
        self.current = None


def article_text(html: bytes) -> str:
    """The article's paragraphs as plain text, capped at MAX_TEXT characters."""
    parser = Paragraphs()
    parser.feed(html.decode("utf-8", errors="replace"))
    parser.close()
    parser.end_paragraph()
    chosen = parser.in_article or parser.all
    return "\n\n".join(chosen)[:MAX_TEXT]


def fetch_text(url: str) -> str:
    """The article text at url, or FetchError."""
    text = article_text(page(url))
    if len(text) < 200:  # noqa: PLR2004 -- a paywall, consent wall or empty shell
        msg = "no article text found"
        raise FetchError(msg)
    return text
