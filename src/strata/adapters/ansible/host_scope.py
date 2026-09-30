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


class HostSecrets:
    """Satisfies `ports.SecretReader` for one host, overrides first.

    With no host there is no host_vars file to consult, so it reads the vault
    alone, as it did before overrides were honoured.
    """

    def __init__(self, host: str | None) -> None:
        """Scope every lookup to `host`."""
        self._host = host

    def override(self, name: str) -> str | None:
        """Return `host`'s host_vars value for `name`, or None when it sets none."""
        # A name outside the inventory has no host_vars Ansible would read, and
        # checking keeps one such as `../x` from naming a file outside host_vars/.
        if self._host is None or inventory.get(self._host) is None:
            return None
        value = host_vars.load(self._host).get(name)
        return None if value in (None, "") else str(value)

    def get_secret(self, name: str) -> str | None:
        """Return the value a playbook against `host` would see for `name`."""
        return self.override(name) or secrets.get_secret(name)

    def has_value(self, name: str) -> bool:
        """Report whether `name` has a value for `host`, without decrypting the vault."""
        return self.override(name) is not None or secrets.has_secret(name)
