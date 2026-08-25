"""
Mock tests for the Basedash node (no live API calls).

Exercises: Bearer auth, the {data}/{error} envelope unwrap, pagination surfacing,
org-scoped path building, create/update bodies (+ body_json passthrough merge),
the PNG chart render (BinaryOutput), 204 handling, and dynamic dropdowns.
"""

import json
import pytest
from unittest.mock import Mock, patch

from nodes.basedash_node import (
    BasedashNode, BasedashNodeConfig, BasedashApiKeyCredential,
    BDListOrganizationsConfig, BDGetDashboardConfig, BDCreateChartConfig,
    BDCreateDefinitionConfig, BDInviteMemberConfig, BDGetChartImageConfig,
    BDUpdateDashboardConfig, BDDeleteDashboardConfig, BDCreateChatConfig,
    BDListDashboardsConfig,
)
from nodes.core.binary_output import BinaryOutput


@pytest.fixture
def creds():
    return BasedashApiKeyCredential(api_key="bd_key_test123")


def create_node(config):
    return BasedashNode(node_id="b", node_type="automation-basedash", node_data={}, config=config,
                        sio=Mock(), sid="s", workflow_id="w", user_id="u")


def create_mock_client(status_code=200, json_data=None, headers=None, content=b"{}"):
    resp = Mock()
    resp.status_code = status_code
    resp.text = ""
    resp.content = content
    resp.headers = headers if headers is not None else {"content-type": "application/json"}
    resp.json = lambda: (json_data if json_data is not None else {})
    mc = Mock(); mc.calls = []

    async def req(*a, **k):
        mc.calls.append(k); return resp
    mc.request = req
    async def aenter(self): return mc
    async def aexit(self, *a): return None
    mc.__aenter__ = aenter; mc.__aexit__ = aexit
    return mc


def last(mc):
    return mc.calls[-1]


async def _run(config, creds, mc):
    node = create_node(BasedashNodeConfig(config=config, credentials=creds))
    with patch("nodes.basedash_node.httpx.AsyncClient", return_value=mc):
        return await node.execute({})


class TestAuthAndEnvelope:
    @pytest.mark.asyncio
    async def test_bearer_auth_and_base_url(self, creds):
        mc = create_mock_client(200, {"data": [], "pagination": {"nextCursor": None, "hasMore": False}})
        await _run(BDListOrganizationsConfig(), creds, mc)
        call = last(mc)
        assert call["headers"]["Authorization"] == "Bearer bd_key_test123"
        assert call["url"] == "https://charts.basedash.com/api/public/organizations"

    @pytest.mark.asyncio
    async def test_unwraps_data_and_surfaces_pagination(self, creds):
        mc = create_mock_client(200, {"data": [{"id": "org_1", "name": "Acme"}], "pagination": {"nextCursor": "c2", "hasMore": True}})
        res = await _run(BDListOrganizationsConfig(), creds, mc)
        assert res["status"] == "success"
        assert res["data"] == [{"id": "org_1", "name": "Acme"}]  # unwrapped from {data}
        assert res["pagination"] == {"nextCursor": "c2", "hasMore": True}

    @pytest.mark.asyncio
    async def test_error_envelope_extracted(self, creds):
        mc = create_mock_client(404, {"error": {"title": "NotFound", "detail": "Audit logs require the Enterprise plan"}})
        res = await _run(BDGetDashboardConfig(organization_id="org_1", dashboard_id="d1"), creds, mc)
        assert res["status"] == "error"
        assert res["error"] == "Audit logs require the Enterprise plan"
        assert res["status_code"] == 404

    @pytest.mark.asyncio
    async def test_204_no_content(self, creds):
        mc = create_mock_client(204, None, headers={"content-type": "text/plain"}, content=b"")
        res = await _run(BDDeleteDashboardConfig(organization_id="org_1", dashboard_id="d1"), creds, mc)
        assert res["status"] == "success" and res["data"] == {"success": True}
        assert last(mc)["method"] == "DELETE"

    @pytest.mark.asyncio
    async def test_missing_credentials(self):
        node = create_node(BasedashNodeConfig(config=BDListOrganizationsConfig(), credentials=None))
        with pytest.raises(ValueError, match="Credentials are required"):
            await node.execute({})


