"""Focused mocked integration checks for Mailjet's Email API contract."""

import base64
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import mailjet_node as mailjet
from nodes.core.run_op import run_node_operation
from nodes.core.connection_evidence import collect_evidence


CREDS = {"credential_type": "mailjet_api_key", "api_key": "key-test", "secret_key": "secret-test"}
ORIGINAL_ASYNC_CLIENT = httpx.AsyncClient


def node(operation: str, **fields):
    config = mailjet.MailjetNodeConfig.model_validate({
        "config": {"operation": operation, **fields}, "credentials": CREDS,
    })
    return mailjet.MailjetNode(
        node_id="mailjet-test", node_type="automation-mailjet", node_data={},
        config=config, sio=None, sid=None, workflow_id="test", user_id="test",
    )


def mock_api(monkeypatch, handler):
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(mailjet.httpx, "AsyncClient", lambda **kw: ORIGINAL_ASYNC_CLIENT(transport=transport, **kw))


@pytest.mark.asyncio
async def test_list_roundtrip_paths_auth_and_envelope(monkeypatch):
    calls = []

    def handler(request):
        calls.append(request)
        assert request.url.host == "api.mailjet.com"
        assert request.headers["Authorization"] == "Basic " + base64.b64encode(b"key-test:secret-test").decode()
        if request.method == "DELETE":
            return httpx.Response(204)
        if request.method == "POST":
            assert json.loads(request.content) == {"Name": "QA contacts"}
            return httpx.Response(201, json={"Count": 1, "Data": [{"ID": 42, "Name": "QA contacts"}], "Total": 1})
        if request.method == "PUT":
            assert json.loads(request.content) == {"Name": "QA contacts renamed"}
            return httpx.Response(200, json={"Count": 1, "Data": [{"ID": 42, "Name": "QA contacts renamed"}], "Total": 1})
        return httpx.Response(200, json={"Count": 1, "Data": [{"ID": 42, "Name": "QA contacts"}], "Total": 1})

    mock_api(monkeypatch, handler)
    created = await node("create_contact_list", name="QA contacts").execute({})
    got = await node("get_contact_list", list_id="42").execute({})
    updated = await node("update_contact_list", list_id="42", name="QA contacts renamed").execute({})
    deleted = await node("delete_contact_list", list_id="42").execute({})
    assert [c.method for c in calls] == ["POST", "GET", "PUT", "DELETE"]
    assert all(c.url.path.startswith("/v3/REST/contactslist") for c in calls)
    assert created["data"]["Data"][0]["ID"] == 42
    assert got["data"]["Count"] == 1
    assert updated["data"]["Data"][0]["Name"] == "QA contacts renamed"
    assert deleted == {"status": "success", "action": "delete_contact_list", "status_code": 204, "data": None}


