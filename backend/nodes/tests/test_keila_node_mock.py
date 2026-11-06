"""Prepared UNRUN Keila native factory/dispatcher/current-authority fixtures.

Synthetic HTTP rows exercise real provider parsing and native entry points;
no provider credentials, accounts or live requests are used by this source.
"""
import json
import logging
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from nodes import keila_node as fn
from nodes.core.registry import NodeFactory
from nodes.core.run_op import run_node_operation, run_node_lookup

C, T, OTHER = "campaign-a", "template-a", "other-resource"
CREDS = {"credential_type": "keila_api_key", "api_key": "synthetic+/=private-key", "instance_origin": "https://app.keila.io"}
STAMP = datetime(2026, 10, 7, tzinfo=timezone.utc)
CAMPAIGN = {"id": C, "inserted_at": "raw resource time", "settings": {"type": "markdown", "do_not_track": True}, "subject": "omit subject", "preview_text": "omit preview", "html_body": "omit body", "text_body": "omit body", "data": {"secret": "omit"}, "sender_id": "omit sender", "segment_id": "omit segment"}
TEMPLATE = {"id": T, "type": "hybrid", "name": "Template display", "inserted_at": "raw resource time", "html_body": "omit body", "styles": "omit style", "assigns": {"secret": "omit"}, "text_content_slots": [{"default_content": "omit content"}]}
OPS = ["test_connection", "list_campaigns", "get_campaign", "list_templates", "get_template"]

def catalog(*rows, meta=None):
    result = {"data": list(rows), "links": {"next": "https://do-not-follow.invalid/api/v1/private"}}
    if meta is not None: result["meta"] = meta
    return result

@pytest.fixture(autouse=True)
def ensure_native_db_pool(): yield

class Response:
    def __init__(self, body=None, *, status=200, raw=None, mime="application/json;charset=utf-8", after=None):
        self.body, self.raw, self.status_code, self.after = body, raw, status, after
        self.headers = {"Content-Type": mime}
    async def __aenter__(self): return self
    async def __aexit__(self, *args):
        if self.after: self.after()
    async def aiter_bytes(self, chunk_size):
        assert chunk_size == 65536
        yield self.raw if self.raw is not None else json.dumps(self.body).encode("utf-8")

@pytest.fixture
def wire(monkeypatch):
    calls, responses = [], []
    class Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        def stream(self, method, url, **kwargs):
            calls.append({"method": method, "url": url, **kwargs})
            logging.getLogger("httpx").info("private %s %s", url, kwargs)
            response = responses.pop(0)
            return response if isinstance(response, Response) else Response(response)
    def client(**kwargs):
        assert kwargs == {"timeout": 20.0, "follow_redirects": False, "trust_env": False}
        return Client()
    monkeypatch.setattr(fn, "guarded_async_client", client)
    return SimpleNamespace(calls=calls, responses=responses)

async def run(op, args=None, *, credential_data=None, **context):
    return await run_node_operation(node_type=fn.NODE_TYPE, operation=op, arguments=args or {}, credential_data=credential_data or CREDS, user_id="actor", **context)

def test_actual_factory_schema_editor_numeric_strings_and_original_family():
    node = NodeFactory.create_node(node_id="native", node_type=fn.NODE_TYPE, user_id="actor", node_data={"config": {"operation": "get_campaign", "campaign_id": C}, "credentials": CREDS})
    assert node.config.config.campaign_id == C and node.config.credentials.api_key == CREDS["api_key"]
    defs = fn.KeilaNode.get_config_schema()["$defs"]
    assert sorted(d["properties"]["operation"]["const"] for d in defs.values() if "operation" in d.get("properties", {})) == sorted(OPS)
    assert defs["KeilaCampaignConfig"]["properties"]["campaign_id"]["x-resource-type"] == "keila_campaign"
    assert defs["KeilaTemplateConfig"]["properties"]["template_id"]["x-resource-type"] == "keila_template"
    assert "depends_on" not in defs["KeilaTemplateConfig"]["properties"]["template_id"]["x-dynamic-options"]
    assert fn.KeilaNode.get_config_model() is fn.KeilaNodeConfig
    assert fn.KeilaNode.parse_config({"config": {"operation": "list_templates", "output_limit": "20"}, "credentials": CREDS}).config.output_limit == 20
    for family in (None, "http_bearer", "keila_oauth"):
        data = {"credential_id": "saved", "config": {"operation": "test_connection"}, "credentials": {**CREDS, "credential_type": family}}
        assert fn.KeilaNode.validate_config(data)["valid"] is False
        with pytest.raises(ValueError, match="family"): fn.KeilaNode.parse_config(data)

