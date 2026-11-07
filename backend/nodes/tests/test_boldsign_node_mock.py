"""Native BoldSign contract, machine-token and privacy regressions.

Real factory/schema/run code uses synthetic HTTP without provider access.
No issued key, contact, document or provider data is accessed.
"""
from datetime import datetime, timezone, timedelta
import hashlib
import hmac
import json
import base64
from pathlib import Path
from urllib.parse import parse_qs
import httpx
import pytest
from pydantic import ValidationError
from nodes import boldsign_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-BoldSign-private-key-fragment"
DOC, TEMPLATE, CONTACT, GROUP = "doc-owned-42", "template-owned-42", "contact-owned-42", "group-owned-42"
BASE = native.BASE


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    """Pure contract fixtures do not initialize a DB pool."""
    native._TOKEN_CACHE.clear()
    yield
    native._TOKEN_CACHE.clear()


def credential(**values):
    return {"credential_type": native.FAMILY, "api_key": TOKEN, "environment": "sandbox",
        "allowed_document_ids": [DOC], "allowed_template_ids": [TEMPLATE],
        "allowed_contact_ids": [CONTACT], "allowed_contact_group_ids": [GROUP], **values}


def document(**values):
    return {"documentId": DOC, "messageTitle": "Owned fixture", "status": "Draft", "createdDate": 1,
        "labels": ["owned"], "signerDetails": [{"emailAddress": "private@example.test", "formFields": [{"value": TOKEN}]}],
        "files": [{"url": "https://private.example.test/document"}], "documentHistory": [{"id": "history-42", "action": "Viewed", "timestamp": 2,
        "email": "private@example.test", "ipAddress": "192.0.2.42", "changes": TOKEN}], **values}


def template(*, detail=False, **values):
    return {("templateId" if detail else "documentId"): TEMPLATE, ("title" if detail else "templateName"): "Owned template",
        "templateLabels": ["owned"], "createdDate": 1, "roles": [{"email": "private@example.test"}], **values}


def contact(*, detail=False, **values):
    return {("contactId" if detail else "id"): CONTACT, "name": "Owned contact", "email": "owned@example.test", "phoneNumber": "private-phone", **values}


def group(**values):
    return {"groupId": GROUP, "groupName": "Owned group", "directories": ["Owned"], "contacts": [contact()], "createdBy": TOKEN, **values}


