"""Native factory tests with fake DNS and HTTP; no SignPath account required."""
import json
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from nodes import signpath_node as node
from nodes.core.binary_output import BinaryOutput
from nodes.core.registry import NodeFactory
from nodes.core.credential_connect import credential_classes_for_node
from utils import ssrf

ORG = "094f5736-6b8c-4ca7-9514-0933c8b928e2"
REQUEST = "3fa85f64-5717-4562-b3fc-2c963f66afa6"
TOKEN = "fixture-signpath-not-live"
AUTH = {"credential_type": "signpath_api_token", "api_token": TOKEN, "organization_id": ORG}


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))
    async def send(request):
        requests.append(request)
        assert request.url.host == "app.signpath.io"
        assert request.headers["Authorization"] == "Bearer " + TOKEN
        assert TOKEN not in str(request.url)
        code, payload, *headers = replies.pop(0)
        if isinstance(payload, bytes):
            return httpx.Response(code, content=payload, headers=headers[0] if headers else {})
        return httpx.Response(code, json=payload, headers=headers[0] if headers else {})
    native = ssrf.guarded_async_client
    monkeypatch.setattr(node, "guarded_async_client", lambda **kw: native(**kw, transport=httpx.MockTransport(send)))
    return requests, replies


async def run(operation, arguments=None):
    instance = NodeFactory.create_node(node_id="signpath-test", node_type="automation-signpath",
        node_data={"config": {"operation": operation, **(arguments or {})}, "credentials": AUTH})
    return await instance.execute({})


CASES = [
    ("get_current_user", {}, "GET", "Users/Me", 200),
    ("get_organization", {}, "GET", "Organization", 200),
    ("list_projects", {}, "GET", "Projects", 200),
    ("get_project", {"project_slug": "release"}, "GET", "Projects/release", 200),
    ("create_project", {"name": "Release", "slug": "release", "artifact_configuration_xml": "<artifact-configuration xmlns='http://signpath.io/artifact-configuration/v1'><pe-file/></artifact-configuration>"}, "POST", "Projects", 201),
    ("edit_project", {"project_slug": "release", "name": "Release 2", "slug": "release-v2"}, "POST", "Projects/release/Edit", 204),
    ("activate_project", {"project_slug": "release"}, "POST", "Projects/release/Activate", 204),
    ("deactivate_project", {"project_slug": "release"}, "POST", "Projects/release/Deactivate", 204),
    ("get_signing_policy", {"project_slug": "release", "signing_policy_slug": "test-signing"}, "GET", "Projects/release/SigningPolicies/test-signing", 200),
    ("list_signing_requests", {}, "GET", "SigningRequests", 200),
    ("get_signing_request", {"signing_request_id": REQUEST}, "GET", f"SigningRequests/{REQUEST}", 200),
    ("get_signing_request_status", {"signing_request_id": REQUEST}, "GET", f"SigningRequests/{REQUEST}/Status", 200),
    ("sign_hash", {"project_slug": "hash-signing", "signing_policy_slug": "test-signing", "hash_base64": "ZOyIygCyaOW6GjVnihtTFtIS9PNmskdyMlNKiuyjfzw="}, "POST", "SigningRequests/SignHash", 201),
    ("resubmit_signing_request", {"original_signing_request_id": REQUEST, "signing_policy_slug": "release-signing"}, "POST", "SigningRequests/Resubmit", 201),
    ("approve_signing_request", {"signing_request_id": REQUEST}, "POST", f"SigningRequests/{REQUEST}/Approve", 204),
    ("deny_signing_request", {"signing_request_id": REQUEST, "deny_reason": "Untrusted build"}, "POST", f"SigningRequests/{REQUEST}/Deny", 204),
    ("cancel_signing_request", {"signing_request_id": REQUEST}, "POST", f"SigningRequests/{REQUEST}/Cancel", 204),
    ("download_signed_artifact", {"signing_request_id": REQUEST}, "GET", f"SigningRequests/{REQUEST}/SignedArtifact", 200),
    ("download_unsigned_artifact", {"signing_request_id": REQUEST}, "GET", f"SigningRequests/{REQUEST}/UnsignedArtifact", 200),
    ("list_certificates", {}, "GET", "Certificates", 200),
    ("get_certificate", {"certificate_slug": "release-cert"}, "GET", "Certificates/release-cert", 200),
    ("list_ci_users", {}, "GET", "CIUsers", 200),
    ("list_user_groups", {}, "GET", "UserGroups", 200),
    ("list_trusted_build_systems", {}, "GET", "TrustedBuildSystems", 200),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,arguments,method,path,code", CASES)
async def test_operations_use_exact_contract_routes(transport, operation, arguments, method, path, code):
    requests, replies = transport
    download = operation.startswith("download_")
    payload = b"artifact-content" if download else b"" if code in {201, 204} and operation != "sign_hash" else {"name": "fixture"}
    replies.append((code, payload))
    result = await run(operation, arguments)
    assert result["status"] == "success"
    assert len(requests) == 1
    assert requests[0].method == method
    assert requests[0].url.path == f"/Api/v1/{ORG}/{path}"
    if download:
        assert isinstance(result["file"], BinaryOutput)
        assert result["file"].data == payload
    if operation == "create_project":
        assert json.loads(requests[0].content) == {"name": "Release", "slug": "release", "artifactConfigurationXml": arguments["artifact_configuration_xml"]}
    if operation == "deny_signing_request":
        assert json.loads(requests[0].content) == {"denyReason": "Untrusted build"}
    if operation == "sign_hash":
        assert json.loads(requests[0].content) == {
            "projectSlug": "hash-signing", "signingPolicySlug": "test-signing",
            "hashSigningData": {"hash": arguments["hash_base64"], "signatureAlgorithm": "Rsa",
                "rsaOptions": {"hashAlgorithmName": "Sha256", "paddingMode": "Pkcs1"}},
        }


@pytest.mark.asyncio
async def test_filtered_list_retains_provider_pagination(transport):
    requests, replies = transport
    payload = {"signingRequests": [], "pagination": {"nextLink": "https://app.signpath.io/Api/v1/next"}}
    replies.append((200, payload))
    result = await run("list_signing_requests", {"submitted_after": "2026-01-01T00:00:00Z", "signing_request_status": ["Completed", "Failed"], "project_slug": "release"})
    assert requests[0].url.params.get_list("signingRequestStatus") == ["Completed", "Failed"]
    assert requests[0].url.params["submittedAfter"] == "2026-01-01T00:00:00Z"
    assert result["data"] == payload
    assert len(requests) == 1  # Return pagination as data; never follow an arbitrary nextLink.


@pytest.mark.asyncio
async def test_resubmission_json_and_location(transport):
    requests, replies = transport
    replies.append((201, b"", {"Location": f"/Api/v1/{ORG}/SigningRequests/{REQUEST}"}))
    result = await run("resubmit_signing_request", {"original_signing_request_id": REQUEST, "signing_policy_slug": "release", "keep_snapshotted_artifact_configuration": False})
    assert json.loads(requests[0].content) == {"originalSigningRequestId": REQUEST, "signingPolicySlug": "release", "keepSnapshottedArtifactConfiguration": False}
    assert result["location"].endswith(REQUEST)


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [302, 401, 403, 404, 429, 500])
async def test_rejections_are_verbatim_redacted_and_never_retried(transport, code):
    requests, replies = transport
    replies.append((code, {"title": "Forbidden", "detail": "Access denied: " + TOKEN}, {"Location": "https://other.example.test"}))
    result = await run("list_projects")
    assert result["status"] == "error"
    assert result["http_status"] == code
    assert result["error"] == "Access denied: [redacted]"
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("payload,headers", [(b"", {}), (b"<html>login</html>", {"Content-Type": "text/html"}), (b"broken json", {"Content-Type": "application/json"})])
async def test_invalid_reads_cannot_prove_connection(transport, payload, headers):
    _, replies = transport
    replies.append((200, payload, headers))
    with pytest.raises(ValueError):
        await run("list_projects")


