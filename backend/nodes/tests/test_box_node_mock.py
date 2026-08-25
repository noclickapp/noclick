"""
Mock tests for the Box Content API node.

Exercises every operation with mocked HTTP responses (no live API calls):
- Users: get current user, list enterprise users
- Folders: list items, get, create, update, delete, copy, list trash
- Files: get, get download URL, upload, upload version, update, delete, copy
- Sharing: create file/folder shared links
- Search: search content
- Collaboration: add, list, remove
- Comments: add, list
- Tasks: create
- Webhooks: create, list, delete
- Trigger: on_box_event passthrough, webhook registration/deregistration,
  signature verification
- Error handling: API errors, missing credentials
- Dynamic options: folder dropdown
"""

import base64
import hashlib
import hmac

import pytest
from unittest.mock import Mock, patch

from nodes.box_node import (
    BoxNode,
    BoxNodeConfig,
    BoxOAuthCredential,
    BoxDeveloperTokenCredential,
    BoxGetMeConfig,
    BoxListUsersConfig,
    BoxListFolderItemsConfig,
    BoxGetFolderConfig,
    BoxCreateFolderConfig,
    BoxUpdateFolderConfig,
    BoxDeleteFolderConfig,
    BoxCopyFolderConfig,
    BoxListTrashConfig,
    BoxGetFileConfig,
    BoxGetDownloadUrlConfig,
    BoxUploadFileConfig,
    BoxUploadVersionConfig,
    BoxUpdateFileConfig,
    BoxDeleteFileConfig,
    BoxCopyFileConfig,
    BoxCreateFileSharedLinkConfig,
    BoxCreateFolderSharedLinkConfig,
    BoxSearchConfig,
    BoxAddCollaborationConfig,
    BoxListCollaborationsConfig,
    BoxRemoveCollaborationConfig,
    BoxAddCommentConfig,
    BoxListCommentsConfig,
    BoxCreateTaskConfig,
    BoxCreateWebhookConfig,
    BoxListWebhooksConfig,
    BoxDeleteWebhookConfig,
    BoxWebhookTriggerConfig,
    BOX_WEBHOOK_TRIGGERS,
    _box_request,
)


@pytest.fixture
def token_credentials():
    return BoxDeveloperTokenCredential(access_token="box_dev_token_12345")


@pytest.fixture
def oauth_credentials():
    return BoxOAuthCredential(access_token="box_oauth_access_token")


def create_box_node(config):
    return BoxNode(
        node_id="test-box-node",
        node_type="automation-box",
        node_data={},
        config=config,
        sio=Mock(),
        sid="test-sid",
        workflow_id="test-workflow",
        user_id="test-user",
    )


@pytest.mark.asyncio
async def test_box_request_rejects_non_provider_base_before_client():
    with patch(
        "nodes.box_node.guarded_async_client",
        side_effect=AssertionError("client must not be created"),
    ) as client:
        with pytest.raises(ValueError, match="code-owned API base"):
            await _box_request(
                "secret",
                "GET",
                "/collect",
                base="https://attacker.example",
            )
    client.assert_not_called()


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


async def _run(node, json_data, status_code=200):
    mock_client = create_mock_client(status_code, json_data)
    with patch("nodes.box_node.httpx.AsyncClient", return_value=mock_client):
        return await node.execute({})


# ============================================================================
# Users
# ============================================================================


class TestBoxUsersMock:
    @pytest.mark.asyncio
    async def test_get_me(self, oauth_credentials):
        config = BoxNodeConfig(config=BoxGetMeConfig(), credentials=oauth_credentials)
        result = await _run(create_box_node(config), {"id": "u1", "name": "Ada", "login": "ada@example.com"})
        assert result["status"] == "success"
        assert result["action"] == "get_me"
        assert result["data"]["login"] == "ada@example.com"

    @pytest.mark.asyncio
    async def test_list_users(self, token_credentials):
        config = BoxNodeConfig(config=BoxListUsersConfig(filter_term="ada"), credentials=token_credentials)
        result = await _run(create_box_node(config), {"total_count": 1, "entries": [{"id": "u1"}]})
        assert result["status"] == "success"
        assert result["action"] == "list_users"
        assert result["data"]["total_count"] == 1


