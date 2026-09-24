"""The Scheduled tasks screen and a run's detail page, and the job data other screens reuse.

A task's prompt, its runs' replies and every tool call's arguments and results
were all in the agent's context, so they are shown in full. A job runs with no
workspace: it gets AnythingLLM's built-in default prompt, no chat history and
only its own tools. A run needs a look when it failed, recorded an error, or
its reply holds tool calls the model wrote out as text (DeepSeek's "DSML"
markup) instead of running them. Error text comes from the server, not the
agent, so it is Admin only. Standard library only.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field

import review_content as content
import review_layout as ui

RUNS_PER_JOB = 50
PROMPT_LINES = 12
WRITE_TOOLS = re.compile(r"(^|-)(write-text-file|edit-file|create-.*-file|create-text-file)$")
INVOKE = re.compile(r'invoke\s+name="([^"]+)"')
DAYS = ("Sundays", "Mondays", "Tuesdays", "Wednesdays", "Thursdays", "Fridays", "Saturdays")


@dataclass
class Call:
    """One tool call as the run recorded it."""

    tool: str
    args: dict
    result: str


@dataclass
class Run:
    """One run of a job, with everything the agent saw and said."""

    id: int
    job_id: int
    status: str
    started: object
    done: object
    text: str
    error: str
    calls: list[Call] = field(default_factory=list)
    thoughts: list[str] = field(default_factory=list)

    @property
    def took(self) -> float | None:
        """Seconds from start to finish, or None while unknown."""
        start, end = content.millis(self.started), content.millis(self.done)
        return (end - start) / 1000 if start and end else None

    @property
    def leaks(self) -> list[str]:
        """Tools named in calls the model wrote out as text instead of running."""
        if "DSML" not in self.text:
            return []
        return INVOKE.findall(self.text) or ["(unnamed)"]

    @property
    def writes(self) -> list[str]:
        """Paths the run wrote, in order."""
        return [str(c.args.get("path", "")) for c in self.calls if WRITE_TOOLS.search(c.tool)]

    @property
    def problems(self) -> list[str]:
        """Why the run needs a look; empty when it ran fine."""
        found = []
        if self.status not in ("completed", "running", "queued"):
            found.append(f"it ended as {self.status or 'no status'}")
        if self.error:
            found.append("it recorded an error")
        if self.leaks:
            n = len(self.leaks)
            found.append(
                f"{'one tool call' if n == 1 else f'{n} tool calls'} came back as text "
                "instead of running"
            )
        return found

    @property
    def ok(self) -> bool:
        """Whether the run needs no look."""
        return not self.problems


@dataclass
class Job:
    """One scheduled job with its recent runs, newest first."""

    id: int
    name: str
    prompt: str
    schedule: str
    enabled: bool
    next_run: object
    tools: list[str]
    runs: list[Run]


def parse_run(row: tuple) -> Run:
    """A scheduled_job_runs row as a Run."""
    run_id, job_id, status, result, error, started, done = row
    data = content.json_field(result)
    calls = [
        Call(
            str(c.get("toolName", "")),
            c.get("arguments") if isinstance(c.get("arguments"), dict) else {},
            c.get("result") if isinstance(c.get("result"), str) else json.dumps(c.get("result")),
        )
        for c in data.get("toolCalls") or []
        if isinstance(c, dict)
    ]
    thoughts = [str(t) for t in data.get("thoughts") or [] if t]
    text = str(data.get("text") or "")
    return Run(
        run_id, job_id, str(status or ""), started, done, text, str(error or ""), calls, thoughts
    )


RUN_SQL = "select id, jobId, status, result, error, startedAt, completedAt from scheduled_job_runs"


def jobs(runs: int = RUNS_PER_JOB) -> list[Job]:
    """Every scheduled job with its latest runs."""
    found = []
    for job_id, name, prompt, schedule, enabled, next_run, tools in content.rows(
        "select id, name, prompt, schedule, enabled, nextRunAt, tools "
        "from scheduled_jobs order by id"
    ):
        try:
            listed = json.loads(tools) if isinstance(tools, str) else []
        except ValueError:
            listed = []
        found.append(
            Job(
                job_id,
                str(name),
                str(prompt or ""),
                str(schedule or ""),
                bool(enabled),
                next_run,
                [str(t) for t in listed if isinstance(t, str)] if isinstance(listed, list) else [],
                [
                    parse_run(r)
                    for r in content.rows(
                        f"{RUN_SQL} where jobId = ? order by id desc limit ?", (job_id, runs)
                    )
                ],
            )
        )
    return found


def tool_label(tool_id: str) -> str:
    """A job's tool id as a name: '@@news-wire' -> 'news-wire', 'fs#fs-read' -> 'fs-read'."""
    return tool_id.removeprefix("@@").split("#")[-1]


def plain_schedule(cron: object) -> str:
    """A five-field cron line in words when it is a daily or weekly time; else as written."""
    parts = str(cron or "").split()
    if len(parts) == 5 and parts[0].isdigit() and parts[1].isdigit() and parts[2:4] == ["*", "*"]:  # noqa: PLR2004
        at = f"{int(parts[1]):02d}:{int(parts[0]):02d} UTC"
        if parts[4] == "*":
            return f"Every day at {at}"
        if parts[4].isdigit() and int(parts[4]) < len(DAYS):
            return f"{DAYS[int(parts[4])]} at {at}"
    return str(cron or "")


