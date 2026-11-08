"""Exercise Freshteam operations through staging native application dispatch.

Keep transport and credential reload regressions local to this integration.
"""
from contextlib import asynccontextmanager
import json
from unittest.mock import AsyncMock

import httpx
import pytest
from nodes import freshteam_node as native
from nodes.core.registry import NodeFactory
from nodes.core.run_op import run_node_operation
from nodes.core.credential_connect import validate_for_connect

TYPE = "automation-freshteam"
USER = "11111111-1111-4111-8111-111111111111"
CID = "22222222-2222-4222-8222-222222222222"
CREDENTIAL = {"credential_type": "freshteam", "account_name": "synthetic", "api_key": "synthetic-private-key"}
DEPARTMENT = {"id": 3000126932, "name": "Synthetic department", "deleted": False}
JOB = {"id": 3000042017, "title": "Synthetic job", "status": "draft", "remote": False, "department": DEPARTMENT}
EMPLOYEE = {"id": 3000053373, "first_name": "Synthetic", "last_name": "Employee", "designation": "Fixture", "department_id": DEPARTMENT["id"], "official_email": "omit@example.test", "bank_details": {"number": "omit-bank"}, "salary": {"amount": 100}, "government_documents": "omit-government"}
APPLICANT = {"id": 3001379428, "job_id": JOB["id"], "status": "open", "candidate": {"id": 3001335826, "first_name": "Synthetic", "last_name": "Candidate", "email": "omit@example.test", "eeo_gender": "omit-sensitive", "resumes": [{"url": "https://files.example.test/signed"}]}, "custom_fields": {"cf_metadata": "Old fixture"}}
TEXT_FIELD = {"id": 3000907498, "name": "cf_metadata", "label": "Synthetic CRM metadata", "field_type": "paragraph", "base_model": "applicant", "default": False}


def node(operation, credential=CREDENTIAL, **args):
    return NodeFactory.create_node(node_id="freshteam-fixture", node_type=TYPE, node_data={"config": {"operation": operation, **args}, "credentials": credential}, sio=None, sid=None, user_id=USER)


@pytest.fixture(autouse=True)
def admission(monkeypatch):
    monkeypatch.setattr("utils.credential_approval.admit_node", AsyncMock(return_value=None))


@pytest.fixture
def transport(monkeypatch):
    calls, responses = [], []
    async def receive(request):
        calls.append(request)
        value = responses.pop(0)
        if callable(value):
            value = value()
        return value if isinstance(value, httpx.Response) else httpx.Response(200, json=value)
    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs == {"timeout": 20, "follow_redirects": False, "trust_env": False}
        async with httpx.AsyncClient(transport=httpx.MockTransport(receive)) as value:
            yield value
    monkeypatch.setattr(native, "guarded_async_client", client)
    return calls, responses


@pytest.mark.parametrize("page", [True, "10", "10x", 1.5, 0, 10001])
def test_actual_factory_strict_page_bound_before_io(page, transport):
    with pytest.raises(ValueError):
        node("list_jobs", page=page)
    assert transport[0] == []


@pytest.mark.parametrize("tenant", ["http://synthetic.freshteam.com", "https://synthetic.freshdesk.com", "https://synthetic.freshteam.com/api", "https://synthetic.freshteam.com:443", "https://synthetic.freshteam.com?key=x", "127.0.0.1", "https://user@synthetic.freshteam.com", "synthetic#evil", "a.b"])
def test_tenant_admission_before_transport(tenant, transport):
    with pytest.raises(ValueError):
        node("check_connection", credential={**CREDENTIAL, "account_name": tenant})
    assert transport[0] == []


def test_original_foreign_row_tag_precedes_reconciliation(transport):
    with pytest.raises(ValueError):
        NodeFactory.create_node(node_id="foreign", node_type=TYPE, node_data={"config": {"operation": "check_connection"}, "credentials": {**CREDENTIAL, "credential_type": "freshsales_api_key"}, "credentialIds": {"freshteam": CID}}, sio=None, sid=None)
    assert transport[0] == []


@pytest.mark.asyncio
async def test_visible_only_connect_uses_bearer_and_honest_tenant_reachability(transport):
    transport[1].append([DEPARTMENT])
    verdict = await validate_for_connect(credential_type="freshteam", credential_data={key: value for key, value in CREDENTIAL.items() if key != "credential_type"}, user_id=USER)
    assert verdict.ok and verdict.credential_data["credential_type"] == "freshteam"
    assert transport[0][0].url.host == "synthetic.freshteam.com"
    assert transport[0][0].url.path == "/api/departments"
    assert transport[0][0].headers["Authorization"] == "Bearer synthetic-private-key"
    assert native.FreshteamNode.connection_evidence.proves == "reachability"
    transport[1].append([])
    result = await node("check_connection").execute({})
    assert result["data"]["api_access_accepted"] and not result["data"]["authenticated_identity_available"]
    assert not result["data"]["operation_permissions_verified"]


