"""Cron: a schedule, for app schedules and agent triggers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class Cron:
    """A schedule: a five-field cron expression (minute, hour, day of month,
    month, day of week: numbers, ``*``, ranges, steps, lists and month or day
    names) read in a timezone, so ``"0 9 * * 1-5"`` with
    ``tz="America/New_York"`` means 9am New York time on weekdays, daylight saving
    included. When both day fields are restricted a run must match both. An
    agent's schedule wakes the agent with ``message`` as the turn (each run a
    conversation of its own); a wake-up's ``every`` wakes one conversation at
    each time, with its ``note`` (a routine: ``agent.wake``); a channel's posts
    ``message`` in the room; an app's calls one of its paths. ``tz="user"`` reads it in a
    user's agent's (or channel's) user's ``timezone``, following them when they
    move (UTC while they have none; an account agent refuses it, having no user);
    a wake-up reads it in the timezone of the user whose conversation it wakes.

    Every agent turn is told the date and time, so a schedule's ``message`` can say
    "last month" or "this week" and mean it.

    Usage:
        Wake an agent every weekday morning::

            digest = noclick.Agent.from_name(
                "digest", create_if_missing=True, instructions="You summarize the overnight tickets.",
                triggers=[noclick.Cron("0 8 * * 1-5", tz="Europe/London", message="Post the overnight summary")],
            )

        Call an app's path every hour::

            app = noclick.Project.from_name("booking")
            app.schedule(noclick.Cron("0 * * * *"), path="/jobs/reminders")

        Brief each user at 8am where they are::

            with noclick.as_user("user_42"):
                assistant = noclick.Agent.from_name("assistant")
                assistant.add_trigger(noclick.Cron("0 8 * * *", tz="user", message="Brief me on today's calendar"))
    """

    expr: str
    # An IANA timezone, or ``"user"``: the agent's user's ``timezone``, followed when they move.
    tz: str = "UTC"
    # The turn's text when this schedule wakes an agent; apps ignore it.
    message: Optional[str] = None

    def _wire(self) -> Dict[str, Any]:
        body: Dict[str, Any] = {"cron": self.expr, "tz": self.tz}
        if self.message is not None:
            body["message"] = self.message
        return body
