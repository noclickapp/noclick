"""Tests for the HTTP Request node — fail-loud behavior, required URL, SSRF
guard, and secret redaction.

Mocked-host tests set HTTP_NODE_ALLOW_PRIVATE_IPS so the SSRF guard doesn't try
to resolve the fake hostnames; SSRF-block tests deliberately leave it unset and
use literal private/metadata IPs (validated without DNS).

Run: pytest backend/nodes/tests/test_http_request_node.py
"""

import base64
from unittest.mock import patch

import httpx
import pytest
from pydantic import ValidationError

# Local respx-compatible shim (httpx MockTransport) — the external respx package
# isn't installed in the node-tests CI job. See _httpx_mock.py.
from nodes.tests import _httpx_mock as respx

from nodes.http_request_node import HttpRequestNode, HttpRequestNodeConfig
from utils.ssrf import SSRFError, assert_url_allowed, is_blocked_ip


def _node(operation: str, url: str, **cfg) -> HttpRequestNode:
    parsed = HttpRequestNodeConfig(config={"operation": operation, "url": url, **cfg})
    return HttpRequestNode(
        node_id="n1",
        node_type="automation-http-request",
        node_data={},
        config=parsed,
    )


@pytest.fixture
def allow_private(monkeypatch):
    monkeypatch.setenv("HTTP_NODE_ALLOW_PRIVATE_IPS", "true")


# --------------------------------------------------------------------------- #
# Required URL
# --------------------------------------------------------------------------- #


def test_url_is_required():
    with pytest.raises(ValidationError):
        HttpRequestNodeConfig(config={"operation": "send_http_get_request"})


def test_empty_url_rejected():
    with pytest.raises(ValidationError):
        HttpRequestNodeConfig(config={"operation": "send_http_get_request", "url": ""})


def test_all_methods_share_the_body_surface():
    # Every verb now carries the same request surface, so GET/DELETE can send a
    # body too (body_type defaults to "none", so nothing is sent unless asked).
    for op in (
        "send_http_get_request",
        "send_http_post_request",
        "send_http_delete_request",
    ):
        cfg = HttpRequestNodeConfig(
            config={"operation": op, "url": "https://x.com"}
        ).config
        assert hasattr(cfg, "body")
        assert cfg.body_type == "none"


# --------------------------------------------------------------------------- #
# Fail-loud behavior
# --------------------------------------------------------------------------- #


@respx.mock
async def test_4xx_fails_loudly_by_default(allow_private):
    respx.get("https://api.test/x").mock(
        return_value=httpx.Response(404, json={"error": "nope"})
    )
    node = _node("send_http_get_request", "https://api.test/x")
    with pytest.raises(ValueError, match="HTTP 404"):
        await node.execute({})


@respx.mock
async def test_never_error_returns_envelope(allow_private):
    respx.get("https://api.test/x").mock(
        return_value=httpx.Response(404, json={"error": "nope"})
    )
    node = _node("send_http_get_request", "https://api.test/x", never_error="true")
    out = await node.execute({})
    assert out["status"] == "error"
    assert out["status_code"] == 404
    assert out["response"] == {"error": "nope"}


@respx.mock
async def test_success_returns_data(allow_private):
    respx.post("https://api.test/y").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    node = _node("send_http_post_request", "https://api.test/y", body='{"a": 1}')
    out = await node.execute({})
    assert out["status"] == "success"
    assert out["response"] == {"ok": True}


@respx.mock
async def test_timeout_fails_loudly(allow_private):
    respx.get("https://api.test/slow").mock(side_effect=httpx.ConnectTimeout("slow"))
    node = _node("send_http_get_request", "https://api.test/slow")
    with pytest.raises(ValueError, match="failed"):
        await node.execute({})


@respx.mock
async def test_timeout_with_never_error_returns_envelope(allow_private):
    respx.get("https://api.test/slow").mock(side_effect=httpx.ConnectTimeout("slow"))
    node = _node("send_http_get_request", "https://api.test/slow", never_error="true")
    out = await node.execute({})
    assert out["status"] == "error"
    assert "error" in out


# --------------------------------------------------------------------------- #
# Structured headers + query params
# --------------------------------------------------------------------------- #


