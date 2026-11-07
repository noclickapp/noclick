"""Exercise machine credentials through native factory, connect and saved-row gates.

Only the HTTP transport and repository fixtures are synthetic; request shaping,
token lifetime, corpus restrictions and authority checks execute their real code.
"""
import json
from contextlib import asynccontextmanager
from copy import deepcopy
from urllib.parse import parse_qs

import httpx
import pytest

from nodes import vectara_node as v
from nodes.core import connection_evidence as ce, credential_connect as cc
from nodes.core.registry import NodeFactory
from tests.test_vectara_native_seams import CID, USER, current  # noqa: F401
from tests.test_vectara_node import CORPUS

CLIENT = {
    "credential_type": v.OAUTH_FAMILY,
    "client_id": "fixture-machine-client",
    "client_secret": "fixture-machine-secret",
    "token_endpoint": "https://auth.vectara.io/oauth2/token",
    "corpus_key": "owned",
}
TOKEN = {"access_token": "fixture.bearer.token", "token_type": "Bearer", "expires_in": 1800}


def make(credential=None, *, saved=False, operation="get_corpus", **config):
    return NodeFactory.create_node("machine", "automation-vectara", {
        "config": {"operation": operation, **config},
        "credentials": dict(CLIENT if credential is None else credential),
        **({"credentialIds": {v.OAUTH_FAMILY: CID}, "_approval_pool": object()} if saved else {}),
    }, user_id=USER)


@pytest.fixture
def transport(monkeypatch):
    v._TOKEN_CACHE.clear()
    calls, replies = [], []

    def handler(request):
        calls.append(request)
        assert replies, "Unexpected request"
        reply = replies.pop(0)
        if callable(reply):
            reply = reply(request)
        if isinstance(reply, Exception):
            raise reply
        status, payload = reply
        return httpx.Response(status, json=payload)

    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs == {"timeout": 30, "follow_redirects": False, "trust_env": False}
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs) as client:
            yield client

    monkeypatch.setattr(v, "guarded_async_client", client)
    yield calls, replies
    v._TOKEN_CACHE.clear()


@pytest.mark.parametrize("endpoint", ["https://auth.vectara.io/oauth2/token", "https://auth.vectara.com/oauth2/token"])
async def test_exact_form_exchange_bearer_api_and_no_secret_output(transport, endpoint):
    calls, replies = transport
    replies.extend([(200, TOKEN), (200, CORPUS)])
    result = await make({**CLIENT, "token_endpoint": endpoint}).run({})
    assert str(calls[0].url) == endpoint
    assert calls[0].method == "POST"
    assert parse_qs(calls[0].content.decode()) == {
        "grant_type": ["client_credentials"], "client_id": [CLIENT["client_id"]],
        "client_secret": [CLIENT["client_secret"]],
    }
    assert calls[1].headers["Authorization"] == "Bearer " + TOKEN["access_token"]
    assert "x-api-key" not in calls[1].headers
    assert result["data"]["key"] == "owned"
    assert not any(secret in json.dumps(result) for secret in (*v._secrets(make().config.credentials), TOKEN["access_token"]))


async def test_token_reuse_expiry_and_changed_authority(monkeypatch, transport):
    clock = [100.0]
    monkeypatch.setattr(v.time, "monotonic", lambda: clock[0])
    calls, replies = transport
    replies.extend([(200, TOKEN), (200, CORPUS), (200, CORPUS)])
    await make().run({})
    await make().run({})
    assert [r.method for r in calls] == ["POST", "GET", "GET"]
    clock[0] = 1840.0
    replies.extend([(200, TOKEN), (200, CORPUS)])
    await make().run({})
    replies.extend([(200, TOKEN), (200, CORPUS)])
    await make({**CLIENT, "client_secret": "rotated-fixture-secret"}).run({})
    assert sum(r.method == "POST" for r in calls) == 3
    assert CLIENT["client_secret"] not in str(v._TOKEN_CACHE.keys())


@pytest.mark.parametrize("patch", [
    {"access_token": "bad token"}, {"token_type": "MAC"}, {"expires_in": 0},
    {"expires_in": True}, {"expires_in": "1800"}, {"expires_in": None},
    {"access_token": CLIENT["client_secret"]}, {"access_token": "x" * 16385},
])
async def test_invalid_token_response_never_reaches_corpus(transport, patch):
    transport[1].append((200, {**TOKEN, **patch}))
    with pytest.raises(v.VectaraError, match="invalid machine token"):
        await make().run({})
    assert len(transport[0]) == 1 and len(v._TOKEN_CACHE) == 0


