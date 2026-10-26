"""A turn that keeps calling tools without changing anything is stuck, whatever its arguments: a coordinator asked to
rework one 8 MB game file re-read it at shifting offsets for over an hour and edited it once, and the repeat guard
never fired, since no two calls were the same (2026-10-26). With a ``stalled`` wrap-up, the turn's
guard counts the calls in a row that only read (``progress.only_reads``): the ``QUIET_NUDGE``th carries a note to act
or say what blocks it, and the ``QUIET_STOP``th stops the turn after the calls in hand, wrapped up as a limit's. Run
through the real streamed SDK and PostgreSQL with a scripted model (``test_openai_agent_turn_guards._run``)."""

import json

import pytest

from coder.openai_agent import progress
from tests.test_builder_requests import builder_request_db  # noqa: F401
from tests.test_openai_agent_turn_guards import STANDING, WRAP_UP, _outputs, _run, _said

STALLED = {**WRAP_UP, "stalled": {"prompt": "Out of stalled: say what blocks you.", "line": "Stopped on stalled."}}

# Commands from the turns that looped (reads at shifting offsets of one file), and the writes that end a run of them.
READS = [
    "python3 - <<'PY'\np='/workspace/game/city.html'; s=open(p).read(); print(len(s))\n"
    "for key in ['const RX=','function cellOf']:\n i=s.find(key); print('\\n##',key,i); print(s[i:i+2200])\nPY",
    "sed -n '395,445p' /workspace/game/game.js; sed -n '720,733p' /workspace/game/game.js;",
    "cd /workspace/game && grep -nE 'const RX|function buildBlocks|G\\.peds' game.js | head -70",
    "ls -l /workspace/a.html /workspace/b.html 2>/dev/null; grep -n 'ROAD_NODES' /workspace/game.js | head -100",
    "cd /workspace/repo && git status --short && git log -1 --oneline && git branch --show-current",
    "curl -fsS https://rosa-tacos.noclick.site/ | head -c 500",
    "node --check /workspace/game/game.js && echo ok",
    'for f in /workspace/*.js; do wc -l "$f"; done',
    "rg -n 'spawnTraffic' /workspace && outline /workspace/game/city.html",
    "html-script list /workspace/game/city.html",
    "python3 -c 'import json; print(json.load(open(\"/workspace/package.json\"))[\"name\"])'",
    "timeout 30 node -e 'console.log(require(\"fs\").readFileSync(\"/workspace/a.js\", \"utf8\").length)'",
]
WRITES = [
    "cat > /workspace/game.js <<'EOF'\nconsole.log(1)\nEOF",
    "python3 - <<'PY'\np='/workspace/x.html'; s=open(p).read()\nopen(p,'w').write(s.replace('a','b'))\nPY",
    "python3 - <<'PY'\nfrom pathlib import Path\nPath('/workspace/x.js').write_text('x')\nPY",
    "sed -i 's/grid/curve/' /workspace/game.js",
    "cd /workspace/repo && git add -A && git commit -m 'Curve the roads' && git push",
    "grep -n 'RX' /workspace/game.js > /tmp/refs.txt; cat /tmp/refs.txt",
    "html-script extract /workspace/page.html 2 /workspace/game.js",
    "perl -pi -e 's/a/b/' /workspace/x.js",
    "curl -fsS -X POST -d '{}' https://api.example.com/x",
    "node -e \"require('fs').writeFileSync('/workspace/a', 'b')\"",
    "npm install",
    "echo $(rm -rf /workspace/x)",
    "find /workspace -name '*.tmp' -delete",
    "python3 /workspace/build.py",
    "echo 'unterminated",
    "ls `pwd`",
]


@pytest.mark.parametrize("command", READS)
def test_a_command_that_only_looks_reads(command):
    assert progress.shell_reads(command)
    assert progress.only_reads("execute_bash", json.dumps({"command": command}))


@pytest.mark.parametrize("command", WRITES)
def test_a_command_that_may_change_something_is_progress(command):
    assert not progress.shell_reads(command)


