# ---
# description: An agent that keeps watch over what you built in the NoClick app - it hears every failed workflow run and every app agent asking for you, looks into each, answers what it can and pauses a workflow that keeps failing - and your code asking an app agent directly.
# card_title: An agent that watches the app
# card_line: Handles failed runs and waiting agents.
# mark: eye
# cmd: ["python", "08_automations/watch_over_the_app.py"]
# env: ["NOCLICK_API_KEY"]
# deps: []
# ---

# # An agent that keeps watch over the app
#
# The workflows and agents you build in the NoClick app run on their own: a schedule fires, a message
# arrives, an agent works through it. When one breaks, or an agent needs you, you hear about it as an
# event. This example lists the agents built in the app, asks one of them something from code, and
# sets up an `ops` agent of your own that takes a turn on every failed run and every app agent's
# question: it reads what happened, answers the agent if it can, and pauses a workflow that keeps
# failing.
#
# ```bash
# pip install noclick
# export NOCLICK_API_KEY=nk_live_...
# python 08_automations/watch_over_the_app.py
# ```

import noclick

# ## The agents you built in the app
#
# `Agent.list` gives them after the agents made from code, with `origin` `app`; each names its
# workflow, whether it's switched on, and where to change it in the app.


def list_app_agents() -> list:
    agents = noclick.Agent.list(origin="app")
    for agent in agents:
        state = "on" if agent.enabled else "off"
        print(f"{agent.name} in '{agent.workflow_name}' ({state}): {agent.app_url}")
    return agents


# ## Ask one directly
#
# A message runs a turn on the agent's own step in its workflow, as a message from the app does, and
# the reply comes back whole. `conversation` continues the thread.


def ask(agent: noclick.Agent) -> None:
    reply = agent.message("In two lines: what are you working on, and is anything stuck?")
    print(f"\n{agent.name}: {reply.text}")


# ## An agent that keeps watch
#
# `ops` hears two of NoClick's own events. `workflow.run.failed` comes once per failing workflow
# (failures within six hours fold into one), so a workflow failing every minute is one conversation,
# keyed by the workflow. `agent.asked_owner` is an app agent messaging you. With NoClick's workflows
# and agents as its tools it can read a run step by step, pause a workflow, and message the agent
# back.


def keep_watch() -> noclick.Agent:
    return noclick.Agent.from_name(
        "ops",
        create_if_missing=True,
        instructions=(
            "You keep our automations healthy. When a workflow's run fails, read the run, find the step "
            "that broke and why, and pause the workflow if it keeps failing the same way. When one of our "
            "agents asks for us, answer it if what it needs is in the account; otherwise say plainly "
            "what a person has to do."
        ),
        tools=[noclick.Platform.only("workflows", "agents")],
        triggers=[
            noclick.OnPlatformEvent("workflow.run.failed", conversation="workflow-{data.workflow_id}",
                                    message="A workflow's run failed."),
            noclick.OnPlatformEvent("agent.asked_owner", conversation="asked-{data.agent_id}",
                                    message="One of our agents is asking for us."),
        ],
    )


def main() -> None:
    agents = list_app_agents()
    if agents and agents[0].enabled:
        ask(agents[0])
    ops = keep_watch()
    print(f"\n{ops.name} is keeping watch: {ops.trigger_kinds}")


if __name__ == "__main__":
    main()

# ## Clean up
#
# Listing and reading cost nothing; a message to an agent costs its turn. `ops` takes a turn only when
# something fails or asks, and `noclick.Agent.from_name("ops").delete()` removes it.
