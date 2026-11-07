"""
Mock tests for the Arcads REST API node.

Exercises every operation with mocked HTTP responses (no live API calls):
- Products: list, create, get, update, delete
- Folders & Scripts: list folders, create folder, list scripts, create project,
  create script, get script, update script
- Generation: generate script videos, generate video (v2), generate image (v2),
  generate talking actor (v2), generate camera-movement preset, Veo 3.1, Omnihuman
- Assets & Status: list script videos, get video, get video watch, get workflow
  run, get presigned URL
- Catalog: list actors, list actor situations, list situations, list voices,
  list presets
- Auth: Basic auth header construction
- Error handling: API errors, missing credentials
- Dynamic options: product / actor / voice dropdowns
"""

import base64
from typing import Any, Dict

import pytest
from unittest.mock import AsyncMock, Mock, patch

from nodes.arcads_node import (
    ArcadsNode,
    ArcadsNodeConfig,
    ArcadsApiKeyCredential,
    _basic_auth_header,
    ArcadsOnGenerationCompletedConfig,
    ArcadsListProductsConfig,
    ArcadsCreateProductConfig,
    ArcadsGetProductConfig,
    ArcadsUpdateProductConfig,
    ArcadsDeleteProductConfig,
    ArcadsListFoldersConfig,
    ArcadsCreateFolderConfig,
    ArcadsListScriptsConfig,
    ArcadsCreateProjectConfig,
    ArcadsCreateScriptConfig,
    ArcadsGetScriptConfig,
    ArcadsUpdateScriptConfig,
    ArcadsGenerateScriptVideosConfig,
    ArcadsGenerateVideoConfig,
    ArcadsGenerateImageConfig,
    ArcadsGenerateTalkingActorConfig,
    ArcadsGeneratePresetConfig,
    ArcadsGenerateVeo31Config,
    ArcadsGenerateOmnihumanConfig,
    ArcadsListScriptVideosConfig,
    ArcadsGetVideoConfig,
    ArcadsGetVideoWatchConfig,
    ArcadsGetWorkflowRunConfig,
    ArcadsGetPresignedUrlConfig,
    ArcadsListActorsConfig,
    ArcadsListActorSituationsConfig,
    ArcadsListSituationsConfig,
    ArcadsListVoicesConfig,
    ArcadsListPresetsConfig,
)


@pytest.fixture
def credentials():
    return ArcadsApiKeyCredential(client_id="cid_123", client_secret="csecret_456")