@pytest.mark.asyncio
async def test_picker_is_account_specific_and_rejection_cannot_go_green(monkeypatch):
    mock_api(monkeypatch, lambda request: httpx.Response(200, json={
        "Count": 2, "Total": 2, "Data": [{"ID": 1, "Name": "Sales"}, {"ID": 2, "Name": "Product"}],
    }))
    result = await mailjet.MailjetNode.load_field_options("list_id", CREDS)
    assert result["options"] == [{"value": "1", "label": "Sales"}, {"value": "2", "label": "Product"}]
    assert mailjet.MailjetNode.connection_evidence.field == "list_id"
    assert mailjet.MailjetNode.connection_evidence.identity_operation == "get_my_profile"

    mock_api(monkeypatch, lambda request: httpx.Response(401, json={"ErrorMessage": "secret-test"}))
    with pytest.raises(ValueError, match="Mailjet returned HTTP 401") as rejected:
        await mailjet.MailjetNode.load_field_options("list_id", CREDS)
    assert "secret-test" not in str(rejected.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("field_name,expected_path,rows,total,expected_next", [
    ("list_id", "/v3/REST/contactslist", 100, 100, "100"),
    ("list_id", "/v3/REST/contactslist", 37, 37, None),
    ("list_id", "/v3/REST/contactslist", 0, 0, None),
    ("content_template_id", "/v1/REST/templates", 100, 100, None),
    ("content_template_id", "/v1/REST/templates", 37, 250, "37"),
    ("content_template_id", "/v1/REST/templates", 0, 250, None),
])
async def test_picker_pagination_uses_the_right_api_total_contract(
    monkeypatch, field_name, expected_path, rows, total, expected_next,
):
    def handler(request):
        assert request.url.path == expected_path
        assert request.url.params["Limit"] == "100"
        assert request.url.params["Offset"] == "0"
        return httpx.Response(200, json={"Count": rows, "Total": total, "Data": [
            {"ID": index + 1, "Name": f"Owned {index + 1}"} for index in range(rows)
        ]})

    mock_api(monkeypatch, handler)
    page = await mailjet.MailjetNode.load_field_options(field_name, CREDS)
    assert len(page["options"]) == rows
    assert page["next_page_token"] == expected_next


@pytest.mark.asyncio
async def test_picker_next_page_offsets_and_v1_global_total(monkeypatch):
    seen = []

    def handler(request):
        seen.append((request.url.path, request.url.params["Offset"]))
        offset = int(request.url.params["Offset"])
        if request.url.path == "/v3/REST/contactslist":
            size = 100 if offset == 0 else 25
            total = size  # v3 Total is only the number of lines in this page.
        else:
            size = 100 if offset == 0 else 25
            total = 125  # v1 Total is the global matching count.
        return httpx.Response(200, json={"Count": size, "Total": total, "Data": [
            {"ID": offset + index + 1, "Name": f"Owned {offset + index + 1}"}
            for index in range(size)
        ]})

    mock_api(monkeypatch, handler)
    for field_name in ("list_id", "content_template_id"):
        first = await mailjet.MailjetNode.load_field_options(field_name, CREDS)
        second = await mailjet.MailjetNode.load_field_options(field_name, CREDS, page_token=first["next_page_token"])
        assert first["next_page_token"] == "100"
        assert second["next_page_token"] is None
        assert second["options"][0]["value"] == "101"
    assert seen == [
        ("/v3/REST/contactslist", "0"), ("/v3/REST/contactslist", "100"),
        ("/v1/REST/templates", "0"), ("/v1/REST/templates", "100"),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("field_name", ["list_id", "content_template_id"])
@pytest.mark.parametrize("first_page_matches", [0, 1])
async def test_picker_search_accumulates_later_matches_and_advances_raw_offset(
    monkeypatch, field_name, first_page_matches,
):
    seen = []

    def handler(request):
        offset = int(request.url.params["Offset"])
        seen.append(offset)
        matches = first_page_matches if offset == 0 else 20
        rows = [{"ID": offset + index + 1,
                 "Name": f"{'Wanted' if index < matches else 'Other'} {offset + index + 1}"}
                for index in range(100)]
        total = 300 if field_name == "content_template_id" else 100
        return httpx.Response(200, json={"Count": 100, "Total": total, "Data": rows})

    mock_api(monkeypatch, handler)
    result = await mailjet.MailjetNode.load_field_options(field_name, CREDS, search=" WANTED ")
    assert seen == [0, 100]
    assert len(result["options"]) == first_page_matches + 20
    assert result["options"][-1] == {"value": "120", "label": "Wanted 120"}
    assert result["next_page_token"] == "200"


@pytest.mark.asyncio
@pytest.mark.parametrize("field_name", ["list_id", "content_template_id"])
@pytest.mark.parametrize("final_matches", [0, 1])
async def test_picker_search_exhausts_sparse_or_absent_matches(monkeypatch, field_name, final_matches):
    seen = []

    def handler(request):
        offset = int(request.url.params["Offset"])
        seen.append(offset)
        size = 100 if offset == 0 else 17
        rows = [{"ID": offset + index + 1,
                 "Name": "Wanted" if offset == 100 and index < final_matches else "Other"}
                for index in range(size)]
        total = 117 if field_name == "content_template_id" else size
        return httpx.Response(200, json={"Count": size, "Total": total, "Data": rows})

    mock_api(monkeypatch, handler)
    result = await mailjet.MailjetNode.load_field_options(field_name, CREDS, search="wanted")
    assert seen == [0, 100]
    assert result == {"options": [{"value": "101", "label": "Wanted"}] if final_matches else [],
                      "next_page_token": None}


@pytest.mark.asyncio
@pytest.mark.parametrize("field_name", ["list_id", "content_template_id"])
async def test_picker_search_terminates_on_empty_later_page(monkeypatch, field_name):
    seen = []

    def handler(request):
        offset = int(request.url.params["Offset"])
        seen.append(offset)
        size = 100 if offset == 0 else 0
        total = 200 if field_name == "content_template_id" else size
        return httpx.Response(200, json={"Count": size, "Total": total, "Data": [
            {"ID": index + 1, "Name": "Other"} for index in range(size)
        ]})

    mock_api(monkeypatch, handler)
    assert await mailjet.MailjetNode.load_field_options(field_name, CREDS, search="wanted") == {
        "options": [], "next_page_token": None,
    }
    assert seen == [0, 100]


@pytest.mark.asyncio
async def test_picker_search_honors_requested_continuation_offset(monkeypatch):
    seen = []

    def handler(request):
        seen.append(int(request.url.params["Offset"]))
        return httpx.Response(200, json={"Count": 100, "Total": 100, "Data": [
            {"ID": index + 101, "Name": "Wanted" if index < 20 else "Other"}
            for index in range(100)
        ]})

    mock_api(monkeypatch, handler)
    result = await mailjet.MailjetNode.load_field_options("list_id", CREDS, page_token="100", search="wanted")
    assert seen == [100]
    assert result["options"][0] == {"value": "101", "label": "Wanted"}
    assert result["next_page_token"] == "200"


@pytest.mark.asyncio
@pytest.mark.parametrize("search", [None, "wanted"])
@pytest.mark.parametrize("page_token", ["-1", "1.5", "invalid", "", True])
async def test_picker_rejects_invalid_cursor_before_request(monkeypatch, search, page_token):
    mock_api(monkeypatch, lambda request: pytest.fail("invalid cursor reached Mailjet"))
    with pytest.raises(ValueError, match="Invalid option page"):
        await mailjet.MailjetNode.load_field_options("list_id", CREDS, page_token=page_token, search=search)


@pytest.mark.asyncio
@pytest.mark.parametrize("field_name,later_response", [
    ("list_id", httpx.Response(401, json={"ErrorMessage": "provider rejection"})),
    ("list_id", httpx.Response(200, json={"Count": 1, "Total": 1, "Data": {"ID": 101}})),
    ("list_id", httpx.Response(200, json={"Count": 1, "Total": 1, "Data": [{"ID": True, "Name": "Wanted"}]})),
    ("content_template_id", httpx.Response(200, json={
        "Count": 1, "Total": 100, "Data": [{"ID": 101, "Name": "Wanted"}],
    })),
])
async def test_picker_search_later_failure_never_returns_partial_matches(monkeypatch, field_name, later_response):
    seen = []

    def handler(request):
        offset = int(request.url.params["Offset"])
        seen.append(offset)
        if offset:
            return later_response
        total = 300 if field_name == "content_template_id" else 100
        return httpx.Response(200, json={"Count": 100, "Total": total, "Data": [
            {"ID": index + 1, "Name": "Wanted" if index == 0 else "Other"}
            for index in range(100)
        ]})

    mock_api(monkeypatch, handler)
    with pytest.raises(ValueError, match="Mailjet"):
        await mailjet.MailjetNode.load_field_options(field_name, CREDS, search="wanted")
    assert seen == [0, 100]


@pytest.mark.asyncio
async def test_picker_search_counts_distinct_visible_matches(monkeypatch):
    seen = []

    def handler(request):
        offset = int(request.url.params["Offset"])
        seen.append(offset)
        rows = ([{"ID": 1, "Name": "Wanted"}] * 100 if offset == 0 else [
            {"ID": index + 101, "Name": "Wanted" if index < 19 else "Other"}
            for index in range(100)
        ])
        return httpx.Response(200, json={"Count": 100, "Total": 100, "Data": rows})

    mock_api(monkeypatch, handler)
    result = await mailjet.MailjetNode.load_field_options("list_id", CREDS, search="wanted")
    assert seen == [0, 100]
    assert len(result["options"]) == len({option["value"] for option in result["options"]}) == 20
    assert result["next_page_token"] == "200"


@pytest.mark.asyncio
async def test_picker_search_floor_counts_matches_visible_to_dropdown(monkeypatch):
    seen = []

    def handler(request):
        offset = int(request.url.params["Offset"])
        seen.append(offset)
        rows = [{"ID": offset + index + 1,
                 "Name": "Straße" if offset == 0 else "STRASSE" if index < 20 else "Other"}
                for index in range(100)]
        return httpx.Response(200, json={"Count": 100, "Total": 100, "Data": rows})

    mock_api(monkeypatch, handler)
    result = await mailjet.MailjetNode.load_field_options("list_id", CREDS, search="strasse")
    assert seen == [0, 100]
    assert len(result["options"]) == 20
    assert all(option["label"] == "STRASSE" for option in result["options"])
    assert result["next_page_token"] == "200"


@pytest.mark.asyncio
async def test_picker_search_validates_whole_page_before_returning_matches(monkeypatch):
    rows = [{"ID": index + 1, "Name": "Wanted"} for index in range(100)]
    rows[-1]["Name"] = {"invalid": "label"}
    mock_api(monkeypatch, lambda request: httpx.Response(200, json={"Count": 100, "Total": 100, "Data": rows}))
    with pytest.raises(ValueError, match="invalid list response"):
        await mailjet.MailjetNode.load_field_options("list_id", CREDS, search="wanted")


@pytest.mark.asyncio
async def test_picker_search_rejects_repeated_provider_page(monkeypatch):
    seen = []

    def handler(request):
        seen.append(int(request.url.params["Offset"]))
        return httpx.Response(200, json={"Count": 100, "Total": 100, "Data": [
            {"ID": index + 1, "Name": "Other"} for index in range(100)
        ]})

    mock_api(monkeypatch, handler)
    with pytest.raises(ValueError, match="repeated option page"):
        await mailjet.MailjetNode.load_field_options("list_id", CREDS, search="wanted")
    assert seen == [0, 100]


@pytest.mark.asyncio
async def test_picker_search_cap_fails_with_remaining_offset(monkeypatch):
    seen = []

    def handler(request):
        offset = int(request.url.params["Offset"])
        seen.append(offset)
        return httpx.Response(200, json={"Count": 100, "Total": 100, "Data": [
            {"ID": offset + index + 1, "Name": "Wanted" if index == 0 else "Other"}
            for index in range(100)
        ]})

    mock_api(monkeypatch, handler)
    with pytest.raises(ValueError, match="search page limit.*next offset 1000"):
        await mailjet.MailjetNode.load_field_options("list_id", CREDS, search="wanted")
    assert seen == list(range(0, 1000, 100))


@pytest.mark.asyncio
async def test_empty_account_profile_identity_and_invalid_profile(monkeypatch):
    mock_api(monkeypatch, lambda request: httpx.Response(200, json={
        "Count": 1, "Data": [{"CompanyName": "Example Company", "ID": 7,
                              "AddressCity": "private billing address"}], "Total": 1,
    }))
    profile = await node("get_my_profile").execute({})
    assert profile["data"] == {"CompanyName": "Example Company"}
    mock_api(monkeypatch, lambda request: httpx.Response(200, json={"Count": 0, "Data": []}))
    assert (await node("get_my_profile").execute({}))["status"] == "error"


@pytest.mark.asyncio
async def test_send_uses_v31_and_checks_message_status(monkeypatch):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"Messages": [{"Status": "success", "To": [{"MessageID": 7}]}]})

    mock_api(monkeypatch, handler)
    result = await node("send_email", from_email="sender@example.com", to_email="to@example.com",
                        subject="Hi", text_part="Hello", sandbox_mode=True).execute({})
    assert result["status"] == "success"
    assert seen[0].url.path == "/v3.1/send"
    body = json.loads(seen[0].content)
    assert body == {"Messages": [{"From": {"Email": "sender@example.com"},
                "To": [{"Email": "to@example.com"}], "Subject": "Hi", "TextPart": "Hello"}],
                "SandboxMode": True}

    mock_api(monkeypatch, lambda request: httpx.Response(200, json={"Messages": [{
        "Status": "error", "Errors": [{"ErrorMessage": "private recipient leaked"}],
    }]}))
    rejected = await node("send_email", from_email="sender@example.com", to_email="to@example.com",
                          subject="Hi", text_part="Hello").execute({})
    assert rejected["status"] == "error"
    assert "private recipient leaked" not in str(rejected)


