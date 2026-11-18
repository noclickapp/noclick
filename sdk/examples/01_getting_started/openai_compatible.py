# ---
# description: Point the official OpenAI SDK at NoClick for chat, streaming and embeddings on your NoClick account, then talk to your hosted agents as models.
# card_title: Use NoClick from the OpenAI SDK
# card_line: Your OpenAI client, pointed at NoClick.
# mark: plug
# cmd: ["python", "01_getting_started/openai_compatible.py"]
# env: ["NOCLICK_API_KEY"]
# deps: ["openai"]
# ---

# # Use NoClick from the OpenAI SDK
#
# NoClick serves an OpenAI-compatible endpoint. Point the official `openai` package, or anything
# built on it, at `noclick.AI.base_url` with your NoClick key, and you get hundreds of models on
# your NoClick account with no key from each provider. Your hosted agents are on the same
# endpoint as models named `agent:<name>`, so any OpenAI client, and any chat UI that speaks the
# OpenAI API, can talk to them.
#
# This example makes a chat completion, streams one, ranks a help center with embeddings, then
# holds a two-turn conversation with an agent through the same client.
#
# ```bash
# pip install noclick openai
# export NOCLICK_API_KEY=nk_live_...
# python 01_getting_started/openai_compatible.py
# ```

import math
import os

from openai import OpenAI

import noclick

# ## Point the client at NoClick
#
# `noclick.AI.base_url` is `https://api.noclick.com/v1/ai` on the hosted API. The key is your
# NoClick key; the model ids are OpenRouter's with an `openrouter/` prefix, the same ids a
# NoClick agent takes. Every call is charged to your account at the model's price and shows as AI
# on the [Usage page](/dashboard/developers/usage).

gpt = OpenAI(base_url=noclick.AI.base_url, api_key=os.environ["NOCLICK_API_KEY"])

CHAT_MODEL = "openrouter/anthropic/claude-sonnet-4.6"
EMBEDDING_MODEL = "openrouter/openai/text-embedding-3-small"

TICKET = """Hi, I ordered the walnut desk (order 88213) on the 3rd. The tracking page has said
"label created" for nine days and nobody answers the phone. I need it before my move on the 20th,
otherwise please just refund me."""


# ## A chat completion
#
# The request and the response are OpenAI's. `usage` counts the tokens the call was charged for.


def summarize_ticket() -> None:
    completion = gpt.chat.completions.create(
        model=CHAT_MODEL,
        messages=[
            {"role": "system", "content": "Summarize support tickets in one line for the queue view."},
            {"role": "user", "content": TICKET},
        ],
        max_tokens=100,
    )
    print(completion.choices[0].message.content)
    print(f"{completion.usage.total_tokens} tokens")


# ## Stream it
#
# `stream=True` gives OpenAI's server-sent events: each chunk carries the next piece of the text.


def draft_reply() -> None:
    stream = gpt.chat.completions.create(
        model=CHAT_MODEL,
        messages=[
            {"role": "system", "content": "You write short, warm replies to support tickets. No promises you can't keep."},
            {"role": "user", "content": TICKET},
        ],
        stream=True,
    )
    for chunk in stream:
        if chunk.choices and chunk.choices[0].delta.content:
            print(chunk.choices[0].delta.content, end="", flush=True)
    print()


# ## Embeddings
#
# One vector per text, in the order you sent them. Texts that mean the same thing get vectors that
# point the same way, so ranking by cosine similarity finds the help article a customer needs even
# when they share no words with it. For more than a few hundred articles, keep the vectors in a
# Postgres [database](/docs/guide/databases#search-by-meaning) and let it rank them.

HELP_CENTER = [
    "Orders ship within 2 business days. Tracking updates once the carrier scans the parcel.",
    "You can return any item within 30 days for a full refund, including shipping.",
    "Assembly instructions for every desk are on the product page under Downloads.",
    "Our phone line is open 9am to 5pm, Monday to Friday. Chat is open every day.",
]


def cosine(a: list, b: list) -> float:
    return sum(x * y for x, y in zip(a, b)) / (math.hypot(*a) * math.hypot(*b))


def rank_help_articles() -> None:
    question = "my parcel hasn't moved in over a week"
    response = gpt.embeddings.create(model=EMBEDDING_MODEL, input=[question, *HELP_CENTER])
    [asked, *articles] = [row.embedding for row in response.data]
    ranked = sorted(zip(HELP_CENTER, articles), key=lambda pair: cosine(asked, pair[1]), reverse=True)
    for text, vector in ranked[:2]:
        print(f"{cosine(asked, vector):.2f}  {text}")


