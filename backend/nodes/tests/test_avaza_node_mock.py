"""Real Avaza factory/dispatcher/authority/admission/picker seams."""
import json
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from nodes import avaza_node as an
from nodes.core.registry import NodeFactory
from nodes.core.run_op import run_node_operation, run_node_lookup

CREDS={"credential_type":an.FAMILIES[0],"access_token":"synthetic+/=private-key","token_source":"personal_access_token"}
ACCOUNT={"AccountID":7,"CompanyName":"Private Account","SC":"private-account-secret","AccountEmail":"omit@example.test","hasStartEndTimesheets":True}
COMPANY={"CompanyID":11,"CompanyName":"Private Company","DateCreated":"2026-10-01T12:00:00","Contacts":[{"Email":"omit@example.test"}],"Comments":"omit notes"}
PROJECT={"ProjectID":22,"CompanyIDFK":11,"Title":"Private Project","ProjectCode":"Private Code","ProjectStatusCode":"custom-status","isArchived":False,"DateCreated":"2026-10-01T12:00:00Z","Notes":"omit notes","BudgetAmount":900,"ProjectHourlyRate":100,"Members":[{"UserIDFK":55,"ProjectIDFK":22,"Fullname":"Private Member","Email":"omit@example.test","RateAmount":100,"canDeleteTasks":True}]}
TASK={"TaskID":33,"ProjectIDFK":22,"Title":"Private Task","ParentTaskIDFK":None,"TaskStatusCode":"custom-task-status","isCompleteStatus":False,"DateDue":None,"Description":"omit description","AssignedToUsers":[{"Email":"omit@example.test"}],"FileAttachments":[{"url":"https://private.test/omit"}]}
ENTRY={"TimesheetEntryID":44,"ProjectIDFK":22,"CustomerIDFK":11,"UserIDFK":55,"TaskIDFK":None,"Duration":1.5,"EntryDate":"2026-10-01T00:00:00","TimesheetEntryApprovalStatusCode":"Draft","HasTimer":False,"Notes":"omit notes","Email":"omit@example.test","RateAmount":100,"InvoiceIDFK":99,"ApprovedBy":"Private Approver"}
PARENTS={"account_id":7,"company_id":11,"project_id":22}
INTERVAL={**PARENTS,"entry_date_from":"2026-10-01T00:00:00Z","entry_date_to":"2026-10-03T00:00:00+00:00"}
OPS=["test_connection","get_account","list_companies","get_company","list_projects","get_project","list_project_team","list_tasks","get_task","list_time_entries","get_time_entry"]

@pytest.fixture(autouse=True)
def ensure_native_db_pool(): yield

class Response:
    def __init__(self, body=None, *, status=200, raw=None, content_type="application/json", after=None):
        self.body,self.raw,self.status_code,self.after=body,raw,status,after
        self.headers={"Content-Type":content_type}
    async def __aenter__(self): return self
    async def __aexit__(self,*args):
        if self.after: self.after()
    async def aiter_bytes(self,chunk_size):
        assert chunk_size==65536
        yield self.raw if self.raw is not None else json.dumps(self.body).encode()

@pytest.fixture
def wire(monkeypatch):
    calls,responses=[],[]
    class Client:
        async def __aenter__(self): return self
        async def __aexit__(self,*args): pass
        def stream(self,method,url,**kwargs):
            calls.append({"method":method,"url":url,**kwargs});logging.getLogger("httpx").info("private %s",kwargs)
            response=responses.pop(0);return response if isinstance(response,Response) else Response(response)
    def client(**kwargs):
        assert kwargs=={"timeout":20.0,"follow_redirects":False,"trust_env":False}
        return Client()
    monkeypatch.setattr(an,"guarded_async_client",client)
    return SimpleNamespace(calls=calls,responses=responses)

def scoped(wire,body): wire.responses.extend([ACCOUNT,body,ACCOUNT])
def page(name,rows,*,number=1,size=20,total=None): return {name:rows,"TotalCount":len(rows) if total is None else total,"PageNumber":number,"PageSize":size}
async def run(op,args=None,*,credential_data=None,**context):
    return await run_node_operation(node_type=an.NODE_TYPE,operation=op,arguments=args or {},credential_data=credential_data or CREDS,user_id="actor",**context)

