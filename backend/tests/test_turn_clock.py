"""The date and time an agent's turn is told (``nodes.agent.turn_clock``), and
the agent node opening a turn with it when a platform set the clock."""

from datetime import datetime, timezone

from nodes.agent.turn_clock import TURN_CLOCK_KEY, clock_line, clock_of


def test_the_line_names_the_local_time_its_offset_and_the_time_in_utc():
    now = datetime(2026, 1, 15, 23, 30, tzinfo=timezone.utc)
    assert clock_line("Asia/Kolkata", now) == ("It is Friday, 16 January 2026, 05:00 in Asia/Kolkata (UTC+05:30), "
                                               "23:30 UTC on Thursday 15 January.")
    assert clock_line("America/New_York", now) == ("It is Thursday, 15 January 2026, 18:30 in America/New_York "
                                                   "(UTC-05:00), 23:30 UTC.")
    summer = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    assert clock_line("Europe/London", summer) == ("It is Wednesday, 1 July 2026, 13:00 in Europe/London (UTC+01:00), "
                                                   "12:00 UTC.")
    # Where local time is UTC, there's nothing to tell apart.
    assert clock_line("UTC", summer).endswith("12:00 in UTC (UTC+00:00).")
    assert clock_line("Europe/London", now).endswith("23:30 in Europe/London (UTC+00:00).")


def test_a_time_given_in_utc_reads_against_the_utc_time_not_the_local_one():
    """Told only the local time (22:10 in Kolkata), a model read it as UTC and called 21:30Z past (2026-10-26): the
    line it reads says it's 16:40 UTC."""
    line = clock_line("Asia/Kolkata", datetime(2026, 10, 26, 16, 40, tzinfo=timezone.utc))
    assert line == "It is Monday, 26 October 2026, 22:10 in Asia/Kolkata (UTC+05:30), 16:40 UTC."


def test_only_a_platform_set_clock_counts():
    assert clock_of({TURN_CLOCK_KEY: {"timezone": "Europe/Paris"}}) == "Europe/Paris"
    for config in ({}, None, {TURN_CLOCK_KEY: {}}, {TURN_CLOCK_KEY: "Europe/Paris"}, {TURN_CLOCK_KEY: {"timezone": ""}}):
        assert clock_of(config) is None


class _Reached(Exception):
    """Raised at the first step after the turn is composed."""


async def _composed(monkeypatch, config: dict) -> str:
    import pytest

    from nodes.agent_node import AgentNode

    data = {"config": {"model": "openrouter/openai/gpt-4o-mini", "message": "What happened last month?", **config}}
    agent = AgentNode(node_id="agent_1", node_type="agent", node_data=data, config=AgentNode.parse_config(data),
                      sio=None, sid=None, workflow_id="wf_1")

    async def _no_emit(*a, **k):
        return None

    async def _reached(*a, **k):
        raise _Reached()

    monkeypatch.setattr("nodes.agent_node.send_event", _no_emit)
    monkeypatch.setattr(agent, "_resolve_model_env_overrides", _reached)
    with pytest.raises(_Reached):
        await agent.execute({})
    return agent.config.config.message




async def test_no_clock_leaves_the_turn_as_it_was(monkeypatch):
    assert await _composed(monkeypatch, {}) == "What happened last month?"
