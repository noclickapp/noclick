"""Socket-level DNS pinning for Motor/PyMongo connections."""

import socket
from unittest.mock import MagicMock, call, patch

import pytest

from nodes.mongodb_node import _pinned_pymongo_create_connection
from utils.ssrf import SSRFError


@pytest.fixture(autouse=True)
def private_targets_blocked(monkeypatch):
    monkeypatch.delenv("OUTBOUND_ALLOW_PRIVATE_IPS", raising=False)
    monkeypatch.delenv("HTTP_NODE_ALLOW_PRIVATE_IPS", raising=False)


def _answer(address, port=27017):
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    sockaddr = (address, port, 0, 0) if family == socket.AF_INET6 else (address, port)
    return (family, socket.SOCK_STREAM, 6, "", sockaddr)


def test_pymongo_dials_only_the_validated_ip_literal():
    original = MagicMock(return_value=object())
    options = object()
    with patch(
        "nodes.mongodb_node.socket.getaddrinfo",
        return_value=[_answer("93.184.216.34")],
    ) as resolve:
        result = _pinned_pymongo_create_connection(
            original,
            ("db.customer.example", 27017),
            options,
        )

    assert result is original.return_value
    resolve.assert_called_once_with(
        "db.customer.example",
        27017,
        family=socket.AF_UNSPEC,
        type=socket.SOCK_STREAM,
    )
    original.assert_called_once_with(("93.184.216.34", 27017), options)


def test_pymongo_blocks_mixed_private_dns_before_any_dial():
    original = MagicMock()
    with patch(
        "nodes.mongodb_node.socket.getaddrinfo",
        return_value=[
            _answer("93.184.216.34"),
            _answer("169.254.169.254"),
        ],
    ):
        with pytest.raises(SSRFError, match="non-public"):
            _pinned_pymongo_create_connection(
                original,
                ("rebind.example", 27017),
                object(),
            )
    original.assert_not_called()


def test_pymongo_retries_only_addresses_from_the_validated_snapshot():
    connection = object()
    original = MagicMock(side_effect=[OSError("unavailable"), connection])
    options = object()
    with patch(
        "nodes.mongodb_node.socket.getaddrinfo",
        return_value=[
            _answer("93.184.216.34"),
            _answer("93.184.216.35"),
        ],
    ):
        result = _pinned_pymongo_create_connection(
            original,
            ("db.customer.example", 27017),
            options,
        )

    assert result is connection
    assert original.call_args_list == [
        call(("93.184.216.34", 27017), options),
        call(("93.184.216.35", 27017), options),
    ]


def test_explicit_private_network_override_preserves_driver_behavior(monkeypatch):
    monkeypatch.setenv("OUTBOUND_ALLOW_PRIVATE_IPS", "true")
    original = MagicMock(return_value=object())
    options = object()

    result = _pinned_pymongo_create_connection(
        original,
        ("localhost", 27017),
        options,
    )

    assert result is original.return_value
    original.assert_called_once_with(("localhost", 27017), options)
