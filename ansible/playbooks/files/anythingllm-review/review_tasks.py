"""The Scheduled tasks screen, and the job and run data other screens reuse.

A run's output can quote chat text, fetched pages or keys, so none of it is
shown. Each run is reduced to a safe summary computed here: its result, how
long it took, how many files it wrote and how many tools it called, and
whether it needs a look -- it failed, recorded an error, or its reply holds
tool calls the model wrote out as text (DeepSeek's "DSML" markup) instead of
running them. Job prompts are never read. Standard library only.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

import review_content as content
import review_layout as ui

RUNS_PER_JOB = 30
WRITE_TOOLS = ("filesystem-write-text-file", "filesystem-edit-file", "filesystem-create-file")
DAYS = ("Sundays", "Mondays", "Tuesdays", "Wednesdays", "Thursdays", "Fridays", "Saturdays")


@dataclass
class Run:
    """One run, reduced to what is safe to show."""

    started: object
    took: float | None
    ok: bool
    summary: str
    tools: list[str] = field(default_factory=list)


@dataclass
class Job:
    """One scheduled job with its recent runs, newest first."""

    id: int
    name: str
    schedule: str
    enabled: bool
    next_run: object
    skills: list[str]
    runs: list[Run]


def safe_run(status: object, result: object, error: object, started: object, done: object) -> Run:
    """A run's safe summary: counts and flags only, never its text."""
    try:
        data = json.loads(result) if isinstance(result, str) else {}
    except ValueError:
        data = {}
    data = data if isinstance(data, dict) else {}
    calls = data.get("toolCalls")
    calls = calls if isinstance(calls, list) else []
    tools = [str(c.get("toolName", "")) for c in calls if isinstance(c, dict)]
    writes = sum(1 for t in tools if t in WRITE_TOOLS)
    leaked = "DSML" in str(data.get("text", ""))
    took = (millis(done) - millis(started)) / 1000 if millis(done) and millis(started) else None
    problems = []
    if status not in ("completed", "running", "queued"):
        problems.append(str(status or "no status"))
    if error:
        problems.append("recorded an error (not shown)")
    if leaked:
        problems.append("tool calls leaked as text and did not run")
    counts = f"wrote {writes} file{'s' if writes != 1 else ''} · {len(tools)} tool call" + (
        "s" if len(tools) != 1 else ""
    )
    summary = counts if not problems else f"{'; '.join(problems)} · {counts}"
    return Run(started, took, not problems, summary, tools)


def jobs() -> list[Job]:
    """Every scheduled job with its latest RUNS_PER_JOB runs."""
    found = []
    for job_id, name, schedule, enabled, next_run, tools in content.rows(
        "select id, name, schedule, enabled, nextRunAt, tools from scheduled_jobs order by id"
    ):
        try:
            listed = json.loads(tools) if isinstance(tools, str) else []
        except ValueError:
            listed = []
        runs = [
            safe_run(*row)
            for row in content.rows(
                "select status, result, error, startedAt, completedAt from scheduled_job_runs "
                "where jobId = ? order by id desc limit ?",
                (job_id, RUNS_PER_JOB),
            )
        ]
        skills = [str(t).removeprefix("@@").split("#")[0] for t in listed if isinstance(t, str)]
        found.append(Job(job_id, name, schedule, bool(enabled), next_run, skills, runs))
    return found


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


def duration(seconds: float | None) -> str:
    """'1m 48s', or '' when unknown."""
    if seconds is None or seconds < 0:
        return ""
    minutes, secs = divmod(round(seconds), 60)
    return f"{minutes}m {secs:02d}s"


def result_pill(job: Job) -> str:
    """The latest run's result as a pill."""
    if not job.runs:
        return ui.pill("Not run yet")
    return ui.pill("Ran fine", "ok") if job.runs[0].ok else ui.pill("Needs a look", "warn")


def strip(job: Job) -> str:
    """The last ten runs as coloured bars, oldest first."""
    last = job.runs[:10][::-1]
    bad = sum(1 for r in last if not r.ok)
    bars = "".join(f'<i class="{"" if r.ok else "warn"}"></i>' for r in last)
    label = f"Recent runs: {len(last) - bad} fine, {bad} needed a look"
    return (
        f'<div class="strip" aria-label="{ui.esc(label)}">{bars}'
        f'<span class="small" style="margin-left:8px">last {len(last)} runs</span></div>'
    )