def test_build_headers_skips_disabled_and_unnamed():
    node = _node(
        "send_http_get_request",
        "https://api.test/x",
        headers=[
            {"key": "Accept", "value": "application/json", "enabled": True},
            {"key": "X-Off", "value": "nope", "enabled": False},
            {"key": "", "value": "skip"},
        ],
    )
    assert node.config.config.headers is not None
    assert HttpRequestNode._build_headers(node.config.config.headers) == {
        "Accept": "application/json"
    }


def test_query_params_appended_and_encoded():
    url = HttpRequestNode._apply_query_params(
        "https://api.test/v1?existing=1",
        [
            type("R", (), {"key": "page", "value": "2", "enabled": True})(),
            type("R", (), {"key": "q", "value": "a b", "enabled": True})(),
        ],
    )
    assert url == "https://api.test/v1?existing=1&page=2&q=a+b"


def test_legacy_json_object_headers_migrated():
    node = _node(
        "send_http_get_request",
        "https://api.test/x",
        headers='{"Authorization": "Bearer xyz", "Accept": "text/html"}',
    )
    rows = node.config.config.headers
    assert [(r.key, r.value, r.enabled) for r in rows] == [
        ("Authorization", "Bearer xyz", True),
        ("Accept", "text/html", True),
    ]


def test_invalid_headers_json_rejected_at_parse():
    with pytest.raises(ValidationError):
        HttpRequestNodeConfig(
            config={
                "operation": "send_http_get_request",
                "url": "https://x.com",
                "headers": "{not json}",
            }
        )


@respx.mock
async def test_json_body_sets_json_content_type(allow_private):
    route = respx.post("https://api.test/j").mock(return_value=httpx.Response(200, json={}))
    await _node(
        "send_http_post_request", "https://api.test/j", body_type="json", body='{"a": 1}'
    ).execute({})
    req = route.calls.last.request
    assert req.headers["content-type"] == "application/json"
    assert req.content == b'{"a":1}'


@respx.mock
async def test_form_urlencoded_body(allow_private):
    route = respx.post("https://api.test/f").mock(return_value=httpx.Response(200, json={}))
    await _node(
        "send_http_post_request",
        "https://api.test/f",
        body_type="form_urlencoded",
        body_form=[{"key": "a", "value": "1"}, {"key": "b", "value": "x y"}],
    ).execute({})
    req = route.calls.last.request
    assert req.headers["content-type"] == "application/x-www-form-urlencoded"
    assert req.content == b"a=1&b=x+y"


@respx.mock
async def test_raw_body_with_content_type_override(allow_private):
    route = respx.put("https://api.test/r").mock(return_value=httpx.Response(200, json={}))
    await _node(
        "send_http_put_request",
        "https://api.test/r",
        body_type="raw",
        body="<xml/>",
        content_type_override="application/xml",
    ).execute({})
    req = route.calls.last.request
    assert req.headers["content-type"] == "application/xml"
    assert req.content == b"<xml/>"


@respx.mock
async def test_get_can_send_a_body(allow_private):
    route = respx.get("https://api.test/g").mock(return_value=httpx.Response(200, json={}))
    await _node(
        "send_http_get_request", "https://api.test/g", body_type="json", body='{"q": 1}'
    ).execute({})
    assert route.calls.last.request.content == b'{"q":1}'


@respx.mock
async def test_body_type_none_sends_no_body(allow_private):
    route = respx.post("https://api.test/n").mock(return_value=httpx.Response(200, json={}))
    await _node("send_http_post_request", "https://api.test/n").execute({})
    assert route.calls.last.request.content == b""


async def test_invalid_json_body_raises(allow_private):
    node = _node(
        "send_http_post_request", "https://api.test/x", body_type="json", body="{bad}"
    )
    with pytest.raises(ValueError, match="not valid JSON"):
        await node.execute({})


def test_legacy_body_without_type_classified():
    json_cfg = HttpRequestNodeConfig(
        config={"operation": "send_http_post_request", "url": "https://x.com", "body": '{"a": 1}'}
    )
    raw_cfg = HttpRequestNodeConfig(
        config={"operation": "send_http_post_request", "url": "https://x.com", "body": "plain"}
    )
    assert json_cfg.config.body_type == "json"
    assert raw_cfg.config.body_type == "raw"


