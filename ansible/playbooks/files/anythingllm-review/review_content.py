"""What the /review monitor shows: the tree, allowlisted files and database status.

Split from review.py, which serves it. Nothing here writes anything: files are
opened read-only without following symlinks, the database is opened read-only,
and secrets are listed by name and size only. Standard library only.
"""

from __future__ import annotations

import html
import json
import os
import pwd
import re
import sqlite3
import stat
import subprocess
import time
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(os.environ.get("REVIEW_ROOT", "/srv/anythingllm"))
PREFIX = os.environ.get("REVIEW_PREFIX", "/review")
MAX_VIEW_BYTES = 256 * 1024
MAX_ENTRIES = 5000
MAX_DEPTH = 12
REDACTED = "<redacted>"
CONTROL = re.compile(r"[\x00-\x1f\x7f]")

# The only files whose contents may be shown, as paths relative to ROOT.
# Anything else is listed by name and size only.
VIEWABLE = [
    re.compile(p)
    for p in (
        r"storage/anythingllm-fs/.+\.(md|html|css)",
        r"storage/plugins/agent-skills/[^/]+/(plugin\.json|handler\.js|handler\.js\.draft)",
        r"storage/plugins/agent-skills/[^/]+/lib/[^/]+\.js",
        r"storage/plugins/agent-skills/[^/]+/engine/[^/]+\.(py|md)",
        r"storage/plugins/agent-skills/[^/]+/engine/contracts/[^/]+\.md",
        r"storage/plugins/agent-flows/[^/]+\.json",
        r"storage/research-runs/[^/]+/reports/final\.md",
        r"site-nginx/default\.conf",
    )
]
# Files the AI agent can write: shown, but labelled so their text is never
# mistaken for the monitor's own.
AGENT_WRITTEN = re.compile(
    r"storage/anythingllm-fs/.*|storage/plugins/agent-skills/[^/]+/handler\.js\.draft"
    r"|storage/plugins/agent-flows/.*|storage/research-runs/.*"
)
SETTING_VALUES = {"default_agent_skills", "disabled_agent_skills", "whitelisted_agent_skills"}
HEADERS = {
    "Content-Security-Policy": (
        "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"
    ),
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}
STYLE = (
    "body{font:15px/1.5 system-ui,sans-serif;max-width:78rem;margin:2rem auto;"
    "padding:0 1rem;color:#1d1a16;background:#faf8f3}"
    "h1{font-size:1.5rem;margin:0}"
    "h2{font-size:1rem;margin:2rem 0 .5rem;text-transform:uppercase;letter-spacing:.08em}"
    "table{border-collapse:collapse;width:100%;font-size:13px}"
    "td,th{border-bottom:1px solid #ddd5c6;padding:.25rem .5rem;text-align:left;"
    "vertical-align:top}th{background:#efe9dc}"
    "pre{white-space:pre-wrap;background:#f0ebe0;padding:1rem;font-size:12.5px;"
    "overflow-x:auto}.muted{color:#6b6257}"
    ".agent{border-left:4px solid #b8860b;padding:.5rem 1rem;background:#fbf3dd}"
    "@media (prefers-color-scheme:dark){body{background:#17140f;color:#e9e2d4}"
    "th{background:#2a251e}td,th{border-color:#3b342a}pre{background:#221e18}"
    ".muted{color:#a3988a}.agent{background:#2b2414}}"
)


def clean(text: object) -> str:
    """HTML-escaped text with control characters shown as '?'."""
    return html.escape(CONTROL.sub("?", "" if text is None else str(text)))


def viewable(rel: str) -> bool:
    """Whether ROOT/rel is on the allowlist of files whose contents may be shown."""
    return any(p.fullmatch(rel) for p in VIEWABLE)