def card(job: Job) -> str:
    """A job's card for the Overview."""
    what = ""
    if job.runs and not job.runs[0].ok:
        what = (
            "<details><summary>What happened</summary>"
            f'<div class="log">{ui.esc(job.runs[0].summary)}</div></details>'
        )
    return (
        '<div class="card pad stack"><div class="sechead" style="align-items:center">'
        f'<span style="font-weight:500">{ui.esc(job.name)}</span>{result_pill(job)}</div>'
        f'<div class="muted">{ui.esc(plain_schedule(job.schedule))} · next '
        f"{ui.esc(content.when(job.next_run) or 'not scheduled')}</div>"
        f"{strip(job) if job.runs else ''}{what}</div>"
    )


def detail(job: Job, prefix: str) -> str:
    """One job's run history, safe summaries only."""
    fine = sum(1 for r in job.runs if r.ok)
    times = sorted(r.took for r in job.runs if r.took is not None)
    usual = duration(times[len(times) // 2]) if times else ""
    last = content.when(job.runs[0].started) if job.runs else ""
    uses = ", ".join(
        f'<a href="{prefix}/skills#skill-{ui.esc(s)}">{ui.esc(s)}</a>' for s in job.skills
    )
    stats = "".join(
        f'<div class="stat"><span class="small">{ui.esc(k)}</span><b>{ui.esc(v)}</b></div>'
        for k, v in (
            ("Ran fine", f"{fine} of {len(job.runs)}"),
            ("Usual time", usual or "--"),
            ("Last run", last or "--"),
            ("Next run", content.when(job.next_run) or "--"),
        )
    )
    history = ui.grid_table(
        "160px 120px 80px 1fr",
        ["When", "Result", "Took", "What happened"],
        [
            [
                ui.esc(content.when(r.started)),
                ui.pill("Ran fine", "ok") if r.ok else ui.pill("Needs a look", "warn"),
                ui.esc(duration(r.took)),
                ui.esc(r.summary),
            ]
            for r in job.runs[:10]
        ]
        or [["No runs yet", "", "", ""]],
    )
    return (
        f'<section class="card pad stack" id="task-{job.id}" style="gap:16px">'
        f'<div class="sechead"><h2 style="font-size:22px">{ui.esc(job.name)}</h2>'
        f'<span class="muted">Uses {uses or "no tools"}</span></div>'
        f'<div class="grid4">{stats}</div>{history}'
        '<div class="small">Run output is not shown here: it can quote chats, fetched pages '
        "or keys. Each run is summarised from its tool calls instead.</div></section>"
    )


def screen(prefix: str) -> str:
    """The Scheduled tasks screen."""
    found = jobs()
    table = ui.grid_table(
        "1fr 200px 160px 130px 80px",
        ["Task", "Schedule", "Next run", "Last result", "Took"],
        [
            [
                f'<a href="#task-{j.id}"><strong style="font-weight:500">{ui.esc(j.name)}'
                f"</strong></a>{'' if j.enabled else ' ' + ui.pill('Off')}",
                ui.esc(plain_schedule(j.schedule)),
                ui.esc(content.when(j.next_run)),
                result_pill(j),
                ui.esc(duration(j.runs[0].took) if j.runs else ""),
            ]
            for j in found
        ]
        or [["No scheduled tasks", "", "", "", ""]],
    )
    return (
        ui.header(prefix, "Scheduled tasks", "When each task runs, how it went, and what it did.")
        + table
        + "".join(detail(j, prefix) for j in found)
    )


def millis(value: object) -> float:
    """An epoch-milliseconds value as a number; 0 when it is not one."""
    try:
        return float(value)  # ty: ignore[invalid-argument-type]
    except (TypeError, ValueError):
        return 0.0


def week_ago_ms() -> float:
    """Seven days ago, in AnythingLLM's epoch milliseconds."""
    return (time.time() - 7 * 86400) * 1000
