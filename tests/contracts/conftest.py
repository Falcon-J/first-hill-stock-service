"""Contracts run entirely in-process; no external networking is permitted."""
import socket
import ipaddress
import pytest


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    # Windows asyncio creates a loopback socketpair internally. Permit local
    # IPC/job-owned providers, but reject every external address before connect.
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    def allowed(sock, address):
        if sock.family == getattr(socket, 'AF_UNIX', None):
            return True
        try:
            return ipaddress.ip_address(address[0]).is_loopback
        except (ValueError, TypeError, IndexError):
            return False
    def connect(sock, address):
        assert allowed(sock, address), 'External network access is forbidden in contract tests'
        return original_connect(sock, address)
    def connect_ex(sock, address):
        assert allowed(sock, address), 'External network access is forbidden in contract tests'
        return original_connect_ex(sock, address)
    monkeypatch.setattr(socket.socket, 'connect', connect)
    monkeypatch.setattr(socket.socket, 'connect_ex', connect_ex)
