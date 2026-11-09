"""Transport and poll tests. DTOs are opaque in the provider's Swagger 1.0.

Empty objects exercise that published lower bound; populated test objects are
synthetic and deliberately assert no undocumented field names.
"""
import httpx
import pytest
from pydantic import ValidationError

from nodes.small_improvements_node import (
    SmallImprovementsNode, SmallImprovementsPersonalAccessToken,
)
from nodes.core.poll_trigger import poll_scope


def node(operation, **config):
    cls = SmallImprovementsNode
    data = {"config": {"operation": operation, **config},
            "credentials": {"credential_type": "small_improvements_personal_access_token",
                            "access_token": "test-personal-token"}}
    return cls(node_id="si", node_type=cls.integration_type, node_data={}, config=cls.parse_config(data))


@pytest.mark.asyncio
async def test_token_region_and_query_transport(monkeypatch):
    requests = []

    async def request(self, method, url, **kwargs):
        request = httpx.Request(method, url, params=kwargs.get("params"), headers=kwargs["headers"])
        requests.append(request)
        return httpx.Response(200, json={}, request=request)

    monkeypatch.setattr(httpx.AsyncClient, "request", request)
    credential = SmallImprovementsPersonalAccessToken(access_token="test-personal-token", data_center="eu")
    await SmallImprovementsNode._request(credential, "GET", "/v2/users/me")
    request = requests[0]
    assert str(request.url) == "https://eu.small-improvements.com/api/v2/users/me"
    assert request.headers["Authorization"] == "Bearer test-personal-token"
    assert SmallImprovementsPersonalAccessToken.model_fields["credential_type"].default == "small_improvements_personal_access_token"


@pytest.mark.parametrize("operation,config,method,path,params,body", [
    ("set_manager", {"user_id": "employee", "manager_id": "manager"}, "PUT", "/v2/users/employee/manager", {"managerId": "manager"}, None),
    ("set_secondary_reviewer", {"user_id": "employee", "reviewer_id": "reviewer"}, "PUT", "/v2/users/employee/secondary-reviewer", {"secondaryReviewerId": "reviewer"}, None),
    ("set_objective_completion", {"cycle_id": "cycle", "objective_id": "objective", "completion_percentage": 75}, "POST", "/v2/objective-cycles/cycle/objectives/objective/changeCompletionPercentage", {"completionPercentage": 75}, None),
    ("lock_users", {"user_ids": ["employee"]}, "POST", "/v2/users/roles/lock", {}, ["employee"]),
    ("unlock_users", {"user_ids": ["employee"]}, "POST", "/v2/users/roles/unlock", {}, ["employee"]),
    ("delete_praise_comment", {"praise_id": "praise", "comment_id": "comment"}, "DELETE", "/v2/praise/praise/comments/comment", {}, None),
])
@pytest.mark.asyncio
async def test_mutations_have_exact_contract_wire_shape(monkeypatch, operation, config, method, path, params, body):
    seen = []

    async def request(credential, actual_method, actual_path, **kwargs):
        seen.append((actual_method, actual_path, kwargs))
        return None

    monkeypatch.setattr(SmallImprovementsNode, "_request", staticmethod(request))
    assert await node(operation, **config).execute({}) == {"data": None}
    assert seen == [(method, path, {"params": params, "body": body})]


@pytest.mark.parametrize("values", [
    {"operation": "set_manager", "user_id": "a"},
    {"operation": "get_user", "user_id": "../users/me"},
    {"operation": "set_objective_completion", "cycle_id": "a", "objective_id": "b", "completion_percentage": 101},
    {"operation": "lock_users", "user_ids": []},
    {"operation": "list_praise", "start_date": "yesterday"},
    {"operation": "on_new_or_changed_praise", "start_date": "2026-01-01"},
])
def test_invalid_config_rejected(values):
    with pytest.raises(ValueError):
        SmallImprovementsNode.parse_config({"config": values})


@pytest.mark.parametrize("kwargs", [
    {"access_token": "https://example.com/token"},
    {"access_token": "Bearer token"},
    {"access_token": "test-token", "data_center": "evil.example"},
])
def test_credential_boundaries(kwargs):
    with pytest.raises(ValidationError):
        SmallImprovementsPersonalAccessToken(**kwargs)


@pytest.mark.asyncio
@pytest.mark.parametrize("padding", [0, 1980])
async def test_provider_failure_redacts_token_and_does_not_retry(monkeypatch, padding):
    calls = []

    async def request(self, method, url, **kwargs):
        calls.append(method)
        return httpx.Response(401, text="Rejected " + "x" * padding + "test-personal-token", request=httpx.Request(method, url))

    monkeypatch.setattr(httpx.AsyncClient, "request", request)
    with pytest.raises(ValueError, match="401: Rejected") as error:
        await node("get_current_user").execute({})
    assert "[redacted]" in str(error.value)
    assert "test-per" not in str(error.value)
    assert calls == ["GET"]


@pytest.mark.asyncio
async def test_poll_schema_minimum_and_changed_opaque_records(monkeypatch):
    n = node("on_new_or_changed_praise", recipient_id="employee")
    state = {"seen_ids": []}
    page = [{}]  # Valid MessageDto: the published schema is an opaque object.
    calls = []

    async def update(mutator, **kwargs):
        new_state, result = mutator(dict(state))
        if new_state is not None:
            state.clear()
            state.update(new_state)
        return result

    async def request(credential, method, path, **kwargs):
        calls.append((method, path, kwargs))
        return page

    n._update_node_state = update
    monkeypatch.setattr(SmallImprovementsNode, "_request", staticmethod(request))
    result = await n.execute({})
    assert result["new_or_changed_count"] == 1
    assert SmallImprovementsNode.resolve_agent_event(result)["text"].startswith("Small Improvements: 1")
    assert (await n.execute({}))["new_or_changed_count"] == 0
    assert SmallImprovementsNode.resolve_agent_event(await n.execute({})) is None
    page = [{"synthetic_test_field": "updated"}]
    assert (await n.execute({}))["new_or_changed_count"] == 1
    assert calls[0] == ("GET", "/v2/praise", {"params": {"recipientId": "employee", "limit": 100, "offset": 0}})


@pytest.mark.asyncio
async def test_poll_reads_all_pages_before_state_and_rejects_truncation(monkeypatch):
    n = node("on_new_or_changed_praise")
    pages, state_calls = [], []

    async def request(credential, method, path, **kwargs):
        pages.append(kwargs["params"]["offset"])
        return [{}] * 100

    async def unseen(*args):
        state_calls.append(True)
        return []

    monkeypatch.setattr(SmallImprovementsNode, "_request", staticmethod(request))
    n._filter_unseen = unseen
    with pytest.raises(ValueError, match="exceeds 10,000"):
        await n.execute({})
    assert pages == list(range(0, 10000, 100))
    assert not state_calls


def test_poll_scope_uses_declared_fields():
    a = {"operation": "on_new_or_changed_praise", "recipient_id": "a"}
    assert poll_scope(SmallImprovementsNode, a) == poll_scope(SmallImprovementsNode, {**a, "label": "renamed"})
    assert poll_scope(SmallImprovementsNode, a) != poll_scope(SmallImprovementsNode, {**a, "recipient_id": "b"})


def test_provider_id_validation_does_not_restrict_scheduler_ids():
    n = node("on_new_or_changed_praise", schedule_id="cron:workflow:node", webhook_id="relay:node")
    assert n.config.config.schedule_id == "cron:workflow:node"
    assert n.config.config.webhook_id == "relay:node"
