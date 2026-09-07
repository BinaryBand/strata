"""Encrypt and store ansible-vault secrets in ansible/inventory/group_vars/secrets/all.yml."""

import getpass
import re
import textwrap

from ansible.parsing.vault import AnsibleVaultError, VaultLib, VaultSecret

from strata.adapters import fs
from strata.adapters.ansible import vault_pass
from strata.core import paths

_SECRETS_DIR = paths.GROUP_VARS_DIR / "secrets"
_SECRETS_FILE = _SECRETS_DIR / "all.yml"

# `ansible-vault encrypt_string` indents the vault text ten spaces under the
# key, and wraps the payload at 80 columns; VaultLib.encrypt() produces the
# same 80-column body, so reproducing the indent is all that is needed to keep
# writing the exact block shape every secret already on disk was written in.
# has_secret/get_secret/set_secret all parse this file by regex, so the layout
# is load-bearing rather than cosmetic.
_BLOCK_INDENT = " " * 10

# Labels the password in VaultLib's secret list; it is a lookup key, not part
# of the output. Passing a vault_id to encrypt() *would* change the output --
# it moves the header from `$ANSIBLE_VAULT;1.1;AES256` to a 1.2 header with
# the id appended -- so encrypt() is deliberately called without one.
_VAULT_ID = "default"


def ensure_vault_password() -> None:
    """Prompt for and store the vault password in the OS keychain if absent.

    Every ansible-vault call needs it, so anything that encrypts or decrypts
    calls this first. It used to be reached via a @guard.prerequisite decorator
    on set_secret; guards are declarative now and only apply to runbooks, so an
    adapter that needs this has to ask for it directly.
    """
    if not vault_pass.has_vault_password():
        password = getpass.getpass("vault password (will be stored in keychain): ")
        vault_pass.set_vault_password(password)


def _vault() -> VaultLib:
    """Build a VaultLib bound to the vault password held in the OS keychain.

    Callers that write have already been through ensure_vault_password(); a
    reader has not, so a missing password has to fail with something that says
    what to do about it rather than an ansible-internal error.
    """
    password = vault_pass.get_vault_password()
    if password is None:
        msg = "No vault password in the OS keychain. Run: strata config vault-password"
        raise RuntimeError(msg)
    return VaultLib(secrets=[(_VAULT_ID, VaultSecret(password.encode()))])


def _encrypt(name: str, value: str) -> str:
    """Vault-encrypt `value` and render it as `name`'s block in the secrets file.

    Encryption happens in this process. It used to shell out to `ansible-vault
    encrypt_string`, which made keeping the plaintext out of argv a live
    concern -- an argument is readable by any local process through
    /proc/<pid>/cmdline for as long as the child runs, and check=True raises
    CalledProcessError, whose message embeds the whole argument vector, so a
    vault failure once printed the plaintext sudo password into the terminal.
    Passing the value on stdin fixed that, and moving in-process removes the
    argument vector altogether.

    The obligation that outlives the subprocess is the other half of that bug:
    `value` must never reach an exception message. AnsibleVaultError does not
    carry it (a failure here reports a missing password, not the input), and
    nothing below interpolates it.
    """
    vaulttext = _vault().encrypt(value).decode()
    return f"{name}: !vault |\n" + textwrap.indent(vaulttext.rstrip("\n"), _BLOCK_INDENT)


def has_secret(name: str) -> bool:
    """Report whether `name` has a vaulted entry in the secrets file.

    Scans for the key without decrypting, so it needs no vault password.

    Args:
        name: Secret variable name to look for.

    Returns:
        True if the secrets file exists and declares `name`.
    """
    if not _SECRETS_FILE.exists():
        return False
    return bool(re.search(rf"(?m)^{re.escape(name)}:", _SECRETS_FILE.read_text()))


def get_secret(name: str) -> str | None:
    """Decrypt and return a stored secret's plaintext, or None if unset.

    Each secret is its own single-key block, so decryption dedents the block
    back into standalone vault text, matching what `_encrypt` produced.

    This used to write that text to a temporary file and shell out to
    `ansible-vault view`, which put every secret's ciphertext through /tmp on
    the way to being read. Decrypting in-process needs no such file. It also
    drops the `view` display newline the old code had to rstrip: VaultLib
    returns exactly the bytes that were encrypted.
    """
    if not has_secret(name):
        return None

    content = _SECRETS_FILE.read_text()
    match = re.search(rf"(?m)^{re.escape(name)}: !vault \|\n((?:[ \t]+.*\n)*)", content)
    if not match:
        return None

    ciphertext = "\n".join(line.strip() for line in match.group(1).splitlines()) + "\n"
    try:
        return _vault().decrypt(ciphertext).decode()
    except AnsibleVaultError as exc:
        msg = f"decrypting {name!r} from the vault failed: {exc}"
        raise RuntimeError(msg) from exc


def set_secret(name: str, value: str) -> None:
    """Vault-encrypt `value` and store it as `name` in the secrets file.

    Replaces the existing block for `name` if one is present, otherwise appends
    a new one, leaving the other secrets untouched.

    Args:
        name: Secret variable name to write.
        value: Plaintext to encrypt under that name.
    """
    ensure_vault_password()
    _SECRETS_DIR.mkdir(parents=True, exist_ok=True)
    block = _encrypt(name, value) + "\n"

    content = _SECRETS_FILE.read_text() if _SECRETS_FILE.exists() else ""
    pattern = rf"(?m)^{re.escape(name)}:[ \t]*.*\n(?:[ \t]+.*\n)*"

    if re.search(pattern, content):
        # A function replacement, not the string: re.sub interprets \g<...>,
        # \1 and backslashes in a replacement string, and `block` carries the
        # caller-supplied secret name. re.escape guards the pattern; nothing
        # guarded this side.
        content = re.sub(pattern, lambda _match: block, content)
    else:
        content = (content.rstrip("\n") + "\n" if content else "") + block

    # This directory is gitignored, so all.yml is the only copy of every
    # credential the tool has stored -- a truncate-then-write interrupted
    # halfway loses all of them at once.
    fs.write_text(_SECRETS_FILE, content)
