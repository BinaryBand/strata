"""Entry point for `python -m strata`."""

from __future__ import annotations

# The Typer application, not the `main` callback next to it: `@app.callback()`
# returns the decorated function unchanged, so importing `main` here gave a
# no-op with an empty body -- `python -m strata` printed nothing and exited
# 0. The console script in pyproject.toml always pointed at `:app`.
from strata.cli.main import app

if __name__ == "__main__":
    app()
