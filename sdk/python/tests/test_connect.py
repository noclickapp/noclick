import httpx
import pytest
import respx

import noclick as nc
from platform_helpers import USER_ID, body, integration_row, listing, operation, operation_row

CONN = {
    "object": "connection", "id": "con_1", "name": "gmail", "integration": "gmail",
    "credential_type": "GmailOAuth", "user_id": USER_ID, "status": "connected", "account": "ana@gmail.com",
    "verification": {"reachable": True, "samples": ["INBOX"], "message": None}, "connect_link": None,
    "connected_at": "2026-09-25T10:00:00Z", "created_at": "2026-09-25T10:00:00Z", "updated_at": "2026-09-25T10:00:00Z",
}
PENDING = {
    **CONN, "status": "pending", "account": None, "verification": None, "connected_at": None,
    "connect_link": {"id": "lnk_1", "url": "https://noclick.com/c/xyz", "expires_at": "2026-10-02T10:00:00Z",
                     "operation_id": "op_c"},
}


# --- what a connection's service can do -----------------------------------------

def test_integrations_is_the_catalog_filtered_by_query_and_sent_for_no_user(api, client):
    route = api.get("/v1/integrations").respond(json=listing(
        integration_row("gmail", label="Gmail", credential_types=["GmailOAuth", "GmailAppPassword"], operation_count=12,
                        events=[]),
        integration_row("exa", label="Exa", connect_with=["key"], credential_types=["exa_api_key"], operation_count=4,
                        account_free_operation_count=4, events=["monitor_results"]),
    ))
    with nc.as_user(USER_ID):
        gmail, exa = nc.Connection.integrations("a")
    request = route.calls.last.request
    assert request.url.params["q"] == "a" and "NoClick-User" not in request.headers
    assert isinstance(gmail, nc.IntegrationInfo)
    assert (gmail.name, gmail.label, gmail.connect_with, gmail.operation_count) == ("gmail", "Gmail", ["oauth"], 12)
    assert gmail.credential_types == ["GmailOAuth", "GmailAppPassword"]
    assert (exa.connect_with, exa.credential_types) == (["key"], ["exa_api_key"])
    assert (gmail.account_free_operation_count, exa.account_free_operation_count) == (0, 4)
    # Gmail's new mail is polled, not pushed: it names no events, so no OnEvent is built on it.
    assert (gmail.events, exa.events) == ([], ["monitor_results"])
    nc.Connection.integrations()
    assert "q" not in route.calls.last.request.url.params


def test_operations_read_the_hinted_catalog_without_loading_or_creating_the_connection(api, client):
    read = api.get("/v1/connections/slack").respond(json=CONN)
    create = api.post("/v1/connections").respond(201, json=CONN)
    search = api.get("/v1/integrations/slack/operations").respond(json=listing(
        operation_row("send_message_to_channel", description="Post a message", read_only=False, scopes=["chat:write"]),
        operation_row("list_messages", description="Read a channel", read_only=True, scopes=["channels:history"]),
    ))
    one = api.get("/v1/integrations/slack/operations/send_message_to_channel").respond(
        json=operation_row("send_message_to_channel", parameters={"type": "object", "required": ["channel"]}))
    api.get("/v1/integrations/slack/operations/nope").respond(404, json={"error": {"type": "not_found", "message": "No"}})
    with nc.as_user(USER_ID):
        slack = nc.Connection.from_name("slack", integration="slack", create_if_missing=True)
        send, listed = slack.operations(search="message")
        assert search.calls.last.request.url.params["q"] == "message"
        assert "NoClick-User" not in search.calls.last.request.headers
        assert isinstance(send, nc.IntegrationOperation)
        assert (send.name, send.description, send.read_only, send.scopes) == (
            "send_message_to_channel", "Post a message", False, ["chat:write"])
        assert (listed.name, listed.read_only, listed.needs_account) == ("list_messages", True, True)
        slack.operations()
        assert "q" not in search.calls.last.request.url.params
        assert slack.operation("send_message_to_channel").parameters == {"type": "object", "required": ["channel"]}
        assert "NoClick-User" not in one.calls.last.request.headers
        with pytest.raises(nc.NotFound):
            slack.operation("nope")
    assert read.call_count == 0 and create.call_count == 0 and not slack.is_hydrated


def test_discovery_learns_the_integration_from_the_connection_when_it_has_no_hint(api, client):
    crm = {**CONN, "id": "con_c", "name": "crm", "integration": "affinity", "credential_type": "affinity_api_key"}
    read = api.get("/v1/connections/crm").respond(json=crm)
    ops = api.get("/v1/integrations/affinity/operations").respond(json=listing(operation_row("list_lists")))
    connection = nc.Connection.from_name("crm", user=USER_ID)
    assert [op.name for op in connection.operations()] == ["list_lists"]
    assert [op.name for op in connection.operations()] == ["list_lists"]
    assert read.call_count == 1 and ops.call_count == 2
    # A hint that names another integration is a check, not a hint: loading it raises, naming the one it is.
    with pytest.raises(nc.Conflict) as taken:
        nc.Connection.from_name("crm", integration="hubspot", user=USER_ID).hydrate()
    assert (taken.value.field, taken.value.integration, taken.value.existing_id) == ("integration", "affinity", "con_c")
    # The hint that names its own integration loads it, and the catalog follows it.
    nc.Connection.from_name("crm", integration="affinity", user=USER_ID).hydrate().operations()
    assert ops.call_count == 3


def test_needs_account_is_false_only_when_the_catalog_says_so(api, client):
    api.get("/v1/integrations/exa/operations").respond(json=listing(
        operation_row("search", needs_account=False),
        operation_row("create_monitor", needs_account=True),
        {k: v for k, v in operation_row("answer").items() if k != "needs_account"},
    ))
    web = nc.Connection.from_name("web", integration="exa")
    assert [(op.name, op.needs_account) for op in web.operations()] == [
        ("search", False), ("create_monitor", True), ("answer", True),
    ]


def test_catalog_paths_are_percent_encoded(api, client):
    route = api.get("/v1/integrations/my%20crm/operations/a%2Fb").respond(json=operation_row("a/b"))
    assert nc.Connection.from_name("crm", integration="my crm").operation("a/b").name == "a/b"
    assert route.call_count == 1