def create_arcads_node(config):
    return ArcadsNode(
        node_id="test-arcads-node",
        node_type="automation-arcads",
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


async def _run(config_obj, credentials, status_code=200, json_data=None):
    config = ArcadsNodeConfig(config=config_obj, credentials=credentials)
    node = create_arcads_node(config)
    mock_client = create_mock_client(status_code, json_data)
    with patch("nodes.arcads_node.httpx.AsyncClient", return_value=mock_client):
        return await node.execute({})


# ============================================================================
# Auth
# ============================================================================


def test_basic_auth_header():
    header = _basic_auth_header("cid_123", "csecret_456")
    expected = base64.b64encode(b"cid_123:csecret_456").decode()
    assert header == f"Basic {expected}"


# ============================================================================
# Products
# ============================================================================


class TestArcadsProductsMock:
    @pytest.mark.asyncio
    async def test_list_products(self, credentials):
        result = await _run(
            ArcadsListProductsConfig(page="1", page_size="10"),
            credentials,
            200,
            {"data": [{"id": "p1"}, {"id": "p2"}]},
        )
        assert result["status"] == "success"
        assert result["action"] == "list_products"
        assert len(result["data"]["data"]) == 2

    @pytest.mark.asyncio
    async def test_create_product(self, credentials):
        result = await _run(
            ArcadsCreateProductConfig(name="Widget", description="A widget"),
            credentials,
            201,
            {"id": "p_new", "name": "Widget"},
        )
        assert result["status"] == "success"
        assert result["action"] == "create_product"
        assert result["data"]["id"] == "p_new"

    @pytest.mark.asyncio
    async def test_get_product(self, credentials):
        result = await _run(
            ArcadsGetProductConfig(product_id="p1"),
            credentials,
            200,
            {"id": "p1", "name": "Widget"},
        )
        assert result["status"] == "success"
        assert result["action"] == "get_product"
        assert result["data"]["id"] == "p1"

    @pytest.mark.asyncio
    async def test_update_product(self, credentials):
        result = await _run(
            ArcadsUpdateProductConfig(product_id="p1", name="Widget v2"),
            credentials,
            200,
            {"id": "p1", "name": "Widget v2"},
        )
        assert result["status"] == "success"
        assert result["action"] == "update_product"

    @pytest.mark.asyncio
    async def test_delete_product(self, credentials):
        result = await _run(
            ArcadsDeleteProductConfig(product_id="p1"), credentials, 204, None
        )
        assert result["status"] == "success"
        assert result["action"] == "delete_product"
        assert result["data"]["success"] is True


# ============================================================================
# Folders & Scripts
# ============================================================================


class TestArcadsFoldersScriptsMock:
    @pytest.mark.asyncio
    async def test_list_folders(self, credentials):
        result = await _run(
            ArcadsListFoldersConfig(product_id="p1"),
            credentials,
            200,
            {"data": [{"id": "f1"}]},
        )
        assert result["status"] == "success"
        assert result["action"] == "list_folders"

    @pytest.mark.asyncio
    async def test_create_folder(self, credentials):
        result = await _run(
            ArcadsCreateFolderConfig(product_id="p1", name="Campaign"),
            credentials,
            201,
            {"id": "f_new"},
        )
        assert result["status"] == "success"
        assert result["action"] == "create_folder"

    @pytest.mark.asyncio
    async def test_list_scripts(self, credentials):
        result = await _run(
            ArcadsListScriptsConfig(folder_id="f1"),
            credentials,
            200,
            {"data": [{"id": "s1"}]},
        )
        assert result["status"] == "success"
        assert result["action"] == "list_scripts"

    @pytest.mark.asyncio
    async def test_create_project(self, credentials):
        result = await _run(
            ArcadsCreateProjectConfig(name="Q3 Ads", folder_id="f1"),
            credentials,
            201,
            {"id": "prj_new"},
        )
        assert result["status"] == "success"
        assert result["action"] == "create_project"

    @pytest.mark.asyncio
    async def test_create_script(self, credentials):
        result = await _run(
            ArcadsCreateScriptConfig(name="Ad", text="Buy now!", folder_id="f1"),
            credentials,
            201,
            {"id": "s_new"},
        )
        assert result["status"] == "success"
        assert result["action"] == "create_script"
        assert result["data"]["id"] == "s_new"

    @pytest.mark.asyncio
    async def test_get_script(self, credentials):
        result = await _run(
            ArcadsGetScriptConfig(script_id="s1"),
            credentials,
            200,
            {"id": "s1", "text": "Buy now!"},
        )
        assert result["status"] == "success"
        assert result["action"] == "get_script"

    @pytest.mark.asyncio
    async def test_update_script(self, credentials):
        result = await _run(
            ArcadsUpdateScriptConfig(script_id="s1", text="Updated"),
            credentials,
            200,
            {"id": "s1"},
        )
        assert result["status"] == "success"
        assert result["action"] == "update_script"


# ============================================================================
# Generation
# ============================================================================


class TestArcadsGenerationMock:
    @pytest.mark.asyncio
    async def test_generate_script_videos(self, credentials):
        result = await _run(
            ArcadsGenerateScriptVideosConfig(script_id="s1"),
            credentials,
            202,
            {"jobId": "job_1"},
        )
        assert result["status"] == "success"
        assert result["action"] == "generate_script_videos"

    @pytest.mark.asyncio
    async def test_generate_video(self, credentials):
        result = await _run(
            ArcadsGenerateVideoConfig(prompt="Hello", product_id="p1", model="veo31"),
            credentials,
            202,
            {"id": "vid_1"},
        )
        assert result["status"] == "success"
        assert result["action"] == "generate_video"

    @pytest.mark.asyncio
    async def test_generate_image(self, credentials):
        result = await _run(
            ArcadsGenerateImageConfig(
                prompt="A red car",
                product_id="p1",
                model="gpt-image",
                aspect_ratio="16:9",
            ),
            credentials,
            202,
            {"id": "img_1"},
        )
        assert result["status"] == "success"
        assert result["action"] == "generate_image"

    @pytest.mark.asyncio
    async def test_generate_talking_actor(self, credentials):
        result = await _run(
            ArcadsGenerateTalkingActorConfig(
                text="Hi there",
                product_id="p1",
                model="arcads_1.0",
                actors=[{"situationId": "s1"}],
            ),
            credentials,
            202,
            {"id": "ta_1"},
        )
        assert result["status"] == "success"
        assert result["action"] == "generate_talking_actor"

    @pytest.mark.asyncio
    async def test_generate_preset(self, credentials):
        result = await _run(
            ArcadsGeneratePresetConfig(
                product_id="p1",
                situation_id="s1",
                reference_images=["/tmp-uploads/avatar.png"],
            ),
            credentials,
            202,
            {"runId": "run_1"},
        )
        assert result["status"] == "success"
        assert result["action"] == "generate_preset"

    @pytest.mark.asyncio
    async def test_generate_veo31(self, credentials):
        result = await _run(
            ArcadsGenerateVeo31Config(
                prompt="A drone over a city",
                product_id="p1",
                resolution="1080p",
                aspect_ratio="16:9",
            ),
            credentials,
            202,
            {"id": "veo_1"},
        )
        assert result["status"] == "success"
        assert result["action"] == "generate_veo31"

    @pytest.mark.asyncio
    async def test_generate_omnihuman(self, credentials):
        result = await _run(
            ArcadsGenerateOmnihumanConfig(
                text="Welcome", product_id="p1", videos=[{"situationId": "s1"}]
            ),
            credentials,
            202,
            {"id": "omni_1"},
        )
        assert result["status"] == "success"
        assert result["action"] == "generate_omnihuman"


# ============================================================================
# Assets & Status
# ============================================================================


class TestArcadsAssetsMock:
    @pytest.mark.asyncio
    async def test_list_script_videos(self, credentials):
        result = await _run(
            ArcadsListScriptVideosConfig(script_id="s1"),
            credentials,
            200,
            {"data": [{"id": "vid_1", "status": "ready"}]},
        )
        assert result["status"] == "success"
        assert result["action"] == "list_script_videos"

    @pytest.mark.asyncio
    async def test_get_video(self, credentials):
        result = await _run(
            ArcadsGetVideoConfig(video_id="vid_1"),
            credentials,
            200,
            {"id": "vid_1", "status": "ready"},
        )
        assert result["status"] == "success"
        assert result["action"] == "get_video"
        assert result["data"]["status"] == "ready"

    @pytest.mark.asyncio
    async def test_get_video_watch(self, credentials):
        result = await _run(
            ArcadsGetVideoWatchConfig(video_id="vid_1"),
            credentials,
            200,
            {"url": "https://cdn.arcads.ai/vid_1.mp4"},
        )
        assert result["status"] == "success"
        assert result["action"] == "get_video_watch"
        assert "url" in result["data"]

    @pytest.mark.asyncio
    async def test_get_workflow_run(self, credentials):
        result = await _run(
            ArcadsGetWorkflowRunConfig(run_id="run_1"),
            credentials,
            200,
            {"id": "run_1", "status": "completed"},
        )
        assert result["status"] == "success"
        assert result["action"] == "get_workflow_run"

    @pytest.mark.asyncio
    async def test_get_presigned_url(self, credentials):
        result = await _run(
            ArcadsGetPresignedUrlConfig(file_type="image/png"),
            credentials,
            200,
            {"uploadUrl": "https://s3.example.com/presigned"},
        )
        assert result["status"] == "success"
        assert result["action"] == "get_presigned_url"
        assert "uploadUrl" in result["data"]


# ============================================================================
# Catalog
# ============================================================================


class TestArcadsCatalogMock:
    @pytest.mark.asyncio
    async def test_list_actors(self, credentials):
        result = await _run(
            ArcadsListActorsConfig(gender="female"),
            credentials,
            200,
            {"data": [{"id": "a1", "name": "Ava"}]},
        )
        assert result["status"] == "success"
        assert result["action"] == "list_actors"

    @pytest.mark.asyncio
    async def test_list_actor_situations(self, credentials):
        result = await _run(
            ArcadsListActorSituationsConfig(actor_id="a1"),
            credentials,
            200,
            {"data": [{"id": "sit_1"}]},
        )
        assert result["status"] == "success"
        assert result["action"] == "list_actor_situations"

    @pytest.mark.asyncio
    async def test_list_situations(self, credentials):
        result = await _run(
            ArcadsListSituationsConfig(),
            credentials,
            200,
            {"data": [{"id": "sit_1"}]},
        )
        assert result["status"] == "success"
        assert result["action"] == "list_situations"

    @pytest.mark.asyncio
    async def test_list_voices(self, credentials):
        result = await _run(
            ArcadsListVoicesConfig(),
            credentials,
            200,
            {"data": [{"id": "v1", "name": "Calm"}]},
        )
        assert result["status"] == "success"
        assert result["action"] == "list_voices"

    @pytest.mark.asyncio
    async def test_list_presets(self, credentials):
        result = await _run(
            ArcadsListPresetsConfig(),
            credentials,
            200,
            {"data": [{"id": "product-showcase"}]},
        )
        assert result["status"] == "success"
        assert result["action"] == "list_presets"


# ============================================================================
# Error handling
# ============================================================================


class TestArcadsErrorHandlingMock:
    @pytest.mark.asyncio
    async def test_api_error(self, credentials):
        result = await _run(
            ArcadsGetProductConfig(product_id="missing"),
            credentials,
            404,
            {"message": "Product not found"},
        )
        assert result["status"] == "error"
        assert result["status_code"] == 404
        assert "not found" in str(result["error"]).lower()

    @pytest.mark.asyncio
    async def test_auth_error_403(self, credentials):
        result = await _run(
            ArcadsListProductsConfig(),
            credentials,
            403,
            {"message": "Forbidden"},
        )
        assert result["status"] == "error"
        assert result["status_code"] == 403

    @pytest.mark.asyncio
    async def test_missing_credentials(self):
        config = ArcadsNodeConfig(config=ArcadsListProductsConfig(), credentials=None)
        node = create_arcads_node(config)
        with pytest.raises(ValueError, match="Credentials are required"):
            await node.execute({})


# ============================================================================
# Dynamic options
# ============================================================================


class TestArcadsDynamicOptionsMock:
    @pytest.mark.asyncio
    async def test_load_product_options(self):
        with patch(
            "nodes.arcads_node._arcads_request",
            return_value={
                "status": "success",
                "data": {"data": [{"id": "p1", "name": "Widget"}]},
            },
        ) as request:
            result = await ArcadsNode.load_field_options(
                "product_id",
                {"client_id": "cid", "client_secret": "sec"},
                context={},
                page_token=None,
                search=None,
            )
        assert request.call_args.args == ("cid", "sec", "GET", "/v1/products")
        assert "options" in result
        assert result["options"][0]["value"] == "p1"
        assert result["options"][0]["label"] == "Widget"

    @pytest.mark.asyncio
    async def test_load_actor_options(self):
        with patch(
            "nodes.arcads_node._arcads_request",
            return_value={
                "status": "success",
                "data": {"actors": [{"id": "a1", "name": "Ava"}]},
            },
        ):
            result = await ArcadsNode.load_field_options(
                "actor_id",
                {"client_id": "cid", "client_secret": "sec"},
                context={},
                page_token=None,
                search=None,
            )
        assert result["options"][0]["value"] == "a1"
        assert result["options"][0]["label"] == "Ava"

    @pytest.mark.asyncio
    async def test_load_voice_options(self):
        with patch(
            "nodes.arcads_node._arcads_request",
            return_value={
                "status": "success",
                "data": [{"id": "v1", "name": "Calm"}],
            },
        ):
            result = await ArcadsNode.load_field_options(
                "voice_id",
                {"client_id": "cid", "client_secret": "sec"},
                context={},
                page_token=None,
                search=None,
            )
        assert result["options"][0]["value"] == "v1"

    @pytest.mark.asyncio
    async def test_load_unknown_field_returns_empty(self):
        result = await ArcadsNode.load_field_options(
            "nonexistent_field",
            {"client_id": "cid", "client_secret": "sec"},
            context={},
        )
        assert result == {"options": []}


# ============================================================================
# Trigger: on_generation_completed (poll-based)
# ============================================================================


async def _run_poll(config_obj, credentials, json_data, stored_state=None):
    """Run the poll trigger op with mocked httpx + mocked per-node cursor state.

    Returns (result, saved_state) where saved_state is what the node persisted
    via _save_node_state during the run."""
    config = ArcadsNodeConfig(config=config_obj, credentials=credentials)
    node = create_arcads_node(config)

    node._load_node_state = AsyncMock(return_value=stored_state or {})
    saved: Dict[str, Any] = {}

    async def _save(state):
        saved.update(state)

    node._save_node_state = AsyncMock(side_effect=_save)

    mock_client = create_mock_client(200, json_data)
    with patch("nodes.arcads_node.httpx.AsyncClient", return_value=mock_client):
        result = await node.execute({})
    return result, saved


class TestArcadsTriggerMock:
    def test_resolve_trigger_payload_returns_none_for_poll_op(self):
        """Poll-based trigger: resolve_trigger_payload must return None so the
        node's execute() runs and actually polls the API."""
        out = ArcadsNode.resolve_trigger_payload(
            {"some": "webhook payload"}, {"operation": "on_generation_completed"}
        )
        assert out is None

    def test_resolve_trigger_payload_passthrough_for_normal_op(self):
        """Non-trigger operations must pass the payload through unchanged."""
        payload = {"hello": "world"}
        out = ArcadsNode.resolve_trigger_payload(
            payload, {"operation": "list_products"}
        )
        assert out is payload

    @pytest.mark.asyncio
    async def test_poll_emits_only_completed_videos(self, credentials):
        """Polling the script's videos emits only videos in a completed status,
        skipping in-progress ones."""
        result, saved = await _run_poll(
            ArcadsOnGenerationCompletedConfig(script_id="s1"),
            credentials,
            {
                "data": [
                    {"id": "vid_1", "status": "ready"},
                    {"id": "vid_2", "status": "processing"},
                    {"id": "vid_3", "status": "completed"},
                ]
            },
        )
        assert result["status"] == "success"
        assert result["operation"] == "on_generation_completed"
        assert result["new_count"] == 2
        emitted_ids = {v["id"] for v in result["items"]}
        assert emitted_ids == {"vid_1", "vid_3"}
        # Cursor now carries both completed ids (the in-progress one is excluded)
        assert saved["last_seen_ids"] == ["vid_1", "vid_3"]

    @pytest.mark.asyncio
    async def test_poll_dedupes_via_stored_cursor(self, credentials):
        """A video already in the persisted cursor must not be re-emitted; only a
        newly completed one comes through."""
        result, saved = await _run_poll(
            ArcadsOnGenerationCompletedConfig(script_id="s1"),
            credentials,
            {
                "data": [
                    {"id": "vid_1", "status": "ready"},
                    {"id": "vid_2", "status": "ready"},
                ]
            },
            stored_state={"last_seen_ids": ["vid_1"]},
        )
        assert result["new_count"] == 1
        assert [v["id"] for v in result["items"]] == ["vid_2"]
        assert saved["last_seen_ids"] == ["vid_1", "vid_2"]

    @pytest.mark.asyncio
    async def test_poll_dedupes_via_config_cursor(self, credentials):
        """The config-supplied last_seen_ids seed also suppresses re-emission."""
        result, saved = await _run_poll(
            ArcadsOnGenerationCompletedConfig(script_id="s1", last_seen_ids=["vid_1"]),
            credentials,
            {
                "data": [
                    {"id": "vid_1", "status": "ready"},
                    {"id": "vid_2", "status": "ready"},
                ]
            },
        )
        assert result["new_count"] == 1
        assert [v["id"] for v in result["items"]] == ["vid_2"]

    @pytest.mark.asyncio
    async def test_poll_no_new_items_when_all_seen(self, credentials):
        """When every completed video is already in the cursor, nothing is emitted."""
        result, saved = await _run_poll(
            ArcadsOnGenerationCompletedConfig(script_id="s1"),
            credentials,
            {"data": [{"id": "vid_1", "status": "ready"}]},
            stored_state={"last_seen_ids": ["vid_1"]},
        )
        assert result["new_count"] == 0
        assert result["items"] == []
        assert saved["last_seen_ids"] == ["vid_1"]

    @pytest.mark.asyncio
    async def test_poll_surfaces_api_error(self, credentials):
        """An upstream API error is returned unchanged (no items emitted)."""
        config = ArcadsNodeConfig(
            config=ArcadsOnGenerationCompletedConfig(script_id="s1"),
            credentials=credentials,
        )
        node = create_arcads_node(config)
        node._load_node_state = AsyncMock(return_value={})
        node._save_node_state = AsyncMock()
        mock_client = create_mock_client(404, {"message": "Script not found"})
        with patch("nodes.arcads_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "error"
        assert result["status_code"] == 404
        # On error we do not advance the cursor.
        node._save_node_state.assert_not_called()


# Request contracts from https://external-api.arcads.ai/docs-json.
# These checks catch the old field names and missing required inputs even when
# a mocked server would accept any body.
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation, config_values, path, body",
    [
        (
            "create_project",
            {"folder_id": "123e4567-e89b-12d3-a456-426614174000", "name": "My Project"},
            "/v1/projects",
            {"folderId": "123e4567-e89b-12d3-a456-426614174000", "name": "My Project"},
        ),
        (
            "create_script",
            {
                "folder_id": "123e4567-e89b-12d3-a456-426614174000",
                "name": "My Project",
                "text": "Hello, this is a test script.",
            },
            "/v1/scripts",
            {
                "folderId": "123e4567-e89b-12d3-a456-426614174000",
                "name": "My Project",
                "text": "Hello, this is a test script.",
                "projectId": None,
                "videos": None,
            },
        ),
        (
            "generate_video",
            {
                "product_id": "40c97d04-b1b8-45fa-878d-4490a729bf5f",
                "prompt": "A futuristic city skyline at sunset",
                "model": "veo31",
            },
            "/v2/videos/generate",
            {
                "productId": "40c97d04-b1b8-45fa-878d-4490a729bf5f",
                "prompt": "A futuristic city skyline at sunset",
                "model": "veo31",
                "projectId": None,
                "aspectRatio": None,
                "resolution": None,
                "duration": None,
                "referenceImages": None,
            },
        ),
        (
            "generate_talking_actor",
            {
                "product_id": "40c97d04-b1b8-45fa-878d-4490a729bf5f",
                "text": "Hello, this is a test script.",
                "model": "arcads_1.0",
                "actors": [
                    {
                        "situationId": "40c97d04-b1b8-45fa-878d-4490a729bf5f",
                        "voiceId": "elevenlabs-voice-id",
                    }
                ],
            },
            "/v2/talking-actors/generate",
            {
                "productId": "40c97d04-b1b8-45fa-878d-4490a729bf5f",
                "script": "Hello, this is a test script.",
                "model": "arcads_1.0",
                "actors": [
                    {
                        "situationId": "40c97d04-b1b8-45fa-878d-4490a729bf5f",
                        "voiceId": "elevenlabs-voice-id",
                    }
                ],
                "projectId": None,
            },
        ),
        (
            "generate_preset",
            {
                "product_id": "40c97d04-b1b8-45fa-878d-4490a729bf5f",
                "situation_id": "40c97d04-b1b8-45fa-878d-4490a729bf5f",
                "reference_images": ["/tmp-uploads/avatar.png"],
            },
            "/v1/presets/camera-movement/generate",
            {
                "productId": "40c97d04-b1b8-45fa-878d-4490a729bf5f",
                "situationId": "40c97d04-b1b8-45fa-878d-4490a729bf5f",
                "referenceImages": ["/tmp-uploads/avatar.png"],
                "projectId": None,
                "aspectRatio": None,
                "strength": None,
            },
        ),
        (
            "get_presigned_url",
            {"file_type": "image/jpeg"},
            "/v1/file-upload/get-presigned-url",
            {"fileType": "image/jpeg"},
        ),
    ],
)
async def test_arcads_documented_request_bodies(
    credentials, operation, config_values, path, body
):
    config = ArcadsNodeConfig.model_validate(
        {
            "config": {"operation": operation, **config_values},
            "credentials": credentials.model_dump(),
        }
    )
    node = create_arcads_node(config)
    with patch(
        "nodes.arcads_node._arcads_request",
        new_callable=AsyncMock,
        return_value={"status": "success"},
    ) as request:
        await node.execute({})
    assert request.call_args.args[2:] == ("POST", path)
    assert request.call_args.kwargs["json_body"] == body


def test_arcads_script_requires_a_folder_or_project():
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="folder ID or project ID"):
        ArcadsCreateScriptConfig(
            name="My Project", text="Hello, this is a test script."
        )


def test_arcads_generation_requires_provider_inputs():
    from pydantic import ValidationError

    for config_type in (
        ArcadsGenerateVideoConfig,
        ArcadsGenerateImageConfig,
        ArcadsGenerateTalkingActorConfig,
        ArcadsGenerateVeo31Config,
        ArcadsGenerateOmnihumanConfig,
    ):
        with pytest.raises(ValidationError):
            config_type()


def test_arcads_connection_evidence_lists_workspace_products():
    evidence = ArcadsNode.connection_evidence
    assert evidence.operation == "list_products"
    assert evidence.noun == "products"
    assert evidence.proves == "account"
    assert not evidence.operation_arguments
