"""Pictures reach a page only when the builder itself has checked them.

The agent's picture-desk skill writes news/images/<id>.<ext> and a record
<id>.toml. The builder trusts none of it: names, magic numbers, pixel sizes and
record fields are checked again, and a picture that fails only loses the
picture, never the story or the edition.
"""

from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest

from tests.test_anythingllm_site_build import DAY, STORY, front, modules, write_edition

__all__ = ["modules"]  # the fixture, imported for pytest

RECORD = """description = "Harbour cranes at dusk"
tags = ["port", "trade"]
creator = "Jane Doe"
source_url = "https://commons.wikimedia.org/wiki/File:Cranes.jpg"
license = "{license}"
added = 2026-09-20
active = {active}
"""


def png(width: int = 640, height: int = 360) -> bytes:
    return b"\x89PNG\r\n\x1a\n" + struct.pack(">I4sII", 13, b"IHDR", width, height) + b"\0" * 40


def jpeg(width: int = 640, height: int = 360) -> bytes:
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\0" + b"\0" * 9
    sof = b"\xff\xc0" + struct.pack(">HBHHB", 17, 8, height, width, 3) + b"\0" * 9
    return b"\xff\xd8" + app0 + sof + b"\xff\xda" + b"\0" * 20


def webp(width: int = 640, height: int = 360) -> bytes:
    vp8x = b"VP8X" + struct.pack("<I", 10) + b"\0" * 4
    dims = (width - 1).to_bytes(3, "little") + (height - 1).to_bytes(3, "little")
    return b"RIFF" + struct.pack("<I", 30) + b"WEBP" + vp8x + dims + b"\0" * 10


def add_picture(
    source: Path, image_id: str, data: bytes, ext: str = "png", *, active: bool = True
) -> None:
    folder = source / "news" / "images"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{image_id}.{ext}").write_bytes(data)
    record = RECORD.format(license="cc0", active=str(active).lower())
    (folder / f"{image_id}.toml").write_text(record)


def pictured_story(image_id: str) -> str:
    return STORY.format(lead="true", rank=1) + f'image = "{image_id}"\n'


def stories_of(result) -> list[dict]:
    return front(result.files[f"news/{DAY}/_index.md"])["extra"]["stories"]


@pytest.mark.parametrize(("ext", "data"), [("png", png()), ("jpg", jpeg()), ("webp", webp())])
def test_a_checked_picture_is_credited_and_published(modules, ext, data) -> None:
    validate, build, source = modules
    add_picture(source, "harbour-cranes", data, ext)
    write_edition(source, {"01-a.toml": pictured_story("harbour-cranes")})
    result = validate.collect(source)
    assert result.rejected == []
    assert stories_of(result)[0]["image"] == {
        "file": f"harbour-cranes.{ext}",
        "credit": "Jane Doe",
        "source": "https://commons.wikimedia.org/wiki/File:Cranes.jpg",
        "license": "CC0",
    }
    assert result.images == {f"harbour-cranes.{ext}": data}
    project = source.parent / "project"
    build.assemble(project, result)
    assert (project / "static" / "news" / "images" / f"harbour-cranes.{ext}").read_bytes() == data


def test_the_story_service_gets_the_resolved_picture(modules) -> None:
    _, build, source = modules
    add_picture(source, "harbour-cranes", png())
    write_edition(source, {"01-a.toml": pictured_story("harbour-cranes")})
    assert build.build_once()
    stories = json.loads((build.PUBLIC / "stories" / f"{DAY}.json").read_text())
    assert stories[0]["image"]["file"] == "harbour-cranes.png"


@pytest.mark.parametrize(
    ("image_id", "data", "ext", "reason"),
    [
        ("fake-png", b"GIF89a" + b"\0" * 40, "png", "not a PNG image"),
        ("wrong-ext", png(), "jpg", "not a JPEG image"),
        ("huge", png(9000, 100), "png", "1-6000 pixels a side"),
        ("heavy", png() + b"\0" * (1600 * 1024), "png", "over"),
    ],
)
def test_a_bad_picture_loses_only_the_picture(modules, image_id, data, ext, reason) -> None:
    validate, _, source = modules
    add_picture(source, image_id, data, ext)
    write_edition(source, {"01-a.toml": pictured_story(image_id)})
    result = validate.collect(source)
    rejected = dict(result.rejected)
    assert reason in rejected[f"news/images/{image_id}"]
    assert "runs without it" in rejected[f"news/editions/{DAY}"]
    assert "image" not in stories_of(result)[0]  # the story and its edition still built
    assert result.images == {}


