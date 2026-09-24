"""The file viewer: any file the agent can read, and an allowlist of others.

Text and Markdown are shown as written, TOML and JSON formatted, anything else
as its size, type and the first bytes in hex. Every value is escaped before
the formatter wraps it in markup. A news story file also shows what the site
builder made of it, and a file a scheduled task wrote names the task.
Standard library only.
"""

from __future__ import annotations

import datetime
import json
import tomllib

import review_content as content
import review_layout as ui
import review_tasks

HEX_BYTES = 256
KINDS = {".toml": "TOML", ".json": "JSON", ".md": "Markdown", ".css": "CSS", ".html": "HTML"}
BUILT_BY = {"site/FORMAT.md": "Placed by strata", "site/BUILD.md": "Written by the site builder"}


def kind_of(rel: str) -> str:
    """The file's type from its extension."""
    dot = rel.rfind(".")
    return KINDS.get(rel[dot:].lower(), "Text") if dot > rel.rfind("/") else "Text"


def is_binary(data: bytes) -> bool:
    """Whether data looks like something other than UTF-8 text."""
    if b"\x00" in data[:8192]:
        return True
    try:
        data[:8192].decode("utf-8")
    except UnicodeDecodeError as exc:
        return exc.start < 8188  # a character cut at the boundary is still text  # noqa: PLR2004
    return False


def hexdump(data: bytes) -> str:
    """The first HEX_BYTES bytes as offset, hex and printable columns."""
    lines = []
    for at in range(0, min(len(data), HEX_BYTES), 16):
        chunk = data[at : at + 16]
        text = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)  # noqa: PLR2004
        lines.append(f"{at:08x}  {chunk.hex(' '):<47}  {text}")
    return "\n".join(lines)


def _value(value: object) -> str:  # noqa: PLR0911 -- one return per TOML type
    """A TOML value as highlighted, escaped markup."""
    if isinstance(value, str):
        if "\n" in value:
            return f'<span class="s">"""\n{ui.esc(value)}"""</span>'
        return f'<span class="s">{ui.esc(json.dumps(value, ensure_ascii=False))}</span>'
    if isinstance(value, bool):
        return f'<span class="v">{"true" if value else "false"}</span>'
    if isinstance(value, datetime.date | datetime.time):
        return f'<span class="v">{ui.esc(value.isoformat())}</span>'
    if isinstance(value, list):
        return "[" + ", ".join(_value(v) for v in value) + "]"
    if isinstance(value, dict):
        return (
            "{ "
            + ", ".join(
                f'<span class="k">{ui.esc(k)}</span> = {_value(v)}' for k, v in value.items()
            )
            + " }"
        )
    return f'<span class="v">{ui.esc(value)}</span>'


def toml_markup(data: dict, path: str = "") -> str:
    """A parsed TOML document laid out again: plain keys first, then tables."""
    lines = [
        f'<span class="k">{ui.esc(k)}</span> = {_value(v)}'
        for k, v in data.items()
        if not isinstance(v, dict)
        and not (isinstance(v, list) and v and all(isinstance(i, dict) for i in v))
    ]
    for key, value in data.items():
        name = f"{path}.{key}" if path else key
        if isinstance(value, dict):
            lines.append(f'\n<span class="v">[{ui.esc(name)}]</span>')
            lines.append(toml_markup(value, name))
        elif isinstance(value, list) and value and all(isinstance(i, dict) for i in value):
            for item in value:
                lines.append(f'\n<span class="v">[[{ui.esc(name)}]]</span>')
                lines.append(toml_markup(item, name))
    return "\n".join(line for line in lines if line)


def writer(rel: str) -> str:
    """'Written today 06:01 by Daily news digest' when a recent task run wrote rel."""
    inside = rel.removeprefix(f"{content.AGENT_DIR}/")
    for job in review_tasks.jobs(runs=30):
        for run in job.runs:
            if inside in run.writes or f"/{inside}" in {"/" + p.lstrip("/") for p in run.writes}:
                return f"Written {content.day_time(run.done or run.started)} by {job.name}"
    return ""


