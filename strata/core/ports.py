"""Protocol ports that core depends on and adapters implement.

core holds the interface; adapters/ holds the concrete implementation; cli/
constructs the adapter and passes it in. ty verifies conformance structurally
at the call site, so no adapter needs to inherit from anything here.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol


class PlaybookRunner(Protocol):
    """Runs an Ansible playbook and reports its exit code."""

    def run_playbook(
        self,
        playbook: str,
        extravars: Mapping[str, object] | None = None,
        target: str | None = None,
    ) -> int:
        """Run `playbook` against `target`, returning 0 on success."""
        ...


class Reporter(Protocol):
    """Writes human-facing progress to wherever the caller decided it goes.

    core must not choose an output channel -- a runbook that calls print()
    cannot be run headlessly or tested without capturing stdout -- so anything
    core wants to say goes through here and cli decides where it lands.
    """

    def info(self, message: str) -> None:
        """Report a progress or status message."""
        ...


class NullReporter:
    """Discards messages, for callers with no terminal to write to.

    Satisfies Reporter. Lives here rather than in either adapter because both
    needed it and each had grown its own byte-identical copy.
    """

    def info(self, message: str) -> None:
        """Drop `message`."""


class SecretReader(Protocol):
    """Reads previously stored vault secrets."""

    def get_secret(self, name: str) -> str | None:
        """Return the plaintext for `name`, or None if it is not stored."""
        ...
