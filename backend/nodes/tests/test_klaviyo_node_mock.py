"""
Mock tests for the Klaviyo node.

Exercises operations with mocked HTTP responses (no live API calls):
- Auth: private-API-key header (Klaviyo-API-Key) vs OAuth Bearer, the mandatory
  `revision` date header, and the JSON:API Accept/Content-Type
- JSON:API request bodies ({data:{type,attributes}}), id-in-body-and-path on
  update, relationship arrays, and the special non-REST paths (upsert/merge/clone)
- Profiles, subscriptions, lists, segments, events, metrics, campaigns, flows,
  templates, catalogs, coupons, tags, images, webhooks
- The on_event push trigger: registration body + secret capture + HMAC verify
- Dynamic dropdowns + JSON:API error extraction
"""

import hashlib
import hmac
import json
import pytest
from unittest.mock import Mock, patch, AsyncMock

from nodes.klaviyo_node import (
    KlaviyoNode, KlaviyoNodeConfig, KlaviyoApiKeyCredential, KlaviyoOAuthCredential,
    KLAVIYO_REVISION,
    KlaviyoGetProfileConfig, KlaviyoCreateProfileConfig, KlaviyoUpdateProfileConfig,
    KlaviyoUpsertProfileConfig, KlaviyoMergeProfilesConfig,
    KlaviyoSubscribeProfilesConfig, KlaviyoUnsubscribeProfilesConfig,
    KlaviyoListListsConfig, KlaviyoCreateListConfig, KlaviyoAddToListConfig, KlaviyoRemoveFromListConfig,
    KlaviyoListSegmentsConfig, KlaviyoCreateSegmentConfig,
    KlaviyoCreateEventConfig, KlaviyoListMetricsConfig, KlaviyoQueryMetricAggregatesConfig,
    KlaviyoListCampaignsConfig, KlaviyoSendCampaignConfig, KlaviyoCloneCampaignConfig,
    KlaviyoUpdateFlowStatusConfig, KlaviyoCreateTemplateConfig, KlaviyoRenderTemplateConfig,
    KlaviyoCreateCatalogItemConfig, KlaviyoCreateCouponConfig, KlaviyoCreateTagConfig,
    KlaviyoUploadImageUrlConfig, KlaviyoGetAccountConfig, KlaviyoRequestDeletionConfig,
    KlaviyoCreateWebhookConfig, KlaviyoListWebhookTopicsConfig, KlaviyoOnEventConfig,
)


@pytest.fixture
def api_key_credentials():
    return KlaviyoApiKeyCredential(api_key="pk_test123")


@pytest.fixture
def oauth_credentials():
    return KlaviyoOAuthCredential(access_token="tok-abc", refresh_token="r", expires_at="2099-12-31T23:59:59Z")


def create_node(config):
    return KlaviyoNode(node_id="k", node_type="automation-klaviyo", node_data={}, config=config,
                       sio=Mock(), sid="s", workflow_id="w", user_id="u")


def create_mock_client(status_code=200, json_data=None, headers=None, content=b"{}"):
    resp = Mock()
    resp.status_code = status_code
    resp.text = ""
    resp.content = content
    resp.headers = headers if headers is not None else {"content-type": "application/vnd.api+json"}
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


async def _run(config, credentials, mc):
    node = create_node(KlaviyoNodeConfig(config=config, credentials=credentials))
    with patch("nodes.klaviyo_node.httpx.AsyncClient", return_value=mc):
        return await node.execute({})


