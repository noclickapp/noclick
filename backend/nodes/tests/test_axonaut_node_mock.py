"""Actual native Axonaut seams; only DB, encryption and HTTP boundaries are synthetic."""
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime, timezone
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

USER = "00000000-0000-4000-8000-000000000001"
OWNER = "00000000-0000-4000-8000-000000000002"
CID = "00000000-0000-4000-8000-000000000003"
WORKFLOW = "00000000-0000-4000-8000-000000000004"
KEY = "axonaut-synthetic-fixture-key-42"
FAMILY = "axonaut_api_key"
NOW = datetime(2026, 10, 6, tzinfo=timezone.utc)


@pytest.fixture
def ensure_native_db_pool():
    yield


def company(**extra):
    return {"id": 42, "name": "Fixture company", "is_customer": True, "iban": "private bank",
        "employees": [{"email": "private@example.test"}], "comments": KEY, **extra}


def contact(**extra):
    return {"id": 43, "company_id": 42, "firstname": "Fixture", "lastname": "Contact", "email": "private@example.test", **extra}


def opportunity(**extra):
    return {"id": 44, "name": "Fixture opportunity", "company": {"id": 42, "name": 42},
        "amount": 12.3, "comments": KEY, "employees": [{"email": "private@example.test"}], **extra}


def task(**extra):
    return {"id": 45, "company_id": 42, "project_id": 46, "title": "Fixture task", "priority": "normale", "description": KEY, **extra}


def project(**extra):
    return {"id": 46, "company_id": 42, "name": "Fixture project", "comments": KEY, "estimated_cost": 500, "workforces": [{"email": "private@example.test"}], **extra}


def me(**extra):
    return {"id": 7, "fullname": "Fixture operator", "user_api_key": KEY, "email": "private@example.test",
        "account": [{"id": 8, "company_name": "Fixture account", "company_phone": "private phone"}], **extra}


@pytest.fixture
def native(monkeypatch):
    from nodes import axonaut_node as provider
    from nodes.core import credential_connect, connection_evidence
    from repositories.credentials import credential_access_predicate
    from repositories.organization import OrgRepo
    from repositories.credential_approvals import CredentialApprovalRepo
    from utils import credentials, encryption, credential_approval

    state = SimpleNamespace(blob={"api_key": KEY}, allowed={USER}, requests=[], constructors=[], replies={}, after_read=None,
        approval=None, sql=[], row={"id": CID, "owner_id": USER, "credential_type": FAMILY, "credential": b"synthetic-blob",
        "token_version": 7, "updated_at": NOW, "created_at": NOW, "revoked_at": None, "approval_revision": 0, "name": "Fixture key", "metadata": {}})

    class Pool:
        @asynccontextmanager
        async def acquire(self):
            yield self

        async def fetchrow(self, sql, *args):
            state.sql.append((sql, args))
            assert credential_access_predicate() in sql
            return deepcopy(state.row) if args[0] == CID and args[1] in state.allowed else None

    state.pool, state.crypto = Pool(), MagicMock()
    state.crypto.decrypt_credential.side_effect = lambda _: deepcopy(state.blob)
    monkeypatch.setattr(encryption, "get_encryption", lambda: state.crypto)
    monkeypatch.setattr(credentials, "get_encryption", lambda: state.crypto)
    monkeypatch.setattr(OrgRepo, "get_primary_org_id", AsyncMock(return_value=None))
    monkeypatch.setattr(credentials, "get_workflow_owner_id", AsyncMock(return_value=OWNER))
    state.workflow_grant = AsyncMock(return_value=True)
    monkeypatch.setattr(credentials, "is_credential_authorized_for_workflow", state.workflow_grant)
    state.admit = AsyncMock(side_effect=lambda **_: state.approval)
    monkeypatch.setattr(CredentialApprovalRepo, "admit", state.admit)
    monkeypatch.setattr(credential_approval, "get_frontend_url", lambda: "https://fixture.invalid")
    monkeypatch.setattr(credential_connect, "_collect_evidence", connection_evidence.collect_evidence)
    credential_connect._class_index.cache_clear()
    defaults = {"companies": [company()], "companies/42": company(), "me": me(),
        "employees/43": contact(), "opportunities/44": opportunity(), "tasks/45": task(), "projects/46": project()}

    def respond(request):
        state.requests.append(request)
        route = request.url.path.removeprefix("/api/v2/")
        reply = state.replies.get((request.method, route))
        if reply is None and request.method == "GET" and route in defaults:
            reply = (200, defaults[route])
        assert reply is not None, (request.method, route)
        status, payload, *headers = reply
        result = httpx.Response(status, json=payload, headers=headers[0] if headers else {})
        if request.method == "GET" and state.after_read:
            callback, state.after_read = state.after_read, None
            callback()
        return result

    original = httpx.AsyncClient

    class LocalClient(original):
        def __init__(self, *args, **kwargs):
            state.constructors.append(kwargs)
            super().__init__(*args, **kwargs, transport=httpx.MockTransport(respond))

    monkeypatch.setattr(provider.httpx, "AsyncClient", LocalClient)

    async def run(operation, args=None, *, saved=False, blob=None, workflow_id=None):
        from nodes.core.run_op import run_node_operation
        return await run_node_operation(node_type="automation-axonaut", operation=operation, arguments=args or {},
            user_id=USER, pool=state.pool, organization_id=None, credential_id=CID if saved else None,
            credential_data=(blob or {"api_key": KEY}) if not saved else None, workflow_id=workflow_id)

    state.run = run
    yield state
    credential_connect._class_index.cache_clear()


