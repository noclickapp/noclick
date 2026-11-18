# ---
# description: A hosted agent that researches the web and works out the numbers, keeps the conversation going, then runs on Claude Code with one more argument.
# card_title: Hello, agent
# card_line: Research, compute, hand off to Claude Code.
# mark: code
# cmd: ["python", "01_getting_started/hello_agent.py"]
# env: ["NOCLICK_API_KEY"]
# deps: []
# ---

# # Hello, agent
#
# Your team needs a transactional email provider, and someone has to read five pricing pages and
# do the sums. In this example a hosted agent does it: it searches the web, reads each vendor's
# pricing page, and in a follow-up works out what each option would cost you. Then you run the
# same agent on Claude Code by adding one argument, and see what changes.
#
# You need a NoClick API key and nothing else. The web search runs on NoClick's key, so there's no
# account to create and nothing to connect until the last step, which asks for a Claude key.
#
# ```bash
# pip install noclick
# export NOCLICK_API_KEY=nk_live_...
# python 01_getting_started/hello_agent.py
# ```

import noclick

# ## Define the agent
#
# An [agent](/docs/guide/agents) is instructions plus tools, and NoClick runs it: the model, the
# tool calls, the conversation history and the billing. `from_name` with `create_if_missing=True`
# creates it on first use and, after that, sets the fields this code passes, so running the script
# again changes nothing until you change them.
#
# Its one tool, `"exa.search"`, is Exa's web search, which can also return each page's text. It
# needs no account, so it runs on NoClick's key for any agent, with no connection to create, and
# it's billed as a tool run.
#
# Every agent also has a sandbox with a shell, the `code` tool, whether or not you list it. The
# instructions send arithmetic there, because tiered pricing is the kind of sum a model gets
# slightly wrong in its head.

INSTRUCTIONS = """You research software vendors for a small engineering team.
Read the vendor's own pricing page before you trust a number, and cite it.
Do arithmetic with code, never in your head. Keep your replies short."""


def define_researcher() -> noclick.Agent:
    return noclick.Agent.from_name(
        "researcher",
        create_if_missing=True,
        instructions=INSTRUCTIONS,
        tools=["exa.search"],
    )


# ## Message it, then keep talking
#
# `message` sends the text and waits for the reply: its `text`, the `conversation` it belongs to,
# and the `tool_calls` the turn made. The follow-up only makes sense with the first answer in
# view ("each of them"), so it passes the conversation back. Without `conversation`, a message
# starts a new one.


def compare_providers(researcher: noclick.Agent) -> None:
    reply = researcher.message(
        "Compare the transactional email APIs Postmark, Resend and Amazon SES: the plan a startup "
        "would start on, its monthly price, the emails it includes, and the price per 1,000 beyond that."
    )
    print(reply.text)
    print("tools used:", ", ".join(call["name"] for call in reply.tool_calls))

    costs = researcher.message(
        "We send about 180,000 emails a month. What would each of them cost us, cheapest first?",
        conversation=reply.conversation,
    )
    print(costs.text)
    print("tools used:", ", ".join(call["name"] for call in costs.tool_calls))


# ## The same agent on Claude Code
#
# `harness=` picks what runs the agent. Everything above ran on `sdk`, NoClick's own agent loop.
# `claude_code` runs Claude Code instead, with the same instructions and the same tools: the
# agent below differs by that one argument, plus the Claude connection Claude Code thinks
# with. It's a second agent here so you can compare the two side by side;
# `researcher.update(harness="claude_code", model_connection=claude)` would move the first one
# instead, its conversations included. `Agent.harness_info` says what NoClick runs: the harness's
# version, its default model, and whether its reply streams.
#
# That connection is a [model provider's connection](/docs/guide/connections#model-providers).
# The first time, the script prints a link where you paste a Claude API key; NoClick checks the
# key with Anthropic before it saves it, and your code never sees it.
#
# What changes on Claude Code:
#
# - **It starts a sandbox first.** The turn's operation reports `step` `delivering` while the
#   sandbox starts, then `working`. The sandbox stays warm for about a minute after each reply.
# - **It has its own shell, files and web.** Its built-in commands show up in `tool_calls` with
#   `source: "harness"`, beside the NoClick tools you gave it.
# - **The reply arrives whole** when the turn ends, rather than as it's written.
# - **Billing splits.** The model's tokens go to your Claude key; NoClick bills the sandbox's
#   running time.


def on_claude_code() -> None:
    harness = noclick.Agent.harness_info("claude_code")
    print(f"Claude Code {harness.version}: default model {harness.default_model}, reply {harness.streaming}")

    claude = noclick.Connection.from_name("claude", integration="anthropic", create_if_missing=True)
    if not claude.connected:
        link = claude.connect_link(reason="so your Claude Code agent can think with your Claude key")
        print(f"Paste a Claude API key here, then come back:\n  {link.url}")
        link.wait()

    coder = noclick.Agent.from_name(
        "researcher-on-claude-code",
        create_if_missing=True,
        instructions=INSTRUCTIONS,
        tools=["exa.search"],
        harness="claude_code",
        model_connection=claude,
    )

    turn = coder.send(
        "Compare the transactional email APIs SendGrid and Mailgun: the plan a startup would start on, "
        "and what each would cost us at 180,000 emails a month."
    )
    for event in turn.events(interval=3):
        print(f"  {event.status} {turn.step or ''}")
    reply = turn.wait()
    print(reply.text)
    for call in reply.tool_calls:
        print(f"  {call.get('source', 'noclick'):<8} {call['name']}")


def main() -> None:
    researcher = define_researcher()
    compare_providers(researcher)
    on_claude_code()
    print(f"\nEvery turn and tool call is in the console: {researcher.console_url}")


if __name__ == "__main__":
    main()

# ## Clean up
#
# The agents and the connection stay until you delete them. An agent costs nothing between
# messages, so there's no rush:
#
# ```python
# noclick.Agent.from_name("researcher").delete()
# noclick.Agent.from_name("researcher-on-claude-code").delete()
# noclick.Connection.from_name("claude").delete()
# ```
#
# Next, `connect_a_user.py` connects your first user's Gmail, so an agent can act in their own
# account.
