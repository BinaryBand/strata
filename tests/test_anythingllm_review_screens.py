"""Each /review screen shows what the agent sees, escaped, and keeps server details apart.

Prompts, chats, job prompts, run output, tool schemas, documents, memories and
every file in the agent's folder are shown in full; temperature, service state,
error text and the event log sit in the Admin only part.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from tests._review import CHAT, JOB_PROMPT, OUTPUT, REPLY, SITE, build, load


@pytest.fixture
def review(monkeypatch, tmp_path: Path):
    return load(monkeypatch, build(tmp_path))


def admin_part(page: str) -> str:
    """The page from its Admin only section on."""
    return page[page.index('aria-label="Admin only"') :]


def test_the_overview_shows_the_model_tasks_build_and_counts(review) -> None:
    page = review.render("overview")[1]
    for shown in (
        "Good ",
        "What the agent in <strong>Workshop test</strong> can see.",
        "Instance online",
        "deepseek-flash",
        "Thinking model",
        "Daily news digest",
        "Needs a look",
        "came back as text instead of running",
        "Site build · The Daily Seek",
        "Editions built",
        "14",
        'href="/run?id=2"',
    ):
        assert shown in page, shown
    assert "Running" in admin_part(page)


def test_the_sidebar_splits_the_instance_from_the_workspace(review) -> None:
    page = review.render("tools")[1]
    assert "Whole instance" in page
    assert 'href="/workspace?ws=workshop-test"' in page
    assert 'class="nav on" href="/tools"' in page
    assert '<nav class="tabs"' in page  # the phone's tab bar


def test_a_task_shows_its_whole_prompt_tools_and_runs(review) -> None:
    page = review.render("tasks")[1]
    assert JOB_PROMPT in page
    assert "news-wire, filesystem-write-text-file" in page
    assert "default system prompt, no chat history" in page
    assert "Every day at 05:00 UTC" in page
    assert "site/news/editions/2026-09-24/001-harbour.toml" in page  # writes to
    assert 'href="/run?id=1"' in page
    assert "server &lt;boom&gt;" not in page


def test_a_run_shows_the_reply_every_call_and_the_leak(review) -> None:
    status, main = review.review_run.run_view("", "2")
    assert status == 200
    assert "Needs a look." in main
    assert "Writing." in main
    assert OUTPUT in main
    assert "feeds: sources.toml" in main
    assert "Leaked as text · DSML" in main
    assert "filesystem-write-text-file" in main
    assert "&lt;DSML invoke" in main
    assert "Checking the feeds first." in main
    assert "server &lt;boom&gt;" in admin_part(main)
    status, main = review.review_run.run_view("", "1")
    assert "content: 400 B of text" in main  # long arguments are shown as a size
    assert "Leaked" not in main


def test_tools_show_the_parameters_the_model_sees(review) -> None:
    page = review.render("tools")[1]
    assert "news-wire" in page
    assert "Feed &lt;list&gt; path" in page
    assert "filesystem-read-text-file" in page
    assert "filesystem-move-file" not in page  # switched off one by one
    assert "Built-in and switched off: Web Browsing" in page
    assert "feed-cache" in page
    assert "Starts only when switched on" in page
    assert "edition-check" in page
    assert "Which day" in page
    assert ">fixed<" not in page  # static flow variables are hidden from the model
    assert "npx" not in page


def test_the_workspace_shows_the_prompt_variables_presets_and_threads(review) -> None:
    status, main = review.review_workspace.screen("", "workshop-test")
    assert status == 200
    assert "You are the &lt;Workshop&gt; agent." in main
    assert "Edited from default" in main
    assert "The default prompt." in main
    assert "{datetime}" in main
    assert "Night desk" in main
    assert "/digest" in main
    assert "Last 2 exchanges of a thread; an agent session gets the last 20" in main
    assert "Layout &lt;ideas&gt;" in main
    assert "Temperature" in admin_part(main)


def test_a_thread_marks_what_is_in_the_agents_context(review) -> None:
    status, main = review.review_thread.view("", "workshop-test", "default")
    assert status == 200
    assert f"{CHAT} 1" in main
    assert f"{REPLY} 3" in main
    context = main[main.index('class="ctx"') :]
    assert f"{CHAT} 1" not in context  # history is 2: only exchanges 2 and 3 are sent
    assert f"{CHAT} 2" in context
    assert "an agent session still gets the last 20" in main
    status, main = review.review_thread.view("", "workshop-test", "7")
    assert "Thread reply" in main
    assert f"{CHAT} 1" not in main


def test_knowledge_shows_documents_and_memories(review) -> None:
    status, main = review.review_knowledge.screen("", "workshop-test")
    assert status == 200
    assert "Guide" in main
    assert "2 passages" in main
    assert "Always included" in main
    assert "The weather box stays left." in main
    status, main = review.review_knowledge.doc_view("", "1")
    assert "The whole &lt;guide&gt; text." in main


def test_knowledge_has_empty_states(monkeypatch, tmp_path: Path) -> None:
    root = build(tmp_path)
    db = sqlite3.connect(root / "storage" / "anythingllm.db")
    db.execute("delete from workspace_documents")
    db.execute("delete from memories")
    db.commit()
    db.close()
    review = load(monkeypatch, root)
    main = review.review_knowledge.screen("", "")[1]
    assert "No documents yet" in main
    assert "No memories saved" in main


def test_files_open_on_the_agent_folder_and_every_file_opens(review) -> None:
    status, main = review.review_files.screen("", "")
    assert status == 200
    assert "agent folder" in main
    assert "file?path=storage%2Fanythingllm-fs%2Flogo.bin" in main
    assert "Agent-written" in main


def test_toml_is_formatted_and_checked_against_the_build(review) -> None:
    view = review.review_viewer.file_view
    status, main = view("", "storage/anythingllm-fs/site/news/editions/2026-09-24/001-harbour.toml")
    assert status == 200
    assert "TOML · formatted" in main
    assert '<span class="s">&quot;Harbour &lt;strike&gt; ends&quot;</span>' in main
    assert "[summary]" in main
    assert "Valid" in main
    assert "Written " in main
    assert "by Daily news digest" in main
    status, main = view("", "storage/anythingllm-fs/site/news/editions/2026-09-24/002-bad.toml")
    assert "TOML · not valid" in main
    assert "&lt;b&gt;bad&lt;/b&gt; TOML" in main
    assert "Skipped" in main


def test_text_is_escaped_and_binary_shows_hex(review) -> None:
    view = review.review_viewer.file_view
    main = view("", "storage/anythingllm-fs/site/FORMAT.md")[1]
    assert "&lt;b&gt;bold&lt;/b&gt;" in main
    assert "Placed by strata" in main
    main = view("", "storage/anythingllm-fs/logo.bin")[1]
    assert "Binary" in main
    assert "89 50 4e 47 00" in main


def test_artifacts_link_to_the_site_origin_and_list_research(review) -> None:
    page = review.render("artifacts")[1]
    assert f'href="{SITE}/news/"' in page
    assert "Trip &lt;report&gt;" in page
    assert "Feed licences?" in page
    assert "Passed" in page
    assert "sent_chat" in admin_part(page)


def test_a_current_link_outside_the_releases_is_not_followed(monkeypatch, tmp_path: Path) -> None:
    root = build(tmp_path)
    review = load(monkeypatch, root)
    current = root / "site-public" / "current"
    current.unlink()
    current.symlink_to(root / "storage")
    assert review.review_artifacts.publications() == []


def test_story_sources_show_failing_hosts_first_and_no_story_text(
    monkeypatch, tmp_path: Path
) -> None:
    root = build(tmp_path)
    cache = root / "story-cache"
    cache.mkdir()
    (cache / "health.json").write_text(
        json.dumps(
            {
                "npr.org": {"ok": 4, "failed": 0, "streak": 0, "last_ok": "2026-09-24T09:00"},
                "pbs.org": {"ok": 0, "failed": 3, "streak": 3, "last_error": "<i>403</i>"},
            }
        )
    )
    (cache / "abc.json").write_text(
        json.dumps({"day": "2026-09-24", "paragraphs": ["SECRET STORY TEXT"], "model_seconds": 2.4})
    )
    review = load(monkeypatch, root)
    page = review.render("artifacts")[1]
    assert page.index("pbs.org") < page.index("npr.org")
    assert "&lt;i&gt;403&lt;/i&gt;" in page
    assert "Failing" in page
    assert "write 2.4 s" in page
    assert "SECRET STORY TEXT" not in page


def test_the_more_tab_lists_the_screens_without_a_tab(review) -> None:
    page = review.render("more")[1]
    assert 'href="/artifacts"' in page
    assert 'href="/files"' in page
    assert 'href="/knowledge?ws=workshop-test"' in page
