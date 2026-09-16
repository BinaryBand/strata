"""Unit tests for strata.adapters.reachability."""

from __future__ import annotations

import socket
import threading

from strata.adapters import reachability


def test_reachable_when_something_is_listening() -> None:
    with socket.create_server(("127.0.0.1", 0)) as server:
        server.settimeout(2)
        host, port = server.getsockname()

        def accept_once() -> None:
            with server.accept()[0]:
                pass

        thread = threading.Thread(target=accept_once, daemon=True)
        thread.start()
        assert reachability.tcp_reachable(host, port) is True
        # Join before the `with` block closes the listening socket -- otherwise
        # accept_once's accept() can race that close() and log a spurious
        # "Bad file descriptor" from the background thread.
        thread.join(timeout=2)


def test_unreachable_when_nothing_is_listening() -> None:
    with socket.create_server(("127.0.0.1", 0)) as server:
        host, port = server.getsockname()
    # The server above is closed, so the port is very likely free again --
    # if the OS reused it in between, this would flake, but not doing so
    # would need a full connection refusal to be simulated instead.
    assert reachability.tcp_reachable(host, port, timeout=0.5) is False


def test_unreachable_for_an_unresolvable_host() -> None:
    assert reachability.tcp_reachable("this-host-does-not-exist.invalid", 22, timeout=0.5) is False
