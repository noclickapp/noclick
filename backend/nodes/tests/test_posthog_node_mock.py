"""
Mock tests for the PostHog node (no live API calls).

Verifies host/region resolution, ingestion vs REST routing, key selection
(project key in body for capture, personal key Bearer for REST), URL/path
construction, the HogQL query wrapper, the generic passthrough, and the Hog
Function webhook trigger lifecycle. The two HTTP seams (_rest_request,
_ingest_request) are patched so the node's request-shaping is what's tested.
"""

import pytest
from unittest.mock import Mock, patch

from nodes.posthog_node import (
    PostHogNode, PostHogNodeConfig, PostHogPersonalApiKeyCredential, PostHogProjectApiKeyCredential, _hosts,
    PostHogCaptureConfig, PostHogBatchCaptureConfig, PostHogIdentifyConfig, PostHogGroupIdentifyConfig,
    PostHogEvaluateFlagsConfig, PostHogRunQueryConfig, PostHogListEventsConfig,
    PostHogListFeatureFlagsConfig, PostHogCreateFeatureFlagConfig, PostHogUpdateFeatureFlagConfig,
    PostHogDeleteFeatureFlagConfig, PostHogGetPersonConfig, PostHogUpdatePersonConfig, PostHogDeletePersonConfig,
    PostHogCreateCohortConfig, PostHogCreateAnnotationConfig, PostHogListInsightsConfig,
    PostHogCreateDashboardConfig, PostHogRawRequestConfig, PostHogOnCustomEventConfig,
)


def cred(**kw):
    """Personal API key credential — for REST / management / trigger ops."""
    base = dict(region="us", personal_api_key="phx_test", project_id="42")
    base.update(kw)
    return PostHogPersonalApiKeyCredential(**base)


def project_cred(**kw):
    """Project API key credential — for event ingestion."""
    base = dict(region="us", project_api_key="phc_test")
    base.update(kw)
    return PostHogProjectApiKeyCredential(**base)


def node(cfg, credential=None):
    return PostHogNode(node_id="ph", node_type="automation-posthog", node_data={},
                       config=PostHogNodeConfig(config=cfg, credentials=credential or cred()),
                       sio=Mock(), sid="s", workflow_id="w", user_id="u")


async def run_rest(cfg, credential=None, response=None):
    captured = {}

    async def fake(cred_, method, path, params=None, json_body=None, action_name="request"):
        captured.update(cred=cred_, method=method, path=path, params=params, json_body=json_body, action_name=action_name)
        return response or {"status": "success", "action": action_name, "data": {}}

    with patch("nodes.posthog_node._rest_request", side_effect=fake):
        result = await node(cfg, credential).execute({})
    return result, captured


async def run_ingest(cfg, credential=None):
    captured = {}

    async def fake(cred_, path, body, action_name):
        captured.update(cred=cred_, path=path, body=body, action_name=action_name)
        return {"status": "success", "action": action_name, "data": {"status": 1}}

    with patch("nodes.posthog_node._ingest_request", side_effect=fake):
        result = await node(cfg, credential or project_cred()).execute({})
    return result, captured


# ------------------------------------------------------------------ host resolution


def test_hosts_us():
    assert _hosts("us", None) == ("https://us.posthog.com", "https://us.i.posthog.com")


def test_hosts_eu():
    assert _hosts("eu", None) == ("https://eu.posthog.com", "https://eu.i.posthog.com")


def test_hosts_custom():
    assert _hosts("custom", "https://ph.acme.com") == ("https://ph.acme.com", "https://ph.acme.com")


def test_hosts_custom_adds_scheme():
    assert _hosts("custom", "ph.acme.com")[0] == "https://ph.acme.com"


# ------------------------------------------------------------------ ingestion


@pytest.mark.asyncio
async def test_capture_uses_ingestion_path_and_key_in_body():
    _, cap = await run_ingest(PostHogCaptureConfig(event="signup", distinct_id="u1", properties='{"plan":"pro"}'))
    assert cap["path"] == "/i/v0/e/"
    assert cap["body"]["event"] == "signup"
    assert cap["body"]["distinct_id"] == "u1"
    assert cap["body"]["properties"] == {"plan": "pro"}


@pytest.mark.asyncio
async def test_batch_capture():
    _, cap = await run_ingest(PostHogBatchCaptureConfig(batch='[{"event":"a","properties":{"distinct_id":"u1"}}]'))
    assert cap["path"] == "/batch/"
    assert isinstance(cap["body"]["batch"], list)
    assert cap["body"]["historical_migration"] is False


@pytest.mark.asyncio
async def test_identify_builds_set_and_set_once():
    _, cap = await run_ingest(PostHogIdentifyConfig(distinct_id="u1", set_properties='{"email":"a@b.com"}', set_once_properties='{"first_seen":"2026"}'))
    assert cap["body"]["event"] == "$identify"
    assert cap["body"]["properties"]["$set"] == {"email": "a@b.com"}
    assert cap["body"]["properties"]["$set_once"] == {"first_seen": "2026"}


