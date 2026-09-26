"""Cheap network reachability probe, for the GUI's "test connection" action."""

import socket


def tcp_reachable(host: str, port: int = 22, *, timeout: float = 2.0) -> bool:
    """Report whether a TCP connection to `host:port` succeeds within `timeout` seconds."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False
