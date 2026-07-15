"""
Live integration tests for the BambooHR node (API-key auth).

These hit the real BambooHR API and are SKIPPED unless both env vars are set:
    BAMBOOHR_SUBDOMAIN   your company subdomain (the text before .bamboohr.com)
    BAMBOOHR_API_KEY     an API key from BambooHR (name menu -> API Keys)

A BambooHR free trial provisions a real subdomain + API key that exercises
every read path here. Run with:
    BAMBOOHR_SUBDOMAIN=acme BAMBOOHR_API_KEY=xxxx pytest nodes/tests/test_bamboohr_node_integration.py -v
"""

import os
import pytest

from nodes.bamboohr_node import (
    BambooHRNode,
    BambooHRNodeConfig,
    BambooHRApiKeyCredential,
    BambooGetDirectoryConfig,
    BambooGetEmployeeConfig,
    BambooListTimeOffTypesConfig,
    BambooListFieldsConfig,
    BambooListTabularFieldsConfig,
    BambooWhosOutConfig,
    BambooListDatasetsConfig,
    BambooGetAccountConfig,
    BambooListWebhooksConfig,
)

SUBDOMAIN = os.environ.get("BAMBOOHR_SUBDOMAIN")
API_KEY = os.environ.get("BAMBOOHR_API_KEY")

pytestmark = pytest.mark.skipif(
    not (SUBDOMAIN and API_KEY),
    reason="Set BAMBOOHR_SUBDOMAIN and BAMBOOHR_API_KEY to run live BambooHR tests",
)


def _node(config):
    creds = BambooHRApiKeyCredential(subdomain=SUBDOMAIN, api_key=API_KEY)
    return BambooHRNode(
        node_id="it-bamboohr", node_type="automation-bamboohr", node_data={},
        config=BambooHRNodeConfig(config=config, credentials=creds),
        sio=None, sid=None, workflow_id="it-wf", user_id="it-user",
    )


@pytest.mark.asyncio
async def test_live_employee_directory():
    res = await _node(BambooGetDirectoryConfig()).execute({})
    assert res["status"] == "success", res
    assert "employees" in res["data"]


@pytest.mark.asyncio
async def test_live_get_me():
    # Employee id 0 = the API-key owner.
    res = await _node(BambooGetEmployeeConfig(employee_id="0", fields="firstName,lastName,workEmail")).execute({})
    assert res["status"] == "success", res


@pytest.mark.asyncio
async def test_live_time_off_types():
    res = await _node(BambooListTimeOffTypesConfig()).execute({})
    assert res["status"] == "success", res


@pytest.mark.asyncio
async def test_live_list_fields():
    res = await _node(BambooListFieldsConfig()).execute({})
    assert res["status"] == "success", res


@pytest.mark.asyncio
async def test_live_whos_out():
    res = await _node(BambooWhosOutConfig()).execute({})
    assert res["status"] == "success", res


@pytest.mark.asyncio
async def test_live_list_tabular_fields():
    res = await _node(BambooListTabularFieldsConfig()).execute({})
    assert res["status"] == "success", res


@pytest.mark.asyncio
async def test_live_list_datasets():
    res = await _node(BambooListDatasetsConfig()).execute({})
    assert res["status"] == "success", res


@pytest.mark.asyncio
async def test_live_get_account():
    res = await _node(BambooGetAccountConfig()).execute({})
    assert res["status"] == "success", res
    assert res["data"].get("domain") == "noclick" or res["data"].get("name")


@pytest.mark.asyncio
async def test_live_list_webhooks():
    res = await _node(BambooListWebhooksConfig()).execute({})
    assert res["status"] == "success", res