# ============================================================================
# Folders
# ============================================================================


class TestBoxFoldersMock:
    @pytest.mark.asyncio
    async def test_list_folder_items(self, token_credentials):
        config = BoxNodeConfig(config=BoxListFolderItemsConfig(folder_id="0"), credentials=token_credentials)
        result = await _run(create_box_node(config), {"entries": [{"id": "f1", "type": "file"}]})
        assert result["status"] == "success"
        assert result["action"] == "list_folder_items"
        assert len(result["data"]["entries"]) == 1

    @pytest.mark.asyncio
    async def test_get_folder(self, token_credentials):
        config = BoxNodeConfig(config=BoxGetFolderConfig(folder_id="123"), credentials=token_credentials)
        result = await _run(create_box_node(config), {"id": "123", "name": "Docs", "type": "folder"})
        assert result["status"] == "success"
        assert result["action"] == "get_folder"
        assert result["data"]["id"] == "123"

    @pytest.mark.asyncio
    async def test_create_folder(self, token_credentials):
        config = BoxNodeConfig(
            config=BoxCreateFolderConfig(name="New", parent_id="0"), credentials=token_credentials
        )
        result = await _run(create_box_node(config), {"id": "456", "name": "New"}, status_code=201)
        assert result["status"] == "success"
        assert result["action"] == "create_folder"
        assert result["data"]["id"] == "456"

    @pytest.mark.asyncio
    async def test_update_folder(self, token_credentials):
        config = BoxNodeConfig(
            config=BoxUpdateFolderConfig(folder_id="123", name="Renamed", parent_id="0"),
            credentials=token_credentials,
        )
        result = await _run(create_box_node(config), {"id": "123", "name": "Renamed"})
        assert result["status"] == "success"
        assert result["action"] == "update_folder"

    @pytest.mark.asyncio
    async def test_delete_folder(self, token_credentials):
        config = BoxNodeConfig(
            config=BoxDeleteFolderConfig(folder_id="123", recursive="true"), credentials=token_credentials
        )
        result = await _run(create_box_node(config), None, status_code=204)
        assert result["status"] == "success"
        assert result["action"] == "delete_folder"
        assert result["data"]["success"] is True

    @pytest.mark.asyncio
    async def test_copy_folder(self, token_credentials):
        config = BoxNodeConfig(
            config=BoxCopyFolderConfig(folder_id="123", parent_id="0", name="Copy"),
            credentials=token_credentials,
        )
        result = await _run(create_box_node(config), {"id": "789", "name": "Copy"}, status_code=201)
        assert result["status"] == "success"
        assert result["action"] == "copy_folder"

    @pytest.mark.asyncio
    async def test_list_trash(self, token_credentials):
        config = BoxNodeConfig(config=BoxListTrashConfig(), credentials=token_credentials)
        result = await _run(create_box_node(config), {"entries": [{"id": "t1"}]})
        assert result["status"] == "success"
        assert result["action"] == "list_trash"


# ============================================================================
# Files
# ============================================================================