@pytest.mark.parametrize("host", ["http://app.keila.io", "https://127.0.0.1", "https://localhost", "https://private.internal", "https://www.keila.io", "https://app.keila.io/api/v1", "https://key@app.keila.io", "https://app.keila.io:444", "https://app.keila.io?key=secret", "https://app.keila.io#fragment"])
def test_only_public_https_instance_root(host):
    with pytest.raises(ValueError): fn.KeilaNode.parse_config({"config": {"operation": "test_connection"}, "credentials": {**CREDS, "instance_origin": host}})

@pytest.mark.parametrize("cfg", [{"operation": "get_campaign", "campaign_id": "../other"}, {"operation": "get_template", "template_id": "https://other.invalid"}, {"operation": "list_campaigns", "output_limit": True}, {"operation": "list_campaigns", "output_limit": "1.2"}, {"operation": "list_campaigns", "output_limit": 101}, {"operation": "list_campaigns", "include_names": True}, {"operation": "list_templates", "page": 1}, {"operation": "list_campaigns", "per_page": 20}, {"operation": "test_connection", "project_id": "fake"}, {"operation": "get_template", "campaign_id": C, "template_id": T}, {"operation": "send_campaign"}, {"operation": "create_template"}])
def test_closed_native_config_no_guessed_pagination_parent_or_controls(cfg):
    with pytest.raises(ValueError): fn.KeilaNode.parse_config({"config": cfg, "credentials": CREDS})

@pytest.mark.asyncio
async def test_actual_connect_one_bearer_catalog_no_identity_or_content(wire, caplog):
    wire.responses.append(catalog(CAMPAIGN))
    with caplog.at_level(logging.DEBUG): result = await run("test_connection")
    assert len(wire.calls) == 1 and wire.calls[0]["url"] == CREDS["instance_origin"] + "/api/v1/campaigns"
    assert wire.calls[0]["method"] == "GET" and "params" not in wire.calls[0]
    assert wire.calls[0]["headers"] == {"Authorization": "Bearer " + CREDS["api_key"], "Content-Type": "application/json", "Accept": "application/json"}
    proof = result["data"]
    assert proof["protected_read_completed"] is True and proof["proves"] == "reachability"
    assert all(proof[k] is False for k in ("account_identity_verified", "user_identity_verified", "project_identity_verified", "ownership_verified", "all_permissions_verified", "entitlement_verified"))
    assert proof["results"] == [{"id": C, "inserted_at": "raw resource time", "format": "markdown"}]
    private_values = ("omit subject", "omit preview", "omit body", "omit sender", "omit segment", '"omit"')
    assert all(value not in json.dumps(result) for value in private_values)
    assert CREDS["api_key"] not in caplog.text and fn._PRIVATE_REQUEST.get() is False
    logging.getLogger("httpx").warning("unrelated context"); assert "unrelated context" in caplog.text

@pytest.mark.asyncio
async def test_empty_and_optional_scalar_omission_no_null_or_fake_times(wire):
    wire.responses.extend([catalog(), catalog({"id": T}), catalog({"id": C})])
    assert (await run("test_connection"))["data"]["results"] == []
    assert (await run("list_templates"))["data"]["templates"] == [{"id": T}]
    result = await run("list_campaigns")
    assert result["data"]["campaigns"] == [{"id": C}] and "optional_template_reference_verified" not in result["data"]
    assert result["data"]["pagination"]["entire_catalog_completion_verified"] is False
    assert "more_pages_by_metadata" not in result["data"]["pagination"]

