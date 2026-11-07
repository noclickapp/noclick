"""PayPal's documented event and registration response, plus signature negatives.

The certificate/key used for the cryptographic unit test is generated at test
time; the event body and transmission metadata are copied from PayPal's guide.
No live registration or live signature verification is claimed by these tests.
"""
import base64
import json
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import NameOID

from nodes.paypal_node import PayPalNode, PayPalNodeConfig, _webhook_certificate

EXAMPLE = json.loads((Path(__file__).parent / "fixtures/paypal/webhook_examples.json").read_text())
CREDENTIAL = {"client_id": "test-client", "client_secret": "test-secret", "environment": "sandbox"}


@pytest.mark.asyncio
async def test_paypal_register_and_unregister_use_documented_contract():
    requests = []

    def respond(request):
        requests.append(request)
        if request.method == "POST":
            return httpx.Response(201, json=EXAMPLE["registration_response"])
        return httpx.Response(204)

    real_client = httpx.AsyncClient
    with patch("nodes.paypal_node._access_token", new=AsyncMock(return_value="test-token")), patch(
        "nodes.paypal_node.httpx.AsyncClient",
        side_effect=lambda **kw: real_client(transport=httpx.MockTransport(respond), **kw),
    ):
        config = await PayPalNode._register_external_webhook(
            webhook_url="https://example.com/example_webhook", credential=CREDENTIAL,
            config={"event_type": "PAYMENT.CAPTURE.COMPLETED"}, node_id="paypal-test",
        )
        await PayPalNode._unregister_external_webhook(
            credential=CREDENTIAL, config=config, node_id="paypal-test")
    assert config == {"external_webhook_id": EXAMPLE["registration_response"]["id"],
                      "signing_secret": EXAMPLE["registration_response"]["id"]}
    assert requests[0].url == "https://api-m.sandbox.paypal.com/v1/notifications/webhooks"
    assert requests[0].headers["authorization"] == "Bearer test-token"
    assert json.loads(requests[0].content) == {
        "url": "https://example.com/example_webhook",
        "event_types": [{"name": "PAYMENT.CAPTURE.COMPLETED"}],
    }
    assert requests[1].method == "DELETE"
    assert requests[1].url.path == "/v1/notifications/webhooks/" + EXAMPLE["registration_response"]["id"]


@pytest.mark.asyncio
async def test_paypal_registration_requires_provider_id_and_supported_event():
    with patch.object(PayPalNode, "_webhook_request", new=AsyncMock(return_value={})) as request:
        with pytest.raises(ValueError, match="webhook ID"):
            await PayPalNode._register_external_webhook(
                webhook_url="https://example.com/example_webhook", credential=CREDENTIAL,
                config={}, node_id="paypal-test")
        request.reset_mock()
        with pytest.raises(ValueError, match="supported PayPal event"):
            await PayPalNode._register_external_webhook(
                webhook_url="https://example.com/example_webhook", credential=CREDENTIAL,
                config={"event_type": "INVALID"}, node_id="paypal-test")
        request.assert_not_called()


def test_paypal_trigger_schema_lifecycle_filter_and_agent_turn():
    trigger = {"operation": "on_event", "event_type": "PAYMENT.CAPTURE.COMPLETED",
               "external_webhook_id": EXAMPLE["webhook_id"], "signing_secret": EXAMPLE["webhook_id"]}
    model = PayPalNodeConfig.model_validate({"config": trigger, "credentials": CREDENTIAL})
    assert model.config.model_dump()["external_webhook_id"] == EXAMPLE["webhook_id"]
    schema = PayPalNodeConfig.model_json_schema()["$defs"]["PayPalOnEventConfig"]
    assert schema["x-requires-webhook"] is True
    assert schema["properties"]["operation"]["x-is-trigger"] is True
    assert PayPalNode.filter_trigger_payload(EXAMPLE["event"], trigger)
    assert not PayPalNode.filter_trigger_payload(EXAMPLE["event"], {"event_type": "PAYMENT.CAPTURE.REFUNDED"})
    assert not PayPalNode.filter_trigger_payload({}, trigger)
    assert PayPalNode.registration_fingerprint_fields(trigger) != PayPalNode.registration_fingerprint_fields(
        {"event_type": "PAYMENT.CAPTURE.REFUNDED"})
    turn = PayPalNode.resolve_agent_event({"status": "success", "data": EXAMPLE["event"]})
    assert turn == PayPalNode.resolve_agent_event(EXAMPLE["event"])
    assert turn["conversation_key"] == "9P99943869582473S"
    for text in ("500.00 USD", "receivingbusiness@example.com", "PAYMENT.CAPTURE.COMPLETED",
                 "3Y662965014333303", "9P99943869582473S", "get_capture capture_id=3Y662965014333303"):
        assert text in turn["text"]