async def test_actual_factory_schema_connect_header_and_safe_identity(native):
    from nodes.core.credential_connect import shape_credential, validate_for_connect
    from nodes.core.registry import NodeFactory
    from nodes.axonaut_node import AxonautNode
    shaped, errors, resolved = shape_credential(FAMILY, {"api_key": KEY})
    assert not errors and shaped["api_key"] == KEY and resolved[0] == "automation-axonaut"
    assert NodeFactory.is_registered("automation-axonaut")
    assert len(AxonautNode.get_config_schema()["properties"]["config"]["discriminator"]["mapping"]) == 30
    verdict = await validate_for_connect(credential_type=FAMILY, credential_data={"api_key": KEY}, user_id=USER)
    assert verdict.ok and verdict.evidence.samples[0].label == "Fixture company"
    request = native.requests[-1]
    assert request.headers["userApiKey"] == KEY and "Authorization" not in request.headers
    assert request.url.host == "axonaut.com" and request.url.path == "/api/v2/companies"
    assert dict(request.url.params) == {"type": "all"} and "page" not in request.headers
    assert all(c["trust_env"] is False and c["follow_redirects"] is False for c in native.constructors)
    result = await native.run("get_account")
    assert result["data"] == {"id": 7, "fullname": "Fixture operator", "accounts": [{"id": 8, "company_name": "Fixture account"}]}
    assert KEY not in json.dumps(result) and "private" not in json.dumps(result)


@pytest.mark.parametrize("blob", [{}, {"api_key": None}, {"api_key": "Bearer " + KEY}, {"api_key": "two words"}])
async def test_invalid_key_shaping_refuses_before_provider_probe(native, blob):
    from nodes.core.credential_connect import validate_for_connect
    verdict = await validate_for_connect(credential_type=FAMILY, credential_data=blob, user_id=USER)
    assert not verdict.ok and verdict.field_errors and native.requests == []


@pytest.mark.parametrize("tag", [None, "", " ", 7, "slack_oauth", " axonaut_api_key "])
def test_raw_native_family_refusal_precedes_base_reconciliation(native, tag):
    from nodes.core.registry import NodeFactory
    from nodes.core.base import ConfigValidationError
    from nodes.axonaut_node import AxonautNode
    raw = {"config": {"operation": "list_companies"}, "credentials": {"api_key": KEY, "credential_type": tag}}
    assert AxonautNode.validate_config(raw)["valid"] is False
    with pytest.raises(ConfigValidationError):
        NodeFactory.create_node("fixture", "automation-axonaut", raw, user_id=USER)
    assert native.requests == []


async def test_dispatcher_rereads_current_row_and_authorized_owner_fallback(native):
    native.blob["credential_type"] = "slack_oauth"
    assert (await native.run("list_companies", saved=True))["status"] == "success"
    native.allowed, native.row["owner_id"] = {OWNER}, OWNER
    assert (await native.run("list_companies", saved=True, workflow_id=WORKFLOW))["status"] == "success"
    native.workflow_grant.return_value = False
    native.requests.clear()
    with pytest.raises(ValueError):
        await native.run("list_companies", saved=True, workflow_id=WORKFLOW)
    assert native.requests == []