@respx.mock
async def test_structured_headers_and_params_sent(allow_private):
    route = respx.get("https://api.test/data").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    node = _node(
        "send_http_get_request",
        "https://api.test/data",
        headers=[{"key": "X-Api-Version", "value": "2", "enabled": True}],
        query_params=[{"key": "limit", "value": "5", "enabled": True}],
    )
    await node.execute({})
    sent = route.calls.last.request
    assert sent.url.params["limit"] == "5"
    assert sent.headers["X-Api-Version"] == "2"


# --------------------------------------------------------------------------- #
# SSRF guard
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "ip,blocked",
    [
        ("169.254.169.254", True),  # cloud metadata
        ("127.0.0.1", True),  # loopback
        ("10.0.0.5", True),  # RFC1918
        ("192.168.1.1", True),  # RFC1918
        ("172.16.0.1", True),  # RFC1918
        ("100.64.0.1", True),  # CGNAT
        ("0.0.0.0", True),  # unspecified
        ("::1", True),  # ipv6 loopback
        ("fd00:ec2::254", True),  # ipv6 metadata (ULA)
        ("::ffff:10.0.0.1", True),  # ipv4-mapped private
        ("8.8.8.8", False),  # public
        ("1.1.1.1", False),  # public
    ],
)
def test_is_blocked_ip(ip, blocked):
    assert is_blocked_ip(ip) is blocked


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data/",
        "http://127.0.0.1:8000/",
        "http://10.0.0.1/",
        "https://[::1]/",
        "file:///etc/passwd",
        "gopher://internal/",
        "http://localhost/",
    ],
)
async def test_assert_url_allowed_blocks(url):
    with pytest.raises(SSRFError):
        await assert_url_allowed(url)


async def test_assert_url_allowed_permits_public_literal_ip():
    await assert_url_allowed("https://8.8.8.8/")  # must not raise


async def test_node_blocks_metadata_endpoint():
    node = _node("send_http_get_request", "http://169.254.169.254/latest/meta-data/iam/")
    with pytest.raises(ValueError, match="non-public address"):
        await node.execute({})


@respx.mock
async def test_node_blocks_redirect_to_internal():
    # First hop is a public literal IP; it 302s to the metadata endpoint, which
    # the per-hop SSRF hook must block.
    respx.get("https://8.8.8.8/redir").mock(
        return_value=httpx.Response(302, headers={"location": "http://169.254.169.254/"})
    )
    node = _node("send_http_get_request", "https://8.8.8.8/redir")
    with pytest.raises(ValueError, match="non-public address"):
        await node.execute({})


# --------------------------------------------------------------------------- #
# Reliability options (timeout / retry / redirects)
# --------------------------------------------------------------------------- #


@pytest.fixture
def fast_retry(monkeypatch):
    monkeypatch.setattr(HttpRequestNode, "_retry_delay", classmethod(lambda cls, a, response=None: 0.0))


@respx.mock
async def test_retries_then_succeeds(allow_private, fast_retry):
    respx.get("https://api.test/r").mock(
        side_effect=[httpx.Response(503), httpx.Response(200, json={"ok": 1})]
    )
    out = await _node("send_http_get_request", "https://api.test/r", max_retries="2").execute({})
    assert out["status_code"] == 200


@respx.mock
async def test_retries_exhausted_fails_loud(allow_private, fast_retry):
    route = respx.get("https://api.test/r").mock(return_value=httpx.Response(503))
    with pytest.raises(ValueError, match="HTTP 503"):
        await _node("send_http_get_request", "https://api.test/r", max_retries="2").execute({})
    assert route.call_count == 3  # 1 initial + 2 retries


@respx.mock
async def test_no_retry_by_default(allow_private, fast_retry):
    route = respx.get("https://api.test/r").mock(return_value=httpx.Response(500))
    with pytest.raises(ValueError):
        await _node("send_http_get_request", "https://api.test/r").execute({})
    assert route.call_count == 1


@respx.mock
async def test_network_error_retried(allow_private, fast_retry):
    respx.get("https://api.test/n").mock(
        side_effect=[httpx.ConnectError("boom"), httpx.Response(200, json={})]
    )
    out = await _node("send_http_get_request", "https://api.test/n", max_retries="1").execute({})
    assert out["status"] == "success"