@pytest.mark.asyncio
async def test_non_json_contract_and_bad_json(monkeypatch):
    mock_api(monkeypatch, lambda request: httpx.Response(202, content=b""))
    accepted = await node("manage_many_contacts", body_json='{"Contacts":[]}').execute({})
    assert accepted["status"] == "success" and accepted["status_code"] == 202
    mock_api(monkeypatch, lambda request: httpx.Response(200, text="a,b\n1,2", headers={"content-type": "text/csv"}))
    assert (await node("list_contacts").execute({}))["status"] == "error"
    assert (await node("get_csv_import_errors", job_id="42").execute({}))["data"] == "a,b\n1,2"
    mock_api(monkeypatch, lambda request: httpx.Response(200, content=b"\x00\x01", headers={"content-type": "application/octet-stream"}))
    assert (await node("list_contacts").execute({}))["status"] == "error"
    binary_op = mailjet.Operation("get_binary", "Test", "GET", "/v3/DATA/test", response_kind="binary")
    binary = (await mailjet._request(mailjet.MailjetApiKeyCredential.model_validate(CREDS), binary_op,
                                     binary_op.path))["data"]
    assert isinstance(binary, mailjet.BinaryOutput) and binary.data == b"\x00\x01"
    text_op = mailjet.Operation("get_text", "Test", "GET", "/v3/DATA/test", response_kind="text")
    mock_api(monkeypatch, lambda request: httpx.Response(200, text="plain response", headers={"content-type": "text/plain"}))
    assert (await mailjet._request(mailjet.MailjetApiKeyCredential.model_validate(CREDS), text_op,
                                   text_op.path))["data"] == "plain response"
    mock_api(monkeypatch, lambda request: httpx.Response(200, content=b"bad", headers={"content-type": "application/json"}))
    assert (await node("list_contacts").execute({}))["status"] == "error"