def open_no_follow(rel: str) -> int:
    """A read-only descriptor for ROOT/rel, refusing a symlink at any step.

    Each component is opened relative to the last with O_NOFOLLOW, so a path
    swapped for a symlink after the allowlist check cannot redirect the read.
    """
    parts = [p for p in rel.split("/") if p]
    if not parts or any(p in (".", "..") for p in parts):
        raise PermissionError(rel)
    fd = os.open(ROOT, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in parts[:-1]:
            nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = nxt
        return os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    finally:
        os.close(fd)


def redact_manifest(text: str) -> str:
    """A skill's plugin.json with every setup value the user entered hidden."""
    try:
        data = json.loads(text)
    except ValueError:
        return text
    for arg in (data.get("setup_args") or {}).values():
        if isinstance(arg, dict) and "value" in arg:
            arg["value"] = REDACTED
    return json.dumps(data, indent=2, ensure_ascii=False)


class ViewError(Exception):
    """A file the viewer will not show, with the status and message to answer."""

    def __init__(self, status: int, message: str) -> None:
        """Keep the HTTP status beside the message."""
        super().__init__(message)
        self.status = status


def read_allowed(rel: str) -> str:
    """The text of an allowlisted, regular, not-too-large file, or ViewError."""
    if not viewable(rel):
        raise ViewError(403, "Not viewable here: only its name and size are shown in the tree.")
    try:
        fd = open_no_follow(rel)
    except FileNotFoundError as exc:
        raise ViewError(404, "No such file.") from exc
    except OSError as exc:
        raise ViewError(403, "That path cannot be opened here.") from exc
    with os.fdopen(fd, "rb") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise ViewError(403, "Not a regular file.")
        data = handle.read(MAX_VIEW_BYTES + 1)
    if len(data) > MAX_VIEW_BYTES:
        raise ViewError(413, f"Over {MAX_VIEW_BYTES // 1024} KB; not shown.")
    return data.decode("utf-8", errors="replace")


def file_view(rel: str) -> tuple[int, str]:
    """(status, body) for the file viewer."""
    try:
        text = read_allowed(rel)
    except ViewError as exc:
        return exc.status, str(exc)
    if rel.endswith("/plugin.json"):
        text = redact_manifest(text)
    note = (
        '<p class="agent">Written by the AI agent: this is its text, not the monitor\'s.</p>'
        if AGENT_WRITTEN.fullmatch(rel)
        else ""
    )
    return 200, page(rel, f"{note}<pre>{html.escape(text)}</pre>")


def owner(st: os.stat_result) -> str:
    """The file's owning account name, or its uid when unknown."""
    try:
        return pwd.getpwuid(st.st_uid).pw_name
    except KeyError:
        return str(st.st_uid)


def entry_row(full: Path, rel: str) -> str | None:
    """One table row for a tree entry, read with lstat so links are not followed."""
    try:
        st = full.lstat()
    except OSError:
        return None
    if stat.S_ISLNK(st.st_mode):
        kind = "link"
    elif stat.S_ISDIR(st.st_mode):
        kind = "dir"
    else:
        kind = "file"
    label = clean(rel + ("/" if kind == "dir" else ""))
    if kind == "file" and viewable(rel):
        query_string = html.escape(urlencode({"path": rel}))
        label = f'<a href="{PREFIX}/file?{query_string}">{label}</a>'
    when = time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime))
    size = "" if kind == "dir" else f"{st.st_size:,}"
    return (
        f"<tr><td>{label}</td><td>{kind}</td><td>{size}</td><td>{clean(owner(st))}</td>"
        f"<td>{stat.filemode(st.st_mode)}</td><td>{when}</td></tr>"
    )


def tree_rows() -> list[str]:
    """One table row per entry under ROOT, never following symlinks, bounded."""
    rows: list[str] = []
    for dirpath, dirnames, filenames in os.walk(ROOT, followlinks=False):
        if len(Path(dirpath).relative_to(ROOT).parts) >= MAX_DEPTH:
            dirnames.clear()
        dirnames.sort()
        for name in sorted(dirnames) + sorted(filenames):
            if len(rows) >= MAX_ENTRIES:
                rows.append(f"<tr><td colspan=6>... stopped at {MAX_ENTRIES} entries</td></tr>")
                return rows
            full = Path(dirpath) / name
            row = entry_row(full, full.relative_to(ROOT).as_posix())
            if row:
                rows.append(row)
    return rows


def query(db: sqlite3.Connection, sql: str) -> list[tuple]:
    """The rows for `sql`, or one row naming the error when the schema differs."""
    try:
        return db.execute(sql).fetchall()
    except sqlite3.Error as exc:
        return [(f"unavailable: {exc}",)]


def table(headings: list[str], rows: list[tuple]) -> str:
    """An HTML table with every cell escaped."""
    head = "".join(f"<th>{clean(h)}</th>" for h in headings)
    body = "".join("<tr>" + "".join(f"<td>{clean(v)}</td>" for v in row) + "</tr>" for row in rows)
    return f"<table><tr>{head}</tr>{body}</table>"


