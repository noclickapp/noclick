"""The date and time an agent's turn is told (``nodes.agent.turn_clock``), and
the agent node opening a turn with it when a platform set the clock."""

from datetime import datetime, timezone

from nodes.agent.turn_clock import TURN_CLOCK_KEY, clock_line, clock_of


def test_the_line_names_the_local_time_and_its_offset():
    now = datetime(2026, 1, 15, 23, 30, tzinfo=timezone.utc)
    assert clock_line("Asia/Kolkata", now) == "It is Friday, 16 January 2026, 05:00 in Asia/Kolkata (UTC+05:30)."
    assert clock_line("America/New_York", now) == ("It is Thursday, 15 January 2026, 18:30 in America/New_York "
                                                   "(UTC-05:00).")
    summer = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    assert clock_line("Europe/London", summer) == "It is Wednesday, 1 July 2026, 13:00 in Europe/London (UTC+01:00)."
    assert clock_line("UTC", summer).endswith("12:00 in UTC (UTC+00:00).")


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