def page(rows, *, current=1, size=20, total=None):
    total = len(rows) if total is None else total
    return {"pageDetails": {"page": current, "pageSize": size, "totalRecordsCount": total, "totalPages": (total + size - 1) // size}, "result": rows}


def reply(request):
    size, current = int(request.url.params.get("pageSize", request.url.params.get("PageSize", 20))), int(request.url.params.get("page", request.url.params.get("Page", 1)))
    paths = {"/v1/document/list": page([document()], size=size, current=current),
        "/v1/document/properties": document(), "/v1/template/list": page([template()], size=size, current=current),
        "/v1/template/properties": template(detail=True), "/v1/contacts/list": page([contact()], size=size, current=current),
        "/v1/contacts/get": contact(detail=True), "/v1/contactGroups/list": page([group()], size=size, current=current), "/v1/contactGroups/get": group()}
    assert request.url.path in paths
    return httpx.Response(200, json=paths[request.url.path])


@pytest.fixture
def transport(monkeypatch):
    requests, holder = [], {"reply": reply}
    async def provider(request):
        requests.append(request)
        return holder["reply"](request)
    def client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(provider), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests, holder


def node(operation="check_connection", *, credentials=None, **config):
    return NodeFactory.create_node(node_id="owned-fixture", node_type=native.NODE_TYPE,
        node_data={"credentials": credential() if credentials is None else credentials, "config": {"operation": operation, **config}})


@pytest.mark.asyncio
async def test_real_factory_direct_execute_protected_reachability_and_header_only(transport):
    requests, holder = transport
    holder["reply"] = lambda request: httpx.Response(200, json={**page([], size=1), "result": None})
    result = await node().execute({})
    assert result == {"operation": "check_connection", "status": "success", "reachable": True, "proves": "reachability"}
    assert requests[0].url.host == "api.boldsign.com" and requests[0].headers["X-API-KEY"] == TOKEN
    assert "Authorization" not in requests[0].headers and TOKEN not in str(requests[0].url)
    assert native.BoldSignNode.connection_evidence.proves == "reachability"


@pytest.mark.asyncio
async def test_expiry_and_out_of_scope_refuse_before_http(transport):
    requests, _ = transport
    expired = credential(expires_at=(datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat())
    assert (await node(credentials=expired).run({}))["status"] == "error"
    assert (await node("get_document", document_id="outside").run({}))["status"] == "error"
    assert requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,values,forbidden", [
    ("get_document", {"document_id": DOC}, ["signerDetails", "formFields", "files", "private@example.test", TOKEN]),
    ("get_document_status", {"document_id": DOC}, ["name", "labels", "signerDetails", TOKEN]),
    ("get_document_history", {"document_id": DOC}, ["email", "ipAddress", "changes", TOKEN]),
    ("get_template", {"template_id": TEMPLATE}, ["roles", "private@example.test"]),
    ("get_contact", {"contact_id": CONTACT}, ["phoneNumber", "private-phone"]),
    ("get_contact_group", {"group_id": GROUP}, ["contacts", "createdBy", TOKEN]),
])
async def test_selected_metadata_privacy_and_exact_resource_ids(transport, operation, values, forbidden):
    requests, _ = transport
    result = await node(operation, **values).run({})
    assert result["status"] == "success"
    for value in forbidden: assert value not in json.dumps(result)
    if operation in {"get_contact", "get_contact_group"}:
        assert requests[0].url.params["ContactType" if operation == "get_contact_group" else "contactType"] == "MyContacts"
        assert requests[-1].url.params["groupId" if operation == "get_contact_group" else "id"] == (GROUP if operation == "get_contact_group" else CONTACT)


@pytest.mark.asyncio
async def test_scoped_list_template_case_and_mycontacts_membership(transport):
    requests, holder = transport
    assert (await node("list_templates").run({}))["items"][0]["id"] == TEMPLATE
    assert requests[-1].url.params["templateType"] == "mytemplates"
    holder["reply"] = lambda request: httpx.Response(200, json=page([contact(id="not-owned")], size=int(request.url.params["pageSize"])))
    assert (await node("list_contacts").run({}))["items"] == []
    before = len(requests)
    assert (await node("delete_contact", contact_id=CONTACT).run({}))["status"] == "error"
    assert len(requests) == before + 1 and requests[-1].method == "GET"


@pytest.mark.asyncio
@pytest.mark.parametrize("status,key", [(200, "contacts"), (201, "createdContacts")])
async def test_array_create_status_specific_completed_contract(transport, status, key):
    requests, holder = transport
    holder["reply"] = lambda request: httpx.Response(status, json={key: [{"id": CONTACT, "email": "owned@example.test"}]})
    result = await node("create_contact", credentials=credential(allow_contact_create=True), email="owned@example.test", name="Owned fixture").run({})
    assert result["status"] == "success" and result["resource_id"] == CONTACT
    assert result["readback_required"] and result["saved_scope_required"] and "readback_verified" not in result
    assert json.loads(requests[0].content) == [{"Email": "owned@example.test", "Name": "Owned fixture"}]
    assert requests[0].method == "POST" and requests[0].url.path == "/v1/contacts/create"


@pytest.mark.asyncio
async def test_create_shape_conflict_and_returned_id_survive_uncertain_email(transport):
    requests, holder = transport
    instance = node("create_contact", credentials=credential(allow_contact_create=True), email="owned@example.test", name="Owned fixture")
    holder["reply"] = lambda request: httpx.Response(200, json={"createdContacts": [{"id": CONTACT, "email": "owned@example.test"}]})
    assert (await instance.run({}))["outcome_uncertain"] is True
    holder["reply"] = lambda request: httpx.Response(200, json={"contacts": [{"id": CONTACT, "email": "different@example.test"}]})
    result = await instance.run({})
    assert result["status"] == "error" and result["resource_id"] == CONTACT and result["outcome_uncertain"]
    before = len(requests)
    assert (await node("create_contact", email="owned@example.test", name="Owned").run({}))["status"] == "error"
    assert len(requests) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,method,status", [("update_contact", "PUT", 200), ("delete_contact", "DELETE", 204)])
async def test_owned_contact_empty_write_contract_separate_readback(transport, operation, method, status):
    requests, holder = transport
    holder["reply"] = lambda request: httpx.Response(status) if request.method == method else reply(request)
    values = {"email": "owned@example.test", "name": "Changed owned"} if operation == "update_contact" else {}
    result = await node(operation, contact_id=CONTACT, **values).run({})
    assert result["status"] == "success" and result["resource_id"] == CONTACT and "readback_verified" not in result
    assert result["absence_readback_required" if method == "DELETE" else "readback_required"] is True
    assert [r.method for r in requests] == ["GET", "GET", method] and requests[-1].url.params["id"] == CONTACT


@pytest.mark.asyncio
async def test_contact_timeout_and_unexpected_body_keep_exact_cleanup_id(transport):
    requests, holder = transport
    def timeout(request):
        if request.method == "DELETE": raise httpx.ReadTimeout("synthetic uncertainty", request=request)
        return reply(request)
    holder["reply"] = timeout
    result = await node("delete_contact", contact_id=CONTACT).run({})
    assert result["status"] == "error" and result["resource_id"] == CONTACT and result["outcome_uncertain"]
    assert len(requests) == 3
    holder["reply"] = lambda request: httpx.Response(200, json={}) if request.method == "PUT" else reply(request)
    result = await node("update_contact", contact_id=CONTACT, email="owned@example.test", name="Owned").run({})
    assert result["status"] == "error" and result["resource_id"] == CONTACT and result["readback_required"]


@pytest.mark.asyncio
async def test_selected_detail_mismatch_is_not_valid_scope_or_history(transport):
    requests, holder = transport
    holder["reply"] = lambda request: httpx.Response(200, json=document(documentId="different"))
    result = await node("get_document_history", document_id=DOC).run({})
    assert result["status"] == "error" and "items" not in result and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("template_tags,adding", [(False, True), (False, False), (True, True), (True, False)])
async def test_tags_exact_scope_readback_no_derived_documents(transport, template_tags, adding):
    requests, holder = transport
    labels = ["owned"]
    def response(request):
        if request.method in {"PATCH", "DELETE"}:
            labels[:] = ["owned", "fixture"] if adding else []
            return httpx.Response(200)
        return httpx.Response(200, json=template(detail=True, templateLabels=list(labels)) if template_tags else document(labels=list(labels)))
    holder["reply"] = response
    operation = ("add_" if adding else "delete_") + ("template_tags" if template_tags else "document_tags")
    values = {"template_id": TEMPLATE} if template_tags else {"document_id": DOC}
    result = await node(operation, tags=["fixture" if adding else "owned"], **values).run({})
    assert result["status"] == "success" and result["readback_verified"]
    payload = json.loads(requests[1].content)
    assert set(payload) == ({"TemplateId", "TemplateLabels"} if template_tags else {"DocumentId", "Tags"})
    assert "DocumentLabels" not in payload and "onBehalfOf" not in payload
    assert [r.method for r in requests] == ["GET", "PATCH" if adding else "DELETE", "GET"]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [202, 301, 401, 403, 404, 429, 500])
