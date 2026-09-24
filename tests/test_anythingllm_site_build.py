"""The site builder publishes only validated agent content, and never a half-built site.

The agent writes TOML data files; the builder validates them, composes every
line of Zola front matter itself, and publishes a build by switching a link.
These tests drive validate.py and build.py with a stand-in `zola` that can be
told to fail, so a failed build is shown to leave the last good release live.
"""

from __future__ import annotations

import importlib
import json
import sys
import tomllib
from pathlib import Path

import pytest

FILES = Path(__file__).resolve().parents[1] / "ansible" / "playbooks" / "files"
BUILDER = FILES / "anythingllm-site-build"
DAY = "2026-09-25"
STORY = """headline = "A headline"
region = "America"
lead = {lead}
rank = {rank}
summary = "One sentence."
sources = [{{ name = "NPR", url = "https://www.npr.org/a" }}]
"""
EDITION = f'date = "{DAY}"\nfeeds_total = 11\nfeed_errors = []\n'
STUB_ZOLA = """#!/usr/bin/env python3
import os, sys
if os.path.exists(os.path.join(os.path.dirname(os.path.abspath(__file__)), "FAIL")):
    sys.stderr.write("stub zola: build failed\\n")
    sys.exit(1)
out = sys.argv[sys.argv.index("--output-dir") + 1]
os.makedirs(out, exist_ok=True)
open(os.path.join(out, "index.html"), "w").write("built")
"""


@pytest.fixture
def modules(monkeypatch, tmp_path: Path):
    """validate and build, fresh, pointed at a temporary source, skeleton and public folder."""
    monkeypatch.syspath_prepend(str(BUILDER))
    for name in ("validate", "build"):
        sys.modules.pop(name, None)
    validate = importlib.import_module("validate")
    build = importlib.import_module("build")
    source, skeleton, public = tmp_path / "site", tmp_path / "skeleton", tmp_path / "public"
    for d in (source / "news" / "editions" / DAY, skeleton / "templates", public):
        d.mkdir(parents=True)
    (skeleton / "config.toml").write_text('base_url = "x"\n')
    (source / "news" / "style.css").write_text("body{}")
    zola = tmp_path / "zola"
    zola.write_text(STUB_ZOLA)
    zola.chmod(0o755)
    for attr, value in (
        ("SOURCE", source),
        ("SKELETON", skeleton),
        ("PUBLIC", public),
        ("ZOLA", str(zola)),
    ):
        monkeypatch.setattr(build, attr, value)
    return validate, build, source


def write_edition(source: Path, stories: dict[str, str], *, edition: str | None = EDITION) -> Path:
    folder = source / "news" / "editions" / DAY
    for name, body in stories.items():
        (folder / name).write_text(body)
    if edition is not None:
        (folder / "edition.toml").write_text(edition)
    return folder


def front(text: str) -> dict:
    """The TOML between a generated file's +++ lines, parsed."""
    return tomllib.loads(text.split("+++")[1])


def test_a_valid_edition_becomes_one_section_with_its_stories_as_data(modules) -> None:
    validate, _, source = modules
    write_edition(
        source,
        {
            "01-a.toml": STORY.format(lead="true", rank=1),
            "02-b.toml": STORY.format(lead="false", rank=2),
        },
    )
    result = validate.collect(source)
    assert result.rejected == []
    meta = front(result.files[f"news/{DAY}/_index.md"])
    assert meta["template"] == "news/edition.html"
    assert [s["rank"] for s in meta["extra"]["stories"]] == [1, 2]
    assert not any(path.endswith("01-a.md") for path in result.files)  # stories are not pages


def test_an_edition_without_edition_toml_waits(modules) -> None:
    validate, _, source = modules
    write_edition(source, {"01-a.toml": STORY.format(lead="true", rank=1)}, edition=None)
    result = validate.collect(source)
    assert result.waiting == [f"news/editions/{DAY}"]
    assert f"news/{DAY}/_index.md" not in result.files