class TestKlaviyoAuth:
    @pytest.mark.asyncio
    async def test_api_key_header_and_revision(self, api_key_credentials):
        mc = create_mock_client(200, {"data": []})
        await _run(KlaviyoListListsConfig(), api_key_credentials, mc)
        h = last(mc)["headers"]
        assert h["Authorization"] == "Klaviyo-API-Key pk_test123"
        assert h["revision"] == KLAVIYO_REVISION
        assert h["Accept"] == "application/vnd.api+json"

    @pytest.mark.asyncio
    async def test_oauth_bearer(self, oauth_credentials):
        mc = create_mock_client(200, {"data": []})
        with patch("nodes.core.oauth_refresh.ensure_fresh_oauth_token", new=AsyncMock(return_value="tok-abc")):
            await _run(KlaviyoListListsConfig(), oauth_credentials, mc)
        assert last(mc)["headers"]["Authorization"] == "Bearer tok-abc"

    @pytest.mark.asyncio
    async def test_base_url(self, api_key_credentials):
        mc = create_mock_client(200, {"data": []})
        await _run(KlaviyoListListsConfig(), api_key_credentials, mc)
        assert last(mc)["url"] == "https://a.klaviyo.com/api/lists/"

    @pytest.mark.asyncio
    async def test_missing_credentials(self):
        node = create_node(KlaviyoNodeConfig(config=KlaviyoListListsConfig(), credentials=None))
        with pytest.raises(ValueError, match="Credentials are required"):
            await node.execute({})


class TestKlaviyoRevoke:
    """Token revocation on credential delete (marketplace uninstall)."""

    @pytest.mark.asyncio
    async def test_revoke_posts_basic_auth_and_body(self):
        from nodes.oauth.klaviyo_oauth import revoke_token, KLAVIYO_REVOKE_URL, _basic_auth

        mock_resp = Mock()
        mock_resp.status_code = 200
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp) as mock_post:
            ok = await revoke_token("rt-123", token_type_hint="refresh_token", client_id="cid", client_secret="csec")

        assert ok is True
        assert mock_post.call_args[0][0] == KLAVIYO_REVOKE_URL
        body = mock_post.call_args[1]["data"]
        assert body == {"token": "rt-123", "token_type_hint": "refresh_token"}
        assert mock_post.call_args[1]["headers"]["Authorization"] == _basic_auth("cid", "csec")

    @pytest.mark.asyncio
    async def test_revoke_never_raises_on_error(self):
        from nodes.oauth.klaviyo_oauth import revoke_token

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, side_effect=Exception("boom")):
            assert await revoke_token("rt", client_id="c", client_secret="s") is False

    @pytest.mark.asyncio
    async def test_revoke_returns_false_on_non_2xx(self):
        from nodes.oauth.klaviyo_oauth import revoke_token

        mock_resp = Mock()
        mock_resp.status_code = 400
        mock_resp.text = "bad"
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp):
            assert await revoke_token("rt", client_id="c", client_secret="s") is False

    @pytest.mark.asyncio
    async def test_revoke_empty_token_noop(self):
        from nodes.oauth.klaviyo_oauth import revoke_token

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            assert await revoke_token("", client_id="c", client_secret="s") is False
        mock_post.assert_not_called()

    def test_revoke_importable_from_handler(self):
        from wss.handlers.credentials_handler import revoke_klaviyo_token  # noqa: F401


