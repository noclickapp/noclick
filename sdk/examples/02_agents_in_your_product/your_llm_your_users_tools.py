# ---
# description: Run your own model loop with each of your users' Gmail, Calendar and web search as tools, approvals and connect links included, then serve the same tools to Claude Desktop and Cursor.
# card_title: Your model, your users' tools
# card_line: Your model, your users' apps as tools.
# mark: server
# cmd: ["python", "02_agents_in_your_product/your_llm_your_users_tools.py"]
# env: ["NOCLICK_API_KEY", "USER_EMAIL"]
# deps: ["openai"]
# ---

# # Your model loop, your users' tools
#
# You already run the model: your prompts, your loop, your provider. What you don't want to build
# is the rest: an OAuth app per service, token storage and refresh for every user, an API client
# per integration, and a way to stop the model sending email nobody approved. A
# [toolkit](/docs/guide/toolkits) is that part. You list the tools, and it gives your model their
# definitions, runs each call in the right user's account, and hands back results in your model
# API's shape.
#
# In this example a user asks for a morning brief: what's on their calendar tomorrow, which emails
# still need a reply, sent to them by email. You'll see the loop, what happens when the user hasn't
# connected an account yet, a send held for their approval, and the same tools served to Claude
# Desktop and Cursor as an MCP server.
#
# You play the user. `USER_EMAIL` is your own address: approval requests go there.
#
# ```bash
# pip install noclick openai
# export NOCLICK_API_KEY=nk_live_...
# export USER_EMAIL=you@example.com
# python 02_agents_in_your_product/your_llm_your_users_tools.py
# ```

import os
import time
from dataclasses import dataclass, field
from datetime import date

from openai import OpenAI

import noclick

# ## One toolkit for every user
#
# Each entry names a connection and one of its operations: `gmail` and `calendar` are
# connections every user of your product has, and a name resolves among the connections of the
# user a call acts for. So this one toolkit, built once at import, reads Ana's Gmail for Ana and
# Bo's for Bo. `exa.search` needs no account and runs on NoClick's key.
#
# Naming single operations keeps the model to what the feature needs: it can read mail and the
# calendar and send one kind of email, and nothing here deletes or archives.

TOOLKIT = noclick.Toolkit([
    "gmail.fetch_emails_from_inbox",
    "gmail.fetch_email_thread",
    "gmail.send_email_message",
    "calendar.list_calendar_events",
    "exa.search",
])

CONNECTIONS = {"gmail": "gmail", "calendar": "google_calendar"}

# ## The model
#
# Any OpenAI-compatible client works. This one uses NoClick's own
# [endpoint](/docs/guide/ai), so the model is charged to your NoClick account and needs no
# provider key. To use your own OpenAI key instead, build `OpenAI()` and pick an OpenAI model id;
# nothing else in the loop changes.

llm = OpenAI(base_url=noclick.AI.base_url, api_key=os.environ["NOCLICK_API_KEY"])
MODEL = "openrouter/anthropic/claude-sonnet-4.6"
MAX_MODEL_CALLS = 12

SYSTEM = f"""You are the assistant inside a productivity app. Today is {date.today():%A %d %B %Y}.
You can read the user's Gmail and Google Calendar and search the web.
Sending an email waits for the user's approval. When a tool says a call is waiting, tell the user
and stop; they will tell you when to go on. When a tool says an account isn't connected, say so."""

# ## Onboard a user
#
# Do this when someone signs up: the [user](/docs/guide/users), under your id for them, and a
# pending [connection](/docs/guide/connections) for each account the feature uses. Pending is fine:
# a tool whose account isn't connected yet answers with the link to connect it. `from_id` with
# `create_if_missing=True` also sets an existing user's name and email to yours, every time.
#
# The [policy](/docs/guide/policy) is the safety net. A `require_approval` rule holds every
# `gmail.send_email_message` call until a person approves that exact call, whoever makes it: your
# loop, an agent, or an MCP client. The rule names the integration's operation, not your
# connection's name. `Policy.add` adds the one rule and leaves the rest of the policy as it is, so
# it's safe to run every time. It's added for this user alone, so the example leaves your
# account's policy alone; in a real product you'd add it to the account once.
#
# A call made for a user is approved by that user, by email, which is why the user needs an
# address.