@pytest.mark.asyncio
async def test_content_lock_unlock_accept_documented_empty_204_only(monkeypatch):
    seen = []

    def handler(request):
        seen.append(request.url.path)
        return httpx.Response(204)

    mock_api(monkeypatch, handler)
    for operation in ("lock_content_template", "unlock_content_template"):
        result = await node(operation, content_template_id="42").execute({})
        assert result == {"status": "success", "action": operation, "status_code": 204, "data": None}
    rejected = await node("publish_content_template", content_template_id="42").execute({})
    assert rejected["status"] == "error"
    assert seen == [
        "/v1/REST/templates/42/contents/lock",
        "/v1/REST/templates/42/contents/unlock",
        "/v1/REST/templates/42/contents/publish",
    ]


@pytest.mark.asyncio
async def test_statistics_required_queries_from_parsed_config(monkeypatch):
    seen = []

    def handler(request):
        seen.append((request.url.path, dict(request.url.params)))
        return httpx.Response(200, json={"Count": 0, "Data": [], "Total": 0})

    mock_api(monkeypatch, handler)
    counters = await node(
        "list_stat_counters", counter_source="Campaign", counter_resolution="Day",
        counter_timing="Event", source_id=42, from_ts="2026-10-01T00:00:00Z",
        to_ts="2026-10-02T00:00:00Z", limit=25, offset=5,
    ).execute({})
    clicks = await node("list_link_click_statistics", campaign_id=42).execute({})
    esp = await node("list_recipient_esp_statistics", campaign_id=42).execute({})
    assert counters["status"] == clicks["status"] == esp["status"] == "success"
    assert seen == [
        ("/v3/REST/statcounters", {
            "Limit": "25", "Offset": "5", "CounterSource": "Campaign",
            "CounterResolution": "Day", "CounterTiming": "Event", "SourceID": "42",
            "FromTS": "2026-10-01T00:00:00Z", "ToTS": "2026-10-02T00:00:00Z",
        }),
        ("/v3/REST/statistics/link-click", {"CampaignID": "42"}),
        ("/v3/REST/statistics/recipient-esp", {"CampaignID": "42"}),
    ]
    assert node("list_stat_counters", counter_source="APIKey", counter_resolution="Lifetime",
                counter_timing="Message").config.config.source_id is None


