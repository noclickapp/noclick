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

_REFERENCE_PATTERN = re.compile(r'^\{\{([^}]+)\}\}$')
_TIME_OF_DAY_RE = re.compile(r'^(\d{1,2}):(\d{2})$')


def _to_int(value: Any, default: int) -> int:
    """Safely cast a value to int. Frontend widgets send numeric fields as strings."""
    if value is None:
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def _is_reference(value: Any) -> bool:
    return isinstance(value, str) and bool(_REFERENCE_PATTERN.match(value.strip()))

def _parse_hhmm(value: Any, field_name: str) -> tuple:
    m = _TIME_OF_DAY_RE.match(str(value).strip())
    if m:
        hour, minute = int(m.group(1)), int(m.group(2))
        if hour <= 23 and minute <= 59:
            return hour, minute
    raise ValueError(f'{field_name} must be a 24-hour "HH:MM" time, got {value!r}')


# Which frequencies each narrowing constraint applies to. Mirrored by the
# schedule widget's clause menu (ScheduleWidget CLAUSE_APPLICABILITY) — the UI
# only offers what registration can honor, and vice versa.
_WINDOW_FREQUENCIES = ("seconds", "minute", "minutes", "hour", "hours")
_DOW_FREQUENCIES = _WINDOW_FREQUENCIES + ("day",)
_MONTHDAY_FREQUENCIES = _DOW_FREQUENCIES
# `weeks` is excluded: its /Nw week-stepping counts elapsed weeks since the
# last run, which turns month-gapped years into arbitrary phases.
_MONTH_FREQUENCIES = _DOW_FREQUENCIES + ("week", "month")


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
    daysOfWeek: Optional[List[Union[int, str]]] = Field(
        None,
        description="Days of week to run on (0=Sunday … 6=Saturday); empty = every day. "
                    "Supported for seconds/minutes/hours intervals and daily schedules.",
    )
    windowStart: Optional[str] = Field(
        None,
        description='Part-of-day start as 24-hour "HH:MM" in the schedule timezone '
                    '(e.g. "09:00"). Set together with windowEnd; interval frequencies only.',
    )
    windowEnd: Optional[str] = Field(
        None,
        description='Part-of-day end as 24-hour "HH:MM", inclusive — a run landing '
                    'exactly on it fires (e.g. "18:00" runs the 6:00 PM tick).',
    )
    monthDayStart: Optional[Union[int, str]] = Field(
        None,
        description="Part-of-month start day (1-31), inclusive. Set together with "
                    "monthDayEnd; a start after the end wraps around month end "
                    "(25→5 = the 25th through the 5th).",
    )
    monthDayEnd: Optional[Union[int, str]] = Field(
        None,
        description="Part-of-month end day (1-31), inclusive.",
    )
    monthStart: Optional[Union[int, str]] = Field(
        None,
        description="Part-of-year start month (1=January … 12=December), inclusive. "
                    "Set together with monthEnd; a start after the end wraps around "
                    "the new year (11→2 = November through February).",
    )
    monthEnd: Optional[Union[int, str]] = Field(
        None,
        description="Part-of-year end month (1-12), inclusive.",
    )

    @model_validator(mode="after")
    def _validate_constraints(self) -> 'ScheduleConfig':
        """Constraint coherence for literal values; {{ref}} values resolve at
        registration and are judged there (schedule_to_cron_expressions)."""
        for name in ("windowStart", "windowEnd", "monthDayStart", "monthDayEnd",
                     "monthStart", "monthEnd"):
            v = getattr(self, name)
            if isinstance(v, str) and not v.strip():
                setattr(self, name, None)  # ""/whitespace = unset marker

        def pair(a_name: str, b_name: str) -> tuple:
            a, b = getattr(self, a_name), getattr(self, b_name)
            if _is_reference(a) or _is_reference(b):
                return None, None  # judged at registration once resolved
            if (a is None) != (b is None):
                raise ValueError(f"{a_name} and {b_name} must be set together")
            return a, b

        ws, we = pair("windowStart", "windowEnd")
        if ws is not None:
            if self.frequency not in _WINDOW_FREQUENCIES:
                raise ValueError("A part-of-day window is only supported for interval (seconds/minutes/hours) frequencies")
            s_h, s_m = _parse_hhmm(ws, "windowStart")
            e_h, e_m = _parse_hhmm(we, "windowEnd")
            if s_h == e_h and s_m > e_m:
                raise ValueError("windowEnd must not be earlier than windowStart within the same hour")

        if self.daysOfWeek:
            if self.frequency not in _DOW_FREQUENCIES:
                raise ValueError("daysOfWeek is only supported for interval and daily schedules")
            for d in self.daysOfWeek:
                if not _is_reference(d) and not (0 <= _to_int(d, -1) <= 6):
                    raise ValueError("daysOfWeek entries must be 0 (Sunday) through 6 (Saturday)")

        md_s, md_e = pair("monthDayStart", "monthDayEnd")
        if md_s is not None:
            if self.frequency not in _MONTHDAY_FREQUENCIES:
                raise ValueError("A part-of-month range is only supported for interval and daily schedules")
            for name, v in (("monthDayStart", md_s), ("monthDayEnd", md_e)):
                if not (1 <= _to_int(v, -1) <= 31):
                    raise ValueError(f"{name} must be a day of month (1-31)")

        mo_s, mo_e = pair("monthStart", "monthEnd")
        if mo_s is not None:
            if self.frequency not in _MONTH_FREQUENCIES:
                raise ValueError(f"A part-of-year range is not supported for '{self.frequency}' schedules")
            for name, v in (("monthStart", mo_s), ("monthEnd", mo_e)):
                if not (1 <= _to_int(v, -1) <= 12):
                    raise ValueError(f"{name} must be a month (1=January … 12=December)")
        return self


