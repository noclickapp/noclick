"""UNRUN actual saved-row, registered action/picker and admission contracts.
Only synthetic storage, encryption and HTTP transports are substituted; production
authority policy, node factory, operation pinning and validation context remain real.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock
import pytest
from nodes import openstatus_node as R
from nodes.tests.test_openstatus_node_mock import AUTH, USER, world, args
from repositories.credentials import credential_access_predicate
from repositories.organization import PRIMARY_ORG_SQL

CID="00000000-0000-4000-8000-000000000042"
OWNER="00000000-0000-4000-8000-000000000002"
ORG="00000000-0000-4000-8000-000000000003"
WF="00000000-0000-4000-8000-000000000004"


class Context:
    def __init__(self, value): self.value=value
    async def __aenter__(self): return self.value
    async def __aexit__(self,*_): return False


class Storage:
    def __init__(self):
        self.row={"credential": b"synthetic-only", "credential_type": R.FAMILY, "owner_id": OWNER,
            "token_version": 7, "updated_at": datetime(2026,10,7,tzinfo=timezone.utc), "revoked_at": None, "approval_revision": 0}
        self.grant,self.calls=deepcopy(AUTH),[]
        self.access={(USER,ORG),(USER,None),(OWNER,ORG)}
        self.current_org,self.workflow_owner,self.workflow_authorized=ORG,OWNER,True
    def acquire(self): return Context(self)
    async def fetchrow(self, sql,*v):
        self.calls.append((sql,v))
        if sql==PRIMARY_ORG_SQL: return {"organization_id": self.current_org} if self.current_org else None
        if "SELECT owner_id FROM workflows" in sql: return {"owner_id": self.workflow_owner} if self.workflow_owner else None
        if "SELECT 1 FROM workflow_authorized_credentials" in sql: return {"authorized": 1} if self.workflow_authorized else None
        assert "FROM credentials c" in sql and credential_access_predicate() in sql and str(v[0])==CID
        principal,org=str(v[1]),v[2]
        allowed=(principal,org) in self.access
        if len(v)==6:
            caller,current,workflow=v[3:]
            assert caller==USER and "workflow_authorized_credentials" in sql
            if principal!=caller: allowed=allowed and workflow==WF and self.workflow_owner==principal and self.workflow_authorized
            if current: allowed=allowed and org==self.current_org
        return deepcopy(self.row) if allowed and self.row else None
    async def execute(self,*_): raise AssertionError("No API key persistence")


@pytest.fixture
def storage(monkeypatch):
    s=Storage();s.crypto=MagicMock()
    s.crypto.decrypt_credential.side_effect=lambda _: deepcopy(s.grant)
    s.crypto.encrypt_credential.side_effect=AssertionError("No API key persistence")
    monkeypatch.setattr("utils.encryption.get_encryption",lambda:s.crypto)
    monkeypatch.setattr("utils.credentials.get_encryption",lambda:s.crypto)
    monkeypatch.setattr("utils.database_pool.get_native_pool",lambda:s)
    monkeypatch.setattr("utils.credentials.get_native_pool",lambda:s)
    return s


@pytest.fixture
def registry(monkeypatch):
    from nodes.core import registry as module
    monkeypatch.setattr(module,"NODE_REGISTRY",{R.NODE_TYPE:R.OpenStatusNode})
    return module


@pytest.fixture
def admission(monkeypatch):
    from repositories.credential_approvals import CredentialApprovalRepo
    from utils import credential_approval
    admit=AsyncMock(return_value=None)
    monkeypatch.setattr(CredentialApprovalRepo,"admit",admit)
    monkeypatch.setattr(credential_approval,"get_frontend_url",lambda:"https://synthetic.invalid")
    return admit


@pytest.mark.asyncio
@pytest.mark.parametrize("bad",["missing","foreign","revoked","version","timestamp","access"])
async def test_current_row_refuses_before_decrypt_or_http(storage,world,bad):
    if bad=="missing": storage.row=None
    elif bad=="foreign": storage.row["credential_type"]="slack_oauth"
    elif bad=="revoked": storage.row["revoked_at"]=datetime.now(timezone.utc)
    elif bad=="version": storage.row["token_version"]=True
    elif bad=="timestamp": storage.row["updated_at"]="invalid"
    else: storage.access.clear()
    with pytest.raises(ValueError):
        await R.OpenStatusNode.freshen_credential(AUTH,pool=storage,user_id=USER,credential_id=CID,organization_id=ORG)
    storage.crypto.decrypt_credential.assert_not_called()
    assert world.calls==[]


@pytest.mark.asyncio
@pytest.mark.parametrize("change",["owner","org","version","timestamp","revocation","access","key","family"])
async def test_current_authority_race_blocks_output_without_write(storage,world,change):
    bound=await R.OpenStatusNode.freshen_credential(AUTH,pool=storage,user_id=USER,credential_id=CID)
    def after(_):
        world.after_request=None
        if change=="owner": storage.row["owner_id"]=USER
        elif change=="org": storage.current_org=OWNER
        elif change=="version": storage.row["token_version"]+=1
        elif change=="timestamp": storage.row["updated_at"]+=timedelta(seconds=1)
        elif change=="revocation": storage.row["revoked_at"]=datetime.now(timezone.utc)
        elif change=="access": storage.access.clear()
        elif change=="family": storage.row["credential_type"]="slack_oauth"
        else: storage.grant["api_key"]="changed-synthetic-key"
    world.after_request=after
    with pytest.raises(ValueError): await R.records(bound,{"operation":"list_status_pages"})
    assert len(world.calls)==1
    storage.crypto.encrypt_credential.assert_not_called()


@pytest.mark.asyncio
async def test_personal_none_owner_policy_and_saved_wrapper(storage,world):
    bound=await R.OpenStatusNode.freshen_credential(AUTH,pool=storage,user_id=USER,credential_id=CID,organization_id=None)
    assert bound.snapshot[0].organization_id is None and bound.snapshot[0].current_organization is False
    with pytest.raises(ValueError): await R.records(dict(bound),{"operation":"list_status_pages"})
    with pytest.raises(ValueError): await R.OpenStatusNode.freshen_credential(AUTH,pool=storage,user_id=USER,credential_id=CID,organization_id=ORG,require_owner=True)
    assert world.calls==[]


@pytest.mark.asyncio
async def test_version_bound_page_invalidated_before_http(storage,world):
    old=await R.OpenStatusNode.freshen_credential(AUTH,pool=storage,user_id=USER,credential_id=CID,organization_id=ORG)
    token=R.seal_page(old,"page",None,50,50)
    storage.row["token_version"]+=1
    current=await R.OpenStatusNode.freshen_credential(AUTH,pool=storage,user_id=USER,credential_id=CID,organization_id=ORG)
    with pytest.raises(ValueError): await R.records(current,{"operation":"list_status_pages","page_token":token})
    assert world.calls==[]


@pytest.mark.asyncio
async def test_actual_registered_operation_pin_and_authorized_owner_fallback(storage,world,registry,admission):
    from nodes.core.run_op import run_node_operation
    storage.access.discard((USER,ORG))
    value=await run_node_operation(node_type=R.NODE_TYPE,operation="list_status_pages",arguments={"operation":"get_status_page"},
        credential_id=CID,user_id=USER,pool=storage,organization_id=ORG,workflow_id=WF)
    assert value["read_completed"] and value["identity_verified"] is False
    assert all(req.url.path.endswith("/ListStatusPages") for req in world.calls)
    storage.workflow_authorized=False;world.calls.clear()
    with pytest.raises(ValueError):
        await run_node_operation(node_type=R.NODE_TYPE,operation="list_status_pages",arguments={},credential_id=CID,
            user_id=USER,pool=storage,organization_id=ORG,workflow_id=WF)
    assert world.calls==[]


@pytest.mark.asyncio
async def test_real_shared_picker_and_trusted_context_preserve_unknown(storage,world,registry,admission,monkeypatch):
    from nodes.core.run_op import run_node_lookup
    from nodes.core.credential_validation import CredentialValidationContext
    from repositories.credentials import CredentialsRepo
    storage.row["owner_id"]=USER
    result=await run_node_lookup(node_type=R.NODE_TYPE,field_name="page_id",credential_id=CID,
        user_id=USER,pool=storage,organization_id=ORG,workflow_id=WF,context={})
    assert result["options"][0]["metadata"]["proves"]=="reachability"
    row=await CredentialsRepo(storage).fetch_validation_authority(CID,USER,ORG)
    ctx=CredentialValidationContext(CID,R.NODE_TYPE,USER,ORG,storage,row,WF)
    monkeypatch.setattr("wss.handlers.workflow_handler.get_user_org_context",AsyncMock(return_value=ORG))
    assert await R.OpenStatusNode.validate_credential_access(AUTH)=={"valid":None,"error":"Save and check a protected metadata read"}
    storage.row["owner_id"]=USER
    value=await R.OpenStatusNode.validate_credential_access(AUTH,validation_context=ctx)
    assert value["valid"] is True and value["identity_verified"] is False




@pytest.mark.asyncio
async def test_storage_uncertainty_is_sanitized_unknown(storage,world):
    storage.fetchrow=AsyncMock(side_effect=ConnectionError("private-storage-diagnostic"))
    with pytest.raises(RuntimeError) as caught:
        await R.OpenStatusNode.freshen_credential(AUTH,pool=storage,user_id=USER,credential_id=CID)
    assert "private-storage-diagnostic" not in str(caught.value) and world.calls==[]


@pytest.mark.asyncio
@pytest.mark.parametrize("status,expected",[(200,True),(401,False),(403,False),(429,None),(500,None),(0,False),(-1,None)])
async def test_actual_saved_socket_context_has_honest_tristate(storage,world,registry,admission,monkeypatch,status,expected):
    from types import SimpleNamespace
    from wss.handlers import credentials_handler as H, workflow_handler
    from wss.receiver.client_events import CredentialValidateAccessRequest
    storage.row["owner_id"]=USER
    monkeypatch.setattr(workflow_handler,"get_user_org_context",AsyncMock(return_value=ORG))
    monkeypatch.setattr(H,"get_encryption",lambda:storage.crypto)
    sent=[]
    async def send(_sio,_sid,response): sent.append(response.model_dump()["data"])
    monkeypatch.setattr(H,"send_event",send)
    handler=H.CredentialsHandler(SimpleNamespace(get_session=AsyncMock(return_value={"user_id":USER})))
    handler.get_pool=AsyncMock(return_value=storage)
    if status==0: storage.row["revoked_at"]=datetime.now(timezone.utc)
    elif status==-1: world.override=lambda *_:[]
    else: world.status=status
    body=CredentialValidateAccessRequest(request_id="synthetic-validation",node_type=R.NODE_TYPE,credential_id=CID)
    await handler.get_events()[body.event_name]("synthetic-sid",body)
    assert sent[0]["valid"] is expected and AUTH["api_key"] not in str(sent)
    if expected is True: assert sent[0]["identity_verified"] is False and sent[0]["proves"]=="reachability"
    assert len(world.calls)==(0 if status==0 else 2 if status==200 else 1)


@pytest.mark.asyncio
async def test_actual_public_discovery_manual_connect_and_no_guessed_identity(world,registry,monkeypatch):
    from nodes.core import credential_connect,connection_evidence
    from utils.credential_request_routes import _credential_union_leaves, _get_oauth_provider
    leaves=_credential_union_leaves(R.OpenStatusNode.get_config_schema())
    assert len(leaves)==1
    _,schema,hidden=leaves[0]
    assert not hidden and _get_oauth_provider(R.FAMILY) is None
    assert schema["properties"]["credential_type"]["const"]==R.FAMILY
    assert schema["required"]==["api_key"] and schema["properties"]["api_key"]["ui:sensitive"] is True
    monkeypatch.setattr(credential_connect,"_collect_evidence",connection_evidence.collect_evidence)
    value=await credential_connect.validate_for_connect(credential_type=R.FAMILY,credential_data={"api_key":AUTH["api_key"]},user_id=USER)
    assert value.ok and value.credential_data["credential_type"]==R.FAMILY
    assert value.evidence.reachable is True and value.evidence.proves=="reachability" and value.evidence.account_label is None




@pytest.mark.asyncio
async def test_actual_public_transport_policy_blocks_private_dns_despite_override(monkeypatch):
    import asyncio,socket,httpx
    from utils import ssrf
    lookup=AsyncMock(return_value=[(socket.AF_INET,socket.SOCK_STREAM,6,"",("10.0.0.8",443))])
    monkeypatch.setattr(asyncio.get_running_loop(),"getaddrinfo",lookup)
    monkeypatch.setattr(ssrf,"allow_private_hosts",lambda:True)
    calls=[]
    def client(**kw): return ssrf.guarded_async_client(**kw,transport=httpx.MockTransport(lambda req:calls.append(req) or httpx.Response(200,json={})))
    monkeypatch.setattr(R,"guarded_async_client",client)
    with pytest.raises(ValueError): await R.request(AUTH,"ListStatusPages",{"limit":50,"offset":0})
    assert calls==[]