def test_a_pending_connection_sends_every_run_and_the_server_decides_which_need_an_account(api, client):
    """A needs_account=False operation runs on NoClick's key while pending (the server's call);
    one that needs an account raises NeedsConnection. The client never refuses a run for its status."""
    pending = {**PENDING, "id": "con_w", "name": "web", "integration": "exa", "credential_type": "exa_api_key"}
    api.get("/v1/connections/web").respond(404, json={"error": {"type": "not_found", "message": "No"}})
    create = api.post("/v1/connections").respond(201, json=pending)
    search = api.post("/v1/connections/con_w/operations/search/run").respond(
        json={"object": "operation_result", "connection": "web", "result": {"results": []}})
    api.post("/v1/connections/con_w/operations/create_monitor/run").respond(424, json={"error": {
        "type": "needs_connection", "message": "Connect Exa first.", "connection": "web", "integration": "exa",
        "connect_url": "https://noclick.com/c/xyz"}})
    web = nc.Connection.from_name("web", integration="exa", create_if_missing=True, user=USER_ID)
    assert web.run("search", {"query": "q"}) == {"results": []}
    assert body(create.calls.last.request) == {"name": "web", "integration": "exa"}
    assert web.status == "pending" and body(search.calls.last.request) == {"arguments": {"query": "q"}}
    with pytest.raises(nc.NeedsConnection) as info:
        web.run("create_monitor", {"query": "q"})
    assert info.value.connect_url == "https://noclick.com/c/xyz"


def test_integrations_filter_by_kind_and_read_model_providers(api, client):
    route = api.get("/v1/integrations").respond(json=listing(
        integration_row("anthropic", label="Anthropic", kind="model", subscription=True, connect_with=["key"],
                        credential_types=["agent_anthropic", "agent_claude_code_oauth"], operation_count=0),
        integration_row("openrouter", label="OpenRouter", kind="model", connect_with=["key"],
                        credential_types=["agent_openrouter"], operation_count=0),
    ))
    anthropic, openrouter = nc.Connection.integrations(kind="model")
    assert route.calls.last.request.url.params["kind"] == "model"
    assert "q" not in route.calls.last.request.url.params
    assert (anthropic.kind, anthropic.subscription, anthropic.connect_with, anthropic.operation_count) == (
        "model", True, ["key"], 0)
    assert (openrouter.kind, openrouter.subscription) == ("model", False)
    assert anthropic.events == []  # a row that names no events (a model provider has none)
    nc.Connection.integrations("gmail", kind="app")
    assert dict(route.calls.last.request.url.params) == {"q": "gmail", "kind": "app"}
    with pytest.raises(KeyError):  # a row without its kind is malformed, never an app by default
        route.respond(json=listing({k: v for k, v in integration_row("gmail").items() if k != "kind"}))
        nc.Connection.integrations()


def test_a_model_connection_holds_a_key_and_never_hands_it_out(api, client):
    claude = {"object": "connection", "id": "con_cl", "name": "claude", "integration": "anthropic",
              "credential_type": "agent_anthropic", "user_id": None, "status": "connected",
              "verification": {"reachable": True, "samples": [], "message": "Anthropic accepted the key."}}
    create = api.post("/v1/connections").respond(201, json=claude)
    api.post("/v1/connections/con_cl/token").respond(403, json={"error": {
        "type": "permission_denied", "message": "NoClick never hands out a model key."}})
    connection = nc.Connection.create("claude", integration="anthropic", data={"api_key": "sk-ant-x"})
    assert body(create.calls.last.request) == {"name": "claude", "integration": "anthropic", "data": {"api_key": "sk-ant-x"}}
    assert connection.verification.reachable is True
    with pytest.raises(nc.PermissionDenied, match="never hands out a model key"):
        connection.token()


def test_a_catalog_row_without_its_account_free_count_is_malformed_never_zero(api, client):
    row = {k: v for k, v in integration_row("exa").items() if k != "account_free_operation_count"}
    api.get("/v1/integrations").respond(json=listing(row))
    with pytest.raises(nc.Error, match="account_free_operation_count"):
        nc.Connection.integrations()


# --- noclick.run(): one operation by its ref -------------------------------------------

def _run_result(ref, result, connection=None):
    integration, _, operation = ref.partition(".")
    return {"object": "operation_result", "ref": ref, "integration": integration, "operation": operation,
            "connection": connection, "result": result}


def test_run_posts_the_ref_and_arguments_for_the_account_and_returns_the_result(api, client):
    route = api.post("/v1/run").respond(json=_run_result("exa.search", {"results": [{"url": "https://a.test"}]}))
    assert nc.run("exa.search", {"query": "q"}) == {"results": [{"url": "https://a.test"}]}
    request = route.calls.last.request
    assert body(request) == {"ref": "exa.search", "arguments": {"query": "q"}}
    assert "NoClick-User" not in request.headers and request.headers["Idempotency-Key"]
    nc.run("exa.search")
    assert body(route.calls.last.request) == {"ref": "exa.search", "arguments": {}}


def test_run_returns_a_null_result_as_none_and_refuses_a_response_without_one(api, client):
    api.post("/v1/run").mock(side_effect=[
        httpx.Response(200, json=_run_result("slack.delete_message", None, "con_s")),
        httpx.Response(200, json={"object": "operation_result"}),
    ])
    assert nc.run("slack.delete_message", {"ts": "1.2"}) is None
    with pytest.raises(nc.Error, match="missing `result`"):
        nc.run("slack.delete_message", {"ts": "1.2"})


def test_run_acts_for_the_ambient_user_and_user_wins(api, client):
    route = api.post("/v1/run").respond(json=_run_result("gmail.send_email_message", {"id": "msg_1"}, "con_1"))
    with nc.as_user(USER_ID):
        assert nc.run("gmail.send_email_message", {"to": ["a@b.c"]}) == {"id": "msg_1"}
        assert route.calls.last.request.headers["NoClick-User"] == USER_ID
        nc.run("gmail.send_email_message", user=None)
        assert "NoClick-User" not in route.calls.last.request.headers
    nc.run("gmail.send_email_message", user="user_7")
    assert route.calls.last.request.headers["NoClick-User"] == "user_7"


async def test_run_aio_follows_the_user(api, client):
    route = api.post("/v1/run").respond(json=_run_result("exa.search", []))
    async with nc.as_user(USER_ID):
        assert await nc.run.aio("exa.search", {"query": "q"}) == []
    assert route.calls.last.request.headers["NoClick-User"] == USER_ID