@respx.mock
async def test_follow_redirects_disabled(allow_private):
    respx.get("https://api.test/redir").mock(
        return_value=httpx.Response(302, headers={"location": "https://api.test/dest"})
    )
    out = await _node(
        "send_http_get_request",
        "https://api.test/redir",
        follow_redirects="false",
        never_error="true",
    ).execute({})
    assert out["status_code"] == 302


def test_retry_after_header_parsed():
    assert HttpRequestNode._parse_retry_after("12") == 12.0
    assert HttpRequestNode._parse_retry_after(None) is None
    assert HttpRequestNode._parse_retry_after("garbage") is None


def test_blank_numeric_options_use_defaults():
    cfg = HttpRequestNodeConfig(
        config={
            "operation": "send_http_get_request",
            "url": "https://x.com",
            "timeout_seconds": "",
            "max_retries": "",
        }
    ).config
    assert cfg.timeout_seconds == 30
    assert cfg.max_retries == 0


# --------------------------------------------------------------------------- #
# Authentication
# --------------------------------------------------------------------------- #


@pytest.fixture(autouse=True)
def _clear_oauth_cache():
    HttpRequestNode._OAUTH2_TOKEN_CACHE.clear()
    yield
    HttpRequestNode._OAUTH2_TOKEN_CACHE.clear()


def _node_with_creds(operation, url, creds, **cfg):
    parsed = HttpRequestNodeConfig(
        config={"operation": operation, "url": url, **cfg}, credentials=creds
    )
    return HttpRequestNode(
        node_id="n1", node_type="automation-http-request", node_data={}, config=parsed
    )


@pytest.mark.parametrize(
    "credentials",
    [
        {"credential_type": "http_bearer_token", "token": "secret"},
        {
            "credential_type": "http_basic_auth",
            "username": "user",
            "password": "secret",
        },
        {"credential_type": "http_api_key", "api_key": "secret"},
        {
            "credential_type": "http_oauth2_client_credentials",
            "token_url": "https://auth.test/token",
            "client_id": "client",
            "client_secret": "secret",
        },
    ],
)
def test_credentials_require_an_explicit_resource_origin(credentials):
    with pytest.raises(ValidationError, match="allowed_origin"):
        _node_with_creds(
            "send_http_get_request",
            "https://api.test/resource",
            credentials,
        )


@pytest.mark.parametrize(
    "credentials",
    [
        {
            "credential_type": "http_bearer_token",
            "allowed_origin": "https://api.test/v1",
            "token": "secret",
        },
        {
            "credential_type": "http_basic_auth",
            "allowed_origin": "http://api.test",
            "username": "user",
            "password": "secret",
        },
        {
            "credential_type": "http_api_key",
            "allowed_origin": "https://user@api.test",
            "api_key": "secret",
        },
        {
            "credential_type": "http_oauth2_client_credentials",
            "allowed_origin": "api.test",
            "token_url": "https://auth.test/token",
            "client_id": "client",
            "client_secret": "secret",
        },
    ],
)
def test_credential_resource_origin_rejects_non_origins(credentials):
    with pytest.raises(ValidationError, match="Allowed Resource Origin"):
        _node_with_creds(
            "send_http_get_request",
            "https://api.test/resource",
            credentials,
        )


def test_oauth2_token_endpoint_requires_https():
    with pytest.raises(ValidationError, match="Token URL must be.*HTTPS"):
        _node_with_creds(
            "send_http_get_request",
            "https://api.test/resource",
            {
                "credential_type": "http_oauth2_client_credentials",
                "allowed_origin": "https://api.test",
                "token_url": "http://auth.test/token",
                "client_id": "client",
                "client_secret": "secret",
            },
        )


@respx.mock
async def test_api_key_in_header(allow_private):
    route = respx.get("https://api.test/h").mock(return_value=httpx.Response(200, json={}))
    await _node_with_creds(
        "send_http_get_request",
        "https://api.test/h",
        {
            "credential_type": "http_api_key",
            "allowed_origin": "https://api.test",
            "api_key": "K",
            "header_name": "X-Custom",
            "location": "header",
        },
    ).execute({})
    assert route.calls.last.request.headers["X-Custom"] == "K"


