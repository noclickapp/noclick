"""Coordinator alarm validation; reuse the agent Alarm node's countdown parser."""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from utils.cron_scheduler_client import parse_countdown_to_timestamp

MAX_PENDING = 10
MAX_DAILY = 24
MIN_GAP_SECONDS = 300
MIN_REPEAT_SECONDS = 900


def next_cron(expression, zone, now=None):
    if not isinstance(expression, str) or len(expression) > 100 or len(expression.split()) != 5:
        raise ValueError("Use a standard five-field cron expression.")
    ZoneInfo(zone)
    from utils.cron_timing import _compute_next_run
    return _compute_next_run(expression, zone, after=now)



def alarm_time(alarm_type, delay_or_time, timezone_name="UTC"):
    now = datetime.now(timezone.utc)
    if alarm_type == "countdown":
        due = datetime.fromisoformat(parse_countdown_to_timestamp(delay_or_time))
    elif alarm_type == "datetime":
        due = datetime.fromisoformat(delay_or_time.replace("Z", "+00:00"))
        if due.tzinfo is None:
            raise ValueError("Include a timezone offset in the alarm timestamp.")
    elif alarm_type == "cron":
        due = next_cron(delay_or_time, timezone_name, now)
        # Reject obvious high-frequency schedules up front. The durable
        # admission limiter also enforces spacing across *all* alarm series.
        previous = due
        for _ in range(32):
            following = next_cron(delay_or_time, timezone_name, previous)
            if (following - previous).total_seconds() < MIN_REPEAT_SECONDS:
                raise ValueError("Recurring coordinator alarms must be at least 15 minutes apart.")
            previous = following
    else:
        raise ValueError("alarm_type must be countdown, datetime or cron.")
    minimum = now if alarm_type == "cron" else now + timedelta(seconds=60)
    if due <= minimum or due > now + timedelta(days=366):
        raise ValueError("Schedule alarms between one minute and one year from now.")
    return due.astimezone(timezone.utc)
