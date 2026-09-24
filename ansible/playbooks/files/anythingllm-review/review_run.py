"""A scheduled task run's detail page: the agent's reply, then every tool call in order.

Each call shows its tool, its arguments on one line (long values as a size)
and the first lines of its result. Calls the model wrote into its reply as
DSML text instead of running are listed after the recorded ones, since the
run keeps no position for them. The run's status and error text come from the
server, so they are Admin only. Standard library only.
"""

from __future__ import annotations

import json

import review_content as content
import review_layout as ui
from review_tasks import RUN_SQL, Call, duration, parse_run, sentence

STEPS_PER_PAGE = 20


def _args(call: Call) -> str:
    """A call's arguments on one line: short values as written, long ones as a size."""
    parts = []
    for key, value in call.args.items():
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        shown = text if len(text) <= 160 else f"{content.size_text(len(text.encode()))} of text"  # noqa: PLR2004
        parts.append(f"{key}: {shown}")
    return " · ".join(parts)


def _result(text: str) -> str:
    """The first lines of a tool's result."""
    lines = text.splitlines()
    head = "\n".join(lines[:14])[:1600]
    return head + ("\n…" if len(head) < len(text) else "")


def run_view(prefix: str, run_id: str, start: str = "") -> tuple[int, str]:
    """(status, main markup) for one run: the reply, then every tool call in order."""
    found = content.rows(f"{RUN_SQL} where id = ?", (run_id,))
    if not found:
        return 404, ui.header("No such run", crumb=("Scheduled tasks", ui.href(prefix, "tasks")))
    run = parse_run(found[0])
    name = content.rows("select name from scheduled_jobs where id = ?", (run.job_id,))
    title = f"{name[0][0] if name else 'Task'} · {content.day_time(run.started)}"
    first = max(int(start) if start.isdigit() else 1, 1)
    page = run.calls[first - 1 : first - 1 + STEPS_PER_PAGE]
    steps = [
        f'<li><span class="bar" style="justify-content:flex-start"><span class="muted">'
        f"Step {first + i}</span>{ui.mono(c.tool)}</span>"
        f'<span class="args">{ui.esc(_args(c))}</span>{ui.code(_result(c.result))}</li>'
        for i, c in enumerate(page)
    ]
    if run.leaks and first - 1 + STEPS_PER_PAGE >= len(run.calls):
        at = run.text.find("DSML")
        snippet = run.text[max(run.text.rfind("\n", 0, at), 0) :][:1200]
        steps.append(
            f'<li class="leak"><span class="bar" style="justify-content:flex-start">'
            f"{ui.pill('Leaked as text · DSML', 'warn')}</span>"
            '<span class="lede" style="font-size:14px">The model wrote '
            f"{ui.esc(', '.join(run.leaks))} into its reply instead of running it. "
            "Nothing ran.</span>"
            f"{ui.code(snippet)}</li>"
        )
    nxt = first + STEPS_PER_PAGE
    more = (
        ui.more(
            ui.href(prefix, "run", id=run.id, start=nxt),
            f"Show steps {nxt} to {min(nxt + STEPS_PER_PAGE - 1, len(run.calls))}",
        )
        if nxt <= len(run.calls)
        else ""
    )
    notice = (
        ui.alert(
            "warn",
            f"<span><strong>Needs a look.</strong> {ui.esc(sentence(run.problems))}</span>",
        )
        if run.problems
        else ""
    )
    thoughts = (
        f"<details><summary>The model&rsquo;s notes during the run ({len(run.thoughts)})</summary>"
        f"{ui.code(chr(10).join(run.thoughts)[:20000])}</details>"
        if run.thoughts
        else ""
    )
    showing = f"showing {first} to {first + len(page) - 1}" if page else ""
    return 200, (
        ui.header(
            title,
            ui.esc(f"Ran for {duration(run.took, words=True)}.") if run.took else "Still running.",
            ("Scheduled tasks", ui.href(prefix, "tasks")),
        )
        + notice
        + ui.card("Agent's reply", f'<div class="prompt">{ui.esc(run.text[:20000])}</div>')
        + ui.section(
            "Tool calls",
            f'<ol class="steps">{"".join(steps)}</ol>'
            if steps
            else ('<div class="muted">No tool calls.</div>'),
            ui.esc(f"{len(run.calls)} step{'s' * (len(run.calls) != 1)} · {showing}"),
        )
        + more
        + thoughts
        + ui.admin(
            '<section class="card"><div>'
            + ui.kv("Run", ui.esc(f"#{run.id} · {run.status}"))
            + ui.kv("Started", ui.esc(content.when(run.started)))
            + ui.kv("Finished", ui.esc(content.when(run.done) or "--"))
            + "</div>"
            + (
                ui.code(run.error[:4000])
                if run.error
                else '<span class="muted">No error recorded.</span>'
            )
            + "</section>"
        )
    )