@pytest.mark.asyncio
@pytest.mark.parametrize("fields", [
    {"counter_source": "Campaign", "counter_resolution": "Lifetime", "counter_timing": "Message"},
    {"counter_source": "List", "counter_resolution": "Day", "counter_timing": "Message", "source_id": 42,
     "from_ts": "2026-10-01T00:00:00Z"},
    {"counter_source": "Sender", "counter_resolution": "Day", "counter_timing": "Event", "source_id": 42,
     "from_ts": "2026-10-01T00:00:00Z"},
    {"counter_source": "Campaign", "counter_resolution": "Lifetime", "counter_timing": "Event", "source_id": 42},
    {"counter_source": "Campaign", "counter_resolution": "Day", "counter_timing": "Message", "source_id": 42},
    {"counter_source": "APIKey", "counter_resolution": "Lifetime", "counter_timing": "Message", "source_id": 42},
])
async def test_invalid_stat_counter_combinations_do_not_call_provider(monkeypatch, fields):
    def handler(request):
        raise AssertionError("invalid query should not reach Mailjet")

    mock_api(monkeypatch, handler)
    with pytest.raises(ValueError):
        await node("list_stat_counters", **fields).execute({})


def test_statistics_required_filters_are_in_config_schema():
    with pytest.raises(ValidationError):
        node("list_stat_counters")
    for operation in ("list_link_click_statistics", "list_recipient_esp_statistics"):
        with pytest.raises(ValidationError):
            node(operation)
    with pytest.raises(ValidationError):
        node("list_stat_counters", counter_source="invalid", counter_resolution="Day",
             counter_timing="Message", source_id=42, from_ts="2026-10-01T00:00:00Z")


