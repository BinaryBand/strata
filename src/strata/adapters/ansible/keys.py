"""Generate and retrieve SSH keypairs, labeled for reuse across runbooks.

A keypair is a compound input: the private half stays in the standard ~/.ssh
location (the controller is also the SSH client, so the private key never has
to move), and only the public half is published -- as the
`<label>_authorized_key` group var that playbooks install into authorized_keys.
This mirrors secrets.py: where that module guarantees a vaulted value, this one
guarantees a keypair.
"""

from pathlib import Path

from strata.adapters import proc
from strata.adapters.ansible import group_vars

_SSH_DIR = Path.home() / ".ssh"


def _private_path(label: str) -> Path:
    return _SSH_DIR / label


def _public_path(label: str) -> Path:
    return _SSH_DIR / f"{label}.pub"


def var_name(label: str) -> str:
    """The group var the public half is published under (and playbooks read)."""
    return f"{label}_authorized_key"


def has_key(label: str) -> bool:
    """Report whether a private key file already exists for `label`.

    Args:
        label: Keypair label naming the key on disk.

    Returns:
        True if the private half is present.
    """
    return _private_path(label).exists()


def public_key(label: str) -> str | None:
    """Return the public key for `label`, or None if no such keypair exists.

    Reads the .pub file when present, otherwise derives it from the private
    key so a stray missing .pub never hides an existing key.

    Always returns rather than raising, as the signature says: the derivation
    used check=True, so a corrupt or passphrase-protected private key raised
    CalledProcessError out of what callers treat as a pure query. Feeding it
    an empty stdin matters for the same reason -- `ssh-keygen -y` on a
    passphrase-protected key otherwise inherits the terminal and blocks on a
    prompt, inside a function whose job is to answer a question.
    """
    pub = _public_path(label)
    if pub.exists():
        return pub.read_text().strip() or None
    priv = _private_path(label)
    if not priv.exists():
        return None
    result = proc.run(
        ["ssh-keygen", "-y", "-f", str(priv)],
        capture_output=True,
        text=True,
        input="",
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def generate_key(label: str, comment: str | None = None) -> str:
    """Ensure an ed25519 keypair labeled `label` exists, and return its public key.

    Creates ~/.ssh/<label>{,.pub} on first call (passphraseless, since it is
    consumed unattended by the pipeline) and is a no-op when the key is already
    present. Either way the public half is (re)published to group_vars so the
    var stays in sync with the key on disk.
    """
    if not has_key(label):
        _SSH_DIR.mkdir(mode=0o700, exist_ok=True)
        proc.run(
            [
                "ssh-keygen",
                "-t",
                "ed25519",
                "-N",
                "",
                "-C",
                comment or label,
                "-f",
                str(_private_path(label)),
            ],
            check=True,
            capture_output=True,
        )

    pub = public_key(label)
    if not pub:
        # `is None` let an empty or whitespace-only .pub through, since
        # public_key() strips what it reads -- and set_var then published
        # `<label>_authorized_key: ''` to group_vars, which playbooks
        # installed as an empty authorized key. group_vars/all/managed.yml
        # still carries exactly that from a keypair that no longer exists.
        msg = (
            f"Generated the {label!r} keypair but could not read its public half back "
            f"from {_public_path(label)}."
        )
        raise RuntimeError(msg)
    group_vars.set_var(var_name(label), pub)
    return pub