async def test_http_refusals_preserve_status_without_redirect_or_secret_echo(transport, status):
    requests, holder = transport
    holder["reply"] = lambda request: httpx.Response(status, json={"message": TOKEN}, headers={"Location": "https://elsewhere.example.test"})
    result = await node().run({})
    assert result["status"] == "error" and result["http_status"] == status and TOKEN not in json.dumps(result)
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_document_paging_boundary_cursor_explicit_and_unknown(transport):
    requests, holder = transport
    holder["reply"] = lambda request: httpx.Response(200, json=page([document(nextCursor=987)], current=10_000, size=1, total=10_001))
    result = await node("list_documents", page=10_000, page_size=1).run({})
    assert result["cursor_required"] and result["last_document_cursor"] == 987 and result["next_page"] is None
    before = len(requests)
    assert (await node("list_documents", page=1001, page_size=10).run({}))["status"] == "error"
    assert len(requests) == before
    holder["reply"] = lambda request: httpx.Response(200, json=page([document(nextCursor=988)], size=1, total=10_001))
    result = await node("list_documents", page_size=1, next_cursor=987).run({})
    assert result["pagination_unknown"] and result["has_more"] is None and result["complete"] is False
    assert requests[-1].url.params["nextCursor"] == "987"


@pytest.mark.parametrize("change", ["missing-result", "duplicate", "count", "page", "bool-count", "total-pages"])
def test_actual_page_validation_refuses_false_empty_and_contradiction(change):
    body = page([document()], size=2)
    if change == "missing-result": body.pop("result")
    elif change == "duplicate": body = page([document(), document()], size=2)
    elif change == "count": body["pageDetails"]["totalRecordsCount"] = 2
    elif change == "page": body["pageDetails"]["page"] = 2
    elif change == "bool-count": body["pageDetails"]["totalRecordsCount"] = True
    else: body["pageDetails"]["totalPages"] = 9
    with pytest.raises(ValueError): native.BoldSignNode._page(body, native.BoldSignDocumentsConfig(page_size=2), native.BoldSignNode._document, documents=True)


