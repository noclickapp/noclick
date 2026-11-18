# ---
# description: A weekday digest posted to Slack from one long conversation, so each morning builds on the last, through the Slack account you already connected in the NoClick app.
# card_title: A digest that remembers yesterday
# card_line: Posts to Slack, picks up from yesterday.
# mark: automation-slack
# cmd: ["python", "08_automations/daily_digest_routine.py"]
# env: ["NOCLICK_API_KEY", "SLACK_CREDENTIAL_ID"]
# deps: []
# ---

# # A daily digest that remembers yesterday
#
# A schedule trigger starts a fresh conversation every run, which suits a job that stands alone. A
# digest doesn't: "what changed since yesterday" needs yesterday. This example sets a **routine**, a
# wake-up that comes back on a schedule into the same conversation, so each morning's turn reads
# what the last one posted. Months of mornings don't overflow the agent: once the conversation grows
# long, its older part folds into a checkpoint in the agent's memory, which you can read and correct.
#
# The agent posts through the Slack workspace you connected in the NoClick app, named by its id, so
# there's nothing to connect from code.
#
# ```bash
# pip install noclick
# export NOCLICK_API_KEY=nk_live_...
# export SLACK_CREDENTIAL_ID=9b2a1c5e-...   # from Connection.list(origin="app"), after "credential:"
# python 08_automations/daily_digest_routine.py            # set it up
# python 08_automations/daily_digest_routine.py --memory   # what it carries forward
# ```

import os
import sys

import noclick

CONVERSATION = "daily-digest"
SCHEDULE = noclick.Cron("0 9 * * 1-5", tz="America/New_York")

# ## The account from the app
#
# An account connected in the NoClick app is a connection whose id is `credential:<id>`. An account
# agent takes it in `tools` like any connection: here just the two Slack operations the digest
# needs, so the agent can't do anything else in your workspace.


def slack() -> noclick.Connection:
    return noclick.Connection.from_id(f"credential:{os.environ['SLACK_CREDENTIAL_ID']}")


def digest_agent() -> noclick.Agent:
    return noclick.Agent.from_name(
        "digest",
        create_if_missing=True,
        instructions=(
            "Each weekday morning you post a short digest of yesterday's news about our market to #general. "
            "Lead with what changed since your last digest; never repeat a story you already posted."
        ),
        tools=["search", slack().only("list_channels", "send_message_to_channel")],
    )


# ## A routine in one conversation
#
# `wake(every=...)` sets the routine: at each time of the schedule, the `daily-digest` conversation
# takes a turn whose message is the note. It stays `pending` between mornings, and a morning it
# missed (say, while a turn ran long) folds into the next one instead of posting twice. Run this
# again with a new schedule and the routine moves; it never doubles, since it's found and updated.


def routine(agent: noclick.Agent) -> noclick.Wakeup:
    for wakeup in agent.wakeups(CONVERSATION, status="pending"):
        if wakeup.every is not None:
            return wakeup if wakeup.every == SCHEDULE else wakeup.update(every=SCHEDULE)
    return agent.wake(CONVERSATION, every=SCHEDULE, note="Post today's digest to #general.")


# ## What it carries forward
#
# The conversation's checkpoint is an entry of the agent's memory, marked with the conversation it
# belongs to. Read it to see what the agent remembers of earlier mornings; edit it, and the next
# turn reads your words.


def carried_forward(agent: noclick.Agent) -> str:
    for entry in agent.memory.list():
        if entry.conversation == CONVERSATION:
            return agent.memory.read(entry.name).content or ""
    return "Nothing yet: the conversation is still short enough to read whole."


def main() -> None:
    agent = digest_agent()
    if "--memory" in sys.argv:
        print(carried_forward(agent))
        return
    wakeup = routine(agent)
    print(f"{agent.name} posts at {wakeup.every.expr} ({wakeup.every.tz}); next: {wakeup.at}")


if __name__ == "__main__":
    main()

# ## Clean up
#
# Each morning is a billed turn on NoClick's default model. To stop it, cancel the routine
# (`wakeup.cancel()`), or delete the agent, which cancels its wake-ups too:
# `noclick.Agent.from_name("digest").delete()`.
