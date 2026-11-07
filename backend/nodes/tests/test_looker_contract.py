"""Looker API 4.0 source-contract regressions using synthetic HTTP responses.

These tests exercise the registered node, real connection-evidence collector, and
result parser without an instance, account, token, or network request.
"""

import httpx
import pytest
from unittest.mock import AsyncMock, patch

from nodes.core.binary_output import BinaryOutput
from nodes.core.connection_evidence import collect_evidence
from nodes.core.registry import NODE_REGISTRY
from nodes.core.poll_trigger import poll_scope, _scope_of_op_config
from nodes.looker_node import _looker_request, _normalize_base_url, LookerNode


CRED = {
    "instance_url": "https://acme.cloud.looker.com:19999/proxy/api/4.0",
    "client_id": "synthetic-id",
    "client_secret": "synthetic-secret",
}


def mock_client(handler):
    def factory(**kwargs):
        assert kwargs["follow_redirects"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)
    return factory


def two_step(data_status=200, data_body=None, data_type="application/json", login_status=200):
    seen = []

    def handler(request):
        seen.append(request)
        if request.url.path.endswith("/login"):
            assert request.method == "POST"
            assert b"client_id=synthetic-id" in request.content
            assert b"client_secret=synthetic-secret" in request.content
            assert "synthetic-secret" not in str(request.url)
            return httpx.Response(
                login_status, json={"access_token": "synthetic-token"}
                if login_status == 200 else {"message": "provider-reflection-sentinel"},
                headers={"location": "https://elsewhere.example/"} if login_status == 302 else {},
            )
        assert request.headers["authorization"] == "token synthetic-token"
        return httpx.Response(
            data_status, content=data_body if data_body is not None else b'{"id":5,"email":"ada@example.com"}',
            headers={"content-type": data_type, "location": "https://elsewhere.example/"}
            if data_status == 302 else {"content-type": data_type},
        )
    return handler, seen


@pytest.mark.parametrize("raw,want", [
    ("acme.cloud.looker.com:19999", "https://acme.cloud.looker.com:19999/api/4.0"),
    ("https://acme.example.com:443/proxy", "https://acme.example.com:443/proxy/api/4.0"),
    ("https://acme.example.com/proxy/api/4.0", "https://acme.example.com/proxy/api/4.0"),
])
def test_instance_url_keeps_host_port_and_proxy_path(raw, want):
    assert _normalize_base_url(raw) == want


@pytest.mark.parametrize("raw", [
    "http://acme.example.com", "https://user:pass@acme.example.com",
    "https://acme.example.com/api/3.1", "https://acme.example.com/path?secret=x",
    "https://acme.example.com/#fragment", "https://127.0.0.1.evil\\@acme.example.com",
    "https://acme.example.com/%2f%2fevil", "https://acme.example.com/proxy/../other",
])
def test_rejected_instance_never_opens_client(raw):
    with patch("nodes.looker_node.guarded_async_client") as client:
        with pytest.raises(ValueError):
            _normalize_base_url(raw)
        client.assert_not_called()


@pytest.mark.asyncio
async def test_current_user_real_collector_proves_narrow_identity():
    handler, seen = two_step()
    with patch("nodes.looker_node.guarded_async_client", side_effect=mock_client(handler)):
        evidence = await collect_evidence(
            node_type="automation-looker", user_id="synthetic-user", credential_data=CRED,
        )
    assert evidence.reachable is True
    assert evidence.account_label == "ada@example.com"
    assert len(seen) == 2
    assert seen[1].url.params["fields"] == "id,first_name,last_name,email,display_name"
    assert NODE_REGISTRY["automation-looker"] is LookerNode


@pytest.mark.asyncio
async def test_user_proxy_extra_credential_fields_are_not_returned():
    handler, _ = two_step(data_body=(
        b'{"id":5,"email":"ada@example.com","credentials_email":'
        b'{"password_reset_url":"provider-reflection-sentinel"}}'
    ))
    with patch("nodes.looker_node.guarded_async_client", side_effect=mock_client(handler)):
        result = await _looker_request(CRED, "GET", "/user", action_name="get_current_user")
    assert result["status"] == "success"
    assert result["data"] == {"id": 5, "email": "ada@example.com"}
    assert "provider-reflection-sentinel" not in str(result)


