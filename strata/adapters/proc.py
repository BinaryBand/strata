"""Run external commands with the binary resolved to an absolute path.

Every external tool this project drives -- rclone, ansible-vault, ssh-keygen --
was invoked by bare name, which resolves through whatever PATH happens to be in
effect and produces a bare FileNotFoundError when the tool is missing. Routing
them through here resolves the binary up front, so a missing tool fails with a
sentence naming it rather than a traceback, and the security suppression that
subprocess use requires lives in exactly one reviewed place instead of at all
26 call sites.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Sequence


class CommandNotFoundError(RuntimeError):
    """A required external binary is not installed or not on PATH."""


def resolve(program: str) -> str:
    """Return the absolute path to `program`, or raise CommandNotFoundError."""
    path = shutil.which(program)
    if path is None:
        msg = f"{program!r} is not installed or not on PATH."
        raise CommandNotFoundError(msg)
    return path


def run(
    argv: Sequence[str],
    *,
    check: bool = False,
    capture_output: bool = False,
    text: bool = False,
    input: str | None = None,  # noqa: A002 -- mirrors subprocess.run's own name
) -> subprocess.CompletedProcess[str]:
    """Run `argv` with argv[0] resolved to an absolute path.

    Args:
        argv: Command and arguments. argv[0] is resolved via PATH.
        check: Raise CalledProcessError on a non-zero exit.
        capture_output: Capture stdout/stderr instead of inheriting them.
        text: Decode stdout/stderr as text. Implied by a str `input`.
        input: String written to the child's stdin. Prefer this over an
            argument for anything sensitive: argv is world-readable through
            /proc for the lifetime of the call, and CalledProcessError embeds
            the whole vector in its message.

    Returns:
        The completed process.

    Raises:
        CommandNotFoundError: If argv[0] cannot be found on PATH.
    """
    program, *args = argv
    # A str input with text=False makes subprocess raise TypeError writing a
    # str to a bytes pipe -- so the documented `run(argv, input="x")` did not
    # actually work. The two settings describe the same choice of encoding;
    # inferring one from the other removes a trap rather than adding magic.
    # S603: the argument vector is built by callers from literals and
    # already-validated names, never from a shell string, and shell=False is
    # subprocess.run's default -- so there is no injection surface here.
    return subprocess.run(  # noqa: S603
        [resolve(program), *args],
        check=check,
        capture_output=capture_output,
        text=text or input is not None,
        input=input,
    )