class TestBoxFilesMock:
    @pytest.mark.asyncio
    async def test_get_file(self, token_credentials):
        config = BoxNodeConfig(config=BoxGetFileConfig(file_id="f1"), credentials=token_credentials)
        result = await _run(create_box_node(config), {"id": "f1", "name": "report.pdf", "size": 1024})
        assert result["status"] == "success"
        assert result["action"] == "get_file"
        assert result["data"]["name"] == "report.pdf"

    @pytest.mark.asyncio
    async def test_get_download_url(self, token_credentials):
        config = BoxNodeConfig(config=BoxGetDownloadUrlConfig(file_id="f1"), credentials=token_credentials)
        result = await _run(create_box_node(config), {"id": "f1", "name": "report.pdf"})
        assert result["status"] == "success"
        assert result["action"] == "get_download_url"
        assert result["data"]["download_url"].endswith("/files/f1/content")

    @pytest.mark.asyncio
    async def test_upload_file(self, token_credentials):
        config = BoxNodeConfig(
            config=BoxUploadFileConfig(name="notes.txt", parent_id="0", content="hello"),
            credentials=token_credentials,
        )
        result = await _run(create_box_node(config), {"entries": [{"id": "f2", "name": "notes.txt"}]}, status_code=201)
        assert result["status"] == "success"
        assert result["action"] == "upload_file"
        assert result["data"]["entries"][0]["id"] == "f2"

    @pytest.mark.asyncio
    async def test_upload_version(self, token_credentials):
        config = BoxNodeConfig(
            config=BoxUploadVersionConfig(file_id="f1", content="updated"), credentials=token_credentials
        )
        result = await _run(create_box_node(config), {"entries": [{"id": "f1"}]}, status_code=201)
        assert result["status"] == "success"
        assert result["action"] == "upload_version"

    @pytest.mark.asyncio
    async def test_update_file(self, token_credentials):
        config = BoxNodeConfig(
            config=BoxUpdateFileConfig(file_id="f1", name="renamed.pdf"), credentials=token_credentials
        )
        result = await _run(create_box_node(config), {"id": "f1", "name": "renamed.pdf"})
        assert result["status"] == "success"
        assert result["action"] == "update_file"

    @pytest.mark.asyncio
    async def test_delete_file(self, token_credentials):
        config = BoxNodeConfig(config=BoxDeleteFileConfig(file_id="f1"), credentials=token_credentials)
        result = await _run(create_box_node(config), None, status_code=204)
        assert result["status"] == "success"
        assert result["action"] == "delete_file"

    @pytest.mark.asyncio
    async def test_copy_file(self, token_credentials):
        config = BoxNodeConfig(
            config=BoxCopyFileConfig(file_id="f1", parent_id="0", name="copy.pdf"),
            credentials=token_credentials,
        )
        result = await _run(create_box_node(config), {"id": "f3", "name": "copy.pdf"}, status_code=201)
        assert result["status"] == "success"
        assert result["action"] == "copy_file"


# ============================================================================
# Sharing
# ============================================================================


class TestBoxSharingMock:
    @pytest.mark.asyncio
    async def test_create_file_shared_link(self, token_credentials):
        config = BoxNodeConfig(
            config=BoxCreateFileSharedLinkConfig(file_id="f1", access="open"), credentials=token_credentials
        )
        result = await _run(
            create_box_node(config), {"id": "f1", "shared_link": {"url": "https://app.box.com/s/abc"}}
        )
        assert result["status"] == "success"
        assert result["action"] == "create_file_shared_link"
        assert "shared_link" in result["data"]

    @pytest.mark.asyncio
    async def test_create_folder_shared_link(self, token_credentials):
        config = BoxNodeConfig(
            config=BoxCreateFolderSharedLinkConfig(folder_id="123", access="company"),
            credentials=token_credentials,
        )
        result = await _run(
            create_box_node(config), {"id": "123", "shared_link": {"url": "https://app.box.com/s/xyz"}}
        )
        assert result["status"] == "success"
        assert result["action"] == "create_folder_shared_link"


# ============================================================================
# Search
# ============================================================================


class TestBoxSearchMock:
    @pytest.mark.asyncio
    async def test_search(self, token_credentials):
        config = BoxNodeConfig(
            config=BoxSearchConfig(query="quarterly", type="file"), credentials=token_credentials
        )
        result = await _run(create_box_node(config), {"total_count": 2, "entries": [{"id": "f1"}, {"id": "f2"}]})
        assert result["status"] == "success"
        assert result["action"] == "search"
        assert result["data"]["total_count"] == 2


# ============================================================================
# Collaboration
# ============================================================================


