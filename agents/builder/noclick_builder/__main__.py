"""Build a workflow from the command line with your own builder.

    export NOCLICK_API_KEY=nk_live_...
    python -m noclick_builder "Morning brief" "Every weekday at 8, email me today's calendar."

The workflow is made when the account has none by that name, and changed when it does. ``--assume`` has the builder
ask nothing.
"""

from __future__ import annotations

import argparse
import sys

import noclick

from . import agent, definition


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m noclick_builder", description=__doc__.splitlines()[0])
    parser.add_argument("name", help="the workflow's name")
    parser.add_argument("instructions", help="what it should do, or what to change")
    parser.add_argument("--assume", action="store_true", help="ask nothing: decide, and say what was assumed")
    args = parser.parse_args(argv)

    try:
        workflow = noclick.Workflow.from_name(args.name)
        workflow.id  # loads it; none by that name raises NotFound
    except noclick.NotFound:
        workflow = noclick.Workflow.create(args.name)

    built = agent.build(workflow, args.instructions,
                        questions=definition.ASSUME if args.assume else definition.ASK)
    print(built.summary)
    print()
    print(f"version {built.version} · {built.readiness.get('status')} · {built.readiness.get('meaning') or ''}")
    for issue in built.readiness.get("issues") or []:
        print(f"  in the way: {issue.get('step')}: {issue.get('message')}")
    for step in built.readiness.get("unverified") or []:
        print(f"  not run yet: {step.get('step')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