def test_real_factory_numeric_forms_eleven_operations_and_original_family():
    node=NodeFactory.create_node(node_id="native",node_type=an.NODE_TYPE,user_id="actor",node_data={"config":{"operation":"list_tasks","account_id":"7","company_id":"11","project_id":"22","page_size":"2"},"credentials":CREDS})
    assert node.config.config.account_id==7 and node.config.config.page_size==2
    defs=an.AvazaNode.get_config_schema()["$defs"]
    assert sorted(d["properties"]["operation"]["const"] for d in defs.values() if "operation" in d.get("properties",{}))==sorted(OPS)
    assert "is_complete" not in defs["AvazaTimesheetsConfig"]["properties"]
    for family in (None,"http_bearer","avaza_oauth"):
        data={"credential_id":"saved","config":{"operation":"test_connection"},"credentials":{**CREDS,"credential_type":family}}
        assert an.AvazaNode.validate_config(data)["valid"] is False
        with pytest.raises(ValueError,match="family"): an.AvazaNode.parse_config(data)

@pytest.mark.parametrize("cfg",[{"operation":"get_account","account_id":True},{"operation":"get_account","account_id":"7.5"},{"operation":"list_tasks",**PARENTS,"page_size":1001},{"operation":"get_project","project_id":22},{"operation":"get_task",**PARENTS,"task_id":"../admin"},{"operation":"list_time_entries",**INTERVAL,"entry_date_from":"2026-10-01"},{"operation":"list_time_entries",**INTERVAL,"entry_date_to":INTERVAL["entry_date_from"]},{"operation":"list_time_entries",**INTERVAL,"entry_date_to":"2028-10-03T00:00:00Z"},{"operation":"list_time_entries",**INTERVAL,"is_complete":True},{"operation":"test_connection","url":"https://evil.test"},{"operation":"approve_timesheet"},{"operation":"write_task"}])
def test_closed_scope_dates_ids_and_unexposed_writes(cfg):
    with pytest.raises(ValueError): an.AvazaNode.parse_config({"config":cfg,"credentials":CREDS})

@pytest.mark.asyncio
async def test_bearer_header_real_account_proof_privacy_and_logging_reset(wire,caplog):
    wire.responses.append(ACCOUNT)
    with caplog.at_level(logging.DEBUG): result=await run("test_connection")
    assert wire.calls==[{"method":"GET","url":an.BASE+"/api/Account","params":None,"headers":{"Authorization":"Bearer "+CREDS["access_token"],"Accept":"application/json"}}]
    assert result["data"]["AccountID"]==7 and result["data"]["account_identity_verified"] is True and result["data"]["user_identity_verified"] is False and result["data"]["entitlement_verified"] is False
    assert "CompanyName" not in result["data"] and "private-account-secret" not in json.dumps(result) and CREDS["access_token"] not in caplog.text and an._PRIVATE_REQUEST.get() is False
    logging.getLogger("httpx").warning("unrelated context");assert "unrelated context" in caplog.text
    wire.responses.append(ACCOUNT);other=await run("test_connection",credential_data={**CREDS,"token_source":"oauth2_access_token"})
    assert other["data"]["AccountID"]==7 and len(wire.calls)==2
    with pytest.raises(ValueError): await run("test_connection",credential_data={**CREDS,"access_token":"Bearer bogus-token"})
    assert len(wire.calls)==2

@pytest.mark.asyncio
async def test_company_minimal_paging_exact_echoes_continuation_and_empty(wire):
    scoped(wire,page("Companies",[COMPANY],size=1,total=2))
    scoped(wire,page("Companies",[{**COMPANY,"CompanyID":12}],number=2,size=1,total=2))
    scoped(wire,page("Companies",[]))
    first=await run("list_companies",{"account_id":"7","page_size":"1","search":"Private"});token=first["data"]["next_page_token"]
    second=await run("list_companies",{"account_id":7,"page_size":1,"search":"Private","page_token":token})
    assert wire.calls[1]["url"]==an.BASE+"/api/Company/Lookup" and wire.calls[1]["params"]=={"pageSize":"1","search":"Private","pageNumber":"1"}
    assert wire.calls[4]["params"]["pageNumber"]=="2" and second["data"]["pagination"]["provider_reported_complete"] is True
    assert second["data"]["pagination"]["snapshot_verified"] is False and first["data"]["companies"][0]["CompanyID"]==11 and "CompanyName" not in first["data"]["companies"][0]
    empty=await run("list_companies",{"account_id":7});assert empty["data"]["companies"]==[] and empty["data"]["pagination"]["provider_total"]==0
    assert len(wire.calls)==9 and "omit@example.test" not in json.dumps(first)+json.dumps(second)