@pytest.mark.asyncio
async def test_registered_lookup_dispatcher_preserves_context_and_search():
    from nodes.core.run_op import run_node_lookup

    with patch("nodes.core.run_op.resolve_operation_credential", return_value=CRED), \
         patch("utils.credential_approval.admit_lookup", return_value=None), \
         patch("nodes.looker_node._looker_request", return_value={
             "status": "success", "data": {"explores": [
                 {"name": "orders", "label": "Orders"},
                 {"name": "users", "label": "Users"},
             ]},
         }) as request:
        result = await run_node_lookup(
            node_type="automation-looker", field_name="view", user_id="synthetic-user",
            credential_id="synthetic-credential", context={"model": "ecommerce"},
            search=" orders ",
        )
    assert result == {"options": [{"label": "Orders", "value": "orders"}], "next_page_token": None}
    assert request.call_args.args[2] == "/lookml_models/ecommerce"


@pytest.mark.asyncio
async def test_recognized_picker_without_credential_has_actionable_dispatcher_error():
    from nodes.core.run_op import run_node_lookup

    assert await LookerNode.load_field_options("not_a_looker_picker", credential_data=None) == []
    with pytest.raises(ValueError, match="Connect a Looker account"):
        await LookerNode.load_field_options("look_id", credential_data=None)
    with pytest.raises(ValueError, match="connect one on the workflow"):
        await run_node_lookup(
            node_type="automation-looker", field_name="look_id", user_id="synthetic-user",
            credential_id=None,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [b"{}", b"[]", b"not-json"])
async def test_malformed_identity_does_not_prove_connection(body):
    handler, _ = two_step(data_body=body)
    with patch("nodes.looker_node.guarded_async_client", side_effect=mock_client(handler)):
        evidence = await collect_evidence(
            node_type="automation-looker", user_id="synthetic-user", credential_data=CRED,
        )
    assert evidence.reachable is None


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [200, 202, 204])
async def test_empty_current_user_never_proves_connection(status):
    handler, _ = two_step(data_status=status, data_body=b"")
    with patch("nodes.looker_node.guarded_async_client", side_effect=mock_client(handler)):
        evidence = await collect_evidence(
            node_type="automation-looker", user_id="synthetic-user", credential_data=CRED,
        )
    assert evidence.reachable is None
    assert evidence.account_label is None


@pytest.mark.asyncio
@pytest.mark.parametrize("login_status,data_status", [(401, 200), (200, 403)])
async def test_rejected_identity_is_reported_by_real_collector(login_status, data_status):
    handler, _ = two_step(login_status=login_status, data_status=data_status)
    with patch("nodes.looker_node.guarded_async_client", side_effect=mock_client(handler)):
        evidence = await collect_evidence(
            node_type="automation-looker", user_id="synthetic-user", credential_data=CRED,
        )
    assert evidence.reachable is False
    assert "provider-reflection-sentinel" not in str(evidence)


@pytest.mark.asyncio
async def test_login_rejection_and_redirect_do_not_reflect_or_follow():
    for status in (401, 302):
        handler, seen = two_step(login_status=status)
        with patch("nodes.looker_node.guarded_async_client", side_effect=mock_client(handler)):
            result = await _looker_request(CRED, "GET", "/user", action_name="get_current_user")
        assert result["status"] == "error"
        assert result["status_code"] == status
        assert "provider-reflection-sentinel" not in str(result)
        assert len(seen) == 1


@pytest.mark.asyncio
async def test_data_redirect_and_error_are_bounded():
    for status in (302, 403):
        handler, seen = two_step(data_status=status, data_body=b"provider-reflection-sentinel")
        with patch("nodes.looker_node.guarded_async_client", side_effect=mock_client(handler)):
            result = await _looker_request(CRED, "GET", "/looks/1", action_name="get_look")
        assert result["status"] == "error"
        assert result["status_code"] == status
        assert "provider-reflection-sentinel" not in str(result)
        assert len(seen) == 2


