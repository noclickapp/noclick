"""Docusign OAuth and eSignature API contracts, using HTTP response fixtures."""

import base64
import json
from unittest.mock import Mock

import httpx
import pytest
import respx

from nodes.docusign_node import (
    CreateFromTemplate, DocusignNode, DocusignNodeConfig,
    DocusignOAuthCredential, DownloadDocument, GetAccount, GetEnvelope,
    GetTemplate, ListDocuments, ListEnvelopes, ListRecipients, ListTemplates,
    SendDocument, VoidEnvelope,
)
from nodes.oauth.docusign_oauth import (
    OAUTH_PROVIDER, refresh_access_token, resolve_account, validate_base_uri,
)
from nodes.core.binary_output import BinaryOutput


API = "https://demo.docusign.net/restapi/v2.1/accounts/acct-1"


def make_node(operation):
    credentials = DocusignOAuthCredential(
        access_token="access", refresh_token="refresh", account_id="acct-1",
        base_uri="https://demo.docusign.net", expires_at="2099-01-01T00:00:00Z",
    )
    return DocusignNode(
        node_id="docusign-test", node_type="automation-docusign", node_data={},
        config=DocusignNodeConfig(config=operation, credentials=credentials),
        sio=Mock(), sid="sid", workflow_id="workflow", user_id="user",
    )


@pytest.mark.asyncio
async def test_oauth_discovers_default_account_and_refreshes(monkeypatch):
    monkeypatch.setenv("DOCUSIGN_CLIENT_ID", "client")
    monkeypatch.setenv("DOCUSIGN_CLIENT_SECRET", "secret")

    with respx.mock(assert_all_called=True) as router:
        token = router.post("https://account.docusign.com/oauth/token").mock(
            side_effect=[
                httpx.Response(200, json={"access_token": "first", "refresh_token": "renew", "expires_in": 3600}),
                httpx.Response(200, json={"access_token": "second", "refresh_token": "rotated", "expires_in": 3600}),
            ])
        router.get("https://account.docusign.com/oauth/userinfo").mock(
            return_value=httpx.Response(200, json={
                "sub": "user-1", "name": "Ava", "email": "ava@example.com",
                "accounts": [
                    {"account_id": "other", "account_name": "Other", "base_uri": "https://eu.docusign.net", "is_default": False},
                    {"account_id": "acct-1", "account_name": "Main", "base_uri": "https://demo.docusign.net", "is_default": True},
                ],
            }))
        verifier = "v" * 43
        tokens, name = await OAUTH_PROVIDER.exchange("code", "https://noclick.com/api/auth/oauth/docusign/callback", verifier)
        identity = await resolve_account(tokens.model_dump())
        renewed = await refresh_access_token(tokens.refresh_token)
    assert token.call_count == 2
    assert dict(httpx.QueryParams(token.calls[0].request.content.decode()))["code_verifier"] == verifier
    assert name == "Ava"
    assert identity["account_id"] == "acct-1"
    assert identity["base_uri"] == "https://demo.docusign.net"
    assert renewed.access_token == "second"
    assert renewed.refresh_token == "rotated"


@pytest.mark.parametrize("uri", [
    "http://demo.docusign.net", "https://demo.docusign.net.evil.example",
    "https://demo.docusign.net:8443", "https://demo.docusign.net/restapi",
    "https://user@demo.docusign.net",
])
def test_account_api_origin_is_constrained(uri):
    with pytest.raises(ValueError, match="invalid account API base URI"):
        validate_base_uri(uri)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,method,path", [
    (GetAccount(), "GET", ""),
    (ListTemplates(), "GET", "/templates"),
    (GetTemplate(template_id="template-1"), "GET", "/templates/template-1"),
    (GetEnvelope(envelope_id="env-1"), "GET", "/envelopes/env-1"),
    (ListEnvelopes(from_date="2026-01-01T00:00:00Z"), "GET", "/envelopes"),
    (ListRecipients(envelope_id="env-1"), "GET", "/envelopes/env-1/recipients"),
    (ListDocuments(envelope_id="env-1"), "GET", "/envelopes/env-1/documents"),
])
async def test_read_operations_hit_account_api(operation, method, path, monkeypatch):
    node = make_node(operation)
    async def no_refresh(_):
        return "access"
    monkeypatch.setattr(node, "_token", no_refresh)
    with respx.mock(assert_all_called=True) as router:
        route = router.request(method, API + path).mock(return_value=httpx.Response(200, json={"ok": True}))
        result = await node.execute({})
    assert route.called
    assert route.calls[0].request.headers["Authorization"] == "Bearer access"
    assert result["data"] == {"ok": True}