def test_run_uses_the_given_client(client):
    other = nc.Client(api_key="nk_live_other", base_url="https://other.test", max_retries=0)
    with respx.mock(base_url="https://other.test") as router:
        route = router.post("/v1/run").respond(json=_run_result("exa.search", {"results": []}))
        assert nc.run("exa.search", {"query": "q"}, client=other) == {"results": []}
    assert route.calls.last.request.headers["Authorization"] == "Bearer nk_live_other"


@pytest.mark.parametrize("error, cls", [
    ({"type": "needs_connection", "message": "Connect Gmail first.", "connection": "gmail", "integration": "gmail",
      "connect_url": "https://noclick.com/c/xyz"}, nc.NeedsConnection),
    ({"type": "policy_denied", "message": "gmail.send_email_message is denied by policy."}, nc.PolicyDenied),
    ({"type": "invalid_request", "message": "gmail.send_email_message needs an account.",
      "next_step": "Create a connection named gmail.", "field": "ref"}, nc.InvalidRequest),
    ({"type": "not_found", "message": "No connection or integration is named crm."}, nc.NotFound),
])
def test_run_raises_what_the_server_refuses_with(api, client, error, cls):
    status = {nc.NeedsConnection: 424, nc.PolicyDenied: 403, nc.InvalidRequest: 400, nc.NotFound: 404}[cls]
    api.post("/v1/run").respond(status, json={"error": error})
    with pytest.raises(cls) as info:
        nc.run("gmail.send_email_message", {"to": ["a@b.c"]}, user=USER_ID)
    assert info.value.message == error["message"] and info.value.status == status
    if cls is nc.NeedsConnection:
        assert (info.value.connection, info.value.connect_url) == ("gmail", "https://noclick.com/c/xyz")
    if cls is nc.InvalidRequest:
        assert info.value.next_step == "Create a connection named gmail." and info.value.field == "ref"


def test_run_retries_a_held_call_with_its_approval_id(api, client):
    held = {"error": {
        "type": "approval_required", "message": "Sending email needs approval.",
        "approval_id": "ap_9", "request_id": "hr_9", "approve_url": "https://noclick.com/h/hr_9",
        "operation": operation(op_id="op_ap", kind="human.approve"),
    }}
    route = api.post("/v1/run").mock(side_effect=[
        httpx.Response(402, json=held),
        httpx.Response(200, json=_run_result("gmail.send_email_message", {"id": "msg_1"}, "con_1")),
    ])
    wait = api.get("/v1/operations/op_ap/wait").respond(json=operation(
        op_id="op_ap", kind="human.approve", status="succeeded", result={"approved": True}))
    args = {"to": ["a@b.c"]}
    with pytest.raises(nc.ApprovalRequired) as info:
        nc.run("gmail.send_email_message", args, user=USER_ID)
    pending = info.value
    assert pending.operation.wait() is True
    assert wait.calls.last.request.headers["NoClick-User"] == USER_ID  # polled for the user the call acted for
    assert nc.run("gmail.send_email_message", args, user=USER_ID, approval_id=pending.approval_id) == {"id": "msg_1"}
    assert body(route.calls[0].request) == {"ref": "gmail.send_email_message", "arguments": args}
    assert body(route.calls.last.request) == {"ref": "gmail.send_email_message", "arguments": args, "approval_id": "ap_9"}


@pytest.mark.parametrize("ref", ["exa", "search", ".search", "exa.", ""])
def test_run_refuses_a_ref_that_names_no_single_operation_before_sending(api, client, ref):
    route = api.post("/v1/run").respond(json=_run_result("exa.search", []))
    with pytest.raises(nc.InvalidRequest) as info:
        nc.run(ref, {"query": "q"})
    assert info.value.field == "ref" and "exa.search" in info.value.next_step
    assert route.call_count == 0


def test_run_takes_a_string_ref(api, client):
    route = api.post("/v1/run").respond(json=_run_result("exa.search", []))
    with pytest.raises(TypeError):
        nc.run(nc.Connection.from_name("exa"), {"query": "q"})
    assert route.call_count == 0


def test_an_integration_info_names_the_integration_to_connect(api, client):
    api.get("/v1/integrations").respond(json=listing(integration_row("gmail")))
    api.get("/v1/connections/mail").respond(404, json={"error": {"type": "not_found", "message": "No"}})
    create = api.post("/v1/connections").respond(201, json={**PENDING, "name": "mail"})
    [gmail] = nc.Connection.integrations("gmail")
    nc.Connection.from_name("mail", integration=gmail, create_if_missing=True, user=USER_ID).hydrate()
    assert body(create.calls.last.request) == {"name": "mail", "integration": "gmail"}


# --- Connection --------------------------------------------------------------

def test_from_name_is_lazy_and_creates_a_pending_connection_on_first_use(api, client):
    missing = api.get("/v1/connections/gmail").respond(404, json={"error": {"type": "not_found", "message": "No"}})
    create = api.post("/v1/connections").respond(201, json=PENDING)
    with nc.as_user(USER_ID):
        gmail = nc.Connection.from_name("gmail", integration="gmail", create_if_missing=True,
                                        reason="Send your summary")
    assert missing.call_count == 0 and not gmail.is_hydrated
    assert gmail.connected is False and gmail.status == "pending"
    assert gmail.connect_url == "https://noclick.com/c/xyz"
    assert body(create.calls.last.request) == {"name": "gmail", "integration": "gmail", "reason": "Send your summary"}
    assert create.calls.last.request.headers["NoClick-User"] == USER_ID


def test_mark_test_account_lets_a_preview_write_through_it_and_unmarks(api, client):
    route = api.post("/v1/connections/con_1/test_account").mock(side_effect=[
        httpx.Response(200, json={**CONN, "test_account": True}),
        httpx.Response(200, json={**CONN, "test_account": False}),
    ])
    gmail = nc.Connection.from_id("con_1")
    assert gmail.mark_test_account().test_account is True
    assert body(route.calls.last.request) == {"test_account": True}
    assert gmail.mark_test_account(False).test_account is False
    assert body(route.calls.last.request) == {"test_account": False}


