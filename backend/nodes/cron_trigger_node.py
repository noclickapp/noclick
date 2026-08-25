"""
Cron trigger node implementation.

This node acts as an entry point for workflows triggered by a cron schedule.
It uses external relay services to schedule alarms that call the webhook URL.

The node has:
- An intuitive schedule picker (frequency + optional time/day)
- A webhook URL (auto-generated) that gets called when the cron fires
"""

import re
import time
import json
import logging
from typing import Dict, Any, List, Literal, Optional, Union, Type
from pydantic import BaseModel, ConfigDict, Field, model_validator
import uuid as uuid_module

from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.schedule_registration import CronScheduleSpec, CronScheduleTriggerMixin

logger = logging.getLogger(__name__)


# ============================================================================
# Schedule to Cron Conversion
# ============================================================================

ScheduleFrequency = Literal["seconds", "minutes", "hours", "day", "week", "weeks", "month"]


class ScheduleConfig(BaseModel):
    """Schedule configuration from the frontend widget.
    Fields accept Union[int, str] to support drag-and-drop references like
    {{nodeId.values.field}} which get resolved at configuration time."""
    model_config = ConfigDict(extra='forbid')
    frequency: ScheduleFrequency = "hours"
    interval: Optional[Union[int, str]] = Field(None, description="Repeat interval (for seconds/minutes/hours/weeks)")
    hour: Optional[Union[int, str]] = Field(9, description="Hour of day (0-23)")
    minute: Optional[Union[int, str]] = Field(0, description="Minute (0-59)")
    dayOfWeek: Optional[Union[int, str]] = Field(1, description="Day of week (0=Sunday, 6=Saturday)")
    dayOfMonth: Optional[Union[int, str]] = Field(1, description="Day of month (1-31)")


def _to_int(value: Any, default: int) -> int:
    """Safely cast a value to int. Frontend widgets send numeric fields as strings."""
    if value is None:
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def _convert_time_to_utc(
    hour: int, minute: int,
    day_of_week: Optional[int] = None,
    day_of_month: Optional[int] = None,
    timezone: str = "UTC",
) -> Dict[str, int]:
    """Convert a local hour/minute (+ optional day fields) to UTC equivalents.

    Uses the current UTC offset for the timezone. For fixed-offset zones (e.g.
    Asia/Kolkata) this is always correct. For DST zones (e.g. US/Eastern) the
    offset is based on the current date — a known trade-off vs deploying
    timezone support in the external scheduler.
    """
    from zoneinfo import ZoneInfo
    from datetime import datetime

    result: Dict[str, int] = {"hour": hour, "minute": minute}
    if day_of_week is not None:
        result["day_of_week"] = day_of_week
    if day_of_month is not None:
        result["day_of_month"] = day_of_month

    if timezone == "UTC":
        return result

    try:
        tz = ZoneInfo(timezone)
    except KeyError:
        logger.warning(f"[CronTriggerNode] Unknown timezone {timezone}, using UTC")
        return result

    offset = datetime.now(tz).utcoffset()
    if offset is None:
        return result

    offset_minutes = int(offset.total_seconds() / 60)
    local_total = hour * 60 + minute
    utc_total = local_total - offset_minutes

    day_delta = 0
    if utc_total < 0:
        utc_total += 24 * 60
        day_delta = -1
    elif utc_total >= 24 * 60:
        utc_total -= 24 * 60
        day_delta = 1

    result["hour"] = utc_total // 60
    result["minute"] = utc_total % 60

    if day_of_week is not None and day_delta != 0:
        result["day_of_week"] = (day_of_week + day_delta) % 7
    if day_of_month is not None and day_delta != 0:
        result["day_of_month"] = max(1, min(28, day_of_month + day_delta))

    return result