@pytest.mark.asyncio
async def test_cursor_scopes_actor_key_expiry_stop_before_http(wire,monkeypatch):
    args={"account_id":7,"company_id":11,"page_size":1};scoped(wire,COMPANY);scoped(wire,page("Projects",[PROJECT],size=1,total=2))
    token=(await run("list_projects",args))["data"]["next_page_token"]
    for change in ({"account_id":8},{"company_id":12},{"include_names":True},{"include_archived":True},{"page_size":2},{"page_token":token+"x"}):
        with pytest.raises(ValueError,match="continuation"):await run("list_projects",{**args,"page_token":token,**change})
    data=an._shape(CREDS);query=an._query(an.AvazaProjectsConfig(**args))
    for changed,context in ((data,{"_user_id":"other"}),({**data,"access_token":"other-synthetic-key"},{"_user_id":"actor"})):
        with pytest.raises(ValueError,match="continuation"):an._decode_cursor(token,changed,context,query)
    now=int(an.time.time());monkeypatch.setattr(an.time,"time",lambda:now+901)
    with pytest.raises(ValueError,match="expired"):await run("list_projects",{**args,"page_token":token})
    assert len(wire.calls)==6

@pytest.mark.asyncio
async def test_project_team_task_time_exact_closed_native_contracts(wire):
    scoped(wire,PROJECT);project=await run("get_project",PARENTS)
    assert project["data"]["project"]["CompanyIDFK"]==11 and "Title" not in project["data"]["project"] and "BudgetAmount" not in project["data"]["project"]
    scoped(wire,PROJECT);team=await run("list_project_team",{**PARENTS,"include_names":True})
    assert team["data"]["members"]==[{"UserIDFK":55,"ProjectIDFK":22,"Fullname":"Private Member"}]
    scoped(wire,PROJECT);scoped(wire,page("Tasks",[TASK]));tasks=await run("list_tasks",{**PARENTS,"is_complete":False})
    assert wire.calls[-2]["params"]=={"pageSize":"20","ProjectID":"22","IncludeCustomFields":"false","isComplete":"false","pageNumber":"1"}
    assert tasks["data"]["tasks"][0]["ParentTaskIDFK"] is None and tasks["data"]["tasks"][0]["TaskStatusCode"]=="custom-task-status"
    scoped(wire,PROJECT);scoped(wire,page("Timesheets",[ENTRY]));entries=await run("list_time_entries",INTERVAL)
    assert wire.calls[-2]["params"]=={"pageSize":"20","ProjectID":"22","EntryDateFrom":INTERVAL["entry_date_from"],"EntryDateTo":INTERVAL["entry_date_to"],"includeInvoiceDetails":"false","pageNumber":"1"}
    assert entries["data"]["time_entries"][0]["Duration"]==1.5 and entries["data"]["time_entries"][0]["EntryDate"]=="2026-10-01T00:00:00"
    scoped(wire,PROJECT);scoped(wire,TASK);task=await run("get_task",{**PARENTS,"task_id":33,"include_names":True})
    scoped(wire,PROJECT);scoped(wire,ENTRY);entry=await run("get_time_entry",{**PARENTS,"time_entry_id":"44"})
    assert task["data"]["task"]["Title"]=="Private Task" and entry["data"]["time_entry"]["TimesheetEntryID"]==44
    combined=json.dumps([project,team,tasks,entries,task,entry]);assert all(value not in combined for value in ("omit@example.test","omit notes","omit description","private.test",'"RateAmount"','"canDeleteTasks"','"InvoiceIDFK"',"Private Approver"))
    assert len(wire.calls)==30

