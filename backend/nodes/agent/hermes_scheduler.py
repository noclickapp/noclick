"""Hermes's scheduler in a gateway NoClick owns: it never fires, and the tool
that would schedule on it is withheld."""
from __future__ import annotations

from typing import Dict

# NoClick wakes an agent itself (its routines and alarms), and a gateway lives
# only as long as the place it runs, so Hermes's own scheduler never fires in a
# gateway NoClick owns. Hermes has no switch for its ticker, but it takes a
# scheduler by name (``cron.provider``), from a plugin under its home that only
# its scheduler discovery reads: ``CRON_PROVIDER`` fires nothing. Its scheduling
# tool is withheld, since it would accept a job that never runs.
WITHHELD_TOOLSETS = ("cronjob",)
CRON_PROVIDER = "noclick"

_CRON_PROVIDER_SOURCE = '''"""NoClick schedules this agent's wake-ups itself: no Hermes cron job fires here."""
from cron.scheduler_provider import CronScheduler


class NoClickCron(CronScheduler):
    @property
    def name(self):
        return "noclick"

    def start(self, stop_event, **kwargs):
        return None


def register(ctx):
    ctx.register_cron_scheduler(NoClickCron())
'''

CRON_CONFIG = f"cron:\n  provider: {CRON_PROVIDER}\n"


def home_files() -> Dict[str, str]:
    """The files under a Hermes home that ``CRON_CONFIG`` needs, by path relative to it."""
    return {f"plugins/{CRON_PROVIDER}/__init__.py": _CRON_PROVIDER_SOURCE}
