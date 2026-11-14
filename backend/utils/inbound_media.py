"""Rehost an inbound message's media as a workflow resource.

A channel provider hands a trigger a media URL the RUN cannot use: authed
with a shared platform key (WhatsApp over WAHooks), minted with the bot's own
token (Telegram's file path embeds it), or expiring on the provider's worker.
The one way such media becomes run-usable — fetchable by the agent, playable
in the run popup, digestible by ``nodes.core.media_digest`` — is to stream it
into workflow resources at delivery time and carry the public capability URL
instead. Each provider's ``transform_trigger_payload`` decides WHICH url and
WHICH auth, then calls :func:`rehost_inbound_media` (or
:func:`copy_inbound_media`, to say something about media over its cap);
media a node already read as bytes (an IMAP attachment) is kept by
:func:`store_inbound_media`.

The returned dict is the ``media`` slot every consumer reads (the frontend's
``deriveInboundMedia`` keys on ``rehosted`` + ``url``):
``{url, mimetype, filename, size, rehosted: True, resource_id}``.
"""

import logging
from typing import Any, AsyncIterator, Dict, Iterable, Optional, Tuple

import httpx

from utils.ssrf import guarded_async_client

logger = logging.getLogger(__name__)

DEFAULT_MAX_BYTES = 25 * 1024 * 1024
DEFAULT_TIMEOUT_S = 20


class MediaTooLarge(Exception):
    """Media over its cap. ``size`` is the size it declared; None when it declared
    none, and the download was stopped at the cap without learning the real one."""

    def __init__(self, source: str, size: Optional[int], max_bytes: int):
        super().__init__(f"{source}: media over the rehost cap of {max_bytes} bytes")
        self.size = size
        self.max_bytes = max_bytes


class MediaFetchFailed(Exception):
    """The provider refused the media (a dead link, usually). Replaces httpx's
    status error, whose message carries the URL and is logged by the delivery seam."""


async def _capped(chunks: AsyncIterator[bytes], source: str, max_bytes: int, sink=None) -> AsyncIterator[bytes]:
    total = 0
    async for chunk in chunks:
        total += len(chunk)
        if total > max_bytes:
            raise MediaTooLarge(source, None, max_bytes)
        if sink is not None:
            sink.add(chunk)
        yield chunk