@pytest.mark.parametrize("change", ["reconnect", "revoked", "foreign", "denied"])
async def test_current_authority_changes_after_parent_read_block_write(native, change):
    def mutate():
        if change == "reconnect":
            native.blob["api_key"] = "other-synthetic-key"
        elif change == "revoked":
            native.row["revoked_at"] = NOW
        elif change == "foreign":
            native.row["credential_type"] = "slack_oauth"
        else:
            native.allowed.clear()
    native.after_read = mutate
    result = await native.run("update_company", {"company_id": 42, "name": "Updated", "confirm_management_write": True}, saved=True)
    assert result["status"] == "error" and len(native.requests) == 1 and KEY not in json.dumps(result)


@pytest.mark.parametrize("approval", ["pending", "rejected"])
async def test_real_admission_nonexecution_does_not_verify_or_probe(native, approval):
    from nodes.core.connection_evidence import collect_evidence
    from nodes.core.run_op import run_node_lookup
    native.approval = {"status": approval, "id": CID, "new_request": False}
    result = await collect_evidence(node_type="automation-axonaut", credential_id=CID, user_id=USER, pool=native.pool)
    assert result.reachable is None and result.samples == [] and native.requests == []
    picker = await run_node_lookup(node_type="automation-axonaut", field_name="company_id", credential_id=CID,
        user_id=USER, pool=native.pool, organization_id=None)
    assert picker["executed"] is False and native.requests == []


@pytest.mark.parametrize("op,route,payload,args", [
    ("list_contacts", "companies/42/employees", [contact()], {"company_id": 42}),
    ("list_opportunities", "companies/42/opportunities", [opportunity()], {"company_id": 42, "status": "ongoing"}),
    ("list_tasks", "tasks", [task()], {}), ("list_projects", "projects", [project()], {"name": "Fixture"}),
    ("list_pipes", "pipes", [{"id": 48, "name": "Fixture pipeline", "pipe_steps": [{"name": "Qualified", "order_number": 1}]}], {}),
    ("list_task_natures", "taskNatures", [{"id": 49, "name": "Fixture type"}], {}),
])
async def test_lists_are_bare_arrays_and_page_is_only_a_header(native, op, route, payload, args):
    native.replies[("GET", route)] = (200, payload)
    result = await native.run(op, {**args, "page": 2})
    assert result["status"] == "success" and result["data"]["has_more"] is None and result["data"]["next_page_token"] is None
    request = native.requests[-1]
    assert request.headers["page"] == "2" and "page" not in request.url.params
    assert "private" not in json.dumps(result) and KEY not in json.dumps(result)


@pytest.mark.parametrize("op,route", [("list_task_statuses", "taskStatus"), ("list_project_natures", "projectNatures")])
async def test_unpaged_reference_lists_have_no_invented_header(native, op, route):
    native.replies[("GET", route)] = (200, [{"id": 49, "name": "Fixture type"}])
    assert (await native.run(op))["status"] == "success" and "page" not in native.requests[-1].headers


@pytest.mark.parametrize("kind,row,identifier", [("company", company(), 42), ("contact", contact(), 43),
    ("opportunity", opportunity(), 44), ("task", task(), 45), ("project", project(), 46)])
async def test_native_get_create_update_delete_contracts_all_resource_kinds(native, kind, row, identifier):
    resources = {"company": "companies", "contact": "employees", "opportunity": "opportunities", "task": "tasks", "project": "projects"}
    route = resources[kind]
    bound = {kind + "_id": identifier, **({"company_id": 42} if kind != "company" else {})}
    assert (await native.run("get_" + kind, bound))["data"]["id"] == identifier
    create = {"name": row.get("name")} if kind in {"company", "opportunity", "project"} else (
        {"firstname": "Fixture", "lastname": "Contact", "email": "contact@example.test"} if kind == "contact" else {"title": "Fixture task", "project_id": 46})
    if kind != "company":
        create["company_id"] = 42
    native.replies[("POST", route)] = (200, row)
    result = await native.run("create_" + kind, {**create, "confirm_management_write": True})
    assert result["status"] == "success" and result["data"]["verified_readback"] is None
    body = json.loads(native.requests[-1].content)
    assert "confirm_management_write" not in body
    assert body["company_id"] == 42 if kind != "company" else body["isB2C"] is False
    update = {"firstname": "Fixture"} if kind == "contact" else {"title": "Fixture task"} if kind == "task" else {"name": row["name"]}
    native.replies[("PATCH", route + "/" + str(identifier))] = (200, row)
    assert (await native.run("update_" + kind, {**bound, **update, "confirm_management_write": True}))["status"] == "success"
    assert json.loads(native.requests[-1].content) == update
    native.replies[("DELETE", route + "/" + str(identifier))] = (202 if kind == "company" else 200, None)
    result = await native.run("delete_" + kind, {**bound, "confirm_management_write": True})
    assert result["data"]["deletion_request_acknowledged"] is True and result["data"]["deletion_verified"] is None
    assert result["data"]["pending"] is True if kind == "company" else result["data"]["pending"] is None