def test_an_app_account_says_who_shared_it_its_live_health_the_checks_whole_answer_and_renames(api, client):
    app = {**CONN, "id": "credential:cred_1", "name": "Team inbox", "origin": "app", "access": "edit",
           "shared": {"with": "workspace", "by": {"name": "Priya Raman", "email": "priya@example.test"}},
           "health": {"healthy": False, "status": "failed", "hint": "Scan the code again."}}
    api.get("/v1/connections/credential%3Acred_1").respond(json=app)
    api.post("/v1/connections/credential%3Acred_1/verify").respond(json={**app, "verification": {
        "reachable": True, "samples": [{"label": "site", "value": None}], "message": "ok", "noun": "repositories",
        "total": 9, "account_label": "octo", "proves": "account", "error": None}})
    rename = api.patch("/v1/connections/credential%3Acred_1").respond(json={**app, "name": "Sales inbox"})

    account = nc.Connection.get("credential:cred_1")
    assert (account.shared.with_, account.shared.by_name, account.shared.by_email) == (
        "workspace", "Priya Raman", "priya@example.test")
    assert (account.health.healthy, account.health.status, account.health.hint) == (
        False, "failed", "Scan the code again.")
    check = account.verify()
    assert (check.noun, check.total, check.account_label, check.proves, check.error) == (
        "repositories", 9, "octo", "account", None)
    assert account.rename("Sales inbox").name == "Sales inbox"
    assert body(rename.calls.last.request) == {"name": "Sales inbox"}
    # A named connection, whose kind of account has no live check, reads neither.
    api.get("/v1/connections/con_1").respond(json={**CONN, "shared": None, "health": None})
    named = nc.Connection.get("con_1")
    assert (named.shared, named.health) == (None, None)


def test_from_name_without_create_raises_not_found_and_a_concurrent_create_is_read(api, client):
    api.get("/v1/connections/gmail").respond(404, json={"error": {"type": "not_found", "message": "No"}})
    try:
        nc.Connection.from_name("gmail").hydrate()
    except nc.NotFound:
        pass
    else:
        raise AssertionError("expected NotFound")
    api.post("/v1/connections").respond(409, json={"error": {"type": "conflict", "message": "exists",
                                                             "existing_id": "con_1"}})
    api.get("/v1/connections/con_1").respond(json=CONN)
    assert nc.Connection.from_name("gmail", integration="gmail", create_if_missing=True).id == "con_1"
    try:
        nc.Connection.from_name("gmail", create_if_missing=True)
    except ValueError as e:
        assert "integration=" in str(e)
    else:
        raise AssertionError("expected ValueError")


def test_wait_follows_the_open_links_operation_to_the_connected_connection(api, client):
    get = api.get("/v1/connections/gmail").respond(json=PENDING)
    reload = api.get("/v1/connections/con_1").respond(json=CONN)
    api.get("/v1/operations/op_c/wait").respond(
        json=operation(op_id="op_c", kind="credential.connect", status="succeeded", result={"connection": CONN})
    )
    gmail = nc.Connection.from_name("gmail", user=USER_ID)
    assert gmail.wait() is gmail and gmail.connected and gmail.account == "ana@gmail.com"
    assert get.call_count == 1 and reload.call_count == 1  # addressed by id once known
    assert gmail.wait() is gmail and reload.call_count == 1  # already connected


def test_a_fresh_link_updates_the_connection_and_wait_follows_it(api, client):
    """connect_link() makes the new link the connection's own, so wait() waits on
    it (not the lapsed one it was loaded with) with no refresh()."""
    api.get("/v1/connections/gmail").respond(json=PENDING)
    api.post("/v1/connections/con_1/connect_links").respond(json={
        "object": "connect_link", "id": "lnk_2", "url": "https://noclick.com/c/new", "expires_at": "2026-10-09T10:00:00Z",
        "connection": "gmail", "operation": operation(op_id="op_d", kind="credential.connect"),
    })
    lapsed = api.get("/v1/operations/op_c/wait").respond(json=operation(
        op_id="op_c", kind="credential.connect", status="expired",
        error={"type": "expired", "message": "The connect link expired before anyone connected an account."}))
    fresh = api.get("/v1/operations/op_d/wait").respond(
        json=operation(op_id="op_d", kind="credential.connect", status="succeeded", result={"connection": CONN}))
    api.get("/v1/connections/con_1").respond(json=CONN)
    gmail = nc.Connection.from_name("gmail", user=USER_ID)
    assert gmail.connect_url == "https://noclick.com/c/xyz"
    link = gmail.connect_link()
    assert gmail.connect_url == link.url == "https://noclick.com/c/new"
    assert gmail.wait() is gmail and gmail.connected
    assert fresh.call_count == 1 and lapsed.call_count == 0


def test_wait_follows_the_connection_past_a_lapsed_link(api, client, monkeypatch):
    """A link that lapses while a fresh one is open (made anywhere) hands the wait
    to the fresh one; one that lapses with none open raises OperationExpired; an
    account connected through another link ends a wait on the newest one."""
    fresh_pending = {**PENDING, "connect_link": {**PENDING["connect_link"], "id": "lnk_2", "operation_id": "op_d"}}
    reads = api.get("/v1/connections/con_1").mock(side_effect=[
        httpx.Response(200, json=fresh_pending), httpx.Response(200, json=CONN)])
    api.get("/v1/connections/gmail").respond(json=PENDING)
    api.get("/v1/operations/op_c/wait").respond(json=operation(
        op_id="op_c", kind="credential.connect", status="expired",
        error={"type": "expired", "message": "The connect link expired before anyone connected an account."}))
    api.get("/v1/operations/op_d/wait").respond(
        json=operation(op_id="op_d", kind="credential.connect", status="succeeded", result={"connection": CONN}))
    gmail = nc.Connection.from_name("gmail", user=USER_ID)
    assert gmail.wait() is gmail and gmail.connected and reads.call_count == 2

    # Lapsed with nothing open: the documented OperationExpired.
    api.get("/v1/connections/con_2").respond(json={**PENDING, "id": "con_2", "connect_link": None})
    stale = nc.Connection._new(raw={**PENDING, "id": "con_2"}, client=None, user=USER_ID)
    with pytest.raises(nc.OperationExpired):
        stale.wait()

    # Connected through the older link while this wait watched the newest: the reload ends it.
    monkeypatch.setattr("noclick.connection._LONG_POLL_S", 0.01)
    api.get("/v1/connections/con_3").respond(json={**CONN, "id": "con_3"})
    api.get("/v1/operations/op_e/wait").respond(json=operation(op_id="op_e", kind="credential.connect"))
    watching = nc.Connection._new(raw={**PENDING, "id": "con_3", "connect_link": {
        **PENDING["connect_link"], "operation_id": "op_e"}}, client=None, user=USER_ID)
    assert watching.wait(timeout=30).connected


