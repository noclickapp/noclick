"""Invites, links and a workflow's accounts: a workflow's runs a page at a time and the accounts its steps use; a
request for someone else's account and whether one works where it's used; joining through a share's or a team's
invite, a team's picture and single sign-on; the account's invite link; and claiming an agent's own account."""

import noclick as nc
from platform_helpers import body, listing

WF = "6f1c2d3e-4a5b-4c6d-8e7f-9a0b1c2d3e4f"


def test_a_workflows_runs_read_a_page_at_a_time_and_its_accounts_by_name_and_owner(api, client):
    runs = api.get(f"/v1/workflows/{WF}/runs").respond(json=listing(
        {"object": "workflow_run", "id": "run_1", "status": "failed"}, next_cursor="c2"))
    workflow = nc.Workflow.from_id(WF)
    page = workflow.runs_page(status="failed", limit=50, cursor="c1")
    assert (page.data[0].id, page.next_cursor) == ("run_1", "c2")
    params = runs.calls.last.request.url.params
    assert (params["status"], params["limit"], params["cursor"]) == ("failed", "50", "c1")

    api.get(f"/v1/workflows/{WF}/connections").respond(json={"credentials": [
        {"id": "cred_1", "name": "Ops Gmail", "credential_type": "gmail_oauth", "owned_by_me": False,
         "owner_name": "dana"}]})
    [account] = workflow.connections()
    assert (account.id, account.credential_type, account.owned_by_me, account.owner_name) == (
        "cred_1", "gmail_oauth", False, "dana")


def test_asking_someone_for_their_account_and_checking_one_works_where_its_used(api, client):
    asked = api.post("/v1/connections/connect_links").respond(201, json={
        "object": "credential_request", "success": True, "provide_url": "https://noclick.com/credential/provide/tok",
        "request": {"id": "req_1", "credential_type": "slack_oauth", "target_email": "sam@example.com",
                    "status": "pending", "expires_at": "2026-12-01T00:00:00Z"}})
    request = nc.ConnectLink.create("slack_oauth", email="sam@example.com", message="For the digest")
    assert body(asked.calls.last.request) == {"credential_type": "slack_oauth", "target_email": "sam@example.com",
                                              "message": "For the digest"}
    assert (request.id, request.url, request.status) == ("req_1", "https://noclick.com/credential/provide/tok",
                                                         "pending")

    checked = api.get("/v1/connections/conn_1/access").respond(json={"runs_for_owner": False, "reason": "Not selected."})
    access = nc.Connection.from_id("conn_1").access_for(workflow=WF, node_type="automation-gmail")
    params = checked.calls.last.request.url.params
    assert (params["workflow_id"], params["node_type"]) == (WF, "automation-gmail")
    assert (access.runs_for_owner, access.reason, access.valid) == (False, "Not selected.", None)


def test_joining_through_a_shares_invite_and_a_teams_invite_picture_and_single_sign_on(api, client):
    api.post("/v1/shares/invites/tok_s/accept").respond(json={
        "object": "share_invite", "workflow_id": WF, "workflow_name": "Intake", "refresh_session": True})
    joined = nc.Share.accept_invite("tok_s")
    assert (joined.workflow_id, joined.workflow_name, joined.refresh_session) == (WF, "Intake", True)

    api.get("/v1/organizations/invites/tok_o").respond(json={"organization_name": "Acme", "role": "admin"})
    assert nc.Organization.invitation("tok_o")["organization_name"] == "Acme"
    icon = api.put("/v1/organizations/org_1/icon").respond(json={"icon_url": "https://x/i.png"})
    assert nc.Organization.upload_icon("org_1", "aGk=")["icon_url"] == "https://x/i.png"
    assert body(icon.calls.last.request) == {"image_data": "aGk=", "content_type": "image/png"}
    sso = api.put("/v1/organizations/org_1/sso").respond(json={"domain": "acme.com"})
    nc.Organization.configure_sso("org_1", domain="acme.com", metadata_url="https://idp.acme.com/metadata")
    assert body(sso.calls.last.request) == {"domain": "acme.com", "metadata_url": "https://idp.acme.com/metadata"}
    off = api.delete("/v1/organizations/org_1/sso").respond(json={})
    nc.Organization.disable_sso("org_1")
    assert off.call_count == 1


def test_the_accounts_invite_link_applying_one_and_claiming_an_agents_own_account(api, client):
    view = {"object": "referral", "code": "ana-k3x9", "url": "https://noclick.com/join/ana-k3x9", "share_text": "Try it",
            "reward_usd": 5, "joined": 2, "earned": 1, "earned_usd": 5, "joined_through": None, "can_apply_until": None}
    api.get("/v1/referral").respond(json=view)
    referral = nc.Referral.get()
    assert (referral.code, referral.joined, referral.earned_usd, referral.joined_through) == ("ana-k3x9", 2, 5.0, None)
    applied = api.post("/v1/referral/apply").respond(json={**view, "joined_through": {"name": "Sam", "channel": "web"}})
    assert nc.Referral.apply("sam-1").joined_through == {"name": "Sam", "channel": "web"}
    assert body(applied.calls.last.request) == {"code": "sam-1"}

    preview = api.post("/v1/agent_signups/claims/preview").respond(json={"agent": {"name": "Builder"}, "may_claim": True})
    assert nc.AgentSignup.preview_claim("tok_c")["may_claim"] is True
    assert body(preview.calls.last.request) == {"token": "tok_c"}
    answered = api.post("/v1/agent_signups/claims/answer").respond(json={"status": "claimed"})
    nc.AgentSignup.answer_claim("tok_c", "claim", accept_terms=True, key_access="build")
    assert body(answered.calls.last.request) == {"token": "tok_c", "decision": "claim", "accept_terms": True,
                                                 "key_access": "build"}