@pytest.mark.parametrize("status", [302, 400, 401, 403, 429, 500])
async def test_token_failure_never_follows_redirect_retries_or_echoes_body(transport, status):
    transport[1].append((status, {"error_description": CLIENT["client_secret"]}))
    with pytest.raises(v.VectaraError) as exc:
        await make().run({})
    assert exc.value.http_status == status and CLIENT["client_secret"] not in str(exc.value)
    assert len(transport[0]) == 1


@pytest.mark.parametrize("field,value", [
    ("token_endpoint", "https://attacker.example/token"),
    ("token_endpoint", "https://auth.vectara.io/oauth2/token?other=1"),
    ("client_id", 123), ("client_secret", "{{node.secret}}"), ("corpus_key", "other/path"),
    ("api_key", "mixed-fixture-key"),
])
def test_credential_shape_rejects_endpoint_injection_and_mixed_families(field, value):
    with pytest.raises(ValueError):
        make({**CLIENT, field: value})


async def test_real_connect_requires_bound_corpus_read(monkeypatch, transport):
    cc._class_index.cache_clear()
    monkeypatch.setattr(cc, "_collect_evidence", ce.collect_evidence)
    transport[1].extend([(200, TOKEN), (403, {"error": "withheld"})])
    result = await cc.validate_for_connect(credential_type=v.OAUTH_FAMILY, credential_data=CLIENT, user_id=USER)
    assert not result.ok and result.evidence.reachable is False
    assert v.VectaraNode.connection_evidence.proves == "reachability"
    assert len(transport[0]) == 2


async def test_saved_row_rotation_uses_current_pair_and_cache_version(current, transport):
    row = current[0]
    row.update(credential_type=v.OAUTH_FAMILY, credential=deepcopy(CLIENT))
    row["credential"]["client_secret"] = "current-row-fixture-secret"
    transport[1].extend([(200, TOKEN), (200, CORPUS)])
    await make(saved=True).run({})
    assert parse_qs(transport[0][0].content.decode())["client_secret"] == ["current-row-fixture-secret"]
    row["token_version"] += 1
    transport[1].extend([(200, TOKEN), (200, CORPUS)])
    await make(saved=True).run({})
    assert len(transport[0]) == 4


@pytest.mark.parametrize("change", ["revoked", "corpus", "family"])
async def test_current_authority_change_during_token_exchange_stops_api(current, transport, change):
    row = current[0]
    row.update(credential_type=v.OAUTH_FAMILY, credential=deepcopy(CLIENT))
    def changed(request):
        if change == "revoked": row["revoked_at"] = "revoked"
        elif change == "corpus": row["credential"]["corpus_key"] = "different"
        else: row["credential_type"] = v.FAMILY
        return 200, TOKEN
    transport[1].append(changed)
    with pytest.raises(v.VectaraError):
        await make(saved=True).run({})
    assert len(transport[0]) == 1 and len(v._TOKEN_CACHE) == 0


async def test_foreign_corpus_refused_before_token_and_bearer_reflection_withheld(transport):
    with pytest.raises(v.VectaraError, match="parent binding"):
        await make(corpus_key="foreign").run({})
    assert transport[0] == []
    transport[1].extend([(200, TOKEN), (200, {**CORPUS, "description": TOKEN["access_token"]})])
    with pytest.raises(v.VectaraError, match="withheld"):
        await make().run({})


async def test_api_401_never_reissues_or_retries_write(transport):
    transport[1].extend([(200, TOKEN), (200, CORPUS), (401, {"error": "expired"})])
    with pytest.raises(v.VectaraError) as exc:
        await make(operation="update_corpus", name="fixture-name").run({})
    assert exc.value.http_status == 401
    assert [r.method for r in transport[0]] == ["POST", "GET", "PATCH"]


def test_invalid_machine_material_is_absent_from_validation_errors():
    with pytest.raises(ValueError) as exc:
        v.VectaraNodeConfig.model_validate({"config": {"operation": "get_corpus"},
            "credentials": {**CLIENT, "client_secret": "private invalid secret"}})
    assert "private invalid secret" not in str(exc.value)
    assert CLIENT["client_id"] not in str(exc.value)