def schedule_to_cron(schedule: Dict[str, Any], timezone: str = "UTC") -> str:
    """
    Convert a schedule config object to a cron expression (in UTC).

    For absolute-time schedules (day, week, month), the hour/minute are
    converted from the given timezone to UTC so the scheduled callback fires at the
    correct wall-clock time.

    Supports:
    - Every minute: "* * * * *"
    - Every X minutes: "*/X * * * *"
    - Every hour: "0 * * * *"
    - Every X hours: "0 */X * * *"
    - Every day at H:M: "M H * * *"
    - Every week on D at H:M: "M H * * D"
    - Every month on D at H:M: "M H D * *"
    """
    freq = schedule.get("frequency", "hour")
    interval = _to_int(schedule.get("interval"), 1)
    hour = _to_int(schedule.get("hour"), 9)
    minute = _to_int(schedule.get("minute"), 0)
    day_of_week = _to_int(schedule.get("dayOfWeek"), 1)
    day_of_month = _to_int(schedule.get("dayOfMonth"), 1)

    if freq == "seconds":
        # Cron doesn't support seconds natively, but the external scheduler does
        # We'll pass this as a special case - the scheduler will handle sub-minute intervals
        interval = max(1, min(59, interval))
        return f"*/{interval}s * * * *"  # Custom format: scheduler interprets 's' suffix

    elif freq == "minute":
        return "* * * * *"

    elif freq == "minutes":
        interval = max(1, min(59, interval))
        return f"*/{interval} * * * *"

    elif freq == "hour":
        return "0 * * * *"

    elif freq == "hours":
        interval = max(1, min(23, interval))
        # For intervals that divide evenly into 24, use standard cron (predictable times)
        # For intervals that don't (e.g., 5, 7, 11, 13, etc.), use custom interval format
        # so users get true "every X hours from now" behavior
        if 24 % interval == 0:
            return f"0 */{interval} * * *"
        else:
            # Custom format: external scheduler interprets /Xh as hour interval
            return f"0 0 * * * /{interval}h"

    elif freq == "day":
        utc = _convert_time_to_utc(hour, minute, timezone=timezone)
        return f"{utc['minute']} {utc['hour']} * * *"

    elif freq == "week":
        utc = _convert_time_to_utc(hour, minute, day_of_week=day_of_week, timezone=timezone)
        return f"{utc['minute']} {utc['hour']} * * {utc['day_of_week']}"

    elif freq == "weeks":
        # Every N weeks on a specific day - custom format for external scheduler
        # Format: "M H * * D /Nw" where /Nw indicates week interval
        interval = max(1, min(52, interval))
        utc = _convert_time_to_utc(hour, minute, day_of_week=day_of_week, timezone=timezone)
        return f"{utc['minute']} {utc['hour']} * * {utc['day_of_week']} /{interval}w"

    elif freq == "month":
        utc = _convert_time_to_utc(hour, minute, day_of_month=day_of_month, timezone=timezone)
        return f"{utc['minute']} {utc['hour']} {utc['day_of_month']} * *"

    # Default to hourly
    return "0 * * * *"


def schedule_to_interval_ms(schedule: Dict[str, Any]) -> Optional[int]:
    """
    Convert a schedule config to interval in milliseconds.
    Only returns a value for interval-based schedules (seconds, minutes, hours).
    Returns None for time-based schedules (day, week, month) since those run at fixed times.
    """
    freq = schedule.get("frequency", "hour")
    interval = _to_int(schedule.get("interval"), 1)

    if freq == "seconds":
        return interval * 1000
    elif freq in ("minute", "minutes"):
        actual_interval = 1 if freq == "minute" else interval
        return actual_interval * 60 * 1000
    elif freq in ("hour", "hours"):
        actual_interval = 1 if freq == "hour" else interval
        return actual_interval * 60 * 60 * 1000

    # Time-based schedules don't have a fixed interval
    return None


# ============================================================================
# Reference Resolution for Schedule Fields
# ============================================================================

_REFERENCE_PATTERN = re.compile(r'^\{\{([^}]+)\}\}$')