class TestKlaviyoJsonApi:
    @pytest.mark.asyncio
    async def test_create_profile_body(self, api_key_credentials):
        mc = create_mock_client(201, {"data": {"id": "P1"}})
        await _run(KlaviyoCreateProfileConfig(email="a@b.com", first_name="Ada", properties_json='{"plan":"pro"}'), api_key_credentials, mc)
        call = last(mc)
        assert call["method"] == "POST" and call["url"].endswith("/profiles/")
        assert call["json"] == {"data": {"type": "profile", "attributes": {"email": "a@b.com", "first_name": "Ada", "properties": {"plan": "pro"}}}}
        assert last(mc)["headers"]["Content-Type"] == "application/vnd.api+json"

    @pytest.mark.asyncio
    async def test_update_profile_id_in_body_and_path(self, api_key_credentials):
        mc = create_mock_client(200, {"data": {"id": "P1"}})
        await _run(KlaviyoUpdateProfileConfig(profile_id="P1", attributes_json='{"first_name":"Grace"}'), api_key_credentials, mc)
        call = last(mc)
        assert call["method"] == "PATCH" and call["url"].endswith("/profiles/P1/")
        assert call["json"]["data"]["id"] == "P1" and call["json"]["data"]["type"] == "profile"

    @pytest.mark.asyncio
    async def test_upsert_uses_profile_import(self, api_key_credentials):
        mc = create_mock_client(200, {"data": {"id": "P1"}})
        await _run(KlaviyoUpsertProfileConfig(email="a@b.com"), api_key_credentials, mc)
        assert last(mc)["url"].endswith("/profile-import/")

    @pytest.mark.asyncio
    async def test_merge_body(self, api_key_credentials):
        mc = create_mock_client(200, {"data": {}})
        await _run(KlaviyoMergeProfilesConfig(destination_id="DEST", source_id="SRC"), api_key_credentials, mc)
        call = last(mc)
        assert call["url"].endswith("/profile-merge/")
        assert call["json"]["data"]["id"] == "DEST"
        assert call["json"]["data"]["relationships"]["profiles"]["data"] == [{"type": "profile", "id": "SRC"}]

    @pytest.mark.asyncio
    async def test_add_to_list_relationships_array(self, api_key_credentials):
        mc = create_mock_client(204, None, headers={"content-type": "text/plain"}, content=b"")
        await _run(KlaviyoAddToListConfig(list_id="L1", profile_ids="P1, P2"), api_key_credentials, mc)
        call = last(mc)
        assert call["method"] == "POST" and call["url"].endswith("/lists/L1/relationships/profiles/")
        assert call["json"]["data"] == [{"type": "profile", "id": "P1"}, {"type": "profile", "id": "P2"}]

    @pytest.mark.asyncio
    async def test_remove_from_list_delete(self, api_key_credentials):
        mc = create_mock_client(204, None, headers={"content-type": "text/plain"}, content=b"")
        await _run(KlaviyoRemoveFromListConfig(list_id="L1", profile_ids="P1"), api_key_credentials, mc)
        assert last(mc)["method"] == "DELETE"