@pytest.mark.asyncio
async def test_exact_independent_catalog_detail_and_optional_template_reference(wire):
    linked = {**CAMPAIGN, "template_id": T}
    wire.responses.extend([catalog(linked), {"data": linked}, catalog(TEMPLATE)])
    result = await run("get_campaign", {"campaign_id": C})
    assert result["data"]["selected_resource_in_current_catalog"] is True and result["data"]["optional_template_reference_verified"] is True
    assert "template_id" not in result["data"]["campaign"]
    wire.responses.extend([catalog(TEMPLATE), {"data": TEMPLATE}])
    template = await run("get_template", {"template_id": T, "include_names": True})
    assert template["data"]["template"]["name"] == TEMPLATE["name"]
    assert [c["url"].split("/api/v1")[1] for c in wire.calls] == ["/campaigns", "/campaigns/"+C, "/templates", "/templates", "/templates/"+T]
    wire.responses.extend([catalog(linked), {"data": linked}, catalog()])
    with pytest.raises(fn.KeilaAPIError, match="reference"): await run("get_campaign", {"campaign_id": C})
    wire.responses.append(catalog(TEMPLATE))
    with pytest.raises(fn.KeilaAPIError, match="outside"): await run("get_template", {"template_id": OTHER})
    wire.responses.extend([catalog(TEMPLATE), {"data": {**TEMPLATE, "id": OTHER}}])
    with pytest.raises(fn.KeilaAPIError): await run("get_template", {"template_id": T})

@pytest.mark.asyncio
async def test_zero_index_page_witness_local_cap_no_query_or_short_page_inference(wire):
    wire.responses.append(catalog(TEMPLATE, {**TEMPLATE, "id": OTHER}, meta={"page": 0, "page_count": 3, "page_size": 50, "total_entries": 900, "next_url": "https://omit.invalid"}))
    result = await run("list_templates", {"output_limit": "1"})
    page = result["data"]["pagination"]
    assert page["page"] == 0 and page["page_count"] == 3 and page["more_pages_by_metadata"] is True and page["locally_truncated"] is True
    assert "total_entries" not in page and "next_page_token" not in page and "params" not in wire.calls[0]
    assert page["entire_catalog_completion_verified"] is False
    wire.responses.append(catalog(meta={"page": 0, "page_count": 0, "page_size": 0}))
    page = (await run("list_campaigns"))["data"]["pagination"]
    assert "more_pages_by_metadata" not in page and "observed_page_last_by_metadata" not in page

@pytest.mark.asyncio
async def test_actual_independent_id_pickers_unknown_completion_and_cap_error(wire):
    wire.responses.extend([catalog(CAMPAIGN), catalog(TEMPLATE)])
    first = await fn.KeilaNode.load_field_options("campaign_id", CREDS, context={"_user_id": "actor"}, search="campaign")
    second = await fn.KeilaNode.load_field_options("template_id", CREDS, context={"_user_id": "actor", "campaign_id": OTHER})
    assert first["options"] == [{"value": C, "label": C}] and second["options"] == [{"value": T, "label": T}]
    assert all("params" not in c for c in wire.calls)
    wire.responses.append(catalog(TEMPLATE, meta={"page": 0, "page_count": 2}))
    with pytest.raises(fn.KeilaAPIError, match="bounded"): await fn.KeilaNode.load_field_options("template_id", CREDS)
    before = len(wire.calls)
    with pytest.raises(ValueError): await fn.KeilaNode.load_field_options("campaign_id", CREDS, page_token="invented")
    with pytest.raises(ValueError): await fn.KeilaNode.load_field_options("template_id", CREDS, search="private template name")
    assert len(wire.calls) == before

@pytest.mark.asyncio
@pytest.mark.parametrize("body", [[], {}, {"data": None}, {"data": {}}, catalog({}), catalog({"id": 1}), catalog({"id": C}, {"id": C}), catalog({"id": C, "inserted_at": None}), catalog({"id": C, "settings": {"type": None}}), catalog({"id": C, "settings": {"type": "unknown"}}), catalog({"id": C, "template_id": None}), catalog(meta={"page": True}), catalog(meta={"page": 2, "page_count": 2}), {"data": [], "meta": None}, {**catalog(CAMPAIGN), "status": "rejected"}])
async def test_exact_wrapper_ids_optional_field_nullability_and_markers(wire, body):
    wire.responses.append(body)
    with pytest.raises(fn.KeilaAPIError): await run("list_campaigns")
    assert len(wire.calls) == 1

@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["403", "429", "redirect", "wrong_mime", "invalid_utf8", "duplicate", "nan", "overflow", "deep", "size"])
async def test_read_bounds_and_error_privacy_no_replay(wire, monkeypatch, case):
    bodies = {"403": Response(status=403, raw=b"private", mime="text/html"), "429": Response(status=429), "redirect": Response(status=302), "wrong_mime": Response(catalog(), mime="text/plain"), "invalid_utf8": Response(raw=b"\xff"), "duplicate": Response(raw=b'{"data":[],"data":[]}'), "nan": Response(raw=b'{"data":[],"private":NaN}'), "overflow": Response(raw=b'{"data":[],"private":1e309}'), "deep": Response(raw=('{"data":[],"private":'+('['*40)+'0'+(']'*40)+'}').encode()), "size": Response(raw=b"x"*20)}
    if case == "size": monkeypatch.setattr(fn, "MAX_BYTES", 10)
    wire.responses.append(bodies[case])
    with pytest.raises(fn.KeilaAPIError) as error: await run("list_templates")
    assert CREDS["api_key"] not in str(error.value) and len(wire.calls) == 1