@pytest.mark.asyncio
@pytest.mark.parametrize("case",["account_before","account_after","company","project","task_parent","entry_company","team_parent"])
async def test_actual_returned_account_parent_and_requested_id_witness_failures(wire,case):
    if case=="account_before":wire.responses.append({**ACCOUNT,"AccountID":8});op="get_company";args={"account_id":7,"company_id":11};expected=1
    elif case=="account_after":wire.responses.extend([ACCOUNT,COMPANY,{**ACCOUNT,"AccountID":8}]);op="get_company";args={"account_id":7,"company_id":11};expected=3
    elif case=="company":scoped(wire,{**COMPANY,"CompanyID":12});op="get_company";args={"account_id":7,"company_id":11};expected=3
    elif case=="project":scoped(wire,{**PROJECT,"CompanyIDFK":12});op="get_task";args={**PARENTS,"task_id":33};expected=3
    elif case=="task_parent":scoped(wire,PROJECT);scoped(wire,{**TASK,"ProjectIDFK":23});op="get_task";args={**PARENTS,"task_id":33};expected=6
    elif case=="entry_company":scoped(wire,PROJECT);scoped(wire,{**ENTRY,"CustomerIDFK":12});op="get_time_entry";args={**PARENTS,"time_entry_id":44};expected=6
    else:scoped(wire,{**PROJECT,"Members":[{**PROJECT["Members"][0],"ProjectIDFK":23}]});op="list_project_team";args=PARENTS;expected=3
    with pytest.raises(an.AvazaAPIError):await run(op,args)
    assert len(wire.calls)==expected

@pytest.mark.asyncio
@pytest.mark.parametrize("body",[page("Companies",[],total=1),page("Companies",[COMPANY],total=0),page("Companies",[COMPANY,COMPANY]),page("Companies",[],number=2),{**page("Companies",[]),"PageSize":True},{"Companies":[]},{**page("Companies",[]),"status":"rejected"}])
async def test_malformed_paging_missing_totals_and_nonexecution_never_success(wire,body):
    scoped(wire,body)
    with pytest.raises(an.AvazaAPIError):await run("list_companies",{"account_id":7})
    assert len(wire.calls) in (2,3)

@pytest.mark.asyncio
@pytest.mark.parametrize("case",["403","429","503","204","html","empty","duplicate","nan","deep","oversize"])
async def test_safe_response_json_bounds_no_body_echo_or_retry(wire,monkeypatch,case):
    response=Response(ACCOUNT)
    if case.isdigit():response=Response(status=int(case),raw=b"private nonJSON",content_type="text/plain")
    if case=="html":response.headers["Content-Type"]="text/html"
    if case=="empty":response.raw=b""
    if case=="duplicate":response.raw=b'{"AccountID":7,"AccountID":8}'
    if case=="nan":response.raw=b'{"AccountID":7,"unknown":1e309}'
    if case=="deep":response.raw=b'['*40+b'0'+b']'*40
    if case=="oversize":monkeypatch.setattr(an,"MAX_BYTES",32)
    wire.responses.append(response)
    with pytest.raises(an.AvazaAPIError) as error:await run("test_connection")
    assert error.value.authority_rejected is False and CREDS["access_token"] not in str(error.value) and len(wire.calls)==1 and an._PRIVATE_REQUEST.get() is False
    if case=="403":assert error.value.http_status==403 and "403" not in str(error.value)

@pytest.mark.asyncio
async def test_staging_saved_resolution_and_picker_actor(monkeypatch, wire):
    from utils import credentials
    resolver = AsyncMock(return_value=CREDS)
    monkeypatch.setattr(credentials, "resolve_credential_with_owner_fallback", resolver)
    pool = object()
    fresh = await an._current_data(CREDS, pool=pool, user_id="actor", credential_id="saved", organization_id="org", workflow_id="wf")
    resolver.assert_awaited_once_with("saved", "actor", pool, org_id="org", workflow_id="wf")
    context = an._context(fresh, {"_user_id": "actor", "_credential_id": "forged"})
    assert context["_credential_id"] == "saved" and context["_approval_pool"] is pool
    with pytest.raises(ValueError, match="actor"):
        an._context(fresh, {"_user_id": "other"})
    for unavailable in (None, {**CREDS, "credential_type": "http_bearer"}):
        resolver.return_value = unavailable
        with pytest.raises(ValueError, match="unavailable"):
            await an._current_data(CREDS, pool=pool, user_id="actor", credential_id="saved", organization_id="org")
    assert wire.calls == []

