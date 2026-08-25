"""
Delay node for adding wait/timeout functionality in workflows.

Short delays (<= 15 minutes) run in-process with asyncio.sleep. Longer delays
suspend the workflow run and resume it later via a scheduled wake-up — so a
delay of days or weeks survives backend restarts and deploys.

Useful for:
- Waiting for external API processing (e.g., video generation, AI tasks)
- Rate limiting and throttling
- Polling intervals
- Onboarding / drip sequences with multi-day gaps
"""

import asyncio
import time
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional, Type

from pydantic import BaseModel, Field

from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.execution_strategy import ExecutionContext, ExecutionResult
from nodes.core.suspend_strategy import SuspendingExecutionStrategy

logger = logging.getLogger(__name__)


# ============================================================================
# Duration helpers
# ============================================================================

# Multiplier from each delay unit to seconds.
DELAY_UNIT_SECONDS = {
    "seconds": 1,
    "minutes": 60,
    "hours": 3600,
    "days": 86400,
    "weeks": 604800,
}

# Delays at or under this run in-process with asyncio.sleep. Longer delays
# suspend the run and resume via a scheduled wake-up (durable across restarts).
IN_PROCESS_DELAY_MAX_SECONDS = 900


def compute_delay_seconds(delay_amount: int, delay_unit: str) -> int:
    """Convert an amount + unit into a total number of seconds."""
    multiplier = DELAY_UNIT_SECONDS.get(delay_unit)
    if multiplier is None:
        raise ValueError(f"[DelayNode] Unknown delay unit: {delay_unit!r}")
    return int(delay_amount) * multiplier


# ============================================================================
# Delay Node Configuration
# ============================================================================

class DelayInnerConfig(BaseModel):
    """Configuration for the delay node."""

    delay_amount: int = Field(
        default=1,
        ge=1,
        title="Delay",
        description="How long to wait, in the chosen unit",
        json_schema_extra={"placeholder": "1"},
    )

    delay_unit: str = Field(
        default="minutes",
        title="Unit",
        description="Unit for the delay duration",
        json_schema_extra={
            "enum": ["seconds", "minutes", "hours", "days", "weeks"],
            "enumNames": ["Seconds", "Minutes", "Hours", "Days", "Weeks"],
            "x-enum-searchable": True,
        },
    )

    message: Optional[str] = Field(
        default=None,
        title="Wait Message (optional)",
        description="Optional message to display while waiting",
        json_schema_extra={
            "placeholder": "Waiting for video generation..."
        }
    )


class DelayNodeConfig(NodeConfig[DelayInnerConfig, None]):
    """Full configuration for delay node (no credentials needed)."""
    pass


# ============================================================================
# Delay Node Implementation
# ============================================================================

