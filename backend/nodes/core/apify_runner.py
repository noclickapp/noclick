"""
Reusable Apify actor runner mixin for workflow nodes.

Provides _run_apify_actor(), _track_apify_usage(), _check_credits_or_raise(),
_get_apify_token(), and _split_lines() so multiple nodes (Instagram, LinkedIn,
etc.) share Apify integration logic without code duplication. The mixin
intentionally omits internal Apify metadata (actor_id, run_id, billing) from
user-facing output — only platform-relevant fields are returned.
"""

import asyncio
import json
import logging
import os
import time
from decimal import Decimal
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

APIFY_API_BASE = "https://api.apify.com/v2"
APIFY_ACTOR_TIMEOUT_SECONDS = 540.0


class ApifyRunnerMixin:
    """Mixin for WorkflowNode subclasses that call Apify actors.

    Host class must expose: self.sio, self.sid, self.user_id,
    self.organization_id, and self.emit() — all provided by WorkflowNode.
    """

    @staticmethod
    def _get_apify_token() -> str:
        from nodes.core.platform_billing import require_platform_key

        return require_platform_key("APIFY_API_TOKEN", "Apify", byok=False)

    @staticmethod
    def _split_lines(value: Optional[str]) -> List[str]:
        """Split a textarea value into a deduped list of non-empty trimmed lines."""
        seen: List[str] = []
        for line in (value or "").splitlines():
            stripped = line.strip()
            if stripped and stripped not in seen:
                seen.append(stripped)
        return seen

    async def _check_credits_or_raise(self) -> None:
        """Pre-flight gate via the standardized helper: strict org-owner
        resolution (org work with no resolvable owner fails the run), balance
        check at MIN_CREDITS, exhausted-event emit, and abort. Apify is always
        NoClick-keyed (user_resource=False)."""
        if not self.user_id:
            raise ValueError(f"[{type(self).__name__}] No user context — cannot meter Apify usage.")
        from billing.usage_tracker import usage_tracker
        await usage_tracker.enforce_credit_gate(
            self.user_id,
            organization_id=self.organization_id,
            sio=self.sio,
            sid=self.sid,
            user_resource=False,
            surface="apify",
        )

    async def _track_apify_usage(
        self,
        actor_id: str,
        action_name: str,
        usage_subtype: str,
        raw_cost_usd: float,
        item_count: int,
        run_id: Optional[str],
        platform: str = "unknown",
    ) -> None:
        """Apply the platform markup to the actor's actual cost and record a UsageEventData."""
        from billing.markup import apply_apify_markup
        from billing.schema import UsageEventData
        from billing.usage_tracker import usage_tracker

        raw = Decimal(str(raw_cost_usd or 0))
        charged = apply_apify_markup(raw)

        if not self.user_id:
            logger.error(f"[{type(self).__name__}] No user_id; skipping usage tracking")
            return

        # Pass the raw runner; track_usage_event resolves to the org owner
        # centrally (organization attribution policy choke point).
        usage_event = UsageEventData(
            user_id=self.user_id,
            total_cost=charged,
            usage_type="api_usage",
            usage_subtype=usage_subtype,
            quantity=Decimal(str(item_count)),
            unit_type="requests",
            user_resource=False,
            organization_id=self.organization_id,
            metadata={
                "platform": platform,
                "provider": "apify",
                "actor_id": actor_id,
                "operation": action_name,
                "run_id": run_id,
                "items_returned": item_count,
                "raw_cost_usd": float(raw),
                "charged_cost_usd": float(charged),
            },
        )
        try:
            await usage_tracker.track_usage_event(
                usage_event,
                sio=self.sio,
                sid=self.sid,
            )
        except Exception as e:
            logger.error(f"[{type(self).__name__}] Failed to track Apify usage: {e}")

    async def _run_apify_actor(
        self,
        actor_id: str,
        actor_input: Dict[str, Any],
        action_name: str,
        usage_subtype: str,
        platform: str,
    ) -> Dict[str, Any]:
        """Run an Apify actor, fetch dataset items, and charge the user.

        Pattern:
          1. POST /v2/acts/{id}/runs?waitForFinish=60
          2. Poll GET /v2/actor-runs/{runId}?waitForFinish=60 until terminal
          3. GET /v2/datasets/{defaultDatasetId}/items
          4. Track cost from usageTotalUsd with markup via _track_apify_usage()

        Returns only platform-facing fields; internal Apify details (actor_id,
        run_id, billing) are omitted from the output to keep the user-facing
        response clean.
        """
        total_start = time.time()
        await self._check_credits_or_raise()
        token = self._get_apify_token()
        normalized_actor_id = actor_id.replace("/", "~")

        logger.info(f"[{type(self).__name__}] Apify actor={normalized_actor_id} action={action_name}")

        items: List[Any] = []
        run_id: Optional[str] = None
        api_time: float = 0.0
        usage_total_usd: float = 0.0
        terminal_statuses = {"SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"}

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(connect=15.0, read=120.0, write=30.0, pool=15.0)
        ) as client:
            api_start = time.time()
            start_resp = await client.post(
                f"{APIFY_API_BASE}/acts/{normalized_actor_id}/runs",
                params={"token": token, "waitForFinish": "60"},
                json=actor_input,
            )
            api_time = (time.time() - api_start) * 1000

            if start_resp.status_code >= 400:
                return await self._emit_apify_error(
                    platform, action_name, start_resp, total_start, api_time
                )

            try:
                run_data = (start_resp.json() or {}).get("data") or {}
            except json.JSONDecodeError:
                run_data = {}
            run_id = run_data.get("id")
            dataset_id = run_data.get("defaultDatasetId")
            run_status = run_data.get("status")

            if not run_id:
                err = f"Apify did not return a run id (response: {start_resp.text[:200]})"
                return await self._emit_apify_error_text(
                    platform, action_name, err, total_start, api_time
                )

            while run_status not in terminal_statuses:
                if (time.time() - total_start) > APIFY_ACTOR_TIMEOUT_SECONDS:
                    logger.warning(f"[{type(self).__name__}] Apify run {run_id} exceeded timeout")
                    break
                poll_resp = await client.get(
                    f"{APIFY_API_BASE}/actor-runs/{run_id}",
                    params={"token": token, "waitForFinish": "60"},
                )
                if poll_resp.status_code >= 400:
                    break
                try:
                    run_data = (poll_resp.json() or {}).get("data") or run_data
                    run_status = run_data.get("status")
                except json.JSONDecodeError:
                    break

            # usageTotalUsd is computed asynchronously after run termination —
            # retry up to ~10s with backoff if it's still 0.
            usage_total_usd = float(run_data.get("usageTotalUsd") or 0)
            if run_status in terminal_statuses and usage_total_usd == 0:
                for delay in (1, 2, 3, 4):
                    await asyncio.sleep(delay)
                    refetch = await client.get(
                        f"{APIFY_API_BASE}/actor-runs/{run_id}",
                        params={"token": token},
                    )
                    if refetch.status_code >= 400:
                        break
                    try:
                        run_data = (refetch.json() or {}).get("data") or run_data
                    except json.JSONDecodeError:
                        break
                    usage_total_usd = float(run_data.get("usageTotalUsd") or 0)
                    if usage_total_usd > 0:
                        break

            items = []
            if dataset_id:
                items_resp = await client.get(
                    f"{APIFY_API_BASE}/datasets/{dataset_id}/items",
                    params={"token": token, "format": "json", "clean": "true"},
                )
                if items_resp.status_code < 400:
                    try:
                        parsed = items_resp.json()
                        items = parsed if isinstance(parsed, list) else [parsed]
                    except json.JSONDecodeError:
                        items = []
                else:
                    logger.warning(
                        f"[{type(self).__name__}] dataset fetch failed: "
                        f"{items_resp.status_code} {items_resp.text[:200]}"
                    )

            if run_status and run_status != "SUCCEEDED":
                err = (
                    f"Apify run finished with status={run_status}. "
                    f"See https://console.apify.com/actors/runs/{run_id}"
                )
                logger.error(f"[{type(self).__name__}] {err}")
                await self._track_apify_usage(
                    normalized_actor_id, action_name, usage_subtype,
                    usage_total_usd, len(items), run_id, platform=platform,
                )
                total_time = (time.time() - total_start) * 1000
                output = {
                    "type": platform,
                    "action": action_name,
                    "status": "error",
                    "error": err,
                    "data": {"items": items, "count": len(items)},
                    "timing_ms": {"total": round(total_time, 1)},
                }
                await self.emit(output)
                return output

        await self._track_apify_usage(
            normalized_actor_id, action_name, usage_subtype,
            usage_total_usd, len(items), run_id, platform=platform,
        )
        total_time = (time.time() - total_start) * 1000
        output = {
            "type": platform,
            "action": action_name,
            "status": "success",
            "data": {"items": items, "count": len(items)},
            "timing_ms": {
                "api_request": round(api_time, 1),
                "total": round(total_time, 1),
            },
        }
        await self.emit(output)
        return output

    async def _emit_apify_error(
        self,
        platform: str,
        action_name: str,
        response: "httpx.Response",
        total_start: float,
        api_time_ms: float,
    ) -> Dict[str, Any]:
        try:
            error_data = response.json()
            error_msg = error_data.get("error", {}).get("message", response.text)
        except Exception:
            error_msg = response.text
        return await self._emit_apify_error_text(
            platform, action_name, error_msg, total_start, api_time_ms,
            status_code=response.status_code,
        )

    async def _emit_apify_error_text(
        self,
        platform: str,
        action_name: str,
        error_msg: str,
        total_start: float,
        api_time_ms: float,
        status_code: Optional[int] = None,
    ) -> Dict[str, Any]:
        logger.error(f"[{type(self).__name__}] Apify error: {error_msg}")
        total_time = (time.time() - total_start) * 1000
        output = {
            "type": platform,
            "action": action_name,
            "status": "error",
            "error": error_msg,
            "data": None,
            "timing_ms": {
                "api_request": round(api_time_ms, 1),
                "total": round(total_time, 1),
            },
        }
        await self.emit(output)
        return output