@pytest.mark.asyncio
async def test_transport_exception_does_not_reflect_secret():
    with patch("nodes.looker_node.guarded_async_client", side_effect=RuntimeError("synthetic-secret provider-reflection-sentinel")):
        result = await _looker_request(CRED, "GET", "/looks/1", action_name="get_look")
    assert result["status"] == "error"
    assert "synthetic-secret" not in str(result)
    assert "provider-reflection-sentinel" not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("fmt,mime,body", [
    ("csv", "text/csv", b"name,value\nAda,5\n"),
    ("html", "text/html", b"<table><tr><td>5</td></tr></table>"),
    ("sql", "text/plain", b"select 5"),
])
async def test_documented_text_formats_preserved(fmt, mime, body):
    handler, _ = two_step(data_body=body, data_type=mime)
    with patch("nodes.looker_node.guarded_async_client", side_effect=mock_client(handler)):
        result = await _looker_request(CRED, "GET", "/looks/1/run/" + fmt,
                                       action_name="run_look", result_format=fmt)
    assert result["status"] == "success"
    assert result["data"] == {"raw": body.decode()}


@pytest.mark.asyncio
@pytest.mark.parametrize("fmt", ["csv", "txt", "html", "md", "sql"])
async def test_text_format_rejects_json_error_envelope(fmt):
    handler, _ = two_step(
        data_body=b'{"message":"provider-reflection-sentinel"}', data_type="application/json"
    )
    with patch("nodes.looker_node.guarded_async_client", side_effect=mock_client(handler)):
        result = await _looker_request(
            CRED, "GET", f"/looks/1/run/{fmt}", action_name="run_look", result_format=fmt
        )
    assert result["status"] == "error"
    assert "provider-reflection-sentinel" not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("action,fmt,mime,body", [
    ("run_look", "xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", b"PK synthetic"),
    ("get_render_task", None, "application/pdf", b"%PDF-1.7 synthetic"),
    ("get_query_task_results", None, "application/octet-stream", b"PK async synthetic"),
])
async def test_binary_results_use_shared_resource_marker(action, fmt, mime, body):
    handler, _ = two_step(data_body=body, data_type=mime)
    with patch("nodes.looker_node.guarded_async_client", side_effect=mock_client(handler)):
        result = await _looker_request(CRED, "GET", "/render_tasks/1/results",
                                       action_name=action, result_format=fmt)
    assert result["status"] == "success"
    assert isinstance(result["data"], BinaryOutput)
    assert result["data"].data == body
    assert result["data"].content_type == mime


@pytest.mark.asyncio
@pytest.mark.parametrize("action,fmt,mime", [
    ("get_render_task", None, "text/plain"),
    ("get_render_task", None, ""),
    ("run_look", "xlsx", "application/json"),
])
async def test_binary_result_rejects_mislabelled_text_or_json(action, fmt, mime):
    handler, _ = two_step(data_body=b"provider-reflection-sentinel", data_type=mime)
    with patch("nodes.looker_node.guarded_async_client", side_effect=mock_client(handler)):
        result = await _looker_request(
            CRED, "GET", "/render_tasks/1/results", action_name=action, result_format=fmt
        )
    assert result["status"] == "error"
    assert "provider-reflection-sentinel" not in str(result)


@pytest.mark.asyncio
async def test_async_pending_and_empty_delete_are_distinct():
    for status, expected in ((202, "pending"), (204, "success")):
        handler, _ = two_step(data_status=status, data_body=b"")
        with patch("nodes.looker_node.guarded_async_client", side_effect=mock_client(handler)):
            result = await _looker_request(CRED, "GET", "/query_tasks/1/results",
                                           action_name="get_query_task_results")
        assert result["status"] == expected
        if status == 204:
            assert result["data"] == {"success": True}


@pytest.mark.asyncio
async def test_render_pending_keeps_only_bounded_retry_after():
    def handler(request):
        if request.url.path.endswith("/login"):
            return httpx.Response(200, json={"access_token": "synthetic-token"})
        return httpx.Response(202, headers={
            "retry-after": "15", "location": "provider-reflection-sentinel",
        })

    with patch("nodes.looker_node.guarded_async_client", side_effect=mock_client(handler)):
        result = await _looker_request(
            CRED, "GET", "/render_tasks/1/results", action_name="get_render_task"
        )
    assert result["status"] == "pending"
    assert result["retry_after_seconds"] == 15
    assert "provider-reflection-sentinel" not in str(result)