@pytest.mark.asyncio
async def test_send_from_template_has_recipient_role_and_draft_mode(monkeypatch):
    node = make_node(CreateFromTemplate(
        template_id="template-1", signer_name="Ava", signer_email="ava@example.com",
        role_name="Customer", send_now=False,
    ))
    async def no_refresh(_):
        return "access"
    monkeypatch.setattr(node, "_token", no_refresh)
    with respx.mock(assert_all_called=True) as router:
        route = router.post(API + "/envelopes").mock(return_value=httpx.Response(201, json={"envelopeId": "env-1"}))
        result = await node.execute({})
    assert result["data"]["envelopeId"] == "env-1"
    body = json.loads(route.calls[0].request.content)
    assert body["status"] == "created"
    assert body["templateRoles"] == [{"email": "ava@example.com", "name": "Ava", "roleName": "Customer"}]


@pytest.mark.asyncio
async def test_send_document_and_download_signed_pdf(monkeypatch):
    source_pdf = b"%PDF-1.5\n/sign1/\n%%EOF"
    node = make_node(SendDocument(
        document_base64=base64.b64encode(source_pdf).decode(),
        signer_name="Ava", signer_email="ava@example.com", anchor_string="/sign1/",
    ))
    async def no_refresh(_):
        return "access"
    monkeypatch.setattr(node, "_token", no_refresh)
    with respx.mock(assert_all_called=True) as router:
        route = router.post(API + "/envelopes").mock(return_value=httpx.Response(201, json={"envelopeId": "env-1"}))
        await node.execute({})
    body = json.loads(route.calls[0].request.content)
    assert body["status"] == "sent"
    assert body["documents"][0]["documentBase64"] == base64.b64encode(source_pdf).decode()
    assert body["recipients"]["signers"][0]["tabs"]["signHereTabs"][0]["anchorString"] == "/sign1/"

    download = make_node(DownloadDocument(envelope_id="env-1"))
    monkeypatch.setattr(download, "_token", no_refresh)
    with respx.mock(assert_all_called=True) as router:
        router.get(API + "/envelopes/env-1/documents/combined").mock(
            return_value=httpx.Response(200, content=source_pdf, headers={"Content-Type": "application/pdf"}))
        result = await download.execute({})
    content = result["data"]["content"]
    assert isinstance(content, BinaryOutput)
    assert content.data == source_pdf
    assert content.content_type == "application/pdf"
    assert content.filename == "combined.pdf"


@pytest.mark.asyncio
async def test_void_envelope_sends_reason(monkeypatch):
    node = make_node(VoidEnvelope(envelope_id="env-1", reason="Sent in error"))
    async def no_refresh(_):
        return "access"
    monkeypatch.setattr(node, "_token", no_refresh)
    with respx.mock(assert_all_called=True) as router:
        route = router.put(API + "/envelopes/env-1").mock(return_value=httpx.Response(200, json={"status": "voided"}))
        result = await node.execute({})
    assert result["data"]["status"] == "voided"
    assert json.loads(route.calls[0].request.content)["voidedReason"] == "Sent in error"


@pytest.mark.asyncio
async def test_generic_credential_executes_and_retains_discovered_account():
    node = make_node(GetAccount())
    node.config.credentials.account_id = None
    node.config.credentials.base_uri = None
    with respx.mock(assert_all_called=True) as router:
        identity = router.get(OAUTH_PROVIDER.identity_url).mock(
            return_value=httpx.Response(200, json={
                "accounts": [{"account_id": "acct-1", "is_default": True,
                              "base_uri": "https://demo.docusign.net"}],
            }))
        route = router.get(API).mock(return_value=httpx.Response(200, json={"accountId": "acct-1"}))
        first = await node.execute({})
        await node.execute({})
    assert first["data"]["accountId"] == "acct-1"
    assert identity.call_count == 1
    assert route.call_count == 2
    assert node.config.credentials.account_id == "acct-1"
    assert node.config.credentials.base_uri == "https://demo.docusign.net"


@pytest.mark.asyncio
async def test_account_discovery_rejects_missing_default():
    with respx.mock(assert_all_called=True) as router:
        router.get(OAUTH_PROVIDER.identity_url).mock(return_value=httpx.Response(
            200, json={"accounts": []}))
        with pytest.raises(ValueError, match="no matching default"):
            await resolve_account({"access_token": "access"})


@pytest.mark.asyncio
async def test_refresh_requires_successor_token(monkeypatch):
    monkeypatch.setenv("DOCUSIGN_CLIENT_ID", "client")
    monkeypatch.setenv("DOCUSIGN_CLIENT_SECRET", "secret")
    with respx.mock(assert_all_called=True) as router:
        router.post(OAUTH_PROVIDER.token_url).mock(return_value=httpx.Response(
            200, json={"access_token": "new", "expires_in": 3600}))
        with pytest.raises(ValueError, match="refresh_token"):
            await refresh_access_token("old")
