"""Every test runs with outbound network access blocked.

Connections to the loopback interface stay open, because a notebook kernel talks to its
client over local sockets.
"""

import socket

import pytest

LOOPBACK = {"127.0.0.1", "::1", "localhost"}

_real_connect = socket.socket.connect
_real_connect_ex = socket.socket.connect_ex
_real_getaddrinfo = socket.getaddrinfo


def _allowed(sock: socket.socket, address) -> bool:
    if sock.family == getattr(socket, "AF_UNIX", None):
        return True
    host = address[0] if isinstance(address, tuple) else address
    return host in LOOPBACK


def _guarded_connect(self, address):
    if not _allowed(self, address):
        raise OSError(f"network access is blocked in the tests: {address!r}")
    return _real_connect(self, address)


def _guarded_connect_ex(self, address):
    if not _allowed(self, address):
        raise OSError(f"network access is blocked in the tests: {address!r}")
    return _real_connect_ex(self, address)


def _guarded_getaddrinfo(host, *args, **kwargs):
    if host not in LOOPBACK and host is not None:
        raise OSError(f"name resolution is blocked in the tests: {host!r}")
    return _real_getaddrinfo(host, *args, **kwargs)


GUARD_SOURCE = """\
import socket as _socket
_LOOPBACK = {"127.0.0.1", "::1", "localhost"}
_real_connect = _socket.socket.connect
_real_getaddrinfo = _socket.getaddrinfo
def _connect(self, address):
    host = address[0] if isinstance(address, tuple) else address
    if self.family != getattr(_socket, "AF_UNIX", None) and host not in _LOOPBACK:
        raise OSError(f"network access is blocked in the tests: {address!r}")
    return _real_connect(self, address)
def _getaddrinfo(host, *args, **kwargs):
    if host is not None and host not in _LOOPBACK:
        raise OSError(f"name resolution is blocked in the tests: {host!r}")
    return _real_getaddrinfo(host, *args, **kwargs)
_socket.socket.connect = _connect
_socket.getaddrinfo = _getaddrinfo
"""


@pytest.fixture(autouse=True, scope="session")
def block_network():
    socket.socket.connect = _guarded_connect
    socket.socket.connect_ex = _guarded_connect_ex
    socket.getaddrinfo = _guarded_getaddrinfo
    yield
    socket.socket.connect = _real_connect
    socket.socket.connect_ex = _real_connect_ex
    socket.getaddrinfo = _real_getaddrinfo
