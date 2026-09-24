"""The Overview screen: what the agent can see, at a glance.

The greeting names the one tailnet login the monitor serves. Below it: the key
check (review_secrets), the model, each scheduled task's latest run, the last
site build, and counts of skills, documents and memories. Service states and
disk use are the server's, so they are Admin only. Standard library only.
"""

from __future__ import annotations

import shutil
import time

import review_artifacts
import review_content as content
import review_layout as ui
import review_secrets
import review_tasks
import review_tools

# (label, unit, is a user unit of diot's)
SERVICES = (
    ("AnythingLLM server", "anythingllm.service", True),
    ("Site web server", "anythingllm-site.service", True),
    ("Site builder", "anythingllm-site-build.service", False),
    ("Story service", "anythingllm-story.service", False),
)


def greeting(login: str) -> str:
    """'Good morning, name' by the server's local hour."""
    hour = time.localtime().tm_hour
    part = "morning" if 5 <= hour < 12 else "afternoon" if 12 <= hour < 18 else "evening"  # noqa: PLR2004
    return f"Good {part}, {login.split('@', maxsplit=1)[0] or 'there'}"


def key_check(prefix: str) -> tuple[str, str]:
    """(status-line markup, alert markup) for the key check."""
    findings = review_secrets.check()
    if not findings:
        return (
            f'<span class="okline">{ui.icon("check", 16)}'
            "No keys found in the agent&rsquo;s reach</span>",
            "",
        )
    items = []
    for f in findings[:10]:
        at = f", line {f.line}" if f.line else ""
        link = (
            f' <a class="more" href="{ui.href(prefix, "file", path=f.path)}">Open the file</a>'
            if f.path and content.viewable(f.path)
            else ""
        )
        items.append(
            f"<span>Found in {ui.mono(f.where)}{ui.esc(at)}. It matches the stored value of "
            f"{ui.mono(f.setting)}.{link}</span>"
        )
    more = f"<span>And {len(findings) - 10} more places.</span>" if len(findings) > 10 else ""  # noqa: PLR2004
    alert = ui.alert(
        "bad",
        "<strong>A key from settings appears where the agent can read it. Rotate it.</strong>"
        + "".join(items)
        + more
        + "<span>The value itself is never shown here.</span>",
    )
    return (
        f'<span style="color:var(--badfg)">{ui.icon("alert", 16)}'
        "Key found in the agent&rsquo;s reach</span>",
        alert,
    )


def model_card(prefix: str, ws: tuple[str, str] | None) -> str:
    """The system model: what every job and, unless overridden, every chat uses."""
    provider, model, thinking = content.model()
    link = (
        f'<a href="{ui.href(prefix, "workspace", ws=ws[0])}" style="color:inherit">Workspace</a>'
        if ws
        else ""
    )
    return ui.card(
        "Model",
        "<div>"
        + ui.kv("Provider", ui.esc(provider))
        + ui.kv("Model", ui.mono(model))
        + ui.kv("Type", "Thinking model" if thinking else "Model")
        + ui.kv("Used for", "Every scheduled task, and chat unless a workspace sets its own")
        + "</div>",
        link,
    )


def build_card(prefix: str) -> str:
    """The site builder's last outcome."""
    status = review_artifacts.build_status()
    if not status:
        return ui.card("Site build", '<span class="muted">No build yet.</span>')
    rejected = content.as_list(status.get("rejected"))
    waiting = content.as_list(status.get("waiting"))
    stamp = str(status.get("time") or "")
    tiles = [
        ui.stat("Last build", stamp[11:16] or "--", stamp[:10]),
        ui.stat("Editions built", status.get("editions") or 0),
        ui.stat("Files skipped", len(rejected), f"{len(waiting)} waiting" if waiting else ""),
    ]
    report = ui.more(
        ui.href(prefix, "file", path=f"{content.AGENT_DIR}/site/BUILD.md"), "See the build report"
    )
    ok = status.get("ok") is True
    return ui.card(
        "Site build · The Daily Seek",
        ui.stats(tiles) + report,
        ui.pill("Built", "ok") if ok else ui.pill("Failed", "bad"),
    )


def counts() -> str:
    """Skills on, documents embedded and memories saved."""
    skills = [s for s in review_tools.skills() if s.on]
    custom = sum(1 for s in skills if s.source != "Built-in")
    docs = content.rows("select count(*) from workspace_documents")
    mems = content.rows("select count(*) from memories")
    n_docs = docs[0][0] if docs else 0
    n_mems = mems[0][0] if mems else 0
    return ui.stats(
        [
            ui.stat("Skills", len(skills), f"{custom} custom, {len(skills) - custom} built-in"),
            ui.stat("Documents", n_docs, "none embedded yet" if not n_docs else "embedded"),
            ui.stat("Memories", n_mems, "none saved yet" if not n_mems else "saved"),
        ]
    )


def admin_part() -> str:
    """Service states and disk use."""
    items = []
    for label, unit, user in SERVICES:
        state = content.service_state(unit, user=user)
        kind = "ok" if state == "active" else "" if state == "inactive" else "warn"
        items.append(
            ui.row(
                label,
                unit,
                ui.pill({"active": "Running", "inactive": "Idle"}.get(state, state), kind),
            )
        )
    try:
        disk = shutil.disk_usage(content.ROOT)
        items.append(
            ui.row("Storage", f"{content.size_text(disk.used)} of {content.size_text(disk.total)}")
        )
    except OSError:
        pass
    return ui.admin(ui.rows(items))


def screen(prefix: str, login: str, ws: tuple[str, str] | None) -> str:
    """The Overview screen."""
    state = content.service_state("anythingllm.service")
    online = state == "active"
    keys, alert = key_check(prefix)
    where = f" in <strong>{ui.esc(ws[1])}</strong>" if ws else ""
    status = (
        '<div class="status">'
        f'<span style="color:var({"--okdot" if online else "--badfg"})">{ui.icon("dot", 12)}'
        '<span style="color:var(--ink2)">'
        f"Instance {'online' if online else ui.esc(state)}</span></span>"
        f"<span>Checked {time.strftime('%H:%M')}</span>{keys}</div>"
    )
    return (
        ui.header(greeting(login), f"What the agent{where} can see.")
        + status
        + alert
        + model_card(prefix, ws)
        + "".join(review_tasks.overview_card(prefix, j) for j in review_tasks.jobs(runs=14))
        + build_card(prefix)
        + counts()
        + admin_part()
    )


def more_screen(prefix: str, ws: tuple[str, str] | None) -> str:
    """The phone's More tab: the screens without a tab of their own."""
    instance = ui.rows(
        [
            ui.row(
                "Artifacts",
                "The Daily Seek, research runs, /story",
                ui.icon("chevron"),
                ui.href(prefix, "artifacts"),
            ),
            ui.row(
                "Files", "The agent's file folder", ui.icon("chevron"), ui.href(prefix, "files")
            ),
        ]
    )
    own = (
        ui.rows(
            [
                ui.row(
                    "Knowledge",
                    "Documents and memories",
                    ui.icon("chevron"),
                    ui.href(prefix, "knowledge", ws=ws[0]),
                )
            ]
        )
        if ws
        else ""
    )
    return (
        ui.header("More", f"Everything else{' in ' + ui.esc(ws[1]) if ws else ''}.")
        + '<div class="muted">Whole instance</div>'
        + instance
        + (f'<div class="muted">{ui.esc(ws[1])}</div>' + own if ws else "")
    )
