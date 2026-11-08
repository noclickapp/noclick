"""Wire, pagination and error regressions; no live provider account is used."""
import hashlib
import json
from pathlib import Path

import httpx
import pytest
import yaml
from pydantic import ValidationError

from nodes import dock_certs_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-dock-certs-token"
UUID = "37275574-7ea4-438d-b8ef-f8fc61dbf09e"
DID = "did:cheqd:testnet:ac2b9027-ec1a-4ee2-aad1-1e316e7d6f59"
URI = "https://creds.truvera.io/521bb7"
AUTH = {"credential_type": "dock_certs_api_key", "api_key": TOKEN}
FIXTURE = Path(__file__).parent / "fixtures/dock-certs/openapi.yaml"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, **credential):
    return NodeFactory.create_node(node_id="dock-certs-test", node_type="automation-dock-certs",
        node_data={"config": config, "credentials": {**AUTH, **credential}})


def transport(monkeypatch, payload, status=200):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=payload)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


# Independent expected method/route/arguments, with provider parameter names.
CASES = [
    ("list_profiles", {}, "GET", "/profiles", None),
    ("get_profile", {"did": DID}, "GET", "/profiles/" + DID, None),
    ("list_dids", {}, "GET", "/dids", None),
    ("get_did", {"did": DID}, "GET", "/dids/" + DID, None),
    ("create_did", {}, "POST", "/dids", {"type": "cheqd", "keyType": "ed25519", "includeDidcommService": True}),
    ("list_templates", {}, "GET", "/templates", None),
    ("get_template", {"template_id": UUID}, "GET", "/templates/" + UUID, None),
    ("create_template", {"name": "Degree", "html": "<h1>Degree</h1>", "css": "h1 {color: black}"}, "POST", "/templates", {"name": "Degree", "html": "<h1>Degree</h1>", "css": "h1 {color: black}"}),
    ("delete_template", {"template_id": UUID}, "DELETE", "/templates/" + UUID, None),
    ("list_credentials", {}, "GET", "/credentials", None),
    ("get_credential", {"credential_id": URI}, "GET", "/credentials/" + URI, None),
    ("issue_credential", {"credential": {"issuer": DID, "subject": {"name": "A. Holder"}}}, "POST", "/credentials", {"credential": {"issuer": DID, "subject": {"name": "A. Holder"}}, "revocable": False, "distribute": False, "format": "jsonld", "persist": False}),
    ("revoke_credential", {"credential_id": URI}, "POST", "/credentials/" + URI + "/revoke", None),
    ("unrevoke_credential", {"credential_id": URI}, "POST", "/credentials/" + URI + "/unrevoke", None),
    ("delete_credential", {"credential_id": URI}, "DELETE", "/credentials/" + URI, None),
    ("verify_credential", {"presentation": {"type": ["VerifiablePresentation"]}}, "POST", "/verify", {"type": ["VerifiablePresentation"]}),
    ("list_schemas", {}, "GET", "/schemas", None),
    ("get_schema", {"schema_id": "schema-1"}, "GET", "/schemas/schema-1", None),
    ("create_schema", {"schema_document": {"name": "Degree", "type": "object"}}, "POST", "/schemas", {"name": "Degree", "type": "object"}),
    ("delete_schema", {"schema_id": "schema-1"}, "DELETE", "/schemas/schema-1", None),
    ("list_proof_requests", {}, "GET", "/proof-requests", None),
    ("get_proof_request", {"proof_request_id": UUID}, "GET", "/proof-requests/" + UUID, None),
    ("create_proof_request", {"name": "Proof request", "nonce": "1234567890"}, "POST", "/proof-requests", {"name": "Proof request", "nonce": "1234567890"}),
    ("delete_proof_request", {"proof_request_id": UUID}, "DELETE", "/proof-requests/" + UUID, None),
    ("get_job", {"job_id": "2432"}, "GET", "/jobs/2432", None),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,args,method,path,body", CASES, ids=["dock-certs-" + case[0] for case in CASES])
async def test_dock_certs_all_operations_one_exact_request(monkeypatch, operation, args, method, path, body):
    payload = [{"name": "My issuer", "did": DID}] if operation.startswith("list_") else {"id": "2432"}
    requests = transport(monkeypatch, payload)
    result = await node({"operation": operation, **args}).execute({})
    assert result["status"] == "success" and result["data"] == payload
    assert len(requests) == 1
    req = requests[0]
    assert req.method == method and req.url.path == path
    assert req.url.host == "api.truvera.io" and req.headers["Authorization"] == "Bearer " + TOKEN
    assert TOKEN not in str(req.url) and TOKEN not in str(result)
    assert (json.loads(req.content) if req.content else None) == body
    if operation in {"create_did", "create_schema"}:
        assert result["job_submitted"] is True


def test_dock_certs_contract_fixture_pin_and_operation_coverage():
    assert hashlib.sha256(FIXTURE.read_bytes()).hexdigest() == "7dd764ac9504faca38075e1253e118bda9ad29f3daaee1232ca2922e0ec5b978"
    contract = yaml.safe_load(FIXTURE.read_text())
    assert len(CASES) == len(native.ROUTES) == 25
    assert {c[0] for c in CASES} == set(native.ROUTES)
    for method, route in native.ROUTES.values():
        route = route.replace("{credential_id}", "{id}").replace("{template_id}", "{id}").replace("{proof_request_id}", "{id}").replace("{schema_id}", "{schemaId}").replace("{job_id}", "{id}")
        assert method.lower() in contract["paths"][route]


@pytest.mark.asyncio
async def test_dock_certs_filters_pagination_and_sandbox(monkeypatch):
    requests = transport(monkeypatch, [{"id": "one"}])
    result = await node({"operation": "list_credentials", "limit": 1, "offset": 2, "subject_id": DID, "filter": "University + degree"}, environment="sandbox").execute({})
    assert result["next_offset"] == 3 and len(requests) == 1
    assert requests[0].url.host == "api-testnet.truvera.io"
    assert dict(requests[0].url.params) == {"limit": "1", "offset": "2", "subjectId": DID, "filter": "University + degree"}
    transport(monkeypatch, [])
    result = await node({"operation": "list_profiles"}).execute({})
    assert result["items"] == [] and result["next_offset"] is None


@pytest.mark.asyncio
async def test_dock_certs_credential_uri_is_encoded_as_one_path_value(monkeypatch):
    requests = transport(monkeypatch, {})
    await node({"operation": "get_credential", "credential_id": "https://creds.truvera.io/id?x=1#fragment"}).execute({})
    req = requests[0]
    assert req.url.raw_path == b"/credentials/https%3A%2F%2Fcreds.truvera.io%2Fid%3Fx%3D1%23fragment"
    assert not req.url.query and not req.url.fragment


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 302, 400, 401, 403, 404, 429, 500])
async def test_dock_certs_http_errors_preserve_rejection_and_redact_key(monkeypatch, status):
    requests = transport(monkeypatch, {"message": "Rejected " + TOKEN}, status)
    result = await node({"operation": "list_profiles"}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert "Rejected" in result["error"] and TOKEN not in str(result) and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{"errors": ["rejected"]}, {"error": "rejected"}, "unexpected", {"items": []}])