@respx.mock
async def test_api_key_in_query_is_sent_and_redacted(allow_private):
    route = respx.get("https://api.test/q").mock(return_value=httpx.Response(200, json={}))
    out = await _node_with_creds(
        "send_http_get_request",
        "https://api.test/q",
        {
            "credential_type": "http_api_key",
            "allowed_origin": "https://api.test",
            "api_key": "SECRET",
            "header_name": "apikey",
            "location": "query",
        },
    ).execute({})
    assert route.calls.last.request.url.params["apikey"] == "SECRET"  # really sent
    assert "SECRET" not in out["url"]  # redacted in echoed output
    assert "apikey=***" in out["url"]


@respx.mock
async def test_bearer_token(allow_private):
    route = respx.get("https://api.test/b").mock(return_value=httpx.Response(200, json={}))
    await _node_with_creds(
        "send_http_get_request",
        "https://api.test/b",
        {
            "credential_type": "http_bearer_token",
            "allowed_origin": "https://api.test",
            "token": "tok",
        },
    ).execute({})
    assert route.calls.last.request.headers["Authorization"] == "Bearer tok"


@respx.mock
async def test_basic_auth(allow_private):
    route = respx.get("https://api.test/basic").mock(
        return_value=httpx.Response(200, json={})
    )
    await _node_with_creds(
        "send_http_get_request",
        "https://api.test/basic",
        {
            "credential_type": "http_basic_auth",
            "allowed_origin": "https://api.test",
            "username": "ada",
            "password": "secret",
        },
    ).execute({})
    expected = base64.b64encode(b"ada:secret").decode()
    assert route.calls.last.request.headers["Authorization"] == f"Basic {expected}"


@pytest.mark.parametrize(
    "credentials",
    [
        {
            "credential_type": "http_bearer_token",
            "allowed_origin": "https://api.test",
            "token": "secret",
        },
        {
            "credential_type": "http_basic_auth",
            "allowed_origin": "https://api.test",
            "username": "user",
            "password": "secret",
        },
        {
            "credential_type": "http_api_key",
            "allowed_origin": "https://api.test",
            "api_key": "secret",
            "location": "query",
        },
        {
            "credential_type": "http_oauth2_client_credentials",
            "allowed_origin": "https://api.test",
            "token_url": "https://auth.test/token",
            "client_id": "client",
            "client_secret": "secret",
        },
    ],
)
async def test_off_origin_target_is_rejected_before_any_auth_is_applied(credentials):
    node = _node_with_creds(
        "send_http_get_request",
        "https://attacker.example/collect",
        credentials,
    )
    with (
        patch.object(node, "_apply_query_auth", wraps=node._apply_query_auth) as query_auth,
        patch.object(node, "_apply_auth", wraps=node._apply_auth) as header_auth,
        patch.object(node, "_apply_oauth2", wraps=node._apply_oauth2) as oauth2,
        pytest.raises(SSRFError, match="outside"),
    ):
        await node.execute({})
    query_auth.assert_not_called()
    header_auth.assert_not_called()
    oauth2.assert_not_awaited()


@respx.mock
async def test_host_override_is_rejected_before_token_or_resource_request(allow_private):
    token_route = respx.post("https://auth.test/token").mock(
        return_value=httpx.Response(200, json={"access_token": "secret"})
    )
    resource_route = respx.get("https://api.test/resource").mock(
        return_value=httpx.Response(200, json={})
    )
    node = _node_with_creds(
        "send_http_get_request",
        "https://api.test/resource",
        {
            "credential_type": "http_oauth2_client_credentials",
            "allowed_origin": "https://api.test",
            "token_url": "https://auth.test/token",
            "client_id": "client",
            "client_secret": "secret",
        },
        headers=[{"key": "hOsT", "value": "attacker.test"}],
    )

    with pytest.raises(SSRFError, match="Host"):
        await node.execute({})

    assert token_route.call_count == 0
    assert resource_route.call_count == 0