def test_connect_link_is_an_operation_that_waits_to_the_connection(api, client):
    api.get("/v1/connections/con_1").respond(json=CONN)
    route = api.post("/v1/connections/con_1/connect_links").respond(json={
        "object": "connect_link", "url": "https://noclick.com/c/xyz", "expires_at": "2026-09-26T10:00:00Z",
        "connection": "gmail", "operation": operation(op_id="op_c", kind="credential.connect"),
    })
    api.get("/v1/operations/op_c/wait").respond(
        json=operation(op_id="op_c", kind="credential.connect", status="succeeded", result={"connection": CONN})
    )
    link = nc.Connection.get("con_1").connect_link(redirect_url="https://acme.ai/done", reason="Reconnect")
    assert isinstance(link, nc.ConnectLink) and isinstance(link, nc.Operation)
    assert link.url == "https://noclick.com/c/xyz" and str(link) == link.url and link.connection == "gmail"
    assert link.status == "awaiting_human" and link.id == "op_c"
    assert body(route.calls.last.request) == {"redirect_url": "https://acme.ai/done", "reason": "Reconnect"}
    assert route.calls.last.request.headers["NoClick-User"] == USER_ID  # the connection's user
    connection = link.wait()
    assert isinstance(connection, nc.Connection) and connection.id == "con_1"
    assert connection.verification.reachable is True


def test_request_sends_to_the_user_by_default(api, client):
    read = api.get("/v1/connections/gmail").respond(json=PENDING)
    route = api.post("/v1/connections/gmail/connect_links").respond(json={
        "object": "connect_link", "url": "u", "expires_at": None, "operation": "op_c",
        "delivery": {"delivered_via": ["email"]},
    })
    gmail = nc.Connection.from_name("gmail", user="user_42")
    link = gmail.request(reason="to send mail")
    assert body(route.calls.last.request) == {"reason": "to send mail", "send_to": {"user": True}}
    # Acting needs no read: by name, for the user it was obtained under.
    assert link.id == "op_c" and route.calls.last.request.headers["NoClick-User"] == "user_42"
    assert read.call_count == 0
    assert link.delivered_via == ["email"] and link.undelivered == []
    gmail.request(send_to="ana@example.com")
    assert body(route.calls.last.request)["send_to"] == {"email": "ana@example.com"}
    # A connection of the account's own goes to the owner.
    nc.Connection.from_name("gmail", user=None).request(send_to="owner")
    assert body(route.calls.last.request)["send_to"] == {"owner": True}
    assert "NoClick-User" not in route.calls.last.request.headers


def test_a_link_whose_email_failed_says_so(api, client):
    route = api.post("/v1/connections/gmail/connect_links").respond(json={
        "object": "connect_link", "url": "u", "expires_at": None, "operation": "op_c",
        "delivery": {"delivered_via": [], "undelivered": [{"channel": "email", "reason": "The email could not be sent."}]},
    })
    gmail = nc.Connection.from_name("gmail", user="user_42")
    failed = gmail.request()
    assert failed.delivered_via == []
    assert failed.undelivered == [{"channel": "email", "reason": "The email could not be sent."}]
    route.respond(json={"object": "connect_link", "url": "u", "expires_at": None, "operation": "op_d"})
    unsent = gmail.connect_link()
    assert unsent.delivered_via == [] and unsent.undelivered == []


def test_create_with_data_list_get(api, client):
    create = api.post("/v1/connections").respond(201, json=CONN)
    lst = api.get("/v1/connections").respond(json={"object": "list", "data": [CONN], "next_cursor": None})
    api.get("/v1/connections/con_1").respond(json=CONN)
    connection = nc.Connection.create("openai", credential_type="OpenAIKey", data={"api_key": "sk-x"})
    assert body(create.calls.last.request) == {"name": "openai", "credential_type": "OpenAIKey",
                                               "data": {"api_key": "sk-x"}}
    assert connection.integration == "gmail" and connection.connected
    [listed] = nc.Connection.list(integration="gmail")
    assert lst.calls.last.request.url.params["integration"] == "gmail" and listed == connection
    assert nc.Connection.get("con_1").name == "gmail"


def test_run_and_lookup_act_in_the_connections_account(api, client):
    run = api.post("/v1/connections/gmail/operations/send_email/run").respond(
        json={"object": "operation_result", "connection": "gmail", "result": {"id": "msg_1"}})
    lookup = api.post("/v1/connections/gmail/lookup").respond(json={
        "object": "lookup_result", "field": "label", "options": [{"value": "L1", "label": "Inbox"}],
        "next_page_token": "p2",
    })
    gmail = nc.Connection.from_name("gmail", user=USER_ID)
    assert gmail.run("send_email", {"to": "a@b.c"}) == {"id": "msg_1"}
    assert body(run.calls.last.request) == {"arguments": {"to": "a@b.c"}}
    assert run.calls.last.request.headers["NoClick-User"] == USER_ID
    options = gmail.lookup("label", search="In")
    [option] = options
    assert (option.value, option.label, options.next_page_token) == ("L1", "Inbox", "p2")
    assert body(lookup.calls.last.request) == {"field": "label", "search": "In"}


def test_a_pending_run_raises_needs_connection_with_the_link(api, client):
    api.post("/v1/connections/gmail/operations/send_email/run").respond(424, json={"error": {
        "type": "needs_connection", "message": "No account yet.", "connection": "gmail", "integration": "gmail",
        "connect_url": "https://noclick.com/c/xyz", "operation_id": "op_c"}})
    try:
        nc.Connection.from_name("gmail").run("send_email", {})
    except nc.NeedsConnection as e:
        assert (e.connection, e.integration, e.connect_url) == ("gmail", "gmail", "https://noclick.com/c/xyz")
    else:
        raise AssertionError("expected NeedsConnection")


