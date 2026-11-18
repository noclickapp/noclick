# ---
# description: An agent that runs your NoClick account for you, buying a phone number once you approve it, and a read-only one that answers questions about a file you send it.
# card_title: An assistant that runs your account
# card_line: Buys numbers, answers about your files.
# mark: bot
# cmd: ["python", "06_multi_agent/ops_assistant.py"]
# env: ["NOCLICK_API_KEY"]
# deps: []
# ---

# # An assistant that runs your NoClick account
#
# Everything your code does on NoClick, an agent can do too. Give it `"noclick"` as a tool and it
# gets your account's API: it can look up what you have, create agents and resources, buy a phone
# number or a domain, and deploy, the way a connected app does on NoClick's MCP server. In this
# example one agent buys your front desk a phone number, and a second, read-only one answers a
# question about a spreadsheet you send it.
#
# Nothing it buys or deletes goes through without you: each purchase waits for your approval on
# NoClick, at its exact price, and the agent carries on once you decide.
#
# ```bash
# pip install noclick
# export NOCLICK_API_KEY=nk_live_...
# python 06_multi_agent/ops_assistant.py
# ```

import tempfile
from pathlib import Path

import noclick

# ## Give an agent NoClick itself
#
# `"noclick"` in `tools` gives the agent NoClick's own tools: `search` and `fetch` for NoClick's
# guides and your account's objects, `api_describe` and `api_call` for any API operation, and
# `quote`, `buy` and `delete`. They act as the key that sends each message, so the agent can never
# do more than that key could. A purchase or a deletion waits for your account's owner, and a
# secret's value never comes from the conversation: the agent asks a person to type it on NoClick.

OPS_INSTRUCTIONS = """You run this company's NoClick account: phone numbers, domains, agents and apps.
Look things up before you change them, and say what something costs before you buy it.
When a purchase waits for approval, say so in one line and stop."""


def define_ops() -> noclick.Agent:
    return noclick.Agent.from_name(
        "ops",
        create_if_missing=True,
        instructions=OPS_INSTRUCTIONS,
        tools=["noclick"],
    )


# ## Watch it work, and approve what it buys
#
# `stream` shows the turn as it happens. Beside the reply's text and its tool calls, NoClick's own
# tools add two events: `approval` when a purchase or a deletion waits for you (with its exact
# `price` and the `url` of the page where you approve it), and `operation` when the agent starts
# something long, like a deploy.
#
# The turn ends while the purchase waits. Once you approve it, NoClick buys exactly what was held
# and the agent takes its next turn in the same conversation with the result, so `watch` follows
# the conversation until its reply arrives.


def buy_a_number(ops: noclick.Agent) -> None:
    waiting = False
    for event in ops.stream("Get our front desk a local phone number in the 415 area code.", conversation="front-desk"):
        if event.type == "text":
            print(event.text, end="", flush=True)
        elif event.type == "approval":
            waiting = True
            print(f"\n\nWaiting for you: {event.approval['summary']}")
            print(f"  approve it here: {event.approval['url']}")
        elif event.type == "operation":
            print(f"\n  [{event.operation['summary']}: {event.operation['status']}]")
    if not waiting:
        return
    for event in ops.watch("front-desk"):
        if event.type == "message" and event.role == "assistant":
            print(f"\n{event.text}")
            break


# ## A read-only agent, and a file
#
# `noclick.Platform.only(...)` narrows what the agent gets. Capability groups (`read`, `build`,
# `deploy`, `spend` and `delete`) bound what kind of call it makes, and API areas (`domains`,
# `phone`, `agents`...) which part of the API it reaches. This analyst only reads, so it's never
# even offered `quote`, `buy` or `delete`.
#
# `files` sends documents, images, audio and video with a message. A path is uploaded first, and the
# turn reads the file as the agent reads any: a spreadsheet's or a PDF's text, a voice note's
# transcript, an image as an image.


def define_analyst() -> noclick.Agent:
    return noclick.Agent.from_name(
        "analyst",
        create_if_missing=True,
        instructions="You explain this company's NoClick usage and spend. Cite the numbers you read.",
        tools=[noclick.Platform.only("read")],
    )


def check_the_budget(analyst: noclick.Agent) -> None:
    budget = Path(tempfile.mkdtemp()) / "budget.csv"
    budget.write_text("month,limit_usd\nOctober,250\nNovember,250\n")
    reply = analyst.message("Here's our budget. Are we on track this month?", files=[budget])
    print(reply.text)
    for message in analyst.history(reply.conversation):
        print(f"  {message.role}: {[file.name for file in message.files]}")


def main() -> None:
    buy_a_number(define_ops())
    check_the_budget(define_analyst())


if __name__ == "__main__":
    main()

# ## Clean up
#
# A phone number bills monthly until you release it, from the console or with
# `noclick.PhoneNumber`. The agents cost nothing between messages:
#
# ```python
# noclick.Agent.from_name("ops").delete()
# noclick.Agent.from_name("analyst").delete()
# ```