@pytest.mark.parametrize(
    ("body", "reason"),
    [
        (
            STORY.format(lead="true", rank=1).replace('summary = "One sentence."\n', ""),
            "missing summary",
        ),
        (STORY.format(lead="true", rank=1).replace('"America"', '"Mars"'), "region must be"),
        (
            STORY.format(lead="true", rank=1).replace(
                "https://www.npr.org/a", "javascript:alert(1)"
            ),
            "http(s)",
        ),
        (
            STORY.format(lead="true", rank=1).replace(
                '"https://www.npr.org/a"', "'https://x\" onmouseover=\"y'"
            ),
            "http(s)",
        ),
        (STORY.format(lead="true", rank=1) + 'template = "page.html"\n', "unknown field template"),
        (STORY.format(lead="true", rank=1).replace("rank = 1", "rank = 0"), "rank must be"),
        ("headline = ", "not valid TOML"),
        (STORY.format(lead="true", rank=1) + "x = '" + "a" * 17000 + "'\n", "over 16384 bytes"),
    ],
    ids=[
        "missing",
        "region",
        "js-url",
        "quote-url",
        "template-field",
        "rank",
        "bad-toml",
        "oversize",
    ],
)
def test_an_invalid_story_is_skipped_with_its_reason(modules, body: str, reason: str) -> None:
    validate, _, source = modules
    write_edition(source, {"01-lead.toml": STORY.format(lead="true", rank=1), "02-bad.toml": body})
    result = validate.collect(source)
    reasons = dict(result.rejected)
    assert reason in reasons[f"news/editions/{DAY}/02-bad.toml"]
    assert f"news/{DAY}/_index.md" in result.files  # the rest of the edition still builds


def test_one_file_may_hold_several_stories(modules) -> None:
    validate, _, source = modules
    tables = "".join(
        "[[story]]\n" + STORY.format(lead=lead, rank=rank)
        for lead, rank in (("true", 1), ("false", 3), ("false", 2))
    )
    write_edition(source, {"01-america.toml": tables})
    meta = front(validate.collect(source).files[f"news/{DAY}/_index.md"])
    assert [s["rank"] for s in meta["extra"]["stories"]] == [1, 2, 3]


def test_one_bad_story_in_a_list_skips_its_file_and_names_it(modules) -> None:
    validate, _, source = modules
    bad = "[[story]]\n" + STORY.format(lead="false", rank=2) + "[[story]]\nheadline = 'x'\n"
    write_edition(source, {"01-lead.toml": STORY.format(lead="true", rank=1), "02-world.toml": bad})
    result = validate.collect(source)
    assert dict(result.rejected)[f"news/editions/{DAY}/02-world.toml"].startswith(
        "story 2: missing"
    )
    assert f"news/{DAY}/_index.md" in result.files


def test_two_leads_skip_the_whole_edition(modules) -> None:
    validate, _, source = modules
    write_edition(
        source,
        {
            "01-a.toml": STORY.format(lead="true", rank=1),
            "02-b.toml": STORY.format(lead="true", rank=2),
        },
    )
    result = validate.collect(source)
    assert f"news/{DAY}/_index.md" not in result.files
    assert "exactly one lead" in dict(result.rejected)[f"news/editions/{DAY}"]


def test_markup_and_quotes_in_text_stay_text_in_valid_front_matter(modules) -> None:
    validate, _, source = modules
    tricky = 'Say "hi" <script>alert(1)</script> \\ +++ & ünïcode\nnew line'
    story = STORY.format(lead="true", rank=1).replace('"One sentence."', json.dumps(tricky))
    write_edition(source, {"01-a.toml": story})
    meta = front(validate.collect(source).files[f"news/{DAY}/_index.md"])
    assert meta["extra"]["stories"][0]["summary"] == tricky


def test_a_symlinked_story_is_refused(modules, tmp_path: Path) -> None:
    validate, _, source = modules
    secret = tmp_path / "secret.toml"
    secret.write_text(STORY.format(lead="false", rank=2))
    folder = write_edition(source, {"01-a.toml": STORY.format(lead="true", rank=1)})
    (folder / "02-link.toml").symlink_to(secret)
    assert (
        "cannot be opened"
        in dict(validate.collect(source).rejected)[f"news/editions/{DAY}/02-link.toml"]
    )


