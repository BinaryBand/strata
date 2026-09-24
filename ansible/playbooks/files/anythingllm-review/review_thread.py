"""A thread's messages, marked by whether they are in the agent's context.

AnythingLLM sends a thread's last `openAiHistory` exchanges that are still
included (a cleared chat stays stored but is no longer sent); an agent session
takes the last 20. Each exchange is the user's prompt and the reply's text.
Newest page first; "Show earlier messages" pages back. Standard library only.
"""

from __future__ import annotations

import review_content as content
import review_layout as ui
import review_workspace

PAGE = 20
CLAUSES = {
    "default": ("thread_id is null and api_session_id is null", ()),
    "api": ("thread_id is null and api_session_id is not null", ()),
}


def where(thread: str) -> tuple[str, tuple] | None:
    """The SQL clause and parameters selecting a thread's chats, or None."""
    if thread in CLAUSES:
        return CLAUSES[thread]
    return ("thread_id = ?", (int(thread),)) if thread.isdigit() else None


def message(who: str, text: str) -> str:
    """One message bubble."""
    kind = "msg you" if who == "You" else "msg"
    return f'<div class="{kind}"><small>{ui.esc(who)}</small><div>{ui.esc(text)}</div></div>'


def exchange(prompt: object, response: object) -> str:
    """A prompt and its reply."""
    reply = content.json_field(response).get("text")
    return message("You", str(prompt or "")) + message(
        "Agent", str(reply if reply is not None else response or "")
    )


def view(prefix: str, slug: str, thread: str, before: str = "") -> tuple[int, str]:
    """(status, main markup) for one thread."""
    ws = review_workspace.workspace(slug)
    clause = where(thread)
    crumb = ("Workspace", ui.href(prefix, "workspace", ws=slug))
    if ws is None or clause is None:
        return 404, ui.header("No such thread", crumb=crumb)
    sql, params = clause
    base = f"from workspace_chats where workspaceId = ? and {sql}"
    names = (
        content.rows("select name from workspace_threads where id = ?", params) if params else []
    )
    name = names[0][0] if names else ("default" if thread == "default" else "Developer API chats")
    total, last = (
        content.rows(f"select count(*), max(createdAt) {base}", (ws.id, *params)) or [(0, None)]
    )[0]
    context = {
        r[0]
        for r in content.rows(
            f"select id {base} and include = 1 order by id desc limit ?",
            (ws.id, *params, ws.history),
        )
    }
    agent = {
        r[0]
        for r in content.rows(
            f"select id {base} and include = 1 order by id desc limit ?",
            (ws.id, *params, review_workspace.AGENT_HISTORY),
        )
    }
    upper = int(before) if before.isdigit() else 2**62
    page = content.rows(
        f"select id, prompt, response, include {base} and id < ? order by id desc limit ?",
        (ws.id, *params, upper, PAGE),
    )[::-1]
    older = [r for r in page if r[0] not in context]
    newer = [r for r in page if r[0] in context]
    parts = []
    if page and content.rows(f"select 1 {base} and id < ? limit 1", (ws.id, *params, page[0][0])):
        parts.append(
            ui.more(
                ui.href(prefix, "thread", ws=slug, id=thread, before=page[0][0]),
                "Show earlier messages",
            )
        )
    if older:
        cleared = sum(1 for r in older if not r[3])
        note = "Outside the agent's context" + (f" · {cleared} cleared from it" if cleared else "")
        if any(r[0] in agent for r in older):
            note += f" · an agent session still gets the last {review_workspace.AGENT_HISTORY}"
        parts.append(
            f'<div class="msgs out"><span class="muted">{ui.esc(note)}</span>'
            + "".join(exchange(r[1], r[2]) for r in older)
            + "</div>"
        )
    if newer:
        parts.append(
            '<section class="ctx" aria-label="In the agent&rsquo;s context">'
            + ui.bar(
                ui.pill("In the agent's context", "accent"),
                ui.esc(f"The last {ws.history} exchanges still included. Showing {len(newer)}."),
            )
            + '<div class="msgs">'
            + "".join(exchange(r[1], r[2]) for r in newer)
            + "</div></section>"
        )
    lede = f"{total} exchange{'s' * (total != 1)}" + (
        f" · last one {content.day_time(last)}" if last else ""
    )
    return 200, (
        ui.header(str(name), ui.esc(lede), crumb)
        + ("".join(parts) or '<div class="muted">No messages yet.</div>')
    )
