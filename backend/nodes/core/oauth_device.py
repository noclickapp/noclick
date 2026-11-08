"""RFC 8628 polling shared with subscription sign-ins.

Device codes stay encrypted server-side. Browser ids are single-use, bound to
both the provider and the initiating account/connect link. Redis serializes
polls across containers and enforces the provider's interval server-side.
"""
import math
import re
import secrets
import time

from nodes.core.oauth_provider import OAuthTokens

DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"


def device_poll_status(error):
    if not isinstance(error, str):
        return None
    return {
        "authorization_pending": "pending",
        "slow_down": "slow_down",
        "expired_token": "expired",
        "access_denied": "denied",
        "authorization_denied": "denied",
    }.get(error)


def _redis():
    from utils.redis_client import get_shared_redis

    redis = get_shared_redis()
    if redis is None:
        raise ValueError("Device sign-in requires configured Redis")
    return redis


def _encryption():
    from utils.encryption import get_encryption

    return get_encryption()


async def start_device(spec, *, binding: str, scopes: list[str], context: dict):
    if not spec.device:
        raise ValueError("Provider does not support device authorization")
    spec.granted_scopes(OAuthTokens(access_token="scope-check"), scopes)
    context = spec.validate_context(context, sources={"input"})
    request = spec.token_request({}, context=context)
    request["url"] = spec.endpoint(spec.device.authorization_url, context)
    body_key = "json" if spec.token_format == "json" else "data"
    # Device authorization is not a token grant. Only declared device params,
    # client authentication and scopes belong in its request.
    request[body_key] = {
        k: v
        for k, v in request[body_key].items()
        if k in ("client_id", "client_secret")
    }
    request[body_key].update(
        spec.device.params, scope=spec.scope_separator.join(scopes)
    )
    redis = _redis()  # Refuse before issuing a device code we cannot retain.
    async with spec._client(spec.device.authorization_url) as client:
        response = await client.post(**request)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict) or not all(
        isinstance(payload.get(k), str) and payload[k]
        for k in ("device_code", "user_code", "verification_uri")
    ):
        raise ValueError("Incomplete OAuth device response")
    if not payload["verification_uri"].startswith("https://"):
        raise ValueError("Device verification URI must use HTTPS")
    interval, expires = int(payload.get("interval", 5)), int(payload["expires_in"])
    if not 1 <= interval <= 3600 or not 1 <= expires <= 86400:
        raise ValueError("Invalid device authorization lifetime")
    authorization_id = secrets.token_urlsafe(32)
    state = {
        "provider": spec.provider,
        "binding": binding,
        "device_code": payload["device_code"],
        "scopes": scopes,
        "context": context,
        "interval": interval,
        "expires_at": time.time() + expires,
        "next_poll": time.time() + interval,
    }
    await redis.set(
        "oauth:device:" + authorization_id,
        _encryption().encrypt_credential(state),
        ex=expires,
    )
    return {
        "status": "pending",
        "authorization_id": authorization_id,
        "user_code": payload["user_code"],
        "verification_uri": payload["verification_uri"],
        "interval": interval,
        "expires_in": expires,
    }


async def poll_device(spec, *, binding: str, authorization_id: str, complete):
    if not spec.device or not re.fullmatch(r"[A-Za-z0-9_-]{43}", authorization_id):
        raise ValueError("Invalid device authorization")
    redis = _redis()
    key = "oauth:device:" + authorization_id
    lock = redis.lock(key + ":lock", timeout=120, blocking_timeout=1)
    if not await lock.acquire():
        return {"status": "pending", "interval": 5}
    try:
        raw = await redis.get(key)
        if not raw:
            return {"status": "expired"}
        state = _encryption().decrypt_credential(
            raw.decode() if isinstance(raw, bytes) else raw
        )
        if state["provider"] != spec.provider or state["binding"] != binding:
            raise ValueError("Device authorization does not belong to this connection")
        remaining = state["expires_at"] - time.time()
        if remaining <= 0:
            await redis.delete(key)
            return {"status": "expired"}
        if time.time() < state["next_poll"]:
            return {
                "status": "pending",
                "interval": max(1, math.ceil(state["next_poll"] - time.time())),
            }
        state["next_poll"] = time.time() + state["interval"]
        await redis.set(
            key,
            _encryption().encrypt_credential(state),
            ex=max(1, math.ceil(remaining)),
        )
        async with spec._client(spec.token_url) as client:
            response = await client.post(
                **spec.token_request(
                    {"grant_type": DEVICE_GRANT, "device_code": state["device_code"]},
                    context=state["context"],
                )
            )
        payload = response.json()
        status = (
            device_poll_status(payload.get("error"))
            if isinstance(payload, dict)
            else None
        )
        if status in ("pending", "slow_down"):
            if status == "slow_down":
                state["interval"] += 5
            state["next_poll"] = time.time() + state["interval"]
            await redis.set(
                key,
                _encryption().encrypt_credential(state),
                ex=max(1, math.ceil(remaining)),
            )
            return {"status": status, "interval": state["interval"]}
        # Consume before any identity or credential write; no replay on a failed
        # completion, which may already have spent a rotating token.
        await redis.delete(key)
        if status:
            return {"status": status}
        tokens, _ = spec.parse_tokens(response, context=state["context"])
        name = await spec.account_name(
            tokens.access_token,
            context={k: getattr(tokens, k) for k in spec.context_fields},
        )
        result = await complete(tokens, name, state["scopes"])
        return {"status": "completed", **result}
    finally:
        await lock.release()
