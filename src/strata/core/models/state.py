"""Model for the CLI's persisted state under the XDG state directory."""

from pydantic import BaseModel


class AppState(BaseModel):
    """CLI state persisted between invocations."""

    last_target: str | None = None
