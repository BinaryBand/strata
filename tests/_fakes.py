"""Fakes shared across the unit and feature suites."""

from __future__ import annotations


class FakePrompter:
    """Records every question and answers from a script, satisfying `ports.Prompter`.

    Answers are consumed in order; once they run out it behaves like a terminal
    where the operator just presses Enter, returning the default or "".
    """

    def __init__(self, answers: list[str] | None = None) -> None:
        self.answers = list(answers or [])
        self.asked: list[dict[str, object]] = []
        self.told: list[str] = []

    def ask(self, message: str, *, default: str | None = None, hidden: bool = False) -> str:
        self.asked.append({"message": message, "default": default, "hidden": hidden})
        if self.answers:
            return self.answers.pop(0)
        return default or ""

    def tell(self, message: str) -> None:
        self.told.append(message)
