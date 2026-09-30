"""Vault password storage in the OS keychain.

The same entry is read at playbook time by ansible/vault_pass.py (the
--vault-password-file script), so the service/account names must stay in sync.
"""

import keyring

_SERVICE = "strata"
_ACCOUNT = "vault"


def has_vault_password() -> bool:
    """Report whether a vault password is already stored in the OS keychain.

    Returns:
        True if the strata/vault keychain entry exists.
    """
    return get_vault_password() is not None


def get_vault_password() -> str | None:
    """Return the stored Ansible vault password, or None if the keychain has none.

    secrets.py encrypts and decrypts in-process, so it needs the password
    itself rather than a path to the ansible/vault_pass.py script. Playbook
    runs still go through that script -- ansible-runner spawns a child process
    that cannot be handed an in-memory value.

    Returns:
        The vault password, or None if no strata/vault entry exists.
    """
    return keyring.get_password(_SERVICE, _ACCOUNT)


def set_vault_password(value: str) -> None:
    """Store the Ansible vault password in the OS keychain, replacing any existing entry.

    Args:
        value: The vault password to persist.

    Raises:
        ValueError: If `value` is empty.
    """
    if not value:
        msg = "vault password cannot be empty"
        raise ValueError(msg)
    keyring.set_password(_SERVICE, _ACCOUNT, value)