class TestBoxCollaborationMock:
    @pytest.mark.asyncio
    async def test_add_collaboration(self, token_credentials):
        config = BoxNodeConfig(
            config=BoxAddCollaborationConfig(
                item_type="folder", item_id="123", login="bob@example.com", role="editor"
            ),
            credentials=token_credentials,
        )
        result = await _run(create_box_node(config), {"id": "c1", "role": "editor"}, status_code=201)
        assert result["status"] == "success"
        assert result["action"] == "add_collaboration"

    @pytest.mark.asyncio
    async def test_list_collaborations(self, token_credentials):
        config = BoxNodeConfig(
            config=BoxListCollaborationsConfig(item_type="folder", item_id="123"),
            credentials=token_credentials,
        )
        result = await _run(create_box_node(config), {"entries": [{"id": "c1"}]})
        assert result["status"] == "success"
        assert result["action"] == "list_collaborations"

    @pytest.mark.asyncio
    async def test_remove_collaboration(self, token_credentials):
        config = BoxNodeConfig(
            config=BoxRemoveCollaborationConfig(collaboration_id="c1"), credentials=token_credentials
        )
        result = await _run(create_box_node(config), None, status_code=204)
        assert result["status"] == "success"
        assert result["action"] == "remove_collaboration"


# ============================================================================
# Comments
# ============================================================================


class TestBoxCommentsMock:
    @pytest.mark.asyncio
    async def test_add_comment(self, token_credentials):
        config = BoxNodeConfig(
            config=BoxAddCommentConfig(file_id="f1", message="Looks good"), credentials=token_credentials
        )
        result = await _run(create_box_node(config), {"id": "cm1", "message": "Looks good"}, status_code=201)
        assert result["status"] == "success"
        assert result["action"] == "add_comment"

    @pytest.mark.asyncio
    async def test_list_comments(self, token_credentials):
        config = BoxNodeConfig(config=BoxListCommentsConfig(file_id="f1"), credentials=token_credentials)
        result = await _run(create_box_node(config), {"total_count": 1, "entries": [{"id": "cm1"}]})
        assert result["status"] == "success"
        assert result["action"] == "list_comments"


# ============================================================================
# Tasks
# ============================================================================


class TestBoxTasksMock:
    @pytest.mark.asyncio
    async def test_create_task(self, token_credentials):
        config = BoxNodeConfig(
            config=BoxCreateTaskConfig(file_id="f1", message="Please review", action="review"),
            credentials=token_credentials,
        )
        result = await _run(create_box_node(config), {"id": "tk1", "action": "review"}, status_code=201)
        assert result["status"] == "success"
        assert result["action"] == "create_task"


# ============================================================================
# Webhooks (manual operations)
# ============================================================================


class TestBoxWebhooksMock:
    @pytest.mark.asyncio
    async def test_create_webhook(self, token_credentials):
        config = BoxNodeConfig(
            config=BoxCreateWebhookConfig(
                target_type="folder", target_id="123", address="https://x.hooks.example.test", triggers="FILE.UPLOADED"
            ),
            credentials=token_credentials,
        )
        result = await _run(create_box_node(config), {"id": "wh1"}, status_code=201)
        assert result["status"] == "success"
        assert result["action"] == "create_webhook"

    @pytest.mark.asyncio
    async def test_list_webhooks(self, token_credentials):
        config = BoxNodeConfig(config=BoxListWebhooksConfig(), credentials=token_credentials)
        result = await _run(create_box_node(config), {"entries": [{"id": "wh1"}]})
        assert result["status"] == "success"
        assert result["action"] == "list_webhooks"

    @pytest.mark.asyncio
    async def test_delete_webhook(self, token_credentials):
        config = BoxNodeConfig(config=BoxDeleteWebhookConfig(webhook_id="wh1"), credentials=token_credentials)
        result = await _run(create_box_node(config), None, status_code=204)
        assert result["status"] == "success"
        assert result["action"] == "delete_webhook"


# ============================================================================
# Trigger
# ============================================================================


