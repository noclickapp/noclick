"""``resolve_agent_event`` for the Exa monitor trigger.

Exa posts a finished monitor run as ``{id, object: "event", type:
"monitor.run.completed", data: <the run>}``, the run carrying ``output.results``
(the pages found), ``output.content`` (Exa's summary, text or the monitor's
schema) and ``output.grounding``. The base hook dumps that as JSON; the
override turns it into what a person reads: provider and event, the summary
and each new page clipped, the monitor and run ids, and the node's real
operations for acting on it. The delivery envelope never rides the turn, and
any other shape falls through to the base. Fixtures are fictional
(``.example`` hosts).
"""

import json

from nodes.core.agent_events import default_agent_event
from nodes.exa_node import EVENT_RESULTS_SHOWN, ExaNode

SECRET = "t=1700000000,v1=deadbeefcafe0123"
WEBHOOK = {"id": "wh-1", "method": "POST", "headers": {"exa-signature": SECRET}, "query_params": {}}
MANUAL_RUN = {"status": "success", "action": "on_monitor_results", "data": {"webhook_url": "https://wh.example/1"}}


def _result(i, **over):
    result = {
        "id": f"https://news.example/battery-{i}",
        "title": f"Battery recycling plant {i} announced",
        "url": f"https://news.example/battery-{i}",
        "publishedDate": "2026-11-06T08:00:00.000Z",
        "author": "Casey Example",
        "highlights": [f"Plant {i} will process 10,000 tonnes a year.", "Construction starts in spring."],
    }
    result.update(over)
    return result


def _delivery(*, status="completed", results=None, content="Two new plants were announced this week.", **run):
    output = None if status != "completed" else {
        "results": [_result(1), _result(2)] if results is None else results,
        "content": content,
        "grounding": [{"field": "content", "citations": [{"title": "t", "url": "https://news.example/battery-1"}],
                       "confidence": "high"}],
    }
    return {
        "id": "event_01kexample",
        "object": "event",
        "type": "monitor.run.completed",
        "data": {
            "id": "01krunexample",
            "monitorId": "01kmonitorexample",
            "status": status,
            "output": output,
            "failReason": None,
            "metadata": {"workspace": "ops"},
            "completedAt": "2026-11-06T09:00:00.000Z" if status == "completed" else None,
            **run,
        },
        "createdAt": "2026-11-06T09:00:01.000Z",
        "_webhook": WEBHOOK,
    }


def _schema_text() -> str:
    return json.dumps(ExaNode.get_config_schema())


def _assert_names_real_operation(text: str, *operations: str):
    for op in operations:
        assert f"{op} " in text, f"act hint should name {op}"
        assert f'"{op}"' in _schema_text(), f"ExaNode has no operation {op}"


def test_completed_run_reads_as_what_the_monitor_found():
    ev = ExaNode.resolve_agent_event(_delivery())
    text = ev["text"]
    assert text.splitlines()[0] == "Exa monitor run completed: 2 new results"
    assert ev["title"] == "Exa monitor run completed: 2 new results"
    assert ev["conversation_key"] is None
    assert "- monitor: 01kmonitorexample" in text and "- run: 01krunexample" in text
    assert "- finished: 2026-11-06T09:00:00.000Z" in text
    assert "- metadata: workspace: ops" in text and "- confidence: content high" in text
    assert "Summary:\nTwo new plants were announced this week." in text
    assert "1. Battery recycling plant 1 announced (2026-11-06)" in text
    assert "   https://news.example/battery-2" in text
    assert "Plant 2 will process 10,000 tonnes a year. … Construction starts in spring." in text
    assert "get_contents urls=<url>" in text
    assert "list_monitor_runs monitor_id=01kmonitorexample" in text
    _assert_names_real_operation(text, "get_contents", "list_monitor_runs")
    for leaked in (SECRET, "_webhook", "event_01kexample", '"object"'):
        assert leaked not in text


def test_a_result_reads_its_summary_before_its_highlights_and_text():
    results = [
        _result(1, summary="A summary of the page.", text="Body text."),
        _result(2, highlights=[], text="Only   the\npage text."),
        _result(3, highlights=[], text=None, title=None),
    ]
    text = ExaNode.resolve_agent_event(_delivery(results=results))["text"]
    assert "   A summary of the page." in text and "Body text." not in text
    assert "   Only the page text." in text
    assert "3. https://news.example/battery-3 (2026-11-06)" in text
    assert text.count("https://news.example/battery-3") == 1  # a title that IS the url isn't repeated


def test_a_structured_summary_rides_as_bounded_json():
    content = {"announcements": [{"company": "Example Metals", "location": "Ohio", "announcement": "x" * 5000}]}
    text = ExaNode.resolve_agent_event(_delivery(content=content))["text"]
    assert '"company": "Example Metals"' in text
    assert "[truncated" in text and "x" * 1600 not in text


def test_a_big_run_stays_bounded_and_says_what_it_left_out():
    results = [_result(i, text="word " * 2000, highlights=[]) for i in range(1, 26)]
    ev = ExaNode.resolve_agent_event(_delivery(results=results, content="y" * 9000))
    text = ev["text"]
    assert len(text) < 4000
    assert "Exa monitor run completed: 25 new results" in text
    assert f"{EVENT_RESULTS_SHOWN + 1}. " not in text
    assert "more on the trigger node]" in text
    assert "y" * 1600 not in text
    assert text.rstrip().endswith("list_monitor_runs monitor_id=01kmonitorexample.")


def test_a_failed_run_says_why_and_how_to_run_it_again():
    ev = ExaNode.resolve_agent_event(
        _delivery(status="failed", failReason="insufficient_credits", failedAt="2026-11-06T09:05:00.000Z")
    )
    text = ev["text"]
    assert text.splitlines()[0] == "Exa monitor run failed: insufficient credits"
    assert "- finished: 2026-11-06T09:05:00.000Z" in text
    assert "get_contents" not in text and "New results" not in text
    _assert_names_real_operation(text, "trigger_monitor", "list_monitor_runs")
    assert "trigger_monitor monitor_id=01kmonitorexample" in text


def test_a_run_that_found_nothing_new_says_so():
    text = ExaNode.resolve_agent_event(_delivery(results=[], content=None))["text"]
    assert text.splitlines()[0] == "Exa monitor run completed: nothing new"
    assert "Summary" not in text and "get_contents" not in text


def test_other_shapes_fall_through_to_the_base():
    assert ExaNode.resolve_agent_event(MANUAL_RUN)["text"].startswith("Event: on_monitor_results")
    for output in (
        MANUAL_RUN,
        {"type": "monitor.created", "data": {"id": "01kmonitorexample"}, "_webhook": WEBHOOK},
        {"type": "monitor.run.completed", "data": {"status": "completed"}},
        {"unrelated": "shape"},
        "not a dict",
    ):
        assert ExaNode.resolve_agent_event(output) == default_agent_event(output)