@respx.mock
async def test_credentialed_request_cannot_disable_tls_verification(allow_private):
    resource_route = respx.get("https://api.test/resource").mock(
        return_value=httpx.Response(200, json={})
    )
    node = _node_with_creds(
        "send_http_get_request",
        "https://api.test/resource",
        {
            "credential_type": "http_bearer_token",
            "allowed_origin": "https://api.test",
            "token": "secret",
        },
        verify_ssl="false",
    )

    with pytest.raises(SSRFError, match="verification cannot be disabled"):
        await node.execute({})

    assert resource_route.call_count == 0


@respx.mock
async def test_credentialed_redirect_cannot_leave_allowed_origin(allow_private):
    first = respx.get("https://api.test/start").mock(
        return_value=httpx.Response(
            302,
            headers={"location": "https://attacker.test/collect"},
        )
    )
    attacker = respx.get("https://attacker.test/collect").mock(
        return_value=httpx.Response(200, json={})
    )
    node = _node_with_creds(
        "send_http_get_request",
        "https://api.test/start",
        {
            "credential_type": "http_api_key",
            "allowed_origin": "https://api.test",
            "api_key": "secret",
            "header_name": "X-Custom-Secret",
        },
    )

    with pytest.raises(SSRFError, match="outside"):
        await node.execute({})

    assert first.call_count == 1
    assert first.calls.last.request.headers["X-Custom-Secret"] == "secret"
    assert attacker.call_count == 0


@respx.mock
async def test_credentialed_same_origin_redirect_succeeds(allow_private):
    first = respx.get("https://api.test/start").mock(
        return_value=httpx.Response(302, headers={"location": "/finish"})
    )
    final = respx.get("https://api.test/finish").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    output = await _node_with_creds(
        "send_http_get_request",
        "https://api.test/start",
        {
            "credential_type": "http_api_key",
            "allowed_origin": "https://api.test/",
            "api_key": "secret",
            "header_name": "X-Custom-Secret",
        },
    ).execute({})

    assert output["response"] == {"ok": True}
    assert first.call_count == 1
    assert final.call_count == 1
    assert final.calls.last.request.headers["X-Custom-Secret"] == "secret"


@respx.mock
async def test_oauth2_client_credentials_mints_bearer(allow_private):
    token_route = respx.post("https://auth.test/token").mock(
        return_value=httpx.Response(200, json={"access_token": "ABC", "expires_in": 3600})
    )
    api_route = respx.get("https://api.test/o").mock(return_value=httpx.Response(200, json={}))
    await _node_with_creds(
        "send_http_get_request",
        "https://api.test/o",
        {
            "credential_type": "http_oauth2_client_credentials",
            "allowed_origin": "https://api.test",
            "token_url": "https://auth.test/token",
            "client_id": "cid",
            "client_secret": "csec",
            "scope": "read",
        },
    ).execute({})
    assert b"grant_type=client_credentials" in token_route.calls.last.request.content
    assert api_route.calls.last.request.headers["Authorization"] == "Bearer ABC"


@respx.mock
async def test_oauth2_token_failure_raises(allow_private):
    respx.post("https://auth.test/token").mock(return_value=httpx.Response(401, text="bad"))
    node = _node_with_creds(
        "send_http_get_request",
        "https://api.test/o",
        {
            "credential_type": "http_oauth2_client_credentials",
            "allowed_origin": "https://api.test",
            "token_url": "https://auth.test/token",
            "client_id": "x",
            "client_secret": "y",
        },
    )
    with pytest.raises(ValueError, match="OAuth2 token request failed"):
        await node.execute({})


@respx.mock
async def test_oauth2_token_cached_across_executes(allow_private):
    token_route = respx.post("https://auth.test/token").mock(
        return_value=httpx.Response(200, json={"access_token": "ABC", "expires_in": 3600})
    )
    respx.get("https://api.test/o").mock(return_value=httpx.Response(200, json={}))
    creds = {
        "credential_type": "http_oauth2_client_credentials",
        "allowed_origin": "https://api.test",
        "token_url": "https://auth.test/token",
        "client_id": "cid",
        "client_secret": "csec",
    }
    await _node_with_creds("send_http_get_request", "https://api.test/o", creds).execute({})
    await _node_with_creds("send_http_get_request", "https://api.test/o", creds).execute({})
    assert token_route.call_count == 1  # token reused from cache
    cache_key = next(iter(HttpRequestNode._OAUTH2_TOKEN_CACHE.keys()))
    assert len(cache_key) == 64
    assert creds["client_secret"] not in cache_key