@pytest.mark.asyncio
async def test_json_detail_sql_error_inside_200_is_not_success_or_reflected():
    handler, _ = two_step(data_body=(
        b'{"data":[],"errors":[{"message":"provider-reflection-sentinel"}]}'
    ))
    with patch("nodes.looker_node.guarded_async_client", side_effect=mock_client(handler)):
        result = await _looker_request(
            CRED, "GET", "/query_tasks/1/results", action_name="get_query_task_results"
        )
    assert result["status"] == "error"
    assert result["error"] == "Looker query returned SQL errors"
    assert "provider-reflection-sentinel" not in str(result)


@pytest.mark.asyncio
async def test_malformed_poll_never_writes_baseline():
    from nodes.looker_node import LookerNodeConfig, LookerOnLookResultsConfig, LookerApiKeyCredential
    credentials = LookerApiKeyCredential(**CRED)
    node = LookerNode(
        node_id="look-1", node_type="automation-looker", node_data={},
        config=LookerNodeConfig(config=LookerOnLookResultsConfig(look_id="7"), credentials=credentials),
        sio=None, sid=None, workflow_id="wf-1", user_id="user-1",
    )
    for body in (b"{}", b'[null,{"id":1}]'):
        handler, _ = two_step(data_body=body)
        with patch("nodes.looker_node.guarded_async_client", side_effect=mock_client(handler)), \
             patch.object(node, "_update_node_state") as update:
            result = await node.execute({})
        assert result["status"] == "error"
        update.assert_not_called()


@pytest.mark.asyncio
async def test_trigger_scope_rotates_on_selected_look_change():
    from nodes.looker_node import LookerNodeConfig, LookerOnLookResultsConfig, LookerApiKeyCredential

    operation = LookerOnLookResultsConfig(look_id="7", cursor_field="id")
    config = LookerNodeConfig(config=operation, credentials=LookerApiKeyCredential(**CRED))
    node_data = {
        "config": {"operation": "on_look_results", "look_id": "7", "cursor_field": "id",
                   "credentialIds": {"looker_api_key": "tenant-a"}},
        "credential_id": "tenant-a",
    }
    node = LookerNode(
        node_id="look-1", node_type="automation-looker", node_data=node_data,
        config=config, sio=None, sid=None, workflow_id="wf-1", user_id="user-1",
    )
    state = {}

    async def update(mutator, *, max_retries=4, skip_result=None):
        new_state, result = mutator(dict(state))
        if new_state is not None:
            state.clear()
            state.update(new_state)
        return result

    node._update_node_state = update
    assert _scope_of_op_config(operation) == poll_scope(LookerNode, node_data["config"])
    with patch("nodes.looker_node._looker_request", new_callable=AsyncMock) as request:
        request.return_value = {"status": "success", "data": [{"id": 1}], "status_code": 200}
        assert (await node._on_look_results(operation, CRED))["new_count"] == 0
        scope_a = state["scope"]
        request.return_value["data"] = [{"id": 1}, {"id": 2}]
        assert (await node._on_look_results(operation, CRED))["new_count"] == 1

        tenant_b_data = {
            "config": {**node_data["config"], "look_id": "8"},
            "credential_id": "tenant-b",
        }
        tenant_b_node = LookerNode(
            node_id="look-1", node_type="automation-looker", node_data=tenant_b_data,
            config=LookerNodeConfig(
                config=LookerOnLookResultsConfig(look_id="8", cursor_field="id"),
                credentials=LookerApiKeyCredential(**CRED),
            ), sio=None, sid=None, workflow_id="wf-1", user_id="user-1",
        )
        tenant_b_node._update_node_state = update
        request.return_value["data"] = [{"id": 1}, {"id": 2}]
        assert (await tenant_b_node._on_look_results(tenant_b_node.config.config, CRED))["new_count"] == 0
        assert state["scope"] != scope_a
        assert state["scope"] == poll_scope(LookerNode, tenant_b_data["config"])
        request.return_value["data"] = [{"id": 1}, {"id": 2}, {"id": 3}]
        assert (await tenant_b_node._on_look_results(tenant_b_node.config.config, CRED))["items"] == [{"id": 3}]


