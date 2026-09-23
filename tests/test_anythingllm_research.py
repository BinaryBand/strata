"""The research skill's AnythingLLM tool keeps evidence out of the agent's reach.

A run lives outside the File System tools' root, the agent can write only a
brief, a handback or the report there, every write reports its saved hash, and
a report is published only after `check` passes. The engine is a stand-in
(tests/fixtures/anythingllm_research/fake_research.py) that records its calls.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HANDLER = ROOT / "ansible" / "playbooks" / "files" / "anythingllm-research"
FIXTURES = ROOT / "tests" / "fixtures" / "anythingllm_research"
NODE = shutil.which("node")
REPORT = "# Title\n\n## Verdict\n\nJudges agree with raters. Confidence: 70%\n\n## Sources\n"


@pytest.fixture
def skill(tmp_path: Path) -> Path:
    assert NODE, "node is required to test the research skill"
    skill_dir = tmp_path / "skill"
    engine = skill_dir / "engine" / "contracts"
    engine.mkdir(parents=True)
    shutil.copy(HANDLER / "handler.js", skill_dir / "handler.js")
    shutil.copy(FIXTURES / "fake_research.py", skill_dir / "engine" / "research.py")
    (skill_dir / "engine" / "SKILL.md").write_text("# Research\nYou are the lead.\n")
    for name in ("sweep.md", "brief.md", "final.md"):
        (engine / name).write_text(f"# {name}\n")
    (tmp_path / "storage").mkdir()
    return skill_dir


def run(skill: Path, *calls: dict) -> list[str]:
    calls_file = skill.parent / "calls.json"
    calls_file.write_text(json.dumps(list(calls)))
    result = subprocess.run(
        [str(NODE), str(FIXTURES / "harness.mjs"), str(skill), str(calls_file)],
        capture_output=True,
        text=True,
        env={**os.environ, "STORAGE_DIR": str(skill.parent / "storage")},
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def engine_calls(skill: Path) -> list[dict]:
    log = skill / "engine" / "calls.jsonl"
    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


def test_guide_prefaces_the_skill_files(skill: Path) -> None:
    [text] = run(skill, {"action": "guide"})
    assert text.startswith("You are running the research skill below inside AnythingLLM.")
    assert "You are the lead." in text
    assert "===== contracts/sweep.md =====" in text


def test_runs_live_outside_the_file_tools_root_and_search_uses_duckduckgo(skill: Path) -> None:
    run(
        skill,
        {"action": "init", "run": "judges"},
        {"action": "search", "run": "judges", "query": "q", "counter": True},
    )
    init, search = engine_calls(skill)
    runs = skill.parent / "storage" / "research-runs" / "judges"
    assert init["argv"][:3] == ["init", "--run", str(runs)]
    assert "--counter" in search["argv"]
    assert {init["engine"], search["engine"]} == {"duckduckgo"}
    assert not (skill.parent / "storage" / "anythingllm-fs").exists()


@pytest.mark.parametrize("slug", ["../escape", "a", "Judges", "x/y"])
def test_a_bad_run_name_is_rejected_before_the_engine_runs(skill: Path, slug: str) -> None:
    [text] = run(skill, {"action": "init", "run": slug})
    assert text.startswith("Rejected")
    assert engine_calls(skill) == []


@pytest.mark.parametrize(
    "file",
    [
        "ledger.jsonl",
        "sources/abc.txt",
        "budget.json",
        "../x.md",
        "briefs/1.md",
        "reports/other.md",
    ],
)
def test_write_refuses_anything_but_a_brief_a_handback_or_the_report(
    skill: Path, file: str
) -> None:
    run(skill, {"action": "init", "run": "judges"})
    [text] = run(skill, write(file, "x"))
    assert text.startswith("Rejected")


def test_write_reports_the_saved_size_and_hash(skill: Path) -> None:
    [_, text] = run(
        skill,
        {"action": "init", "run": "judges"},
        write("briefs/01.md", "# Brief 01"),
    )
    digest = hashlib.sha256(b"# Brief 01").hexdigest()
    assert text == f"saved briefs/01.md: 10 bytes, sha256 {digest}"


def write(file: str, content: str, **extra: int) -> dict:
    return {"action": "write", "run": "judges", "file": file, "content": content, **extra}


def test_a_file_sent_in_parts_is_saved_once_the_last_part_arrives(skill: Path) -> None:
    [_, first] = run(
        skill,
        {"action": "init", "run": "judges"},
        write("reports/final.md", "Part one. ", part=1, parts=2),
    )
    [second] = run(skill, write("reports/final.md", "Part two.", part=2, parts=2))
    assert first.startswith("part 1 of 2 received")
    assert second.startswith("saved reports/final.md")
    [text] = run(skill, {"action": "read", "run": "judges", "file": "reports/final.md"})
    assert text == "Part one. Part two."


def test_an_invalid_handback_is_not_saved(skill: Path) -> None:
    [_, text, back] = run(
        skill,
        {"action": "init", "run": "judges"},
        write("handbacks/01.json", "{not json"),
        {"action": "read", "run": "judges", "file": "handbacks/01.json"},
    )
    assert "not valid JSON" in text
    assert back == "handbacks/01.json does not exist in this run."


def test_finish_publishes_only_a_report_that_passes_check(skill: Path) -> None:
    published = skill.parent / "storage" / "anythingllm-fs" / "research" / "judges.md"
    [_, _, failed] = run(
        skill,
        {"action": "init", "run": "judges"},
        write("reports/final.md", REPORT + "FAIL"),
        {"action": "finish", "run": "judges"},
    )
    assert failed.startswith("Not finished: check failed")
    assert not published.exists()

    [_, passed] = run(
        skill,
        write("reports/final.md", REPORT),
        {"action": "finish", "run": "judges"},
    )
    assert passed.startswith("check: passed\nReport: research/judges.md")
    assert "Judges agree with raters. Confidence: 70%" in passed
    assert published.read_text() == REPORT


def test_the_exit_code_comes_back_with_its_meaning(skill: Path) -> None:
    [_, text] = run(
        skill,
        {"action": "init", "run": "judges"},
        {"action": "search", "run": "judges", "query": "refused"},
    )
    assert text.startswith("exit 4 (the search or fetch failed: that URL is not citable)")