# ## Your agents are models too
#
# A hosted [agent](/docs/guide/agents) is addressable as the model `agent:<name>`, on any
# harness, and `models.list()` lists your agents beside the models (with `owned_by`
# `"noclick-agent"`), which is how a chat UI finds them. `hydrate()` creates the agent now, since
# the OpenAI client only knows it by name.
#
# The agent runs its own loop: it searches, reads and calls its tools on NoClick's side, and you get
# its reply as the assistant message. Its tool calls are its own, never `tool_calls` for your client
# to run, so a request that sends `tools` to an agent is refused.


def trip_planner() -> noclick.Agent:
    return noclick.Agent.from_name(
        "trip-planner",
        create_if_missing=True,
        instructions="You plan days out. Search for what's on before you suggest it, and say where you found it.",
        tools=["exa.search"],
    ).hydrate()


def list_agent_models() -> None:
    print([model.id for model in gpt.models.list() if model.owned_by == "noclick-agent"])


# ## A conversation that continues
#
# The agent keeps each conversation on NoClick's side, including the tool calls your client never
# saw. The first request starts one and names it in the response's `metadata`. Send it back as
# `metadata={"conversation": ...}` to continue: you can keep sending the whole message list, as
# any OpenAI app does, and only the messages after the last assistant message reach the agent as
# the new turn.
#
# A request with no conversation starts a new one, with the whole message list as its first turn, so
# the agent still sees everything said; keep the conversation the first response names to stay in it.


def plan_a_saturday(planner: noclick.Agent) -> None:
    model = f"agent:{planner.name}"
    messages = [{"role": "user", "content": "I'm in Lisbon next Saturday with nothing planned. What's on?"}]
    first = gpt.chat.completions.create(model=model, messages=messages)
    print(first.choices[0].message.content)
    conversation = first.metadata["conversation"]

    messages += [
        {"role": "assistant", "content": first.choices[0].message.content},
        {"role": "user", "content": "Which of those still works if it rains?"},
    ]
    second = gpt.chat.completions.create(model=model, messages=messages, metadata={"conversation": conversation})
    print(second.choices[0].message.content)
    print(f"Both turns are one thread in the console: {planner.console_url}")


# ## Or the Responses API
#
# The Responses API continues a conversation by the previous response's id, with nothing else to
# keep.


def plan_with_responses(planner: noclick.Agent) -> None:
    first = gpt.responses.create(model=f"agent:{planner.name}", input="Plan me a Sunday morning in Porto.")
    print(first.output_text)
    later = gpt.responses.create(
        model=f"agent:{planner.name}", input="Make it cheaper.", previous_response_id=first.id,
    )
    print(later.output_text)


def main() -> None:
    summarize_ticket()
    draft_reply()
    rank_help_articles()
    planner = trip_planner()
    list_agent_models()
    plan_a_saturday(planner)
    plan_with_responses(planner)


if __name__ == "__main__":
    main()

# ## Streaming an agent
#
# `stream=True` works with an agent too. While its turn runs, the stream carries keepalive comments,
# which OpenAI clients skip, so a long turn never looks like a dead connection; then comes the
# reply. An agent on a coding harness such as Claude Code sends its reply whole when the turn ends.
# A request that doesn't stream has to finish inside the gateway's time limit, and one that can't
# gets an error telling you to stream: for long agent turns, always stream.
#
# ## Act for one of your users
#
# By default the endpoint acts for your account: your account's agents, your spend. To act for one
# of your [users](/docs/guide/users), with their own agents and counting toward their spend cap,
# send their id in the `NoClick-User` header. `noclick.AI.headers()` inside `as_user` gives it,
# with your key:
#
# ```python
# with noclick.as_user("user_42"):
#     ana = gpt.with_options(default_headers=noclick.AI.headers())
# ana.chat.completions.create(model="agent:assistant", messages=[{"role": "user", "content": "Anything urgent?"}])
# ```
#
# A user's [session](/docs/guide/sessions) token works as the key too, for a client that runs in
# their browser.
#
# ## Put your agents in a chat UI
#
# Any chat UI that speaks the OpenAI API can use NoClick as its backend, and your agents appear in
# its model picker. With [Open WebUI](https://openwebui.com), for example:
#
# ```bash
# docker run -d -p 3000:8080 \
#   -e OPENAI_API_BASE_URL=https://api.noclick.com/v1/ai \
#   -e OPENAI_API_KEY=$NOCLICK_API_KEY \
#   -v open-webui:/app/backend/data --name open-webui \
#   ghcr.io/open-webui/open-webui:main
# ```
#
# Open http://localhost:3000, pick `agent:trip-planner`, and chat. Open WebUI sends the whole chat
# with every message and no conversation, so each message starts a new conversation carrying the
# chat so far: the agent sees everything said, and the console shows a thread per message.
# Give the UI a key of its own with a monthly spend cap, since everyone who uses it spends as your
# account.
#
# ## Clean up
#
# The calls leave nothing behind. The agent stays until you delete it:
#
# ```python
# noclick.Agent.from_name("trip-planner").delete()
# ```