def test_continuation_binds_key_scope_search_handles_max_allowlist():
    values = credential(allowed_document_ids=["d" + str(i) + "x" * 150 for i in range(200)])
    model = native.BoldSignCredential.model_validate(values)
    token = native._encode_page(2, model, "document_id", "Owned + Unicode Ω")
    assert len(token) < 2_000 and native._decode_page(token, model, "document_id", "Owned + Unicode Ω") == 2
    for changed, field, search in [(credential(api_key="different"), "document_id", "Owned + Unicode Ω"),
        (credential(), "document_id", "Owned + Unicode Ω"), (values, "template_id", "Owned + Unicode Ω"), (values, "document_id", "different")]:
        with pytest.raises(ValueError): native._decode_page(token, native.BoldSignCredential.model_validate(changed), field, search)
    payload = b"[]"
    malformed = base64.urlsafe_b64encode(payload + hmac.new(TOKEN.encode(), payload, hashlib.sha256).digest()).decode().rstrip("=")
    with pytest.raises(ValueError): native._decode_page(malformed, model, "document_id", None)


def test_actual_schema_golden_family_and_prohibited_operations():
    schema = native.BoldSignNode.get_config_schema()
    golden = json.loads((Path(__file__).parent / "fixtures/boldsign/native.json").read_text())
    refs = schema["properties"]["config"].get("oneOf") or schema["properties"]["config"]["anyOf"]
    operations = {schema["$defs"][ref["$ref"].split("/")[-1]]["properties"]["operation"]["const"] for ref in refs}
    assert operations == set(golden["operations"]) and len(operations) == 18
    assert {"send_document", "create_document", "sign_document", "remind", "invite", "revoke", "download"}.isdisjoint(operations)
    cred = schema["$defs"]["BoldSignCredential"]
    assert cred["properties"]["api_key"]["ui:widget"] == "password" and "x-oauth-provider" not in cred
    assert native.BoldSignNode.validate_config({"config": {"operation": "check_connection"}})["valid"]
    assert native.BoldSignCredential.model_validate(credential(allow_contact_create="true")).allow_contact_create is True
    for value in ("yes", "TRUE", 1):
        with pytest.raises(ValidationError): native.BoldSignCredential.model_validate(credential(allow_contact_create=value))
    with pytest.raises(ValidationError): native.BoldSignCredential.model_validate(credential(expires_at="2026-10-06T00:00:00"))
    for tag in (None, "", [], "foreign"):
        assert native.BoldSignNode.validate_config({"config": {"operation": "check_connection"}, "credentials": credential(credential_type=tag)})["valid"] is False


def oauth_credential(**values):
    raw = credential()
    raw.pop("api_key")
    return {**raw, "credential_type": native.OAUTH_FAMILY, "client_id": "synthetic-client-42",
        "client_secret": "synthetic-client-secret-42", "scopes": ["BoldSign.Documents.All", "BoldSign.Templates.Read"], **values}


def token_response(**values):
    return {"access_token": "synthetic-machine-bearer-42", "token_type": "Bearer", "expires_in": 3600,
        "scope": "BoldSign.Documents.All BoldSign.Templates.Read", **values}


def machine_reply(request):
    return httpx.Response(200, json=token_response()) if str(request.url) == native.TOKEN_ENDPOINT else reply(request)


