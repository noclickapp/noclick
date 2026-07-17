"""
Live integration tests for the Klaviyo node (private API key).

SKIPPED unless ``KLAVIYO_API_KEY`` (a pk_ private key) is set. A Klaviyo free
account grants full API access, so these exercise the read + light-write paths
live. Run with:
    KLAVIYO_API_KEY=pk_xxx pytest nodes/tests/test_klaviyo_node_integration.py -v
"""

import os
import time
import pytest

from nodes.klaviyo_node import (
    KlaviyoNode, KlaviyoNodeConfig, KlaviyoApiKeyCredential,
    KlaviyoGetAccountConfig, KlaviyoListMetricsConfig, KlaviyoListListsConfig,
    KlaviyoListSegmentsConfig, KlaviyoListFlowsConfig, KlaviyoListTemplatesConfig,
    KlaviyoCreateProfileConfig, KlaviyoCreateEventConfig, KlaviyoListCampaignsConfig,
)

API_KEY = os.environ.get("KLAVIYO_API_KEY")
pytestmark = pytest.mark.skipif(not API_KEY, reason="Set KLAVIYO_API_KEY to run live Klaviyo tests")


def _node(config):
    creds = KlaviyoApiKeyCredential(api_key=API_KEY)
    return KlaviyoNode(node_id="it", node_type="automation-klaviyo", node_data={},
                       config=KlaviyoNodeConfig(config=config, credentials=creds),
                       sio=None, sid=None, workflow_id="it", user_id="it")


@pytest.mark.asyncio
async def test_live_account():
    res = await _node(KlaviyoGetAccountConfig()).execute({})
    assert res["status"] == "success", res


@pytest.mark.asyncio
async def test_live_metrics():
    assert (await _node(KlaviyoListMetricsConfig()).execute({}))["status"] == "success"


@pytest.mark.asyncio
async def test_live_lists():
    assert (await _node(KlaviyoListListsConfig()).execute({}))["status"] == "success"


@pytest.mark.asyncio
async def test_live_segments():
    assert (await _node(KlaviyoListSegmentsConfig()).execute({}))["status"] == "success"


@pytest.mark.asyncio
async def test_live_flows():
    assert (await _node(KlaviyoListFlowsConfig()).execute({}))["status"] == "success"


@pytest.mark.asyncio
async def test_live_templates():
    assert (await _node(KlaviyoListTemplatesConfig()).execute({}))["status"] == "success"


@pytest.mark.asyncio
async def test_live_campaigns():
    assert (await _node(KlaviyoListCampaignsConfig(channel="email")).execute({}))["status"] == "success"


@pytest.mark.asyncio
async def test_live_create_profile_and_event():
    stamp = str(int(time.time()))
    p = await _node(KlaviyoCreateProfileConfig(email=f"it+{stamp}@noclick.dev", first_name="IT")).execute({})
    assert p["status"] == "success", p
    e = await _node(KlaviyoCreateEventConfig(metric_name="NoClick IT Test", email=f"it+{stamp}@noclick.dev", value="1")).execute({})
    assert e["status"] == "success", e
