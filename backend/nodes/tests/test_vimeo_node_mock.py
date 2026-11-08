"""Offline request contract checks through the real node factory."""
import httpx
import pytest
from nodes import vimeo_node as native
from nodes.core.registry import NodeFactory

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="vimeo-test", node_type="automation-vimeo", node_data={
        "config": config, "credentials": {"credential_type": "vimeo_token", "access_token": "synthetic-vimeo-token"}})


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", native.ROUTES)
async def test_vimeo_exact_request_and_response(monkeypatch, operation):
    route = native.ROUTES[operation]
    config = {"operation": operation}
    import re
    for key in re.findall(r"{(.*?)}", route["path"]):
        config[key] = "12345"
    config.update({key: "Example value" for key in route["body"]})
    requests = []
    status = route["statuses"][0]
    data = {"data": [], "paging": {"next": None}} if operation.startswith("list_") else {"uri": "/users/12345", "name": "Example"}
    def handler(request):
        requests.append(request)
        return httpx.Response(status, **({} if status == 204 else {"json": data}))
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    result = await node(config).execute({})
    assert result["status"] == "success"
    assert len(requests) == 1
    req = requests[0]
    assert req.method == route["method"]
    assert req.url.host == "api.vimeo.com"
    assert req.url.path == re.sub(r"{.*?}", "12345", route["path"])
    assert req.headers["authorization"] == "Bearer synthetic-vimeo-token"
    if route["body"]:
        import json
        assert json.loads(req.content) == {key: config[key] for key in route["body"]}
        assert req.headers["content-type"] == route["content_type"]
    if operation.startswith("list_"):
        assert dict(req.url.params) == {"page": "1", "per_page": "25"}
    if status == 204:
        assert result["acknowledged"] is True
    else:
        assert result["data"] == data


@pytest.mark.asyncio
async def test_vimeo_rejection_is_not_evidence_and_redacts_token(monkeypatch):
    def client(**kwargs):
        return httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(401, json={"error": "Rejected synthetic-vimeo-token"})), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    result = await node({"operation": "get_account"}).execute({})
    assert result == {"status": "error", "http_status": 401, "error": "Rejected [redacted]"}


def test_vimeo_path_injection_rejected():
    with pytest.raises(Exception):
        node({"operation": "get_video", "video_id": "../me"})