class TestKlaviyoResources:
    @pytest.mark.asyncio
    async def test_create_list(self, api_key_credentials):
        mc = create_mock_client(201, {"data": {"id": "L1"}})
        await _run(KlaviyoCreateListConfig(name="VIPs"), api_key_credentials, mc)
        assert last(mc)["json"] == {"data": {"type": "list", "attributes": {"name": "VIPs"}}}

    @pytest.mark.asyncio
    async def test_subscribe_body(self, api_key_credentials):
        mc = create_mock_client(202, None, headers={"content-type": "text/plain"}, content=b"")
        await _run(KlaviyoSubscribeProfilesConfig(list_id="L1", emails="a@b.com"), api_key_credentials, mc)
        call = last(mc)
        assert call["url"].endswith("/profile-subscription-bulk-create-jobs/")
        assert call["json"]["data"]["relationships"]["list"]["data"] == {"type": "list", "id": "L1"}
        prof = call["json"]["data"]["attributes"]["profiles"]["data"][0]
        assert prof["attributes"]["subscriptions"]["email"]["marketing"]["consent"] == "SUBSCRIBED"

    @pytest.mark.asyncio
    async def test_unsubscribe_includes_subscriptions(self, api_key_credentials):
        # Klaviyo's bulk-delete job requires a `subscriptions` field per profile.
        mc = create_mock_client(202, None, headers={"content-type": "text/plain"}, content=b"")
        await _run(KlaviyoUnsubscribeProfilesConfig(list_id="L1", emails="a@b.com"), api_key_credentials, mc)
        prof = last(mc)["json"]["data"]["attributes"]["profiles"]["data"][0]
        assert prof["attributes"]["subscriptions"]["email"]["marketing"]["consent"] == "UNSUBSCRIBED"

    @pytest.mark.asyncio
    async def test_create_event_shape(self, api_key_credentials):
        mc = create_mock_client(202, None, headers={"content-type": "text/plain"}, content=b"")
        await _run(KlaviyoCreateEventConfig(metric_name="Placed Order", email="a@b.com", value="42.5", properties_json='{"OrderId":"x"}'), api_key_credentials, mc)
        attrs = last(mc)["json"]["data"]["attributes"]
        assert attrs["metric"]["data"]["attributes"]["name"] == "Placed Order"
        assert attrs["profile"]["data"]["attributes"]["email"] == "a@b.com"
        assert attrs["value"] == 42.5
        assert attrs["properties"] == {"OrderId": "x"}

    @pytest.mark.asyncio
    async def test_query_metric_aggregates(self, api_key_credentials):
        mc = create_mock_client(200, {"data": {}})
        await _run(KlaviyoQueryMetricAggregatesConfig(attributes_json='{"metric_id":"M1","measurements":["count"],"interval":"day"}'), api_key_credentials, mc)
        call = last(mc)
        assert call["url"].endswith("/metric-aggregates/")
        assert call["json"]["data"]["type"] == "metric-aggregate"

    @pytest.mark.asyncio
    async def test_list_campaigns_channel_filter(self, api_key_credentials):
        mc = create_mock_client(200, {"data": []})
        await _run(KlaviyoListCampaignsConfig(channel="sms"), api_key_credentials, mc)
        assert last(mc)["params"]["filter"] == "equals(messages.channel,'sms')"

    @pytest.mark.asyncio
    async def test_send_campaign_job(self, api_key_credentials):
        mc = create_mock_client(202, {"data": {"id": "J1"}})
        await _run(KlaviyoSendCampaignConfig(campaign_id="C1"), api_key_credentials, mc)
        call = last(mc)
        assert call["url"].endswith("/campaign-send-jobs/")
        # campaign-send-job is keyed by the campaign id directly — NOT a relationship
        # (Klaviyo rejects "'campaign' is not an allowed relation on ... campaign-send-jobs").
        assert call["json"]["data"] == {"type": "campaign-send-job", "id": "C1"}
        assert "relationships" not in call["json"]["data"]

    @pytest.mark.asyncio
    async def test_clone_campaign(self, api_key_credentials):
        mc = create_mock_client(201, {"data": {"id": "C2"}})
        await _run(KlaviyoCloneCampaignConfig(campaign_id="C1", new_name="Copy"), api_key_credentials, mc)
        call = last(mc)
        assert call["url"].endswith("/campaign-clone/")
        assert call["json"]["data"]["id"] == "C1" and call["json"]["data"]["attributes"]["new_name"] == "Copy"

    @pytest.mark.asyncio
    async def test_update_flow_status(self, api_key_credentials):
        mc = create_mock_client(200, {"data": {}})
        await _run(KlaviyoUpdateFlowStatusConfig(flow_id="F1", status="live"), api_key_credentials, mc)
        call = last(mc)
        assert call["method"] == "PATCH" and call["json"]["data"]["attributes"]["status"] == "live"

    @pytest.mark.asyncio
    async def test_create_template(self, api_key_credentials):
        mc = create_mock_client(201, {"data": {"id": "T1"}})
        await _run(KlaviyoCreateTemplateConfig(name="Welcome", html="<h1>Hi</h1>"), api_key_credentials, mc)
        attrs = last(mc)["json"]["data"]["attributes"]
        assert attrs == {"name": "Welcome", "editor_type": "CODE", "html": "<h1>Hi</h1>"}

    @pytest.mark.asyncio
    async def test_render_template(self, api_key_credentials):
        mc = create_mock_client(200, {"data": {}})
        await _run(KlaviyoRenderTemplateConfig(template_id="T1", context_json='{"first_name":"Ada"}'), api_key_credentials, mc)
        call = last(mc)
        assert call["url"].endswith("/template-render/")
        assert call["json"]["data"]["id"] == "T1"
        assert call["json"]["data"]["attributes"]["context"] == {"first_name": "Ada"}

    @pytest.mark.asyncio
    async def test_upload_image_import_from_url(self, api_key_credentials):
        mc = create_mock_client(201, {"data": {"id": "I1"}})
        await _run(KlaviyoUploadImageUrlConfig(import_from_url="https://x/y.png", name="hero"), api_key_credentials, mc)
        assert last(mc)["json"]["data"]["attributes"]["import_from_url"] == "https://x/y.png"

    @pytest.mark.asyncio
    async def test_create_coupon_and_tag(self, api_key_credentials):
        mc = create_mock_client(201, {"data": {"id": "CP1"}})
        await _run(KlaviyoCreateCouponConfig(external_id="SUMMER", description="Summer sale"), api_key_credentials, mc)
        assert last(mc)["json"]["data"]["attributes"]["external_id"] == "SUMMER"
        mc2 = create_mock_client(201, {"data": {"id": "TG1"}})
        await _run(KlaviyoCreateTagConfig(name="Priority", tag_group_id="G1"), api_key_credentials, mc2)
        assert last(mc2)["json"]["data"]["relationships"]["tag-group"]["data"] == {"type": "tag-group", "id": "G1"}

    @pytest.mark.asyncio
    async def test_get_account(self, api_key_credentials):
        mc = create_mock_client(200, {"data": [{"id": "ACC"}]})
        res = await _run(KlaviyoGetAccountConfig(), api_key_credentials, mc)
        assert res["status"] == "success" and last(mc)["url"].endswith("/accounts/")

    @pytest.mark.asyncio
    async def test_request_deletion(self, api_key_credentials):
        mc = create_mock_client(202, {"data": {}})
        await _run(KlaviyoRequestDeletionConfig(email="a@b.com"), api_key_credentials, mc)
        call = last(mc)
        assert call["url"].endswith("/data-privacy-deletion-jobs/")
        assert call["json"]["data"]["attributes"]["profile"]["data"]["attributes"]["email"] == "a@b.com"


