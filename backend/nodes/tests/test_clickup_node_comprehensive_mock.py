"""
Mock tests for the ClickUp node's COMPREHENSIVE (table-driven) operations.

The 24 hand-written ops are covered in test_clickup_node_mock.py. This module
verifies the generic dispatcher that powers the ~135 long-tail operations:
- path-placeholder substitution (single + multi-segment, URL-encoding)
- v2 vs v3 base-URL routing
- GET -> query string, writes -> JSON body
- ClickUp's custom-task-id keys riding the query string even on writes
- PATCH (chat) and DELETE-with-body (delete_space_tag) methods
- extra_params merge/override
- the custom_request escape hatch (v2 + v3)
- the multipart create_task_attachment op (download URL -> upload)

Construction uses ClickUpNodeConfig(config={...}) so the discriminated union
resolves the generated model by its `operation` discriminator — the same path
the frontend/backend take.

Run: pytest nodes/tests/test_clickup_node_comprehensive_mock.py -q
"""

import pytest
from unittest.mock import Mock, patch

from nodes.clickup_node import (
    ClickUpNode,
    ClickUpNodeConfig,
    ClickUpPersonalTokenCredential,
    ClickUpOAuthCredential,
    CLICKUP_API_BASE,
    CLICKUP_API_BASE_V3,
    _EXTENDED_OPERATIONS,
)


@pytest.fixture
def pat_credentials():
    return ClickUpPersonalTokenCredential(personal_token="pk_12345_ABCDEF")


def make_node(config_dict, credentials):
    config = ClickUpNodeConfig(config=config_dict, credentials=credentials)
    return ClickUpNode(
        node_id="test-clickup-node",
        node_type="automation-clickup",
        node_data={},
        config=config,
        sio=Mock(),
        sid="test-sid",
        workflow_id="test-workflow",
        user_id="test-user",
    )


def _response(status_code=200, json_data=None, content=b"filedata"):
    resp = Mock()
    resp.status_code = status_code
    resp.text = ""
    resp.content = content
    resp.json = lambda: (json_data if json_data is not None else {"ok": True})
    return resp


class CapturingClient:
    """Records every request/get/post call so assertions can inspect what the
    dispatcher actually sent. Reused as its own async context manager."""

    def __init__(self, calls, response):
        self.calls = calls
        self.response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return None

    async def request(self, **kwargs):
        self.calls.append(("request", kwargs))
        return self.response

    async def get(self, url, **kwargs):
        self.calls.append(("get", {"url": url, **kwargs}))
        return self.response

    async def post(self, url, **kwargs):
        self.calls.append(("post", {"url": url, **kwargs}))
        return self.response


