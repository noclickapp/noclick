"""A release's progress as both CLIs draw it: the same reads give the same lines at a terminal (drawn in place) and
anywhere else (a line each). ``cli_progress_cases.json`` holds what they print; the TypeScript CLI's tests read it too.
After a deliberate change, rewrite it with ``PYTHONPATH=. python tests/test_cli_progress.py --write``."""

import json
import sys
from pathlib import Path

import pytest

from noclick._cli import progress, style

CASES = Path(__file__).with_name("cli_progress_cases.json")


def render(events, live):
    out, now = [], [0.0]
    steps = progress.Steps(out.append, live=live, clock=lambda: now[0], paint=style.Style(False), ticker=False)
    follower = progress.Follower(steps, single=next((e["single"] for e in events if e.get("single")), None))
    for event in events:
        now[0] = event["at"]
        if "start" in event:
            steps.start(event["start"])
        if "end" in event:
            steps.end(event["end"])
        if "tick" in event:
            steps.tick()
        if "apply" in event:
            follower.apply(event["apply"])
    steps.close()
    return "".join(out)


def _cases():
    return json.loads(CASES.read_text())["cases"]


@pytest.mark.parametrize("case", [c for c in _cases() if "events" in c], ids=lambda c: c["name"])
def test_both_ways_of_drawing_a_release_print_what_the_cases_say(case):
    assert render(case["events"], live=False) == case["plain"]
    assert render(case["events"], live=True) == case["live"]


def test_times_cut_to_tenths_then_minutes():
    for seconds, said in next(c for c in _cases() if c["name"] == "took")["took"]:
        assert progress.took(seconds) == said


def test_following_reads_each_change_once_names_what_it_saw_and_stops_where_ctrl_c_does():
    """Each read waits for the operation to move past the ``updated_at`` it last saw; Ctrl-C mid-read stops
    following (the work goes on) with the stage left as it was."""
    reads = []
    snapshots = iter([
        {"status": "running", "updated_at": "t2", "progress": {"stages": [{"name": "Building", "status": "current"}],
                                                               "lines": ["> vite build"], "line_count": 1}},
        KeyboardInterrupt,
    ])

    def read(op_id, window, changed_since):
        reads.append((op_id, window, changed_since))
        got = next(snapshots)
        if got is KeyboardInterrupt:
            raise KeyboardInterrupt
        return got

    out = []
    steps = progress.Steps(out.append, live=False, ticker=False)
    first = {"status": "queued", "updated_at": "t1", "progress": None}
    assert progress.follow("op_d", first, steps, read, timeout=30, clock=lambda: 0.0) is None
    assert reads == [("op_d", 30, "t1"), ("op_d", 30, "t2")]
    assert "".join(out) == "Build…\n  > vite build\n"


if __name__ == "__main__" and "--write" in sys.argv:
    written = json.loads(CASES.read_text())
    for case in written["cases"]:
        if "events" in case:
            case["plain"], case["live"] = render(case["events"], False), render(case["events"], True)
    CASES.write_text(json.dumps(written, indent=2, ensure_ascii=False) + "\n")