@pytest.mark.asyncio
@pytest.mark.parametrize("profile", [
    "string", {}, {"ID": 7}, {"CompanyName": True}, {"CompanyName": {"name": "fake"}},
    {"CompanyName": "  ", "Email": "  "},
])
async def test_malformed_account_identity_cannot_pass(monkeypatch, profile):
    mock_api(monkeypatch, lambda request: httpx.Response(200, json={
        "Count": 1, "Data": [profile], "Total": 1,
    }))
    result = await node("get_my_profile").execute({})
    assert result["status"] == "error"
    assert "fake" not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("row", [
    "string", {"ID": {}}, {"ID": True, "Name": "Fake"}, {"ID": 1, "Name": {}},
    {"ID": -1, "Name": "Fake"}, {"ID": 1, "Name": " "},
])
async def test_malformed_picker_cannot_be_connection_evidence(monkeypatch, row):
    mock_api(monkeypatch, lambda request: httpx.Response(200, json={
        "Count": 1, "Data": [row], "Total": 1,
    }))
    with pytest.raises(ValueError, match="invalid"):
        await mailjet.MailjetNode.load_field_options("list_id", CREDS)


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [
    httpx.Response(200),
    httpx.Response(200, text="<html>login</html>", headers={"content-type": "text/html"}),
    httpx.Response(200, json={"Data": {"ID": 42}}),
    httpx.Response(200, json={"Data": [], "Count": True, "Total": 0}),
    httpx.Response(302, headers={"location": "https://wrong.example/login"}),
    httpx.Response(401, json={"ErrorMessage": "private secret"}),
])
async def test_empty_html_bad_envelope_redirect_and_auth_error_fail_closed(monkeypatch, response):
    mock_api(monkeypatch, lambda request: response)
    result = await node("list_contacts").execute({})
    assert result["status"] == "error"
    assert "wrong.example" not in str(result)
    assert "private secret" not in str(result)


def test_catalog_schema_and_safe_json_body():
    assert len(mailjet.OPERATIONS) == len(mailjet._OPERATIONS) == 121
    assert all(op.path.startswith(("/v3/REST/", "/v3/DATA/", "/v3.1/send", "/v1/REST/")) for op in mailjet._OPERATIONS)
    schema = mailjet.MailjetNode.get_config_schema()
    cred = schema["$defs"]["MailjetApiKeyCredential"]["properties"]
    assert cred["api_key"]["ui:widget"] == "password"
    assert cred["secret_key"]["ui:widget"] == "password"
    with pytest.raises(ValueError, match="nonempty JSON object"):
        mailjet._body_object("[]")
    with pytest.raises(ValueError, match="valid JSON"):
        mailjet._body_object("{")
    assert mailjet._path(mailjet.OPERATIONS["get_contact"], node("get_contact", contact_id="a/b").config.config).endswith("a%2Fb")


def test_mailjet_source_and_assets_ship_to_public_edition():
    # Run in both editions: export tooling itself is absent from the open tree.
    root = Path(__file__).resolve().parents[3]
    for path in (
        "backend/nodes/mailjet_node.py",
        "frontend/app/components/workflow/nodes/integrations/mailjet.tsx",
        "frontend/app/schemas/nodes/mailjet.json",
        "frontend/public/icons/mailjet-preferred-brand.svg",
    ):
        assert (root / path).is_file(), path


@pytest.mark.asyncio
async def test_registered_dispatcher_uses_declared_operation(monkeypatch):
    paths = []

    def handler(request):
        paths.append(request.url.path)
        return httpx.Response(200, json={"Count": 1, "Data": [{"ID": 42}], "Total": 1})

    mock_api(monkeypatch, handler)
    result = await run_node_operation(
        node_type="automation-mailjet", operation="get_contact_list",
        arguments={"operation": "delete_contact_list", "list_id": "42"},
        credential_data=CREDS, user_id="test-user",
    )
    assert result["status"] == "success"
    assert paths == ["/v3/REST/contactslist/42"]


