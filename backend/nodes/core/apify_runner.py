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
        from billing.markup import apply_apify_markup, PLATFORM_MIN_MARKUP
        from billing.schema import UsageEventData
        from billing.usage_tracker import usage_tracker

        raw = Decimal(str(raw_cost_usd or 0))
        charged = apply_apify_markup(raw)
        markup_pct = int((PLATFORM_MIN_MARKUP - 1) * 100)

        if not self.user_id:
            logger.error(f"[{type(self).__name__}] No user_id; skipping usage tracking")
            return

        # Pass the raw runner; track_usage_event resolves to the org owner
        # centrally (Owner Pays choke point).
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
                "markup_pct": markup_pct,
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
        *,
        build: Optional[str] = None,
        max_total_charge_usd: Optional[float] = None,
        summary_key: Optional[str] = None,
        result_charge_event: Optional[str] = None,
        emit_output: bool = True,
    ) -> Dict[str, Any]:
        """Run, validate and meter an actor. Provider failures must fail the tool."""
        total_start = time.monotonic()
        await self._check_credits_or_raise()
        token = self._get_apify_token()
        actor_id = actor_id.replace("/", "~")
        terminal = {"SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"}
        params = {"waitForFinish": 30, "timeout": int(APIFY_ACTOR_TIMEOUT_SECONDS)}
        if build:
            params["build"] = build
        if max_total_charge_usd is not None:
            params["maxTotalChargeUsd"] = max_total_charge_usd
        run = {}
        items = []
        summary = None
        api_time = 0.0
        validated = False
        async with httpx.AsyncClient(
            headers={"Authorization": f"Bearer {token}"},
            timeout=httpx.Timeout(connect=15.0, read=75.0, write=30.0, pool=15.0),
        ) as client:
            try:
                response = await client.post(
                    f"{APIFY_API_BASE}/acts/{actor_id}/runs",
                    params=params,
                    json=actor_input,
                )
                api_time = (time.monotonic() - total_start) * 1000
                run = self._apify_json(response).get("data") or {}
                if not run.get("id"):
                    raise RuntimeError("Apify did not return a run id")
                while run.get("status") not in terminal:
                    if time.monotonic() - total_start > APIFY_ACTOR_TIMEOUT_SECONDS:
                        raise TimeoutError("Apify scraper exceeded its execution time limit")
                    response = await client.get(
                        f"{APIFY_API_BASE}/actor-runs/{run['id']}",
                        params={"waitForFinish": 30},
                    )
                    polled = self._apify_json(response).get("data") or {}
                    if not polled.get("status"):
                        raise RuntimeError("Apify returned an invalid run status")
                    run = polled
                if run["status"] != "SUCCEEDED":
                    raise RuntimeError(
                        f"Apify run {run['id']} finished with status={run['status']}: "
                        f"{run.get('statusMessage') or 'Scraping did not complete'}"
                    )
                if not run.get("defaultDatasetId"):
                    raise RuntimeError("Apify completed without a dataset")
                while True:
                    response = await client.get(
                        f"{APIFY_API_BASE}/datasets/{run['defaultDatasetId']}/items",
                        params={
                            "format": "json",
                            "clean": "true",
                            "offset": len(items),
                            "limit": 1000,
                        },
                    )
                    page = self._apify_json(response)
                    if not isinstance(page, list) or any(not isinstance(x, dict) for x in page):
                        raise RuntimeError("Apify returned an invalid dataset")
                    items.extend(page)
                    if len(page) < 1000:
                        break
                for item in items:
                    if item.get("error"):
                        raise RuntimeError(
                            f"Apify scraper returned an error: {str(item['error'])[:500]}"
                        )
                if summary_key:
                    store_id = run.get("defaultKeyValueStoreId")
                    if not store_id:
                        raise RuntimeError("Apify completed without a run summary store")
                    summary = self._apify_json(
                        await client.get(
                            f"{APIFY_API_BASE}/key-value-stores/{store_id}/records/{summary_key}",
                        )
                    )
                    self._validate_apify_summary(summary, len(items))
                validated = True
            finally:
                if run.get("id"):
                    if run.get("status") not in terminal:
                        # Poll failures and task cancellation must not leave paid work running.
                        try:
                            aborted = self._apify_json(
                                await client.post(
                                    f"{APIFY_API_BASE}/actor-runs/{run['id']}/abort",
                                )
                            ).get("data")
                            if aborted:
                                run = aborted
                        except Exception:
                            logger.exception(
                                "Could not abort Apify run %s; server timeout remains active",
                                run["id"],
                            )
                    # Even a nonzero total can still contain only the startup charge.
                    previous_cost = run.get("usageTotalUsd")
                    settled = False
                    delays = (1, 2, 4, 8, 15, 30) if result_charge_event else (1, 2, 3, 4)
                    for delay in delays:
                        try:
                            await asyncio.sleep(delay)
                            fresh = (
                                self._apify_json(
                                    await client.get(
                                        f"{APIFY_API_BASE}/actor-runs/{run['id']}",
                                        params={"waitForFinish": 0},
                                    )
                                ).get("data")
                                or {}
                            )
                            if not fresh.get("id"):
                                raise RuntimeError("Missing run metadata when settling Apify usage")
                            run = fresh
                            cost = run.get("usageTotalUsd")
                            counts = run.get("chargedEventCounts") or {}
                            event_cost = self._apify_event_cost(run)
                            if (
                                cost is not None
                                and (
                                    event_cost is None
                                    or Decimal(str(cost)) + Decimal("1e-12") >= event_cost
                                )
                                and (
                                    (result_charge_event and event_cost is not None)
                                    or (delay >= 2 and cost == previous_cost)
                                )
                                and (
                                    not result_charge_event
                                    or counts.get(result_charge_event, 0) >= len(items)
                                )
                            ):
                                settled = True
                                break
                            previous_cost = cost
                        except Exception:
                            logger.exception(
                                "Could not refresh final cost for Apify run %s", run["id"]
                            )
                            break
                    await self._track_apify_usage(
                        actor_id,
                        action_name,
                        usage_subtype,
                        float(run.get("usageTotalUsd") or 0),
                        len(items),
                        run["id"],
                        platform=platform,
                    )
                    if result_charge_event and validated and not settled:
                        raise RuntimeError(
                            f"Apify usage for run {run['id']} has not settled; "
                            "the provider has not confirmed all result charges."
                        )
        output = {
            "type": platform,
            "action": action_name,
            "status": "success",
            "data": {"items": items, "count": len(items)},
            "timing_ms": {
                "api_request": round(api_time, 1),
                "total": round((time.monotonic() - total_start) * 1000, 1),
            },
        }
        if emit_output:
            await self.emit(output)
        return output

    @staticmethod
    def _apify_event_cost(run: Dict[str, Any]) -> Optional[Decimal]:
        """The aggregate total can lag even after individual charges are visible."""
        pricing = run.get("pricingInfo") or {}
        if pricing.get("pricingModel") != "PAY_PER_EVENT":
            return None
        events = (pricing.get("pricingPerEvent") or {}).get("actorChargeEvents") or {}
        counts = run.get("chargedEventCounts") or {}
        if any(name not in events or "eventPriceUsd" not in events[name] for name in counts):
            return None
        return sum(
            (
                Decimal(str(count)) * Decimal(str(events[name]["eventPriceUsd"]))
                for name, count in counts.items()
            ),
            Decimal(0),
        )

    @staticmethod
    def _apify_json(response: httpx.Response):
        try:
            payload = response.json()
        except (json.JSONDecodeError, ValueError):
            raise RuntimeError(
                f"Apify returned a non-JSON response (HTTP {response.status_code})"
            ) from None
        if response.status_code >= 400:
            error = payload.get("error", {}) if isinstance(payload, dict) else {}
            message = error.get("message") if isinstance(error, dict) else str(error)
            raise RuntimeError(
                f"Apify request failed (HTTP {response.status_code}): {message or 'Provider request failed'}"
            )
        return payload

    @staticmethod
    def _validate_apify_summary(summary, item_count: int) -> None:
        if not isinstance(summary, dict) or summary.get("itemsTotal") != item_count:
            raise RuntimeError("Apify run summary does not match the returned dataset")
        requests = summary.get("requests") or {}
        if (
            not requests.get("finished")
            or requests.get("failed")
            or summary.get("skippedTotal")
            or summary.get("inputWarnings")
            or summary.get("chargeLimitReached")
        ):
            raise RuntimeError(
                "Apify scraper returned incomplete results (failed/skipped requests, "
                "input warnings, or a spending limit). Retry with a smaller request."
            )