@pytest.mark.asyncio
async def test_employee_projection_uses_large_ids_and_discards_hr_fields(transport):
    transport[1].append(EMPLOYEE)
    result = await node("get_employee", employee_id=str(EMPLOYEE["id"])).execute({})
    assert result["data"]["id"] == 3000053373
    assert all(secret not in repr(result) for secret in ("omit@example.test", "omit-bank", "omit-government", "salary"))


@pytest.mark.asyncio
async def test_numeric_page_false_remote_and_no_follow_of_link(transport):
    transport[1].append(httpx.Response(200, json=[JOB], headers={"total-pages": "12", "link": "https://foreign.example.test/?secret=x"}))
    result = await node("list_jobs", page=10, remote=False).execute({})
    assert dict(transport[0][0].url.params) == {"page": "10", "remote": "false"}
    assert result["data"]["next_page"] == 11 and result["data"]["automatic_paging"] is False
    assert len(transport[0]) == 1 and "foreign" not in repr(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("remote", [None, False, True])
async def test_unset_false_true_remote_distinction(transport, remote):
    transport[1].append([JOB])
    await node("list_jobs", remote=remote).execute({})
    expected = {"page": "1"} if remote is None else {"page": "1", "remote": "true" if remote else "false"}
    assert dict(transport[0][0].url.params) == expected


@pytest.mark.asyncio
async def test_job_scope_and_response_exact_ids(transport):
    transport[1].extend([JOB, {**APPLICANT, "job_id": 99}])
    with pytest.raises(ValueError, match="outside"):
        await node("get_applicant", job_id=str(JOB["id"]), applicant_id=str(APPLICANT["id"])).execute({})
    assert [request.url.path for request in transport[0]] == ["/api/job_postings/3000042017", "/api/applicants/3001379428"]


@pytest.mark.asyncio
async def test_job_parent_picker_and_custom_entry_qualification(transport):
    with pytest.raises(ValueError):
        await native.FreshteamNode.load_field_options("applicant_id", CREDENTIAL, context={})
    assert transport[0] == []
    transport[1].extend([JOB, httpx.Response(200, json=[APPLICANT], headers={"total-pages": "2"})])
    result = await native.FreshteamNode.load_field_options("applicant_id", CREDENTIAL, context={"job_id": str(JOB["id"])})
    assert result == {"options": [{"value": str(APPLICANT["id"]), "label": "Synthetic Candidate"}], "next_page_token": "2"}
    assert "omit@example.test" not in repr(result)


@pytest.mark.asyncio
async def test_custom_text_update_and_separate_selected_field_readback(transport):
    updated = {**APPLICANT, "custom_fields": {"cf_metadata": "New fixture"}}
    transport[1].extend([JOB, APPLICANT, [TEXT_FIELD], updated])
    result = await node("update_applicant_text_field", job_id=str(JOB["id"]), applicant_id=str(APPLICANT["id"]), field_name="cf_metadata", value="New fixture").execute({})
    assert transport[0][-1].method == "PUT"
    assert json.loads(transport[0][-1].content) == {"custom_fields": {"cf_metadata": "New fixture"}}
    assert result["data"]["write_acknowledged"] and not result["data"]["readback_verified"]
    transport[1].extend([JOB, updated, [TEXT_FIELD]])
    readback = await node("get_applicant", job_id=str(JOB["id"]), applicant_id=str(APPLICANT["id"]), field_name="cf_metadata").execute({})
    assert readback["data"]["text_metadata"] == {"field_name": "cf_metadata", "value": "New fixture"}
    assert "omit-sensitive" not in repr(readback) and "signed" not in repr(readback)


@pytest.mark.asyncio
@pytest.mark.parametrize("defect", ["default", "candidate", "attachment", "populated_other"])
async def test_unqualified_text_mutation_refuses_before_write(transport, defect):
    field = {**TEXT_FIELD, **{"default": {"default": True}, "candidate": {"base_model": "candidate"}, "attachment": {"field_type": "attachment"}, "populated_other": {}}[defect]}
    raw = {**APPLICANT, "custom_fields": {"cf_metadata": "Old", "cf_other": "preserve"}} if defect == "populated_other" else APPLICANT
    transport[1].extend([JOB, raw, [field]])
    with pytest.raises(ValueError, match="Only an existing"):
        await node("update_applicant_text_field", job_id=str(JOB["id"]), applicant_id=str(APPLICANT["id"]), field_name="cf_metadata", value="New").execute({})
    assert all(request.method == "GET" for request in transport[0])


@pytest.mark.asyncio
async def test_create_source_201_closed_body_and_honest_cleanup(transport):
    # https://developers.freshteam.com/api/ — Create a candidate source.
    transport[1].append(httpx.Response(201, json={"id": 3000185680, "created_at": "2021-01-29T09:12:45.000Z", "updated_at": "2021-01-29T09:12:45.000Z", "deleted": False, "label": "JobAgency", "default": False, "leads_count": 0}))
    result = await node("create_candidate_source", label="JobAgency").execute({})
    assert json.loads(transport[0][0].content) == {"label": "JobAgency"}
    assert result["data"]["readback_verified"] is False
    assert result["data"]["cleanup_method"] == "owned Freshteam UI; API delete unavailable"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 429, 500])