class TestPathsAndBodies:
    @pytest.mark.asyncio
    async def test_org_scoped_path(self, creds):
        mc = create_mock_client(200, {"data": {"id": "d1"}})
        await _run(BDGetDashboardConfig(organization_id="org_9", dashboard_id="d1"), creds, mc)
        assert last(mc)["url"].endswith("/organizations/org_9/dashboards/d1")

    @pytest.mark.asyncio
    async def test_list_dashboards_pagination_params(self, creds):
        mc = create_mock_client(200, {"data": []})
        await _run(BDListDashboardsConfig(organization_id="org_9", limit="25", cursor="abc"), creds, mc)
        assert last(mc)["params"] == {"limit": "25", "cursor": "abc"}

    @pytest.mark.asyncio
    async def test_create_chart_body_merges_body_json(self, creds):
        mc = create_mock_client(201, {"data": {"id": "chart_1"}})
        await _run(BDCreateChartConfig(organization_id="org_1", dashboard_id="d1", name="Rev",
                                       chart_type="LINE", sql_query="select 1",
                                       body_json='{"yAxisProperty":"count","layout":{"x":0,"y":0,"width":6,"height":4}}'), creds, mc)
        body = last(mc)["json"]
        assert body["dashboardId"] == "d1" and body["name"] == "Rev"
        assert body["chartType"] == "LINE" and body["sqlQuery"] == "select 1"
        assert body["yAxisProperty"] == "count" and body["layout"]["width"] == 6  # body_json merged

    @pytest.mark.asyncio
    async def test_create_definition_body(self, creds):
        mc = create_mock_client(201, {"data": {"id": "def_1"}})
        await _run(BDCreateDefinitionConfig(organization_id="org_1", name="Active", sql_query="select 1", database_connection_id="ds_1", body_json="{}"), creds, mc)
        body = last(mc)["json"]
        assert body == {"name": "Active", "sqlQuery": "select 1", "databaseConnectionId": "ds_1"}

    @pytest.mark.asyncio
    async def test_invite_member_body(self, creds):
        mc = create_mock_client(201, {"data": {"id": "member_1"}})
        await _run(BDInviteMemberConfig(organization_id="org_1", email="a@b.com", role="ADMIN"), creds, mc)
        call = last(mc)
        assert call["method"] == "POST" and call["url"].endswith("/organizations/org_1/members")
        assert call["json"] == {"email": "a@b.com", "role": "ADMIN"}

    @pytest.mark.asyncio
    async def test_update_dashboard_patches_body_json(self, creds):
        mc = create_mock_client(200, {"data": {"id": "d1"}})
        await _run(BDUpdateDashboardConfig(organization_id="org_1", dashboard_id="d1", body_json='{"name":"New"}'), creds, mc)
        assert last(mc)["method"] == "PATCH" and last(mc)["json"] == {"name": "New"}

    @pytest.mark.asyncio
    async def test_invalid_body_json_raises(self, creds):
        node = create_node(BasedashNodeConfig(config=BDUpdateDashboardConfig(organization_id="o", dashboard_id="d", body_json="{not json"), credentials=creds))
        with pytest.raises(ValueError, match="must be valid JSON"):
            await node.execute({})

    @pytest.mark.asyncio
    async def test_create_chat_wait_param(self, creds):
        mc = create_mock_client(200, {"data": {"chat": {"id": "chat_1"}}})
        await _run(BDCreateChatConfig(organization_id="org_1", message="hi", wait="true", body_json="{}"), creds, mc)
        call = last(mc)
        assert call["params"] == {"wait": "true"}
        assert call["json"] == {"message": "hi"}


class TestChartImage:
    @pytest.mark.asyncio
    async def test_chart_image_returns_binary_output(self, creds):
        png = b"\x89PNG\r\n\x1a\n" + b"fake"
        mc = create_mock_client(200, None, headers={"content-type": "image/png"}, content=png)
        res = await _run(BDGetChartImageConfig(organization_id="org_1", chart_id="chart_1"), creds, mc)
        assert res["status"] == "success"
        assert isinstance(res["data"], BinaryOutput)
        assert res["data"].data == png and res["data"].content_type == "image/png"


class TestDropdowns:
    @pytest.mark.asyncio
    async def test_organization_dropdown(self, creds):
        mc = create_mock_client(200, {"data": [{"id": "org_1", "name": "Acme"}], "pagination": {"nextCursor": None}})
        with patch("nodes.basedash_node.httpx.AsyncClient", return_value=mc):
            res = await BasedashNode.load_field_options("organization_id", {"api_key": "bd_key_x"})
        assert res["options"] == [{"value": "org_1", "label": "Acme"}]

    @pytest.mark.asyncio
    async def test_dashboard_dropdown_requires_org_context(self, creds):
        # without organization_id in context -> empty (can't resolve the org-scoped path)
        res = await BasedashNode.load_field_options("dashboard_id", {"api_key": "bd_key_x"})
        assert res == {"options": []}

    @pytest.mark.asyncio
    async def test_dashboard_dropdown_with_org(self, creds):
        mc = create_mock_client(200, {"data": [{"id": "d1", "name": "Sales"}], "pagination": {"nextCursor": None}})
        with patch("nodes.basedash_node.httpx.AsyncClient", return_value=mc):
            res = await BasedashNode.load_field_options("dashboard_id", {"api_key": "bd_key_x"}, context={"organization_id": "org_1"})
        assert res["options"] == [{"value": "d1", "label": "Sales"}]
        assert last(mc)["url"].endswith("/organizations/org_1/dashboards")

    @pytest.mark.asyncio
    async def test_dropdown_no_credential(self):
        assert await BasedashNode.load_field_options("organization_id", {}) == {"options": []}