async def resolve_delivery_credential(
    pool, config: Optional[Dict[str, Any]], workflow_id: str, *credential_keys: str
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """``(credential, owner_id)`` for the trigger node's attached credential
    at delivery time — the one whose token fetches provider-private media —
    resolved as the workflow OWNER (the identity a fire runs as) with the
    owner-fallback policy every run uses. ``credential_keys`` name the
    ``credentialIds`` slots to try in order (a node may accept an OAuth or a
    manual-token credential). ``(None, None)`` when nothing is attached."""
    ids = (config or {}).get("credentialIds") or {}
    credential_id = next((ids[k] for k in credential_keys if ids.get(k)), None)
    if not credential_id:
        return None, None
    owner = await pool.fetchrow(
        "SELECT owner_id, organization_id FROM workflows WHERE id = $1::uuid",
        workflow_id,
    )
    if not owner:
        return None, None
    from utils.credentials import resolve_credential_with_owner_fallback

    owner_id = str(owner["owner_id"])
    credential = await resolve_credential_with_owner_fallback(
        str(credential_id),
        owner_id,
        pool,
        org_id=str(owner["organization_id"]) if owner["organization_id"] else None,
        workflow_id=workflow_id,
    )
    return credential, owner_id


async def _workflow_owner(pool, workflow_id: str):
    return await pool.fetchrow(
        "SELECT owner_id, organization_id FROM workflows WHERE id = $1::uuid",
        workflow_id,
    )


async def rehost_inbound_media(pool, **copy_args) -> Optional[Dict[str, Any]]:
    """:func:`copy_inbound_media` for a channel with nothing to say about media
    over its cap: ``None``, and the delivery proceeds with the original payload —
    media too large to keep is still a message."""
    try:
        return await copy_inbound_media(pool, **copy_args)
    except MediaTooLarge as e:
        logger.warning(f"[inbound_media] {e} — delivering without content")
        return None


async def copy_inbound_media(
    pool,
    *,
    workflow_id: str,
    node_id: Optional[str],
    url: str,
    source: str,
    mimetype: Optional[str] = None,
    filename: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
    declared_size: Optional[int] = None,
    max_bytes: int = DEFAULT_MAX_BYTES,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    trusted_exact_urls: Iterable[str] = (),
    sink=None,
) -> Optional[Dict[str, Any]]:
    """Stream ``url`` into a workflow resource owned by the workflow's owner;
    ``sink`` (``utils.agent_inbox.Held``) is handed each chunk as it passes, so a
    caller keeps the bytes without fetching them twice.

    Raises :class:`MediaTooLarge` when ``declared_size`` or the response's own
    length is over ``max_bytes`` (nothing downloaded) or the body turns out to be
    (stopped there). ``None`` when the workflow is unknown. ``timeout_s`` bounds
    each network operation, not the copy. A provider's refusal raises
    :class:`MediaFetchFailed` and a transport error its own; the delivery seam
    catches them and keeps the original payload. The URL is never logged: a
    provider URL may carry a credential in its path.
    """
    if declared_size is not None and declared_size > max_bytes:
        raise MediaTooLarge(source, declared_size, max_bytes)
    owner = await _workflow_owner(pool, workflow_id)
    if not owner:
        return None

    from utils.resource_store import create_resource_from_stream

    async with guarded_async_client(
        timeout=timeout_s, trusted_exact_urls=trusted_exact_urls
    ) as client:
        async with client.stream("GET", url, headers=headers or {}) as resp:
            try:
                resp.raise_for_status()
            except httpx.HTTPStatusError as e:
                raise MediaFetchFailed(f"{source}: HTTP {e.response.status_code}") from None
            length = resp.headers.get("content-length") or ""
            if length.isdigit() and int(length) > max_bytes:
                raise MediaTooLarge(source, int(length), max_bytes)
            mime = mimetype or resp.headers.get("content-type") or "application/octet-stream"
            name = filename or url.rsplit("/", 1)[-1].split("?", 1)[0] or "inbound-media"
            resource = await create_resource_from_stream(
                user_id=str(owner["owner_id"]),
                workflow_id=str(workflow_id),
                node_id=node_id,
                organization_id=str(owner["organization_id"]) if owner["organization_id"] else None,
                chunks=_capped(resp.aiter_bytes(), source, max_bytes, sink),
                content_type=mime,
                filename=name,
                metadata={"source": source},
            )
    return _media_slot(resource, source=source, mime=mime, name=name)


async def store_inbound_media(
    pool,
    *,
    workflow_id: str,
    node_id: Optional[str],
    body: bytes,
    source: str,
    mimetype: str,
    filename: str,
) -> Optional[Dict[str, Any]]:
    """Keep media a delivery already holds as bytes (a mail attachment read over
    IMAP) the way ``rehost_inbound_media`` keeps fetched media: the same
    resource, owner and ``media`` slot. ``None`` when the workflow is unknown."""
    owner = await _workflow_owner(pool, workflow_id)
    if not owner:
        return None
    return await _store(owner, workflow_id=workflow_id, node_id=node_id, body=body,
                        source=source, mime=mimetype or "application/octet-stream", name=filename)


async def _store(owner, *, workflow_id: str, node_id: Optional[str], body: bytes, source: str,
                 mime: str, name: str) -> Dict[str, Any]:
    from utils.resource_store import create_resource_from_bytes

    resource = await create_resource_from_bytes(
        user_id=str(owner["owner_id"]),
        workflow_id=str(workflow_id),
        node_id=node_id,
        organization_id=str(owner["organization_id"]) if owner["organization_id"] else None,
        body=body,
        content_type=mime,
        filename=name,
        metadata={"source": source},
    )
    return _media_slot(resource, source=source, mime=mime, name=name)


def _media_slot(resource: Dict[str, Any], *, source: str, mime: str, name: str) -> Dict[str, Any]:
    logger.info(
        f"[inbound_media] {source}: rehosted {resource['size_bytes']} bytes "
        f"({mime}) as resource {resource['resource_id']}"
    )
    return {
        "url": resource["download_url"],
        "mimetype": mime,
        "filename": name,
        "size": resource["size_bytes"],
        "rehosted": True,
        "resource_id": resource["resource_id"],
    }