@pytest.mark.asyncio
async def test_connection_evidence_names_empty_account_and_rejects_bad_key(monkeypatch):
    def empty_account(request):
        if request.url.path.endswith("/contactslist"):
            return httpx.Response(200, json={"Count": 0, "Data": [], "Total": 0})
        return httpx.Response(200, json={"Count": 1, "Data": [{"CompanyName": "Own Account"}], "Total": 1})

    mock_api(monkeypatch, empty_account)
    evidence = await collect_evidence(node_type="automation-mailjet", credential_data=CREDS, user_id="test-user")
    assert evidence.reachable is True and evidence.account_label == "Own Account"
    mock_api(monkeypatch, lambda request: httpx.Response(401, json={"ErrorMessage": "secret-test"}))
    rejected = await collect_evidence(node_type="automation-mailjet", credential_data=CREDS, user_id="test-user")
    assert rejected.reachable is False
    assert "secret-test" not in str(rejected)

    def malformed_identity(request):
        if request.url.path.endswith("/contactslist"):
            return httpx.Response(200, json={"Count": 0, "Data": [], "Total": 0})
        return httpx.Response(200, json={"Count": 1, "Data": [{"ID": 7}], "Total": 1})

    mock_api(monkeypatch, malformed_identity)
    unverified = await collect_evidence(node_type="automation-mailjet", credential_data=CREDS, user_id="test-user")
    assert unverified.reachable is None and unverified.account_label is None


@pytest.mark.asyncio
async def test_content_api_template_and_label_paths(monkeypatch):
    seen = []

    def handler(request):
        seen.append(request)
        if request.url.path == "/v1/REST/templates/20/contents":
            return httpx.Response(201, json={
                "ID": 21, "TemplateID": 20, "ContentType": "D", "Locale": "en_US",
                "HTMLPart": "<p>Receipt</p>",
            })
        return httpx.Response(201, json={"Count": 1, "Data": [{"ID": 20}], "Total": 1})

    mock_api(monkeypatch, handler)
    template = await node("create_content_template", name="Receipt", purpose="transactional").execute({})
    content = await node("create_content_template_version", content_template_id="20",
                         html_part="<p>Receipt</p>").execute({})
    label = await node("create_label", name="Receipts", color="#2385E0").execute({})
    assert all(result["status"] == "success" for result in (template, content, label))
    assert content["data"]["ID"] == 21 and content["data"]["TemplateID"] == 20
    assert [r.url.path for r in seen] == [
        "/v1/REST/templates", "/v1/REST/templates/20/contents", "/v1/REST/labels",
    ]
    assert json.loads(seen[0].content)["Purposes"] == ["transactional"]
    assert json.loads(seen[1].content)["HTMLPart"] == "<p>Receipt</p>"
    assert json.loads(seen[2].content)["UsedFor"] == "resource"


@pytest.mark.asyncio
@pytest.mark.parametrize("content_type", ["D", "P", "A"])
async def test_get_content_template_version_accepts_each_documented_status(monkeypatch, content_type):
    seen = []
    content = {"ID": 21, "TemplateID": 20, "ContentType": content_type}

    def handler(request):
        seen.append((request.method, request.url.path))
        return httpx.Response(200, json={"Count": 1, "Data": [content], "Total": 1})

    mock_api(monkeypatch, handler)
    result = await node("get_content_template_version", content_template_id="20",
                        content_type=content_type).execute({})
    assert seen == [("GET", f"/v1/REST/templates/20/contents/types/{content_type}")]
    assert result["status"] == "success" and result["data"]["Data"] == [content]


@pytest.mark.asyncio
async def test_update_content_template_version_sends_draft_put(monkeypatch):
    seen = []
    body = {"HTMLPart": "<p>Updated receipt</p>"}

    def handler(request):
        seen.append((request.method, request.url.path, json.loads(request.content)))
        return httpx.Response(200, json={"Count": 1, "Data": [{"ContentType": "D"}], "Total": 1})

    mock_api(monkeypatch, handler)
    result = await node("update_content_template_version", content_template_id="20",
                        content_type="D", body_json=json.dumps(body)).execute({})
    assert seen == [("PUT", "/v1/REST/templates/20/contents/types/D", body)]
    assert result["status"] == "success"