def test_a_linked_picture_is_refused(modules, tmp_path) -> None:
    validate, _, source = modules
    add_picture(source, "linked", png())
    outside = tmp_path / "secret.png"
    outside.write_bytes(png())
    (source / "news" / "images" / "linked.png").unlink()
    (source / "news" / "images" / "linked.png").symlink_to(outside)
    result = validate.collect(source)
    assert "a link" in dict(result.rejected)["news/images/linked"]


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        (('license = "cc0"', 'license = "cc-by"'), "license must be one of"),
        (('source_url = "https://', 'source_url = "javascript://'), "source_url must be"),
        (("active = true", 'active = "yes"'), "active must be"),
        (("active = true", "active = true\nextra = 1"), "unknown field extra"),
    ],
)
def test_a_bad_record_is_refused(modules, change, reason) -> None:
    validate, _, source = modules
    add_picture(source, "cranes", png())
    record = source / "news" / "images" / "cranes.toml"
    record.write_text(record.read_text().replace(*change))
    result = validate.collect(source)
    assert reason in dict(result.rejected)["news/images/cranes"]


def test_names_outside_the_pattern_are_refused(modules) -> None:
    validate, _, source = modules
    folder = source / "news" / "images"
    folder.mkdir(parents=True)
    for name in ("Upper.png", "a.b.png", "page.html", "x"):
        (folder / name).write_bytes(png())
    rejected = dict(validate.collect(source).rejected)
    for name in ("Upper.png", "a.b.png", "page.html", "x"):
        assert "named id.toml" in rejected[f"news/images/{name}"]


def test_an_image_without_its_record_waits_and_temp_files_are_ignored(modules) -> None:
    validate, _, source = modules
    folder = source / "news" / "images"
    folder.mkdir(parents=True)
    (folder / "mid-swap.png").write_bytes(png())
    (folder / ".mid-swap.toml.tmp").write_text("partial")
    result = validate.collect(source)
    assert "news/images/mid-swap.png" in result.waiting
    assert result.rejected == []


def test_a_retired_picture_still_shows_where_an_edition_uses_it(modules) -> None:
    validate, _, source = modules
    add_picture(source, "old-cranes", png(), active=False)
    add_picture(source, "unused-retired", png(), active=False)
    write_edition(source, {"01-a.toml": pictured_story("old-cranes")})
    result = validate.collect(source)
    assert stories_of(result)[0]["image"]["file"] == "old-cranes.png"
    assert set(result.images) == {"old-cranes.png"}  # the unused retired one is not published


def test_pictures_editions_use_are_read_first_under_the_cap(modules, monkeypatch) -> None:
    validate, _, source = modules
    monkeypatch.setattr(validate.pictures, "MAX_IMAGES", 1)
    add_picture(source, "aaa-first", png())
    add_picture(source, "zzz-used", png())
    write_edition(source, {"01-a.toml": pictured_story("zzz-used")})
    result = validate.collect(source)
    assert stories_of(result)[0]["image"]["file"] == "zzz-used.png"
    assert "news/images/aaa-first.toml (over 1 images)" in result.waiting


def test_a_malformed_image_id_or_want_rejects_the_story_file(modules) -> None:
    validate, _, source = modules
    write_edition(
        source,
        {
            "01-a.toml": STORY.format(lead="true", rank=1) + 'image = "../style"\n',
            "02-b.toml": STORY.format(lead="false", rank=2) + f'image_want = "{"x" * 201}"\n',
        },
    )
    rejected = dict(validate.collect(source).rejected)
    assert "image must be the id" in rejected[f"news/editions/{DAY}/01-a.toml"]
    assert "image_want must be text" in rejected[f"news/editions/{DAY}/02-b.toml"]


def test_image_want_is_accepted_and_never_published(modules) -> None:
    validate, _, source = modules
    body = STORY.format(lead="true", rank=1) + 'image_want = "flooded city street"\n'
    write_edition(source, {"01-a.toml": body})
    result = validate.collect(source)
    assert result.rejected == []
    assert "image_want" not in stories_of(result)[0]