@pytest.mark.asyncio
async def test_group_identify():
    _, cap = await run_ingest(PostHogGroupIdentifyConfig(group_type="company", group_key="acme", properties='{"name":"Acme"}'))
    assert cap["body"]["event"] == "$groupidentify"
    assert cap["body"]["properties"]["$group_type"] == "company"
    assert cap["body"]["properties"]["$group_key"] == "acme"
    assert cap["body"]["properties"]["$group_set"] == {"name": "Acme"}


@pytest.mark.asyncio
async def test_evaluate_flags_uses_flags_endpoint():
    _, cap = await run_ingest(PostHogEvaluateFlagsConfig(distinct_id="u1", groups='{"company":"acme"}'))
    assert cap["path"] == "/flags?v=2"
    assert cap["body"]["distinct_id"] == "u1"
    assert cap["body"]["groups"] == {"company": "acme"}


@pytest.mark.asyncio
async def test_capture_requires_project_key():
    # A personal-key credential has no project key → capture errors clearly.
    result = await node(PostHogCaptureConfig(event="e", distinct_id="u1"), credential=cred()).execute({})
    assert result["status"] == "error"
    assert result["status_code"] == 401
    assert "Project API Key" in result["error"]


# ------------------------------------------------------------------ REST + query


@pytest.mark.asyncio
async def test_run_query_wraps_hogql():
    _, cap = await run_rest(PostHogRunQueryConfig(hogql="SELECT event FROM events LIMIT 1"))
    assert cap["method"] == "POST"
    assert cap["path"] == "/api/projects/42/query/"
    assert cap["json_body"]["query"] == {"kind": "HogQLQuery", "query": "SELECT event FROM events LIMIT 1"}


@pytest.mark.asyncio
async def test_run_query_uses_structured_json_over_hogql():
    _, cap = await run_rest(PostHogRunQueryConfig(hogql="ignored", query_json='{"kind":"TrendsQuery","series":[]}'))
    assert cap["json_body"]["query"] == {"kind": "TrendsQuery", "series": []}


@pytest.mark.asyncio
async def test_list_events_path_and_params():
    _, cap = await run_rest(PostHogListEventsConfig(event="signup", limit="50"))
    assert cap["path"] == "/api/projects/42/events/"
    assert cap["params"]["event"] == "signup"
    assert cap["params"]["limit"] == "50"


@pytest.mark.asyncio
async def test_list_feature_flags_path():
    _, cap = await run_rest(PostHogListFeatureFlagsConfig())
    assert cap["method"] == "GET"
    assert cap["path"] == "/api/projects/42/feature_flags/"


@pytest.mark.asyncio
async def test_create_feature_flag_body():
    _, cap = await run_rest(PostHogCreateFeatureFlagConfig(key="new-flag", name="New", active="true"))
    assert cap["method"] == "POST"
    assert cap["path"] == "/api/projects/42/feature_flags/"
    assert cap["json_body"]["key"] == "new-flag"
    assert cap["json_body"]["active"] is True


@pytest.mark.asyncio
async def test_update_feature_flag_patch():
    _, cap = await run_rest(PostHogUpdateFeatureFlagConfig(flag_id="7", body_json='{"active":false}'))
    assert cap["method"] == "PATCH"
    assert cap["path"] == "/api/projects/42/feature_flags/7/"
    assert cap["json_body"] == {"active": False}


@pytest.mark.asyncio
async def test_delete_feature_flag_soft_deletes():
    _, cap = await run_rest(PostHogDeleteFeatureFlagConfig(flag_id="7"))
    assert cap["method"] == "PATCH"
    assert cap["json_body"] == {"deleted": True}


@pytest.mark.asyncio
async def test_get_person():
    _, cap = await run_rest(PostHogGetPersonConfig(person_id="123"))
    assert cap["path"] == "/api/projects/42/persons/123/"


@pytest.mark.asyncio
async def test_update_person_wraps_properties():
    _, cap = await run_rest(PostHogUpdatePersonConfig(person_id="123", properties='{"plan":"enterprise"}'))
    assert cap["method"] == "PATCH"
    assert cap["json_body"] == {"properties": {"plan": "enterprise"}}


@pytest.mark.asyncio
async def test_delete_person_hard_delete():
    _, cap = await run_rest(PostHogDeletePersonConfig(person_id="123"))
    assert cap["method"] == "DELETE"
    assert cap["path"] == "/api/projects/42/persons/123/"


@pytest.mark.asyncio
async def test_create_cohort_merges_definition():
    _, cap = await run_rest(PostHogCreateCohortConfig(name="Power Users", body_json='{"is_static":true}'))
    assert cap["json_body"]["name"] == "Power Users"
    assert cap["json_body"]["is_static"] is True


@pytest.mark.asyncio
async def test_create_annotation():
    _, cap = await run_rest(PostHogCreateAnnotationConfig(content="Deployed v2", date_marker="2026-07-13T00:00:00Z"))
    assert cap["path"] == "/api/projects/42/annotations/"
    assert cap["json_body"] == {"content": "Deployed v2", "date_marker": "2026-07-13T00:00:00Z"}


@pytest.mark.asyncio
async def test_list_insights():
    _, cap = await run_rest(PostHogListInsightsConfig())
    assert cap["path"] == "/api/projects/42/insights/"


