"""
tests/conftest.py
Global pytest configuration and guards for the Quotelytics test suite.
Prevents silent 10-minute hangs on Windows loopback socket isolation.
"""
import socket
import pytest

def pytest_configure(config):
    """
    Apply a fast-fail timeout guard on Windows socketpair creation.
    When running in restricted sandbox environments where 127.0.0.1 IPC
    is blocked by Windows Filtering Platform (WFP), this prevents
    asyncio / anyio from hanging indefinitely on accept().
    """
    orig_socketpair = getattr(socket, "socketpair", None)
    
    def guarded_socketpair(family=socket.AF_INET, type=socket.SOCK_STREAM, proto=0):
        lsock = socket.socket(family, type, proto)
        try:
            lsock.bind(("127.0.0.1", 0))
            lsock.listen(1)
            port = lsock.getsockname()[1]
            csock = socket.socket(family, type, proto)
            try:
                csock.settimeout(2.0)
                lsock.settimeout(2.0)
                csock.connect(("127.0.0.1", port))
                ssock, _ = lsock.accept()
                csock.settimeout(None)
                ssock.settimeout(None)
                return ssock, csock
            except Exception as e:
                csock.close()
                raise RuntimeError(
                    "Loopback socket blocked or timed out under sandbox isolation (WinError 10013). "
                    "Run API route integration tests with unsandboxed loopback permissions."
                ) from e
        finally:
            lsock.close()

    socket.socketpair = guarded_socketpair
