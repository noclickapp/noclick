# ---
# description: A morning check of every automation in your account, built in the app or from code - what isn't set up, which step broke in its last failed run and why - that pauses the ones failing over and over until someone fixes them.
# card_title: A health check for automations
# card_line: What broke and why, every morning.
# mark: activity
# cmd: ["python", "08_automations/automation_health_check.py"]
# env: ["NOCLICK_API_KEY"]
# deps: []
# ---

# # A health check for your automations
#
# Automations break quietly: a token expires, a channel is renamed, an API starts refusing a field,
# and a schedule keeps firing into the same error every hour. This example reads every workflow your
# account owns the way the app shows it, says what stands in each one's way, finds the step that
# broke in its last failed run, and pauses the ones that keep failing, so they stop spending until
# someone looks. It changes nothing unless you pass `--pause`.
#
# ```bash
# pip install noclick
# export NOCLICK_API_KEY=nk_live_...
# python 08_automations/automation_health_check.py            # report only
# python 08_automations/automation_health_check.py --pause    # also pause the ones failing over and over
# ```
#
# Run it from a scheduler every morning, or hand the same calls to an agent: the account's own agent
# uses exactly these routes.

import sys

import noclick

RECENT = 5    # how many recent runs to judge a workflow by
FAILING = 3   # paused when at least this many of them failed

# ## What stands in its way
#
# One workflow reads in full: its `steps` (each with its settings, its account and, for a trigger,
# what keeps it from firing), its `readiness` and whether it's `paused`. `readiness.issues` are what
# the app's own check finds, each naming its step: one with no account connected, an account that
# stopped working, a trigger that couldn't register.


def report_setup(workflow: noclick.Workflow) -> None:
    for issue in workflow.readiness.get("issues", []):
        print(f"  needs: {issue['message']}")
    for step in workflow.steps:
        if step.connection and step.connection["healthy"] is False:
            print(f"  {step.name}: its account stopped working. {step.connection['hint']}")
        if step.trigger and step.trigger["error"]:
            print(f"  {step.name}: {step.trigger['error']}")


# ## Why the last failed run failed
#
# `runs()` lists recent runs however they started: a schedule, a webhook, the app, your code.
# `get_run` reads one with what each step did, so the broken step and its own error are right there.


def report_failures(workflow: noclick.Workflow) -> int:
    recent = workflow.runs(limit=RECENT)
    failed = [run for run in recent if run.status == "failed"]
    if failed:
        broken = next((s for s in workflow.get_run(failed[0].id).steps if s.status == "failed"), None)
        where = f"step '{broken.name}': {broken.error}" if broken else failed[0].error
        print(f"  {len(failed)} of its last {len(recent)} runs failed; the latest at {where}")
    return len(failed)


# ## Pause the ones that keep failing
#
# A pause switches the workflow's triggers off with the reason beside them in the app; `resume()`
# later switches back on only what the pause switched off. Runs you start from code still run.


def main() -> None:
    pause = "--pause" in sys.argv
    # Every workflow the account can open comes back, shared ones too; `access` says which are yours.
    owned = [w for w in noclick.Workflow.list() if w.access == "owner"]
    print(f"{len(owned)} workflows of your own\n")
    for listed in owned:
        workflow = noclick.Workflow.get(listed.id)  # a list is light: read each one in full
        print(f"{workflow.name}{'  (paused)' if workflow.paused else ''}")
        report_setup(workflow)
        failures = report_failures(workflow)
        if pause and failures >= FAILING and not workflow.paused:
            workflow.pause(f"{failures} of its last {RECENT} runs failed; paused by the morning check.")
            print("  paused it")
        print()


if __name__ == "__main__":
    main()

# ## Clean up
#
# Nothing here creates anything, and reading costs nothing. To switch a paused workflow back on once
# it's fixed: `noclick.Workflow.from_name("Hourly digest").resume()`.