@pytest.mark.parametrize(
    ("body", "outcome"),
    [
        (
            "Plain *Markdown* with [a link](https://example.com) and [mail](mailto:a@b.c).",
            "accepted",
        ),
        ("<b>bold</b>", "rejected"),
        ("{{ load_data(url='https://example.com') }}", "rejected"),
        ("[x](javascript:alert(1))", "rejected"),
        ("![i](data:image/png;base64,AA)", "rejected"),
        ("[r]: javascript:alert(1)", "rejected"),
    ],
    ids=["plain", "html", "template", "js-link", "data-image", "js-reference"],
)
def test_publication_pages_allow_only_plain_markdown(modules, body: str, outcome: str) -> None:
    validate, _, source = modules
    pub = source / "trip-report"
    pub.mkdir()
    (pub / "publication.toml").write_text('title = "Trip report"\n')
    (pub / "day-one.md").write_text(f'+++\ntitle = "Day one"\n+++\n{body}\n')
    result = validate.collect(source)
    assert ("trip-report/day-one.md" in result.files) is (outcome == "accepted")


def test_a_successful_build_switches_current_and_reports(modules) -> None:
    _, build, source = modules
    write_edition(source, {"01-a.toml": STORY.format(lead="true", rank=1)})
    assert build.build_once()
    current = build.PUBLIC / "current"
    assert current.is_symlink()
    assert (current / "index.html").read_text() == "built"
    assert "Result: published" in (source / "BUILD.md").read_text()
    assert json.loads((build.PUBLIC / "status.json").read_text())["ok"] is True


def test_a_failed_build_leaves_the_last_good_release_live(modules, tmp_path: Path) -> None:
    _, build, source = modules
    write_edition(source, {"01-a.toml": STORY.format(lead="true", rank=1)})
    assert build.build_once()
    live = (build.PUBLIC / "current").readlink()
    (tmp_path / "FAIL").write_text("")  # tells the stand-in zola to fail
    assert not build.build_once()
    assert (build.PUBLIC / "current").readlink() == live
    assert "FAILED, the previous build is still live" in (source / "BUILD.md").read_text()
    assert (
        "stub zola: build failed" in json.loads((build.PUBLIC / "status.json").read_text())["log"]
    )


def test_deleting_a_file_changes_the_fingerprint(modules) -> None:
    _, build, source = modules
    folder = write_edition(source, {"01-a.toml": STORY.format(lead="true", rank=1)})
    before = build.fingerprint()
    (folder / "01-a.toml").unlink()
    assert build.fingerprint() != before


def test_story_pages_link_headlines_and_publish_the_story_list(modules, monkeypatch) -> None:
    _, build, source = modules
    write_edition(
        source,
        {
            "01-a.toml": STORY.format(lead="false", rank=2),
            "02-b.toml": STORY.format(lead="true", rank=1),
        },
    )
    monkeypatch.setattr(build, "STORY_BASE", "/story")
    assert build.build_once()
    listed = json.loads((build.PUBLIC / "stories" / f"{DAY}.json").read_text())
    assert [(s["rank"], s["page"]) for s in listed] == [
        (1, f"/story/{DAY}/1"),
        (2, f"/story/{DAY}/2"),
    ]
    (source / "news" / "editions" / DAY / "edition.toml").unlink()
    assert build.build_once()
    assert not (build.PUBLIC / "stories" / f"{DAY}.json").exists()  # a day no longer built


def test_without_story_pages_headlines_keep_their_source_links(modules) -> None:
    validate, _, source = modules
    write_edition(source, {"01-a.toml": STORY.format(lead="true", rank=1)})
    meta = front(validate.collect(source).files[f"news/{DAY}/_index.md"])
    assert "page" not in meta["extra"]["stories"][0]
