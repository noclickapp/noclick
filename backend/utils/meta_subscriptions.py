"""Bounded, secret-safe Graph requests and serialized subscription updates."""

import asyncio
from contextlib import asynccontextmanager
from contextvars import ContextVar
import logging
import re
from uuid import uuid4

import httpx

logger = logging.getLogger(__name__)
_FIELD = re.compile(r"[A-Za-z][A-Za-z0-9_]*\Z")
_PRIVATE_REQUEST = ContextVar("meta_subscription_request", default=False)


class _TransportPrivacy(logging.Filter):
    def filter(self, record):
        if _PRIVATE_REQUEST.get():
            # HTTPX INFO includes query tokens; HTTP/2 DEBUG can include headers.
            record.msg, record.args = "Meta Graph transport activity", ()
            record.exc_info = record.exc_text = record.stack_info = None
        return True


_TRANSPORT_PRIVACY = _TransportPrivacy()


class MetaAuthorizationDenied(ValueError):
    """A definitive provider rejection, unlike an unavailable verification."""


async def graph_request(client, method, path, *, base, label, params=None, data=None):
    # Callers provide fixed relative paths and tokens in Authorization headers.
    for name in tuple(logging.Logger.manager.loggerDict):
        if name == "httpx" or name.startswith(("httpx.", "httpcore.")):
            logging.getLogger(name).addFilter(_TRANSPORT_PRIVACY)
    private = _PRIVATE_REQUEST.set(True)
    try:
        response = await client.request(method, f"{base}/{path}", params=params, data=data)
    except httpx.HTTPError:
        raise ValueError(f"{label} subscription request failed; retry registration later.") from None
    finally:
        _PRIVATE_REQUEST.reset(private)
    try:
        body = response.json()
    except ValueError:
        raise ValueError(f"{label} subscription returned an invalid response.") from None
    error = body.get("error") if isinstance(body, dict) else None
    if isinstance(error, dict) and error.get("is_transient") is not True and error.get("code") in (10, 102, 190, 200):
        raise MetaAuthorizationDenied(f"{label} account authorization is unavailable; reconnect with the required Page permissions.")
    if response.status_code != 200:
        raise ValueError(f"{label} subscription request returned HTTP {response.status_code}; check account access and callback setup.")
    if not isinstance(body, dict) or error:
        raise ValueError(f"{label} rejected the subscription request; check account access and callback setup.")
    return body


async def read_edge(request, path, *, fields, label, max_pages=5):
    """Exhaust a Graph edge; follow opaque cursors, never provider URLs."""
    rows, seen_cursors = [], set()
    after = None
    for _ in range(max_pages):
        params = {"fields": fields, "limit": 100}
        if after:
            params["after"] = after
        body = await request("GET", path, params=params)
        page = body.get("data")
        if not isinstance(page, list) or any(not isinstance(row, dict) for row in page):
            raise ValueError(f"{label} returned invalid subscription data; existing fields were not changed.")
        rows.extend(page)
        paging = body.get("paging")
        if paging is None:
            return rows
        if not isinstance(paging, dict):
            raise ValueError(f"{label} returned invalid subscription pagination.")
        if not paging.get("next"):
            return rows
        cursors = paging.get("cursors")
        after = cursors.get("after") if isinstance(cursors, dict) else None
        if not isinstance(after, str) or not after or len(after) > 8192 or after in seen_cursors:
            raise ValueError(f"{label} subscription pagination is incomplete; existing fields were not changed.")
        seen_cursors.add(after)
    raise ValueError(f"{label} subscription pagination exceeded its safety bound; existing fields were not changed.")


async def read_subscribed_fields(request, account_id, app_ids, *, label, require_matching_if_nonempty=True):
    rows = await read_edge(request, f"{account_id}/subscribed_apps", fields="id,subscribed_fields", label=label)
    if any(not isinstance(row.get("id"), (str, int)) or isinstance(row["id"], bool)
           or not re.fullmatch(r"[1-9][0-9]{0,31}", str(row["id"])) for row in rows):
        raise ValueError(f"{label} subscribed-app identity is invalid; existing fields were not changed.")
    matching = [row for row in rows if str(row["id"]) in app_ids]
    if len(matching) > 1 or (rows and not matching and require_matching_if_nonempty):
        raise ValueError(f"{label} subscribed-app identity does not match the configured webhook app; existing fields were not changed.")
    if not matching:
        return set()
    fields = matching[0].get("subscribed_fields")
    if not isinstance(fields, list) or any(not isinstance(field, str) or not _FIELD.fullmatch(field) for field in fields):
        raise ValueError(f"{label} did not return a valid subscribed-fields list; existing fields were not changed.")
    return set(fields)


@asynccontextmanager
async def registration_lease(account_id, app_id, *, provider, label):
    from utils.redis_client import get_shared_redis

    redis = get_shared_redis()
    if redis is None:
        raise ValueError(f"{label} registration lock is unavailable; retry later.")
    key, owner = f"{provider}:subscription-register:{app_id}:{account_id}", str(uuid4())
    try:
        async with asyncio.timeout(5):
            acquired = await redis.set(key, owner, nx=True, ex=90)
    except Exception:
        raise ValueError(f"{label} registration lock is unavailable; retry later.") from None
    if not acquired:
        raise ValueError(f"{label} account registration is already in progress; retry later.")

    async def check_owner():
        try:
            async with asyncio.timeout(5):
                held = await redis.get(key)
        except Exception:
            raise ValueError(f"{label} registration lock is unavailable; retry later.") from None
        if held not in (owner, owner.encode()):
            raise ValueError(f"{label} registration lock was lost; remote fields may have changed; retry verification.")

    try:
        async with asyncio.timeout(45):
            yield check_owner
            await check_owner()
    except TimeoutError:
        raise ValueError(f"{label} subscription verification timed out; remote fields may have changed; retry registration later.") from None
    finally:
        try:
            async with asyncio.timeout(5):
                await redis.eval(
                    "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end",
                    1, key, owner,
                )
        except Exception:
            logger.warning("%s registration lease release failed; it will expire automatically.", label)