JOBS_SQL = (
    "select id, name, schedule, enabled, lastRunAt, nextRunAt from scheduled_jobs order by id"
)
# Error text can quote chat or keys, so only its presence and length.
RUNS_SQL = (
    "select r.id, j.name, r.status, r.startedAt, r.completedAt, "
    "case when coalesce(r.error, '') = '' then '' "
    "else 'yes (' || length(r.error) || ' chars, not shown)' end "
    "from scheduled_job_runs r left join scheduled_jobs j on j.id = r.jobId "
    "order by r.id desc limit 10"
)
WORKSPACES_SQL = (
    "select w.name, w.slug, count(c.id), max(c.createdAt) from workspaces w "
    "left join workspace_chats c on c.workspaceId = w.id group by w.id order by w.name"
)
SETTINGS_SQL = "select label, value from system_settings order by label"
EVENTS_SQL = "select event, occurredAt from event_logs order by id desc limit 30"


def shown_setting(row: tuple) -> tuple:
    """A settings row with its value hidden unless it is on the allowlist."""
    if len(row) > 1 and row[0] not in SETTING_VALUES:
        return (row[0], "(not shown)")
    return row


def database_sections() -> str:
    """Jobs, runs, workspaces, settings and events, with no chat or secret text."""
    path = ROOT / "storage" / "anythingllm.db"
    if not path.exists():
        return "<p class=muted>No database.</p>"
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
    try:
        jobs = query(db, JOBS_SQL)
        runs = query(db, RUNS_SQL)
        workspaces = query(db, WORKSPACES_SQL)
        settings = [shown_setting(row) for row in query(db, SETTINGS_SQL)]
        events = query(db, EVENTS_SQL)
    finally:
        db.close()
    job_heads = ["id", "name", "schedule (UTC)", "enabled", "last run", "next run"]
    run_heads = ["run", "job", "status", "started", "completed", "error"]
    return (
        "<h2>Scheduled jobs</h2>"
        + table(job_heads, jobs)
        + "<h2>Last job runs</h2>"
        + table(run_heads, runs)
        + "<h2>Workspaces</h2>"
        + table(["name", "slug", "chats", "last chat"], workspaces)
        + "<h2>Settings</h2>"
        + table(["label", "value"], settings)
        + "<h2>Recent events</h2>"
        + table(["event", "at"], events)
    )


def mcp_servers() -> str:
    """MCP server names and autoStart only: the config itself can hold keys."""
    path = ROOT / "storage" / "plugins" / "anythingllm_mcp_servers.json"
    try:
        servers = json.loads(path.read_text()).get("mcpServers") or {}
    except (OSError, ValueError, AttributeError):
        return "<p class=muted>No MCP config.</p>"
    rows = [(n, (s.get("anythingllm") or {}).get("autoStart", True)) for n, s in servers.items()]
    heads = ["MCP server (config not shown: it can hold keys)", "autoStart"]
    return table(heads, rows or [("none", "")])


def service_state(unit: str) -> str:
    """`systemctl --user is-active` for one of diot's units."""
    env = {
        "PATH": "/usr/bin:/bin",
        "XDG_RUNTIME_DIR": os.environ.get("XDG_RUNTIME_DIR", ""),
        "DBUS_SESSION_BUS_ADDRESS": os.environ.get("DBUS_SESSION_BUS_ADDRESS", ""),
    }
    try:
        done = subprocess.run(
            ["/usr/bin/systemctl", "--user", "is-active", unit],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"unavailable: {exc}"
    return (done.stdout or done.stderr).strip()


def services() -> str:
    """The AnythingLLM and site units' states."""
    units = ("anythingllm.service", "anythingllm-site.service")
    return table(["service (diot user)", "state"], [(u, service_state(u)) for u in units])


def page(title: str, body: str) -> str:
    """A complete page around `body`."""
    return (
        '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{clean(title)} -- AnythingLLM review</title><style>{STYLE}</style></head><body>"
        f'<h1><a href="{PREFIX}/">AnythingLLM review</a></h1>'
        f"<p class=muted>{clean(title)}</p>{body}</body></html>"
    )


def overview(ttl_seconds: int) -> str:
    """The monitor's main page."""
    built = time.strftime("%Y-%m-%d %H:%M:%S %Z")
    tree_head = (
        "<table><tr><th>path</th><th>type</th><th>bytes</th><th>owner</th>"
        "<th>mode</th><th>modified</th></tr>"
    )
    body = (
        f"<p class=muted>Built {built}; rebuilt on a request once over {ttl_seconds} s old. "
        "Secret files are listed by name and size only; files the agent can write are "
        "labelled when opened.</p>"
        "<h2>Services</h2>"
        + services()
        + database_sections()
        + "<h2>MCP servers</h2>"
        + mcp_servers()
        + f"<h2>Files under {clean(ROOT)}</h2>"
        + tree_head
        + "".join(tree_rows())
        + "</table>"
    )
    return page("Overview", body)