@respx.mock
async def test_oauth2_same_public_fields_with_different_secret_cannot_reuse_bearer(
    allow_private,
):
    token_route = respx.post("https://auth.test/token").mock(
        side_effect=[
            httpx.Response(200, json={"access_token": "FIRST", "expires_in": 3600}),
            httpx.Response(200, json={"access_token": "SECOND", "expires_in": 3600}),
        ]
    )
    api_route = respx.get("https://api.test/o").mock(
        return_value=httpx.Response(200, json={})
    )
    common = {
        "credential_type": "http_oauth2_client_credentials",
        "allowed_origin": "https://api.test",
        "token_url": "https://auth.test/token",
        "client_id": "same-client",
        "scope": "read",
        "audience": "tenant-a",
    }

    await _node_with_creds(
        "send_http_get_request",
        "https://api.test/o",
        {**common, "client_secret": "first-secret"},
    ).execute({})
    await _node_with_creds(
        "send_http_get_request",
        "https://api.test/o",
        {**common, "client_secret": "second-secret"},
    ).execute({})

    assert token_route.call_count == 2
    assert api_route.calls[0].request.headers["Authorization"] == "Bearer FIRST"
    assert api_route.calls[1].request.headers["Authorization"] == "Bearer SECOND"


@respx.mock
async def test_oauth2_expired_cache_entry_refreshes(allow_private):
    token_route = respx.post("https://auth.test/token").mock(
        side_effect=[
            httpx.Response(200, json={"access_token": "SHORT", "expires_in": 120}),
            httpx.Response(200, json={"access_token": "FRESH", "expires_in": 120}),
        ]
    )
    api_route = respx.get("https://api.test/o").mock(
        return_value=httpx.Response(200, json={})
    )
    creds = {
        "credential_type": "http_oauth2_client_credentials",
        "allowed_origin": "https://api.test",
        "token_url": "https://auth.test/token",
        "client_id": "cid",
        "client_secret": "csec",
    }
    now = [1000.0]

    with patch("nodes.http_request_node.time.monotonic", side_effect=lambda: now[0]):
        await _node_with_creds(
            "send_http_get_request", "https://api.test/o", creds
        ).execute({})
        now[0] = 1060.0
        await _node_with_creds(
            "send_http_get_request", "https://api.test/o", creds
        ).execute({})

    assert token_route.call_count == 2
    assert api_route.calls[0].request.headers["Authorization"] == "Bearer SHORT"
    assert api_route.calls[1].request.headers["Authorization"] == "Bearer FRESH"


# --------------------------------------------------------------------------- #
# Response handling
# --------------------------------------------------------------------------- #


@respx.mock
async def test_response_format_text_skips_json_parse(allow_private):
    respx.get("https://api.test/t").mock(return_value=httpx.Response(200, json={"a": 1}))
    out = await _node(
        "send_http_get_request", "https://api.test/t", response_format="text"
    ).execute({})
    assert out["response"] == '{"a":1}'  # string, not parsed


@respx.mock
async def test_response_format_json_strict_fails_loud(allow_private):
    respx.get("https://api.test/x").mock(return_value=httpx.Response(200, text="not json"))
    node = _node("send_http_get_request", "https://api.test/x", response_format="json")
    with pytest.raises(ValueError, match="not valid JSON"):
        await node.execute({})


@respx.mock
async def test_response_format_binary_forces_base64(allow_private):
    respx.get("https://api.test/i").mock(
        return_value=httpx.Response(200, content=b"\x89PNG", headers={"content-type": "text/plain"})
    )
    out = await _node(
        "send_http_get_request", "https://api.test/i", response_format="binary"
    ).execute({})
    assert out["is_base64"] is True


@respx.mock
async def test_full_response_false_returns_body_only(allow_private):
    respx.get("https://api.test/b").mock(
        return_value=httpx.Response(200, json={"name": "Ada", "id": 7})
    )
    out = await _node(
        "send_http_get_request", "https://api.test/b", full_response="false"
    ).execute({})
    assert out == {"name": "Ada", "id": 7}  # no envelope keys