@pytest.mark.asyncio
async def test_create_dashboard():
    _, cap = await run_rest(PostHogCreateDashboardConfig(name="Growth"))
    assert cap["method"] == "POST"
    assert cap["json_body"]["name"] == "Growth"


# ------------------------------------------------------------------ passthrough


@pytest.mark.asyncio
async def test_raw_request_substitutes_project_id():
    _, cap = await run_rest(PostHogRawRequestConfig(method="GET", path="/api/projects/{project_id}/hog_functions/", query_params="limit=10"))
    # _rest_request receives the raw path (substitution happens inside it); assert it's passed through
    assert cap["path"] == "/api/projects/{project_id}/hog_functions/"
    assert cap["params"] == {"limit": "10"}


@pytest.mark.asyncio
async def test_raw_request_rejects_absolute_url():
    with patch("nodes.posthog_node._rest_request", side_effect=AssertionError("should not be called")):
        with pytest.raises(ValueError, match="relative"):
            await node(PostHogRawRequestConfig(method="GET", path="https://evil.com")).execute({})


# ------------------------------------------------------------------ trigger lifecycle


@pytest.mark.asyncio
async def test_register_webhook_creates_hog_function():
    captured = {}

    async def fake(cred_, method, path, params=None, json_body=None, action_name="request"):
        captured.update(method=method, path=path, json_body=json_body)
        return {"status": "success", "data": {"id": "hf_123"}}

    with patch("nodes.posthog_node._rest_request", side_effect=fake):
        extra = await PostHogNode._register_external_webhook(
            webhook_url="https://abc.hooks.example.test", credential=cred().model_dump(),
            config={"operation": "on_custom_event", "event_name": "purchase"}, node_id="ph")

    assert captured["method"] == "POST"
    assert captured["path"] == "/api/projects/42/hog_functions/"
    body = captured["json_body"]
    assert body["type"] == "destination"
    assert body["template_id"] == "template-webhook"
    assert body["filters"]["events"] == [{"id": "purchase", "type": "events"}]
    assert body["inputs"]["url"]["value"] == "https://abc.hooks.example.test"
    assert extra["external_webhook_id"] == "hf_123"


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,event_id", [
    ("on_pageview", "$pageview"),
    ("on_feature_flag_called", "$feature_flag_called"),
    ("on_survey_sent", "survey sent"),
    ("on_exception", "$exception"),
])
async def test_register_webhook_fixed_event_per_trigger(operation, event_id):
    """Each decomposed trigger op filters on its own fixed PostHog event id —
    no event_name field needed."""
    captured = {}

    async def fake(cred_, method, path, params=None, json_body=None, action_name="request"):
        captured.update(json_body=json_body)
        return {"status": "success", "data": {"id": "hf_x"}}

    with patch("nodes.posthog_node._rest_request", side_effect=fake):
        await PostHogNode._register_external_webhook(
            webhook_url="https://abc.hooks.example.test", credential=cred().model_dump(),
            config={"operation": operation}, node_id="ph")
    assert captured["json_body"]["filters"]["events"] == [{"id": event_id, "type": "events"}]


@pytest.mark.asyncio
async def test_register_webhook_all_events_no_filter():
    captured = {}

    async def fake(cred_, method, path, params=None, json_body=None, action_name="request"):
        captured.update(json_body=json_body)
        return {"status": "success", "data": {"id": "hf_9"}}

    with patch("nodes.posthog_node._rest_request", side_effect=fake):
        await PostHogNode._register_external_webhook(
            webhook_url="https://abc.hooks.example.test", credential=cred().model_dump(),
            config={"operation": "on_custom_event", "event_name": "*"}, node_id="ph")
    assert "events" not in captured["json_body"]["filters"]


@pytest.mark.asyncio
async def test_unregister_webhook_soft_deletes_hog_function():
    """Hog functions soft-delete via PATCH deleted:true — a raw DELETE is rejected
    for personal API keys."""
    captured = {}

    async def fake(cred_, method, path, params=None, json_body=None, action_name="request", quiet_statuses=()):
        captured.update(method=method, path=path, json_body=json_body)
        return {"status": "success", "data": {}}

    with patch("nodes.posthog_node._rest_request", side_effect=fake):
        await PostHogNode._unregister_external_webhook(
            credential=cred().model_dump(), config={"external_webhook_id": "hf_123"}, node_id="ph")
    assert captured["method"] == "PATCH"
    assert captured["path"] == "/api/projects/42/hog_functions/hf_123/"
    assert captured["json_body"] == {"deleted": True}


@pytest.mark.asyncio
async def test_unregister_webhook_raises_on_failure():
    async def fake(cred_, method, path, params=None, json_body=None, action_name="request", quiet_statuses=()):
        return {"status": "error", "error": "boom"}

    with patch("nodes.posthog_node._rest_request", side_effect=fake):
        with pytest.raises(ValueError, match="Failed to remove"):
            await PostHogNode._unregister_external_webhook(
                credential=cred().model_dump(), config={"external_webhook_id": "hf_123"}, node_id="ph")


