#!/usr/bin/env python3
"""Vault password provider -- retrieves the ansible-vault password from the OS keychain.

Store the password once with:
    uv run strata config vault-password
"""

import sys

import keyring

password = keyring.get_password("strata", "vault")
if not password:
    print(
        "Vault password not found. Run: uv run strata config vault-password",
        file=sys.stderr,
    )
    sys.exit(1)
print(password)
