"""
Mock tests for the Google Cloud Translation node.

Exercises every operation with mocked HTTP responses (no live API calls):
- v2 Basic (API key): translate, detect, list languages
- v3 Advanced (OAuth Bearer + project): translate, detect, supported languages,
  romanize, translate document, batch translate, glossaries
  (create / list), get operation status
- Error handling: API errors, missing credentials, wrong-credential-for-edition
- Dynamic options: language dropdown

Run: pytest nodes/tests/test_google_translate_node_mock.py -v
"""

import pytest
from unittest.mock import Mock, patch

from nodes.google_translate_node import (
    GoogleTranslateNode,
    GoogleTranslateNodeConfig,
    GoogleTranslateOAuthCredential,
    GoogleTranslateApiKeyCredential,
    GoogleTranslateServiceAccountCredential,
    # v3 Advanced
    GoogleTranslateV3TranslateConfig,
    GoogleTranslateV3DetectConfig,
    GoogleTranslateV3LanguagesConfig,
    GoogleTranslateRomanizeConfig,
    GoogleTranslateTranslateDocumentConfig,
    GoogleTranslateBatchTranslateTextConfig,
    GoogleTranslateCreateGlossaryConfig,
    GoogleTranslateListGlossariesConfig,
    GoogleTranslateGetOperationConfig,
    # v2 Basic
    GoogleTranslateV2TranslateConfig,
    GoogleTranslateV2DetectConfig,
    GoogleTranslateV2LanguagesConfig,
    # Trigger
    GoogleTranslateOnBatchCompletedConfig,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def api_key_credentials():
    return GoogleTranslateApiKeyCredential(
        api_key="AIza_test_key_12345", project_id="my-gcp-project"
    )


@pytest.fixture
def oauth_credentials():
    return GoogleTranslateOAuthCredential(
        access_token="ya29.test_access_token",
        refresh_token="1//test_refresh_token",
        expires_at="2030-01-01T00:00:00Z",
        email="user@example.com",
        project_id="my-gcp-project",
    )


def create_node(config, node_data=None):
    return GoogleTranslateNode(
        node_id="test-google-translate-node",
        node_type="automation-google-translate",
        node_data=node_data or {},
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


# Patch token refresh so v3 tests don't touch the DB/OAuth refresh path.
def _patch_token():
    async def _fake(self, credentials):
        return credentials.access_token

    return patch.object(GoogleTranslateNode, "_ensure_fresh_token", _fake)


# ---------------------------------------------------------------------------
# v3 Advanced (OAuth) operations
# ---------------------------------------------------------------------------


class TestGoogleTranslateV3Mock:
    @pytest.mark.asyncio
    async def test_v3_translate_text(self, oauth_credentials):
        config = GoogleTranslateNodeConfig(
            config=GoogleTranslateV3TranslateConfig(
                text="Hello world", target_language="es"
            ),
            credentials=oauth_credentials,
        )
        node = create_node(config)
        mock_client = create_mock_client(
            200, {"translations": [{"translatedText": "Hola mundo"}]}
        )
        with _patch_token(), patch(
            "nodes.google_translate_node.httpx.AsyncClient", return_value=mock_client
        ):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "v3_translate_text"
        assert result["data"]["translations"][0]["translatedText"] == "Hola mundo"

    @pytest.mark.asyncio
    async def test_v3_detect_language(self, oauth_credentials):
        config = GoogleTranslateNodeConfig(
            config=GoogleTranslateV3DetectConfig(text="Bonjour"),
            credentials=oauth_credentials,
        )
        node = create_node(config)
        mock_client = create_mock_client(
            200, {"languages": [{"languageCode": "fr", "confidence": 0.99}]}
        )
        with _patch_token(), patch(
            "nodes.google_translate_node.httpx.AsyncClient", return_value=mock_client
        ):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "v3_detect_language"
        assert result["data"]["languages"][0]["languageCode"] == "fr"

    @pytest.mark.asyncio
    async def test_v3_supported_languages(self, oauth_credentials):
        config = GoogleTranslateNodeConfig(
            config=GoogleTranslateV3LanguagesConfig(display_language="en"),
            credentials=oauth_credentials,
        )
        node = create_node(config)
        mock_client = create_mock_client(
            200, {"languages": [{"languageCode": "es", "displayName": "Spanish"}]}
        )
        with _patch_token(), patch(
            "nodes.google_translate_node.httpx.AsyncClient", return_value=mock_client
        ):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "v3_supported_languages"
        assert result["data"]["languages"][0]["languageCode"] == "es"

    @pytest.mark.asyncio
    async def test_v3_romanize_text(self, oauth_credentials):
        config = GoogleTranslateNodeConfig(
            config=GoogleTranslateRomanizeConfig(
                text="こんにちは", source_language="ja"
            ),
            credentials=oauth_credentials,
        )
        node = create_node(config)
        mock_client = create_mock_client(
            200, {"romanizations": [{"romanizedText": "konnichiwa"}]}
        )
        with _patch_token(), patch(
            "nodes.google_translate_node.httpx.AsyncClient", return_value=mock_client
        ):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "v3_romanize_text"
        assert result["data"]["romanizations"][0]["romanizedText"] == "konnichiwa"

    @pytest.mark.asyncio
    async def test_v3_translate_document(self, oauth_credentials):
        config = GoogleTranslateNodeConfig(
            config=GoogleTranslateTranslateDocumentConfig(
                document_content="JVBERi0xLjQK",
                target_language="es",
            ),
            credentials=oauth_credentials,
        )
        node = create_node(config)
        mock_client = create_mock_client(
            200, {"documentTranslation": {"mimeType": "application/pdf"}}
        )
        with _patch_token(), patch(
            "nodes.google_translate_node.httpx.AsyncClient", return_value=mock_client
        ):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "v3_translate_document"

    @pytest.mark.asyncio
    async def test_v3_batch_translate_text(self, oauth_credentials):
        config = GoogleTranslateNodeConfig(
            config=GoogleTranslateBatchTranslateTextConfig(
                source_language="en",
                target_languages="es,fr",
                input_gcs_uri="gs://bucket/in.tsv",
                output_gcs_uri_prefix="gs://bucket/out/",
            ),
            credentials=oauth_credentials,
        )
        node = create_node(config)
        mock_client = create_mock_client(
            200, {"name": "projects/p/locations/us-central1/operations/op123", "done": False}
        )
        with _patch_token(), patch(
            "nodes.google_translate_node.httpx.AsyncClient", return_value=mock_client
        ):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "v3_batch_translate_text"
        assert "operations/op123" in result["data"]["name"]

    @pytest.mark.asyncio
    async def test_v3_create_glossary(self, oauth_credentials):
        config = GoogleTranslateNodeConfig(
            config=GoogleTranslateCreateGlossaryConfig(
                glossary_id="my-glossary",
                source_language="en",
                target_language="es",
                input_gcs_uri="gs://bucket/glossary.csv",
            ),
            credentials=oauth_credentials,
        )
        node = create_node(config)
        mock_client = create_mock_client(
            200, {"name": "projects/p/locations/us-central1/operations/g1", "done": False}
        )
        with _patch_token(), patch(
            "nodes.google_translate_node.httpx.AsyncClient", return_value=mock_client
        ):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "v3_create_glossary"

    @pytest.mark.asyncio
    async def test_v3_list_glossaries(self, oauth_credentials):
        config = GoogleTranslateNodeConfig(
            config=GoogleTranslateListGlossariesConfig(),
            credentials=oauth_credentials,
        )
        node = create_node(config)
        mock_client = create_mock_client(
            200, {"glossaries": [{"name": "projects/p/locations/us-central1/glossaries/g"}]}
        )
        with _patch_token(), patch(
            "nodes.google_translate_node.httpx.AsyncClient", return_value=mock_client
        ):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "v3_list_glossaries"
        assert len(result["data"]["glossaries"]) == 1

    @pytest.mark.asyncio
    async def test_v3_get_operation(self, oauth_credentials):
        config = GoogleTranslateNodeConfig(
            config=GoogleTranslateGetOperationConfig(operation_name="op123"),
            credentials=oauth_credentials,
        )
        node = create_node(config)
        mock_client = create_mock_client(
            200, {"name": "op123", "done": True, "response": {}}
        )
        with _patch_token(), patch(
            "nodes.google_translate_node.httpx.AsyncClient", return_value=mock_client
        ):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "v3_get_operation"
        assert result["data"]["done"] is True


# ---------------------------------------------------------------------------
# v2 Basic (API key) operations
# ---------------------------------------------------------------------------


class TestGoogleTranslateV2Mock:
    @pytest.mark.asyncio
    async def test_v2_translate_text(self, api_key_credentials):
        config = GoogleTranslateNodeConfig(
            config=GoogleTranslateV2TranslateConfig(
                text="Hello", target_language="de"
            ),
            credentials=api_key_credentials,
        )
        node = create_node(config)
        mock_client = create_mock_client(
            200,
            {"data": {"translations": [{"translatedText": "Hallo", "detectedSourceLanguage": "en"}]}},
        )
        with patch(
            "nodes.google_translate_node.httpx.AsyncClient", return_value=mock_client
        ):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "v2_translate_text"
        assert result["data"]["data"]["translations"][0]["translatedText"] == "Hallo"

    @pytest.mark.asyncio
    async def test_v2_detect_language(self, api_key_credentials):
        config = GoogleTranslateNodeConfig(
            config=GoogleTranslateV2DetectConfig(text="Hola"),
            credentials=api_key_credentials,
        )
        node = create_node(config)
        mock_client = create_mock_client(
            200, {"data": {"detections": [[{"language": "es", "confidence": 0.98}]]}}
        )
        with patch(
            "nodes.google_translate_node.httpx.AsyncClient", return_value=mock_client
        ):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "v2_detect_language"
        assert result["data"]["data"]["detections"][0][0]["language"] == "es"

    @pytest.mark.asyncio
    async def test_v2_list_languages(self, api_key_credentials):
        config = GoogleTranslateNodeConfig(
            config=GoogleTranslateV2LanguagesConfig(target_language="en"),
            credentials=api_key_credentials,
        )
        node = create_node(config)
        mock_client = create_mock_client(
            200, {"data": {"languages": [{"language": "es", "name": "Spanish"}]}}
        )
        with patch(
            "nodes.google_translate_node.httpx.AsyncClient", return_value=mock_client
        ):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "v2_list_languages"
        assert result["data"]["data"]["languages"][0]["language"] == "es"


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestGoogleTranslateErrorHandlingMock:
    @pytest.mark.asyncio
    async def test_api_error(self, api_key_credentials):
        config = GoogleTranslateNodeConfig(
            config=GoogleTranslateV2TranslateConfig(text="x", target_language="zz"),
            credentials=api_key_credentials,
        )
        node = create_node(config)
        mock_client = create_mock_client(
            400, {"error": {"message": "Invalid Value", "code": 400}}
        )
        with patch(
            "nodes.google_translate_node.httpx.AsyncClient", return_value=mock_client
        ):
            result = await node.execute({})
        assert result["status"] == "error"
        assert result["status_code"] == 400
        assert "invalid value" in str(result["error"]).lower()

    @pytest.mark.asyncio
    async def test_missing_credentials(self):
        config = GoogleTranslateNodeConfig(
            config=GoogleTranslateV2LanguagesConfig(), credentials=None
        )
        node = create_node(config)
        with pytest.raises(ValueError, match="Credentials are required"):
            await node.execute({})

    @pytest.mark.asyncio
    async def test_v3_requires_oauth_not_api_key(self, api_key_credentials):
        """A v3 op with an API-key credential is rejected (v3 has no API-key path)."""
        config = GoogleTranslateNodeConfig(
            config=GoogleTranslateV3TranslateConfig(
                text="hi", target_language="es"
            ),
            credentials=api_key_credentials,
        )
        node = create_node(config)
        with pytest.raises(ValueError, match="OAuth"):
            await node.execute({})

    @pytest.mark.asyncio
    async def test_v2_works_with_oauth_bearer(self, oauth_credentials):
        """v2 Basic also accepts an OAuth Bearer token (not just an API key), so a
        single OAuth credential can run every operation in the node."""
        config = GoogleTranslateNodeConfig(
            config=GoogleTranslateV2TranslateConfig(text="hi", target_language="es"),
            credentials=oauth_credentials,
        )
        node = create_node(config)
        captured = {}

        async def async_request(*args, **kwargs):
            captured.update(kwargs)
            return create_mock_response(200, {"data": {"translations": [{"translatedText": "hola"}]}})

        mock_client = create_mock_client()
        mock_client.request = async_request
        with _patch_token(), patch(
            "nodes.google_translate_node.httpx.AsyncClient", return_value=mock_client
        ):
            result = await node.execute({})
        assert result["status"] == "success"
        assert captured["headers"]["Authorization"].startswith("Bearer ")
        assert "key" not in (captured.get("params") or {})

    @pytest.mark.asyncio
    async def test_v3_requires_project_id(self):
        """A v3 op with no project id (credential or node) available is rejected."""
        cred = GoogleTranslateOAuthCredential(
            access_token="ya29.t", refresh_token="r",
            expires_at="2030-01-01T00:00:00Z", email="u@e.com",
        )  # no project_id
        config = GoogleTranslateNodeConfig(
            config=GoogleTranslateV3DetectConfig(text="hi"), credentials=cred
        )
        node = create_node(config)  # no project_id in node_data either
        with _patch_token():
            with pytest.raises(ValueError, match="project ID"):
                await node.execute({})

    @pytest.mark.asyncio
    async def test_v3_node_level_project_id(self):
        """The node-level project_id on the op config satisfies v3 even when the
        OAuth credential carries no project (the UI's only reachable place to set
        it), and it is what scopes the request path."""
        cred = GoogleTranslateOAuthCredential(
            access_token="ya29.t", refresh_token="r",
            expires_at="2030-01-01T00:00:00Z", email="u@e.com",
        )  # no project_id on the credential
        config = GoogleTranslateNodeConfig(
            config=GoogleTranslateV3DetectConfig(text="hi", project_id="node-proj"),
            credentials=cred,
        )
        node = create_node(config)
        captured = {}

        async def async_request(*args, **kwargs):
            captured.update(kwargs)
            return create_mock_response(200, {"languages": [{"languageCode": "en"}]})

        mock_client = create_mock_client()
        mock_client.request = async_request
        with _patch_token(), patch(
            "nodes.google_translate_node.httpx.AsyncClient", return_value=mock_client
        ):
            result = await node.execute({})
        assert result["status"] == "success"
        assert "projects/node-proj/locations/" in captured["url"]
        assert captured["headers"]["x-goog-user-project"] == "node-proj"


# ---------------------------------------------------------------------------
# Dynamic options
# ---------------------------------------------------------------------------


class TestGoogleTranslateDynamicOptionsMock:
    @pytest.mark.asyncio
    async def test_load_language_options_v2(self):
        """v2 API-key credential lists languages via the Basic /languages endpoint."""
        with patch(
            "nodes.google_translate_node._google_translate_request",
            return_value={
                "status": "success",
                "data": {"data": {"languages": [{"language": "es", "name": "Spanish"}]}},
            },
        ):
            result = await GoogleTranslateNode.load_field_options(
                "target_language",
                credential_data={"api_key": "AIza_test", "credential_type": "google_translate_api_key"},
                context={},
            )
        assert result["options"][0]["value"] == "es"
        assert "Spanish" in result["options"][0]["label"]

    @pytest.mark.asyncio
    async def test_load_language_options_oauth_bearer(self):
        """An OAuth credential lists languages via the v2 /languages endpoint with a
        Bearer token (no project required), so the dropdown works without a project."""
        captured = {}

        async def _req(method, url, **kwargs):
            captured.update(url=url, headers=kwargs.get("headers") or {}, params=kwargs.get("params") or {})
            return {"status": "success", "data": {"data": {"languages": [{"language": "ja", "name": "Japanese"}]}}}

        with patch("nodes.google_translate_node._google_translate_request", _req):
            result = await GoogleTranslateNode.load_field_options(
                "source_language",
                credential_data={"access_token": "ya29.tok"},  # note: no project_id
                context={},
            )
        assert result["options"][0]["value"] == "ja"
        assert "Japanese" in result["options"][0]["label"]
        # authorised via Bearer against the v2 /languages endpoint, no ?key=
        assert captured["url"].endswith("/languages")
        assert captured["headers"]["Authorization"].startswith("Bearer ")
        assert "key" not in captured["params"]


# ---------------------------------------------------------------------------
# Poll-based trigger: on_batch_completed
# ---------------------------------------------------------------------------


class TestGoogleTranslateTriggerMock:
    def test_resolve_trigger_payload_returns_none_for_trigger(self):
        """The poll trigger returns None so execute() runs and polls the API."""
        payload = {"_webhook": {"id": "wh"}, "foo": "bar"}
        assert (
            GoogleTranslateNode.resolve_trigger_payload(
                payload, {"operation": "on_batch_completed"}
            )
            is None
        )

    def test_resolve_trigger_payload_passthrough_for_normal_op(self):
        """Non-trigger ops have no webhook delivery -> payload passes through."""
        payload = {"some": "data"}
        assert (
            GoogleTranslateNode.resolve_trigger_payload(
                payload, {"operation": "v3_translate_text"}
            )
            == payload
        )

    def test_trigger_produced_no_event(self):
        """Empty poll output suppresses downstream; non-empty propagates."""
        assert GoogleTranslateNode.trigger_produced_no_event(
            None, {"operation": "on_batch_completed", "operations": []}
        )
        assert not GoogleTranslateNode.trigger_produced_no_event(
            None,
            {"operation": "on_batch_completed", "operations": [{"name": "op1"}]},
        )

    @staticmethod
    def _bind_memory_state(node):
        """Back the node's CAS state update with an in-memory store so the dedup
        seen-set round-trips across polls without a database. Mirrors
        ``_update_node_state``'s contract: run the mutator against the current
        state, persist the returned new_state (``None`` → no write), return the
        mutator's result. Seed ``store['seen_operation_ids']`` to simulate a poll
        past the first-poll baseline."""
        store: dict = {}

        async def _update(mutator, *, max_retries=4, skip_result=None):
            new_state, result = mutator(dict(store))
            if new_state is not None:
                store.clear()
                store.update(new_state)
            return result

        node._update_node_state = _update
        return store

    @pytest.mark.asyncio
    async def test_trigger_baselines_on_first_poll(self, oauth_credentials):
        """First poll baselines: it records the currently-completed operations as
        seen and emits NOTHING, so enabling the trigger never floods the workflow
        with every pre-existing batch/glossary/model job."""
        config = GoogleTranslateNodeConfig(
            config=GoogleTranslateOnBatchCompletedConfig(location="us-central1"),
            credentials=oauth_credentials,
        )
        node = create_node(config)
        store = self._bind_memory_state(node)
        ops_payload = {
            "operations": [
                {"name": "projects/p/locations/us-central1/operations/op1", "done": True},
                {"name": "projects/p/locations/us-central1/operations/op2", "done": True},
            ]
        }
        mock_client = create_mock_client(200, ops_payload)
        with _patch_token(), patch(
            "nodes.google_translate_node.httpx.AsyncClient", return_value=mock_client
        ):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["operation"] == "on_batch_completed"
        # Baseline emits nothing, so trigger_produced_no_event halts downstream.
        assert result["new_count"] == 0
        assert result["operations"] == []
        assert node.trigger_produced_no_event(result) is True
        # Persistent seen-set seeded with both currently-completed operation names.
        assert set(store["seen_operation_ids"]) == {
            "projects/p/locations/us-central1/operations/op1",
            "projects/p/locations/us-central1/operations/op2",
        }

    @pytest.mark.asyncio
    async def test_trigger_emits_only_new_when_seeded(self, oauth_credentials):
        """A poll on top of a seeded seen-set (i.e. not the first poll) emits only
        operations whose name is not already recorded, then unions the seen-set."""
        config = GoogleTranslateNodeConfig(
            config=GoogleTranslateOnBatchCompletedConfig(location="us-central1"),
            credentials=oauth_credentials,
        )
        node = create_node(config)
        store = self._bind_memory_state(node)
        op1 = "projects/p/locations/us-central1/operations/op1"
        op2 = "projects/p/locations/us-central1/operations/op2"
        store["seen_operation_ids"] = [op1]  # op1 already emitted on a prior poll

        mock_client = create_mock_client(
            200,
            {"operations": [{"name": op1, "done": True}, {"name": op2, "done": True}]},
        )
        with _patch_token(), patch(
            "nodes.google_translate_node.httpx.AsyncClient", return_value=mock_client
        ):
            result = await node.execute({})
        assert result["new_count"] == 1
        assert [op["name"] for op in result["operations"]] == [op2]
        assert set(store["seen_operation_ids"]) == {op1, op2}

    @pytest.mark.asyncio
    async def test_trigger_dedupes_across_polls(self, oauth_credentials):
        """Round-trip: the first poll baselines op1 (emits nothing, seeds the
        seen-set); a second poll (op1 still done, op2 newly done) re-uses the
        persisted seen-set and emits only op2."""
        config = GoogleTranslateNodeConfig(
            config=GoogleTranslateOnBatchCompletedConfig(location="us-central1"),
            credentials=oauth_credentials,
        )
        node = create_node(config)
        store = self._bind_memory_state(node)
        op1 = "projects/p/locations/us-central1/operations/op1"
        op2 = "projects/p/locations/us-central1/operations/op2"

        # First poll: only op1 is done — baselines (emits nothing, seeds op1).
        client1 = create_mock_client(200, {"operations": [{"name": op1, "done": True}]})
        with _patch_token(), patch(
            "nodes.google_translate_node.httpx.AsyncClient", return_value=client1
        ):
            r1 = await node.execute({})
        assert r1["new_count"] == 0
        assert r1["operations"] == []
        assert set(store["seen_operation_ids"]) == {op1}

        # Second poll: op1 still returned (already seen) + op2 newly done.
        client2 = create_mock_client(
            200,
            {"operations": [{"name": op1, "done": True}, {"name": op2, "done": True}]},
        )
        with _patch_token(), patch(
            "nodes.google_translate_node.httpx.AsyncClient", return_value=client2
        ):
            r2 = await node.execute({})
        assert r2["new_count"] == 1
        assert [op["name"] for op in r2["operations"]] == [op2]
        # Seen-set now covers both, so a third poll would emit nothing.
        assert set(store["seen_operation_ids"]) == {op1, op2}

    @pytest.mark.asyncio
    async def test_trigger_ignores_in_progress_operations(self, oauth_credentials):
        """Operations not yet done=true are excluded even if returned (seeded past
        the first-poll baseline so completed ops actually emit)."""
        config = GoogleTranslateNodeConfig(
            config=GoogleTranslateOnBatchCompletedConfig(location="us-central1"),
            credentials=oauth_credentials,
        )
        node = create_node(config)
        store = self._bind_memory_state(node)
        store["seen_operation_ids"] = []  # past the baseline: emit newly-done ops
        ops_payload = {
            "operations": [
                {"name": "projects/p/locations/us-central1/operations/running", "done": False},
                {"name": "projects/p/locations/us-central1/operations/finished", "done": True},
            ]
        }
        mock_client = create_mock_client(200, ops_payload)
        with _patch_token(), patch(
            "nodes.google_translate_node.httpx.AsyncClient", return_value=mock_client
        ):
            result = await node.execute({})
        assert result["new_count"] == 1
        assert [op["name"] for op in result["operations"]] == [
            "projects/p/locations/us-central1/operations/finished"
        ]


class TestGoogleTranslateServiceAccountMock:
    @pytest.mark.asyncio
    async def test_v3_translate_with_service_account(self):
        """A v3 op authenticated with a service-account key exchanges a token and
        uses the project from the JSON key."""
        cred = GoogleTranslateServiceAccountCredential(
            client_email="svc@proj.iam.gserviceaccount.com",
            private_key="-----BEGIN PRIVATE KEY-----\nX\n-----END PRIVATE KEY-----\n",
            project_id="sa-project",
        )
        config = GoogleTranslateNodeConfig(
            config=GoogleTranslateV3TranslateConfig(text="Hi", target_language="es"),
            credentials=cred,
        )
        node = create_node(config)
        mock_client = create_mock_client(200, {"translations": [{"translatedText": "Hola"}]})
        async def _fake_exchange(credentials):
            assert credentials.project_id == "sa-project"
            return "ya29.sa_token"
        with patch("nodes.google_translate_node._exchange_service_account_access_token", _fake_exchange), patch(
            "nodes.google_translate_node.httpx.AsyncClient", return_value=mock_client
        ):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "v3_translate_text"
        assert result["data"]["translations"][0]["translatedText"] == "Hola"