class TestKlaviyoErrors:
    @pytest.mark.asyncio
    async def test_jsonapi_error_extracted(self, api_key_credentials):
        mc = create_mock_client(400, {"errors": [{"detail": "Invalid email", "code": "invalid"}]})
        res = await _run(KlaviyoCreateProfileConfig(email="bad"), api_key_credentials, mc)
        assert res["status"] == "error" and "Invalid email" in res["error"]

    @pytest.mark.asyncio
    async def test_bad_json_field(self, api_key_credentials):
        mc = create_mock_client(200, {"data": {}})
        node = create_node(KlaviyoNodeConfig(config=KlaviyoUpdateProfileConfig(profile_id="P1", attributes_json="not-json"), credentials=api_key_credentials))
        with patch("nodes.klaviyo_node.httpx.AsyncClient", return_value=mc):
            with pytest.raises(ValueError, match="must be valid JSON"):
                await node.execute({})


class TestKlaviyoDropdowns:
    @pytest.mark.asyncio
    async def test_list_dropdown(self, api_key_credentials):
        mc = create_mock_client(200, {"data": [{"id": "L1", "attributes": {"name": "Newsletter"}}]})
        with patch("nodes.klaviyo_node.httpx.AsyncClient", return_value=mc):
            res = await KlaviyoNode.load_field_options("list_id", api_key_credentials.model_dump())
        assert res["options"] == [{"value": "L1", "label": "Newsletter"}]

    @pytest.mark.asyncio
    async def test_topics_dropdown(self, api_key_credentials):
        mc = create_mock_client(200, {"data": [{"id": "event:klaviyo.opened_email"}]})
        with patch("nodes.klaviyo_node.httpx.AsyncClient", return_value=mc):
            res = await KlaviyoNode.load_field_options("topics", api_key_credentials.model_dump())
        assert res["options"][0]["value"] == "event:klaviyo.opened_email"

    @pytest.mark.asyncio
    async def test_dropdown_no_credential(self):
        assert await KlaviyoNode.load_field_options("list_id", {}) == {"options": []}

    @pytest.mark.asyncio
    async def test_dropdown_respects_per_resource_page_size_caps(self, api_key_credentials):
        """Klaviyo rejects over-limit page[size]: lists/segments/templates max 10, flows 50, metrics none."""
        for field, expected in [("list_id", "10"), ("segment_id", "10"), ("flow_id", "50"), ("template_id", "10")]:
            mc = create_mock_client(200, {"data": []})
            with patch("nodes.klaviyo_node.httpx.AsyncClient", return_value=mc):
                await KlaviyoNode.load_field_options(field, api_key_credentials.model_dump())
            params = last(mc).get("params") or {}
            assert str(params.get("page[size]")) == expected, (field, params)
        # metrics endpoint rejects page[size] entirely — must not be sent
        mc = create_mock_client(200, {"data": []})
        with patch("nodes.klaviyo_node.httpx.AsyncClient", return_value=mc):
            await KlaviyoNode.load_field_options("metric_id", api_key_credentials.model_dump())
        assert "page[size]" not in (last(mc).get("params") or {})

    @pytest.mark.asyncio
    async def test_dropdown_follows_cursor_pagination(self, api_key_credentials):
        pages = [
            {"data": [{"id": "L1", "attributes": {"name": "A"}}], "links": {"next": "https://a.klaviyo.com/api/lists/?page%5Bcursor%5D=CUR2"}},
            {"data": [{"id": "L2", "attributes": {"name": "B"}}], "links": {"next": None}},
        ]
        mc = Mock(); mc.calls = []

        async def req(*a, **k):
            resp = Mock(); resp.status_code = 200; resp.text = ""; resp.content = b"{}"
            resp.headers = {"content-type": "application/vnd.api+json"}
            resp.json = (lambda page=pages[min(len(mc.calls), len(pages) - 1)]: page)
            mc.calls.append(k); return resp
        mc.request = req
        async def aenter(self): return mc
        async def aexit(self, *a): return None
        mc.__aenter__ = aenter; mc.__aexit__ = aexit

        with patch("nodes.klaviyo_node.httpx.AsyncClient", return_value=mc):
            res = await KlaviyoNode.load_field_options("list_id", api_key_credentials.model_dump())
        assert [o["value"] for o in res["options"]] == ["L1", "L2"]  # both pages collected
        assert (mc.calls[1].get("params") or {}).get("page[cursor]") == "CUR2"  # cursor carried forward


