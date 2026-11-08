import json
from pathlib import Path
from contextlib import asynccontextmanager
import httpx
import pytest
from nodes.core.registry import NodeFactory
from nodes.recruitee_node import ROUTES, RecruiteeCredential

RESPONSES = json.loads((Path(__file__).parent / "fixtures/recruitee/responses.json").read_text())
TOKEN = "recruitee-private-test-key"
CONFIGS = {
 "list_candidates": {"limit": 2, "offset": 2},
 "search_candidates": {"page": 2},
 "create_candidate": {"candidate": {"name": "John Smith", "emails": ["john@example.com"]}, "offers": [487967]},
 "get_candidate": {"candidate_id": 27746490},
 "update_candidate": {"candidate_id": 27746490, "candidate": {"emails": []}},
 "delete_candidate": {"candidate_id": 27746490},
 "list_candidate_notes": {"candidate_id": 27746490},
 "list_offers": {},
 "create_offer": {"offer": {"title": "Developer", "description": "Build", "requirements": "Python", "location_ids": [214599]}},
 "get_offer": {"offer_id": 487967},
 "delete_offer": {"offer_id": 487967},
 "list_departments": {},
 "list_memberships": {},
 "list_locations": {"page": 2},
}

def node(operation):
 return NodeFactory.create_node(node_id="test-recruitee", node_type="automation-recruitee", node_data={
  "config": {"operation": operation, **CONFIGS[operation]},
  "credentials": {"credential_type": "recruitee_api_token", "api_token": TOKEN, "company_id": 49498}})

def transport(monkeypatch, handler):
 @asynccontextmanager
 async def client(**kwargs):
  async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
   yield c
 monkeypatch.setattr("nodes.recruitee_node.guarded_async_client", client)

@pytest.mark.asyncio
@pytest.mark.parametrize("operation", CONFIGS)
async def test_requests_and_provider_envelopes(monkeypatch, operation):
 calls=[]
 method, route=ROUTES[operation]
 path=route.format(**CONFIGS[operation])
 spec_path="/c/{company_id}"+route.replace("{candidate_id}","{id}").replace("{offer_id}","{id}")
 body=RESPONSES.get(method+" "+spec_path, {"offer": {"id":487967,"title":"Developer"}})
 def handler(request):
  calls.append(request)
  assert request.method==method
  assert str(request.url).startswith("https://api.recruitee.com/c/49498"+path)
  assert request.headers["Authorization"]=="Bearer "+TOKEN
  if method in {"POST","PATCH"}:
   sent=json.loads(request.content)
   assert sent["offer" if operation=="create_offer" else "candidate"]==node(operation).config.config.model_dump(exclude_none=True)["offer" if operation=="create_offer" else "candidate"]
  if operation=="list_candidates": assert dict(request.url.params)["offset"]=="2"
  return httpx.Response(200,json=body)
 transport(monkeypatch,handler)
 result=await node(operation).execute({})
 assert result["status"]=="success"
 assert result["data"]==body
 assert len(calls)==1

@pytest.mark.asyncio
async def test_provider_rejection_is_redacted(monkeypatch):
 transport(monkeypatch,lambda r:httpx.Response(401,text="Invalid token "+TOKEN))
 result=await node("list_departments").execute({})
 assert result["status"]=="error" and result["http_status"]==401
 assert TOKEN not in str(result)
 assert "Invalid token" in result["error"]

@pytest.mark.asyncio
async def test_empty_delete_acknowledgement(monkeypatch):
 transport(monkeypatch,lambda r:httpx.Response(204))
 assert (await node("delete_candidate").execute({}))["data"]=={}

@pytest.mark.parametrize("company_id",["../other",0,-1])
def test_company_boundary(company_id):
 with pytest.raises(ValueError): RecruiteeCredential(api_token=TOKEN,company_id=company_id)

def test_provider_fixture_contains_no_real_shaped_credentials():
 import runpy
 root = Path(__file__).resolve().parents[3]
 # The open edition exports this same scanner under scripts/. Fail if neither exists.
 scanner_path = root / 'oss/scan_real_secrets.py'
 if not scanner_path.is_file():
  scanner_path = root / 'scripts/scan_real_secrets.py'
 scanner = runpy.run_path(str(scanner_path))
 fixture = Path(__file__).parent / 'fixtures/recruitee/responses.json'
 assert not scanner['find_secrets'](fixture.read_bytes())
