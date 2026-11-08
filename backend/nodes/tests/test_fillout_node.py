"""Contract checks for Fillout Forms and Zite Database requests."""

from contextlib import contextmanager
from unittest.mock import Mock, patch

import httpx
import pytest

from nodes.fillout_node import (
    CreateDatabase, CreateRecord, CreateSubmissions, DeleteFormWebhook,
    FilloutApiKeyCredential, FilloutNode, FilloutNodeConfig,
    ListForms, ListRecords, ListSubmissions, UpdateField, _request,
)


FORMS = "https://api.zite.com/v1/api"
DATABASE = "https://tables.zite.com/api/v1"


class Route:
    def __init__(self):
        self.response = None
        self.calls = []

    def mock(self, *, return_value):
        self.response = return_value
        return self


class MockApi:
    def __init__(self):
        self.routes = {}

    def _route(self, method, url):
        route = Route()
        self.routes[(method, url)] = route
        return route

    def get(self, url):
        return self._route("GET", url)

    def post(self, url):
        return self._route("POST", url)

    def patch(self, url):
        return self._route("PATCH", url)


@contextmanager
def mock_api():
    api = MockApi()

    def handler(request):
        route = api.routes[(request.method, str(request.url.copy_with(query=None)))]
        route.calls.append(request)
        return route.response

    real_client = httpx.AsyncClient
    with patch("nodes.fillout_node.httpx.AsyncClient", side_effect=lambda **kwargs: real_client(
        **kwargs, transport=httpx.MockTransport(handler)
    )):
        yield api
    assert all(route.calls for route in api.routes.values())


def node(operation):
    return FilloutNode(
        node_id="fillout-test", node_type="automation-fillout", node_data={},
        config=FilloutNodeConfig(
            config=operation,
            credentials=FilloutApiKeyCredential(api_key="secret-test-key"),
        ),
        sio=Mock(), sid="test-sid", workflow_id="test-workflow", user_id="test-user",
    )


@pytest.mark.asyncio
async def test_forms_request_uses_zite_base_and_bearer_token():
    with mock_api() as mock:
        route = mock.get(f"{FORMS}/forms").mock(return_value=httpx.Response(
            200, json=[{"formId": "form-1", "name": "QA form"}]
        ))
        result = await node(ListForms()).execute({})
        request = route.calls[-1]
    assert request.headers["Authorization"] == "Bearer secret-test-key"
    assert result["data"][0]["name"] == "QA form"
    assert result["action"] == "list_forms"


@pytest.mark.asyncio
async def test_eu_form_region_uses_documented_zite_database_host():
    credential = FilloutApiKeyCredential(api_key="secret-test-key", api_region="fillout_eu")
    with mock_api() as mock:
        mock.get("https://eu-api.fillout.com/v1/api/forms/f").mock(
            return_value=httpx.Response(200, json={"formId": "f"})
        )
        mock.get("https://tables.zite.com/api/v1/bases").mock(
            return_value=httpx.Response(200, json=[]))
        assert (await _request(credential, "forms", "GET", "/forms/f"))["formId"] == "f"
        assert await _request(credential, "database", "GET", "/bases") == []


@pytest.mark.asyncio
async def test_submission_search_and_pagination_query_names():
    with mock_api() as mock:
        route = mock.get(f"{FORMS}/forms/f/submissions").mock(
            return_value=httpx.Response(200, json={"responses": [], "totalResponses": 0})
        )
        await node(ListSubmissions(form_id="f", limit=12, offset=6,
                                   after_date="2026-10-01T00:00:00Z",
                                   include_preview=True, sort="desc", search="qa")).execute({})
        query = route.calls[-1].url.params
    assert query["limit"] == "12"
    assert query["offset"] == "6"
    assert query["afterDate"] == "2026-10-01T00:00:00Z"
    assert query["includePreview"] == "true"
    assert query["sort"] == "desc"
    assert query["search"] == "qa"


@pytest.mark.asyncio
async def test_submission_creation_preserves_question_values_and_caps_batch():
    with mock_api() as mock:
        route = mock.post(f"{FORMS}/forms/f/submissions").mock(
            return_value=httpx.Response(200, json={"submissions": [{"submissionId": "s"}]})
        )
        result = await node(CreateSubmissions(
            form_id="f", submissions_json='[{"questions":[{"id":"q","value":"Alice"}]}]'
        )).execute({})
        body = route.calls[-1].content
    assert b'"value":"Alice"' in body
    assert result["data"]["submissions"][0]["submissionId"] == "s"
    with pytest.raises(ValueError, match="1–10"):
        await node(CreateSubmissions(form_id="f", submissions_json="[]")).execute({})


@pytest.mark.asyncio
async def test_form_webhook_removal_uses_post_body():
    with mock_api() as mock:
        route = mock.post(f"{FORMS}/webhook/delete").mock(
            return_value=httpx.Response(200, json={"success": True})
        )
        await node(DeleteFormWebhook(webhook_id="webhook-1")).execute({})
        body = route.calls[-1].content
    assert body == b'{"webhookId":"webhook-1"}'