class TestBoxTriggerMock:
    @pytest.mark.asyncio
    async def test_on_box_event_passthrough(self):
        """The trigger passes the inbound webhook payload through as output."""
        config = BoxNodeConfig(
            config=BoxWebhookTriggerConfig(webhook_url="https://abc.hooks.example.test", target_id="123"),
            credentials=None,
        )
        node = create_box_node(config)
        payload = {"trigger": "FILE.UPLOADED", "source": {"id": "f1", "type": "file"}}
        result = await node.execute(payload)
        assert result["status"] == "success"
        assert result["action"] == "on_box_event"
        assert result["data"]["trigger"] == "FILE.UPLOADED"

    @pytest.mark.asyncio
    async def test_register_external_webhook(self):
        with patch(
            "nodes.box_node._box_request",
            return_value={"status": "success", "data": {"id": "wh99"}},
        ) as mock_req:
            extra = await BoxNode._register_external_webhook(
                webhook_url="https://abc.hooks.example.test",
                credential={"access_token": "box_tok"},
                config={"target_type": "folder", "target_id": "123"},
                node_id="node-1",
            )
        assert mock_req.called
        assert extra["external_webhook_id"] == "wh99"

    @pytest.mark.asyncio
    async def test_register_subscribes_to_selected_event_types(self):
        """Only the user-selected events are passed to Box's triggers array."""
        with patch(
            "nodes.box_node._box_request",
            return_value={"status": "success", "data": {"id": "wh1"}},
        ) as mock_req:
            await BoxNode._register_external_webhook(
                webhook_url="https://abc.hooks.example.test",
                credential={"access_token": "box_tok"},
                config={
                    "target_type": "folder",
                    "target_id": "123",
                    "event_types": "FILE.UPLOADED, FOLDER.CREATED",
                },
                node_id="node-1",
            )
        body = mock_req.call_args.kwargs["json_body"]
        assert body["triggers"] == ["FILE.UPLOADED", "FOLDER.CREATED"]

    @pytest.mark.asyncio
    async def test_register_blank_event_types_subscribes_to_all(self):
        """A blank selection falls back to every Box webhook trigger."""
        with patch(
            "nodes.box_node._box_request",
            return_value={"status": "success", "data": {"id": "wh1"}},
        ) as mock_req:
            await BoxNode._register_external_webhook(
                webhook_url="https://abc.hooks.example.test",
                credential={"access_token": "box_tok"},
                config={"target_type": "folder", "target_id": "123", "event_types": ""},
                node_id="node-1",
            )
        body = mock_req.call_args.kwargs["json_body"]
        assert body["triggers"] == BOX_WEBHOOK_TRIGGERS

    def test_filter_trigger_payload_skips_non_selected_events(self):
        """An event not in the selected set is skipped (returns False)."""
        config = {"event_types": "FILE.UPLOADED,FOLDER.CREATED"}
        assert BoxNode.filter_trigger_payload({"trigger": "FILE.UPLOADED"}, config) is True
        assert BoxNode.filter_trigger_payload({"trigger": "FOLDER.CREATED"}, config) is True
        assert BoxNode.filter_trigger_payload({"trigger": "FILE.DELETED"}, config) is False
        # Missing/unknown trigger is skipped when a filter is set.
        assert BoxNode.filter_trigger_payload({}, config) is False

    def test_filter_trigger_payload_blank_passes_all_events(self):
        """A blank selection fires on every event."""
        for cfg in ({"event_types": ""}, {}):
            assert BoxNode.filter_trigger_payload({"trigger": "FILE.DELETED"}, cfg) is True
            assert BoxNode.filter_trigger_payload({"trigger": "FOLDER.MOVED"}, cfg) is True

    @pytest.mark.asyncio
    async def test_unregister_external_webhook(self):
        with patch(
            "nodes.box_node._box_request",
            return_value={"status": "success", "data": {}},
        ) as mock_req:
            await BoxNode._unregister_external_webhook(
                credential={"access_token": "box_tok"},
                config={"external_webhook_id": "wh99"},
                node_id="node-1",
            )
        assert mock_req.called

    def test_verify_webhook_signature(self):
        from datetime import datetime, timezone
        primary_key = "primarysecret"
        secondary_key = "secondarysecret"
        body = b'{"trigger":"FILE.UPLOADED"}'
        timestamp = datetime.now(timezone.utc).isoformat()
        message = body + timestamp.encode()

        def _sig(key):
            return base64.b64encode(hmac.new(key.encode(), message, hashlib.sha256).digest()).decode()

        sig_primary = _sig(primary_key)
        sig_secondary = _sig(secondary_key)

        headers_both = {
            "box-delivery-timestamp": timestamp,
            "box-signature-primary": sig_primary,
            "box-signature-secondary": sig_secondary,
        }
        config_both = {"signing_secret": primary_key, "signing_secret_secondary": secondary_key}

        # Both keys present — accept
        assert BoxNode.verify_webhook_signature(body, headers_both, config_both)
        # Primary key only in config — accepts via primary header
        assert BoxNode.verify_webhook_signature(body, headers_both, {"signing_secret": primary_key})
        # Secondary key only in config — accepts via secondary header
        assert BoxNode.verify_webhook_signature(body, headers_both, {"signing_secret_secondary": secondary_key})
        # Bad signature rejected
        bad = {"box-delivery-timestamp": timestamp, "box-signature-primary": "deadbeef"}
        assert not BoxNode.verify_webhook_signature(body, bad, config_both)
        # Wrong key rejected
        assert not BoxNode.verify_webhook_signature(body, headers_both, {"signing_secret": "wrongkey"})
        # No secret stored -> accept (trigger not armed)
        assert BoxNode.verify_webhook_signature(body, {}, {})
        # Replay guard: >10-min-old delivery rejected even with valid signature
        old_ts = "2020-01-01T00:00:00+00:00"
        old_msg = body + old_ts.encode()
        old_sig = base64.b64encode(hmac.new(primary_key.encode(), old_msg, hashlib.sha256).digest()).decode()
        assert not BoxNode.verify_webhook_signature(
            body,
            {"box-delivery-timestamp": old_ts, "box-signature-primary": old_sig},
            {"signing_secret": primary_key},
        )