def test_verify_webhook_signature_accepts():
    # Hog Function webhooks aren't HMAC-signed; the URL is the capability.
    assert PostHogNode.verify_webhook_signature(b"{}", {}, {}) is True


@pytest.mark.asyncio
async def test_trigger_passthrough_in_execute():
    n = node(PostHogOnCustomEventConfig(event_name="purchase"))
    payload = {"event": "purchase", "distinct_id": "u1"}
    result = await n.execute(payload)
    assert result["status"] == "success"
    assert result["action"] == "on_custom_event"
    assert result["data"] == payload


def test_credential_union_has_three_types():
    import typing
    from nodes.posthog_node import PostHogCredential
    types = {m.model_fields["credential_type"].default for m in typing.get_args(PostHogCredential)}
    assert types == {"posthog_personal_api_key", "posthog_project_api_key", "posthog_oauth"}


@pytest.mark.asyncio
async def test_oauth_credential_uses_base_url_and_access_token():
    """An OAuth credential routes REST calls to its region base_url with the pha_
    access token as Bearer (verified at the _rest_request seam)."""
    from nodes.posthog_node import PostHogOAuthCredential, PostHogListInsightsConfig
    oauth = PostHogOAuthCredential(access_token="pha_x", refresh_token="phr_x",
                                   expires_at="2999-01-01T00:00:00+00:00",
                                   base_url="https://eu.posthog.com", project_id="9")
    captured = {}

    async def fake(cred_, method, path, params=None, json_body=None, action_name="request"):
        captured.update(cred=cred_, path=path)
        return {"status": "success", "action": action_name, "data": {}}

    with patch("nodes.posthog_node._rest_request", side_effect=fake), \
         patch.object(PostHogNode, "_ensure_fresh_token", _noop_ensure):
        await node(PostHogListInsightsConfig(), credential=oauth).execute({})
    assert captured["cred"]["access_token"] == "pha_x"
    assert captured["cred"]["base_url"] == "https://eu.posthog.com"


@pytest.mark.asyncio
async def test_legacy_oauth_base_url_cannot_exfiltrate_access_token(monkeypatch):
    from nodes.posthog_node import _rest_request

    monkeypatch.setattr(
        "nodes.posthog_node.guarded_async_client",
        lambda **_kwargs: pytest.fail("HTTP client must not be constructed"),
    )
    result = await _rest_request(
        {
            "access_token": "secret-bearer",
            "base_url": "https://attacker.example",
            "project_id": "9",
        },
        "GET",
        "/api/projects/9/insights/",
        action_name="list_insights",
    )

    assert result["status"] == "error"
    assert result["status_code"] == 400


async def _noop_ensure(self, credentials):
    return None


# ------------------------------------------------------------------ expanded-coverage ops


@pytest.mark.asyncio
async def test_experiment_action_builds_action_path():
    from nodes.posthog_node import PostHogExperimentActionConfig
    _, cap = await run_rest(PostHogExperimentActionConfig(experiment_id="5", action="launch"))
    assert cap["method"] == "POST"
    assert cap["path"] == "/api/projects/42/experiments/5/launch/"


@pytest.mark.asyncio
async def test_survey_action_builds_action_path():
    from nodes.posthog_node import PostHogSurveyActionConfig
    _, cap = await run_rest(PostHogSurveyActionConfig(survey_id="s1", action="stop"))
    assert cap["path"] == "/api/projects/42/surveys/s1/stop/"


@pytest.mark.asyncio
async def test_local_evaluation_uses_projectless_path():
    from nodes.posthog_node import PostHogFlagLocalEvaluationConfig
    _, cap = await run_rest(PostHogFlagLocalEvaluationConfig())
    assert cap["path"] == "/api/feature_flag/local_evaluation/"
    assert cap["params"] is None  # personal-key cred, no inline token


@pytest.mark.asyncio
async def test_local_evaluation_includes_inline_project_token():
    """The op accepts an inline project token (this endpoint requires it unless
    auth is a phs_ key)."""
    from nodes.posthog_node import PostHogFlagLocalEvaluationConfig
    _, cap = await run_rest(PostHogFlagLocalEvaluationConfig(project_token="phc_inline"))
    assert cap["params"] == {"token": "phc_inline"}


@pytest.mark.asyncio
async def test_project_id_auto_resolves_when_blank():
    """A personal-key credential with no project_id auto-detects the default
    project, so REST paths still build correctly."""
    from nodes.posthog_node import PostHogListInsightsConfig, PostHogPersonalApiKeyCredential
    no_pid = PostHogPersonalApiKeyCredential(region="us", personal_api_key="phx_test")  # project_id blank
    calls = []

    async def fake(cred_, method, path, params=None, json_body=None, action_name="request"):
        calls.append(path)
        if path == "/api/organizations/@current/projects/":
            return {"status": "success", "data": {"results": [{"id": 777}]}}
        return {"status": "success", "action": action_name, "data": {}}

    with patch("nodes.posthog_node._rest_request", side_effect=fake):
        await node(PostHogListInsightsConfig(), credential=no_pid).execute({})
    # resolved 777 → the insights path uses it
    assert "/api/organizations/@current/projects/" in calls
    assert "/api/projects/777/insights/" in calls


