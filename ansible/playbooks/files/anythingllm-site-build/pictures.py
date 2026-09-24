"""The paper's picture bucket: news/images/<id>.<ext> and its record <id>.toml.

The agent's picture-desk skill downloads public-domain photos and writes each
as an image plus a TOML record, image first and record last, so a record's
presence marks a finished pair. Nothing here trusts that convention: every
name, extension, magic number, pixel size and record field is checked again,
and output names are built only from checked values. Standard library only.

    news/images/<id>.jpg|png|webp   the photo
    news/images/<id>.toml           description, tags, creator, source_url,
                                    license, added, active[, openverse_id]
"""

from __future__ import annotations

import datetime as dt
import re
import struct
from dataclasses import dataclass
from pathlib import Path

from common import Invalid, Result, keys, load_toml, names, read_no_follow, text, texts

FOLDER = "news/images"
IMAGE_ID = re.compile(r"[a-z0-9][a-z0-9-]{1,40}")
URL = re.compile(r"https?://[^\s\"'<>\\]{1,2000}")
LICENSES = {"cc0": "CC0", "pdm": "public domain"}
FORMATS = {"jpg": "JPEG", "png": "PNG", "webp": "WebP"}
EXTENSIONS = tuple(FORMATS)
MAX_IMAGE_BYTES = 1536 * 1024
MAX_RECORD_BYTES = 4 * 1024
MAX_SIDE = 6000
# Retired images are never deleted, so the bucket only grows: about three a
# week is a decade before this. Images an edition shows are read first.
MAX_IMAGES = 2000
# Header bytes the pixel size is read from.
MARK = 0xFF  # every JPEG marker starts with it
START_OF_SCAN = 0xDA  # JPEG image data follows; the frame header comes before it
VP8L_SIGNATURE = 0x2F
WEBP_HEADER = 30  # RIFF header plus the first chunk's size fields
# JPEG start-of-frame markers, which carry the pixel size.
SOF = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}


@dataclass(frozen=True)
class Image:
    """One checked photo: its published file name, bytes and credit."""

    file: str
    data: bytes
    creator: str
    source: str
    license: str
    active: bool


def size_of(ext: str, data: bytes) -> tuple[int, int]:
    """(width, height) read from the header of a `ext` file, or Invalid."""
    if ext == "png" and data[:8] == b"\x89PNG\r\n\x1a\n" and data[12:16] == b"IHDR":
        return struct.unpack(">II", data[16:24])
    if ext == "webp" and data[:4] == b"RIFF" and data[8:12] == b"WEBP" and len(data) >= WEBP_HEADER:
        chunk = data[12:16]
        if chunk == b"VP8 " and data[23:26] == b"\x9d\x01\x2a":
            w, h = struct.unpack("<HH", data[26:30])
            return w & 0x3FFF, h & 0x3FFF
        if chunk == b"VP8L" and data[20] == VP8L_SIGNATURE:
            bits = int.from_bytes(data[21:25], "little")
            return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
        if chunk == b"VP8X":
            w = int.from_bytes(data[24:27], "little") + 1
            return w, int.from_bytes(data[27:30], "little") + 1
    if ext == "jpg" and data[:3] == b"\xff\xd8\xff":
        return jpeg_size(data)
    msg = f"not a {FORMATS[ext]} image"
    raise Invalid(msg)


def jpeg_size(data: bytes) -> tuple[int, int]:
    """(width, height) from a JPEG's start-of-frame segment, or Invalid."""
    at = 2
    while at + 4 <= len(data):
        if data[at] != MARK:
            break
        marker = data[at + 1]
        if marker == MARK:  # fill byte
            at += 1
            continue
        if marker in {0x01, *range(0xD0, 0xD8)}:  # no length follows
            at += 2
            continue
        (length,) = struct.unpack(">H", data[at + 2 : at + 4])
        if marker in SOF and at + 9 <= len(data):
            h, w = struct.unpack(">HH", data[at + 5 : at + 9])
            return w, h
        if marker == START_OF_SCAN:  # no frame header came first
            break
        at += 2 + length
    msg = "not a JPEG image with a readable size"
    raise Invalid(msg)


