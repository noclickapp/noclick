"""Meter Decodo requests through the same owner-pays gate as other API nodes."""

import asyncio
from decimal import Decimal

from nodes.core.decodo_client import DecodoJsonClient
from nodes.core.platform_billing import require_platform_key


class DecodoRunnerMixin:
    async def _run_decodo(self, operation, *, action_name, platform, timeout=120):
        from billing.usage_tracker import usage_tracker

        if not self.user_id:
            raise ValueError("Cannot meter scraping without a user context")
        token = require_platform_key("DECODO_AUTH_TOKEN", "Decodo", byok=False)
        await usage_tracker.enforce_credit_gate(
            self.user_id, organization_id=self.organization_id, sio=self.sio,
            sid=self.sid, user_resource=False, surface="decodo",
        )
        client = DecodoJsonClient(token)
        output = None
        try:
            async with client, asyncio.timeout(timeout):
                output = await operation(client)
        except TimeoutError:
            raise TimeoutError(f"Decodo scraping exceeded the {timeout:g}-second operation deadline") from None
        finally:
            if client.billable_requests:
                await self._track_decodo_usage(client, action_name, platform, output is not None)
        await self.emit(output)
        return output

    async def _track_decodo_usage(self, client, action_name, platform, succeeded):
        from billing.markup import apply_platform_markup
        from billing.schema import UsageEventData
        from billing.usage_tracker import usage_tracker

        raw = client.unit_cost * client.billable_requests
        charged = apply_platform_markup(raw, False, "decodo")
        event = UsageEventData(
            user_id=self.user_id, organization_id=self.organization_id,
            total_cost=charged, usage_type="api_usage", usage_subtype=f"{platform}_scraping",
            quantity=Decimal(client.billable_requests), unit_type="requests", user_resource=False,
            metadata={
                "provider": "decodo", "platform": platform, "operation": action_name,
                "requests_attempted": client.attempts, "billable_requests": client.billable_requests,
                "unit_cost_usd": float(client.unit_cost), "raw_cost_usd": float(raw),
                "charged_cost_usd": float(charged), "task_ids": client.task_ids,
                "succeeded": succeeded,
            },
        )
        await usage_tracker.track_usage_event(event, sio=self.sio, sid=self.sid)
