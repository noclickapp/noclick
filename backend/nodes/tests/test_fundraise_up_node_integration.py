"""Fundraise Up execution through staging's current credential resolver."""
from copy import deepcopy
from unittest.mock import AsyncMock
import httpx
import pytest
from nodes import fundraise_up_node as native
from nodes.core.registry import NodeFactory
from nodes.tests.test_fundraise_up_node_mock import credential, supporter, page, transport, TOKEN

CID = "00000000-0000-4000-8000-000000000042"
USER = "00000000-0000-4000-8000-000000000001"
ORG = "00000000-0000-4000-8000-000000000003"
WORKFLOW = "00000000-0000-4000-8000-000000000004"

@pytest.fixture(autouse=True)
def ensure_native_db_pool(): yield

def saved(pool):
    return NodeFactory.create_node(node_id="fundraise-up-current", node_type=native.NODE_TYPE,
        node_data={"credential_id": CID, "_approval_pool": pool,
            "credentials": credential(api_key="stale-key"), "config": {"operation": "check_connection"}},
        user_id=USER, organization_id=ORG, workflow_id=WORKFLOW)

@pytest.mark.asyncio
async def test_fundraise_up_current_resolver_and_authority_arguments(monkeypatch):
    resolver = AsyncMock(side_effect=lambda **kwargs: deepcopy(credential()))
    monkeypatch.setattr("utils.credentials.resolve_credential_with_owner_fallback", resolver)
    requests, _ = transport(monkeypatch, page([supporter()]))
    pool = object()
    result = await saved(pool).execute({})
    assert result["status"] == "success"
    assert requests[0].headers["Authorization"] == "Bearer " + TOKEN
    assert resolver.await_count >= 3
    for call in resolver.await_args_list:
        assert call.kwargs == dict(credential_id=CID, user_id=USER, pool=pool, org_id=ORG, workflow_id=WORKFLOW)

@pytest.mark.asyncio
async def test_fundraise_up_unavailable_saved_credential_never_sends(monkeypatch):
    monkeypatch.setattr("utils.credentials.resolve_credential_with_owner_fallback", AsyncMock(return_value=None))
    requests, _ = transport(monkeypatch, page([]))
    with pytest.raises(ValueError, match="unavailable"):
        await saved(object()).execute({})
    assert requests == []

@pytest.mark.asyncio
@pytest.mark.parametrize("change", [{"api_key": "changed-key"}, {"livemode": True}, {"account_id": "B1234567"}, {"credential_type": "foreign"}])
async def test_fundraise_up_changed_saved_credential_discards_response(monkeypatch, change):
    current = credential()
    monkeypatch.setattr("utils.credentials.resolve_credential_with_owner_fallback", AsyncMock(side_effect=lambda **kwargs: deepcopy(current)))
    def reply(request):
        current.update(change)
        return httpx.Response(200, json=page([supporter()]))
    requests, _ = transport(monkeypatch, reply)
    with pytest.raises(ValueError):
        await saved(object()).execute({})
    assert len(requests) == 1

@pytest.mark.asyncio
async def test_fundraise_up_staging_picker_and_nonrotating_key_hook(monkeypatch):
    transport(monkeypatch, page([supporter()]))
    raw = credential()
    assert await native.FundraiseUpNode.freshen_credential(raw) == raw | {"check_resource": "supporters"}
    result = await native.FundraiseUpNode.load_field_options("supporter_id", raw)
    assert result == {"options": [{"value": "SAAAAAAA", "label": "SAAAAAAA"}], "next_page_token": None}

@pytest.mark.asyncio
@pytest.mark.parametrize("status,valid", [(200, True), (401, False), (403, False), (429, None)])
async def test_fundraise_up_access_hook_reachability_only(monkeypatch, status, valid):
    transport(monkeypatch, lambda request: httpx.Response(status, json=page([])))
    result = await native.FundraiseUpNode.validate_credential_access(credential())
    assert result["valid"] is valid
    assert TOKEN not in str(result)
    if valid: assert result["account_identity_verified"] is False
