"""Runbook: join this host to the Tailscale tailnet for off-LAN reachability.

Tailscale gives every joined host a stable tailnet address (and MagicDNS name),
so `nas` and friends become SSH-reachable from any other device on the same
tailnet without opening a router port. This runbook automates only the per-host
*join*; three things stay one-time tailnet setup done outside it:

- a Tailscale account, with MagicDNS enabled once in the admin console;
- the device you connect *from* joined to the same tailnet (phones/laptops that
  aren't in the inventory install the app by hand -- no runbook reaches them);
- an auth key minted in the admin console, pasted when the guard prompts. Keys
  expire (<=90 days), so a re-provision months later needs a fresh one.

Tailscale is the network path, not the login: you still authenticate to the
host's normal sshd with your existing credentials.
"""

from strata.core import guard
from strata.core.ports import PlaybookRunner


@guard.alias("join Tailscale network")
@guard.prerequisite("sudo_password")
@guard.secret(
    "tailscale_auth_key",
    prompt="Tailscale auth key (from the admin console)",
)
def main(target: str | None = None, *, runner: PlaybookRunner) -> int:
    """Install Tailscale and bring the host up on the tailnet."""
    return runner.run_playbook("playbooks/enable_tailscale.yml", target=target)