@pytest.mark.asyncio
async def test_machine_form_bearer_cache_expiry_and_rotated_pair(transport, monkeypatch):
    requests, holder = transport
    holder["reply"] = machine_reply
    now = [1000.0]
    monkeypatch.setattr(native.time, "monotonic", lambda: now[0])
    for _ in range(2): assert (await node(credentials=oauth_credential()).run({}))["status"] == "success"
    assert len(requests) == 3
    token_request = requests[0]
    assert token_request.method == "POST" and str(token_request.url) == native.TOKEN_ENDPOINT
    assert parse_qs(token_request.content.decode()) == {"grant_type": ["client_credentials"], "client_id": ["synthetic-client-42"],
        "client_secret": ["synthetic-client-secret-42"], "scope": ["BoldSign.Documents.All BoldSign.Templates.Read"]}
    assert token_request.headers["content-type"] == "application/x-www-form-urlencoded"
    assert "authorization" not in token_request.headers and "x-api-key" not in token_request.headers
    assert all(request.headers["authorization"] == "Bearer synthetic-machine-bearer-42" and "x-api-key" not in request.headers for request in requests[1:])
    assert all(secret not in str(request.url) for request in requests for secret in native._secrets(native._credential_model(oauth_credential())))
    now[0] = 4541
    assert (await node(credentials=oauth_credential()).run({}))["status"] == "success"
    assert (await node(credentials=oauth_credential(client_secret="rotated-synthetic-secret")).run({}))["status"] == "success"
    assert len([request for request in requests if str(request.url) == native.TOKEN_ENDPOINT]) == 3
    assert all(len(key) == 64 and "synthetic" not in key for key in native._TOKEN_CACHE.keys())


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [{"access_token": ""}, {"access_token": "bad\r\ntoken"}, {"token_type": "Basic"},
    {"token_type": None}, {"expires_in": None}, {"expires_in": True}, {"expires_in": "3600"}, {"expires_in": 0},
    {"expires_in": float("inf")}, {"scope": None}, {"scope": "BoldSign.Documents.All"},
    {"scope": "BoldSign.Documents.All BoldSign.Templates.Read offline_access"}, {"access_token": "synthetic-client-secret-42"}])
async def test_machine_malformed_scope_and_expiry_stop_before_api(transport, changes):
    requests, holder = transport
    payload = token_response(**changes)
    holder["reply"] = lambda request: httpx.Response(200, content=json.dumps(payload), headers={"Content-Type": "application/json"})
    result = await node(credentials=oauth_credential()).run({})
    assert result["status"] == "error" and len(requests) == 1 and len(native._TOKEN_CACHE) == 0
    assert "synthetic" not in json.dumps(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [302, 400, 401, 403, 429, 500])
async def test_machine_token_failure_no_redirect_retry_or_body_echo(transport, status):
    requests, holder = transport
    holder["reply"] = lambda request: httpx.Response(status, json={"error": "synthetic-client-secret-42"}, headers={"Location": "https://untrusted.example.test"})
    result = await node(credentials=oauth_credential()).run({})
    assert result["status"] == "error" and result["http_status"] == status
    assert len(requests) == 1 and "synthetic" not in json.dumps(result)


def test_machine_schema_rejects_ambiguous_or_nonliteral_material_and_binds_picker():
    for changes in ({"api_key": TOKEN}, {"token_endpoint": "https://untrusted.example.test"}, {"client_id": 42},
        {"client_secret": "{{secret}}"}, {"scopes": []}, {"scopes": ["offline_access"]},
        {"scopes": ["BoldSign.Documents.All", "BoldSign.Documents.All"]}):
        with pytest.raises(ValidationError): native._credential_model(oauth_credential(**changes))
    model = native._credential_model(oauth_credential())
    token = native._encode_page(2, model, "document_id", "Owned")
    assert native._decode_page(token, model, "document_id", "Owned") == 2
    for changes in ({"client_id": "another-client"}, {"client_secret": "rotated-secret"}, {"environment": "live"},
        {"scopes": ["BoldSign.Documents.All"]}, {"allowed_document_ids": []}):
        with pytest.raises(ValueError): native._decode_page(token, native._credential_model(oauth_credential(**changes)), "document_id", "Owned")
    schema = native.BoldSignNode.get_config_schema()["$defs"]["BoldSignClientCredentials"]
    assert schema["properties"]["client_secret"]["ui:widget"] == "password" and "x-oauth-provider" not in schema