async def test_safe_tri_state_provider_errors(transport, status):
    transport[1].append(httpx.Response(status, text="synthetic-private-key confidential body"))
    verdict, error = await native.FreshteamNode.validate_credential_access(CREDENTIAL)
    assert verdict is (False if status == 401 else None)
    assert "synthetic-private-key" not in error and "confidential" not in error


@pytest.fixture
def current_credential(monkeypatch):
    state = {"credential": dict(CREDENTIAL)}
    monkeypatch.setattr(native, "resolve_credential_with_owner_fallback", AsyncMock(side_effect=lambda *args, **kwargs: state["credential"]))
    return state


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["access", "type", "key", "tenant"])
async def test_saved_dispatch_discards_inflight_credential_changes(transport, current_credential, change):
    def returned():
        delta = {"type": {"credential_type": "foreign"}, "key": {"api_key": "different-key"}, "tenant": {"account_name": "different"}}
        current_credential["credential"] = None if change == "access" else {**CREDENTIAL, **delta[change]}
        return [DEPARTMENT]
    transport[1].append(returned)
    with pytest.raises(ValueError, match="unavailable"):
        await run_node_operation(node_type=TYPE, operation="check_connection", arguments={}, credential_data=CREDENTIAL, user_id=USER, credential_id=CID, pool=object(), organization_id=None)
    assert len(transport[0]) == 1


@pytest.mark.asyncio
async def test_saved_missing_caller_and_stored_foreign_payload_refuse_before_io(transport, current_credential):
    value = node("check_connection")
    value.user_id = None
    value.node_data["credential_id"] = CID
    with pytest.raises(ValueError, match="unavailable"):
        await value.execute({})
    current_credential["credential"] = {**CREDENTIAL, "credential_type": "foreign"}
    with pytest.raises(ValueError, match="unavailable") as exc:
        await native._Authority.create(CREDENTIAL, credential_id=CID, user_id=USER, pool=object(), organization_id=None)
    assert "synthetic-private-key" not in str(exc.value)
    assert transport[0] == []


@pytest.mark.asyncio
async def test_saved_picker_rechecks_access_before_request(transport, current_credential):
    authority = await native._Authority.create(CREDENTIAL, credential_id=CID, user_id=USER, pool=object(), organization_id=None)
    current_credential["credential"] = None
    with pytest.raises(ValueError, match="unavailable"):
        await native.FreshteamNode.load_field_options("job_id", {**CREDENTIAL, native._AUTH_KEY: authority})
    assert transport[0] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [[{**DEPARTMENT, "id": True}], [DEPARTMENT, DEPARTMENT], {"departments": [DEPARTMENT]}, [None]])
async def test_malformed_collections_are_not_access_proof(transport, payload):
    transport[1].append(payload)
    verdict, error = await native.FreshteamNode.validate_credential_access(CREDENTIAL)
    assert verdict is None and "unverified" in error


def test_actual_native_export_config_keeps_integer_and_nullable_boolean():
    value = node("list_jobs", page=10, remote=False).config.model_dump()
    hydrated = native.FreshteamNodeConfig.model_validate(json.loads(json.dumps(value)))
    assert type(hydrated.config.page) is int and hydrated.config.page == 10
    assert hydrated.config.remote is False
    null_value = node("list_jobs", remote=None).config.model_dump()
    assert native.FreshteamNodeConfig.model_validate(null_value).config.remote is None