def _merge_ranges(values: List[int]) -> str:
    """Cron field from an ordered value list, collapsing consecutive runs,
    e.g. [1,2,3,4,5] -> "1-5", [22,23,0,1] -> "22-23,0-1"."""
    ranges: List[List[int]] = []
    for v in values:
        if ranges and ranges[-1][1] == v - 1:
            ranges[-1][1] = v
        else:
            ranges.append([v, v])
    return ",".join(f"{a}-{b}" if a != b else str(a) for a, b in ranges)


def _dow_field(days: List[Any]) -> str:
    """Cron day-of-week field from a daysOfWeek list (0=Sunday … 6=Saturday)."""
    values = sorted({_to_int(d, -1) for d in days})
    if any(v < 0 or v > 6 for v in values):
        raise ValueError(f"daysOfWeek entries must be 0 (Sunday) through 6 (Saturday), got {days!r}")
    if len(values) == 7:
        return "*"
    return _merge_ranges(values)


def _hour_ranges(start: int, count: int) -> str:
    """Cron hour field covering ``count`` consecutive hours from ``start``
    (mod 24), e.g. (22, 4) -> "22-23,0-1"."""
    return _merge_ranges([(start + i) % 24 for i in range(count)])


def _minute_field(lo: int, hi: int, n: int) -> str:
    if lo == hi:
        return str(lo)
    if lo == 0 and hi == 59:
        return "*" if n == 1 else f"*/{n}"
    return f"{lo}-{hi}/{n}" if n > 1 else f"{lo}-{hi}"


def _wrapping_range_field(start: int, end: int, lo: int, hi: int) -> str:
    """Cron field for an inclusive start→end range over the domain [lo, hi],
    wrapping past the domain end (25→5 over days = "25-31,1-5"). The full
    domain collapses to "*"."""
    if start <= end:
        values = list(range(start, end + 1))
    else:
        values = list(range(start, hi + 1)) + list(range(lo, end + 1))
    if len(values) >= hi - lo + 1:
        return "*"
    return _merge_ranges(values)


def _windowed_minute_expressions(n: int, s_h: int, s_m: int, e_h: int, e_m: int, dom: str, mon: str, dow: str) -> List[str]:
    """Expressions for "every n minutes between start and end (inclusive)".

    Cron minute patterns repeat hourly, so the window is expressed per hour:
    the first hour fires from the start minute, later hours continue the phase
    (exact whenever n divides 60), and the final hour is capped at the end
    minute. Windows wrapping midnight use split hour ranges; the day filters
    apply to the calendar day of each fire (standard cron semantics).
    """
    span = (e_h - s_h) % 24
    phase = s_m % n
    tail = f"{dom} {mon} {dow}"
    if span == 0:  # window within a single hour (s_m <= e_m validated upstream)
        return [f"{_minute_field(s_m, e_m, n)} {s_h} {tail}"]
    exprs: List[str] = []
    if phase == s_m:
        exprs.append(f"{_minute_field(s_m, 59, n)} {_hour_ranges(s_h, span)} {tail}")
    else:
        exprs.append(f"{_minute_field(s_m, 59, n)} {s_h} {tail}")
        if span > 1:
            exprs.append(f"{_minute_field(phase, 59, n)} {_hour_ranges((s_h + 1) % 24, span - 1)} {tail}")
    if e_m >= phase:
        exprs.append(f"{_minute_field(phase, e_m, n)} {e_h} {tail}")
    return exprs