@pytest.mark.asyncio
async def test_database_creation_and_record_creation_use_official_wrappers():
    with mock_api() as mock:
        create_db = mock.post(f"{DATABASE}/bases").mock(
            return_value=httpx.Response(201, json={"id": "db-1", "tables": []})
        )
        db = await node(CreateDatabase(name="QA", tables_json=(
            '[{"name":"Entries","fields":[{"name":"Name",'
            '"type":"single_line_text","template":{}}]}]'
        ))).execute({})
        assert db["data"]["id"] == "db-1"
        assert b'"tables":[' in create_db.calls[-1].content

        create_record = mock.post(f"{DATABASE}/bases/db-1/tables/t-1/records").mock(
            return_value=httpx.Response(201, json={"id": "r-1"})
        )
        record = await node(CreateRecord(database_id="db-1", table_id="t-1",
                                         record_json='{"Name":"Alice"}')).execute({})
        assert create_record.calls[-1].content == b'{"record":{"Name":"Alice"}}'
        assert record["data"]["id"] == "r-1"


@pytest.mark.asyncio
async def test_record_filter_sort_and_field_patch():
    with mock_api() as mock:
        list_route = mock.post(f"{DATABASE}/bases/db/tables/table/records/list").mock(
            return_value=httpx.Response(200, json={"records": [{"id": "r"}], "hasMore": False})
        )
        result = await node(ListRecords(
            database_id="db", table_id="table", limit=7,
            filter_json='{"field":"Name","equals":"Alice"}',
            sort_json='[{"field":"createdAt","direction":"desc"}]',
        )).execute({})
        body = list_route.calls[-1].content
        assert b'"filter":{"field":"Name","equals":"Alice"}' in body
        assert b'"sort":[{"field":"createdAt","direction":"desc"}]' in body
        assert result["data"]["records"][0]["id"] == "r"

        patch_route = mock.patch(f"{DATABASE}/bases/db/tables/table/fields/fld").mock(
            return_value=httpx.Response(200, json={"id": "fld", "name": "Display name"})
        )
        await node(UpdateField(database_id="db", table_id="table", field_id="fld",
                               name="Display name", template_json="{}")).execute({})
        assert patch_route.calls[-1].content == b'{"name":"Display name","template":{}}'


@pytest.mark.asyncio
async def test_dynamic_form_database_and_table_pickers():
    cred = {"api_key": "secret-test-key", "api_region": "zite"}
    with mock_api() as mock:
        mock.get(f"{FORMS}/forms").mock(return_value=httpx.Response(200, json=[
            {"formId": "f1", "name": "Signup"}, {"formId": "f2", "name": "Survey"},
        ]))
        mock.get(f"{DATABASE}/bases").mock(return_value=httpx.Response(200, json=[
            {"id": "db1", "name": "Customers"},
        ]))
        mock.get(f"{DATABASE}/bases/db1").mock(return_value=httpx.Response(200, json={
            "tables": [{"id": "t1", "name": "Contacts"}],
        }))
        forms = await FilloutNode.load_field_options("form_id", cred, search="sur")
        databases = await FilloutNode.load_field_options("database_id", cred)
        tables = await FilloutNode.load_field_options("table_id", cred, {"database_id": "db1"})
    assert forms["options"] == [{"value": "f2", "label": "Survey"}]
    assert databases["options"] == [{"value": "db1", "label": "Customers"}]
    assert tables["options"] == [{"value": "t1", "label": "Contacts"}]


@pytest.mark.asyncio
async def test_redirect_and_error_body_never_expose_key_or_message():
    credential = FilloutApiKeyCredential(api_key="secret-test-key")
    with mock_api() as mock:
        mock.get(f"{FORMS}/forms").mock(return_value=httpx.Response(
            302, headers={"Location": "https://elsewhere.example/collect?key=secret-test-key"}
        ))
        with pytest.raises(ValueError, match="HTTP 302") as redirect:
            await _request(credential, "forms", "GET", "/forms")
        assert "secret-test-key" not in str(redirect.value)
        mock.get(f"{FORMS}/forms").mock(return_value=httpx.Response(401, json={
            "error": {"code": "UNAUTHORIZED", "message": "key secret-test-key invalid"}
        }))
        with pytest.raises(ValueError, match="HTTP 401") as denied:
            await _request(credential, "forms", "GET", "/forms")
        assert "secret-test-key" not in str(denied.value)
        mock.get(f"{FORMS}/forms").mock(return_value=httpx.Response(200, json={
            "success": False, "error": "secret-test-key was rejected",
        }))
        with pytest.raises(ValueError, match="returned an error") as logical_error:
            await _request(credential, "forms", "GET", "/forms")
        assert "secret-test-key" not in str(logical_error.value)
