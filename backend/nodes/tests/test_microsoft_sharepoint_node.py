"""SharePoint Graph request contracts and resource-path safety."""

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from nodes.microsoft_sharepoint_node import (
    CreateItem,
    GetRootSite,
    ListFiles,
    ListItems,
    SharePointNode,
    SharePointNodeConfig,
    SharePointOAuthCredential,
    UploadTextFile,
)


def make_node(config):
    return SharePointNode(
        node_id="sharepoint-test", node_type="automation-microsoft-sharepoint", node_data={},
        config=SharePointNodeConfig(
            config=config,
            credentials=SharePointOAuthCredential(
                access_token="test-token", refresh_token="refresh", expires_at="2099-01-01T00:00:00Z",
                email="tester@example.com",
            ),
        ),
        sio=None, sid=None, workflow_id="workflow-test",
    )


@pytest.mark.asyncio
async def test_root_site_can_prove_oauth_connection(respx_mock):
    route = respx_mock.get("https://graph.microsoft.com/v1.0/sites/root").mock(
        return_value=httpx.Response(200, json={"id": "tenant,site", "name": "Team Home"})
    )
    node = make_node(GetRootSite())
    with patch.object(node, "_token", new=AsyncMock(return_value="test-token")):
        result = await node.execute({})
    assert route.called
    assert result["name"] == "Team Home"


@pytest.mark.asyncio
async def test_list_items_expands_columns_and_caps_result_count(respx_mock):
    route = respx_mock.get("https://graph.microsoft.com/v1.0/sites/site/lists/list/items").mock(
        return_value=httpx.Response(200, json={"value": [{"fields": {"Title": "Alpha"}}]})
    )
    node = make_node(ListItems(site_id="site", list_id="list", top=10))
    with patch.object(node, "_token", new=AsyncMock(return_value="test-token")):
        result = await node.execute({})
    assert result["value"][0]["fields"]["Title"] == "Alpha"
    assert route.calls[0].request.url.params["$expand"] == "fields"
    assert route.calls[0].request.url.params["$top"] == "10"


@pytest.mark.asyncio
async def test_create_item_uses_fields_envelope_and_does_not_log_token(respx_mock):
    route = respx_mock.post("https://graph.microsoft.com/v1.0/sites/site/lists/list/items").mock(
        return_value=httpx.Response(201, json={"id": "12", "fields": {"Title": "Alpha"}})
    )
    node = make_node(CreateItem(site_id="site", list_id="list", fields={"Title": "Alpha"}))
    with patch.object(node, "_token", new=AsyncMock(return_value="test-token")):
        result = await node.execute({})
    assert result["id"] == "12"
    assert route.calls[0].request.content == b'{"fields":{"Title":"Alpha"}}'
    assert route.calls[0].request.headers["Authorization"] == "Bearer test-token"


@pytest.mark.asyncio
async def test_upload_rejects_path_traversal_before_request():
    node = make_node(UploadTextFile(drive_id="drive", file_path="../secret.txt", content="data"))
    with patch.object(node, "_token", new=AsyncMock(return_value="test-token")), patch.object(node, "_request", new=AsyncMock()) as request:
        with pytest.raises(ValueError, match="within the library"):
            await node.execute({})
    request.assert_not_called()


@pytest.mark.asyncio
async def test_document_library_uses_graph_drive_path(respx_mock):
    route = respx_mock.get("https://graph.microsoft.com/v1.0/drives/drive/root/children").mock(
        return_value=httpx.Response(200, json={"value": [{
            "name": "notes.txt", "@microsoft.graph.downloadUrl": "https://temporary.example/file",
        }]})
    )
    node = make_node(ListFiles(drive_id="drive"))
    with patch.object(node, "_token", new=AsyncMock(return_value="test-token")):
        result = await node.execute({})
    assert route.called
    assert result["value"][0]["name"] == "notes.txt"
    assert "@microsoft.graph.downloadUrl" not in result["value"][0]


@pytest.mark.asyncio
async def test_graph_permission_failure_is_actionable_without_echoing_token(respx_mock):
    respx_mock.get("https://graph.microsoft.com/v1.0/sites/root").mock(
        return_value=httpx.Response(403, json={"error": {"message": "Insufficient privileges"}})
    )
    node = make_node(GetRootSite())
    with patch.object(node, "_token", new=AsyncMock(return_value="test-token")):
        with pytest.raises(ValueError, match="SharePoint request failed \\(403\\): Insufficient privileges") as error:
            await node.execute({})
    assert "test-token" not in str(error.value)


@pytest.mark.asyncio
async def test_token_uses_staging_microsoft_refresh_and_updates_model():
    node = make_node(GetRootSite())
    credential = node.config.credentials

    async def freshen(**kwargs):
        from nodes.oauth.microsoft_oauth import refresh_access_token
        assert kwargs["refresh"] is refresh_access_token
        assert kwargs["provider"] == "microsoft"
        assert kwargs["caller_path"] == "execute"
        kwargs["credential"].update(access_token="renewed", refresh_token="rotated", expires_at="2100-01-01T00:00:00Z")
        return "renewed"

    with patch("nodes.microsoft_sharepoint_node.ensure_fresh_oauth_token", side_effect=freshen):
        assert await node._token(credential) == "renewed"
    assert credential.access_token == "renewed"
    assert credential.refresh_token == "rotated"
    assert credential.expires_at == "2100-01-01T00:00:00Z"


@pytest.mark.asyncio
async def test_credential_load_uses_staging_microsoft_refresh():
    from nodes.oauth.microsoft_oauth import refresh_access_token
    data = make_node(GetRootSite()).config.credentials.model_dump()
    with patch("nodes.microsoft_sharepoint_node.freshen_oauth_credential", new=AsyncMock(return_value=data)) as freshen:
        assert await SharePointNode.freshen_credential(data, user_id="user", credential_id="credential") == data
    assert freshen.call_args.kwargs["refresh"] is refresh_access_token
    assert freshen.call_args.kwargs["provider"] == "microsoft"
