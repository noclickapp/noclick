"""Facebook's legacy callback must reject unconfigured and forged requests."""

import hashlib
import hmac

import pytest
from fastapi import HTTPException

from nodes.facebook_node import FacebookNode


BODY = b'{"object":"page","entry":[]}'
SECRET = "synthetic-app-secret"


def signed(body=BODY, secret=SECRET):
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


@pytest.mark.parametrize(
    "config",
    [
        None,
        {},
        {"app_secret": None},
        {"app_secret": ""},
        {"app_secret": "   "},
        {"app_secret": 123},
    ],
)
@pytest.mark.parametrize("signature", [None, "sha256=forged", signed()])
def test_signature_requires_configured_secret(config, signature):
    headers = {} if signature is None else {"x-hub-signature-256": signature}
    assert FacebookNode.verify_webhook_signature(BODY, headers, config) is False


@pytest.mark.parametrize(
    "signature",
    [
        None,
        "",
        "sha256=",
        "sha256=bad",
        "sha256=" + "0" * 64,
        "sha256=" + "é" * 64,
        "sha256=" + "a" * 65,
        signed() + "\n",
        123,
        [],
        {},
    ],
)
def test_signature_rejects_malformed_or_forged_digest(signature):
    assert (
        FacebookNode.verify_webhook_signature(
            BODY, {"x-hub-signature-256": signature}, {"app_secret": SECRET}
        )
        is False
    )


@pytest.mark.parametrize("header", ["x-hub-signature-256", "X-Hub-Signature-256"])
def test_signature_authenticates_exact_raw_bytes(header):
    assert FacebookNode.verify_webhook_signature(
        BODY, {header: signed()}, {"app_secret": SECRET}
    )
    assert not FacebookNode.verify_webhook_signature(
        BODY + b" ", {header: signed()}, {"app_secret": SECRET}
    )


def handshake(config, **query):
    return FacebookNode.handle_webhook_handshake(
        b"",
        {
            "__method__": "GET",
            "__query_params__": {
                "hub.mode": "subscribe",
                "hub.verify_token": "verify-test",
                "hub.challenge": "123",
                **query,
            },
        },
        config,
    )


@pytest.mark.parametrize("token", [None, "", "   ", 123, [], {}])
def test_handshake_requires_configured_token(token):
    assert handshake({"verify_token": token}) is None


@pytest.mark.parametrize("token", [None, "", "wrong", 123, [], {}, "é"])
def test_handshake_rejects_nonmatching_token(token):
    assert (
        handshake({"verify_token": "verify-test"}, **{"hub.verify_token": token})
        is None
    )


@pytest.mark.parametrize("challenge", [None, "", "x" * 1025, 123, [], {}])
def test_handshake_requires_bounded_string_challenge(challenge):
    assert (
        handshake({"verify_token": "verify-test"}, **{"hub.challenge": challenge})
        is None
    )


def test_handshake_returns_uncached_plaintext():
    response = handshake({"verify_token": "verify-test"})
    assert response.status_code == 200
    assert response.body == b"123"
    assert response.media_type == "text/plain"
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.asyncio
@pytest.mark.parametrize("config", [{}, {"app_secret": ""}, {"app_secret": SECRET}])
async def test_real_dispatcher_rejects_unsigned_deliveries(config):
    from utils.webhook_routes import _apply_trigger_node_hooks

    node = {
        "id": "trigger",
        "type": "automation-facebook",
        "config": {"operation": "on_feed", **config},
    }
    with pytest.raises(HTTPException) as failure:
        await _apply_trigger_node_hooks(node, BODY, {}, method="POST")
    assert failure.value.status_code in (401, 403)