def onboard(user_id: str, email: str) -> noclick.User:
    user = noclick.User.from_id(user_id, create_if_missing=True, name="Ana Lima", email=email)
    with noclick.as_user(user):
        for name, integration in CONNECTIONS.items():
            noclick.Connection.from_name(
                name, integration=integration, create_if_missing=True, reason="for your morning brief",
            ).hydrate()
        noclick.Policy.add("gmail.send_email_message", to="require_approval")
    return user


# ## The loop
#
# This is the usual OpenAI tool loop. Two NoClick lines do the work:
#
# - `TOOLKIT.definitions("openai")` gives the tool definitions, as `{connection}__{operation}`
#   functions (`gmail__send_email_message`).
# - `TOOLKIT.handle_openai(completion)` runs every tool call in the completion at once, inside the
#   user `as_user` names, and returns the `tool` messages to append.
#
# A tool call never raises for something the model can deal with. An account that isn't connected,
# or a call held for approval, comes back as an error result the model reads and explains. Your
# code hears about both too, so your UI can show a real button rather than a link in the text:
# `on_approval` receives each held call, and `on_connect` each call whose connection needs
# connecting. The model never sees the approval link, so it can't approve its own call.
#
# `as_user` covers NoClick's client, not the `openai` one. `noclick.AI.headers()` inside it gives
# the headers that make the model's own tokens count toward this user's spend cap, like the tool
# calls do.


@dataclass
class Turn:
    reply: str
    held: list = field(default_factory=list)
    to_connect: dict = field(default_factory=dict)


def run_turn(user: noclick.User, messages: list) -> Turn:
    turn = Turn("")
    needs: list = []
    with noclick.as_user(user):
        headers = noclick.AI.headers()
        for _ in range(MAX_MODEL_CALLS):
            completion = llm.chat.completions.create(
                model=MODEL,
                messages=messages,
                tools=TOOLKIT.definitions("openai"),
                extra_headers=headers,
            )
            message = completion.choices[0].message
            messages.append(message)
            if not message.tool_calls:
                turn.reply = message.content or ""
                turn.to_connect = {result.needs_connection["connection"]: result.connect_url for result in needs}
                return turn
            messages += TOOLKIT.handle_openai(completion, on_approval=turn.held.append, on_connect=needs.append)
    raise RuntimeError(f"No answer after {MAX_MODEL_CALLS} model calls")


def say(user: noclick.User, messages: list, text: str) -> Turn:
    messages.append({"role": "user", "content": text})
    turn = run_turn(user, messages)
    print(f"\nassistant: {turn.reply}")
    return turn


# ## Connect, then approve
#
# The first time, the accounts aren't connected yet, so the model says so and your code gets each
# connection's link. In your product these are "Connect Gmail" and "Connect Google Calendar"
# buttons; here they're printed, and `wait()` returns once you've connected each one. Then the
# user says "try again", and the model does.
#
# When the model sends the brief, the call is held. The approval request is already in the user's
# inbox, and your code has it as `result.approval`, a [human request](/docs/guide/humans) with its
# link. `wait()` on it returns `True` once they approve. The model's next attempt at the identical
# call goes through, once: a changed recipient or body would need a new approval.


def connect_accounts(user: noclick.User, links: dict) -> None:
    for name, url in links.items():
        print(f"Connect {name}: {url}")
    with noclick.as_user(user):
        for name in links:
            noclick.Connection.from_name(name).wait()


def approve(user: noclick.User, messages: list, held: list) -> None:
    for result in held:
        print(f"\n{result.name} is waiting for your approval: {result.approve_url}")
        say(user, messages, "Approved, go ahead." if result.approval.wait() else "I declined that. Don't send it.")