async def _get_node_config_from_workflow(workflow_id: uuid_module.UUID, node_id: str, pool) -> Optional[Dict[str, Any]]:
    """Fetch a node's config from the workflow JSON (workflows.workflow column).

    Config form values are stored in the node config at config.values,
    the same Valtio/YJS state that powers the frontend and auto-saves.
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT workflow FROM workflows WHERE id = $1",
            workflow_id
        )
        if not row or not row['workflow']:
            return None

        workflow_data = row['workflow']
        if isinstance(workflow_data, str):
            workflow_data = json.loads(workflow_data)

        nodes = workflow_data.get("nodes", [])
        for node in nodes:
            if node.get("id") == node_id:
                return node.get("config", {})

    return None


async def _resolve_schedule_references(schedule: Dict[str, Any], workflow_id: uuid_module.UUID, pool) -> Dict[str, Any]:
    """Resolve {{nodeId.values.field}} references in schedule fields.

    When a schedule field contains a reference string like {{nodeId.values.day}},
    this looks up the referenced node's config from the workflow data
    and replaces the reference with the resolved value.
    """
    resolved = dict(schedule)
    refs_to_resolve: Dict[str, str] = {}  # field_name -> ref_path

    # Collect all reference fields and their source node IDs
    for key, val in schedule.items():
        if isinstance(val, str):
            m = _REFERENCE_PATTERN.match(val.strip())
            if m:
                refs_to_resolve[key] = m.group(1)  # full ref path

    if not refs_to_resolve:
        return resolved

    # Group by node ID to minimize DB queries
    node_queries: Dict[str, list] = {}  # node_id -> [(field_name, path_parts)]
    for field_name, ref_path in refs_to_resolve.items():
        parts = ref_path.split('.')
        if len(parts) < 2:
            continue
        node_id = parts[0]
        path = parts[1:]  # e.g. ['values', 'schedule_day']
        node_queries.setdefault(node_id, []).append((field_name, path))

    # Fetch config for each referenced node from workflow data
    for node_id, field_paths in node_queries.items():
        config = await _get_node_config_from_workflow(workflow_id, node_id, pool)
        if config is None:
            logger.warning(f"[CronTriggerNode] Referenced node {node_id} not found in workflow")
            continue

        for field_name, path in field_paths:
            # Navigate the path through the node config
            # e.g. path=['values', 'day'] traverses config.values.day
            value = config
            for part in path:
                if isinstance(value, dict) and part in value:
                    value = value[part]
                else:
                    logger.warning(f"[CronTriggerNode] Could not resolve path {'.'.join(path)} in config for node {node_id}")
                    value = None
                    break

            if value is not None:
                # Convert to int if the value is numeric (schedule fields expect numbers)
                try:
                    resolved[field_name] = int(value)
                except (ValueError, TypeError):
                    resolved[field_name] = value
                logger.info(f"[CronTriggerNode] Resolved {field_name}: {schedule[field_name]} -> {resolved[field_name]}")

    return resolved


async def _resolve_whole_schedule_reference(ref_string: str, workflow_id: uuid_module.UUID, pool) -> Optional[Any]:
    """Resolve a whole-schedule reference like {{nodeId.values.schedule_field}}.

    Returns the resolved value (a single schedule dict, a list of schedule dicts,
    or None if resolution fails). The reference targets a node config value
    set by a config form or similar interface node.
    """
    m = _REFERENCE_PATTERN.match(ref_string.strip())
    if not m:
        logger.warning(f"[CronTriggerNode] Invalid whole-schedule reference: {ref_string}")
        return None

    ref_path = m.group(1)
    parts = ref_path.split('.')
    if len(parts) < 2:
        logger.warning(f"[CronTriggerNode] Reference path too short: {ref_path}")
        return None

    node_id = parts[0]
    path = parts[1:]

    config = await _get_node_config_from_workflow(workflow_id, node_id, pool)
    if config is None:
        logger.warning(f"[CronTriggerNode] Referenced node {node_id} not found in workflow")
        return None

    # Navigate the path through the node config
    # e.g. path=['values', 'schedule'] traverses config.values.schedule
    value = config
    for part in path:
        if isinstance(value, dict) and part in value:
            value = value[part]
        else:
            logger.warning(f"[CronTriggerNode] Could not resolve path {'.'.join(path)} in config for node {node_id}")
            return None

    return value


# ============================================================================
# Cron Trigger Node Configuration Models
# ============================================================================

class CronTriggerConfig(BaseModel):
    """Configuration for cron trigger node.
    Supports multiple schedule entries — each becomes a separate Cloudflare cron schedule."""

    schedules: Optional[List[Union[ScheduleConfig, str]]] = Field(
        default=[ScheduleConfig()],
        title="Schedules",
        description="When to run this workflow (supports multiple schedule entries). Entries can be schedule config objects or {{nodeId.values.field}} references.",
        json_schema_extra={"ui:widget": "schedules"}
    )
    timezone: str = Field(
        default="UTC",
        title="Timezone",
        description="Timezone for the cron schedule",
        json_schema_extra={
            "enum": [
                "UTC",
                "US/Eastern", "US/Central", "US/Mountain", "US/Pacific",
                "America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles",
                "America/Sao_Paulo", "America/Toronto", "America/Vancouver",
                "Europe/London", "Europe/Paris", "Europe/Berlin", "Europe/Amsterdam",
                "Europe/Rome", "Europe/Madrid", "Europe/Moscow",
                "Asia/Tokyo", "Asia/Shanghai", "Asia/Hong_Kong", "Asia/Singapore",
                "Asia/Kolkata", "Asia/Dubai", "Asia/Seoul",
                "Australia/Sydney", "Australia/Melbourne",
                "Pacific/Auckland", "Pacific/Honolulu",
            ],
            "x-enum-searchable": True,
        }
    )
    webhook_id: Optional[str] = Field(
        default=None,
        title="Webhook ID",
        description="Auto-generated webhook ID (read-only)",
        json_schema_extra={"ui:hidden": True}
    )
    webhook_url: Optional[str] = Field(
        default=None,
        title="Webhook URL",
        description="The URL that will be called when the cron fires (auto-generated)",
        json_schema_extra={"ui:hidden": True, "ui:loadValue": True}
    )
    schedule_ids: Optional[List[str]] = Field(
        default=None,
        title="Schedule IDs",
        description="IDs of the cron schedules in Cloudflare",
        json_schema_extra={"ui:hidden": True}
    )
    next_run: Optional[str] = Field(
        default=None,
        title="Next Run",
        description="Next scheduled run time (earliest across all schedules)",
        json_schema_extra={"ui:widget": "nextRun"}
    )
    last_run: Optional[str] = Field(
        default=None,
        title="Last Run",
        description="Last execution time",
        json_schema_extra={"ui:widget": "readonly", "ui:hidden": True}
    )
    is_active: Optional[bool] = Field(
        default=True,
        json_schema_extra={"ui:hidden": True}
    )

    @model_validator(mode='after')
    def validate_schedule_entries(self) -> 'CronTriggerConfig':
        """Reject bare strings in schedules — only ScheduleConfig objects or {{ref}} templates allowed."""
        import re
        if self.schedules:
            for i, entry in enumerate(self.schedules):
                if isinstance(entry, str) and not re.match(r'^\{\{.*\}\}$', entry.strip()):
                    raise ValueError(
                        f"schedules[{i}]: '{entry}' is not a valid schedule. "
                        f"Use a ScheduleConfig object with fields: frequency, interval, hour, minute, dayOfWeek, dayOfMonth. "
                        f"Strings are only allowed for template references like {{{{nodeId.values.field}}}}."
                    )
        return self

    @model_validator(mode='before')
    @classmethod
    def migrate_single_schedule(cls, values: Any) -> Any:
        """Backward compat: migrate old schedule/schedule_id to schedules/schedule_ids."""
        if isinstance(values, dict):
            if 'schedule' in values and 'schedules' not in values:
                single = values.pop('schedule')
                values['schedules'] = [single] if single else [ScheduleConfig().model_dump()]
            if 'schedule_id' in values and 'schedule_ids' not in values:
                sid = values.pop('schedule_id')
                values['schedule_ids'] = [sid] if sid else None
            # Remove deprecated interval_ms if present
            values.pop('interval_ms', None)
        return values


class CronTriggerNodeConfig(NodeConfig[CronTriggerConfig, None]):
    """Full configuration for cron trigger node (no credentials needed)"""
    pass


# ============================================================================
# Cron Trigger Node Implementation
# ============================================================================

class CronTriggerNode(CronScheduleTriggerMixin, WorkflowNode):
    """
    Cron trigger node.

    Acts as an entry point for workflows triggered by a cron schedule.
    Uses external relay services for reliable, scalable scheduling.

    When the cron fires:
    1. The external scheduler calls the webhook URL
    2. The webhook triggers workflow execution
    3. This node outputs the trigger metadata to downstream nodes
    """

    edit_examples = [
        "Run this workflow every Monday at 9am EST",
        "Trigger this every 30 minutes throughout the day",
        "Schedule daily execution at 6pm in my timezone",
        "Add a cron schedule to run every week on Friday",
        "Set up multiple schedules with different frequencies",
        "Change the timezone and adjust the run time accordingly",
        "Monitor when the next scheduled run will execute",
    ]

    @classmethod
    def get_config_model(cls) -> Optional[Union[Type, type]]:
        """Get Pydantic config model for cron trigger node"""
        return CronTriggerNodeConfig

    # load_field_value is inherited from CronScheduleTriggerMixin: it mints
    # the webhook row and converges through WebhookManager.reconcile_node.
    # Only the SPEC below is cron-node-specific (multi-schedule + timezone +
    # whole-schedule reference resolution); the reconciler returns ONLY the
    # derived Cloudflare side-effects — never echoing `schedules`/`timezone`
    # back, which would race the user's in-flight widget edits.

    @classmethod
    def _is_schedule_operation(cls, operation: Optional[str]) -> bool:
        return True  # the cron node has no operation — it IS the schedule

    @classmethod
    async def cron_schedule_spec(
        cls,
        config: Dict[str, Any],
        operation: Optional[str],
        *,
        workflow_id: Optional[str] = None,
        pool=None,
    ) -> Optional[CronScheduleSpec]:
        """Resolve the config into an ordered list of cron expressions,
        expanding whole-schedule references. An explicitly EMPTY schedules
        list converges to no schedules (cron disabled); an absent key gets
        the hourly default (backward compat with pre-`schedules` configs)."""
        ctx = config or {}
        schedules_raw: list = []
        if "schedules" in ctx and ctx["schedules"] is not None:
            schedules_raw = ctx["schedules"]
        elif ctx.get("schedule"):
            schedules_raw = [ctx["schedule"]]
        if "schedules" not in ctx and "schedule" not in ctx:
            schedules_raw = [{"frequency": "hours", "interval": 1}]

        # Normalize — may be a bare string (a "{{nodeId.values.field}}"
        # reference) or a single dict when not wrapped in a list.
        if isinstance(schedules_raw, str):
            schedules_raw = [schedules_raw]
        elif isinstance(schedules_raw, dict):
            schedules_raw = [schedules_raw]

        timezone = ctx.get("timezone", "UTC") or "UTC"
        cron_exprs: List[str] = []
        for sched_raw in schedules_raw:
            if isinstance(sched_raw, str):
                resolved_value = await _resolve_whole_schedule_reference(
                    sched_raw, workflow_id, pool
                )
                if resolved_value is None:
                    logger.warning(
                        f"[CronTriggerNode] Could not resolve whole-schedule reference: {sched_raw}"
                    )
                    continue
                entries = resolved_value if isinstance(resolved_value, list) else [resolved_value]
                for entry in entries:
                    if not isinstance(entry, dict):
                        logger.warning(
                            f"[CronTriggerNode] Resolved reference entry is not a dict: {type(entry)}"
                        )
                        continue
                    cron_exprs.append(schedule_to_cron(entry, timezone=timezone))
            else:
                resolved = await _resolve_schedule_references(sched_raw, workflow_id, pool)
                cron_exprs.append(schedule_to_cron(resolved, timezone=timezone))

        return CronScheduleSpec(
            expressions=cron_exprs, timezone=timezone, source="cron_trigger"
        )

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute cron trigger node.

        For trigger nodes, the inputs contain the webhook payload from the cron.
        We pass this through to downstream nodes with cron metadata.

        Args:
            inputs: Payload from the cron webhook call

        Returns:
            Dict containing the cron trigger metadata and payload
        """
        logger.info(f"[CronTriggerNode] Executing node {self.node_id}")

        # Extract webhook/cron metadata if present
        webhook_meta = inputs.get("_webhook", {})
        cron_meta = inputs.get("_cron", inputs)  # Cron payload includes schedule info

        # Build output with the cron trigger info
        output = {
            "type": "cron-trigger",
            "status": "triggered",
            "timestamp": time.time(),
            "schedule_id": cron_meta.get("schedule_id"),
            "workflow_id": cron_meta.get("workflow_id"),
            "triggered_at": cron_meta.get("triggered_at"),
            "webhook_id": webhook_meta.get("id"),
            # The actual payload (without metadata)
            "payload": {k: v for k, v in inputs.items() if k not in ("_webhook", "_cron")},
        }

        # Emit output to frontend
        await self.emit(output)

        logger.info(f"[CronTriggerNode] Cron triggered, passing payload to downstream nodes")
        return output