@pytest.mark.asyncio
async def test_org_members_uses_org_scoped_path():
    from nodes.posthog_node import PostHogListOrgMembersConfig
    _, cap = await run_rest(PostHogListOrgMembersConfig())
    assert cap["path"] == "/api/organizations/@current/members/"


@pytest.mark.asyncio
async def test_list_groups_requires_group_type_index():
    from nodes.posthog_node import PostHogListGroupsConfig
    _, cap = await run_rest(PostHogListGroupsConfig(group_type_index="0"))
    assert cap["path"] == "/api/projects/42/groups/"
    assert cap["params"]["group_type_index"] == "0"


@pytest.mark.asyncio
async def test_create_early_access_includes_stage():
    from nodes.posthog_node import PostHogCreateEarlyAccessConfig
    _, cap = await run_rest(PostHogCreateEarlyAccessConfig(name="Beta X", stage="beta"))
    assert cap["path"] == "/api/projects/42/early_access_feature/"
    assert cap["json_body"]["stage"] == "beta"


# ------------------------------------------------------------------ dynamic dropdowns


@pytest.mark.asyncio
async def test_load_field_options_lists_resource_with_label_fallback():
    """A dropdown field paginates its REST resource and labels each option from
    the first available label key, valuing it by the id key."""
    async def fake(cred_, method, path, params=None, json_body=None, action_name="request"):
        assert path == "/api/projects/42/feature_flags/"
        return {"status": "success", "data": {"results": [
            {"id": 1, "name": "Beta rollout", "key": "beta"},
            {"id": 2, "key": "no-name-flag"},  # no name → falls back to key
        ]}}

    with patch("nodes.posthog_node._rest_request", side_effect=fake):
        result = await PostHogNode.load_field_options("flag_id", cred().model_dump())
    assert result["options"] == [
        {"label": "Beta rollout", "value": "1"},
        {"label": "no-name-flag", "value": "2"},
    ]


@pytest.mark.asyncio
async def test_load_field_options_feature_flag_key_values_by_key():
    """feature_flag_key uses the key (not id) as the option value."""
    async def fake(cred_, method, path, params=None, json_body=None, action_name="request"):
        return {"status": "success", "data": {"results": [{"id": 9, "name": "Beta", "key": "beta"}]}}

    with patch("nodes.posthog_node._rest_request", side_effect=fake):
        result = await PostHogNode.load_field_options("feature_flag_key", cred().model_dump())
    assert result["options"] == [{"label": "Beta", "value": "beta"}]


@pytest.mark.asyncio
async def test_load_field_options_group_types_flat_list():
    """group_type_index reads the flat groups_types endpoint (index is the value)."""
    async def fake(cred_, method, path, params=None, json_body=None, action_name="request"):
        assert path == "/api/projects/42/groups_types/"
        return {"status": "success", "data": [
            {"group_type": "organization", "group_type_index": 0},
            {"group_type": "company", "group_type_index": 1},
        ]}

    with patch("nodes.posthog_node._rest_request", side_effect=fake):
        result = await PostHogNode.load_field_options("group_type_index", cred().model_dump())
    assert result["options"] == [
        {"label": "organization", "value": "0"},
        {"label": "company", "value": "1"},
    ]


@pytest.mark.asyncio
async def test_load_field_options_empty_without_management_key():
    """A project-key-only credential can't read management data → no options."""
    result = await PostHogNode.load_field_options("flag_id", project_cred().model_dump())
    assert result == {"options": []}


# ------------------------------------------------------------------ trigger event scoping (regression: fired for everything)


@pytest.mark.asyncio
async def test_register_custom_event_without_name_refuses_match_all():
    """Registering on_custom_event before the event name is typed must FAIL
    loudly instead of silently minting a match-all destination that fires the
    workflow on every project event (the panel loads webhook_url first)."""
    with pytest.raises(ValueError, match="Event Name"):
        await PostHogNode._register_external_webhook(
            webhook_url="https://abc.hooks.example.test", credential=cred().model_dump(),
            config={"operation": "on_custom_event"}, node_id="ph")


@pytest.mark.asyncio
async def test_register_returns_registered_event_mirror():
    """Registration mirrors the event the provider filter was built with, so
    webhook_registration_stale can detect later event_name edits."""
    async def fake(cred_, method, path, params=None, json_body=None, action_name="request"):
        return {"status": "success", "data": {"id": "hf_1"}}

    with patch("nodes.posthog_node._rest_request", side_effect=fake):
        extra = await PostHogNode._register_external_webhook(
            webhook_url="https://abc.hooks.example.test", credential=cred().model_dump(),
            config={"operation": "on_custom_event", "event_name": "purchase"}, node_id="ph")
    assert extra == {"external_webhook_id": "hf_1", "registered_event_name": "purchase"}