def test_verify_token_import_delete_act_for_the_connections_user(api, client):
    api.get("/v1/connections/con_1").respond(json=CONN)
    verify = api.post("/v1/connections/con_1/verify").respond(
        json={**CONN, "verification": {"reachable": False, "samples": [], "message": "Token revoked"}}
    )
    token = api.post("/v1/connections/con_1/token").respond(
        json={"access_token": "ya29", "token_type": "Bearer", "expires_at": "2026-09-25T11:00:00Z"}
    )
    imported = api.post("/v1/connections/con_1/import").respond(json={**CONN, "account": "bo@gmail.com"})
    delete = api.delete("/v1/connections/con_1").respond(json={"object": "connection", "id": "con_1", "deleted": True})
    connection = nc.Connection.get("con_1")
    verification = connection.verify()
    assert verification.reachable is False and verification.message == "Token revoked"
    assert connection.verification.reachable is False
    assert verify.calls.last.request.headers["NoClick-User"] == USER_ID  # from user_id
    t = connection.token()
    assert t.access_token == "ya29" and t.expires_at.hour == 11 and "ya29" not in repr(t)
    assert connection.import_({"refresh_token": "r"}).account == "bo@gmail.com"
    assert body(imported.calls.last.request) == {"data": {"refresh_token": "r"}}
    assert connection.delete() is None and delete.call_count == 1 and token.call_count == 1


def test_connect_link_retry_keeps_idempotency(api, client):
    route = api.post("/v1/connections/gmail/connect_links").mock(side_effect=[
        httpx.Response(503),
        httpx.Response(200, json={"object": "connect_link", "url": "u", "expires_at": None, "operation": "op_c"}),
    ])
    nc.Connection.from_name("gmail").connect_link()
    assert len({c.request.headers["Idempotency-Key"] for c in route.calls}) == 1


def test_a_lazy_connection_is_created_by_a_write_and_used_when_its_name_is_taken(api, client):
    """A write (a link, an import, a delete) creates a lazy create_if_missing
    connection outright, so it needs only credentials:request; a taken name is used once it's
    the integration the code named."""
    read = api.get("/v1/connections/gmail").respond(json=PENDING)
    create = api.post("/v1/connections").mock(side_effect=[
        httpx.Response(201, json=PENDING),
        httpx.Response(409, json={"error": {"type": "conflict", "message": "exists", "existing_id": "con_9"}}),
        httpx.Response(409, json={"error": {"type": "conflict", "message": "exists", "existing_id": "con_9"}}),
    ])
    existing = api.get("/v1/connections/con_9").respond(json={**PENDING, "id": "con_9"})
    link = api.post("/v1/connections/con_1/connect_links").respond(json={"url": "u", "operation": "op_c"})
    taken = api.post("/v1/connections/con_9/connect_links").respond(json={"url": "u2", "operation": "op_d"})
    gmail = nc.Connection.from_name("gmail", integration="gmail", create_if_missing=True)
    assert gmail.connect_link().url == "u" and gmail.connect_link().url == "u"
    assert create.call_count == 1 and link.call_count == 2
    other = nc.Connection.from_name("gmail", integration="gmail", create_if_missing=True, data={"api_key": "k"})
    assert other.connect_link().url == "u2" and taken.call_count == 1 and existing.call_count == 1
    assert body(create.calls.last.request) == {"name": "gmail", "integration": "gmail", "data": {"api_key": "k"}}
    assert read.call_count == 0
    # A taken name of another integration is refused before anything is written to it.
    with pytest.raises(nc.Conflict) as wrong:
        nc.Connection.from_name("gmail", integration="slack", create_if_missing=True).connect_link()
    assert (wrong.value.field, wrong.value.integration) == ("integration", "gmail") and taken.call_count == 1


def test_only_names_some_operations_of_a_lazy_connection(api, client):
    api.get("/v1/connections/stripe").respond(404, json={"error": {"type": "not_found", "message": "No"}})
    api.post("/v1/connections").respond(201, json={**CONN, "id": "con_s", "name": "stripe", "integration": "stripe"})
    defs = api.post("/v1/toolkits/definitions").respond(json={"object": "tool_definitions", "tools": []})
    stripe = nc.Connection.from_name("stripe", integration="stripe", create_if_missing=True)
    toolkit = nc.Toolkit(["search", stripe.only("list_invoices", "get_invoice")])
    assert toolkit.tools == ["search", "stripe.list_invoices", "stripe.get_invoice"]
    toolkit.definitions()
    assert body(defs.calls.last.request)["tools"] == ["search", "stripe.list_invoices", "stripe.get_invoice"]
    try:
        stripe.only()
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError")


APP_ID = "credential:9b2a1c5e-7d9f-4a31-8f6d-3f1d2c4b8a7e"
FROM_THE_APP = {**CONN, "id": APP_ID, "name": "Gmail (ana@gmail.com)", "user_id": None, "origin": "app",
                "access": "owner", "approval_operations": []}


def test_accounts_connected_in_the_app_list_load_and_run_by_their_credential_ref(api, client):
    lst = api.get("/v1/connections").respond(json=listing({**CONN, "origin": "api", "access": "owner",
                                                           "approval_operations": []}, FROM_THE_APP))
    api.get(f"/v1/connections/{APP_ID}").respond(json=FROM_THE_APP)
    run = api.post(f"/v1/connections/{APP_ID}/operations/send_email/run").respond(
        json={"object": "operation_result", "connection": APP_ID, "result": {"id": "msg_1"}})
    direct = api.post("/v1/run").respond(json={"object": "operation_result", "ref": f"{APP_ID}.send_email",
                                               "connection": APP_ID, "result": {"id": "msg_2"}})
    named, app = nc.Connection.list()
    assert (named.origin, app.origin, app.id, app.access) == ("api", "app", APP_ID, "owner")
    nc.Connection.list(origin="app")
    assert lst.calls.last.request.url.params["origin"] == "app"
    gmail = nc.Connection.from_id(APP_ID)
    assert gmail.name == "Gmail (ana@gmail.com)" and gmail.approval_operations == []
    assert gmail.run("send_email", {"to": "a@b.c"}) == {"id": "msg_1"}
    assert run.call_count == 1
    assert nc.run(f"{APP_ID}.send_email", {"to": "a@b.c"}) == {"id": "msg_2"}
    assert body(direct.calls.last.request)["ref"] == f"{APP_ID}.send_email"


TEAM = "5c0d9e4a-7b1f-4e2a-9c3d-8f6b2a1e4d70"