def photo(root: Path, ext: str, image_id: str) -> bytes:
    """The checked bytes of news/images/<id>.<ext>, or Invalid."""
    data = read_no_follow(root, f"{FOLDER}/{image_id}.{ext}", MAX_IMAGE_BYTES)
    width, height = size_of(ext, data)
    if not (1 <= width <= MAX_SIDE and 1 <= height <= MAX_SIDE):
        msg = f"image must be 1-{MAX_SIDE} pixels a side, not {width}x{height}"
        raise Invalid(msg)
    return data


def record(data: dict) -> dict:
    """A checked image record."""
    keys(
        data,
        {"description", "tags", "creator", "source_url", "license", "added", "active"},
        {"openverse_id"},
    )
    source = data["source_url"]
    if not isinstance(source, str) or not URL.fullmatch(source):
        msg = "source_url must be an http(s) address with no spaces or quotes"
        raise Invalid(msg)
    if data["license"] not in LICENSES:
        msg = f"license must be one of: {', '.join(LICENSES)}"
        raise Invalid(msg)
    if not isinstance(data["added"], dt.date) and not (
        isinstance(data["added"], str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", data["added"])
    ):
        msg = "added must be a date, YYYY-MM-DD"
        raise Invalid(msg)
    if not isinstance(data["active"], bool):
        msg = "active must be true or false"
        raise Invalid(msg)
    text(data["description"], "description", 200)
    texts(data["tags"], "tags", 8, 40)
    if "openverse_id" in data:
        text(data["openverse_id"], "openverse_id", 64)
    return {
        "creator": text(data["creator"], "creator", 120),
        "source": source,
        "license": LICENSES[data["license"]],
        "active": data["active"],
    }


def bucket(root: Path, result: Result) -> dict[str, list[str]]:
    """Each well-named id in news/images with its extensions; every other entry rejected."""
    folder = root / FOLDER
    found: dict[str, list[str]] = {}
    if not folder.is_dir() or folder.is_symlink():
        return found
    for name in names(folder):
        if name.startswith("."):  # the skill's temporary files, mid-write
            continue
        stem, _, ext = name.rpartition(".")
        if not IMAGE_ID.fullmatch(stem) or ext not in (*EXTENSIONS, "toml"):
            why = f"files here are named id.toml and id.{'/'.join(EXTENSIONS)}"
            result.rejected.append((f"{FOLDER}/{name}", why))
            continue
        found.setdefault(stem, []).append(ext)
    return found


def collect(root: Path, used: set[str], result: Result) -> dict[str, Image]:
    """Every finished, valid pair in the bucket; ids editions show are read first.

    Bytes are kept only for images a page can show: active ones and ones an
    edition uses. A retired image nobody shows is checked but not published.
    """
    images: dict[str, Image] = {}
    entries = bucket(root, result)
    for image_id in sorted(entries, key=lambda i: (i not in used, i)):
        exts = [e for e in entries[image_id] if e != "toml"]
        if "toml" not in entries[image_id]:  # image first, record last: not finished yet
            result.waiting += [f"{FOLDER}/{image_id}.{e}" for e in exts]
            continue
        if len(exts) != 1:
            why = f"needs exactly one image beside it, as .{', .'.join(EXTENSIONS)}"
            result.rejected.append((f"{FOLDER}/{image_id}.toml", why))
            continue
        if len(images) >= MAX_IMAGES:
            result.waiting.append(f"{FOLDER}/{image_id}.toml (over {MAX_IMAGES} images)")
            continue
        try:
            meta = record(
                load_toml(read_no_follow(root, f"{FOLDER}/{image_id}.toml", MAX_RECORD_BYTES))
            )
            data = photo(root, exts[0], image_id)
        except Invalid as exc:
            result.rejected.append((f"{FOLDER}/{image_id}", str(exc)))
            continue
        keep = data if meta["active"] or image_id in used else b""
        images[image_id] = Image(file=f"{image_id}.{exts[0]}", data=keep, **meta)
    return images
