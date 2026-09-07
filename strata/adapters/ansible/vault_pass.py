"""Vault password storage in the OS keychain.

The same entry is read at playbook time by ansible/vault_pass.py (the
--vault-password-file script), so the service/account names must stay in sync.
"""

import keyring

_SERVICE = "strata"
_ACCOUNT = "vault"

# Pre-rename service name. get_vault_password() migrates a password stored
# under this name forward, once, the first time it's read post-rename. The
# old entry is left in place rather than deleted -- a stray keychain secret
# is harmless, and this avoids losing the only copy if the copy ever failed
# silently. Remove it by hand later if you want, e.g. via `keyring del
# mr-manager vault` or a keychain GUI.
_OLD_SERVICE = "mr-manager"


def has_vault_password() -> bool:
    """Report whether a vault password is already stored in the OS keychain.

    Returns:
        True if the strata/vault keychain entry exists.
    """
    return get_vault_password() is not None


def _migrate_from_old_service() -> str | None:
    old_value = keyring.get_password(_OLD_SERVICE, _ACCOUNT)
    if old_value is not None:
        set_vault_password(old_value)
    return old_value


def get_vault_password() -> str | None:
    """Return the stored Ansible vault password, or None if the keychain has none.

    secrets.py encrypts and decrypts in-process, so it needs the password
    itself rather than a path to the ansible/vault_pass.py script. Playbook
    runs still go through that script -- ansible-runner spawns a child process
    that cannot be handed an in-memory value.

    Returns:
        The vault password, or None if no strata/vault entry exists (and none
        was found under the pre-rename mr-manager/vault entry either).
    """
    value = keyring.get_password(_SERVICE, _ACCOUNT)
    if value is not None:
        return value
    return _migrate_from_old_service()


def set_vault_password(value: str) -> None:
    """Store the Ansible vault password in the OS keychain, replacing any existing entry.

    Args:
        value: The vault password to persist.
    """
    keyring.set_password(_SERVICE, _ACCOUNT, value)
