"""
Live integration tests for the Basedash node (API key).

SKIPPED unless ``BASEDASH_API_KEY`` (a bd_key_ value) is set. Exercises read paths
plus a create→get→delete dashboard round-trip. Run with:
    BASEDASH_API_KEY=bd_key_xxx pytest nodes/tests/test_basedash_node_integration.py -v
"""

import os
import time
import pytest

from nodes.basedash_node import (
    BasedashNode, BasedashNodeConfig, BasedashApiKeyCredential,
    BDListOrganizationsConfig, BDGetOrganizationConfig, BDListDashboardsConfig,
    BDCreateDashboardConfig, BDGetDashboardConfig, BDDeleteDashboardConfig,
    BDListDataSourcesConfig, BDListMembersConfig,
)

API_KEY = os.environ.get("BASEDASH_API_KEY")
pytestmark = pytest.mark.skipif(not API_KEY, reason="Set BASEDASH_API_KEY to run live Basedash tests")


def _node(config):
    return BasedashNode(node_id="it", node_type="automation-basedash", node_data={},
                        config=BasedashNodeConfig(config=config, credentials=BasedashApiKeyCredential(api_key=API_KEY)),
                        sio=None, sid=None, workflow_id="it", user_id="it")


async def _first_org_id():
    res = await _node(BDListOrganizationsConfig()).execute({})
    assert res["status"] == "success", res
    return (res["data"] or [{}])[0].get("id")


@pytest.mark.asyncio
async def test_live_list_organizations():
    assert (await _node(BDListOrganizationsConfig()).execute({}))["status"] == "success"


@pytest.mark.asyncio
async def test_live_org_scoped_reads():
    oid = await _first_org_id()
    assert oid
    for cfg in (BDGetOrganizationConfig(organization_id=oid), BDListDashboardsConfig(organization_id=oid),
                BDListDataSourcesConfig(organization_id=oid), BDListMembersConfig(organization_id=oid)):
        assert (await _node(cfg).execute({}))["status"] == "success", cfg


@pytest.mark.asyncio
async def test_live_dashboard_roundtrip():
    oid = await _first_org_id()
    stamp = str(int(time.time()))
    created = await _node(BDCreateDashboardConfig(organization_id=oid, name=f"IT Dash {stamp}", body_json="{}")).execute({})
    assert created["status"] == "success", created
    did = created["data"]["id"]
    assert (await _node(BDGetDashboardConfig(organization_id=oid, dashboard_id=did)).execute({}))["status"] == "success"
    assert (await _node(BDDeleteDashboardConfig(organization_id=oid, dashboard_id=did)).execute({}))["status"] == "success"


@pytest.mark.asyncio
async def test_live_organization_dropdown():
    res = await BasedashNode.load_field_options("organization_id", {"api_key": API_KEY})
    assert isinstance(res.get("options"), list) and len(res["options"]) >= 1