@pytest.mark.asyncio
@pytest.mark.parametrize("content_type", ["P", "A"])
async def test_update_content_template_version_rejects_non_draft_before_request(monkeypatch, content_type):
    def handler(request):
        raise AssertionError("non-draft updates must not reach Mailjet")

    mock_api(monkeypatch, handler)
    with pytest.raises(ValidationError) as rejected:
        await node("update_content_template_version", content_template_id="20",
                   content_type=content_type, body_json='{"HTMLPart":"<p>Receipt</p>"}').execute({})
    errors = rejected.value.errors()
    assert len(errors) == 1
    assert errors[0]["loc"][-1] == "content_type" and errors[0]["type"] == "literal_error"


def test_content_template_version_schema_matches_runtime_status_contract():
    schema_path = Path(__file__).resolve().parents[3] / "frontend/app/schemas/nodes/mailjet.json"
    schema = json.loads(schema_path.read_text())
    generated = mailjet.MailjetNode.get_config_schema()
    generated.update({
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Mailjet Node Configuration",
        "x-agent-tool-provider": True,
    })
    assert schema == generated
    get_fields = schema["$defs"]["MailjetGetContentTemplateVersionConfig"]["properties"]
    update_fields = schema["$defs"]["MailjetUpdateContentTemplateVersionConfig"]["properties"]
    assert get_fields["content_type"]["enum"] == ["D", "P", "A"]
    assert update_fields["content_type"]["const"] == "D"
    assert update_fields["content_type"]["enum"] == ["D"]


@pytest.mark.asyncio
@pytest.mark.parametrize("status,payload", [
    (201, {"Count": 1, "Data": [{"ID": 21}], "Total": 1}),
    (201, {"ID": "21", "TemplateID": 20, "ContentType": "D", "Locale": "en_US"}),
    (201, {"ID": 21, "TemplateID": 0, "ContentType": "D", "Locale": "en_US"}),
    (201, {"ID": 21, "TemplateID": 22, "ContentType": "D", "Locale": "en_US"}),
    (201, {"ID": 21, "TemplateID": 20, "ContentType": "P", "Locale": "en_US"}),
    (201, {"ID": 21, "TemplateID": 20, "ContentType": "D", "Locale": " "}),
    (200, {"ID": 21, "TemplateID": 20, "ContentType": "D", "Locale": "en_US"}),
])
async def test_create_content_template_version_rejects_malformed_bare_response(monkeypatch, status, payload):
    mock_api(monkeypatch, lambda request: httpx.Response(status, json=payload))
    result = await node("create_content_template_version", content_template_id="20",
                        html_part="<p>Receipt</p>").execute({})
    assert result["status"] == "error"
    assert result["error"] == "Mailjet returned an invalid template content response"


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,fields,expected", [
    ("create_list_recipient", {"list_id": "2000", "contact_id": 1000},
     {"ListID": 2000, "ContactID": 1000, "IsUnsubscribed": False}),
    ("create_list_recipient", {"list_id": "123456", "contact_email": "passenger@mailjet.com"},
     {"ListID": 123456, "ContactAlt": "passenger@mailjet.com", "IsUnsubscribed": False}),
    ("create_campaign_draft", {"list_id": "123456", "title": "Example Campaign",
      "subject": "Your email flight plan!", "sender": "1234", "sender_email": "no-reply@example.com"},
     {"ContactsListID": 123456, "Title": "Example Campaign", "Subject": "Your email flight plan!",
      "Locale": "en_US", "Sender": "1234", "SenderEmail": "no-reply@example.com"}),
    ("verify_contact_list", {"list_id": "2000", "body_json": '{"Method":"fulllist"}'},
     {"Method": "fulllist"}),
])
async def test_documented_request_bodies_preserve_numeric_ids(monkeypatch, operation, fields, expected):
    def handler(request):
        assert json.loads(request.content) == expected
        return httpx.Response(200, json={"Count": 1, "Total": 1, "Data": [{"ID": 1000}]})

    mock_api(monkeypatch, handler)
    result = await node(operation, **fields).execute({})
    assert result["status"] == "success"


@pytest.mark.asyncio
@pytest.mark.parametrize("fields", [{}, {"contact_id": 1000, "contact_email": "passenger@mailjet.com"}])
async def test_recipient_requires_one_contact_reference(fields):
    with pytest.raises(ValueError, match="exactly one Contact ID or Contact Email"):
        await node("create_list_recipient", list_id=2000, **fields).execute({})
