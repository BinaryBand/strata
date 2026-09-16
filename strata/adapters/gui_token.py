"""GUI access token storage in the OS keychain.

`strata gui` now exposes mutating endpoints (run a runbook, add a device, set
a secret) alongside the read-only snapshot, so a caller must present this
token to use them. Same keychain pattern as `adapters/ansible/vault_pass.py`,
a different account -- this secret has no pre-rename predecessor to migrate
from.
"""

from secrets import token_urlsafe

import keyring

_SERVICE = "strata"
_ACCOUNT = "gui_token"


def has_token() -> bool:
    """Report whether a GUI access token has already been generated."""
    return keyring.get_password(_SERVICE, _ACCOUNT) is not None


def get_or_create_token() -> str:
    """Return the stored GUI access token, generating and storing one if absent."""
    value = keyring.get_password(_SERVICE, _ACCOUNT)
    if value is not None:
        return value
    return rotate_token()


def rotate_token() -> str:
    """Generate a new GUI access token, replacing any existing one, and return it."""
    value = token_urlsafe(32)
    keyring.set_password(_SERVICE, _ACCOUNT, value)
    return value
