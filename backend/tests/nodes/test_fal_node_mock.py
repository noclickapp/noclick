"""Mock-based unit tests for the fal node — no live API calls."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from nodes.fal_node import (
    FalNode, FalNodeConfig, FalApiKeyCredential,
    FalRunModelConfig, FalSubmitQueueConfig, FalGetStatusConfig,
    FalGetResultConfig, FalCancelRequestConfig, FalInitiateUploadConfig,
    FalSearchModelsConfig, FalUsageConfig, FalListRequestsConfig,
    FalListKeysConfig, FalCreateKeyConfig, FalDeleteKeyConfig,
    FalJobCompletedTriggerConfig,
    FAL_RUN_BASE, FAL_QUEUE_BASE, FAL_PLATFORM_BASE, FAL_REST_BASE,
)


def make_node(config_obj, api_key="test-key-123"):
    creds = FalApiKeyCredential(api_key=api_key) if api_key else None
    return FalNode(
        node_id="test-node", node_type="automation-fal", node_data={},
        config=FalNodeConfig(config=config_obj, credentials=creds),
        sio=MagicMock(), sid="sid", workflow_id="wf", user_id="user",
    )


SUCCESS = {"status": "success", "action": "test", "data": {}, "status_code": 200, "timing_ms": {}}


def mock_fal(return_value=None):
    return patch("nodes.fal_node._fal_request", new_callable=AsyncMock,
                 return_value=return_value or SUCCESS)


# ── Model Run ──────────────────────────────────────────────────────────────────

class TestFalModelRunMock:
    @pytest.mark.asyncio
    async def test_run_model(self):
        resp = {**SUCCESS, "data": {"images": [{"url": "https://cdn.fal.ai/img.png"}]}}
        with mock_fal(resp) as m:
            result = await make_node(FalRunModelConfig(
                model_id="fal-ai/flux/dev", input='{"prompt":"test"}'
            )).execute({})
        assert result["status"] == "success"
        assert m.call_args.args[1] == "POST"
        assert FAL_RUN_BASE in m.call_args.args[2]
        assert "fal-ai/flux/dev" in m.call_args.args[2]

    @pytest.mark.asyncio
    async def test_run_model_with_subpath(self):
        with mock_fal() as m:
            await make_node(FalRunModelConfig(
                model_id="fal-ai/flux/dev", subpath="image-to-image", input="{}"
            )).execute({})
        assert "fal-ai/flux/dev/image-to-image" in m.call_args.args[2]

    @pytest.mark.asyncio
    async def test_run_model_invalid_json_raises(self):
        with pytest.raises(ValueError, match="valid JSON"):
            await make_node(FalRunModelConfig(model_id="fal-ai/test", input="not-json")).execute({})

    @pytest.mark.asyncio
    async def test_run_model_json_array_raises(self):
        with pytest.raises(ValueError, match="JSON object"):
            await make_node(FalRunModelConfig(model_id="fal-ai/test", input='[1,2,3]')).execute({})

    @pytest.mark.asyncio
    async def test_submit_queue(self):
        resp = {**SUCCESS, "data": {"request_id": "req_abc123", "status": "IN_QUEUE"}}
        with mock_fal(resp) as m:
            result = await make_node(FalSubmitQueueConfig(
                model_id="fal-ai/flux/dev", input='{"prompt":"async test"}'
            )).execute({})
        assert result["status"] == "success"
        assert result["data"]["request_id"] == "req_abc123"
        assert FAL_QUEUE_BASE in m.call_args.args[2]

    @pytest.mark.asyncio
    async def test_submit_queue_with_webhook(self):
        with mock_fal() as m:
            await make_node(FalSubmitQueueConfig(
                model_id="fal-ai/flux/dev",
                input="{}",
                webhook_url="https://test.hooks.example.test/wh",
            )).execute({})
        params = m.call_args.kwargs.get("params") or {}
        assert params.get("fal_webhook") == "https://test.hooks.example.test/wh"


# ── Queue Status / Result / Cancel ─────────────────────────────────────────────

class TestFalQueueMock:
    @pytest.mark.asyncio
    async def test_get_status_uses_post(self):
        """get_status must use POST — was incorrectly GET (returned 405)."""
        resp = {**SUCCESS, "data": {"status": "IN_PROGRESS", "logs": []}}
        with mock_fal(resp) as m:
            result = await make_node(FalGetStatusConfig(
                model_id="fal-ai/flux/dev", request_id="req_123", logs="false"
            )).execute({})
        assert result["status"] == "success"
        assert m.call_args.args[1] == "POST"
        assert "req_123/status" in m.call_args.args[2]

    @pytest.mark.asyncio
    async def test_get_status_with_logs(self):
        with mock_fal() as m:
            await make_node(FalGetStatusConfig(
                model_id="fal-ai/flux/dev", request_id="req_123", logs="true"
            )).execute({})
        params = m.call_args.kwargs.get("params") or {}
        assert params.get("logs") == "1"

    @pytest.mark.asyncio
    async def test_get_result_uses_post(self):
        """get_result must use POST — was incorrectly GET (returned 405)."""
        resp = {**SUCCESS, "data": {"images": [{"url": "https://cdn.fal.ai/result.png"}]}}
        with mock_fal(resp) as m:
            result = await make_node(FalGetResultConfig(
                model_id="fal-ai/flux/dev", request_id="req_123"
            )).execute({})
        assert result["status"] == "success"
        assert m.call_args.args[1] == "POST"
        assert "req_123" in m.call_args.args[2]

    @pytest.mark.asyncio
    async def test_cancel_request_uses_post(self):
        """cancel_request must use POST — was incorrectly PUT (returned 405)."""
        resp = {**SUCCESS, "data": {"status": "CANCELLED"}}
        with mock_fal(resp) as m:
            result = await make_node(FalCancelRequestConfig(
                model_id="fal-ai/flux/dev", request_id="req_123"
            )).execute({})
        assert result["status"] == "success"
        assert m.call_args.args[1] == "POST"
        assert "req_123/cancel" in m.call_args.args[2]


# ── Storage ────────────────────────────────────────────────────────────────────

class TestFalStorageMock:
    @pytest.mark.asyncio
    async def test_initiate_upload(self):
        resp = {**SUCCESS, "data": {"upload_url": "https://storage.fal.ai/presigned/xyz"}}
        with mock_fal(resp) as m:
            result = await make_node(FalInitiateUploadConfig(
                content_type="image/png", file_name="test.png"
            )).execute({})
        assert result["status"] == "success"
        assert m.call_args.args[1] == "POST"
        assert FAL_REST_BASE in m.call_args.args[2]
        body = m.call_args.kwargs.get("json_body") or {}
        assert body["content_type"] == "image/png"
        assert body["file_name"] == "test.png"

    @pytest.mark.asyncio
    async def test_initiate_upload_no_filename(self):
        with mock_fal() as m:
            await make_node(FalInitiateUploadConfig(content_type="application/octet-stream")).execute({})
        body = m.call_args.kwargs.get("json_body") or {}
        assert "file_name" not in body


# ── Platform: Models ───────────────────────────────────────────────────────────

class TestFalModelsMock:
    @pytest.mark.asyncio
    async def test_search_models(self):
        resp = {**SUCCESS, "data": {"models": [
            {"endpoint_id": "fal-ai/flux/dev", "metadata": {"display_name": "FLUX.1 [dev]"}},
        ]}}
        with mock_fal(resp) as m:
            result = await make_node(FalSearchModelsConfig(query="flux", limit="10")).execute({})
        assert result["status"] == "success"
        assert FAL_PLATFORM_BASE in m.call_args.args[2]

    @pytest.mark.asyncio
    async def test_get_usage(self):
        resp = {**SUCCESS, "data": {"time_series": [], "next_cursor": None}}
        with mock_fal(resp) as m:
            result = await make_node(FalUsageConfig(start_date="2026-06-01")).execute({})
        assert result["status"] == "success"
        assert "/models/usage" in m.call_args.args[2]

    @pytest.mark.asyncio
    async def test_list_requests(self):
        resp = {**SUCCESS, "data": {"items": [], "next_cursor": None}}
        with mock_fal(resp) as m:
            result = await make_node(FalListRequestsConfig(
                model_id="fal-ai/flux/dev", limit="10"
            )).execute({})
        assert result["status"] == "success"
        params = m.call_args.kwargs.get("params") or {}
        assert params.get("endpoint_id") == "fal-ai/flux/dev"


# ── Key Management ─────────────────────────────────────────────────────────────

class TestFalKeysMock:
    @pytest.mark.asyncio
    async def test_list_keys(self):
        resp = {**SUCCESS, "data": {"keys": [{"key_id": "k1", "alias": "prod"}]}}
        with mock_fal(resp) as m:
            result = await make_node(FalListKeysConfig(limit="20")).execute({})
        assert result["status"] == "success"
        assert len(result["data"]["keys"]) == 1
        assert m.call_args.args[1] == "GET"
        assert "/keys" in m.call_args.args[2]

    @pytest.mark.asyncio
    async def test_create_key(self):
        resp = {**SUCCESS, "status_code": 201, "data": {
            "key_id": "new-key-id", "key_secret": "secret-abc", "alias": "e2e-test"
        }}
        with mock_fal(resp) as m:
            result = await make_node(FalCreateKeyConfig(alias="e2e-test")).execute({})
        assert result["status"] == "success"
        assert m.call_args.args[1] == "POST"
        body = m.call_args.kwargs.get("json_body") or {}
        assert body.get("alias") == "e2e-test"

    @pytest.mark.asyncio
    async def test_create_key_empty_alias_raises(self):
        """fal returns 400 validation_error for empty alias; handler validates before calling API."""
        with pytest.raises(ValueError, match="Alias is required"):
            await make_node(FalCreateKeyConfig(alias="")).execute({})

    @pytest.mark.asyncio
    async def test_delete_key(self):
        resp = {**SUCCESS, "status_code": 204, "data": {"success": True}}
        with mock_fal(resp) as m:
            result = await make_node(FalDeleteKeyConfig(key_id="key-id-abc")).execute({})
        assert result["status"] == "success"
        assert m.call_args.args[1] == "DELETE"
        assert "key-id-abc" in m.call_args.args[2]


# ── Trigger ────────────────────────────────────────────────────────────────────

class TestFalTriggerMock:
    @pytest.mark.asyncio
    async def test_trigger_passthrough_completed(self):
        payload = {"status": "COMPLETED", "request_id": "req_abc", "response_url": "https://cdn.fal.ai/r"}
        node = make_node(FalJobCompletedTriggerConfig(webhook_url="https://test.hooks.example.test/wh"), api_key=None)
        result = await node.execute(payload)
        assert result["status"] == "success"
        assert result["action"] == "on_job_completed"
        assert result["data"]["status"] == "COMPLETED"
        assert result["data"]["request_id"] == "req_abc"

    @pytest.mark.asyncio
    async def test_trigger_passthrough_failed(self):
        payload = {"status": "FAILED", "request_id": "req_xyz", "error": "OOM"}
        node = make_node(FalJobCompletedTriggerConfig(webhook_url="https://test.hooks.example.test/wh"), api_key=None)
        result = await node.execute(payload)
        assert result["status"] == "success"
        assert result["data"]["error"] == "OOM"

    def test_verify_signature_valid(self):
        import hashlib, time as t, base64
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        private_key = Ed25519PrivateKey.generate()
        pub = private_key.public_key()
        x = base64.urlsafe_b64encode(pub.public_bytes_raw()).rstrip(b"=").decode()
        fake_keys = [{"kty": "OKP", "crv": "Ed25519", "x": x}]
        req_id = "req1"; user = "user1"; ts = str(int(t.time()))
        body = b'{"status":"COMPLETED"}'
        body_hash = hashlib.sha256(body).hexdigest()
        msg = "\n".join([req_id, user, ts, body_hash]).encode()
        sig_hex = private_key.sign(msg).hex()
        headers = {
            "x-fal-webhook-request-id": req_id,
            "x-fal-webhook-user-id": user,
            "x-fal-webhook-timestamp": ts,
            "x-fal-webhook-signature": sig_hex,
        }
        with patch.object(FalNode, "_get_jwks_keys", return_value=fake_keys):
            assert FalNode.verify_webhook_signature(body, headers, {})

    def test_verify_signature_wrong_sig_rejected(self):
        import time as t
        headers = {
            "x-fal-webhook-request-id": "r",
            "x-fal-webhook-user-id": "u",
            "x-fal-webhook-timestamp": str(int(t.time())),
            "x-fal-webhook-signature": "deadbeef" * 16,
        }
        with patch.object(FalNode, "_get_jwks_keys", return_value=[]):
            assert not FalNode.verify_webhook_signature(b"body", headers, {})

    def test_verify_signature_stale_rejected(self):
        import time as t
        headers = {
            "x-fal-webhook-request-id": "r",
            "x-fal-webhook-user-id": "u",
            "x-fal-webhook-timestamp": str(int(t.time()) - 400),
            "x-fal-webhook-signature": "aabbcc",
        }
        assert not FalNode.verify_webhook_signature(b"body", headers, {})

    def test_verify_signature_missing_headers_rejected(self):
        import time as t
        headers = {"x-fal-webhook-timestamp": str(int(t.time())), "x-fal-webhook-signature": "abc"}
        assert not FalNode.verify_webhook_signature(b"body", headers, {})


# ── Error Handling ─────────────────────────────────────────────────────────────

class TestFalErrorHandlingMock:
    @pytest.mark.asyncio
    async def test_missing_credentials_raises(self):
        node = make_node(FalSearchModelsConfig(limit="5"), api_key=None)
        with pytest.raises(ValueError, match="Credentials"):
            await node.execute({})

    @pytest.mark.asyncio
    async def test_api_error_propagated(self):
        err_resp = {
            "status": "error", "action": "search_models",
            "error": "Unauthorized", "status_code": 401, "timing_ms": {}
        }
        with mock_fal(err_resp):
            result = await make_node(FalSearchModelsConfig(limit="5")).execute({})
        assert result["status"] == "error"
        assert result["status_code"] == 401


# ── Dynamic Options ────────────────────────────────────────────────────────────

class TestFalDynamicOptionsMock:
    @pytest.mark.asyncio
    async def test_load_model_options(self):
        models_resp = {**SUCCESS, "data": {"models": [
            {"endpoint_id": "fal-ai/flux/dev", "title": "FLUX.1 [dev]"},
            {"endpoint_id": "fal-ai/fast-sdxl", "title": "Fast SDXL"},
        ]}}
        mock_cred = {"api_key": "test-key"}
        with patch("utils.credential_loader.load_credential", new_callable=AsyncMock, return_value=mock_cred):
            with patch("nodes.fal_node._fal_request", new_callable=AsyncMock, return_value=models_resp):
                result = await FalNode.load_field_options(
                    field_name="model_id",
                    user_id="user",
                    config_data={},
                    credential_ids={"fal_api_key": "cred_123"},
                    pool=MagicMock(),
                )
        opts = result.get("options", [])
        assert len(opts) == 2
        assert opts[0]["value"] == "fal-ai/flux/dev"
        assert "FLUX.1 [dev]" in opts[0]["label"]

    @pytest.mark.asyncio
    async def test_load_unknown_field_returns_empty(self):
        result = await FalNode.load_field_options(
            field_name="unknown_field",
            user_id="user",
            config_data={},
            credential_ids={},
            pool=MagicMock(),
        )
        assert result == {"options": []}
