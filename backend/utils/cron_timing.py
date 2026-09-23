"""Shared schedule calculation used by local delivery and alarm validation."""
import re
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

# Scheduler expression formats — the same custom vocabulary the CF worker's
# cron-utils speaks: "*/Ns" seconds (+ optional 5-field constraint tail),
# "… /Nh" hour durations, "base /Nw" week-stepped weeklies, plain 5-field cron.
_SECONDS_FORMAT_RE = re.compile(r'^\*/(\d+)s(?:\s+(.*))?$')
_HOURS_FORMAT_RE = re.compile(r'/(\d+)h$')
_WEEKS_FORMAT_RE = re.compile(r'^(.+)\s/(\d+)w$')


def _expand_fields(expr: str):
    """Expression → (minutes, hours, doms, months, dows) as int sets, None =
    unrestricted. croniter does the parsing; evaluation is ours (below)."""
    from croniter import croniter

    fields = croniter.expand(expr)[0]

    def to_set(field) -> Optional[set]:
        if field == ['*']:
            return None
        return {int(v) for v in field}

    return tuple(to_set(f) for f in fields)


def _fields_match(sets, local_dt: datetime) -> bool:
    """Wall-clock membership, with restricted day-of-month AND day-of-week
    INTERSECTING — our generator's semantics, where vixie cron ORs them
    (unrestricted None passes, so the AND is correct for every combination)."""
    mins, hrs, doms, mons, dows = sets
    if mins is not None and local_dt.minute not in mins:
        return False
    if hrs is not None and local_dt.hour not in hrs:
        return False
    if mons is not None and local_dt.month not in mons:
        return False
    if doms is not None and local_dt.day not in doms:
        return False
    if dows is not None and (local_dt.weekday() + 1) % 7 not in dows:
        return False
    return True


def _next_standard(expr: str, tz_name: str, after_utc: datetime) -> datetime:
    """Next fire of a 5-field expression strictly after ``after_utc``,
    DST-correct by construction: local wall-clock candidates are built
    directly with zoneinfo (fold=0 = first occurrence of a fall-back
    repeated hour; spring-forward gap times round-trip-detected and
    skipped) instead of stepping croniter, whose iteration lands fires
    ±1h around DST transitions."""
    sets = _expand_fields(expr)
    mins, hrs, doms, mons, dows = sets
    minutes = sorted(mins) if mins is not None else range(60)
    hours = sorted(hrs) if hrs is not None else range(24)
    tz = ZoneInfo(tz_name or "UTC")
    utc = timezone.utc
    start_date = after_utc.astimezone(tz).date()
    for offset in range(4000):  # ~11-year scan horizon
        d = start_date + timedelta(days=offset)
        if mons is not None and d.month not in mons:
            continue
        if doms is not None and d.day not in doms:
            continue
        if dows is not None and (d.weekday() + 1) % 7 not in dows:
            continue
        for h in hours:
            for m in minutes:
                naive = datetime(d.year, d.month, d.day, h, m)
                candidate = naive.replace(tzinfo=tz).astimezone(utc)
                if candidate.astimezone(tz).replace(tzinfo=None) != naive:
                    continue  # nonexistent wall-clock time (spring-forward gap)
                if candidate > after_utc:
                    return candidate
    raise ValueError(f"No upcoming run for {expr!r} within the scan horizon")


def _compute_next_run(
    cron_expression: str, tz_name: str, last_run: Optional[datetime] = None,
    *, after: Optional[datetime] = None,
) -> datetime:
    """Next fire (UTC) for any scheduler expression, worker-parity semantics."""
    expr = cron_expression.strip()
    now_utc = after or datetime.now(timezone.utc)

    m = _SECONDS_FORMAT_RE.match(expr)
    if m:
        candidate = now_utc + timedelta(seconds=max(1, int(m.group(1))))
        tail = (m.group(2) or "").split()
        if len(tail) == 5:  # constrained: gate the candidate's minute
            tail_expr = " ".join(tail)
            local = candidate.astimezone(ZoneInfo(tz_name or "UTC"))
            if not _fields_match(_expand_fields(tail_expr), local):
                return _next_standard(tail_expr, tz_name, candidate)
        return candidate

    wm = _WEEKS_FORMAT_RE.match(expr)
    if wm:
        base_next = _next_standard(wm.group(1).strip(), tz_name, now_utc)
        interval = max(1, int(wm.group(2)))
        if last_run is not None and interval > 1:
            weeks_since = int((base_next - last_run).total_seconds() // (7 * 86400))
            skip = interval - (weeks_since % interval)
            if 0 < skip < interval:
                return base_next + timedelta(weeks=skip)
        return base_next

    hm = _HOURS_FORMAT_RE.search(expr)
    if hm:  # "/Nh" duration format: true every-N-hours-from-now
        return now_utc + timedelta(hours=max(1, int(hm.group(1))))

    return _next_standard(expr, tz_name, now_utc)


def _parse_run_at(run_at: str) -> datetime:
    dt = datetime.fromisoformat(run_at.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