@pytest.mark.asyncio
async def test_signed_echo_redaction_and_opaque_status_projection(wire):
    wire.responses.append({**catalog({**TEMPLATE, "name": "synthetic%2b%2F%3dprivate-key"}), "status": {"opaque": True}})
    result = await run("list_templates", {"include_names": True})
    assert result["data"]["templates"][0]["name"] == "[redacted]" and "status" not in result["data"]["templates"][0]

@pytest.mark.asyncio
async def test_current_canonical_row_stored_picker_actor_binding(monkeypatch, wire):
    from nodes.core import run_op
    from repositories.credential_approvals import CredentialApprovalRepo
    from utils import credential_loader, credentials
    pool = object()
    raw = {**CREDS, "token_version": 2, "updated_at": STAMP.isoformat()}
    resolve = AsyncMock(return_value=CREDS)
    monkeypatch.setattr(credentials, "resolve_credential_with_owner_fallback", resolve)
    monkeypatch.setattr(credential_loader, "load_credential", AsyncMock(return_value=raw))
    monkeypatch.setattr(CredentialApprovalRepo, "policy", AsyncMock(return_value={"credential_type": fn.FAMILIES[0], "owner_id": "owner", "approval_revision": 1}))
    fresh = await fn._current_data(CREDS, pool=pool, user_id="actor", credential_id="saved", organization_id="org", workflow_id="wf")
    assert fresh["owner_id"] == "owner" and fresh["token_version"] == 2 and fresh["approval_revision"] == 1
    context = fn._context(fresh, {"_user_id": "actor", "_approval_pool": "forged", "_credential_id": "forged"})
    assert context["_approval_pool"] is pool and context["_credential_id"] == "saved"
    with pytest.raises(ValueError, match="actor"): fn._context(fresh, {"_user_id": "other"})
    monkeypatch.setattr(run_op, "resolve_operation_credential", AsyncMock(return_value=CREDS))
    monkeypatch.setattr(CredentialApprovalRepo, "admit", AsyncMock(return_value=None))
    wire.responses.append(catalog(CAMPAIGN))
    result = await fn.KeilaNode.load_field_options("campaign_id", fresh, context={"_user_id": "actor"})
    assert result["options"] == [{"value": C, "label": C}] and len(wire.calls) == 1
    assert all(call.args == ("saved", "actor", pool) for call in resolve.call_args_list)

@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["missing", "revoked", "foreign", "changed"])
async def test_current_denial_before_client(monkeypatch, wire, state):
    from repositories.credential_approvals import CredentialApprovalRepo
    from utils import credential_loader, credentials
    monkeypatch.setattr(credentials, "resolve_credential_with_owner_fallback", AsyncMock(return_value=None if state == "missing" else CREDS))
    monkeypatch.setattr(CredentialApprovalRepo, "policy", AsyncMock(return_value={"credential_type": "http_bearer" if state == "foreign" else fn.FAMILIES[0], "owner_id": "owner", "approval_revision": 1}))
    current = None if state == "revoked" else {**CREDS, "api_key": "changed" if state == "changed" else CREDS["api_key"]}
    monkeypatch.setattr(credential_loader, "load_credential", AsyncMock(return_value=current))
    with pytest.raises(ValueError):
        await fn._current_data(CREDS, pool=object(), user_id="actor", credential_id="saved", organization_id="org")
    assert wire.calls == []