@pytest.mark.asyncio
async def test_machine_scope_and_existing_resource_limits_precede_token(transport):
    requests, _ = transport
    assert (await node(credentials=oauth_credential(scopes=["BoldSign.Templates.Read"])).run({}))["status"] == "error"
    assert (await node("get_document", document_id="outside", credentials=oauth_credential()).run({}))["status"] == "error"
    assert (await node("add_template_tags", template_id=TEMPLATE, tags=["fixture"], credentials=oauth_credential()).run({}))["status"] == "error"
    assert requests == []


@pytest.mark.asyncio
async def test_machine_token_success_is_not_protected_connection_evidence(transport):
    requests, holder = transport
    holder["reply"] = lambda request: machine_reply(request) if str(request.url) == native.TOKEN_ENDPOINT else httpx.Response(403, json={"error": "denied"})
    result = await node(credentials=oauth_credential()).run({})
    assert result["status"] == "error" and result["http_status"] == 403 and "reachable" not in result
    assert len(requests) == 2


@pytest.mark.asyncio
async def test_machine_reflected_bearer_withheld_and_api_failure_never_retried(transport):
    requests, holder = transport
    holder["reply"] = lambda request: machine_reply(request) if str(request.url) == native.TOKEN_ENDPOINT else httpx.Response(200, json=page([document(messageTitle="synthetic-machine-bearer-42")], size=1))
    result = await node(credentials=oauth_credential()).run({})
    assert result["status"] == "error" and "synthetic" not in json.dumps(result)
    holder["reply"] = lambda request: httpx.Response(401, json={"error": "synthetic-machine-bearer-42"})
    result = await node("delete_document_tags", document_id=DOC, tags=["owned"], credentials=oauth_credential()).run({})
    assert result["status"] == "error" and len(requests) == 3
    assert all(request.method != "DELETE" for request in requests)


@pytest.mark.asyncio
async def test_machine_template_all_grants_read_without_requesting_extra_scopes(transport):
    requests, holder = transport
    def reply(request):
        if str(request.url) == native.TOKEN_ENDPOINT:
            return httpx.Response(200, json=token_response(scope="BoldSign.Templates.All"))
        return httpx.Response(200, json=page([], size=20))
    holder["reply"] = reply
    result = await node("list_templates", credentials=oauth_credential(scopes=["BoldSign.Templates.All"])).run({})
    assert result["status"] == "success" and result["items"] == []
    assert len(requests) == 2 and str(requests[1].url).startswith(native.BASE + "/v1/template/list")
    assert parse_qs(requests[0].content.decode())["scope"] == ["BoldSign.Templates.All"]


@pytest.mark.asyncio
async def test_manual_text_inputs_keep_explicit_machine_scope_and_resource_policy(transport):
    requests, holder = transport
    holder["reply"] = lambda request: httpx.Response(200, json=token_response(scope="BoldSign.Documents.All")) if str(request.url) == native.TOKEN_ENDPOINT else reply(request)
    values = oauth_credential(scopes="BoldSign.Documents.All", allowed_document_ids=json.dumps([DOC]), allow_contact_create="false")
    result = await node(credentials=values).run({})
    assert result["status"] == "success" and len(requests) == 2
    assert parse_qs(requests[0].content.decode())["scope"] == ["BoldSign.Documents.All"]
    parsed = native._credential_model(values)
    assert parsed.allowed_document_ids == [DOC] and parsed.allow_contact_create is False
    for changes in ({"scopes": ""}, {"scopes": " BoldSign.Documents.All"}, {"scopes": "BoldSign.Documents.All  BoldSign.Templates.Read"},
                    {"allowed_document_ids": '["outside", "outside"]'}, {"allow_contact_create": "yes"}, {"allowed_document_ids": '{"id":"outside"}'}):
        with pytest.raises(ValueError): native._credential_model({**values, **changes})


@pytest.mark.asyncio
async def test_boldsign_contact_group_query_matches_documented_case(transport):
    requests, _ = transport
    result = await node("list_contact_groups", search_key="Owned").run({})
    assert result["status"] == "success"
    assert dict(requests[-1].url.params) == {"Page": "1", "PageSize": "20", "SearchKey": "Owned", "ContactType": "MyContacts"}
    result = await node("get_contact_group", group_id=GROUP).run({})
    assert result["status"] == "success"
    assert dict(requests[-2].url.params) == {"Page": "1", "PageSize": "100", "ContactType": "MyContacts"}
