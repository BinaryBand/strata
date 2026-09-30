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


class Prompter(Protocol):
    """Asks the operator for a value. cli decides how -- a terminal prompt, or refusal.

    core and adapters must not import a prompting library, so anything they
    need from the operator goes through here. `ask` never loops and never
    validates: a caller that needs a non-empty answer re-asks itself, because
    what counts as acceptable is that caller's rule and not the terminal's.
    """

    def ask(self, message: str, *, default: str | None = None, hidden: bool = False) -> str:
        """Return the answer: on a blank answer, `default` if there is one, else ""."""
        ...

    def tell(self, message: str) -> None:
        """Show a correction or notice before the next question."""
        ...


class PromptUnavailableError(RuntimeError):
    """A value was needed and there was no operator to ask."""


class NonInteractivePrompter:
    """Refuses every question. For callers with no terminal, such as a GUI run.

    Satisfies Prompter. Refusing beats blocking: a GUI run prompting would sit
    on a terminal nobody is watching, from a daemon thread, forever.
    """

    def ask(self, message: str, *, default: str | None = None, hidden: bool = False) -> str:  # noqa: ARG002 -- the Prompter signature
        """Raise: there is nobody to answer."""
        msg = (
            f"{message.strip()!r} needs an answer; "
            "set it with `strata config secret` or run this from the CLI"
        )
        raise PromptUnavailableError(msg)

    def tell(self, message: str) -> None:
        """Drop `message`."""


class SecretReader(Protocol):
    """Reads previously stored vault secrets."""

    def get_secret(self, name: str) -> str | None:
        """Return the plaintext for `name`, or None if it is not stored."""
        ...