def build_check(rel: str) -> str:
    """For a news story file: whether the site builder took it, from its status file."""
    inside = rel.removeprefix(f"{content.AGENT_DIR}/site/")
    if not inside.startswith("news/editions/") or not rel.endswith(".toml"):
        return ""
    status = content.read_json("site-public/status.json")
    if not isinstance(status, dict):
        return ""
    edition = "/".join(inside.split("/")[:3])
    for item in content.as_list(status.get("rejected")):
        if isinstance(item, dict) and item.get("file") in (inside, edition):
            return ui.card(
                "Checked against FORMAT.md",
                f"<span>{ui.esc(item.get('reason'))}</span>",
                ui.pill("Skipped", "bad"),
            )
    if edition in {str(w) for w in content.as_list(status.get("waiting"))}:
        return ui.card(
            "Checked against FORMAT.md",
            "<span>The edition has no edition.toml yet, so the builder has not built it.</span>",
            ui.pill("Waiting", "warn"),
        )
    return ui.card(
        "Checked against FORMAT.md",
        "<span>The site builder took this file in its last build.</span>",
        ui.pill("Valid", "ok"),
    )


def body(rel: str, data: bytes, size: int) -> tuple[str, str]:  # noqa: PLR0911 -- one per format
    """(type label, markup) for the file's contents."""
    kind = kind_of(rel)
    if is_binary(data):
        return "Binary", ui.stats([ui.stat("Size", content.size_text(size))]) + ui.code(
            hexdump(data)
        )
    text = data.decode("utf-8", errors="replace")
    cut = '<span class="muted">Only the first 256 KB is shown.</span>' if size > len(data) else ""
    if rel.endswith("/plugin.json") and not content.in_agent_dir(rel):
        return "JSON · setup values hidden", ui.code(content.redact_manifest(text), big=True) + cut
    if kind == "TOML" and not cut:
        try:
            parsed = tomllib.loads(text)
        except tomllib.TOMLDecodeError as exc:
            return "TOML · not valid", ui.alert("warn", ui.esc(f"Not valid TOML: {exc}")) + ui.code(
                text, big=True
            )
        return "TOML · formatted", f'<pre class="code big">{toml_markup(parsed)}</pre>'
    if kind == "JSON" and not cut:
        try:
            return "JSON · formatted", ui.code(
                json.dumps(json.loads(text), indent=2, ensure_ascii=False), big=True
            )
        except ValueError:
            return "JSON · not valid", ui.code(text, big=True)
    return kind, ui.code(text, big=True) + cut


def file_view(prefix: str, rel: str) -> tuple[int, str]:
    """(status, main markup) for the viewer."""
    parts = [p for p in rel.split("/") if p]
    folder = "/".join(parts[:-1])
    crumb = ("Files", ui.href(prefix, "files", path=folder))
    if not content.viewable(rel):
        return 403, ui.header(
            parts[-1] if parts else "File", "Only its name and size are shown here.", crumb
        )
    try:
        data, st = content.read_bytes(rel)
    except content.ViewError as exc:
        return exc.status, ui.header(parts[-1] if parts else "File", ui.esc(str(exc)), crumb)
    label, markup = body(rel, data, st.st_size)
    inside = rel.removeprefix(f"{content.AGENT_DIR}/")
    pills = [
        ui.pill(BUILT_BY[inside])
        if inside in BUILT_BY
        else ui.pill("Agent-written", "accent")
        if content.AGENT_WRITTEN.fullmatch(rel)
        else "",
        ui.pill(label),
        ui.pill(content.size_text(st.st_size)),
    ]
    if content.in_agent_dir(rel):
        pills.append(ui.pill(writer(rel) or f"Changed {content.day_time(st.st_mtime * 1000)}"))
    where = (
        folder.removeprefix(content.AGENT_DIR).lstrip("/") + "/"
        if content.in_agent_dir(rel)
        else folder + "/"
    )
    return 200, (
        ui.header(parts[-1], ui.mono(where), crumb)
        + f'<div class="status">{"".join(p for p in pills if p)}</div>'
        + markup
        + build_check(rel)
    )
