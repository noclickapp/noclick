"""
Mock tests for the Loops REST API node.

Exercises every operation with mocked HTTP responses (no live API calls):
- Account: test API key, list dedicated sending IPs
- Contacts: create, update, find, delete, suppression get/remove, properties create/list
- Mailing lists: list
- Events: send
- Transactional: send, list, get, create, update, draft, publish
- Transactional groups: list, get, create, update
- Campaigns: list, create, get, update
- Campaign groups: list, get, create, update
- Email messages: get, update, preview
- Design: list/get themes, list/get components
- Audience: list/get segments
- Workflows (alpha): list, get, get node
- Uploads: create image upload (full 3-step), complete upload
- Trigger: on_loops_event passthrough and event-type filtering
- Error handling: API errors, missing credentials
- Dynamic options: mailing-list & transactional dropdowns
"""

import pytest
from unittest.mock import Mock, AsyncMock, MagicMock, patch

from nodes.loops_node import (
    LoopsNode,
    LoopsNodeConfig,
    LoopsAPIKeyCredential,
    LoopsWebhookTriggerConfig,
    LoopsTestApiKeyConfig,
    LoopsCreateContactConfig,
    LoopsUpdateContactConfig,
    LoopsFindContactConfig,
    LoopsDeleteContactConfig,
    LoopsGetSuppressionConfig,
    LoopsRemoveSuppressionConfig,
    LoopsCreateContactPropertyConfig,
    LoopsListContactPropertiesConfig,
    LoopsListMailingListsConfig,
    LoopsSendEventConfig,
    LoopsSendTransactionalConfig,
    LoopsListTransactionalConfig,
    LoopsGetTransactionalConfig,
    LoopsCreateTransactionalEmailConfig,
    LoopsUpdateTransactionalEmailConfig,
    LoopsEnsureTransactionalEmailDraftConfig,
    LoopsPublishTransactionalEmailConfig,
    LoopsListCampaignsConfig,
    LoopsCreateCampaignConfig,
    LoopsGetCampaignConfig,
    LoopsUpdateCampaignConfig,
    LoopsListCampaignGroupsConfig,
    LoopsGetCampaignGroupConfig,
    LoopsCreateCampaignGroupConfig,
    LoopsUpdateCampaignGroupConfig,
    LoopsListTransactionalGroupsConfig,
    LoopsGetTransactionalGroupConfig,
    LoopsCreateTransactionalGroupConfig,
    LoopsUpdateTransactionalGroupConfig,
    LoopsGetEmailMessageConfig,
    LoopsUpdateEmailMessageConfig,
    LoopsSendEmailMessagePreviewConfig,
    LoopsListThemesConfig,
    LoopsGetThemeConfig,
    LoopsListComponentsConfig,
    LoopsGetComponentConfig,
    LoopsListAudienceSegmentsConfig,
    LoopsGetAudienceSegmentConfig,
    LoopsCreateUploadConfig,
    LoopsCompleteUploadConfig,
    LoopsListWorkflowsConfig,
    LoopsGetWorkflowConfig,
    LoopsGetWorkflowNodeConfig,
    LoopsListSendingIpsConfig,
)


@pytest.fixture
def api_key_credentials():
    return LoopsAPIKeyCredential(api_key="loops_test_key_12345")


def create_loops_node(config):
    return LoopsNode(
        node_id="test-loops-node",
        node_type="automation-loops",
        node_data={},
        config=config,
        sio=Mock(),
        sid="test-sid",
        workflow_id="test-workflow",
        user_id="test-user",
    )


def create_mock_response(status_code=200, json_data=None):
    mock_response = Mock()
    mock_response.status_code = status_code
    mock_response.text = ""
    mock_response.json = lambda: (json_data if json_data is not None else {})
    return mock_response


def create_mock_client(status_code=200, json_data=None):
    """Mock httpx.AsyncClient whose .request() returns the mock response and
    which works as an async context manager."""
    mock_response = create_mock_response(status_code, json_data)
    mock_client = Mock()

    async def async_request(*args, **kwargs):
        return mock_response

    mock_client.request = async_request

    async def aenter(self):
        return mock_client

    async def aexit(self, *args):
        return None

    mock_client.__aenter__ = aenter
    mock_client.__aexit__ = aexit
    return mock_client