@respx.mock
async def test_full_response_false_wraps_non_dict(allow_private):
    respx.get("https://api.test/s").mock(return_value=httpx.Response(200, text="hello"))
    out = await _node(
        "send_http_get_request", "https://api.test/s", full_response="false"
    ).execute({})
    assert out == {"data": "hello"}


@respx.mock
async def test_oversized_response_fails_loud(allow_private):
    big = "x" * (HttpRequestNode._MAX_INLINE_BYTES + 1024)
    respx.get("https://api.test/big").mock(return_value=httpx.Response(200, text=big))
    node = _node("send_http_get_request", "https://api.test/big")
    with pytest.raises(ValueError, match="too large"):
        await node.execute({})


@respx.mock
async def test_oversized_response_never_error_returns_envelope(allow_private):
    big = "x" * (HttpRequestNode._MAX_INLINE_BYTES + 1024)
    respx.get("https://api.test/big").mock(return_value=httpx.Response(200, text=big))
    out = await _node(
        "send_http_get_request", "https://api.test/big", never_error="true"
    ).execute({})
    assert out["status"] == "error"
    assert "too large" in out["error"]


# --------------------------------------------------------------------------- #
# Secret redaction
# --------------------------------------------------------------------------- #


def test_redact_url_strips_userinfo_and_secrets():
    redacted = HttpRequestNode._redact_url(
        "https://user:pass@api.x.com/v1?api_key=SECRET&q=hello&token=abc"
    )
    assert "user:pass" not in redacted
    assert "SECRET" not in redacted
    assert "abc" not in redacted
    assert "q=hello" in redacted  # non-secret params preserved


# --------------------------------------------------------------------------- #
# Binary responses → R2 resource
# --------------------------------------------------------------------------- #


def _node_with_ctx(operation, url, **cfg):
    parsed = HttpRequestNodeConfig(config={"operation": operation, "url": url, **cfg})
    return HttpRequestNode(
        node_id="n1",
        node_type="automation-http-request",
        node_data={},
        config=parsed,
        workflow_id="wf-1",
        user_id="user-1",
    )


@respx.mock
async def test_binary_response_stored_as_resource(allow_private, monkeypatch):
    captured = {}

    async def fake_create(**kwargs):
        captured.update(kwargs)
        return {
            "resource_id": "res-123",
            "name": "clip.mp4",
            "mime_type": "video/mp4",
            "size_bytes": len(kwargs["body"]),
            "storage_ref": "user-1/wf-1/res-123/clip.mp4",
            "download_url": "https://assets.test/clip.mp4",
        }

    monkeypatch.setattr("utils.resource_store.create_resource_from_bytes", fake_create)
    respx.get("https://api.test/clip.mp4").mock(
        return_value=httpx.Response(200, content=b"VIDEOBYTES", headers={"content-type": "video/mp4"})
    )
    out = await _node_with_ctx("send_http_get_request", "https://api.test/clip.mp4").execute({})
    assert out["is_file"] is True
    assert out["is_base64"] is False
    assert out["response"]["url"] == "https://assets.test/clip.mp4"  # public URL, no resource_id
    assert out["response"]["mime_type"] == "video/mp4"
    assert "resource_id" not in out["response"]
    # filename derived from the URL path
    assert captured["filename"] == "clip.mp4"
    assert captured["body"] == b"VIDEOBYTES"


@respx.mock
async def test_binary_without_workflow_context_falls_back_to_base64(allow_private):
    respx.get("https://api.test/i.png").mock(
        return_value=httpx.Response(200, content=b"\x89PNG", headers={"content-type": "image/png"})
    )
    # _node has no workflow_id/user_id → no place to store a resource.
    out = await _node("send_http_get_request", "https://api.test/i.png").execute({})
    assert out["is_file"] is False
    assert out["is_base64"] is True
    assert out["response"] == base64.b64encode(b"\x89PNG").decode()


@respx.mock
async def test_json_response_is_not_a_resource(allow_private):
    respx.get("https://api.test/j").mock(return_value=httpx.Response(200, json={"a": 1}))
    out = await _node_with_ctx("send_http_get_request", "https://api.test/j").execute({})
    assert out["is_file"] is False
    assert out["response"] == {"a": 1}