# ## The same tools in Claude Desktop and Cursor
#
# Your users also work in chat apps and editors that speak MCP. A hosted
# [MCP server](/docs/guide/mcp-servers) puts the same toolkit at one URL for them, and NoClick runs
# it: no MCP code of yours, no process to keep up. `TOOLKIT.mcp_server(name)` creates the server in
# the user `as_user` names, over that user's connections, and after that sets its tools to the
# toolkit's, so adding an entry above reaches every user's server the next time this runs.
# The URL stays the same.
#
# In your product this is a "Use your assistant in Claude" page: the URL, and how to add it. Ana
# adds it once:
#
# - **Claude Desktop**: Settings, Connectors, Add custom connector, then paste the URL.
# - **Cursor**: in `.cursor/mcp.json`, `{"mcpServers": {"assistant": {"url": "<url>"}}}`.
# - **Claude Code**: `claude mcp add --transport http assistant <url>`.
#
# Every call through it is the same as a toolkit call: it runs in Ana's accounts, under the same
# policy, so a send from Claude Desktop waits for her approval by email just like one from your
# loop, and the client is told it's waiting. Each call is recorded with the server's name, so the
# console shows what her MCP client did.
#
# The path of the URL is its secret: anyone who has it can call Ana's tools. Show it only to her,
# and `server.rotate()` when she asks for a new one.
#
# Whether it works has two sides. `tool_count` above zero means NoClick is serving tools. A
# connection that isn't connected serves none, which is why this step comes after the user has
# connected. `clients()` lists the MCP clients that have connected, as they named themselves, with
# how many tools each saw; most connect, and list tools, only when a new chat or session starts.


def serve_over_mcp(user: noclick.User) -> noclick.McpServer:
    with noclick.as_user(user):
        server = TOOLKIT.mcp_server("assistant")
    print(f"\nMCP server for {user.id}: {server.url} ({server.tool_count} tools)")
    return server


def wait_for_a_client(server: noclick.McpServer, minutes: int = 10) -> None:
    print("Add it to Claude Desktop or Cursor and start a new chat. Waiting for a client...")
    deadline = time.monotonic() + minutes * 60
    while time.monotonic() < deadline:
        clients = server.clients()
        if clients:
            for client in clients:
                print(f"  {client.name} {client.version or ''} connected, sees {client.tool_count} tools")
            return
        time.sleep(5)
    print("  No client yet. It'll connect whenever one starts a session; the URL doesn't expire.")


def main() -> None:
    user = onboard("user_42", os.environ["USER_EMAIL"])
    messages: list = [{"role": "system", "content": SYSTEM}]

    turn = say(
        user,
        messages,
        "What's on my calendar tomorrow, and which emails from the last two days still need a reply "
        f"from me? Email me the brief at {user.email}.",
    )
    if turn.to_connect:
        connect_accounts(user, turn.to_connect)
        turn = say(user, messages, "I've connected them. Try again.")
    approve(user, messages, turn.held)

    server = serve_over_mcp(user)
    wait_for_a_client(server)


if __name__ == "__main__":
    main()

# ## What it costs
#
# The model's tokens are charged to your NoClick account at the model's price (with your own key,
# to your provider). Each tool call is billed as a tool run, `exa.search` included. The MCP server
# itself is free; its calls bill like toolkit calls. All of it counts toward the user's spend cap
# (`spend_cap_usd_per_month` on the user), so one heavy user can't run up your bill.
#
# ## Clean up
#
# Deleting the server stops its URL; the connections stay. Deleting a connection disconnects NoClick
# from the account (keep `gmail` if you're still using it for `connect_a_user.py`):
#
# ```python
# with noclick.as_user("user_42"):
#     noclick.McpServer.from_name("assistant").delete()
#     noclick.Connection.from_name("calendar").delete()
#     noclick.Connection.from_name("gmail").delete()
#     noclick.Policy.remove("gmail.send_email_message")
# ```