def test_manual_credential_defaults_and_required_inputs():
    credential = node.SignpathAPITokenCredential(api_token=TOKEN, organization_id=ORG)
    assert credential.credential_type == "signpath_api_token"
    assert node.SignpathAPITokenCredential in credential_classes_for_node(node.SignpathNode)
    assert {k for k, v in node.SignpathAPITokenCredential.model_fields.items() if v.is_required()} == {"api_token", "organization_id"}


@pytest.mark.parametrize("token", ["Bearer abc", "https://example.com/token", "abc\r\nInjected: token", "<token>", ""])
def test_invalid_tokens_are_rejected(token):
    with pytest.raises((ValidationError, ValueError)):
        node.SignpathAPITokenCredential(api_token=token, organization_id=ORG)


@pytest.mark.parametrize("field,value", [("project_slug", "../other"), ("project_slug", "x/y"), ("signing_request_id", "not-a-uuid")])
def test_path_injection_is_rejected(field, value):
    operation = "get_project" if field == "project_slug" else "get_signing_request"
    with pytest.raises(ValueError):
        node.SignpathNode.parse_config({"config": {"operation": operation, field: value}, "credentials": AUTH})


@pytest.mark.asyncio
async def test_bad_hash_length_is_rejected_before_request(transport):
    requests, _ = transport
    with pytest.raises(ValueError, match="Digest length"):
        await run("sign_hash", {"project_slug": "hash-signing", "signing_policy_slug": "test-signing", "hash_base64": "YWJj"})
    assert not requests


@pytest.mark.asyncio
async def test_documented_status_response(transport):
    from pathlib import Path
    payload = json.loads((Path(__file__).parent / "fixtures/signpath/status.json").read_text())
    transport[1].append((200, payload))
    result = await run("get_signing_request_status", {"signing_request_id": REQUEST})
    assert result["data"] == payload
