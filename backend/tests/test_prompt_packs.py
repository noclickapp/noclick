"""The prompt seam (utils/prompts.py): every pack's default is a module of listed
parts, a registered pack replaces it whole, and a part it lacks fails rather than
falling back to the default."""

import importlib
from types import SimpleNamespace

import pytest

from utils import prompts


def test_every_default_lists_parts_it_has():
    for name, module in prompts.PACKS.items():
        default = importlib.import_module(module)
        assert default.__all__, f"{module} lists no parts"
        assert [p for p in default.__all__ if not hasattr(default, p)] == [], module


def test_a_registered_pack_replaces_the_default(monkeypatch):
    monkeypatch.setitem(prompts.PACKS, "example", "string")  # a stdlib module with __all__
    monkeypatch.setattr(prompts, "_REGISTERED", {})
    pack = prompts.PromptPack("example")
    assert pack.digits == "0123456789"
    prompts.register_prompts("example", SimpleNamespace(digits="tuned"))
    assert pack.digits == "tuned"
    with pytest.raises(AttributeError):
        pack.ascii_letters  # registered packs offer every part; a missing one is a bug, not the default
    assert "ascii_letters" in prompts.missing_parts("example")


def test_an_unknown_pack_is_refused():
    with pytest.raises(KeyError):
        prompts.PromptPack("no-such-pack")
    with pytest.raises(KeyError):
        prompts.register_prompts("no-such-pack", SimpleNamespace())


def test_the_engine_builds_every_prompt_from_the_defaults(monkeypatch):
    """With no pack registered (the open edition), every tool and note the engine composes from a pack's parts
    is built: each key a dict part is read by is there."""
    from coder.coordinator import tools as coordinator_tools
    from coder.coordinator.followup import FollowupDelivery
    from nodes.agent import platform_tools
    from utils import capabilities

    monkeypatch.setattr(prompts, "_REGISTERED", {})
    plans = [{"plan": "member", "label": "Member", "monthly_usd": 25, "yearly_usd": 300, "description": "d"}]
    for catalog in (None,
                    {"plans": plans, "funds": {"min_usd": 10, "max_usd": 1000, "presets_usd": [10]}, "checkout_note": ""},
                    {"plans": plans, "topups": [{"credits_per_month": 20, "monthly_usd": 5}], "checkout_note": ""}):
        for account_connect in (False, True):
            built = coordinator_tools.coordinator_tool_params(
                include_whatsapp=True, include_imessage=True, include_publishing=True, include_phone_numbers=True,
                include_account_connect=account_connect, include_auto_topup=True, purchase_catalog=catalog,
                include_platform=True, include_upi_payments=True)
            assert all(p["function"]["description"] for p in built)
    assert FollowupDelivery.tool_param()["function"]["description"]
    monkeypatch.setattr(capabilities, "_providers", {**capabilities._providers, **{
        key: object() for key in (capabilities.CONNECTION_REQUESTS, capabilities.WAKEUPS, capabilities.PARENT_UPDATES)}})
    monkeypatch.setattr(platform_tools, "agent_email_available", lambda: True)
    pairs = platform_tools.build_platform_tools(
        True, True, connection_requests={"integrations": ["gmail"]}, wake_me={"thread": "t"}, tell_parent={"p": 1})
    assert len(pairs) == 11 and all(param["function"]["description"] for param, _ in pairs)
    note, keys = platform_tools.builder_updates_note([
        {"kind": "builder_decision", "payload": {"proposal_id": "p1", "decision": "approved"}},
        {"kind": "builder_ask", "payload": {"relay_id": "r1", "bridge_url": "https://b/1",
                                            "inputs": [{"id": "ask_0", "label": "Which channel?"}]}},
        {"kind": "builder_result", "payload": {"relay_id": "r2", "summary": "Done."}},
    ])
    assert "[ask_0] Which channel?" in note and "https://b/1" in note and "Done." in note
    assert keys == [("builder_decision", "p1"), ("builder_ask", "r1"), ("builder_result", "r2")]