class DelayNode(WorkflowNode):
    """
    Delay workflow node for adding timeouts/waits.

    Short delays pause execution in-process. Long delays schedule a wake-up
    and suspend the run — DelayExecutionStrategy handles the suspension.
    """

    edit_examples = [
        "Wait 5 minutes before polling the video generation API",
        "Add a 30-second delay between sending emails",
        "Wait 2 days before sending the onboarding follow-up email",
        "Pause for 1 week before the re-engagement step",
        "Rate limit by waiting between API requests",
        "Change the wait duration from minutes to hours",
    ]

    @classmethod
    def get_config_model(cls) -> Optional[Type]:
        """Get Pydantic config model for delay node."""
        return DelayNodeConfig

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute the delay node.

        Short delays sleep in-process. Long delays schedule a wake-up and
        return a 'waiting' output — DelayExecutionStrategy then suspends the
        run; the wake-up resumes it later.
        """
        logger.info(f"[DelayNode] Executing node {self.node_id}")

        node_config = self.config
        if not node_config or not isinstance(node_config, DelayNodeConfig):
            raise ValueError(f"[DelayNode] Configuration required for node {self.node_id}")

        config = node_config.config
        delay_seconds = compute_delay_seconds(config.delay_amount, config.delay_unit)
        message = config.message or f"Waiting {delay_seconds} seconds..."

        if delay_seconds > IN_PROCESS_DELAY_MAX_SECONDS:
            return await self._schedule_durable_delay(delay_seconds, message)

        return await self._sleep_in_process(delay_seconds, message)

    async def _sleep_in_process(self, delay_seconds: int, message: str) -> Dict[str, Any]:
        """Short delay: wait in-process with asyncio.sleep."""
        start_time = time.time()

        await self.emit({
            'type': 'delay',
            'status': 'waiting',
            'delay_seconds': delay_seconds,
            'message': message,
            'start_time': start_time,
        })

        logger.info(f"[DelayNode] Waiting {delay_seconds} seconds in-process: {message}")
        await asyncio.sleep(delay_seconds)

        elapsed = time.time() - start_time
        output = {
            'type': 'delay',
            'status': 'completed',
            'delay_seconds': delay_seconds,
            'elapsed_seconds': round(elapsed, 2),
            'message': message,
            'start_time': start_time,
            'end_time': time.time(),
        }

        logger.info(f"[DelayNode] Completed after {elapsed:.2f} seconds")
        await self.emit(output)
        return output

    async def _schedule_durable_delay(self, delay_seconds: int, message: str) -> Dict[str, Any]:
        """Long delay: schedule a wake-up and record resume info on the
        execution row. DelayExecutionStrategy suspends the run afterwards.
        """
        if not self.execution_id:
            raise ValueError("[DelayNode] execution_id is required for a long delay")

        from utils.cron_scheduler_client import create_alarm, is_cron_scheduler_enabled
        if not is_cron_scheduler_enabled():
            raise RuntimeError(
                "[DelayNode] long delays require the cron scheduler — "
                "set CRON_SCHEDULER_URL and CRON_SCHEDULER_SECRET"
            )

        from utils.webhook_manager import WebhookManager
        from utils.database_pool import get_native_pool

        # Mint (or reuse) an internal webhook the scheduler can call back to.
        pool = get_native_pool()
        webhook = await WebhookManager.get_or_create_webhook(
            pool, self.user_id, self.workflow_id, self.node_id
        )
        webhook_url = webhook.get("webhook_url")
        if not webhook_url:
            raise RuntimeError("[DelayNode] failed to create the resume webhook")

        wake_at = datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)

        result = await create_alarm(
            user_id=self.user_id,
            workflow_id=self.workflow_id,
            node_id=self.node_id,
            run_at=wake_at.isoformat(),
            webhook_url=webhook_url,
            payload={
                "type": "delay_resume",
                "execution_id": self.execution_id,
                "resume_node_id": self.node_id,
            },
        )
        schedule_id = result.get("id")
        if not schedule_id:
            raise RuntimeError(
                f"[DelayNode] failed to schedule wake-up: {result.get('error', 'unknown error')}"
            )

        # Record resume info on the execution row so the wake-up can resume it
        # and so the schedule can be cancelled if the workflow changes.
        await pool.execute(
            """UPDATE workflow_executions
               SET wake_at = $1, resume_node_id = $2, external_schedule_id = $3
               WHERE id = $4""",
            wake_at, self.node_id, schedule_id, self.execution_id,
        )

        output = {
            'type': 'delay',
            'status': 'waiting',
            'delay_seconds': delay_seconds,
            'wake_at': wake_at.isoformat(),
            'message': message,
        }

        logger.info(
            f"[DelayNode] Scheduled durable delay: node {self.node_id} resumes at {wake_at.isoformat()} "
            f"(schedule {schedule_id})"
        )
        await self.emit(output)
        return output


# ============================================================================
# Execution Strategy
# ============================================================================

class DelayExecutionStrategy(SuspendingExecutionStrategy):
    """
    Execution strategy for delay nodes.

    Short delays run in-process like a normal node — execution continues to
    downstream nodes once the sleep finishes. Long delays use the generic
    suspend flow: the node schedules a wake-up, downstream nodes are skipped,
    and the execution status becomes 'awaiting_delay' until the wake-up fires.
    """

    suspended_status = "awaiting_delay"

    def handles(self, node_type: str) -> bool:
        return node_type == "delay"

    @staticmethod
    def _delay_seconds_for(node: Dict[str, Any]) -> int:
        """Compute the delay duration from a node's stored config.

        The runtime node blob holds config fields flat on ``node["config"]``
        (delay_amount / delay_unit directly). _execute_node only restructures
        it into the {config, credentials} shape when the node is actually
        built — which happens AFTER this strategy's short/long decision.
        """
        config = node.get("config", {}) or {}
        amount = config.get("delay_amount", 1)
        unit = config.get("delay_unit", "minutes")
        try:
            return compute_delay_seconds(int(amount), str(unit))
        except (ValueError, TypeError):
            # A malformed config shouldn't crash orchestration — treat it as a
            # short delay so the node runs in-process and surfaces its own error.
            return 0

    async def execute(self, ctx: ExecutionContext) -> ExecutionResult:
        delay_seconds = self._delay_seconds_for(ctx.node)
        if delay_seconds > IN_PROCESS_DELAY_MAX_SECONDS:
            # Long delay — suspend the run (skip downstream, set awaiting_delay).
            return await super().execute(ctx)
        return await self._execute_in_process(ctx)

    async def _execute_in_process(self, ctx: ExecutionContext) -> ExecutionResult:
        """Run a short delay as a normal node — downstream execution continues."""
        node_id = ctx.node_id
        node = ctx.node
        try:
            async with ctx.semaphore:
                await ctx.emit_state(node_id, "delay", "running", None)

                mocked_output = node.get("config", {}).get("mockedOutput")
                if isinstance(mocked_output, dict):
                    output = mocked_output
                else:
                    output = await ctx.execute_node(node, ctx.node_outputs)

                await ctx.mark_completed(node_id, output)
                await ctx.emit_output(node_id, "delay", output)
                await ctx.emit_state(node_id, "delay", "completed", None)

            return ExecutionResult(output=output, body_nodes_handled=set(), success=True)

        except Exception as e:
            error_msg = f"Delay node {node_id} failed: {str(e)}"
            logger.error(f"[DelayExecutionStrategy] {error_msg}")
            await ctx.mark_failed(node_id, error_msg)
            await ctx.emit_state(node_id, "delay", "error", str(e))
            return ExecutionResult(
                output=None,
                body_nodes_handled=ctx.successors.get(node_id, set()),
                success=False,
                error=error_msg,
            )
        finally:
            ctx.signal_done(node_id)
