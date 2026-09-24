"""Rebuild the AnythingLLM agent's site with Zola whenever its content changes.

Deployed by strata's enable_anythingllm_site runbook as a hardened system
service. Every POLL_SECONDS it fingerprints the agent's site folder and
strata's Zola skeleton; once a change has held still for SETTLE_SECONDS it
validates the content (validate.py), assembles a fresh Zola project in a
private temporary directory, runs `zola build`, and publishes the output as a
new release by switching the `current` link nginx serves -- so readers never
see a half-built site, and a failed build leaves the last good one live. The
outcome goes to BUILD.md in the agent's folder and to status.json for /review.
Standard library only.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import validate

SOURCE = Path(os.environ.get("SITE_SOURCE", "/srv/anythingllm/storage/anythingllm-fs/site"))
SKELETON = Path(os.environ.get("SITE_SKELETON", "/srv/anythingllm/site-zola"))
PUBLIC = Path(os.environ.get("SITE_PUBLIC", "/srv/anythingllm/site-public"))
ZOLA = os.environ.get("SITE_ZOLA", "/usr/local/bin/zola")
BASE_URL = os.environ.get("SITE_BASE_URL", "http://localhost")
POLL_SECONDS = 2.0
SETTLE_SECONDS = 2.0
BUILD_TIMEOUT = 60
KEEP_RELEASES = 3


def fingerprint() -> tuple:
    """(path, size, mtime) of every entry under source and skeleton; links not followed."""
    seen = []
    for top in (SOURCE, SKELETON):
        for dirpath, dirnames, filenames in os.walk(top, followlinks=False):
            dirnames.sort()
            for name in sorted(filenames) + sorted(dirnames):
                path = Path(dirpath) / name
                # The builder's own report must not look like new content.
                if path.name in ("BUILD.md", ".BUILD.md.tmp"):
                    continue
                try:
                    st = path.lstat()
                except OSError:
                    continue
                seen.append((str(path), st.st_size, st.st_mtime_ns))
    return tuple(seen)


def assemble(project: Path, result: validate.Result) -> None:
    """A Zola project: strata's skeleton plus the translated content and stylesheet."""
    shutil.copytree(SKELETON, project, symlinks=False, dirs_exist_ok=True)
    for rel, body in result.files.items():
        target = project / "content" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
    if result.css is not None:
        (project / "static" / "news").mkdir(parents=True, exist_ok=True)
        (project / "static" / "news" / "style.css").write_bytes(result.css)


def zola(project: Path, output: Path) -> tuple[bool, str]:
    """Run `zola build` for the project; (succeeded, its output)."""
    argv = [
        ZOLA,
        "--root",
        str(project),
        "build",
        "--base-url",
        BASE_URL,
        "--output-dir",
        str(output),
        "--force",
    ]
    try:
        done = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=BUILD_TIMEOUT,
            check=False,
            env={"PATH": "/usr/bin:/bin", "HOME": str(project)},
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    return done.returncode == 0, (done.stdout + done.stderr).strip()[-4000:]


def publish(output: Path) -> str:
    """Move the output in as a new release, switch `current` to it, prune old releases."""
    releases = PUBLIC / "releases"
    releases.mkdir(parents=True, exist_ok=True)
    name = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%S%fZ")
    shutil.move(str(output), releases / name)
    link = PUBLIC / "current.new"
    link.unlink(missing_ok=True)
    link.symlink_to(Path("releases") / name)
    link.replace(PUBLIC / "current")  # rename(2): atomic for readers
    for old in sorted(releases.iterdir())[:-KEEP_RELEASES]:
        shutil.rmtree(old, ignore_errors=True)
    return name


def report(result: validate.Result, *, ok: bool, log: str, release: str | None) -> None:
    """BUILD.md for the agent and status.json for the /review monitor."""
    when = dt.datetime.now(dt.UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    status = {
        "time": when,
        "ok": ok,
        "release": release,
        "editions": result.editions,
        "rejected": [{"file": f, "reason": r} for f, r in result.rejected],
        "waiting": result.waiting,
        "log": "" if ok else log,
    }
    outcome = "published" if ok else "FAILED, the previous build is still live"
    lines = [
        "# Site build",
        "",
        f"Last build: {when}. Result: {outcome}.",
        f"Editions built: {result.editions}.",
        "",
    ]
    if result.waiting:
        lines += [
            "## Waiting",
            "",
            "These editions have no edition.toml yet, so they are not built:",
            "",
        ]
        lines += [f"- `{w}`" for w in result.waiting] + [""]
    if result.rejected:
        lines += [
            "## Skipped files",
            "",
            "Fix these and save again; the site rebuilds within seconds.",
            "",
        ]
        lines += [f"- `{f}`: {r}" for f, r in result.rejected]
    else:
        lines.append("No files were skipped.")
    if not ok:
        lines += ["", "## Build error", "", "```text", log, "```"]
    for path, text in (
        (PUBLIC / "status.json", json.dumps(status, indent=2)),
        (SOURCE / "BUILD.md", "\n".join(lines) + "\n"),
    ):
        tmp = path.with_name(f".{path.name}.tmp")
        try:
            tmp.write_text(text, encoding="utf-8")
            tmp.replace(path)
        except OSError as exc:
            sys.stderr.write(f"could not write {path}: {exc}\n")


def build_once() -> bool:
    """Validate, assemble, build and publish once; True when a new release went live."""
    result = validate.collect(SOURCE)
    with tempfile.TemporaryDirectory(prefix="site-build-") as work:
        project, output = Path(work) / "project", Path(work) / "public"
        assemble(project, result)
        ok, log = zola(project, output)
        release = publish(output) if ok else None
    report(result, ok=ok, log=log, release=release)
    return ok


def main() -> None:
    """Build now, then again whenever the content has changed and settled."""
    last = None
    while True:
        current = fingerprint()
        if current != last:
            time.sleep(SETTLE_SECONDS)
            settled = fingerprint()
            if settled == current:
                try:
                    build_once()
                except Exception as exc:  # noqa: BLE001 -- the watcher must outlive any one build
                    sys.stderr.write(f"build failed: {exc!r}\n")
                last = current
            continue
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