def test_registration_stale_detects_event_edit():
    assert PostHogNode.webhook_registration_stale(
        {"operation": "on_custom_event", "event_name": "signup", "registered_event_name": "purchase"}, {}) is True
    assert PostHogNode.webhook_registration_stale(
        {"operation": "on_custom_event", "event_name": "purchase", "registered_event_name": "purchase"}, {}) is False
    # mirror missing (autosave never landed) + typed event → assume stale so the filter converges
    assert PostHogNode.webhook_registration_stale(
        {"operation": "on_custom_event", "event_name": "purchase"}, {}) is True
    # no event typed yet → nothing better to register
    assert PostHogNode.webhook_registration_stale({"operation": "on_custom_event"}, {}) is False
    # fixed-event ops derive from operation → never stale
    assert PostHogNode.webhook_registration_stale({"operation": "on_pageview"}, {}) is False


def test_filter_trigger_payload_scopes_custom_event():
    cfg = {"operation": "on_custom_event", "event_name": "purchase"}
    assert PostHogNode.filter_trigger_payload({"event": "purchase"}, cfg) is True
    assert PostHogNode.filter_trigger_payload({"event": "$pageview"}, cfg) is False


def test_filter_trigger_payload_scopes_fixed_ops():
    assert PostHogNode.filter_trigger_payload({"event": "$pageview"}, {"operation": "on_pageview"}) is True
    assert PostHogNode.filter_trigger_payload({"event": "$identify"}, {"operation": "on_pageview"}) is False
    assert PostHogNode.filter_trigger_payload({"event": "survey sent"}, {"operation": "on_survey_sent"}) is True


def test_filter_trigger_payload_star_and_legacy_matchall():
    # '*' explicitly opts into everything
    assert PostHogNode.filter_trigger_payload({"event": "anything"},
                                              {"operation": "on_custom_event", "event_name": "*"}) is True
    # legacy match-all registration (no event typed) → deliveries dropped
    assert PostHogNode.filter_trigger_payload({"event": "anything"},
                                              {"operation": "on_custom_event"}) is False


def test_filter_trigger_payload_passes_non_hog_envelopes():
    """Payloads without a string 'event' key (manual test posts) pass through."""
    assert PostHogNode.filter_trigger_payload({"foo": 1},
                                              {"operation": "on_custom_event", "event_name": "purchase"}) is True


# ------------------------------------------------------------------ scoped credentials + scope alerts


@pytest.mark.asyncio
async def test_default_project_prefers_scoped_teams():
    """A team-scoped OAuth grant resolves its project from scoped_teams without
    touching org endpoints (which 403 for such tokens)."""
    from nodes.posthog_node import _default_project_id
    called = []

    async def fake(cred_, method, path, params=None, json_body=None, action_name="request"):
        called.append(path)
        return {"status": "error", "status_code": 403}

    with patch("nodes.posthog_node._rest_request", side_effect=fake):
        pid = await _default_project_id({"access_token": "pha_x", "scoped_teams": [98765]})
    assert pid == "98765"
    assert called == []  # no HTTP at all


@pytest.mark.asyncio
async def test_default_project_falls_back_to_users_me():
    """When the org route 403s (project-scoped personal key), /api/users/@me/
    resolves the project (it is exempt from team scoping)."""
    from nodes.posthog_node import _default_project_id

    async def fake(cred_, method, path, params=None, json_body=None, action_name="request"):
        if path == "/api/organizations/@current/projects/":
            return {"status": "error", "status_code": 403,
                    "error": "API keys with scoped projects are only supported on project-based endpoints."}
        assert path == "/api/users/@me/"
        return {"status": "success", "data": {"team": {"id": 424242, "name": "Scoped"}}}

    with patch("nodes.posthog_node._rest_request", side_effect=fake):
        pid = await _default_project_id({"personal_api_key": "phx_x"})
    assert pid == "424242"


def test_scope_error_hints():
    from nodes.posthog_node import _scope_error_hint
    msg = _scope_error_hint("API key missing required scope 'hog_function:write'")
    assert "Not enough scopes" in msg and "hog_function:write" in msg
    msg = _scope_error_hint("API key does not have access to the requested project: ID 123.")
    assert "specific projects" in msg
    msg = _scope_error_hint("API keys with scoped projects are only supported on project-based endpoints.")
    assert "organization-level access" in msg
    assert _scope_error_hint("Something else") == "Something else"


@pytest.mark.asyncio
async def test_rest_request_translates_permission_denied():
    """A 403 permission_denied response surfaces the actionable scopes hint."""
    from nodes.posthog_node import _rest_request

    class _Resp:
        status_code = 403
        content = b"x"
        headers = {}
        def json(self):
            return {"type": "authentication_error", "code": "permission_denied",
                    "detail": "API key missing required scope 'hog_function:write'"}

    class _Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return None
        async def request(self, **kw): return _Resp()

    with patch("nodes.posthog_node.httpx.AsyncClient", return_value=_Client()):
        r = await _rest_request({"personal_api_key": "phx_x", "region": "us", "project_id": "1"},
                                "POST", "/api/projects/1/hog_functions/", action_name="t")
    assert r["status"] == "error"
    assert "Not enough scopes" in r["error"] and "hog_function:write" in r["error"]


def test_secretless_provider_flag_set():
    """PostHog issues no webhook signing secret (URL is the capability). Without
    this flag the mixin's idempotency guard NEVER holds and every config-panel
    open re-registers + orphans a hog function (the prod orphan-accumulation bug)."""
    assert PostHogNode.webhook_signing_secret_not_issued is True


