"""A vaulted value as one host's playbook sees it: its host_vars override, else the vault's.

The vault is a group_vars file (group_vars/secrets/all.yml), and Ansible gives
host_vars precedence over group_vars, so a playbook run against a host reads
`host_vars/<host>.yml`'s value for a key whenever that file sets one. Anything
strata reads on a playbook's behalf -- the storage guard mounting a restic
repository, install_restic's check() looking for its `config` file -- has to
resolve the key the same way, or it prepares and inspects one location while
the playbook uses another.
"""

from __future__ import annotations

from strata.adapters.ansible import host_vars, inventory, secrets


def host_override(host: str | None, name: str) -> str | None:
    """Return `host`'s host_vars value for `name`, or None when it sets none.

    With no host there is no host_vars file to consult. A name outside the
    inventory has none Ansible would read either, and checking keeps one such
    as `../x` from naming a file outside host_vars/.
    """
    if host is None or inventory.get(host) is None:
        return None
    value = host_vars.load(host).get(name)
    return None if value in (None, "") else str(value)


class HostSecrets:
    """Satisfies `ports.SecretReader` for one host, override first, then the vault."""

    def __init__(self, host: str | None) -> None:
        """Scope every lookup to `host`."""
        self._host = host

    def get_secret(self, name: str) -> str | None:
        """Return the value a playbook against `host` would see for `name`."""
        return host_override(self._host, name) or secrets.get_secret(name)
