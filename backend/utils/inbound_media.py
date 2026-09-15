"""Rehost an inbound message's media as a workflow resource.

A channel provider hands a trigger a media URL the RUN cannot use: authed
with a shared platform key (WhatsApp over WAHooks), minted with the bot's own
token (Telegram's file path embeds it), or expiring on the provider's worker.
The one way such media becomes run-usable — fetchable by the agent, playable
in the run popup, digestible by ``nodes.core.media_digest`` — is to stream it
into workflow resources at delivery time and carry the public capability URL
instead. Each provider's ``transform_trigger_payload`` decides WHICH url and
WHICH auth, then calls :func:`rehost_inbound_media`.

The returned dict is the ``media`` slot every consumer reads (the frontend's
``deriveInboundMedia`` keys on ``rehosted`` + ``url``):
``{url, mimetype, filename, size, rehosted: True, resource_id}``.
"""

import logging
from typing import Any, Dict, Iterable, Optional

from utils.ssrf import guarded_async_client

logger = logging.getLogger(__name__)

DEFAULT_MAX_BYTES = 25 * 1024 * 1024
DEFAULT_TIMEOUT_S = 20


async def rehost_inbound_media(
    pool,
    *,
    workflow_id: str,
    node_id: Optional[str],
    url: str,
    source: str,
    mimetype: Optional[str] = None,
    filename: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
    max_bytes: int = DEFAULT_MAX_BYTES,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    trusted_exact_urls: Iterable[str] = (),
) -> Optional[Dict[str, Any]]:
    """Stream ``url`` into a workflow resource owned by the workflow's owner.

    ``None`` when the workflow is unknown or the body exceeds ``max_bytes``
    (the delivery then proceeds with the original payload — media that is
    too large to keep is still a message). Transport errors raise; the
    delivery seam catches them and keeps the original payload. The URL is
    never logged: a provider URL may carry a credential in its path.
    """
    owner = await pool.fetchrow(
        "SELECT owner_id, organization_id FROM workflows WHERE id = $1::uuid",
        workflow_id,
    )
    if not owner:
        return None

    chunks, total = [], 0
    async with guarded_async_client(
        timeout=timeout_s, trusted_exact_urls=trusted_exact_urls
    ) as client:
        async with client.stream("GET", url, headers=headers or {}) as resp:
            resp.raise_for_status()
            content_type_header = resp.headers.get("content-type")
            async for chunk in resp.aiter_bytes():
                total += len(chunk)
                if total > max_bytes:
                    logger.warning(
                        f"[inbound_media] {source}: media exceeds rehost cap "
                        f"({max_bytes} bytes) — delivering without content"
                    )
                    return None
                chunks.append(chunk)
    body = b"".join(chunks)

    from utils.resource_store import create_resource_from_bytes

    mime = mimetype or content_type_header or "application/octet-stream"
    name = filename or url.rsplit("/", 1)[-1].split("?", 1)[0] or "inbound-media"
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