# ============================================================================
# Error handling
# ============================================================================


class TestBoxErrorHandlingMock:
    @pytest.mark.asyncio
    async def test_api_error(self, token_credentials):
        config = BoxNodeConfig(config=BoxGetFileConfig(file_id="missing"), credentials=token_credentials)
        result = await _run(create_box_node(config), {"message": "Not Found", "status": 404}, status_code=404)
        assert result["status"] == "error"
        assert result["status_code"] == 404
        assert "not found" in str(result["error"]).lower()

    @pytest.mark.asyncio
    async def test_missing_credentials(self):
        config = BoxNodeConfig(config=BoxGetMeConfig(), credentials=None)
        node = create_box_node(config)
        with pytest.raises(ValueError, match="Credentials are required"):
            await node.execute({})


# ============================================================================
# Dynamic options
# ============================================================================


class TestBoxDynamicOptionsMock:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("field_name", ["folder_id", "parent_id", "target_id"])
    async def test_load_folder_options(self, field_name):
        """folder_id / parent_id / target_id all resolve to the root subfolder list."""
        with patch(
            "nodes.box_node._box_request",
            return_value={
                "status": "success",
                "data": {"entries": [{"id": "10", "name": "Projects", "type": "folder"}, {"id": "11", "name": "a.txt", "type": "file"}]},
            },
        ):
            result = await BoxNode.load_field_options(field_name, {"access_token": "box_tok"}, context={})
        assert "options" in result
        # root option + the one folder (file filtered out)
        values = [o["value"] for o in result["options"]]
        assert "0" in values
        assert "10" in values
        assert "11" not in values

    @pytest.mark.asyncio
    async def test_load_webhook_options(self):
        with patch(
            "nodes.box_node._box_request",
            return_value={
                "status": "success",
                "data": {
                    "entries": [
                        {"id": "wh1", "target": {"id": "123", "type": "folder"}},
                        {"id": "wh2", "target": {"id": "f9", "type": "file"}},
                    ]
                },
            },
        ):
            result = await BoxNode.load_field_options("webhook_id", {"access_token": "box_tok"}, context={})
        assert "options" in result
        values = [o["value"] for o in result["options"]]
        assert values == ["wh1", "wh2"]
        # labels surface the target so users can tell webhooks apart
        assert "folder" in result["options"][0]["label"]
        assert "123" in result["options"][0]["label"]

    @pytest.mark.asyncio
    async def test_load_options_no_credential(self):
        """No connected credential -> empty options, no API call."""
        result = await BoxNode.load_field_options("webhook_id", {}, context={})
        assert result == {"options": []}

    @pytest.mark.asyncio
    async def test_load_options_unknown_field(self):
        """A field without a dynamic-options handler returns no options."""
        result = await BoxNode.load_field_options("file_id", {"access_token": "box_tok"}, context={})
        assert result == {"options": []}
