"""One chat completion from DeepSeek, with thinking off, for the /story service.

The key reaches the service through systemd's LoadCredential= as the file
`deepseek-api-key` in $CREDENTIALS_DIRECTORY; it is read per call and never
logged, echoed in an error, or put in the environment. The host is fixed,
proxies from the environment are ignored and redirects are refused, so the
key goes only to the provider. A reply is accepted only when it is complete
(`finish_reason` "stop") and non-empty; any reasoning the provider returns is
reported, never served. Standard library only.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

URL = "https://api.deepseek.com/chat/completions"
MODEL = os.environ.get("STORY_MODEL", "deepseek-flash")
KEY_NAME = "deepseek-api-key"
TIMEOUT = 30
MAX_TOKENS = 1200
MAX_REPLY_BYTES = 1024 * 1024
RETRY_AFTER = 2.0
RETRYABLE = {429, 500, 502, 503, 504}
SYSTEM = "You write news stories for a private newspaper. Follow the instructions exactly."


class ModelError(Exception):
    """A reply that could not be used, with a reason safe to show."""


class NoRedirects(urllib.request.HTTPRedirectHandler):
    """Refuse every redirect, so the Authorization header never leaves the fixed host."""

    def redirect_request(self, *args: object, **kwargs: object) -> None:
        """Follow nothing."""
        del args, kwargs


OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirects())


def key_file() -> Path:
    """Where systemd put the key for this service."""
    return Path(os.environ.get("CREDENTIALS_DIRECTORY", "/nonexistent")) / KEY_NAME


def attempt(body: bytes) -> tuple[bytes | None, bool, str]:
    """One request: (raw reply, or None with whether to retry and why)."""
    request = urllib.request.Request(  # noqa: S310 -- URL is the fixed https constant above
        URL,
        body,
        {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key_file().read_text(encoding='utf-8').strip()}",
        },
    )
    try:
        with OPENER.open(request, timeout=TIMEOUT) as resp:
            return resp.read(MAX_REPLY_BYTES + 1), False, ""
    except urllib.error.HTTPError as exc:
        return None, exc.code in RETRYABLE, f"DeepSeek answered {exc.code}"
    except (OSError, urllib.error.URLError) as exc:
        return None, True, f"DeepSeek did not answer ({exc.__class__.__name__})"


def post(body: bytes) -> dict:
    """The provider's JSON reply to one request, or ModelError; retries once when transient."""
    raw, transient, reason = attempt(body)
    if raw is None and transient:
        time.sleep(RETRY_AFTER)
        raw, transient, reason = attempt(body)
    if raw is None:
        raise ModelError(reason)
    if len(raw) > MAX_REPLY_BYTES:
        msg = "DeepSeek's reply was too large"
        raise ModelError(msg)
    try:
        return json.loads(raw)
    except ValueError as exc:
        msg = "DeepSeek's reply was not JSON"
        raise ModelError(msg) from exc


def complete(message: str) -> tuple[str, dict]:
    """(story text, facts about the call) for one message, or ModelError."""
    body = json.dumps(
        {
            "model": MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": message},
            ],
            "thinking": {"type": "disabled"},
            "max_tokens": MAX_TOKENS,
            "stream": False,
        }
    ).encode()
    reply = post(body)
    choices = reply.get("choices") if isinstance(reply, dict) else None
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        msg = "DeepSeek's reply had no choices"
        raise ModelError(msg)
    choice: dict = choices[0]
    message_out = choice.get("message")
    if not isinstance(message_out, dict):
        msg = "DeepSeek's reply had no message"
        raise ModelError(msg)
    if choice.get("finish_reason") != "stop":
        msg = f"the story was cut off ({choice.get('finish_reason')})"
        raise ModelError(msg)
    text = message_out.get("content")
    if not isinstance(text, str) or not text.strip():
        msg = "DeepSeek returned an empty story"
        raise ModelError(msg)
    usage = reply.get("usage")
    usage = usage if isinstance(usage, dict) else {}
    details = usage.get("completion_tokens_details")
    reasoning_tokens = details.get("reasoning_tokens", 0) if isinstance(details, dict) else 0
    reasoning = message_out.get("reasoning_content")
    facts = {
        "model": MODEL,
        "completion_tokens": usage.get("completion_tokens"),
        "reasoning_tokens": reasoning_tokens,
        "reasoning_returned": bool(reasoning),
    }
    return text, facts
