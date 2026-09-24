"""The Workspace screen: how the agent in one workspace is set up.

What reaches the model, as AnythingLLM 1.16 builds it: the workspace's own
prompt (a copy of the default taken when the workspace was made, or the
built-in prompt when it has none) with its {variables} filled in and saved
memories added after it; then the thread's recent history -- the last
`openAiHistory` exchanges in chat, a fixed 20 for an agent session.
Temperature and retrieval settings are the server's, not the agent's, so they
are Admin only. Standard library only.
"""

from __future__ import annotations

from dataclasses import dataclass

import review_content as content
import review_layout as ui

# models/systemSettings.js saneDefaultSystemPrompt in AnythingLLM 1.16: used when
# a workspace has no prompt, and by every scheduled task.
BUILT_IN_PROMPT = (
    "Given the following conversation, relevant context, and a follow up question, reply with "
    "an answer to the current question the user is asking. The current date and time is "
    "{datetime}. Return only your response to the question given the above information "
    "following the users instructions as needed."
)
AGENT_HISTORY = 20  # utils/agents/index.js: #chatHistory(20)
# models/systemPromptVariables.js DEFAULT_VARIABLES; user.* need multi-user mode.
BUILT_IN_VARIABLES = (
    ("time", "Current time"),
    ("time_24", "Current time (24-hour format)"),
    ("date", "Current date"),
    ("datetime", "Current date and time"),
    ("datetime_24", "Current date and time (24-hour format)"),
    ("workspace.id", "Current workspace's ID"),
    ("workspace.name", "Current workspace's name"),
)
WS_SQL = (
    "select id, name, slug, openAiTemp, openAiHistory, openAiPrompt, similarityThreshold, "
    "chatModel, topN, chatMode, chatProvider, agentModel, agentProvider, vectorSearchMode "
    "from workspaces"
)


@dataclass
class Workspace:
    """One workspace's settings."""

    id: int
    name: str
    slug: str
    temp: object
    history: int
    prompt: str | None
    threshold: object
    chat_model: object
    top_n: object
    chat_mode: object
    chat_provider: object
    agent_model: object
    agent_provider: object
    search_mode: object


def workspace(slug: str = "") -> Workspace | None:
    """The workspace with this slug, or the first one when slug is empty."""
    found = content.rows(f"{WS_SQL} where slug = ?", (slug,)) if slug else []
    found = found or ([] if slug else content.rows(f"{WS_SQL} order by id limit 1"))
    if not found:
        return None
    row = list(found[0])
    row[4] = int(row[4]) if str(row[4] or "").isdigit() else 20
    return Workspace(*row)


def threads(ws: Workspace) -> list[tuple[str, str, int, object]]:
    """(thread id, name, exchanges, last one): default thread, named threads, API chats."""
    found = []
    for key, name, where in (
        ("default", "default", "thread_id is null and api_session_id is null"),
        ("api", "Developer API chats", "thread_id is null and api_session_id is not null"),
    ):
        sql = "select count(*), max(createdAt) from workspace_chats where workspaceId = ? and "
        got = content.rows(sql + where, (ws.id,))
        count, last = got[0] if got else (0, None)
        if count or key == "default":
            found.append((key, name, count, last))
    for tid, name, count, last in content.rows(
        "select t.id, t.name, count(c.id), max(c.createdAt) from workspace_threads t "
        "left join workspace_chats c on c.thread_id = t.id where t.workspace_id = ? "
        "group by t.id order by max(c.createdAt) desc",
        (ws.id,),
    ):
        found.append((str(tid), str(name), count, last))
    return found