def test_an_account_shared_with_a_team_is_read_and_run_in_that_teams_workspace(api, client):
    shared = {**FROM_THE_APP, "access": "view", "organization_id": TEAM}
    lst = api.get("/v1/connections").respond(json=listing(shared))
    api.get(f"/v1/connections/{APP_ID}").respond(json=shared)
    run = api.post(f"/v1/connections/{APP_ID}/operations/send_email/run").respond(
        json={"object": "operation_result", "connection": APP_ID, "result": {"id": "msg_1"}})
    [team_account] = nc.Connection.list(organization_id=TEAM)
    assert lst.calls.last.request.url.params["organization_id"] == TEAM
    assert (team_account.organization_id, team_account.access) == (TEAM, "view")
    # What it does goes to the workspace it was read in, and one named by id with its workspace goes there too.
    assert team_account.run("send_email", {"to": "a@b.c"}) == {"id": "msg_1"}
    nc.Connection.from_id(APP_ID, organization_id=TEAM).run("send_email", {"to": "a@b.c"})
    assert [c.request.url.params.get("organization_id") for c in run.calls] == [TEAM, TEAM]
    assert nc.Connection.get(APP_ID, organization_id=TEAM).organization_id == TEAM
    # The account's own carry none.
    own = api.get("/v1/connections/gmail").respond(json={**CONN, "organization_id": None})
    assert nc.Connection.get("gmail").organization_id is None
    assert "organization_id" not in own.calls.last.request.url.params


def test_an_account_agent_takes_an_app_connection_as_a_tool_by_its_id(api, client):
    from platform_helpers import agent_row

    api.get(f"/v1/connections/{APP_ID}").respond(json=FROM_THE_APP)
    create = api.post("/v1/agents").respond(json=agent_row(id="ag_1", name="assistant"))
    gmail = nc.Connection.from_id(APP_ID)
    nc.Agent.create("assistant", instructions="hi",
                    tools=[gmail, gmail.only("send_email_message"), f"{APP_ID}.list_messages"])
    assert body(create.calls.last.request)["tools"] == [
        APP_ID, f"{APP_ID}.send_email_message", f"{APP_ID}.list_messages"]


def test_require_approval_sends_the_operations_and_keeps_the_answer(api, client):
    route = api.post("/v1/connections/gmail/require_approval").respond(
        json={**CONN, "approval_operations": ["delete_message", "send_email_message"]})
    gmail = nc.Connection.from_name("gmail")
    assert gmail.require_approval("send_email_message", "delete_message") is gmail
    assert body(route.calls.last.request) == {"operations": ["send_email_message", "delete_message"]}
    assert gmail.approval_operations == ["delete_message", "send_email_message"]


LIFT = {"object": "approval_policy_change", "id": "chg_1", "batch_id": "chg_1", "scope": "credential",
        "scope_id": "c1", "kind": "credential_rule", "target": "operations",
        "before": {"operations": ["automation-gmail.send_email_message"]}, "after": {"operations": []},
        "loosens": True, "changed_by": "key", "key_id": "key_1", "effective_at": "2026-11-22T09:10:00+00:00",
        "until": None, "pending": True, "undone_at": None, "undone_by": None, "created_at": "2026-11-22T09:00:00+00:00"}


def test_lift_approval_names_what_it_lifts_and_returns_the_change(api, client):
    route = api.delete("/v1/connections/gmail/require_approval").respond(
        json={**CONN, "approval_operations": ["send_email_message"], "approval_changes": [LIFT]})
    gmail = nc.Connection.from_name("gmail")
    [change] = gmail.lift_approval("send_email_message", "delete_message")
    assert route.calls.last.request.url.params["operations"] == "send_email_message,delete_message"
    assert (change.id, change.scope, change.kind, change.target, change.pending) == (
        "chg_1", "credential", "credential_rule", "operations", True)
    assert change.effective_at.isoformat() == "2026-11-22T09:10:00+00:00"
    # Waiting out its undo window, the rule still holds what was lifted.
    assert gmail.approval_operations == ["send_email_message"]
    # Naming none lifts every one (by its id, now it's read).
    by_id = api.delete(f"/v1/connections/{CONN['id']}/require_approval").respond(
        json={**CONN, "approval_changes": [LIFT]})
    gmail.lift_approval()
    assert "operations" not in by_id.calls.last.request.url.params


PLAN_USAGE = {
    "object": "plan_usage", "connection": "credential:c1", "integration": "anthropic", "state": "near",
    "plan": {"tier": "max_20x", "label": "Ultra", "runs": ["claude_code"], "refusal": None},
    "windows": [{"kind": "five_hour", "label": "5-hour", "models": [], "used": 0.91, "left": 0.09,
                 "resets_at": "2026-11-17T14:00:00+00:00", "state": "near"},
                {"kind": "weekly_model", "label": "Opus weekly", "models": ["Opus"], "used": 0.4, "left": 0.6,
                 "resets_at": "2026-11-20T17:00:00+00:00", "state": "ok"}],
    "tightest": {"kind": "five_hour", "label": "5-hour", "models": [], "used": 0.91, "left": 0.09,
                 "resets_at": "2026-11-17T14:00:00+00:00", "state": "near"},
    "available_at": None, "as_of": "2026-11-17T12:00:00+00:00", "source": "provider",
    "next_steps": [{"kind": "connection", "label": "Run on Work key", "until": None, "pays": "per_use",
                    "connection": {"id": "credential:k1", "name": "Work key", "integration": "anthropic",
                                   "credential_type": "agent_anthropic"}},
                   {"kind": "connect", "label": "Connect another", "until": None, "connection": None, "pays": None}],
}


def test_a_plans_tier_and_usage_read_as_the_api_works_them_out(api, client):
    plan = {**CONN, "id": "credential:c1", "credential_type": "agent_claude_code_oauth",
            "plan": PLAN_USAGE["plan"], "usage": {k: PLAN_USAGE[k] for k in ("state", "tightest", "available_at",
                                                                             "as_of")}}
    api.get("/v1/connections/credential:c1").respond(json=plan)
    route = api.get("/v1/connections/credential:c1/usage").respond(json=PLAN_USAGE)
    connection = nc.Connection.get("credential:c1")
    assert (connection.plan.tier, connection.plan.label, connection.plan.runs) == ("max_20x", "Ultra", ["claude_code"])
    summary = connection.usage_summary
    assert (summary.state, summary.tightest.label, summary.tightest.left) == ("near", "5-hour", 0.09)

    used = connection.usage(model="claude-opus-5-5", fresh=True)
    assert dict(route.calls.last.request.url.params) == {"model": "claude-opus-5-5", "fresh": "true"}
    assert (used.state, used.source, used.plan.label, used.connection) == ("near", "provider", "Ultra", "credential:c1")
    assert [w.label for w in used.windows] == ["5-hour", "Opus weekly"] and used.windows[1].models == ["Opus"]
    assert used.tightest.resets_at.hour == 14 and used.available_at is None
    assert [(s.kind, s.pays, s.state) for s in used.next_steps] == [("connection", "per_use", None),
                                                                     ("connect", None, None)]
    assert used.integration == "anthropic"
    assert used.next_steps[0].connection["name"] == "Work key"
    connection.usage()
    assert "fresh" not in route.calls.last.request.url.params and "model" not in route.calls.last.request.url.params

    # Anything but a plan has neither.
    api.get("/v1/connections/con_1").respond(json=CONN)
    other = nc.Connection.get("con_1")
    assert other.plan is None and other.usage_summary is None