class TestKlaviyoTrigger:
    @pytest.mark.asyncio
    async def test_trigger_manual_run_passthrough(self, api_key_credentials):
        node = create_node(KlaviyoNodeConfig(config=KlaviyoOnEventConfig(topics="event:klaviyo.opened_email", webhook_url="https://x.hooks.example.test"), credentials=api_key_credentials))
        res = await node.execute({"foo": "bar"})
        assert res["operation"] == "on_event" and res["data"]["foo"] == "bar"

    @pytest.mark.asyncio
    async def test_discrete_trigger_manual_passthrough(self, api_key_credentials):
        """A decomposed native trigger passes the fired event through like on_event."""
        cfg = KlaviyoNodeConfig(config={"operation": "on_email_opened", "webhook_url": "https://x.hooks.example.test"}, credentials=api_key_credentials)
        assert type(cfg.config).__name__ == "KlaviyoOnEmailOpenedConfig"  # discriminator resolved
        res = await create_node(cfg).execute({"foo": "bar"})
        assert res["operation"] == "on_email_opened" and res["data"]["foo"] == "bar"

    @pytest.mark.asyncio
    async def test_discrete_trigger_resolves_topic_from_operation(self, api_key_credentials):
        """Discrete triggers carry no topics field — the native topic comes from the op."""
        mc = create_mock_client(201, {"data": {"id": "WH9"}})
        with patch("nodes.klaviyo_node.httpx.AsyncClient", return_value=mc):
            await KlaviyoNode._register_external_webhook(
                webhook_url="https://d.hooks.example.test", credential=api_key_credentials.model_dump(),
                config={"operation": "on_subscribed_to_list"}, node_id="d1")
        rel = last(mc)["json"]["data"]["relationships"]["webhook-topics"]["data"]
        assert rel == [{"type": "webhook-topic", "id": "event:klaviyo.subscribed_to_list"}]

    @pytest.mark.asyncio
    async def test_unregister_treats_404_as_idempotent(self, api_key_credentials):
        """A DELETE that 404s (already gone) must NOT raise — cleanup is idempotent."""
        mc = create_mock_client(404, {"errors": [{"detail": "Not found."}]})
        with patch("nodes.klaviyo_node.httpx.AsyncClient", return_value=mc):
            await KlaviyoNode._unregister_external_webhook(
                credential=api_key_credentials.model_dump(), config={"external_webhook_id": "GONE"}, node_id="n1")
        assert last(mc)["method"] == "DELETE"  # it tried, and returned cleanly

    @pytest.mark.asyncio
    async def test_unregister_raises_on_real_failure(self, api_key_credentials):
        """A non-404 failure MUST raise so the lifecycle row records a possibly-live endpoint."""
        mc = create_mock_client(500, {"errors": [{"detail": "boom"}]})
        with patch("nodes.klaviyo_node.httpx.AsyncClient", return_value=mc):
            with pytest.raises(ValueError):
                await KlaviyoNode._unregister_external_webhook(
                    credential=api_key_credentials.model_dump(), config={"external_webhook_id": "WH1"}, node_id="n1")

    @pytest.mark.asyncio
    async def test_unregister_noop_without_id(self, api_key_credentials):
        mc = create_mock_client(204)
        with patch("nodes.klaviyo_node.httpx.AsyncClient", return_value=mc):
            await KlaviyoNode._unregister_external_webhook(
                credential=api_key_credentials.model_dump(), config={}, node_id="n1")
        assert mc.calls == []  # never hit the API

    @pytest.mark.asyncio
    async def test_register_retries_throttle_then_succeeds(self, api_key_credentials):
        """A transient 429 on webhook registration is retried, not surfaced as failure."""
        seq = [(429, {"errors": [{"detail": "throttled"}]}), (201, {"data": {"id": "WHR"}})]
        mc = Mock(); mc.calls = []

        async def req(*a, **k):
            code, body = seq[min(len(mc.calls), len(seq) - 1)]
            resp = Mock(); resp.status_code = code; resp.text = ""; resp.content = b"{}"
            resp.headers = {"content-type": "application/vnd.api+json"}
            resp.json = (lambda b=body: b)
            mc.calls.append(k); return resp
        mc.request = req
        async def aenter(self): return mc
        async def aexit(self, *a): return None
        mc.__aenter__ = aenter; mc.__aexit__ = aexit

        with patch("nodes.klaviyo_node.asyncio.sleep", new=AsyncMock()), \
             patch("nodes.klaviyo_node.httpx.AsyncClient", return_value=mc):
            reg = await KlaviyoNode._register_external_webhook(
                webhook_url="https://r.hooks.example.test", credential=api_key_credentials.model_dump(),
                config={"operation": "on_email_opened"}, node_id="n1")
        assert reg["external_webhook_id"] == "WHR" and len(mc.calls) == 2  # retried once

    @pytest.mark.asyncio
    async def test_register_raises_when_persistently_throttled(self, api_key_credentials):
        mc = create_mock_client(429, {"errors": [{"detail": "throttled"}]})
        with patch("nodes.klaviyo_node.asyncio.sleep", new=AsyncMock()), \
             patch("nodes.klaviyo_node.httpx.AsyncClient", return_value=mc):
            with pytest.raises(ValueError):
                await KlaviyoNode._register_external_webhook(
                    webhook_url="https://r.hooks.example.test", credential=api_key_credentials.model_dump(),
                    config={"operation": "on_email_opened"}, node_id="n1")

    def test_oauth_scopes_cover_all_operation_domains(self):
        """OAuth scope list must include every scope an operation needs (live-verified gaps)."""
        from nodes.klaviyo_node import KlaviyoOAuthCredential
        scopes = set(KlaviyoOAuthCredential.model_config["json_schema_extra"]["x-oauth-scopes"])
        # these were missing and caused live 'missing required scopes' failures
        for required in ("coupon-codes:read", "coupon-codes:write", "data-privacy:write",
                         "coupons:read", "coupons:write", "profiles:write", "campaigns:write",
                         "subscriptions:write", "webhooks:write"):
            assert required in scopes, f"missing OAuth scope: {required}"

    def test_all_native_topics_have_a_discrete_trigger(self):
        from nodes.klaviyo_node import _TRIGGER_SPECS, _TRIGGER_TOPIC_BY_OP
        # every spec maps a unique operation to a unique native topic
        ops = [op for op, _, _ in _TRIGGER_SPECS]
        topics = [t for _, t, _ in _TRIGGER_SPECS]
        assert len(ops) == len(set(ops)) == len(set(topics)) >= 30
        assert all(t.startswith("event:klaviyo.") for t in topics)
        assert _TRIGGER_TOPIC_BY_OP["on_email_marked_spam"] == "event:klaviyo.marked_email_as_spam"

    def test_discrete_triggers_marked_as_triggers_in_schema(self):
        schema = KlaviyoNode.get_config_schema()
        import json
        blob = json.dumps(schema)
        # every discrete op + the generic on_event are present and flagged x-is-trigger
        for op in ("on_email_opened", "on_sms_received", "on_subscribed_to_list", "on_event"):
            assert f'"{op}"' in blob
        assert blob.count('"x-is-trigger": true') >= 30

    @pytest.mark.asyncio
    async def test_register_webhook(self, api_key_credentials):
        mc = create_mock_client(201, {"data": {"id": "WH1"}})
        with patch("nodes.klaviyo_node.httpx.AsyncClient", return_value=mc):
            reg = await KlaviyoNode._register_external_webhook(
                webhook_url="https://abc.hooks.example.test", credential=api_key_credentials.model_dump(),
                config={"operation": "on_event", "topics": "event:klaviyo.opened_email,event:klaviyo.clicked_email"}, node_id="n1")
        call = last(mc)
        assert call["method"] == "POST" and call["url"].endswith("/webhooks/")
        data = call["json"]["data"]
        attrs = data["attributes"]
        assert attrs["endpoint_url"] == "https://abc.hooks.example.test"
        assert len(attrs["secret_key"]) >= 16
        # topics are a JSON:API relationship, NOT an attribute; 'enabled'/'topics' attrs are rejected by Klaviyo
        assert "topics" not in attrs and "enabled" not in attrs
        assert data["relationships"]["webhook-topics"]["data"] == [
            {"type": "webhook-topic", "id": "event:klaviyo.opened_email"},
            {"type": "webhook-topic", "id": "event:klaviyo.clicked_email"},
        ]
        assert reg["external_webhook_id"] == "WH1" and reg["signing_secret"] == attrs["secret_key"]

    @pytest.mark.asyncio
    async def test_create_webhook_action_topics_to_relationship(self, api_key_credentials):
        """The create_webhook action must also route topics → relationship and drop enabled."""
        mc = create_mock_client(201, {"data": {"id": "WH2"}})
        node = create_node(KlaviyoNodeConfig(
            config=KlaviyoCreateWebhookConfig(attributes_json='{"name":"n","endpoint_url":"https://e.x","secret_key":"1234567890123456","topics":["event:klaviyo.opened_email"],"enabled":true}'),
            credentials=api_key_credentials))
        with patch("nodes.klaviyo_node.httpx.AsyncClient", return_value=mc):
            await node.execute({})
        data = last(mc)["json"]["data"]
        assert "topics" not in data["attributes"] and "enabled" not in data["attributes"]
        assert data["relationships"]["webhook-topics"]["data"] == [{"type": "webhook-topic", "id": "event:klaviyo.opened_email"}]

    def test_verify_signature_valid(self):
        secret = "supersecretkey_1234567890"
        body = b'{"data":{"type":"event"}}'
        ts = "2026-07-16T10:00:00"
        mac = hmac.new(secret.encode(), body, hashlib.sha256); mac.update(ts.encode())
        headers = {"Klaviyo-Signature": mac.hexdigest(), "Klaviyo-Timestamp": ts}
        assert KlaviyoNode.verify_webhook_signature(body, headers, {"signing_secret": secret}) is True

    def test_verify_signature_rejects_tamper_and_missing(self):
        secret = "supersecretkey_1234567890"
        body = b'{"data":1}'; ts = "2026-07-16T10:00:00"
        mac = hmac.new(secret.encode(), body, hashlib.sha256); mac.update(ts.encode())
        good = {"Klaviyo-Signature": mac.hexdigest(), "Klaviyo-Timestamp": ts}
        assert KlaviyoNode.verify_webhook_signature(body + b"x", good, {"signing_secret": secret}) is False
        assert KlaviyoNode.verify_webhook_signature(body, {}, {"signing_secret": secret}) is False

    def test_resolve_agent_event(self):
        node = create_node(KlaviyoNodeConfig(config=KlaviyoListListsConfig(), credentials=KlaviyoApiKeyCredential(api_key="pk_x")))
        ev = node.resolve_agent_event({"data": {"type": "event", "id": "E1"}})
        assert json.loads(ev["text"])["id"] == "E1"