@pytest.mark.asyncio
async def test_arm_time_look_scope_baselines_once_without_consuming_next_row():
    from nodes.looker_node import LookerNodeConfig, LookerOnLookResultsConfig, LookerApiKeyCredential

    operation = LookerOnLookResultsConfig(look_id="8", cursor_field="id")
    context_a = {
        "operation": "on_look_results", "look_id": "7", "cursor_field": "id",
        "credentialIds": {"looker_api_key": "tenant-a"},
    }
    context_b = {**context_a, "look_id": "8"}
    state = {"seen_ids": ["1"], "scope": poll_scope(LookerNode, context_a)}
    node = LookerNode(
        node_id="look-1", node_type="automation-looker",
        node_data={"config": context_b, "credential_id": "tenant-b"},
        config=LookerNodeConfig(
            config=operation, credentials=LookerApiKeyCredential(**CRED),
        ),
        sio=None, sid=None, workflow_id="wf-1", user_id="user-1",
    )

    async def update(mutator, *, max_retries=4, skip_result=None):
        new_state, result = mutator(dict(state))
        if new_state is not None:
            state.clear()
            state.update(new_state)
        return result

    async def run(_):
        return await node._on_look_results(operation, CRED)

    node._update_node_state = update
    node.run = run
    assert poll_scope(LookerNode, context_b) == _scope_of_op_config(operation)
    no_id_context = {**context_b, "credentialIds": {}}
    no_id_node = LookerNode(
        node_id="look-1", node_type="automation-looker",
        node_data={"config": no_id_context},
        config=node._config, sio=None, sid=None, workflow_id="wf-1", user_id="user-1",
    )
    assert _scope_of_op_config(no_id_node.config.config) == poll_scope(LookerNode, no_id_context)

    async def fetchrow(*_):
        return {"state": dict(state)}

    with patch("utils.database_pool.get_native_pool") as native, \
         patch("nodes.core.registry.NodeFactory.create_node", return_value=node) as factory, \
         patch("nodes.core.run_op.resolve_operation_credential", new_callable=AsyncMock,
               return_value=CRED), \
         patch("nodes.looker_node._looker_request", new_callable=AsyncMock) as request:
        native.return_value.fetchrow = fetchrow
        request.return_value = {
            "status": "success", "data": [{"id": 1}, {"id": 2}], "status_code": 200,
        }
        await LookerNode._establish_poll_baseline(
            user_id="user-1", workflow_id="wf-1", node_id="look-1",
            context=context_b, credential_ids=context_b["credentialIds"], pool=None,
        )
        assert factory.call_count == 1
        assert request.await_count == 1
        assert state == {"seen_ids": ["1", "2"], "scope": poll_scope(LookerNode, context_b)}

        request.return_value["data"] = [{"id": 1}, {"id": 2}, {"id": 3}]
        await LookerNode._establish_poll_baseline(
            user_id="user-1", workflow_id="wf-1", node_id="look-1",
            context=context_b, credential_ids=context_b["credentialIds"], pool=None,
        )
        assert factory.call_count == 1
        assert request.await_count == 1
        node._poll_baseline_only = False
        assert (await node._on_look_results(operation, CRED))["items"] == [{"id": 3}]


@pytest.mark.asyncio
async def test_legacy_unscoped_looker_state_keeps_shared_adoption_semantics():
    from nodes.looker_node import LookerNodeConfig, LookerOnLookResultsConfig, LookerApiKeyCredential

    operation = LookerOnLookResultsConfig(look_id="7", cursor_field="id")
    node = LookerNode(
        node_id="look-1", node_type="automation-looker",
        node_data={"config": {"operation": "on_look_results", "look_id": "7", "cursor_field": "id"},
                   "credential_id": "tenant-b"},
        config=LookerNodeConfig(
            config=operation, credentials=LookerApiKeyCredential(**CRED),
        ),
        sio=None, sid=None, workflow_id="wf-1", user_id="user-1",
    )
    state = {"seen_ids": ["1"]}

    async def update(mutator, *, max_retries=4, skip_result=None):
        new_state, result = mutator(dict(state))
        if new_state is not None:
            state.clear()
            state.update(new_state)
        return result

    node._update_node_state = update
    with patch("nodes.looker_node._looker_request", new_callable=AsyncMock,
               return_value={"status": "success", "data": [{"id": 1}, {"id": 2}]}):
        result = await node._on_look_results(operation, CRED)
    assert result["items"] == [{"id": 2}]
    assert state["scope"] == _scope_of_op_config(operation)