class TestLoopsAccountMock:
    @pytest.mark.asyncio
    async def test_test_api_key(self, api_key_credentials):
        config = LoopsNodeConfig(config=LoopsTestApiKeyConfig(), credentials=api_key_credentials)
        node = create_loops_node(config)
        mock_client = create_mock_client(200, {"success": True, "teamName": "Acme"})
        with patch("nodes.loops_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "test_api_key"
        assert result["data"]["teamName"] == "Acme"

    @pytest.mark.asyncio
    async def test_list_sending_ips(self, api_key_credentials):
        config = LoopsNodeConfig(config=LoopsListSendingIpsConfig(), credentials=api_key_credentials)
        node = create_loops_node(config)
        mock_client = create_mock_client(200, {"ips": ["1.2.3.4"]})
        with patch("nodes.loops_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_sending_ips"


class TestLoopsContactsMock:
    @pytest.mark.asyncio
    async def test_create_contact(self, api_key_credentials):
        config = LoopsNodeConfig(
            config=LoopsCreateContactConfig(
                email="ada@example.com",
                first_name="Ada",
                mailing_list_id="list_1",
                properties='{"plan": "pro"}',
            ),
            credentials=api_key_credentials,
        )
        node = create_loops_node(config)
        mock_client = create_mock_client(200, {"success": True, "id": "ct_1"})
        with patch("nodes.loops_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_contact"
        assert result["data"]["id"] == "ct_1"

    @pytest.mark.asyncio
    async def test_update_contact(self, api_key_credentials):
        config = LoopsNodeConfig(
            config=LoopsUpdateContactConfig(email="ada@example.com", first_name="Ada B"),
            credentials=api_key_credentials,
        )
        node = create_loops_node(config)
        mock_client = create_mock_client(200, {"success": True, "id": "ct_1"})
        with patch("nodes.loops_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "update_contact"

    @pytest.mark.asyncio
    async def test_find_contact(self, api_key_credentials):
        config = LoopsNodeConfig(
            config=LoopsFindContactConfig(email="ada@example.com"),
            credentials=api_key_credentials,
        )
        node = create_loops_node(config)
        mock_client = create_mock_client(200, [{"id": "ct_1", "email": "ada@example.com"}])
        with patch("nodes.loops_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "find_contact"
        assert result["data"][0]["email"] == "ada@example.com"

    @pytest.mark.asyncio
    async def test_delete_contact(self, api_key_credentials):
        config = LoopsNodeConfig(
            config=LoopsDeleteContactConfig(email="ada@example.com"),
            credentials=api_key_credentials,
        )
        node = create_loops_node(config)
        mock_client = create_mock_client(200, {"success": True})
        with patch("nodes.loops_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "delete_contact"

    @pytest.mark.asyncio
    async def test_get_suppression(self, api_key_credentials):
        config = LoopsNodeConfig(
            config=LoopsGetSuppressionConfig(email="ada@example.com"),
            credentials=api_key_credentials,
        )
        node = create_loops_node(config)
        mock_client = create_mock_client(200, {"suppressed": False, "removalQuota": 5})
        with patch("nodes.loops_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_suppression"
        assert result["data"]["suppressed"] is False

    @pytest.mark.asyncio
    async def test_remove_suppression(self, api_key_credentials):
        config = LoopsNodeConfig(
            config=LoopsRemoveSuppressionConfig(email="ada@example.com"),
            credentials=api_key_credentials,
        )
        node = create_loops_node(config)
        mock_client = create_mock_client(200, {"success": True})
        with patch("nodes.loops_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "remove_suppression"

    @pytest.mark.asyncio
    async def test_create_contact_property(self, api_key_credentials):
        config = LoopsNodeConfig(
            config=LoopsCreateContactPropertyConfig(name="plan", property_type="string"),
            credentials=api_key_credentials,
        )
        node = create_loops_node(config)
        mock_client = create_mock_client(200, {"success": True})
        with patch("nodes.loops_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_contact_property"

    @pytest.mark.asyncio
    async def test_list_contact_properties(self, api_key_credentials):
        config = LoopsNodeConfig(
            config=LoopsListContactPropertiesConfig(),
            credentials=api_key_credentials,
        )
        node = create_loops_node(config)
        mock_client = create_mock_client(200, [{"key": "plan", "type": "string"}])
        with patch("nodes.loops_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_contact_properties"


class TestLoopsMailingListsMock:
    @pytest.mark.asyncio
    async def test_list_mailing_lists(self, api_key_credentials):
        config = LoopsNodeConfig(
            config=LoopsListMailingListsConfig(), credentials=api_key_credentials
        )
        node = create_loops_node(config)
        mock_client = create_mock_client(200, [{"id": "list_1", "name": "Newsletter"}])
        with patch("nodes.loops_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_mailing_lists"
        assert result["data"][0]["id"] == "list_1"


class TestLoopsEventsMock:
    @pytest.mark.asyncio
    async def test_send_event(self, api_key_credentials):
        config = LoopsNodeConfig(
            config=LoopsSendEventConfig(
                event_name="trial_started",
                email="ada@example.com",
                event_properties='{"source": "web"}',
            ),
            credentials=api_key_credentials,
        )
        node = create_loops_node(config)
        mock_client = create_mock_client(200, {"success": True})
        with patch("nodes.loops_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "send_event"


class TestLoopsTransactionalMock:
    @pytest.mark.asyncio
    async def test_send_transactional(self, api_key_credentials):
        config = LoopsNodeConfig(
            config=LoopsSendTransactionalConfig(
                transactional_id="tx_1",
                email="ada@example.com",
                data_variables='{"name": "Ada"}',
            ),
            credentials=api_key_credentials,
        )
        node = create_loops_node(config)
        mock_client = create_mock_client(200, {"success": True})
        with patch("nodes.loops_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "send_transactional"

    @pytest.mark.asyncio
    async def test_list_transactional(self, api_key_credentials):
        config = LoopsNodeConfig(
            config=LoopsListTransactionalConfig(per_page="10"), credentials=api_key_credentials
        )
        node = create_loops_node(config)
        mock_client = create_mock_client(200, {"data": [{"id": "tx_1", "name": "Welcome"}]})
        with patch("nodes.loops_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_transactional"

    @pytest.mark.asyncio
    async def test_get_transactional(self, api_key_credentials):
        config = LoopsNodeConfig(
            config=LoopsGetTransactionalConfig(transactional_id="tx_1"),
            credentials=api_key_credentials,
        )
        node = create_loops_node(config)
        mock_client = create_mock_client(200, {"id": "tx_1", "name": "Welcome"})
        with patch("nodes.loops_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_transactional"
        assert result["data"]["id"] == "tx_1"


class TestLoopsCampaignsMock:
    @pytest.mark.asyncio
    async def test_list_campaigns(self, api_key_credentials):
        config = LoopsNodeConfig(
            config=LoopsListCampaignsConfig(), credentials=api_key_credentials
        )
        node = create_loops_node(config)
        mock_client = create_mock_client(200, {"data": [{"id": "cm_1"}]})
        with patch("nodes.loops_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_campaigns"

    @pytest.mark.asyncio
    async def test_create_campaign(self, api_key_credentials):
        config = LoopsNodeConfig(
            config=LoopsCreateCampaignConfig(name="Launch", subject="Hi"),
            credentials=api_key_credentials,
        )
        node = create_loops_node(config)
        mock_client = create_mock_client(200, {"id": "cm_new"})
        with patch("nodes.loops_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_campaign"
        assert result["data"]["id"] == "cm_new"

    @pytest.mark.asyncio
    async def test_get_campaign(self, api_key_credentials):
        config = LoopsNodeConfig(
            config=LoopsGetCampaignConfig(campaign_id="cm_1"), credentials=api_key_credentials
        )
        node = create_loops_node(config)
        mock_client = create_mock_client(200, {"id": "cm_1", "name": "Launch"})
        with patch("nodes.loops_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_campaign"

    @pytest.mark.asyncio
    async def test_update_campaign(self, api_key_credentials):
        config = LoopsNodeConfig(
            config=LoopsUpdateCampaignConfig(campaign_id="cm_1", name="Launch v2"),
            credentials=api_key_credentials,
        )
        node = create_loops_node(config)
        mock_client = create_mock_client(200, {"id": "cm_1", "name": "Launch v2"})
        with patch("nodes.loops_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "update_campaign"


class TestLoopsEmailMessagesMock:
    @pytest.mark.asyncio
    async def test_get_email_message(self, api_key_credentials):
        config = LoopsNodeConfig(
            config=LoopsGetEmailMessageConfig(email_message_id="em_1"),
            credentials=api_key_credentials,
        )
        node = create_loops_node(config)
        mock_client = create_mock_client(200, {"id": "em_1", "subject": "Hi"})
        with patch("nodes.loops_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_email_message"
        assert result["data"]["id"] == "em_1"

    @pytest.mark.asyncio
    async def test_update_email_message(self, api_key_credentials):
        config = LoopsNodeConfig(
            config=LoopsUpdateEmailMessageConfig(email_message_id="em_1", subject="New subject"),
            credentials=api_key_credentials,
        )
        node = create_loops_node(config)
        mock_client = create_mock_client(200, {"id": "em_1", "subject": "New subject"})
        with patch("nodes.loops_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "update_email_message"


class TestLoopsDesignAndAudienceMock:
    @pytest.mark.asyncio
    async def test_list_themes(self, api_key_credentials):
        config = LoopsNodeConfig(config=LoopsListThemesConfig(), credentials=api_key_credentials)
        node = create_loops_node(config)
        mock_client = create_mock_client(200, {"data": [{"id": "th_1"}]})
        with patch("nodes.loops_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_themes"

    @pytest.mark.asyncio
    async def test_list_components(self, api_key_credentials):
        config = LoopsNodeConfig(config=LoopsListComponentsConfig(), credentials=api_key_credentials)
        node = create_loops_node(config)
        mock_client = create_mock_client(200, {"data": [{"id": "co_1"}]})
        with patch("nodes.loops_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_components"

    @pytest.mark.asyncio
    async def test_list_audience_segments(self, api_key_credentials):
        config = LoopsNodeConfig(
            config=LoopsListAudienceSegmentsConfig(), credentials=api_key_credentials
        )
        node = create_loops_node(config)
        mock_client = create_mock_client(200, {"data": [{"id": "seg_1"}]})
        with patch("nodes.loops_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_audience_segments"


class TestLoopsUploadsMock:
    @pytest.mark.asyncio
    async def test_create_upload(self, api_key_credentials):
        """Full 3-step upload: DB lookup → R2 download → Loops POST → PUT → complete."""
        config = LoopsNodeConfig(
            config=LoopsCreateUploadConfig(image="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"),
            credentials=api_key_credentials,
        )
        node = create_loops_node(config)

        resolved_media = MagicMock(
            data=b"fake-image-bytes",
            mime_type="image/png",
            filename="logo.png",
        )

        call_count = [0]

        def make_side_effect_client():
            mock_client = Mock()

            async def async_request(method, url, **kwargs):
                call_count[0] += 1
                resp = Mock()
                resp.text = ""
                if method == "GET":
                    # R2 download
                    resp.status_code = 200
                    resp.content = b"fake-image-bytes"
                elif method == "POST" and "/v1/uploads" in url and "complete" not in url:
                    resp.status_code = 200
                    resp.json = lambda: {"emailAssetId": "upload-123", "presignedUrl": "https://s3.example/presigned"}
                elif method == "PUT":
                    resp.status_code = 200
                    resp.content = b""
                elif method == "POST" and "complete" in url:
                    resp.status_code = 200
                    resp.json = lambda: {"publicUrl": "https://cdn.loops.so/logo.png", "id": "upload-123"}
                else:
                    resp.status_code = 200
                    resp.json = lambda: {}
                return resp

            mock_client.request = async_request

            async def async_get(url, **kwargs):
                resp = Mock()
                resp.status_code = 200
                resp.content = b"fake-image-bytes"
                resp.raise_for_status = Mock()
                return resp

            mock_client.get = async_get

            async def async_put(url, **kwargs):
                resp = Mock()
                resp.status_code = 200
                resp.content = b""
                return resp

            mock_client.put = async_put

            async def aenter(self):
                return mock_client

            async def aexit(self, *args):
                return None

            mock_client.__aenter__ = aenter
            mock_client.__aexit__ = aexit
            return mock_client

        with (
            patch(
                "nodes.loops_node.resolve_media_input",
                new=AsyncMock(return_value=resolved_media),
            ) as mock_resolve,
            patch("nodes.loops_node.httpx.AsyncClient", side_effect=lambda **kw: make_side_effect_client()),
            patch(
                "nodes.loops_node.guarded_async_client",
                side_effect=lambda **kw: make_side_effect_client(),
            ),
        ):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_upload"
        assert result["asset_id"] == "upload-123"
        mock_resolve.assert_awaited_once_with(
            "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            workflow_id="test-workflow",
            default_mime="image/jpeg",
        )

    @pytest.mark.asyncio
    async def test_create_upload_requires_image(self, api_key_credentials):
        config = LoopsNodeConfig(
            config=LoopsCreateUploadConfig(image=None),
            credentials=api_key_credentials,
        )
        node = create_loops_node(config)
        with pytest.raises(ValueError, match="Image is required"):
            await node.execute({})

    @pytest.mark.asyncio
    async def test_complete_upload(self, api_key_credentials):
        config = LoopsNodeConfig(
            config=LoopsCompleteUploadConfig(upload_id="upload-123"),
            credentials=api_key_credentials,
        )
        node = create_loops_node(config)
        mock_client = create_mock_client(200, {"publicUrl": "https://cdn.loops.so/logo.png"})
        with patch("nodes.loops_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "complete_upload"


class TestLoopsTransactionalCRUDMock:
    @pytest.mark.asyncio
    async def test_create_transactional_email(self, api_key_credentials):
        config = LoopsNodeConfig(
            config=LoopsCreateTransactionalEmailConfig(name="Welcome Email", subject="Welcome!"),
            credentials=api_key_credentials,
        )
        node = create_loops_node(config)
        mock_client = create_mock_client(200, {"id": "te-1", "name": "Welcome Email"})
        with patch("nodes.loops_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_transactional_email"

    @pytest.mark.asyncio
    async def test_update_transactional_email(self, api_key_credentials):
        config = LoopsNodeConfig(
            config=LoopsUpdateTransactionalEmailConfig(transactional_id="te-1", subject="Updated!"),
            credentials=api_key_credentials,
        )
        node = create_loops_node(config)
        mock_client = create_mock_client(200, {"id": "te-1", "subject": "Updated!"})
        with patch("nodes.loops_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "update_transactional_email"

    @pytest.mark.asyncio
    async def test_ensure_transactional_email_draft(self, api_key_credentials):
        config = LoopsNodeConfig(
            config=LoopsEnsureTransactionalEmailDraftConfig(transactional_id="te-1"),
            credentials=api_key_credentials,
        )
        node = create_loops_node(config)
        mock_client = create_mock_client(200, {"id": "te-1", "status": "draft"})
        with patch("nodes.loops_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "ensure_transactional_email_draft"

    @pytest.mark.asyncio
    async def test_publish_transactional_email(self, api_key_credentials):
        config = LoopsNodeConfig(
            config=LoopsPublishTransactionalEmailConfig(transactional_id="te-1"),
            credentials=api_key_credentials,
        )
        node = create_loops_node(config)
        mock_client = create_mock_client(200, {"id": "te-1", "status": "published"})
        with patch("nodes.loops_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "publish_transactional_email"


class TestLoopsCampaignGroupsMock:
    @pytest.mark.asyncio
    async def test_list_campaign_groups(self, api_key_credentials):
        config = LoopsNodeConfig(
            config=LoopsListCampaignGroupsConfig(), credentials=api_key_credentials,
        )
        node = create_loops_node(config)
        mock_client = create_mock_client(200, {"data": [{"id": "cg-1", "name": "Group A"}]})
        with patch("nodes.loops_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_campaign_groups"

    @pytest.mark.asyncio
    async def test_get_campaign_group(self, api_key_credentials):
        config = LoopsNodeConfig(
            config=LoopsGetCampaignGroupConfig(group_id="cg-1"), credentials=api_key_credentials,
        )
        node = create_loops_node(config)
        mock_client = create_mock_client(200, {"id": "cg-1", "name": "Group A"})
        with patch("nodes.loops_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_campaign_group"

    @pytest.mark.asyncio
    async def test_create_campaign_group(self, api_key_credentials):
        config = LoopsNodeConfig(
            config=LoopsCreateCampaignGroupConfig(name="New Group"), credentials=api_key_credentials,
        )
        node = create_loops_node(config)
        mock_client = create_mock_client(200, {"id": "cg-2", "name": "New Group"})
        with patch("nodes.loops_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_campaign_group"

    @pytest.mark.asyncio
    async def test_update_campaign_group(self, api_key_credentials):
        config = LoopsNodeConfig(
            config=LoopsUpdateCampaignGroupConfig(group_id="cg-1", name="Renamed"),
            credentials=api_key_credentials,
        )
        node = create_loops_node(config)
        mock_client = create_mock_client(200, {"id": "cg-1", "name": "Renamed"})
        with patch("nodes.loops_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "update_campaign_group"


class TestLoopsTransactionalGroupsMock:
    @pytest.mark.asyncio
    async def test_list_transactional_groups(self, api_key_credentials):
        config = LoopsNodeConfig(
            config=LoopsListTransactionalGroupsConfig(), credentials=api_key_credentials,
        )
        node = create_loops_node(config)
        mock_client = create_mock_client(200, {"data": [{"id": "tg-1", "name": "TG A"}]})
        with patch("nodes.loops_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_transactional_groups"

    @pytest.mark.asyncio
    async def test_get_transactional_group(self, api_key_credentials):
        config = LoopsNodeConfig(
            config=LoopsGetTransactionalGroupConfig(group_id="tg-1"), credentials=api_key_credentials,
        )
        node = create_loops_node(config)
        mock_client = create_mock_client(200, {"id": "tg-1", "name": "TG A"})
        with patch("nodes.loops_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_transactional_group"

    @pytest.mark.asyncio
    async def test_create_transactional_group(self, api_key_credentials):
        config = LoopsNodeConfig(
            config=LoopsCreateTransactionalGroupConfig(name="New TG"), credentials=api_key_credentials,
        )
        node = create_loops_node(config)
        mock_client = create_mock_client(200, {"id": "tg-2", "name": "New TG"})
        with patch("nodes.loops_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_transactional_group"

    @pytest.mark.asyncio
    async def test_update_transactional_group(self, api_key_credentials):
        config = LoopsNodeConfig(
            config=LoopsUpdateTransactionalGroupConfig(group_id="tg-1", name="Renamed TG"),
            credentials=api_key_credentials,
        )
        node = create_loops_node(config)
        mock_client = create_mock_client(200, {"id": "tg-1", "name": "Renamed TG"})
        with patch("nodes.loops_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "update_transactional_group"


class TestLoopsEmailMessagePreviewMock:
    @pytest.mark.asyncio
    async def test_send_email_message_preview(self, api_key_credentials):
        config = LoopsNodeConfig(
            config=LoopsSendEmailMessagePreviewConfig(
                email_message_id="em-1",
                emails='["preview@example.com"]',
                data_variables='{"name": "Ada"}',
            ),
            credentials=api_key_credentials,
        )
        node = create_loops_node(config)
        mock_client = create_mock_client(200, {"success": True})
        with patch("nodes.loops_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "send_email_message_preview"

    @pytest.mark.asyncio
    async def test_send_email_message_preview_invalid_json(self, api_key_credentials):
        config = LoopsNodeConfig(
            config=LoopsSendEmailMessagePreviewConfig(
                email_message_id="em-1",
                emails="not-json",
            ),
            credentials=api_key_credentials,
        )
        node = create_loops_node(config)
        with pytest.raises(ValueError):
            await node.execute({})


class TestLoopsDesignGetByIdMock:
    @pytest.mark.asyncio
    async def test_get_theme(self, api_key_credentials):
        config = LoopsNodeConfig(
            config=LoopsGetThemeConfig(theme_id="theme-1"), credentials=api_key_credentials,
        )
        node = create_loops_node(config)
        mock_client = create_mock_client(200, {"id": "theme-1", "name": "Default"})
        with patch("nodes.loops_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_theme"

    @pytest.mark.asyncio
    async def test_get_component(self, api_key_credentials):
        config = LoopsNodeConfig(
            config=LoopsGetComponentConfig(component_id="comp-1"), credentials=api_key_credentials,
        )
        node = create_loops_node(config)
        mock_client = create_mock_client(200, {"id": "comp-1", "name": "Header"})
        with patch("nodes.loops_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_component"

    @pytest.mark.asyncio
    async def test_get_audience_segment(self, api_key_credentials):
        config = LoopsNodeConfig(
            config=LoopsGetAudienceSegmentConfig(segment_id="seg-1"), credentials=api_key_credentials,
        )
        node = create_loops_node(config)
        mock_client = create_mock_client(200, {"id": "seg-1", "name": "Active Users"})
        with patch("nodes.loops_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_audience_segment"


class TestLoopsWorkflowsMock:
    @pytest.mark.asyncio
    async def test_list_workflows(self, api_key_credentials):
        config = LoopsNodeConfig(
            config=LoopsListWorkflowsConfig(), credentials=api_key_credentials,
        )
        node = create_loops_node(config)
        mock_client = create_mock_client(200, {"data": [{"id": "wf-1", "name": "Onboarding"}]})
        with patch("nodes.loops_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_workflows"

    @pytest.mark.asyncio
    async def test_get_workflow(self, api_key_credentials):
        config = LoopsNodeConfig(
            config=LoopsGetWorkflowConfig(workflow_id="wf-1"), credentials=api_key_credentials,
        )
        node = create_loops_node(config)
        mock_client = create_mock_client(200, {"id": "wf-1", "name": "Onboarding"})
        with patch("nodes.loops_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_workflow"

    @pytest.mark.asyncio
    async def test_get_workflow_node(self, api_key_credentials):
        config = LoopsNodeConfig(
            config=LoopsGetWorkflowNodeConfig(workflow_id="wf-1", node_id="node-1"),
            credentials=api_key_credentials,
        )
        node = create_loops_node(config)
        mock_client = create_mock_client(200, {"id": "node-1", "type": "email"})
        with patch("nodes.loops_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_workflow_node"


class TestLoopsErrorHandlingMock:
    @pytest.mark.asyncio
    async def test_api_error(self, api_key_credentials):
        config = LoopsNodeConfig(
            config=LoopsGetCampaignConfig(campaign_id="missing"), credentials=api_key_credentials
        )
        node = create_loops_node(config)
        mock_client = create_mock_client(404, {"message": "Campaign not found"})
        with patch("nodes.loops_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "error"
        assert result["status_code"] == 404
        assert "not found" in str(result["error"]).lower()

    @pytest.mark.asyncio
    async def test_missing_credentials(self):
        config = LoopsNodeConfig(config=LoopsTestApiKeyConfig(), credentials=None)
        node = create_loops_node(config)
        with pytest.raises(ValueError, match="Credentials are required"):
            await node.execute({})


class TestLoopsDynamicOptionsMock:
    @pytest.mark.asyncio
    async def test_load_mailing_list_options(self):
        with patch(
            "nodes.loops_node._loops_request",
            return_value={
                "status": "success",
                "data": [{"id": "list_1", "name": "Newsletter"}],
            },
        ):
            result = await LoopsNode.load_field_options(
                "mailing_list_id",
                credential_data={"api_key": "loops_test"},
            )
        assert "options" in result
        assert result["options"][0]["value"] == "list_1"
        assert result["options"][0]["label"] == "Newsletter"

    @pytest.mark.asyncio
    async def test_load_transactional_options(self):
        with patch(
            "nodes.loops_node._loops_request",
            return_value={
                "status": "success",
                "data": {"data": [{"id": "tx_1", "name": "Welcome"}]},
            },
        ):
            result = await LoopsNode.load_field_options(
                "transactional_id",
                credential_data={"api_key": "loops_test"},
            )
        assert "options" in result
        assert result["options"][0]["value"] == "tx_1"
        assert result["options"][0]["label"] == "Welcome"

    @pytest.mark.asyncio
    async def test_unknown_field_returns_empty(self):
        result = await LoopsNode.load_field_options(
            "unknown_field",
            credential_data={"api_key": "loops_test"},
        )
        assert result == {"options": []}

    @pytest.mark.asyncio
    async def test_no_credential_returns_empty(self):
        result = await LoopsNode.load_field_options("mailing_list_id")
        assert result == {"options": []}


class TestLoopsTriggerMock:
    @pytest.mark.asyncio
    async def test_on_loops_event_passthrough(self):
        config = LoopsNodeConfig(
            config=LoopsWebhookTriggerConfig(signing_secret="whsec_test"),
            credentials=None,
        )
        node = create_loops_node(config)
        payload = {"eventName": "email.opened", "contactIdentity": {"email": "ada@example.com"}}
        result = await node.execute(payload)
        assert result["status"] == "success"
        assert result["action"] == "on_loops_event"
        assert result["data"]["eventName"] == "email.opened"

    @pytest.mark.asyncio
    async def test_on_loops_event_filtered_match(self):
        config = LoopsNodeConfig(
            config=LoopsWebhookTriggerConfig(
                signing_secret="whsec_test", event_type="email.opened"
            ),
            credentials=None,
        )
        node = create_loops_node(config)
        result = await node.execute({"eventName": "email.opened"})
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_on_loops_event_filtered_no_match(self):
        config = LoopsNodeConfig(
            config=LoopsWebhookTriggerConfig(
                signing_secret="whsec_test", event_type="email.clicked"
            ),
            credentials=None,
        )
        node = create_loops_node(config)
        result = await node.execute({"eventName": "email.opened"})
        assert result["status"] == "skipped"

    def test_verify_webhook_signature(self):
        import base64
        import hmac
        import hashlib
        # Build a valid Svix-style signature
        raw_secret = b"test_secret_bytes"
        encoded_secret = "whsec_" + base64.b64encode(raw_secret).decode()
        body = b'{"eventName":"email.opened"}'
        wh_id = "evt_123"
        ts = "1700000000"
        to_sign = f"{wh_id}.{ts}.".encode() + body
        sig = base64.b64encode(
            hmac.new(raw_secret, to_sign, hashlib.sha256).digest()
        ).decode()
        headers = {
            "webhook-id": wh_id,
            "webhook-timestamp": ts,
            "webhook-signature": f"v1,{sig}",
        }
        config = {"signing_secret": encoded_secret}
        # Bypass the timestamp check by patching time
        with patch("utils.webhook_signatures.time.time", return_value=1700000000.0):
            assert LoopsNode.verify_webhook_signature(body, headers, config)

    @pytest.mark.asyncio
    async def test_register_webhook_requires_secret(self):
        with pytest.raises(ValueError, match="Signing Secret"):
            await LoopsNode._register_external_webhook(
                webhook_url="https://abc.hooks.example.test",
                credential=None,
                config={},
                node_id="node-1",
            )

    @pytest.mark.asyncio
    async def test_register_webhook_with_secret(self):
        extra = await LoopsNode._register_external_webhook(
            webhook_url="https://abc.hooks.example.test",
            credential=None,
            config={"signing_secret": "whsec_abc123"},
            node_id="node-1",
        )
        assert extra["signing_secret"] == "whsec_abc123"
        assert extra["external_webhook_id"] == "loops-manual"