@pytest.mark.asyncio
async def test_unregister_404_is_converged_success():
    """Deleting an already-gone hog function (double-teardown: panel re-register
    + operation-change hook both fire) is convergence, not a failure — a raise
    here wrongly marked deregistration failed and spammed ERROR logs."""
    async def fake(cred_, method, path, params=None, json_body=None, action_name="request", quiet_statuses=()):
        return {"status": "error", "status_code": 404, "error": "Not found."}

    with patch("nodes.posthog_node._rest_request", side_effect=fake):
        # must NOT raise
        await PostHogNode._unregister_external_webhook(
            credential=cred().model_dump(), config={"external_webhook_id": "gone"}, node_id="ph")


def test_replace_stale_endpoint_flag_set():
    """Re-registrations replace the previous hog function via the mixin's
    stale-endpoint teardown (create-after-delete, never a leak)."""
    assert PostHogNode.webhook_replace_stale_endpoint is True


def test_oauth_scope_rejection_helpers():
    """Post-exchange scope validation mirrors Google: partial/read-only grants
    are rejected with a message carrying the FE marker "didn't grant"."""
    from wss.handlers.oauth.posthog_oauth_handler import (
        find_missing_granted_scopes, format_missing_scopes_message,
    )
    requested = ["openid", "email", "feature_flag:write", "hog_function:write", "query:read"]
    granted = "feature_flag:read query:read"
    missing = find_missing_granted_scopes(requested, granted)
    assert missing == ["feature_flag:write", "hog_function:write"]  # identity scopes excluded
    msg = format_missing_scopes_message(missing)
    assert "didn't grant" in msg  # OAuthErrorPanel marker → "Permissions missing" heading
    assert "hog_function:write" in msg
    # full grant → no rejection
    assert find_missing_granted_scopes(requested, " ".join(requested)) == []


# ------------------------------------------------------------------ destinations (CDP / hog functions)


@pytest.mark.asyncio
async def test_list_destinations_defaults_to_destination_type():
    from nodes.posthog_node import PostHogListDestinationsConfig
    _, cap = await run_rest(PostHogListDestinationsConfig(limit="10"))
    assert cap["path"] == "/api/projects/42/hog_functions/"
    assert cap["params"]["types"] == "destination"


@pytest.mark.asyncio
async def test_create_destination_wraps_plain_inputs():
    """Plain input values are wrapped into PostHog's {value: …} shape."""
    from nodes.posthog_node import PostHogCreateDestinationConfig
    _, cap = await run_rest(PostHogCreateDestinationConfig(
        template_id="template-webhook", name="My hook",
        inputs_json='{"url":"https://x.example","method":{"value":"POST"}}',
        filters_json='{"events":[{"id":"$pageview","type":"events"}]}', enabled="true"))
    assert cap["method"] == "POST"
    body = cap["json_body"]
    assert body["type"] == "destination" and body["template_id"] == "template-webhook"
    assert body["inputs"]["url"] == {"value": "https://x.example"}          # wrapped
    assert body["inputs"]["method"] == {"value": "POST"}                     # already shaped
    assert body["filters"]["events"][0]["id"] == "$pageview"
    assert body["enabled"] is True


@pytest.mark.asyncio
async def test_set_destination_enabled_and_delete_are_patches():
    from nodes.posthog_node import PostHogSetDestinationEnabledConfig, PostHogDeleteDestinationConfig
    _, cap = await run_rest(PostHogSetDestinationEnabledConfig(destination_id="hf9", enabled="false"))
    assert cap["method"] == "PATCH" and cap["json_body"] == {"enabled": False}
    _, cap = await run_rest(PostHogDeleteDestinationConfig(destination_id="hf9"))
    assert cap["method"] == "PATCH" and cap["json_body"] == {"deleted": True}
    assert cap["path"] == "/api/projects/42/hog_functions/hf9/"


@pytest.mark.asyncio
async def test_destination_logs_and_metrics_paths():
    from nodes.posthog_node import PostHogDestinationLogsConfig, PostHogDestinationMetricsConfig
    _, cap = await run_rest(PostHogDestinationLogsConfig(destination_id="hf9", level="ERROR", limit="20"))
    assert cap["path"] == "/api/projects/42/hog_functions/hf9/logs/"
    assert cap["params"]["level"] == "ERROR"
    _, cap = await run_rest(PostHogDestinationMetricsConfig(destination_id="hf9"))
    assert cap["path"] == "/api/projects/42/hog_functions/hf9/metrics/totals/"
    assert cap["params"]["after"] == "-7d"  # default window


@pytest.mark.asyncio
async def test_list_destination_templates_filters_client_side():
    """The templates endpoint ignores ?search= (verified live) — the op fetches
    the catalog and substring-filters on name/id itself."""
    from nodes.posthog_node import PostHogListDestinationTemplatesConfig
    resp = {"status": "success", "action": "x", "data": {"results": [
        {"id": "template-slack", "name": "Slack"},
        {"id": "template-webhook", "name": "HTTP Webhook"},
        {"id": "template-hubspot", "name": "HubSpot"}]}}
    result, cap = await run_rest(PostHogListDestinationTemplatesConfig(search="webhook"), response=resp)
    assert cap["path"] == "/api/projects/42/hog_function_templates/"
    assert [t["id"] for t in result["data"]["results"]] == ["template-webhook"]