def _windowed_hour_expression(n: int, s_h: int, s_m: int, e_h: int, e_m: int, dom: str, mon: str, dow: str) -> str:
    """"Every n hours between start and end": hours step from the window start
    (anchored there, not at midnight), each firing at the start minute."""
    span = (e_h - s_h) % 24
    hours: List[int] = []
    for k in range(span // n + 1):
        h = (s_h + k * n) % 24
        if h == e_h and s_m > e_m:
            continue  # the final-hour fire would land past the window's end minute
        hours.append(h)
    if not hours:
        raise ValueError("The time window is narrower than the hour interval")
    return f"{s_m} {','.join(str(h) for h in sorted(set(hours)))} {dom} {mon} {dow}"


def schedule_to_cron_expressions(schedule: Dict[str, Any]) -> List[str]:
    """
    Convert a schedule config object into cron expressions written in the
    schedule's own timezone. The registration carries that timezone to the
    scheduler, so wall-clock schedules stay correct across DST without offset
    pre-conversion here.

    Interval schedules can be NARROWED by stacked, unit-adaptive from→to
    constraints (all bounds inclusive): a part-of-day window
    (windowStart/windowEnd "HH:MM"), days of the week (daysOfWeek), a
    part-of-month range (monthDayStart/monthDayEnd), and a part-of-year range
    (monthStart/monthEnd) — day filters also apply to daily schedules, the
    year range to weekly/monthly ones (see the _*_FREQUENCIES maps). These
    compile to 1–3 standard cron expressions registered as separate slots.
    Raises ValueError for combinations that cannot run — never silently drops
    a configured constraint.

    Two semantics are deliberately supported by both remote and local
    schedulers beyond stock cron:
    - day-of-month AND day-of-week: when both fields are restricted the run
      must match BOTH (vixie cron ORs them, which would break "Mon–Fri, the
      1st–15th").
    - constrained seconds: "*/Ns M H DOM MON DOW" fires every N seconds while
      the current minute matches the 5-field tail, else sleeps to the tail's
      next match (legacy unconstrained form stays "*/Ns * * * *").

    Base forms:
    - Every minute: "* * * * *"
    - Every X minutes: "*/X * * * *"
    - Every hour: "0 * * * *"
    - Every X hours: "0 */X * * *" (or "0 0 * * * /Xh" when X doesn't divide 24)
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

    days = [d for d in (schedule.get("daysOfWeek") or []) if d not in (None, "")]
    window_start = schedule.get("windowStart") or None
    window_end = schedule.get("windowEnd") or None

    def range_pair(start_key: str, end_key: str, lo: int, hi: int, what: str) -> Optional[tuple]:
        start, end = schedule.get(start_key), schedule.get(end_key)
        start = None if start in (None, "") else start
        end = None if end in (None, "") else end
        if (start is None) != (end is None):
            raise ValueError(f"{start_key} and {end_key} must be set together")
        if start is None:
            return None
        s, e = _to_int(start, -1), _to_int(end, -1)
        if not (lo <= s <= hi and lo <= e <= hi):
            raise ValueError(f"{start_key}/{end_key} must be {what} ({lo}-{hi})")
        return s, e

    if bool(window_start) != bool(window_end):
        raise ValueError("windowStart and windowEnd must be set together")
    has_window = window_start is not None
    month_day = range_pair("monthDayStart", "monthDayEnd", 1, 31, "days of month")
    months = range_pair("monthStart", "monthEnd", 1, 12, "months")

    if has_window and freq not in _WINDOW_FREQUENCIES:
        raise ValueError(f"A part-of-day window is not supported for '{freq}' schedules")
    if days and freq not in _DOW_FREQUENCIES:
        raise ValueError(f"daysOfWeek is not supported for '{freq}' schedules")
    if month_day and freq not in _MONTHDAY_FREQUENCIES:
        raise ValueError(f"A part-of-month range is not supported for '{freq}' schedules")
    if months and freq not in _MONTH_FREQUENCIES:
        raise ValueError(f"A part-of-year range is not supported for '{freq}' schedules")

    dow = _dow_field(days) if days else "*"
    dom = _wrapping_range_field(month_day[0], month_day[1], 1, 31) if month_day else "*"
    mon = _wrapping_range_field(months[0], months[1], 1, 12) if months else "*"
    constrained = has_window or dow != "*" or dom != "*" or mon != "*"

    def parse_window() -> tuple:
        s_h, s_m = _parse_hhmm(window_start, "windowStart")
        e_h, e_m = _parse_hhmm(window_end, "windowEnd")
        if s_h == e_h and s_m > e_m:
            raise ValueError("windowEnd must not be earlier than windowStart within the same hour")
        return s_h, s_m, e_h, e_m

    if freq == "seconds":
        # Cron doesn't support seconds natively, but our schedulers do via the
        # "s" token. Constraints ride a full 5-field tail the scheduler gates
        # each candidate fire against.
        n = max(1, min(59, interval))
        if not constrained:
            return [f"*/{n}s * * * *"]  # legacy unconstrained form, byte-stable
        if has_window:
            # Same per-hour window split as minutes, at full minute coverage.
            tails = _windowed_minute_expressions(1, *parse_window(), dom, mon, dow)
        else:
            tails = [f"* * {dom} {mon} {dow}"]
        return [f"*/{n}s {tail}" for tail in tails]

    if freq in ("minute", "minutes"):
        n = 1 if freq == "minute" else max(1, min(59, interval))
        if has_window:
            return _windowed_minute_expressions(n, *parse_window(), dom, mon, dow)
        base = "*" if freq == "minute" else f"*/{n}"
        return [f"{base} * {dom} {mon} {dow}"]

    if freq in ("hour", "hours"):
        n = 1 if freq == "hour" else max(1, min(23, interval))
        if has_window:
            return [_windowed_hour_expression(n, *parse_window(), dom, mon, dow)]
        if freq == "hour":
            return [f"0 * {dom} {mon} {dow}"]
        if 24 % n == 0:
            return [f"0 */{n} {dom} {mon} {dow}"]
        if not constrained:
            # True "every X hours from now" via the scheduler's custom /Xh
            # duration format for intervals that don't divide 24.
            return [f"0 0 * * * /{n}h"]
        # Constraints need real cron fields, so anchor at midnight.
        return [f"0 {','.join(str(h) for h in range(0, 24, n))} {dom} {mon} {dow}"]

    if freq == "day":
        return [f"{minute} {hour} {dom} {mon} {dow}"]

    if freq == "week":
        return [f"{minute} {hour} * {mon} {day_of_week}"]

    if freq == "weeks":
        # Every N weeks on a specific day using the scheduler's custom format.
        # Format: "M H * * D /Nw" where /Nw indicates week interval
        interval = max(1, min(52, interval))
        return [f"{minute} {hour} * * {day_of_week} /{interval}w"]

    if freq == "month":
        return [f"{minute} {hour} {day_of_month} {mon} *"]

    # Default to hourly
    return ["0 * * * *"]


def schedule_to_cron(schedule: Dict[str, Any]) -> str:
    """Single-expression wrapper for the bespoke pre-family poller paths.
    Family registration goes through schedule_to_cron_expressions — a windowed
    schedule compiles to multiple expressions and would be truncated here."""
    return schedule_to_cron_expressions(schedule)[0]


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
        "Run every 30 minutes between 9:00 AM and 6:00 PM New York time, Monday to Friday",
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
        try:
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
                        cron_exprs.extend(schedule_to_cron_expressions(entry))
                else:
                    resolved = await _resolve_schedule_references(sched_raw, workflow_id, pool)
                    cron_exprs.extend(schedule_to_cron_expressions(resolved))
        except ValueError as e:
            # An unrunnable entry (bad window, bad days) disables the whole
            # node's registration with a visible reason — never a partial
            # registration that silently drops the misconfigured entry.
            return CronScheduleSpec(
                expressions=[], timezone=timezone, source="cron_trigger",
                config_error=str(e),
            )

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