def test_other_tools_are_judged_by_the_platform_and_unknown_ones_are_progress(monkeypatch):
    monkeypatch.setattr(progress, "_JUDGES", [lambda tool, args: (args.get("method") == "GET")
                                              if tool == "api" else None])
    assert progress.only_reads("api", {"method": "GET"})
    assert not progress.only_reads("api", {"method": "POST"})
    assert not progress.only_reads("send_email", {"to": "x"})
    assert not progress.only_reads("api", "not json")


def _reads_look(monkeypatch):
    """The test tool ``look`` only reads, unless its call says it writes."""
    monkeypatch.setattr(progress, "_JUDGES", [
        lambda tool, args: not args.get("write") if tool == "look" else None])


async def test_a_turn_reading_on_without_change_is_told_then_stopped(builder_request_db, monkeypatch):
    from coder.openai_agent import guards
    from coder.openai_agent.guards import TurnLimits

    _reads_look(monkeypatch)
    monkeypatch.setattr(guards, "QUIET_NUDGE", 3)
    monkeypatch.setattr(guards, "QUIET_STOP", 5)
    pool = builder_request_db[0]
    calls, looked, emitted, agent, spans = await _run(pool, monkeypatch, wrap_up=STALLED,
                                                      limits=TurnLimits(steps=20))

    # Each call reads a new page (no two alike, so the repeat guard never fires). The third result carries the note;
    # the fifth stops the turn, which wraps up told why, and its line follows.
    assert len(looked) == 5 and [choice for choice, _ in calls] == [None] * 5 + ["none"]
    outputs = _outputs(calls[-1][1])
    assert '"page 3 of the logs"' in outputs[2]
    assert outputs[2].endswith(guards.QUIET_NOTE.format(calls=3))
    assert not any("only read" in output for i, output in enumerate(outputs) if i != 2)
    assert calls[-1][1][-1] == {"role": "developer", "content": STALLED["stalled"]["prompt"]}
    assert _said(emitted) == f"{STANDING}\n\nStopped on stalled." and agent.turn_ended_by == "stalled"
    [span] = spans
    assert span.attributes["agent.turn.ended_by"] == "stalled"
    assert (span.attributes["agent.turn.longest_read_streak"], span.attributes["agent.turn.read_notes"]) == (5, 1)
    assert span.attributes["agent.turn.loop_nudges"] == 0


async def test_a_change_starts_the_count_again(builder_request_db, monkeypatch):
    from coder.openai_agent import guards
    from coder.openai_agent.guards import TurnLimits

    _reads_look(monkeypatch)
    monkeypatch.setattr(guards, "QUIET_NUDGE", 3)
    monkeypatch.setattr(guards, "QUIET_STOP", 5)
    pool = builder_request_db[0]
    calls, looked, emitted, agent, spans = await _run(
        pool, monkeypatch, wrap_up=STALLED, limits=TurnLimits(steps=20),
        call=lambda n: {"page": n, "write": n in (4, 8)},
        answer_after=lambda model_input: len(_outputs(model_input)) == 10)

    # Reads 1-3 (noted), a write, reads 5-7 (noted again), a write, reads 9-10: never five in a row.
    assert len(looked) == 10 and _said(emitted) == "Done: nothing else to look at." and agent.turn_ended_by is None
    noted = [i + 1 for i, output in enumerate(_outputs(calls[-1][1])) if "only read" in output]
    assert noted == [3, 7]
    assert (spans[0].attributes["agent.turn.longest_read_streak"], spans[0].attributes["agent.turn.read_notes"]) == \
        (3, 2)


async def test_a_turn_without_a_stalled_wrap_up_reads_on_unjudged(builder_request_db, monkeypatch):
    """A workflow's agent node gives no such wrap-up: its turn's guards are only the ones it asked for."""
    from coder.openai_agent import guards
    from coder.openai_agent.guards import TurnLimits

    _reads_look(monkeypatch)
    monkeypatch.setattr(guards, "QUIET_NUDGE", 3)
    monkeypatch.setattr(guards, "QUIET_STOP", 5)
    pool = builder_request_db[0]
    calls, looked, emitted, agent, spans = await _run(
        pool, monkeypatch, limits=TurnLimits(steps=20),
        answer_after=lambda model_input: len(_outputs(model_input)) == 8)

    assert len(looked) == 8 and agent.turn_ended_by is None
    assert not any("only read" in output for output in _outputs(calls[-1][1]))
    assert spans[0].attributes["agent.turn.read_notes"] == 0