@pytest.mark.asyncio
async def test_dropdown_destination_and_template():
    async def fake(cred_, method, path, params=None, json_body=None, action_name="request", quiet_statuses=()):
        if "hog_function_templates" in path:
            return {"status": "success", "data": {"results": [{"id": "template-slack", "name": "Slack"}]}}
        return {"status": "success", "data": {"results": [{"id": "hf1", "name": "My hook"}]}}

    with patch("nodes.posthog_node._rest_request", side_effect=fake):
        d = await PostHogNode.load_field_options("destination_id", cred().model_dump())
        t = await PostHogNode.load_field_options("template_id", cred().model_dump())
    assert d["options"] == [{"label": "My hook", "value": "hf1"}]
    assert t["options"] == [{"label": "Slack", "value": "template-slack"}]


@pytest.mark.asyncio
async def test_add_persons_to_static_cohort_is_patch_with_person_ids():
    """The endpoint is PATCH and the key is person_ids — POST 405s and
    person_uuids 400s (probed live 2026-07-17); the legacy key is remapped."""
    from nodes.posthog_node import PostHogAddPersonsToCohortConfig
    _, cap = await run_rest(PostHogAddPersonsToCohortConfig(cohort_id="7", body_json='{"person_ids":["u1"]}'))
    assert cap["method"] == "PATCH"
    assert cap["path"] == "/api/projects/42/cohorts/7/add_persons_to_static_cohort/"
    assert cap["json_body"] == {"person_ids": ["u1"]}
    _, cap = await run_rest(PostHogAddPersonsToCohortConfig(cohort_id="7", body_json='{"person_uuids":["u1"]}'))
    assert cap["json_body"] == {"person_ids": ["u1"]}  # legacy key remapped


def test_oauth_scope_validation_write_implies_read():
    """Regression: PostHog normalizes grants so X:write implies X:read — a
    full-access consent returns only the write scope per resource. The literal
    comparison false-rejected EVERY full grant with 'Permissions missing' on
    the implied :read scopes."""
    from wss.handlers.oauth.posthog_oauth_handler import find_missing_granted_scopes
    requested = ["openid", "email", "insight:read", "insight:write",
                 "dashboard:read", "dashboard:write", "project:read", "query:read"]
    # what PostHog actually returns for a full grant: write-only per resource
    granted = "insight:write dashboard:write project:read query:read"
    assert find_missing_granted_scopes(requested, granted) == []
    # all-access wildcard grant
    assert find_missing_granted_scopes(requested, "*") == []
    # a genuinely read-only grant is still rejected on the write scopes
    assert find_missing_granted_scopes(requested, "insight:read dashboard:read project:read query:read") == [
        "insight:write", "dashboard:write"]


@pytest.mark.asyncio
async def test_replace_tears_down_both_divergent_stale_ids():
    """Regression: the config mirror and the webhooks ROW can point at DIFFERENT
    stale hog functions (headless re-register raced by a panel edit). Replacement
    must tear down BOTH candidates or the unchosen one leaks provider-side."""
    deleted, created = [], []

    async def fake_rest(cred_, method, path, params=None, json_body=None, action_name="request", quiet_statuses=()):
        if method == "PATCH" and json_body == {"deleted": True}:
            deleted.append(path.rsplit("/", 2)[-2])
            return {"status": "success", "data": {}}
        if method == "POST" and path.endswith("hog_functions/"):
            created.append(1)
            return {"status": "success", "data": {"id": "fnNEW"}}
        return {"status": "success", "data": {}}

    async def fake_get_or_create(**kw):
        return {"webhook_id": "w1", "webhook_url": "https://u.hooks.example.test", "is_active": True,
                "registered_operation": "on_custom_event", "registered_credential_id": "c1",
                "secret_set": False, "external_webhook_id": "fnROW"}

    async def fake_cred(cls, pool, user_id, credential_ids):
        return {"personal_api_key": "phx_x", "project_id": "42", "region": "us"}

    async def fake_persist(*a, **kw):
        return None

    from utils.webhook_manager import WebhookManager
    with patch("nodes.posthog_node._rest_request", side_effect=fake_rest), \
         patch.object(WebhookManager, "get_or_create_webhook", side_effect=fake_get_or_create), \
         patch.object(WebhookManager, "persist_registration_state", side_effect=fake_persist), \
         patch.object(PostHogNode, "_resolve_trigger_credential", classmethod(fake_cred)):
        r = await PostHogNode.load_field_value(
            "webhook_url", "u", "00000000-0000-0000-0000-000000000000", "n1", Mock(),
            context={"operation": "on_custom_event", "event_name": "evt_new",
                     "registered_event_name": "evt_old", "external_webhook_id": "fnCTX"},
            credential_ids={"posthog": "c1"})

    assert sorted(deleted) == ["fnCTX", "fnROW"]      # BOTH stale endpoints torn down
    assert created == [1]                              # exactly one new registration
    assert r["values"]["external_webhook_id"] == "fnNEW"
