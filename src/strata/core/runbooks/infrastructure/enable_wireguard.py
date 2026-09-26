"""Runbook: route all of this host's traffic through a WireGuard full tunnel.

Works with any WireGuard VPN provider: the five prompted values are the ones
every provider's client config carries. The defaults for the tunnel address and
DNS server are Proton VPN's, which are the same in every Proton config.

Tailscale keeps working alongside the tunnel. The playbook pins the tunnel's
policy-routing rules after Tailscale's, so tailnet traffic still reaches
tailscale0 and Tailscale's own packets still leave through the physical link.

The vault is shared by every host, so the stored key belongs to one host at a
time. Two hosts running the same WireGuard key knock each other off the tunnel.
"""

from strata.core import guard
from strata.core.ports import PlaybookRunner


@guard.alias("connect WireGuard tunnel")
@guard.prerequisite("sudo_password")
@guard.secret(
    "wireguard_private_key",
    prompt="WireGuard private key ([Interface] PrivateKey)",
)
@guard.secret(
    "wireguard_address",
    kind="text",
    prompt="Tunnel address, comma-separated if more than one ([Interface] Address)",
    default="10.2.0.2/32",
)
@guard.secret(
    "wireguard_dns",
    kind="text",
    prompt="Tunnel DNS server ([Interface] DNS)",
    default="10.2.0.1",
)
@guard.secret(
    "wireguard_peer_public_key",
    kind="text",
    prompt="Server public key ([Peer] PublicKey)",
)
@guard.secret(
    "wireguard_endpoint",
    kind="text",
    prompt="Server endpoint as host:port ([Peer] Endpoint)",
)
def main(target: str | None = None, *, runner: PlaybookRunner) -> int:
    """Install WireGuard and bring up the full tunnel without breaking Tailscale."""
    return runner.run_playbook("playbooks/enable_wireguard.yml", target=target)
