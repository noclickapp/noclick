"""Exercise all published routes using provider response examples."""
import json
import importlib.util
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError
from nodes import salesql_node as node
from nodes.core.registry import NodeFactory
from utils import ssrf

AUTH = {"credential_type": "salesql_api_key", "api_key": "fixture-salesql-key"}
FIXTURES = json.loads((Path(__file__).parent / "fixtures/salesql/published_examples.json").read_text())["operations"]
JOB = "3f0c7a7e-2b6d-4a1e-9c3b-0d5e6f7a8b9c"
CASES = [
    ("get_credit_allowance", {}, "getCreditsAllowance"),
    ("enrich_organization", {"linkedin_url": "https://linkedin.com/company/oracle"}, "enrichOrganization"),
    ("bulk_enrich_organizations", {"organizations": [{"organization_domain": "oracle.com"}]}, "bulkEnrichOrganizations"),
    ("enrich_person", {"linkedin_url": "https://linkedin.com/in/bob-christiaanse", "match_if_direct_email": True}, "enrichPersonByLinkedInURL"),
    ("lookup_person_by_email", {"email": "catherinelkent@gmail.com"}, "emailLookupPerson"),
    ("bulk_enrich_persons", {"persons": [{"full_name": "Bob Christiaanse", "organization_name": "LinkedIn"}]}, "bulkEnrichPersons"),
    ("verify_email", {"email": "catherine.kent@acme.com"}, "verifyEmail"),
    ("bulk_verify_emails", {"emails": ["catherine.kent@acme.com", "john.doe@gmail.com"]}, "bulkVerifyEmails"),
    ("get_bulk_verification_job", {"job_id": JOB}, "getBulkVerificationJob"),
]
# Allowance has no complete published example; this is a schema-shaped stub.
FIXTURES["getCreditsAllowance"] = {"method": "GET", "path": "/allowance", "status": 200,
    "body": {"credits": {"emails_and_phones": 42, "verifications": 50}, "reset_date": None}}

@pytest.fixture
def ensure_native_db_pool():
    yield

@pytest.fixture
def transport(monkeypatch):
    requests, responses = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))
    async def send(request):
        requests.append(request)
        assert request.url.host == "api-public.salesql.com"
        assert request.headers["Authorization"] == "Bearer " + AUTH["api_key"]
        assert AUTH["api_key"] not in str(request.url)
        return responses.pop(0)
    native = ssrf.guarded_async_client
    monkeypatch.setattr(node, "guarded_async_client", lambda **kw: native(**kw, transport=httpx.MockTransport(send)))
    return requests, responses

async def run(config):
    instance = NodeFactory.create_node(node_id="salesql-test", node_type="automation-salesql",
        node_data={"config": config, "credentials": AUTH})
    return await instance.execute({})

@pytest.mark.asyncio
@pytest.mark.parametrize("operation,config,example", CASES)
async def test_published_routes_and_examples(transport, operation, config, example):
    requests, replies = transport
    fixture = FIXTURES[example]
    replies.append(httpx.Response(fixture["status"], json=fixture["body"]))
    result = await run({"operation": operation, **config})
    assert result == {"status": "success", "data": fixture["body"]}
    assert len(requests) == 1
    request = requests[0]
    assert request.method == fixture["method"]
    assert request.url.path == "/v1" + fixture["path"].replace("{job_id}", JOB)
    if request.method == "POST":
        assert json.loads(request.content) == config.get("organizations", config.get("persons", config))
    else:
        for key, value in config.items():
            if key != "job_id":
                assert request.url.params[key] == (str(value).lower() if isinstance(value, bool) else value)
    assert not replies

@pytest.mark.asyncio
async def test_job_processing_retry_hint(transport):
    body = {"job_id": JOB, "status": "processing", "n_emails": 2, "n_verified_emails": 1,
        "n_unverified_emails": 0, "n_failed_emails": 0, "credits_charged": None}
    transport[1].append(httpx.Response(200, json=body, headers={"Retry-After": "10"}))
    result = await run({"operation": "get_bulk_verification_job", "job_id": JOB})
    assert result["data"] == body and result["retry_after"] == "10"
    assert len(transport[0]) == 1

@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 402, 409, 422, 429, 502, 503])
async def test_provider_errors_no_retry_or_secret_leak(transport, status):
    transport[1].append(httpx.Response(status, json={"error": "missing_scope", "required_scope": "verify:verify", "echo": AUTH["api_key"]},
        headers={"Retry-After": "10", "Location": "https://other.example/"}))
    result = await run({"operation": "verify_email", "email": "catherine.kent@acme.com"})
    assert result["status"] == "error" and result["http_status"] == status
    assert "missing_scope" in result["message"] and "verify:verify" in result["message"]
    assert AUTH["api_key"] not in str(result) and len(transport[0]) == 1

@pytest.mark.asyncio
@pytest.mark.parametrize("body", [[], None, "html"])
async def test_unexpected_single_shape(transport, body):
    transport[1].append(httpx.Response(200, json=body))
    with pytest.raises(ValueError):
        await run({"operation": "get_credit_allowance"})

@pytest.mark.parametrize("config", [
    {"operation": "enrich_organization"}, {"operation": "enrich_person", "first_name": "Bob"},
    {"operation": "bulk_enrich_persons", "persons": [{}]},
    {"operation": "bulk_enrich_organizations", "organizations": []},
    {"operation": "bulk_verify_emails", "emails": ["x@example.com"] * 501},
    {"operation": "get_bulk_verification_job", "job_id": "../../allowance"},
])
def test_input_groups_and_bounds(config):
    with pytest.raises((ValidationError, ValueError)):
        node.SalesQLNode.parse_config({"config": config, "credentials": AUTH})

def test_manual_credential():
    value = node.SalesQLAPIKeyCredential(api_key=" fixture-salesql-key ")
    assert value.credential_type == "salesql_api_key" and value.api_key == AUTH["api_key"]
    assert node.SalesQLAPIKeyCredential.model_json_schema()["required"] == ["api_key"]
    for key in ["Bearer invalid", "https://example.com/key", "key\nheader"]:
        with pytest.raises((ValidationError, ValueError)):
            node.SalesQLAPIKeyCredential(api_key=key)


def test_salesql_published_fixtures_contain_no_real_shaped_credentials():
    """Public documentation's transient signed URLs must not become secrets in Git."""
    root = Path(__file__).resolve().parents[3]
    # The open tree materializes this same scanner under scripts/.
    scanner = next(path for path in (root / "oss/scan_real_secrets.py",
        root / "scripts/scan_real_secrets.py") if path.is_file())
    spec = importlib.util.spec_from_file_location("salesql_fixture_secret_scan", scanner)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    fixture = Path(__file__).parent / "fixtures/salesql/published_examples.json"
    findings = module.find_secrets(fixture.read_bytes())
    assert not findings, {name: len(values) for name, values in findings.items()}
