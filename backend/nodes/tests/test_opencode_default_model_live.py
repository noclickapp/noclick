"""NoClick's default OpenCode model must be one OpenCode runs today.

OpenCode Zen rotates its free models out, and every new OpenCode agent starts
on the default: when it went, each of those agents failed with an HTTP 500.
Run daily by the node integration lane, against the live Zen gateway and
models.dev, through the same pre-flight a turn runs.
"""

import pytest

from nodes.agent.config._cli_models_loader import harness_default_model
from nodes.agent.config.harness_model_lists import opencode_model_refusal
from utils.opencode_zen import fetch_models_dev, get_zen_servable_ids

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_default_opencode_model_is_offered_with_tools():
    default = harness_default_model("opencode")
    tier, _, model_id = default.partition("/")
    # The pre-flight judges nothing when it can't read a catalog, so read both first.
    catalog = await fetch_models_dev()
    servable = await get_zen_servable_ids(tier)
    assert servable, f"OpenCode Zen's {tier} model list could not be read"

    refusal = await opencode_model_refusal(default, catalog_is_the_cli_list=True)
    assert refusal is None, f"{refusal} Change default_model in backend/nodes/agent/config/_cli_models.json."
    assert catalog[tier]["models"][model_id].get("tool_call"), f"{default} doesn't take tool calls"
