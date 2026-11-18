# ---
# description: A Slack post added to the end of an automation built in the app, in one change that lands only if nobody edited the automation meanwhile, with whether it's ready to run, and an undo from the automation's own versions.
# card_title: Change an automation from code
# card_line: One checked change, and its undo.
# mark: code
# cmd: ["python", "08_automations/change_an_automation.py", "Morning brief", "#team"]
# env: ["NOCLICK_API_KEY"]
# deps: []
# ---

# # Change an automation from code
#
# Someone built an automation in the app, and now it should also post to Slack when it's done. You
# could describe the change to NoClick's builder, but this one is small and exact, so this example
# makes it the way the app's canvas would: it reads the automation's steps, adds a Slack step after
# the last one and wires it in, as one change that lands only if nobody edited the automation since
# it was read. It says whether the new step is ready to run, and `--undo` takes it back out.
#
# ```bash
# pip install noclick
# export NOCLICK_API_KEY=nk_live_...
# python 08_automations/change_an_automation.py "Morning brief" "#team"    # add the post, or move it to #team
# python 08_automations/change_an_automation.py "Morning brief" --undo     # put back the version before it
# ```
#
# Set `SLACK_CREDENTIAL_ID` to the id of a Slack account connected in the app (its connection is
# `noclick.Connection.from_id("credential:<id>")`) to attach it to the new step as well.

import os
import sys
from typing import Optional

import noclick

STEP_NAME = "Post to Slack"

# ## Where the new step goes
#
# `graph()` reads the automation whole: each step with its type, name and settings as stored, and
# the edges between them. Each edge is `kind` `data` (the next step runs with this one's output) or
# `tools` (a step an agent uses as its tools). The step to post after is the last one: the one no data
# edge leaves, other than a step wired in as tools and the post this example added before.


def last_step(graph: noclick.WorkflowGraph) -> Optional[noclick.Step]:
    feeding = {edge["from"] for edge in graph.edges}
    ends = [step for step in graph.steps if step.id not in feeding and step.name != STEP_NAME]
    return ends[-1] if ends else None


# ## One change, checked
#
# The step and its edge go in one batch: both land as one version, or neither does. `if_version` is
# the version the graph was read at, so if someone changed the automation in the app in between, the
# batch is refused with `noclick.Conflict`, which carries the automation as it stands, and the loop
# decides again from that. Run it twice and the second run finds the post by its name and only
# changes its channel.


def add_post(workflow: noclick.Workflow, channel: str) -> None:
    graph = workflow.graph()
    for _ in range(3):
        ours = next((step for step in graph.steps if step.name == STEP_NAME), None)
        after = last_step(graph)
        if ours is None and after is None:
            raise SystemExit("The automation has no steps to post after yet.")
        try:
            with workflow.edit(if_version=graph.version) as e:
                if ours is not None:
                    e.update_step(ours, settings={"channel": channel})
                    step_id = ours.id
                else:
                    post = e.add_step("automation-slack", operation="send_message_to_channel", name=STEP_NAME,
                                      settings={"channel": channel, "text": f"{workflow.name} just ran."})
                    e.connect(after, post)
                    step_id = post.id
        except noclick.Conflict as changed:
            graph = changed.graph
            continue
        report(workflow, e.result, step_id)
        return
    raise SystemExit("The automation kept changing while this ran; try again in a minute.")


# ## Ready to run?
#
# A step that isn't ready yet is saved anyway, as on the canvas, and the change says what it needs:
# here, most likely, a Slack account. `set_connection` attaches one connected in the app; until then
# the app shows the step waiting for it. A post to a new channel also needs the Slack app invited
# there.


def report(workflow: noclick.Workflow, result: noclick.WorkflowEdit, step_id: str) -> None:
    print(f"{workflow.name}, version {result.history_version} of its history: {result.summary or 'nothing changed'}")
    verdict = result.steps.get(step_id) or {}
    slack = os.environ.get("SLACK_CREDENTIAL_ID")
    if slack and not verdict.get("config_valid"):
        step = workflow.step(step_id).set_connection(noclick.Connection.from_id(f"credential:{slack}"))
        verdict = step.verdict or {}
    if verdict.get("config_valid"):
        print(f"{STEP_NAME} is ready to run.")
    else:
        needs = verdict.get("validation_error") or ", ".join(verdict.get("missing_required") or [])
        print(f"{STEP_NAME} is saved, and needs: {needs}")


# ## Undo it
#
# Every change lands in the automation's history: who made it, from where and what it changed, each
# version under a `history_version` that never changes. `versions()` lists them newest first, and
# `restore` puts one back as a new version of its own, so an undo can be undone too. This only undoes
# the newest version when it's the post's own change; anything someone did after it stays, and you
# pick a version yourself.


def undo(workflow: noclick.Workflow) -> None:
    versions = workflow.versions(limit=2)
    if len(versions) < 2 or STEP_NAME not in (versions[0].summary or ""):
        print("The newest change isn't the post's. Its versions:")
        for version in workflow.versions(limit=10):
            print(f"  {version.history_version}  {version.source:<11} {version.summary}")
        return
    latest, before = versions
    workflow.restore(history_version=before.history_version, if_version=workflow.graph().version)
    print(f"Restored version {before.history_version}: {workflow.last_edit.summary}")


def main() -> None:
    names = [arg for arg in sys.argv[1:] if not arg.startswith("--")]
    if not names:
        raise SystemExit('Usage: change_an_automation.py "<automation name>" [#channel] [--undo]')
    workflow = noclick.Workflow.from_name(names[0])
    if "--undo" in sys.argv:
        undo(workflow)
    else:
        add_post(workflow, names[1] if len(names) > 1 else "#general")


if __name__ == "__main__":
    main()

# ## Clean up
#
# `--undo` takes the post back out; the versions stay listed for 90 days, so the undo can be undone
# with `restore` too. Changing an automation costs nothing; its runs are billed as they always are.