# --- signing your account in to an app ------------------------------------------

APP_CONN = {**CONN, "id": "credential:c1", "name": "ada@example.test", "origin": "app", "credential_id": "c1"}


def test_sign_in_sends_the_code_and_its_secrets_and_answers_the_connection(api, client):
    route = api.post("/v1/connections/sign_ins").respond(json={
        "object": "sign_in", "id": None, "status": "connected", "provider": "google", "connection": APP_CONN,
        "account": {"email": "ada@example.test"}, "choose": None})

    signed_in = nc.Connection.sign_in("google", code="g-code", redirect_uri="https://app.test/cb",
                                      scopes=("email", "profile"), name="Mine", inputs={"region": "eu"},
                                      oauth_app={"client_id": "own", "client_secret": "own-secret"})

    assert body(route.calls.last.request) == {"provider": "google", "code": "g-code", "redirect_uri": "https://app.test/cb",
                           "scopes": ["email", "profile"], "name": "Mine", "inputs": {"region": "eu"},
                           "client": {"client_id": "own", "client_secret": "own-secret"}}
    assert "NoClick-User" not in route.calls.last.request.headers
    assert (signed_in.status, signed_in.provider, signed_in.id) == ("connected", "google", None)
    assert isinstance(signed_in.connection, nc.Connection) and signed_in.connection.id == "credential:c1"
    assert signed_in.account == {"email": "ada@example.test"} and signed_in.choices == []


def test_a_sign_in_that_asks_for_a_pick_is_finished_with_it(api, client):
    api.post("/v1/connections/sign_ins").respond(json={
        "object": "sign_in", "id": "si_1", "status": "choose", "provider": "supabase", "connection": None,
        "account": {}, "choose": {"what": "project", "choices": [{"id": "proj-a", "name": "Alpha"},
                                                                  {"id": "proj-b", "name": "Beta"}]}})
    finish = api.post("/v1/connections/sign_ins/si_1/finish").respond(json={
        "object": "sign_in", "id": None, "status": "connected", "provider": "supabase", "connection": APP_CONN,
        "account": {"project_url": "https://proj-b.supabase.co"}, "choose": None})

    signed_in = nc.Connection.sign_in("supabase", code="s", redirect_uri="https://app.test/cb", code_verifier="v")
    assert (signed_in.status, signed_in.what, [c["id"] for c in signed_in.choices]) == (
        "choose", "project", ["proj-a", "proj-b"])
    done = signed_in.finish("proj-b")

    assert body(finish.calls.last.request) == {"choice": "proj-b"}
    assert done.status == "connected" and done.connection.id == "credential:c1"
    with pytest.raises(nc.InvalidRequest):
        done.finish("proj-a")


def test_a_pick_is_finished_by_the_sign_ins_id_alone(api, client):
    finish = api.post("/v1/connections/sign_ins/si_9/finish").respond(json={
        "object": "sign_in", "id": None, "status": "connected", "provider": "facebook", "connection": APP_CONN,
        "account": {"instagram_username": "ada"}, "choose": None})

    done = nc.Connection.finish_sign_in("si_9", "ig-2")

    assert body(finish.calls.last.request) == {"choice": "ig-2"}
    assert done.status == "connected" and done.account == {"instagram_username": "ada"}


def _waiting(sign_in_id="si_w", **shown):
    return {"object": "sign_in", "id": sign_in_id, "status": "waiting", "provider": "codex", "credential": None,
            "connection": None, "account": {}, "choose": None,
            "waiting": {"way": "device", "user_code": "ABCD-1234", "verification_url": "https://auth.openai.com/codex/device",
                        "verification_url_complete": None, "authorize_url": None, "interval": 0,
                        "expires_at": "2026-11-24T12:00:00+00:00", **shown}}


def test_a_device_codes_sign_in_starts_and_is_waited_on_until_the_person_enters_it(api, client):
    start = api.post("/v1/connections/sign_ins").respond(json=_waiting())
    polls = api.post("/v1/connections/sign_ins/si_w/finish").mock(side_effect=[
        httpx.Response(200, json=_waiting()),
        httpx.Response(200, json={"object": "sign_in", "id": None, "status": "connected", "provider": "codex",
                                  "credential": {"id": "c1", "name": "ChatGPT (Codex)",
                                                 "credential_type": "agent_codex_oauth"},
                                  "connection": APP_CONN, "account": {}, "choose": None, "waiting": None}),
    ])

    chatgpt = nc.Connection.sign_in("codex", name="ChatGPT")
    assert body(start.calls.last.request) == {"provider": "codex", "name": "ChatGPT"}
    assert (chatgpt.status, chatgpt.way, chatgpt.user_code, chatgpt.verification_url, chatgpt.interval) == (
        "waiting", "device", "ABCD-1234", "https://auth.openai.com/codex/device", 0)
    done = chatgpt.wait()

    assert polls.call_count == 2 and all(body(call.request) is None or body(call.request) == {} for call in polls.calls)
    assert done.status == "connected" and done.credential["credential_type"] == "agent_codex_oauth"


def test_a_claude_plans_sign_in_finishes_with_the_code_its_page_showed(api, client):
    api.post("/v1/connections/sign_ins").respond(json=_waiting(
        way="code", user_code=None, verification_url=None, authorize_url="https://claude.ai/oauth/authorize?x=1"))
    finish = api.post("/v1/connections/sign_ins/si_w/finish").respond(json={
        "object": "sign_in", "id": None, "status": "connected", "provider": "claude_code",
        "credential": {"id": "c1", "name": "Claude", "credential_type": "agent_claude_code_oauth"},
        "connection": APP_CONN, "account": {}, "choose": None, "waiting": None})

    claude = nc.Connection.sign_in("claude_code", reconnect="credential:c1")
    with pytest.raises(nc.InvalidRequest):
        claude.wait()
    done = claude.finish(code="pasted#state")

    assert body(finish.calls.last.request) == {"code": "pasted#state"}
    assert done.status == "connected"