async def run_capturing(node, response=None):
    """Execute the node with a capturing httpx client; return (result, calls)."""
    calls = []
    client = CapturingClient(calls, response or _response())
    with patch("nodes.clickup_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    return result, calls


# ============================================================================
# Spec-table integrity
# ============================================================================


class TestSpecTableIntegrity:
    def test_expected_operation_count(self):
        # 134 generated long-tail ops (everything beyond the 24 hand-written +
        # custom_request + attachment + trigger). get_task_templates was dropped
        # — ClickUp's /team/{id}/taskTemplate endpoint returns a server-side 500.
        assert len(_EXTENDED_OPERATIONS) == 134

    def test_every_op_has_method_path_version(self):
        for op, spec in _EXTENDED_OPERATIONS.items():
            method, path, version = spec
            assert method in {"GET", "POST", "PUT", "PATCH", "DELETE"}, op
            assert path.startswith("/"), op
            assert version in {"v2", "v3"}, op

    def test_v3_ops_are_docs_chat_audit(self):
        v3 = {op for op, (_m, _p, v) in _EXTENDED_OPERATIONS.items() if v == "v3"}
        # 8 docs + 18 chat + 1 audit
        assert len(v3) == 27
        assert "search_docs" in v3
        assert "list_chat_channels" in v3
        assert "create_audit_logs" in v3


# ============================================================================
# Generic dispatch: v2
# ============================================================================


class TestGenericDispatchV2:
    @pytest.mark.asyncio
    async def test_get_authorized_user_no_path_params(self, pat_credentials):
        node = make_node({"operation": "get_authorized_user"}, pat_credentials)
        result, calls = await run_capturing(node, _response(200, {"user": {"id": 9}}))
        assert result["status"] == "success"
        assert result["action"] == "get_authorized_user"
        kind, kw = calls[0]
        assert kw["method"] == "GET"
        assert kw["url"] == f"{CLICKUP_API_BASE}/user"

    @pytest.mark.asyncio
    async def test_path_substitution_single(self, pat_credentials):
        node = make_node({"operation": "get_space", "space_id": "S99"}, pat_credentials)
        _, calls = await run_capturing(node)
        assert calls[0][1]["url"] == f"{CLICKUP_API_BASE}/space/S99"
        assert calls[0][1]["method"] == "GET"

    @pytest.mark.asyncio
    async def test_path_substitution_multi_segment(self, pat_credentials):
        node = make_node(
            {"operation": "add_task_link", "task_id": "T1", "links_to": "T2"},
            pat_credentials,
        )
        _, calls = await run_capturing(node)
        assert calls[0][1]["url"] == f"{CLICKUP_API_BASE}/task/T1/link/T2"
        assert calls[0][1]["method"] == "POST"

    @pytest.mark.asyncio
    async def test_path_field_url_encoded(self, pat_credentials):
        node = make_node(
            {"operation": "add_tag_to_task", "task_id": "T1", "tag_name": "needs review"},
            pat_credentials,
        )
        _, calls = await run_capturing(node)
        assert calls[0][1]["url"] == f"{CLICKUP_API_BASE}/task/T1/tag/needs%20review"

    @pytest.mark.asyncio
    async def test_missing_required_path_field_raises(self, pat_credentials):
        node = make_node({"operation": "get_space", "space_id": ""}, pat_credentials)
        with pytest.raises(ValueError, match="space_id"):
            await node.execute({})

    @pytest.mark.asyncio
    async def test_write_body_from_extra_params(self, pat_credentials):
        node = make_node(
            {
                "operation": "merge_tasks",
                "task_id": "T1",
                "extra_params": {"source_task_ids": ["A", "B"]},
            },
            pat_credentials,
        )
        _, calls = await run_capturing(node)
        kw = calls[0][1]
        assert kw["method"] == "POST"
        assert kw["url"] == f"{CLICKUP_API_BASE}/task/T1/merge"
        assert kw["json"] == {"source_task_ids": ["A", "B"]}

    @pytest.mark.asyncio
    async def test_get_query_from_extra_params(self, pat_credentials):
        node = make_node(
            {"operation": "get_view_tasks", "view_id": "V1", "extra_params": {"page": 0}},
            pat_credentials,
        )
        _, calls = await run_capturing(node)
        kw = calls[0][1]
        assert kw["method"] == "GET"
        assert kw["url"] == f"{CLICKUP_API_BASE}/view/V1/task"
        assert kw["params"] == {"page": 0}
        assert kw.get("json") is None

    @pytest.mark.asyncio
    async def test_custom_task_ids_ride_query_on_write(self, pat_credentials):
        """custom_task_ids + team_id must be QUERY params even on a POST."""
        node = make_node(
            {
                "operation": "add_tag_to_task",
                "task_id": "CUSTOM-7",
                "tag_name": "urgent",
                "extra_params": {"custom_task_ids": "true", "team_id": "111"},
            },
            pat_credentials,
        )
        _, calls = await run_capturing(node)
        kw = calls[0][1]
        assert kw["method"] == "POST"
        assert kw["params"] == {"custom_task_ids": "true", "team_id": "111"}
        # Those keys must NOT leak into the JSON body.
        assert kw.get("json") in (None, {})

    @pytest.mark.asyncio
    async def test_delete_with_body(self, pat_credentials):
        """delete_space_tag is a DELETE that carries a JSON body."""
        node = make_node(
            {
                "operation": "delete_space_tag",
                "space_id": "S1",
                "tag_name": "old",
                "extra_params": {"name": "old", "tag_fg": "#fff", "tag_bg": "#000"},
            },
            pat_credentials,
        )
        _, calls = await run_capturing(node)
        kw = calls[0][1]
        assert kw["method"] == "DELETE"
        assert kw["url"] == f"{CLICKUP_API_BASE}/space/S1/tag/old"
        assert kw["json"]["name"] == "old"


# ============================================================================
# Generic dispatch: v3 (Docs / Chat / Audit)
# ============================================================================


class TestGenericDispatchV3:
    @pytest.mark.asyncio
    async def test_search_docs_uses_v3_base(self, pat_credentials):
        node = make_node(
            {"operation": "search_docs", "workspace_id": "W1"}, pat_credentials
        )
        _, calls = await run_capturing(node)
        kw = calls[0][1]
        assert kw["method"] == "GET"
        assert kw["url"] == f"{CLICKUP_API_BASE_V3}/workspaces/W1/docs"

    @pytest.mark.asyncio
    async def test_create_chat_message_v3_body(self, pat_credentials):
        node = make_node(
            {
                "operation": "create_chat_message",
                "workspace_id": "W1",
                "channel_id": "C1",
                "extra_params": {"type": "message", "content": "hi"},
            },
            pat_credentials,
        )
        _, calls = await run_capturing(node)
        kw = calls[0][1]
        assert kw["method"] == "POST"
        assert kw["url"] == f"{CLICKUP_API_BASE_V3}/workspaces/W1/chat/channels/C1/messages"
        assert kw["json"] == {"type": "message", "content": "hi"}

    @pytest.mark.asyncio
    async def test_update_chat_channel_is_patch(self, pat_credentials):
        node = make_node(
            {
                "operation": "update_chat_channel",
                "workspace_id": "W1",
                "channel_id": "C1",
                "extra_params": {"name": "renamed"},
            },
            pat_credentials,
        )
        _, calls = await run_capturing(node)
        kw = calls[0][1]
        assert kw["method"] == "PATCH"
        assert kw["url"] == f"{CLICKUP_API_BASE_V3}/workspaces/W1/chat/channels/C1"
        assert kw["json"] == {"name": "renamed"}

    @pytest.mark.asyncio
    async def test_delete_chat_reaction_path(self, pat_credentials):
        node = make_node(
            {
                "operation": "delete_chat_reaction",
                "workspace_id": "W1",
                "message_id": "M1",
                "reaction": "thumbsup",
            },
            pat_credentials,
        )
        _, calls = await run_capturing(node)
        kw = calls[0][1]
        assert kw["method"] == "DELETE"
        assert (
            kw["url"]
            == f"{CLICKUP_API_BASE_V3}/workspaces/W1/chat/messages/M1/reactions/thumbsup"
        )


# ============================================================================
# Auth header branching on generic ops
# ============================================================================


class TestGenericAuthHeader:
    @pytest.mark.asyncio
    async def test_pat_raw_header(self, pat_credentials):
        node = make_node({"operation": "get_authorized_user"}, pat_credentials)
        _, calls = await run_capturing(node)
        assert calls[0][1]["headers"]["Authorization"] == "pk_12345_ABCDEF"

    @pytest.mark.asyncio
    async def test_oauth_bearer_header(self):
        oauth = ClickUpOAuthCredential(access_token="tok_abc")
        node = make_node({"operation": "get_authorized_user"}, oauth)
        _, calls = await run_capturing(node)
        assert calls[0][1]["headers"]["Authorization"] == "Bearer tok_abc"


# ============================================================================
# custom_request escape hatch
# ============================================================================


class TestCustomRequest:
    @pytest.mark.asyncio
    async def test_custom_request_get_v2_query(self, pat_credentials):
        node = make_node(
            {
                "operation": "custom_request",
                "http_method": "GET",
                "api_version": "v2",
                "path": "/team",
                "params": {"foo": "bar"},
            },
            pat_credentials,
        )
        result, calls = await run_capturing(node)
        assert result["action"] == "custom_request"
        kw = calls[0][1]
        assert kw["method"] == "GET"
        assert kw["url"] == f"{CLICKUP_API_BASE}/team"
        assert kw["params"] == {"foo": "bar"}

    @pytest.mark.asyncio
    async def test_custom_request_post_v3_body(self, pat_credentials):
        node = make_node(
            {
                "operation": "custom_request",
                "http_method": "POST",
                "api_version": "v3",
                "path": "/workspaces/W1/docs",
                "params": {"name": "My Doc"},
            },
            pat_credentials,
        )
        _, calls = await run_capturing(node)
        kw = calls[0][1]
        assert kw["method"] == "POST"
        assert kw["url"] == f"{CLICKUP_API_BASE_V3}/workspaces/W1/docs"
        assert kw["json"] == {"name": "My Doc"}

    @pytest.mark.asyncio
    async def test_custom_request_normalizes_missing_leading_slash(self, pat_credentials):
        node = make_node(
            {"operation": "custom_request", "http_method": "GET", "path": "team"},
            pat_credentials,
        )
        _, calls = await run_capturing(node)
        assert calls[0][1]["url"] == f"{CLICKUP_API_BASE}/team"


# ============================================================================
# create_task_attachment (multipart)
# ============================================================================


class TestCreateTaskAttachment:
    @pytest.mark.asyncio
    async def test_attachment_downloads_then_uploads_multipart(self, pat_credentials):
        node = make_node(
            {
                "operation": "create_task_attachment",
                "task_id": "T1",
                "file_url": "https://example.com/path/report.pdf",
            },
            pat_credentials,
        )
        result, calls = await run_capturing(node, _response(200, {"id": "att_1"}, content=b"PDFDATA"))
        assert result["status"] == "success"
        assert result["action"] == "create_task_attachment"
        # First a GET to download, then a POST with multipart files.
        assert calls[0][0] == "get"
        assert calls[0][1]["url"] == "https://example.com/path/report.pdf"
        assert calls[1][0] == "post"
        post_kw = calls[1][1]
        assert post_kw["url"] == f"{CLICKUP_API_BASE}/task/T1/attachment"
        assert "files" in post_kw
        fname, fcontent = post_kw["files"]["attachment"]
        assert fname == "report.pdf"  # derived from URL basename
        assert fcontent == b"PDFDATA"
        assert post_kw["headers"]["Authorization"] == "pk_12345_ABCDEF"

    @pytest.mark.asyncio
    async def test_attachment_custom_filename_and_custom_ids(self, pat_credentials):
        node = make_node(
            {
                "operation": "create_task_attachment",
                "task_id": "CUSTOM-1",
                "file_url": "https://example.com/x",
                "filename": "renamed.txt",
                "custom_task_ids": "true",
                "team_id": "111",
            },
            pat_credentials,
        )
        _, calls = await run_capturing(node)
        post_kw = calls[1][1]
        assert post_kw["files"]["attachment"][0] == "renamed.txt"
        assert post_kw["params"] == {"custom_task_ids": "true", "team_id": "111"}

    @pytest.mark.asyncio
    async def test_attachment_download_failure_surfaced(self, pat_credentials):
        node = make_node(
            {
                "operation": "create_task_attachment",
                "task_id": "T1",
                "file_url": "https://example.com/missing",
            },
            pat_credentials,
        )
        result, calls = await run_capturing(node, _response(404))
        assert result["status"] == "error"
        assert "download" in result["error"].lower()
        # No upload attempted after a failed download.
        assert all(c[0] != "post" for c in calls)
