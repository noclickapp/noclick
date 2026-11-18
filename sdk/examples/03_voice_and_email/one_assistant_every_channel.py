# ---
# description: One assistant you text on WhatsApp or iMessage, email and call, in one conversation that your code can join too.
# card_title: One assistant you text, email and call
# card_line: Text, email or call the same assistant.
# mark: automation-whatsapp
# cmd: ["python", "03_voice_and_email/one_assistant_every_channel.py"]
# env: ["NOCLICK_API_KEY"]
# deps: []
# ---

# # One assistant you text, email and call
#
# You already text NoClick: its WhatsApp and iMessage numbers answer whoever owns the account.
# This example puts your own agent there instead, with your instructions and your tools, and
# gives it an email address and a phone number of its own. Whichever way you reach it, it's one
# conversation: what you texted this morning is there when you call this afternoon, and your code
# can read it or add to it.
#
# ```bash
# pip install noclick
# export NOCLICK_API_KEY=nk_live_...
# python 03_voice_and_email/one_assistant_every_channel.py
# ```
#
# You're the account's owner here, so everything runs as your account, never inside `as_user`.
# The first run sets it up and prints where to reach it. Later runs set what this file passes
# again. Nothing is created twice.

import sys

import noclick

# ## The assistant
#
# An [agent](/docs/guide/agents) with web search and one person it can reach: you.
# `noclick.Human.owner()` is your account's owner, and in `tools` it lets the agent message you,
# ask you something or hand you the conversation. It reaches you on the app you last texted
# NoClick on, else by email, so a reminder lands where you already are.

CONVERSATION = "owner"  # the one thread every channel shares
INSTRUCTIONS = """You are my personal assistant. Keep replies short: they're read on a phone.
Look things up before you answer anything that changes, like opening hours or prices.
When I ask you to remind me of something, say when you will, then message me at that time."""


def hire() -> noclick.Agent:
    return noclick.Agent.from_name(
        "assistant", create_if_missing=True, instructions=INSTRUCTIONS,
        tools=["search", noclick.Human.owner()], timezone="America/Los_Angeles",
    )


# ## Your texts and calls go to it
#
# [`answer_with`](/docs/guide/humans#answer-the-owner-s-texts-and-calls-with-an-agent) sends what you text
# NoClick's own WhatsApp and iMessage numbers to the assistant, and its reply comes back on the app
# you texted on; call NoClick's number and the assistant answers that too, out loud. Each text, and
# each thing you say on a call, is a turn in its conversation `"owner"`. Run the script with `undo`
# and you go back to NoClick's own assistant.


def route_texts(assistant: noclick.Agent) -> None:
    noclick.Human.owner().answer_with(assistant, conversation=CONVERSATION)


# ## An address of its own
#
# An [inbox](/docs/guide/inboxes) gives it an email address. `senders="owner"` means only mail
# from you wakes it, so nobody else can write their way into your conversation, and
# `conversation="owner"` puts that mail in the same thread as your texts. It answers with its
# reply tool, on the email's own thread.


def give_it_an_address(assistant: noclick.Agent) -> noclick.Inbox:
    return noclick.Inbox.from_name(
        "assistant", create_if_missing=True, agent=assistant, senders="owner", conversation=CONVERSATION,
    )


# ## A number to call
#
# A [phone number](/docs/guide/phone-numbers) is the one part here that costs a monthly fee, so
# it's bought only when you run the script with `phone`. `callers="owner"` lets only you through,
# recognised by the phone you verified with NoClick, and `conversation="owner"` makes the call one
# more turn in the thread: the assistant knows what you texted, and the call's transcript joins it.


def give_it_a_number(assistant: noclick.Agent) -> noclick.PhoneNumber:
    number = noclick.PhoneNumber.from_name(
        "assistant-line", create_if_missing=True, area_code="415", max_monthly_usd=5, max_upfront_usd=5,
    )
    return number.answer_with(assistant, callers="owner", conversation=CONVERSATION)


# ## Your code is in the conversation too
#
# The thread is an ordinary conversation, so your code reaches it by name. Here the script asks
# for a summary of the day, and then prints the last few things said on every channel.


def catch_up(assistant: noclick.Agent) -> None:
    reply = assistant.message("In two lines: what have I asked you to do today?", conversation=CONVERSATION)
    print("\n" + reply.text)
    for said in assistant.history(CONVERSATION)[-6:]:
        print(f"  {said.role}: {(said.text or '')[:80]}")


# ## Undo it
#
# `undo` hands your texts back to NoClick's assistant, releases the number if you bought one, and
# removes the inbox and the agent:
#
# ```bash
# python 03_voice_and_email/one_assistant_every_channel.py undo
# ```


def undo() -> None:
    noclick.Human.owner().answer_with(None)
    try:
        noclick.PhoneNumber.from_name("assistant-line").release()
    except noclick.NotFound:
        pass
    noclick.Inbox.from_name("assistant").delete()
    noclick.Agent.from_name("assistant").delete()
    print("Your texts go to NoClick's assistant again.")


def main() -> None:
    if sys.argv[1:] == ["undo"]:
        undo()
        return
    assistant = hire()
    route_texts(assistant)
    inbox = give_it_an_address(assistant)
    print(f"Text NoClick on WhatsApp or iMessage, or email {inbox.address}.")
    if sys.argv[1:] == ["phone"]:
        number = give_it_a_number(assistant)
        print(f"Or call {number.number}.")
    catch_up(assistant)


if __name__ == "__main__":
    main()