def model_card(ws: Workspace) -> str:
    """Which model answers in chat and as the agent."""
    provider, model, thinking = content.model(ws.chat_provider, ws.chat_model)
    agent_provider, agent_model, _ = content.model(
        ws.agent_provider or ws.chat_provider, ws.agent_model or ws.chat_model
    )
    same = (agent_provider, agent_model) == (provider, model) == content.model()[:2]
    used = "Chat, agents and every scheduled task" if same else "Chat"
    body = (
        "<div>"
        + ui.kv("Provider", ui.esc(provider))
        + ui.kv("Model", ui.mono(model))
        + ui.kv("Thinking model", "Yes" if thinking else "No")
        + ui.kv("Used for", ui.esc(used))
        + (
            ""
            if same
            else ui.kv("Agent model", ui.mono(agent_model) + f" · {ui.esc(agent_provider)}")
        )
        + ui.kv(
            "Chat history",
            ui.esc(
                f"Last {ws.history} exchanges of a thread; "
                f"an agent session gets the last {AGENT_HISTORY}"
            ),
        )
        + "</div>"
    )
    return ui.card("Model", body)


def prompt_card(ws: Workspace) -> str:
    """The workspace's prompt as the agent gets it, and how it relates to the default."""
    default = content.setting("default_system_prompt") or BUILT_IN_PROMPT
    if ws.prompt is None:
        state, text = ui.pill("Not set: uses the built-in prompt"), BUILT_IN_PROMPT
    else:
        text = ws.prompt
        state = (
            ui.pill("Same as the default")
            if ws.prompt.strip() == default.strip()
            else ui.pill("Edited from default", "accent")
        )
    return (
        '<section class="card">'
        + ui.bar("<h3>System prompt</h3>", state)
        + '<span class="muted">This workspace&rsquo;s prompt. {variables} are filled in when a '
        "message is sent, and saved memories are added after it.</span>"
        + ui.code(text, big=True)
        + "<details><summary>The default for new workspaces</summary>"
        + ui.code(default)
        + "</details></section>"
    )


def variables_card() -> str:
    """Built-in and user-defined prompt variables."""
    items = [
        ui.kv("{" + key + "}", ui.esc(about + " -- filled in when a message is sent"))
        for key, about in BUILT_IN_VARIABLES
    ]
    items += [
        ui.kv("{" + str(key) + "}", ui.mono(value) + (f" · {ui.esc(about)}" if about else ""))
        for key, value, about in content.rows(
            "select key, value, description from system_prompt_variables order by key"
        )
    ]
    return ui.card("Prompt variables", "<div>" + "".join(items) + "</div>")


def presets_card() -> str:
    """Slash-command presets: typing the command sends the preset's prompt."""
    found = content.rows(
        "select command, prompt, description from slash_command_presets order by command"
    )
    items = "".join(
        f'<div class="kv" style="flex-direction:column;gap:4px">{ui.mono(cmd)}'
        f'<span class="prompt" style="text-align:left">{ui.esc(prompt)}</span></div>'
        for cmd, prompt, _ in found
    )
    return ui.card("Slash-command presets", items or '<span class="muted">None.</span>')


def screen(prefix: str, slug: str) -> tuple[int, str]:
    """(status, main markup) for the Workspace screen."""
    ws = workspace(slug)
    if ws is None:
        return 404, ui.header("Workspace", "There is no such workspace.")
    rows = [
        ui.row(
            name,
            f"{count} exchange{'s' * (count != 1)} · {content.day_time(last) or 'none yet'}",
            ui.icon("chevron"),
            ui.href(prefix, "thread", ws=ws.slug, id=tid),
        )
        for tid, name, count, last in threads(ws)
    ]
    edits = content.rows("select count(*) from prompt_history where workspaceId = ?", (ws.id,))
    return 200, (
        ui.header("Workspace", f"How the agent in <strong>{ui.esc(ws.name)}</strong> is set up.")
        + model_card(ws)
        + prompt_card(ws)
        + variables_card()
        + presets_card()
        + ui.section("Threads", ui.rows(rows))
        + ui.admin(
            '<section class="card"><div>'
            + ui.kv("Temperature", ui.esc(ws.temp if ws.temp is not None else "provider default"))
            + ui.kv("Chat mode", ui.esc(ws.chat_mode or "chat"))
            + ui.kv("Similarity threshold", ui.esc(ws.threshold))
            + ui.kv("Vector search results", ui.esc(ws.top_n))
            + ui.kv("Vector search mode", ui.esc(ws.search_mode or "default"))
            + ui.kv("Earlier prompt versions kept", ui.esc(edits[0][0] if edits else 0))
            + "</div></section>"
        )
    )
