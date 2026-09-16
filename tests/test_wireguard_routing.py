"""The WireGuard tunnel's policy rules stay between Tailscale's and main.

A rule added without a priority is numbered by the kernel just ahead of the
first existing rule, which puts it ahead of Tailscale's fixed block when
tailscaled started first, and tailnet traffic then enters the tunnel.
enable_wireguard.yml avoids that by turning off wg-quick's routing and adding
every rule at an explicit priority. This renders the config it writes and
checks both halves of that.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import cast

import pytest
import yaml
from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar, trust_as_template

PLAYBOOK = Path(__file__).resolve().parents[1] / "ansible" / "playbooks" / "enable_wireguard.yml"

# Tailscale's policy rules occupy 5210-5270; the kernel's main-table rule is 32766.
_TAILSCALE_LAST_PREF = 5270
_MAIN_PREF = 32766

_RULE_ADD = re.compile(r"ip -[46] rule add (?P<args>.*)$")
_PREF = re.compile(r"\bpref (?P<pref>\d+)\b")


def _play() -> dict[str, object]:
    plays = cast("list[dict[str, object]]", yaml.safe_load(PLAYBOOK.read_text()))
    return plays[0]


def _rendered_config(*, ipv6: bool) -> str:
    play = _play()
    play_vars = cast("dict[str, object]", play["vars"])
    tasks = cast("list[dict[str, object]]", play["tasks"])
    (write,) = [t for t in tasks if t.get("name") == "Write the tunnel configuration"]
    content = cast("dict[str, str]", write["ansible.builtin.copy"])["content"]
    variables = {
        **play_vars,
        "wireguard_ipv6": ipv6,
        "wireguard_private_key": "private",
        "wireguard_address": "10.2.0.2/32",
        "wireguard_dns": "10.2.0.1",
        "wireguard_peer_public_key": "public",
        "wireguard_endpoint": "198.51.100.1:51820",
    }
    # Ansible's own renderer, so its filters and block trimming apply as in a real run.
    templar = Templar(loader=DataLoader(), variables=variables)
    return str(templar.template(trust_as_template(content)))


@pytest.mark.parametrize("ipv6", [True, False])
def test_wg_quick_routing_is_off(ipv6: bool) -> None:  # noqa: FBT001 -- pytest parameter
    assert re.search(r"^Table = off$", _rendered_config(ipv6=ipv6), re.MULTILINE)


@pytest.mark.parametrize("ipv6", [True, False])
def test_every_rule_sits_between_tailscale_and_main(ipv6: bool) -> None:  # noqa: FBT001 -- pytest parameter
    added = [
        match.group("args")
        for line in _rendered_config(ipv6=ipv6).splitlines()
        if (match := _RULE_ADD.search(line))
    ]
    assert added, "the config adds no policy rules, so nothing routes into the tunnel"
    for args in added:
        pref = _PREF.search(args)
        assert pref, f"rule has no explicit priority, so the kernel picks one: {args!r}"
        assert _TAILSCALE_LAST_PREF < int(pref.group("pref")) < _MAIN_PREF, args


def test_ipv6_rules_follow_the_ipv6_switch() -> None:
    assert "ip -6 rule add" in _rendered_config(ipv6=True)
    assert "ip -6" not in _rendered_config(ipv6=False)
