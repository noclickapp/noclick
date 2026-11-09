"""A conversation forked or gone back to an earlier message, on a coding harness (``interchange.copy_thread``): the
thread cut where the person went back to (by their words, else a count of turns) and written into an empty store of
the same harness, which its runner resumes natively; and a revert's files put back from the dropped edits' diffs,
newest first, each file all or nothing (``interchange.undo``)."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from nodes.agent import interchange as ic
from nodes.agent.interchange.ir import ASSISTANT, MESSAGE, TOOL_CALL, TOOL_RESULT, USER, Event, Provenance, Thread
from nodes.agent.interchange.undo import CHANGED_SINCE, NOTHING_KEPT, undo_edits

CWD = "/home/casey/work/acme-api"
TURNS = ("Find the retry worker.", "Make it retry five times.", "Now add a test.")


def _thread() -> Thread:
    events, n = [], 0

    def add(**kw):
        nonlocal n
        n += 1
        events.append(Event(provenance=Provenance(n), timestamp=f"2026-11-10T10:00:{n:02d}Z", **kw))

    for i, text in enumerate(TURNS):
        add(kind=MESSAGE, role=USER, text=f"[It's 10:0{i}]\n{text}")
        add(kind=TOOL_CALL, tool_name="Bash", tool_call_id=f"call_{i}", tool_input={"command": f"grep -rn step{i} ."})
        add(kind=TOOL_RESULT, tool_name="Bash", tool_call_id=f"call_{i}", text=f"app.py:{i}: step{i}")
        add(kind=MESSAGE, role=ASSISTANT, text=f"Done with step {i}.")
    return Thread(harness="", source="test", session_id=None, cwd=CWD, started_at="2026-11-10T10:00:00Z",
                  cli_version=None, model=None, events=events, records=len(events))


def _store(harness: str, home: Path, **kw) -> ic.StoreRef:
    return ic.StoreRef(harness, home, Path(CWD), session_id="noclick" if harness == "hermes_agent" else None, **kw)


def _source(harness: str, tmp_path: Path) -> ic.StoreRef:
    thread = _thread()
    thread.harness = harness
    store = _store(harness, tmp_path / "source")
    ic.translate(thread, store)
    return store


def _users(store: ic.StoreRef) -> list:
    return [e.text for e in ic.read_thread(store).events if e.kind == MESSAGE and e.role == USER]


@pytest.mark.parametrize("harness", ["claude_code", "codex", "hermes_agent"])
def test_a_fork_or_revert_copies_the_thread_up_to_the_message_it_went_back_to(harness, tmp_path):
    source = _source(harness, tmp_path)
    target = _store(harness, tmp_path / "target", pointer=tmp_path / "target" / ".nc_thread")
    result = ic.copy_thread(source, target, before="Make it retry five times.")
    assert result.fidelity.ok
    assert [u.split("\n")[-1] for u in _users(target)] == [TURNS[0]], "cut before the person's own words"
    tools = [e.tool_call_id for e in ic.read_thread(target).events if e.kind in (TOOL_CALL, TOOL_RESULT)]
    assert tools == ["call_0", "call_0"], "every kept call keeps its result"
    if harness == "codex":
        assert (tmp_path / "target" / ".nc_thread").read_text() == result.session_id
    whole = ic.copy_thread(source, _store(harness, tmp_path / "whole"))
    assert whole.fidelity.ok and len(_users(_store(harness, tmp_path / "whole"))) == 3


def test_a_cut_by_turns_when_the_words_arent_found_and_refusals(tmp_path):
    source = _source("claude_code", tmp_path)
    ic.copy_thread(source, _store("claude_code", tmp_path / "two"), before="nowhere in it", turns=2)
    assert [u.split("\n")[-1] for u in _users(_store("claude_code", tmp_path / "two"))] == list(TURNS[:2])
    with pytest.raises(ic.InterchangeError) as refused:
        ic.copy_thread(source, _store("claude_code", tmp_path / "x"), before="nowhere in it")
    assert refused.value.reason == "cut_not_found"
    with pytest.raises(ic.InterchangeError) as moved:
        ic.copy_thread(source, _store("codex", tmp_path / "y"))
    assert moved.value.reason == "not_same_harness"
    with pytest.raises(ic.InterchangeError) as empty:
        ic.copy_thread(source, _store("claude_code", tmp_path / "z"), turns=0)
    assert empty.value.reason == "empty_source", "nothing kept: the harness starts a fresh session"


def test_the_command_copies_and_prints_one_verdict(tmp_path):
    source = _source("codex", tmp_path)
    package = Path(ic.__file__).parent
    run = subprocess.run(
        [sys.executable, "-m", package.name, "copy", "--harness", "codex", "--source-home", str(source.home),
         "--target-home", str(tmp_path / "t"), "--target-pointer", str(tmp_path / "t" / ".nc_thread"), "--cwd", CWD,
         "--before", "Now add a test."], capture_output=True, text=True, cwd=package.parent, check=True)
    verdict = json.loads(run.stdout.strip().splitlines()[-1])
    assert verdict["ok"] and verdict["fidelity"]["source"]["messages"] == 4, "two turns, each asked and answered"


DIFF = "@@ -1,3 +1,3 @@\n import time\n-RETRIES = 1\n+RETRIES = 5\n def go():\n"


def test_a_reverts_files_go_back_newest_edit_first(tmp_path):
    (tmp_path / "app.py").write_text("import time\nRETRIES = 5\ndef go():\n    return 2\n")
    (tmp_path / "new.txt").write_text("hello\n")
    second = "@@ -3,2 +3,2 @@\n def go():\n-    return 1\n+    return 2\n"
    verdicts = undo_edits([
        {"path": "new.txt", "change": "add", "diff": "@@ -0,0 +1 @@\n+hello\n"},
        {"path": "app.py", "change": "update", "diff": second},
        {"path": "app.py", "change": "update", "diff": DIFF},
    ], tmp_path)
    assert verdicts == [{"path": "new.txt", "restored": True}, {"path": "app.py", "restored": True}]
    assert (tmp_path / "app.py").read_text() == "import time\nRETRIES = 1\ndef go():\n    return 1\n"
    assert not (tmp_path / "new.txt").exists()


def test_a_file_that_changed_since_is_left_whole(tmp_path):
    (tmp_path / "app.py").write_text("import time\nRETRIES = 7\ndef go():\n    return 2\n")
    second = "@@ -3,2 +3,2 @@\n def go():\n-    return 1\n+    return 2\n"
    [verdict] = undo_edits([{"path": "app.py", "change": "update", "diff": second},
                            {"path": "app.py", "change": "update", "diff": DIFF}], tmp_path)
    assert verdict == {"path": "app.py", "restored": False, "why": CHANGED_SINCE}
    assert (tmp_path / "app.py").read_text() == "import time\nRETRIES = 7\ndef go():\n    return 2\n", \
        "the edit that would have gone back didn't: all or nothing"
    (tmp_path / "kept.txt").write_text("mine\n")
    [added] = undo_edits([{"path": "kept.txt", "change": "add", "diff": "theirs"}], tmp_path)
    assert added["why"] == CHANGED_SINCE and (tmp_path / "kept.txt").exists()
    [deleted] = undo_edits([{"path": "gone.txt", "change": "delete", "diff": "whatever it was"}], tmp_path)
    assert deleted["why"] == NOTHING_KEPT
    [back] = undo_edits([{"path": str(tmp_path / "gone.py"), "change": "delete", "diff": "@@ -1,2 +0,0 @@\n-a\n-b\n"}],
                        Path("/nonexistent"))
    assert back["restored"] and (tmp_path / "gone.py").read_text() == "a\nb\n"
