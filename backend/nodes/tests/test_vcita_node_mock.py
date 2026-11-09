"""vcita request wiring against provider examples with credential values redacted."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from nodes import vcita_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-vcita-token-42"
EXAMPLES = json.loads((Path(__file__).parent / "fixtures/vcita/contract_examples.json").read_text())
CONFIGS = {
    "list_clients": {"search_term": "clientemail@mail.com", "search_by": "email", "page": 2, "per_page": 10},
    "get_client": {"client_id": "czpvt3f246p4cw9i"},
    "create_client": {"first_name": "Michael", "last_name": "Douglas", "email": "michael.douglass@spartacus.info.fake", "opt_in": False},
    "update_client": {"client_id": "czpvt3f246p4cw9i", "first_name": "NEWFIRSTNAME", "spam": False},
    "delete_client": {"client_id": "czpvt3f246p4cw9i"},
    "list_fields": {}, "get_field": {"field_id": "c3k9x1p2m8q7r4tz"},
    "list_appointments": {"state": "done,rejected", "page": 2},
    "get_appointment": {"appointment_id": "e7j16p8"},
    "create_booking": {"business_id": "104a5664c3663a8d", "service_id": "vpa6mzkt11f1n2pc", "staff_id": "j9c1xh0vzvkr2g0g", "start_time": "2026-09-16T15:00:00Z", "form_data": {"fields": {"vvx3507vmuy3mz5e": "client@example.com", "m9nb5f34rvvkl4mi": "John"}, "policies": {"meetings_policy": True}}},
    "cancel_booking": {"business_id": "104a5664c3663a8d", "booking_id": "e7j16p8"},
    "list_services": {"business_id": "104a5664c3663a8d"}, "get_service": {"service_uid": "vpa6mzkt11f1n2pc"},
    "list_payments": {"page": "2", "per_page": "10", "on_behalf_of": "104a5664c3663a8d"}, "get_payment": {"payment_uid": "payment123"},
    "list_invoices": {"page": "2", "per_page": "10"}, "get_invoice": {"invoice_id": "invoice123"},
    "list_estimates": {"page": 2}, "get_scheduling_form": {"business_id": "104a5664c3663a8d", "service_id": "vpa6mzkt11f1n2pc"},
    "get_staff_availability": {"start_date": "2026-03-03", "end_date": "2026-03-10", "staff_ids_array": "j9c1xh0vzvkr2g0g", "time_zone": "UTC", "aggregate_by": "staff", "include_dst": "true"},
}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(operation, **changes):
    return NodeFactory.create_node(node_id="vcita-test", node_type="automation-vcita",
        node_data={"config": {"operation": operation, **CONFIGS[operation], **changes},
            "credentials": {"credential_type": "vcita_api_token", "api_token": TOKEN}})


def mock(monkeypatch, status, body):
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", CONFIGS)
async def test_vcita_exact_contract_request_and_documented_response(monkeypatch, operation):
    fixture = EXAMPLES[operation]
    calls = mock(monkeypatch, fixture["status"], fixture["body"])
    instance = node(operation)
    result = await instance.execute({})
    assert result["status"] == "success", result
    assert len(calls) == 1
    request = calls[0]
    assert request.method == fixture["method"]
    expected_path = fixture["path"]
    for field, value in CONFIGS[operation].items():
        expected_path = expected_path.replace("{" + field + "}", str(value))
    assert request.url.path == expected_path
    assert request.url.host == "api.vcita.biz"
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    values = instance.config.config.model_dump(mode="json", exclude_none=True, exclude={"operation"})
    expected_query = {}
    for field, (location, name) in native.ROUTES[operation][3].items():
        if field not in values:
            continue
        value = values.pop(field)
        if location == "query": expected_query[name] = str(value)
        elif location == "header": assert request.headers[name] == value
    assert dict(request.url.params) == expected_query
    if fixture["method"] in {"POST", "PUT"}:
        assert json.loads(request.content) == values
    else:
        assert request.content == b""
    assert TOKEN not in str(result)
    assert "token" not in result["data"]
    if operation.startswith("list_"):
        assert isinstance(result["items"], list)


@pytest.mark.asyncio
@pytest.mark.parametrize("status,body", [(401, {"status": "Error", "error": "Token not authorized"}), (403, {"status": "Error", "message": "Forbidden"}), (429, {"status": "Error", "error": "Rate limited"}), (500, {"status": "Error", "error": "Server failed"}), (302, {"status": "OK", "data": {"clients": []}}), (200, {"status": "Error", "error": "Invalid token"}), (200, {"status": "OK"}), (200, {"status": "OK", "data": {"clients": {}}})])
async def test_vcita_errors_never_look_like_success_or_retry(monkeypatch, status, body):
    calls = mock(monkeypatch, status, body)
    result = await node("list_clients").execute({})
    assert result["status"] == "error" and len(calls) == 1
    if body.get("error"): assert result["error"] == body["error"]


@pytest.mark.asyncio
async def test_vcita_response_token_redaction_and_empty_account_evidence(monkeypatch):
    mock(monkeypatch, 200, {"status": "OK", "data": {"clients": [{"id": "42", "email": TOKEN, "token": "secret-returned-by-provider"}]}})
    result = await node("list_clients").execute({})
    assert TOKEN not in str(result) and "secret-returned-by-provider" not in str(result)
    mock(monkeypatch, 200, {"status": "OK", "data": {"clients": []}})
    assert (await node("list_clients").execute({}))["items"] == []
    assert native.VcitaNode.connection_evidence.operation == "list_clients"


@pytest.mark.parametrize("config", [
    {"operation": "get_client", "client_id": "../payments"},
    {"operation": "get_invoice", "invoice_id": "x?other=y"},
    {"operation": "update_client", "client_id": "client123"},
    {"operation": "list_clients", "per_page": 101},
    {"operation": "create_booking", "business_id": "business123", "form_data": {"fields": {}}},
    {"operation": "create_booking", **CONFIGS["create_booking"], "form_data": {"fields": []}},
    {"operation": "get_staff_availability", **CONFIGS["get_staff_availability"], "start_date": "2026-02-30"},
])
def test_vcita_invalid_targets_and_required_inputs(config):
    with pytest.raises(ValidationError):
        native.VcitaFullConfig.model_validate({"config": config})


def test_vcita_manual_credential_default_and_secret_shape():
    assert native.VcitaAPITokenCredential(api_token=TOKEN).credential_type == "vcita_api_token"
    for bad in ("https://app.vcita.com", "Bearer token123", "abc\r\nHost: evil"):
        with pytest.raises(ValidationError):
            native.VcitaAPITokenCredential(api_token=bad)


@pytest.mark.asyncio
async def test_vcita_explicit_clear_and_omitted_fields(monkeypatch):
    example = EXAMPLES["update_client"]
    calls = mock(monkeypatch, example["status"], example["body"])
    result = await node("update_client", force_nullifying=True, address=None).execute({})
    assert result["status"] == "success"
    body = json.loads(calls[0].content)
    assert body["address"] == "" and "mobile_phone" not in body


@pytest.mark.parametrize("email", ["invalid", "not an email@example.com"])
def test_vcita_invalid_email_is_rejected(email):
    with pytest.raises(ValidationError):
        native.VcitaCreateClientConfig(first_name="John", email=email)


def test_vcita_fixtures_do_not_publish_provider_shaped_credentials():
    import importlib.util

    root = Path(__file__).resolve().parents[3]
    scanner_path = root / "oss/scan_real_secrets.py"
    if not scanner_path.exists():
        scanner_path = root / "scripts/scan_real_secrets.py"
    spec = importlib.util.spec_from_file_location("vcita_secret_scan", scanner_path)
    scanner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(scanner)
    fixture = Path(__file__).parent / "fixtures/vcita/contract_examples.json"
    findings = scanner.find_secrets(fixture.read_bytes())
    # Report counts only, so a future regression cannot print a credential.
    assert not {kind: len(values) for kind, values in findings.items()}
    assert EXAMPLES["create_client"]["body"]["data"]["token"] == "example-vcita-client-token"
