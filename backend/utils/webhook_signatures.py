"""Reusable webhook signature verification primitives.

Webhook-trigger nodes implement a ``verify_webhook_signature`` classmethod (see
``WorkflowNode``) that calls the primitive matching their provider's signing
scheme. All comparisons are constant-time via ``hmac.compare_digest``.
"""

import base64
import hashlib
import hmac
import time
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

__all__ = [
    "verify_hmac_sha256_hex",
    "verify_hmac_sha256_base64",
    "verify_twilio_signature",
    "verify_slack_v0",
    "verify_hubspot_v3",
    "verify_ed25519",
    "verify_svix",
]


def _to_bytes(value) -> bytes:
    return value if isinstance(value, bytes) else str(value).encode()


def verify_hmac_sha256_hex(
    body: bytes, secret: str, signature: str, prefix: str = ""
) -> bool:
    """Verify a hex-encoded HMAC-SHA256 signature over the raw request body.

    Used by GitHub, where the ``X-Hub-Signature-256`` header is
    ``sha256=<hex>`` — pass ``prefix="sha256="``. *signature* is the full
    header value as received.
    """
    if not signature or not secret:
        return False
    expected = hmac.new(_to_bytes(secret), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(f"{prefix}{expected}", signature)


def verify_hmac_sha256_base64(body: bytes, secret: str, signature: str) -> bool:
    """Verify a base64-encoded HMAC-SHA256 signature over the raw request body.

    Used by Shopify (``X-Shopify-Hmac-Sha256``) and Typeform (the
    ``Typeform-Signature`` header is ``sha256=<base64>`` — strip that prefix
    before calling).
    """
    if not signature or not secret:
        return False
    digest = hmac.new(_to_bytes(secret), body, hashlib.sha256).digest()
    expected = base64.b64encode(digest).decode()
    return hmac.compare_digest(expected, signature)


def verify_twilio_signature(
    url: str, form_params: dict, auth_token: str, signature: str
) -> bool:
    """Verify Twilio's ``X-Twilio-Signature`` for a form-encoded webhook POST.

    Twilio signs the full request URL with each POST parameter appended as
    ``key + value`` in sorted key order, HMAC-SHA1 with the account auth token,
    base64-encoded. *form_params* is the decoded POST body as a flat dict.
    """
    if not signature or not auth_token:
        return False
    signing_string = url
    for key in sorted(form_params):
        signing_string += key + str(form_params[key])
    digest = hmac.new(
        auth_token.encode(), signing_string.encode("utf-8"), hashlib.sha1
    ).digest()
    expected = base64.b64encode(digest).decode()
    return hmac.compare_digest(expected, signature)


def verify_slack_v0(
    body: bytes,
    timestamp: str,
    signature: str,
    signing_secret: str,
    max_age_seconds: int = 300,
) -> bool:
    """Verify Slack's ``X-Slack-Signature`` (v0 scheme) with replay protection.

    The signature covers ``v0:{timestamp}:{body}`` HMAC-SHA256'd with the Slack
    app signing secret. Requests older than *max_age_seconds* are rejected.
    """
    if not signature or not signing_secret or not timestamp:
        return False
    try:
        if abs(time.time() - int(timestamp)) > max_age_seconds:
            return False
    except (ValueError, TypeError):
        return False
    basestring = b"v0:" + str(timestamp).encode() + b":" + body
    expected = "v0=" + hmac.new(
        _to_bytes(signing_secret), basestring, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def verify_hubspot_v3(
    method: str,
    uri: str,
    body: bytes,
    timestamp: str,
    signature: str,
    client_secret: str,
    max_age_seconds: int = 300,
) -> bool:
    """Verify HubSpot's ``X-HubSpot-Signature-v3`` with replay protection.

    The signature covers ``{method}{uri}{body}{timestamp}`` HMAC-SHA256'd with
    the HubSpot app client secret, base64-encoded. HubSpot's timestamp is in
    milliseconds since epoch.
    """
    if not signature or not client_secret or not timestamp:
        return False
    try:
        if abs(time.time() * 1000 - int(timestamp)) > max_age_seconds * 1000:
            return False
    except (ValueError, TypeError):
        return False
    basestring = (
        method.encode() + uri.encode() + body + str(timestamp).encode()
    )
    digest = hmac.new(
        _to_bytes(client_secret), basestring, hashlib.sha256
    ).digest()
    expected = base64.b64encode(digest).decode()
    return hmac.compare_digest(expected, signature)


def verify_svix(
    body: bytes,
    webhook_id: str,
    timestamp: str,
    signature_header: str,
    secret: str,
    max_age_seconds: int = 300,
) -> bool:
    """Verify a Svix webhook signature (used by Loops, Clerk, Stytch, etc.).

    Secret format: ``whsec_{base64}`` (or bare base64).
    Signed string: ``{webhook-id}.{webhook-timestamp}.{raw-body}``.
    Header: space-separated ``v1,{base64sig}`` entries.
    """
    if not signature_header or not secret or not webhook_id or not timestamp:
        return False
    try:
        if abs(time.time() - int(timestamp)) > max_age_seconds:
            return False
        # Decode secret: strip prefix up to and including the first underscore.
        raw_secret = base64.b64decode(secret.split("_", 1)[-1] if "_" in secret else secret)
        to_sign = f"{webhook_id}.{timestamp}.".encode() + body
        digest = hmac.new(raw_secret, to_sign, hashlib.sha256).digest()
        expected = base64.b64encode(digest).decode()
        for part in signature_header.split():
            if part.startswith("v1,") and hmac.compare_digest(expected, part[3:]):
                return True
        return False
    except Exception:
        return False


def verify_ed25519(
    body: bytes, timestamp: str, signature: str, public_key_hex: str
) -> bool:
    """Verify Discord's Ed25519 webhook signature over timestamp + raw body."""
    if not signature or not public_key_hex or not timestamp:
        return False
    try:
        public_key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key_hex))
        public_key.verify(bytes.fromhex(signature), str(timestamp).encode() + body)
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False