@pytest.fixture
def signed_delivery():
    body = json.dumps(EXAMPLE["event"], separators=(",", ":")).encode()
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.now(timezone.utc)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "PayPal unit test")])
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=1))
            .not_valid_after(now + timedelta(days=1)).sign(key, hashes.SHA256()))
    headers = {"paypal-auth-algo": "SHA256withRSA", "paypal-transmission-id": EXAMPLE["transmission_id"],
               "paypal-transmission-time": EXAMPLE["transmission_time"], "paypal-cert-url": EXAMPLE["cert_url"]}
    message = (f"{EXAMPLE['transmission_id']}|{EXAMPLE['transmission_time']}|"
               f"{EXAMPLE['webhook_id']}|{zlib.crc32(body) & 0xffffffff}").encode()
    headers["paypal-transmission-sig"] = base64.b64encode(key.sign(message, padding.PKCS1v15(), hashes.SHA256())).decode()
    return body, headers, cert


def test_paypal_signature_uses_raw_body_webhook_id_and_rsa(signed_delivery):
    body, headers, cert = signed_delivery
    with patch("nodes.paypal_node._webhook_certificate", return_value=cert):
        assert PayPalNode.verify_webhook_signature(body, headers, {"external_webhook_id": EXAMPLE["webhook_id"]})
        # The row mirror alone authenticates the first delivery before autosave.
        assert PayPalNode.verify_webhook_signature(body, headers, {"signing_secret": EXAMPLE["webhook_id"]})
        assert not PayPalNode.verify_webhook_signature(body + b" ", headers, {"signing_secret": EXAMPLE["webhook_id"]})
        assert not PayPalNode.verify_webhook_signature(body, headers, {"signing_secret": "wrong-webhook"})
        assert not PayPalNode.verify_webhook_signature(body, headers, {})
        for field in headers:
            modified = dict(headers)
            modified.pop(field)
            assert not PayPalNode.verify_webhook_signature(body, modified, {"signing_secret": EXAMPLE["webhook_id"]})
        assert not PayPalNode.verify_webhook_signature(
            body, {**headers, "paypal-auth-algo": "SHA1withRSA"}, {"signing_secret": EXAMPLE["webhook_id"]})


@pytest.mark.parametrize("url", [
    "http://api.sandbox.paypal.com/v1/notifications/certs/CERT-test",
    "https://api.sandbox.paypal.com.evil.example/v1/notifications/certs/CERT-test",
    "https://evil.example/v1/notifications/certs/CERT-test",
    "https://api.sandbox.paypal.com@evil.example/v1/notifications/certs/CERT-test",
    "https://api.sandbox.paypal.com/v1/notifications/certs/../oauth2/token",
    "https://api.sandbox.paypal.com:444/v1/notifications/certs/CERT-test",
])
def test_paypal_rejects_untrusted_certificate_urls_before_http(url):
    _webhook_certificate.cache_clear()
    with patch("nodes.paypal_node.httpx.Client") as client, pytest.raises(ValueError):
        _webhook_certificate(url)
    client.assert_not_called()


def test_paypal_certificate_download_is_cached_and_refuses_redirects(signed_delivery):
    _, _, cert = signed_delivery
    _webhook_certificate.cache_clear()
    real_client = httpx.Client
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, content=cert.public_bytes(serialization.Encoding.PEM))

    with patch("nodes.paypal_node.httpx.Client",
               side_effect=lambda **kw: real_client(transport=httpx.MockTransport(respond), **kw)):
        assert _webhook_certificate(EXAMPLE["cert_url"]) == cert
        assert _webhook_certificate(EXAMPLE["cert_url"]) == cert
    assert len(requests) == 1
    _webhook_certificate.cache_clear()
    with patch("nodes.paypal_node.httpx.Client", side_effect=lambda **kw: real_client(
        transport=httpx.MockTransport(lambda request: httpx.Response(302, headers={"location": "https://evil.example"})), **kw)):
        with pytest.raises(httpx.HTTPStatusError):
            _webhook_certificate(EXAMPLE["cert_url"])
    _webhook_certificate.cache_clear()
