"""The one rule for the address a request came from (utils/client_ip.py): Cloudflare's ``cf-connecting-ip`` only
beside the secret NoClick's own proxy sends, else the connection's peer. Headers anyone can send (a forged
``cf-connecting-ip``, ``x-forwarded-for``) never decide it, for an HTTP request or a socket.io connect alike."""

from types import SimpleNamespace

import pytest
from starlette.requests import Request

from utils import client_ip

SECRET = "the-proxy-secret"


def request(headers=None, peer="198.51.100.4"):
    raw = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    return Request({"type": "http", "method": "GET", "path": "/", "headers": raw,
                    "client": (peer, 5000) if peer else None})


def environ(headers=None, peer="198.51.100.4"):
    found = {"HTTP_" + k.upper().replace("-", "_"): v for k, v in (headers or {}).items()}
    return {**found, "REMOTE_ADDR": "127.0.0.1", "asgi.scope": {"client": (peer, 5000)}}


@pytest.fixture(autouse=True)
def secret(monkeypatch):
    monkeypatch.setenv(client_ip.PROXY_SECRET_ENV, SECRET)


def test_cloudflares_address_counts_only_beside_the_proxys_secret():
    proxied = {"cf-connecting-ip": "203.0.113.9", client_ip.PROXY_HEADER: SECRET}
    assert client_ip.client_ip(request(proxied)) == "203.0.113.9"
    assert client_ip.environ_ip(environ(proxied)) == "203.0.113.9"
    for forged in ({"cf-connecting-ip": "203.0.113.9"},
                   {"cf-connecting-ip": "203.0.113.9", client_ip.PROXY_HEADER: "a-guess"},
                   {"x-forwarded-for": "203.0.113.9, 10.0.0.1"}, {"x-real-ip": "203.0.113.9"}):
        assert client_ip.client_ip(request(forged)) == "198.51.100.4", forged
        assert client_ip.environ_ip(environ(forged)) == "198.51.100.4", forged


def test_an_origin_with_no_secret_believes_no_header(monkeypatch):
    monkeypatch.delenv(client_ip.PROXY_SECRET_ENV)
    sent = {"cf-connecting-ip": "203.0.113.9", client_ip.PROXY_HEADER: ""}
    assert client_ip.client_ip(request(sent)) == "198.51.100.4"


def test_a_request_with_no_peer_has_no_address():
    assert client_ip.client_ip(request(peer=None)) == "unknown"
    assert client_ip.environ_ip({"REMOTE_ADDR": None}) is None
    assert client_ip.client_ip(SimpleNamespace(headers={}, client=None)) == "unknown"