@pytest.mark.asyncio
async def test_raw_binding_changes_before_after_refusal_and_after_parser(monkeypatch, wire):
    from repositories.credential_approvals import CredentialApprovalRepo
    monkeypatch.setattr(CredentialApprovalRepo, "admit", AsyncMock(return_value=None))
    raw = {**CREDS, "owner_id": "owner", "token_version": 3, "approval_revision": 4, "updated_at": STAMP.isoformat()}; state = {"data": fn._shape(raw)}
    async def current(data, **context): return state["data"]
    monkeypatch.setattr(fn, "_current_data", current)
    wire.responses.append(catalog(CAMPAIGN)); await run("test_connection", credential_data=raw, credential_id="saved", pool=object())
    state["data"] = {**fn._shape(raw), "api_key": "changed-synthetic-key"}
    with pytest.raises(fn.KeilaAPIError, match="binding changed"): await run("test_connection", credential_data=raw, credential_id="saved", pool=object())
    state["data"] = fn._shape(raw); wire.responses.append(Response(status=403, after=lambda: state.update(data={**fn._shape(raw), "approval_revision": 9})))
    with pytest.raises(fn.KeilaAPIError, match="changed"): await run("test_connection", credential_data=raw, credential_id="saved", pool=object())
    state["data"] = fn._shape(raw); original = fn._metadata
    def metadata(*args, **kwargs):
        result = original(*args, **kwargs); state["data"] = {**fn._shape(raw), "token_version": 10}; return result
    monkeypatch.setattr(fn, "_metadata", metadata); wire.responses.append(catalog(CAMPAIGN))
    with pytest.raises(fn.KeilaAPIError, match="changed"): await run("test_connection", credential_data=raw, credential_id="saved", pool=object())
    assert len(wire.calls) == 3

@pytest.mark.asyncio
@pytest.mark.parametrize("change", [{"api_key": "changed-key"}, {"instance_origin": "https://other.keila.com"}, {"owner_id": "other-owner"}, {"token_version": 9}, {"approval_revision": 9}])
async def test_saved_execute_rejects_original_scope_and_policy_changes_before_client(monkeypatch, wire, change):
    raw = {**CREDS, "owner_id": "owner", "token_version": 3, "approval_revision": 4, "updated_at": STAMP.isoformat()}
    monkeypatch.setattr(fn, "_current_data", AsyncMock(return_value=fn._shape({**raw, **change})))
    node = NodeFactory.create_node(node_id="native", node_type=fn.NODE_TYPE, user_id="actor", node_data={"config": {"operation": "test_connection"}, "credentials": raw, "credential_id": "saved", "_approval_pool": object()})
    with pytest.raises(fn.KeilaAPIError, match="binding changed"): await node.execute({})
    assert wire.calls == []




@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["pending", "rejected"])
async def test_saved_picker_admission_before_header_wire(monkeypatch, wire, status):
    from repositories.credential_approvals import CredentialApprovalRepo
    authority = fn._LookupAuthority(object(), "actor", "saved", "org", "wf")
    raw = {**CREDS, "_keila_authority": authority}
    monkeypatch.setattr(fn, "_current_data", AsyncMock(return_value=raw))
    monkeypatch.setattr(CredentialApprovalRepo, "admit", AsyncMock(return_value={"status": status, "id": "approval", "new_request": False}))
    with pytest.raises(fn.KeilaAPIError, match="approval"):
        await fn.KeilaNode.load_field_options("campaign_id", raw, context={"_user_id": "actor"})
    assert wire.calls == []

@pytest.mark.asyncio
async def test_staging_saved_lookup_preserves_trusted_workflow(monkeypatch, wire):
    from nodes.core import run_op
    from repositories.credential_approvals import CredentialApprovalRepo
    pool = object()
    monkeypatch.setattr(run_op, "resolve_operation_credential", AsyncMock(return_value=CREDS))
    current = AsyncMock(return_value=CREDS)
    monkeypatch.setattr(fn, "_current_data", current)
    monkeypatch.setattr(CredentialApprovalRepo, "admit", AsyncMock(return_value=None))
    wire.responses.append(catalog(CAMPAIGN))
    result = await run_node_lookup(node_type=fn.NODE_TYPE, field_name="campaign_id", credential_id="saved", user_id="actor", pool=pool, workflow_id="wf", context={"_workflow_id": "forged"})
    assert result["options"] == [{"value": C, "label": C}]
    assert all(call.kwargs["workflow_id"] == "wf" and call.kwargs["credential_id"] == "saved" and call.kwargs["pool"] is pool for call in current.call_args_list)


@pytest.mark.asyncio
async def test_refresh_hook_binds_saved_authority_until_trusted_lookup():
    pool = object()
    fresh = await fn.KeilaNode.freshen_credential(
        CREDS, pool=pool, user_id="actor", credential_id="saved",
    )
    assert fresh["_keila_authority"] == fn._LookupAuthority(pool, "actor", "saved", None, None)
    assert await fn.KeilaNode.freshen_credential(CREDS) == fn._shape(CREDS)
