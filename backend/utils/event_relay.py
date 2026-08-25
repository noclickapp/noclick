"""In-process event relay used by the self-hosted edition."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

from pydantic import BaseModel

from utils.local_relay import get_local_relay_hub

logger = logging.getLogger(__name__)

# Kept for compatibility with shared callers that select the Socket.IO fallback
# when no external relay is configured. Community delivery itself is in-process.
EVENT_RELAY_SECRET = ""


def _prepare_event_payload(
    event: BaseModel,
) -> Optional[Tuple[str, Dict[str, Any]]]:
    event_name = getattr(event, "event_name", None)
    if not event_name:
        return None
    try:
        data = event.model_dump(mode="json", exclude_none=True)
    except TypeError:
        data = event.model_dump()
    data["type"] = event_name
    return event_name, data


async def broadcast_to_user_safe(
    user_id: str,
    event: BaseModel,
    workflow_id: Optional[str] = None,
    timeout: float = 12.0,
) -> dict:
    del timeout
    prepared = _prepare_event_payload(event)
    if prepared is None:
        logger.error(
            "%s must define an event_name class variable",
            event.__class__.__name__,
        )
        return {"success": False, "error": "missing_event_name"}
    _event_name, data = prepared
    sent = await get_local_relay_hub().publish_user_event(
        user_id, data, workflow_id
    )
    return {"success": True, "delivered": sent}


async def broadcast_dict_to_user_safe(
    user_id: str,
    event_name: str,
    data: Dict[str, Any],
    workflow_id: Optional[str] = None,
) -> dict:
    payload = dict(data)
    payload.setdefault("type", event_name)
    sent = await get_local_relay_hub().publish_user_event(
        user_id, payload, workflow_id
    )
    return {"success": True, "delivered": sent}


async def request_from_frontend(
    user_id: str,
    request_type: str,
    params: dict,
    timeout: float = 10.0,
    collect_ms: int = 0,
) -> dict:
    return await get_local_relay_hub().request_frontend(
        user_id,
        request_type,
        params,
        timeout=timeout,
        collect_ms=collect_ms,
    )