async def test_parent_binding_and_picker_context_refuse_foreign_children(native):
    native.replies[("GET", "employees/43")] = (200, contact(company_id=99))
    result = await native.run("update_contact", {"contact_id": 43, "company_id": 42, "firstname": "Changed", "confirm_management_write": True})
    assert result["status"] == "error" and len(native.requests) == 1
    from nodes.axonaut_node import AxonautNode
    native.requests.clear()
    with pytest.raises(ValueError):
        await AxonautNode.load_field_options("contact_id", {"api_key": KEY}, context={})
    assert native.requests == []
    native.replies[("GET", "companies/42/employees")] = (200, [contact(company_id=99)])
    with pytest.raises(ValueError):
        await AxonautNode.load_field_options("contact_id", {"api_key": KEY}, context={"company_id": "42"})


async def test_task_patch_uses_documented_string_priority_and_exact_status_field(native):
    native.replies[("PATCH", "tasks/45")] = (200, task(priority="haute", task_status_id=50))
    result = await native.run("update_task", {"company_id": 42, "task_id": 45, "priority": "haute",
        "task_status_id": "50", "confirm_management_write": True})
    assert result["status"] == "success"
    assert json.loads(native.requests[-1].content) == {"priority": "haute", "task_status_id": 50}


async def test_project_parent_binding_is_read_before_create_and_checked_in_reply(native):
    native.replies[("POST", "projects")] = (200, project(id=47, parent_project={"id": 46, "name": "Fixture project"}))
    result = await native.run("create_project", {"company_id": 42, "name": "Fixture child", "parent_project_id": 46,
        "confirm_management_write": True})
    assert result["status"] == "success" and result["data"]["resource"]["parent_project_id"] == 46
    assert [r.url.path for r in native.requests] == ["/api/v2/companies/42", "/api/v2/projects/46", "/api/v2/projects"]
    assert json.loads(native.requests[-1].content) == {"company_id": 42, "name": "Fixture child", "parent_project_id": 46}


@pytest.mark.parametrize("status", [201, 202, 204, 301, 400, 401, 403, 404, 429, 503])
async def test_unexpected_status_never_claims_success_or_echoes_body(native, status):
    native.replies[("GET", "companies")] = (status, {"message": KEY}, {"Retry-After": "7"})
    result = await native.run("list_companies")
    assert result["status"] == "error" and result["status_code"] == status and result["retry_after"] == 7
    assert KEY not in json.dumps(result) and len(native.requests) == 1


@pytest.mark.parametrize("payload", [{"data": [company()]}, [company(), company()], [company(id=True)], [company(name=KEY)]])
async def test_malformed_private_or_duplicate_page_cannot_verify(native, payload):
    from nodes.core.credential_connect import validate_for_connect
    native.replies[("GET", "companies")] = (200, payload)
    verdict = await validate_for_connect(credential_type=FAMILY, credential_data={"api_key": KEY}, user_id=USER)
    assert verdict.evidence.reachable is None and verdict.verified_metadata() == {}


async def test_empty_company_list_uses_actual_me_identity_without_key(native):
    from nodes.core.credential_connect import validate_for_connect
    native.replies[("GET", "companies")] = (200, [])
    verdict = await validate_for_connect(credential_type=FAMILY, credential_data={"api_key": KEY}, user_id=USER)
    assert verdict.evidence.reachable is True and verdict.evidence.account_label == "Fixture operator"
    assert verdict.verified_metadata()["verified_as"] == "Fixture operator" and KEY not in json.dumps(verdict.verified_metadata())