@pytest.mark.asyncio
async def test_current_token_before_after_refusal_and_parser(monkeypatch,wire):
    from repositories.credential_approvals import CredentialApprovalRepo
    monkeypatch.setattr(CredentialApprovalRepo,"admit",AsyncMock(return_value=None))
    raw=dict(CREDS)
    state={"data":an._shape(raw)}
    async def current(data,**context):return state["data"]
    monkeypatch.setattr(an,"_current_data",current)
    wire.responses.append(ACCOUNT);await run("test_connection",credential_data=raw,credential_id="saved",pool=object())
    state["data"]={**an._shape(raw),"access_token":"rotated-access-token"}
    with pytest.raises(an.AvazaAPIError,match="binding changed"):await run("test_connection",credential_data=raw,credential_id="saved",pool=object())
    state["data"]=an._shape(raw)
    wire.responses.append(Response(status=403,after=lambda:state.update(data={**an._shape(raw),"access_token":"rotated-access-token"})))
    with pytest.raises(an.AvazaAPIError,match="changed"):await run("test_connection",credential_data=raw,credential_id="saved",pool=object())
    state["data"]=an._shape(raw);original=an._account
    def account(*args,**kwargs):
        result=original(*args,**kwargs);state["data"]={**an._shape(raw),"access_token":"rotated-access-token"};return result
    monkeypatch.setattr(an,"_account",account);wire.responses.append(ACCOUNT)
    with pytest.raises(an.AvazaAPIError,match="changed"):await run("test_connection",credential_data=raw,credential_id="saved",pool=object())
    assert len(wire.calls)==3

@pytest.mark.asyncio
@pytest.mark.parametrize("status",["pending","rejected"])
async def test_actual_admission_stops_account_read_and_parent_picker(monkeypatch,wire,status):
    from nodes.core import run_op
    from repositories.credential_approvals import CredentialApprovalRepo
    monkeypatch.setattr(run_op,"resolve_operation_credential",AsyncMock(return_value=CREDS));monkeypatch.setattr(CredentialApprovalRepo,"admit",AsyncMock(return_value={"status":status,"id":"approval","new_request":False}))
    result=await run("test_connection",credential_id="saved",pool=object());assert result["executed"] is False
    result=await run_node_lookup(node_type=an.NODE_TYPE,field_name="project_id",credential_id="saved",user_id="actor",pool=object(),context={"account_id":7,"company_id":11})
    assert result["status"] in ("pending_approval","rejected") and wire.calls==[]

@pytest.mark.asyncio
async def test_staging_connect_shape_hook_and_account_evidence(wire):
    from nodes.core.connection_evidence import collect_evidence
    assert (await an.AvazaNode.validate_credential_access(CREDS))["valid"] is True
    assert (await an.AvazaNode.validate_credential_access({**CREDS, "access_token": "bad"}))["valid"] is False
    wire.responses.append(ACCOUNT)
    evidence = await collect_evidence(node_type=an.NODE_TYPE, credential_data=CREDS, user_id="actor")
    assert evidence.reachable is True and an.AvazaNode.connection_evidence.proves == "account" and evidence.samples[0].label == "7"
    wire.responses.append(Response(status=403, raw=b"private nonJSON", content_type="text/html"))
    assert (await collect_evidence(node_type=an.NODE_TYPE, credential_data=CREDS, user_id="actor")).reachable is None

@pytest.mark.asyncio
async def test_json_text_media_opaque_status_secret_redaction_and_unpaged_bound(wire,monkeypatch):
    wire.responses.append(Response({**ACCOUNT,"CompanyName":"synthetic%2b%2F%3dprivate-key","status":{"opaque":"future"}},content_type="text/json"))
    result=await run("get_account",{"account_id":7,"include_names":True});assert result["data"]["account"]["CompanyName"]=="[redacted]"
    monkeypatch.setattr(an,"MAX_ROWS",0);scoped(wire,PROJECT)
    with pytest.raises(an.AvazaAPIError,match="metadata is unverified"):await run("list_project_team",PARENTS)
    assert len(wire.calls)==3