def duration(seconds: float | None, *, words: bool = False) -> str:
    """'4m 12s', or '4 minutes 12 seconds' with words; '' when unknown."""
    if seconds is None or seconds < 0:
        return ""
    minutes, secs = divmod(round(seconds), 60)
    if words:
        return f"{minutes} minute{'s' * (minutes != 1)} {secs} second{'s' * (secs != 1)}"
    return f"{minutes}m {secs:02d}s"


def result_pill(run: Run | None) -> str:
    """A run's result as a pill."""
    if run is None:
        return ui.pill("Not run yet")
    return ui.pill("Ran fine", "ok") if run.ok else ui.pill("Needs a look", "warn")


def writes_to(job: Job) -> str:
    """The folder the latest run that wrote anything wrote into, or ''."""
    latest = next((r for r in job.runs if r.writes), None)
    paths = [p for p in latest.writes if p] if latest else []
    return os.path.commonpath(paths) + "/" if len(paths) > 1 else (paths[0] if paths else "")


def sentence(problems: list[str]) -> str:
    """Problems as one sentence: 'It recorded an error; one tool call came back as text ...'."""
    text = "; ".join(problems)
    return f"{text[:1].upper()}{text[1:]}." if text else ""


def run_line(run: Run) -> str:
    """'wrote 11 files · 4m 12s' for a run row."""
    n = len(run.writes)
    took = duration(run.took)
    return f"wrote {n} file{'s' * (n != 1)} · {len(run.calls)} tool calls" + (
        f" · {took}" if took else ""
    )


def overview_card(prefix: str, job: Job) -> str:
    """A job's card for the Overview, linking to its latest run."""
    last = job.runs[0] if job.runs else None
    fine = sum(1 for r in job.runs[:14] if r.ok)
    said = "Not run yet."
    if last:
        said = f"Last run {content.day_time(last.started)}: " + (
            sentence(last.problems).lower() if last.problems else run_line(last) + "."
        )
    body = (
        f'<span class="lede" style="font-size:14px">{ui.esc(said)}</span>'
        f'<span class="muted">Next run {ui.esc(content.day_time(job.next_run) or "not set")}'
        f" · {fine} of {len(job.runs[:14])} recent runs ran fine</span>"
    )
    link = ui.href(prefix, "run", id=last.id) if last else ui.href(prefix, "tasks")
    return ui.card(job.name, body, result_pill(last), link)


def task_card(prefix: str, job: Job, *, full: bool) -> str:
    """A job: settings, its whole prompt, the context it runs with, and its runs."""
    provider, model, _ = content.model()
    lines = job.prompt.splitlines()
    short = len(lines) <= PROMPT_LINES
    prompt = job.prompt if full or short else "\n".join(lines[:PROMPT_LINES]) + "\n…"
    show_all = (
        ui.more(ui.href(prefix, "tasks", job=job.id), "Show all") if not full and not short else ""
    )
    tools = ", ".join(tool_label(t) for t in job.tools) or "none"
    runs = job.runs if full else job.runs[:5]
    run_rows = [
        ui.row(
            content.day_time(r.started),
            run_line(r),
            result_pill(r),
            ui.href(prefix, "run", id=r.id),
        )
        for r in runs
    ]
    more_runs = (
        ui.more(ui.href(prefix, "tasks", job=job.id), "Show more runs")
        if not full and len(job.runs) > len(runs)
        else ""
    )
    return (
        '<section class="card">'
        + ui.bar(
            f"<h2>{ui.esc(job.name)}</h2>",
            ("" if job.enabled else ui.pill("Off"))
            + result_pill(job.runs[0] if job.runs else None),
        )
        + "<div>"
        + ui.kv("Schedule", ui.esc(plain_schedule(job.schedule)))
        + ui.kv("Model", ui.mono(model) + f" · {ui.esc(provider)}")
        + (ui.kv("Writes to", ui.mono(writes_to(job))) if writes_to(job) else "")
        + ui.kv("Next run", ui.esc(content.day_time(job.next_run) or "not scheduled"))
        + ui.kv("Tools", ui.esc(tools))
        + "</div>"
        + ui.bar("<h3>Prompt</h3>", "The task&rsquo;s whole brief, as the agent sees it")
        + ui.code(prompt, big=True)
        + show_all
        + '<span class="muted">It also gets AnythingLLM&rsquo;s default system prompt, no chat '
        "history and only the tools listed above.</span>"
        + ui.bar("<h3>Run history</h3>", f"{len(job.runs)} recent")
        + ui.rows(run_rows, "No runs yet.")
        + more_runs
        + "</section>"
    )


def screen(prefix: str, job_id: str = "") -> str:
    """The Scheduled tasks screen; `job_id` shows that job's whole prompt and every run."""
    found = jobs()
    shown = [j for j in found if str(j.id) == job_id] if job_id else found
    queued = sum(1 for j in found for r in j.runs if r.status in ("queued", "running"))
    count = f"{len(found)} task{'s' * (len(found) != 1)}"
    return (
        ui.header("Scheduled tasks", f"{ui.esc(count)}. Each runs on its own, with no chat.")
        + (
            "".join(task_card(prefix, j, full=bool(job_id)) for j in shown)
            or ('<div class="muted">No scheduled tasks.</div>')
        )
        + ui.admin(
            ui.rows(
                [
                    ui.row(
                        "Scheduler",
                        "Runs inside the AnythingLLM server",
                        ui.pill(content.service_state("anythingllm.service")),
                    ),
                    ui.row("Queue", "Runs waiting or running", ui.pill(str(queued) or "0")),
                ]
            )
        )
    )