async def test_dock_certs_malformed_list_and_error_envelopes(monkeypatch, payload):
    transport(monkeypatch, payload)
    with pytest.raises(ValueError):
        await node({"operation": "list_profiles"}).execute({})


@pytest.mark.parametrize("config", [{"operation": "get_credential", "credential_id": ".."}, {"operation": "list_profiles", "limit": 65}, {"operation": "list_profiles", "offset": -1}, {"operation": "list_profiles", "limit": True}, {"operation": "get_template", "template_id": "bad"}, {"operation": "create_template", "html": "x"}, {"operation": "custom_request"}])
def test_dock_certs_invalid_inputs(config):
    with pytest.raises((ValueError, ValidationError)):
        native.DockCertsNode.parse_config({"config": config, "credentials": AUTH})


def test_dock_certs_manual_credential_default_and_allowed_environments():
    assert native.DockCertsAPIKeyCredential(api_key=TOKEN).credential_type == "dock_certs_api_key"
    for changes in ({"api_key": "Bearer " + TOKEN}, {"environment": "https://evil.example"}, {"api_key": "https://example.com/key"}):
        with pytest.raises(ValidationError):
            native.DockCertsAPIKeyCredential.model_validate({**AUTH, **changes})


@pytest.mark.asyncio
async def test_dock_certs_proof_verification_error_is_resource_state(monkeypatch):
    payload = {"id": UUID, "verified": False, "error": "Presentation did not match"}
    transport(monkeypatch, payload)
    result = await node({"operation": "get_proof_request", "proof_request_id": UUID}).execute({})
    assert result["status"] == "success" and result["data"] == payload


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,field,body", [
    ("issue_credential", "credential", {"issuer": DID, "subject": {"name": "A. Holder"}}),
    ("verify_credential", "presentation", {"type": ["VerifiablePresentation"]}),
    ("create_schema", "schema_document", {"name": "Degree", "type": "object"}),
    ("create_proof_request", "request", {"name": "Degree proof", "purpose": "Verify degree"}),
])
async def test_dock_certs_accepts_pasted_json(monkeypatch, operation, field, body):
    requests = transport(monkeypatch, {"id": UUID})
    config = {"operation": operation, field: json.dumps(body)}
    if operation == "create_proof_request":
        config["name"] = "Proof request"
    await node(config).execute({})
    sent = json.loads(requests[0].content)
    assert (sent[field] if operation in {"issue_credential", "create_proof_request"} else sent) == body
