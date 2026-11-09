"""Offline wire and native factory tests against Event Tickets' published API."""
import base64
from urllib.parse import parse_qs
import httpx
import pytest
from pydantic import ValidationError
from nodes import event_tickets_node as native
from nodes.core.registry import NodeFactory

CREDENTIAL = {"credential_type": "event_tickets_application_password", "site_url": "https://events.example.com", "username": "organizer", "application_password": "abcd efgh ijkl mnop qrst uvwx"}

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="event-tickets-test", node_type="automation-event-tickets", node_data={"config": config, "credentials": CREDENTIAL})


def mock(monkeypatch, body, status=200):
    calls=[]
    def send(request):
        calls.append(request)
        return httpx.Response(status, json=body)
    def client(**kw):
        assert kw["follow_redirects"] is False and kw["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(send), **kw)
    monkeypatch.setattr(native,"guarded_async_client",client)
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize("config,path,query",[
    ({"operation":"list_tickets"},"tickets",{}),
    ({"operation":"search_tickets","search":"Concert + food"},"tickets",{"search":"Concert + food"}),
    ({"operation":"list_available_tickets"},"tickets",{"is_available":"true"}),
    ({"operation":"list_event_tickets","include_post":29},"tickets",{"include_post":"29"}),
    ({"operation":"list_attendees"},"attendees",{}),
    ({"operation":"find_attendees","email":"steve@test.com"},"attendees",{"email":"steve@test.com"}),
    ({"operation":"list_event_attendees","post_id":29},"attendees",{"post_id":"29"}),
    ({"operation":"list_ticket_attendees","ticket_id":30},"attendees",{"ticket_id":"30"}),
    ({"operation":"list_checked_in_attendees","checkedin":False},"attendees",{"checkedin":"false"}),
])
async def test_event_tickets_read_filters_auth_pagination(monkeypatch,config,path,query):
    calls=mock(monkeypatch,{path:[{"id":33}],"total":41,"total_pages":3})
    result=await node({**config,"page":2}).execute({})
    assert result["next_page"]==3
    r=calls[0]
    assert r.method=="GET" and r.url.path=="/wp-json/tribe/tickets/v1/"+path
    assert dict(r.url.params)=={"page":"2","per_page":"20",**query}
    assert r.headers['authorization']=="Basic "+base64.b64encode((CREDENTIAL['username']+":"+CREDENTIAL['application_password']).encode()).decode()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,path",[("get_ticket","tickets"),("get_attendee","attendees"),("get_cart","cart")])
async def test_event_tickets_details(monkeypatch,operation,path):
    calls=mock(monkeypatch,{"id":33} if path!="cart" else {"tickets":[],"meta":[],"cart_url":"https://events.example.com/cart","checkout_url":"https://events.example.com/checkout"})
    cfg={"operation":operation,**({"id":33} if path!="cart" else {})}
    await node(cfg).execute({})
    assert calls[0].url.path=="/wp-json/tribe/tickets/v1/"+path+("/33" if path!="cart" else "")


@pytest.mark.asyncio
async def test_event_tickets_cart_form_is_documented_record_list(monkeypatch):
    body={"tickets":[{"ticket_id":30,"quantity":2}],"meta":[],"cart_url":"https://events.example.com/cart","checkout_url":"https://events.example.com/checkout"}
    calls=mock(monkeypatch,body)
    result=await node({"operation":"update_cart","provider":"woo","post_id":29,"tickets":[{"ticket_id":30,"quantity":2}]}).execute({})
    assert result==body
    assert calls[0].method=="POST"
    assert calls[0].headers['content-type']=="application/x-www-form-urlencoded"
    assert parse_qs(calls[0].content.decode())=={"provider":["woo"],"post_id":["29"],"tickets[0][ticket_id]":["30"],"tickets[0][quantity]":["2"]}


@pytest.mark.asyncio
async def test_event_tickets_empty_attendees_and_provider_rejection(monkeypatch):
    mock(monkeypatch,{"attendees":[],"total":0,"total_pages":0})
    assert (await node({"operation":"list_attendees"}).execute({}))["next_page"] is None
    mock(monkeypatch,{"code":"rest_forbidden","message":"You cannot view attendees."},403)
    with pytest.raises(ValueError,match="You cannot view attendees"):
        await node({"operation":"list_attendees"}).execute({})
    mock(monkeypatch,{"unexpected":[]})
    with pytest.raises(ValueError,match="missing its records"):
        await node({"operation":"list_tickets"}).execute({})


@pytest.mark.parametrize("site",["http://events.example.com","https://u:p@events.example.com","https://events.example.com/?x=1","https://events.example.com/#frag","https://events.example.com/../internal"])
def test_event_tickets_invalid_credential_sites(site):
    with pytest.raises(ValidationError):
        native.EventTicketsApplicationPasswordCredential(**{**CREDENTIAL,"site_url":site})


@pytest.mark.parametrize("provider", ["event-tickets"])
def test_event_tickets_manual_credential_type_default(provider):
    assert native.EventTicketsNode.integration_type == "automation-" + provider
    data={k:v for k,v in CREDENTIAL.items() if k!="credential_type"}
    assert native.EventTicketsApplicationPasswordCredential(**data).credential_type==CREDENTIAL['credential_type']


@pytest.mark.asyncio
async def test_event_tickets_documented_attendee_response(monkeypatch):
    import json
    from pathlib import Path
    fixture=json.loads((Path(__file__).parent/'fixtures/event-tickets/attendees.json').read_text())
    mock(monkeypatch,fixture['body'])
    result=await node({'operation':'list_attendees'}).execute({})
    assert result['attendees'][0]['id']==33
    assert result['attendees'][0]['checkin_details'] is False
    assert result['next_page'] is None


def test_event_tickets_saved_editor_metadata_is_not_an_api_parameter():
    data={"config":{"operation":"list_tickets","credentialIds":{"event_tickets_application_password":"saved-reference"}}, "credentials":CREDENTIAL}
    assert native.EventTicketsNode.validate_config(data)["valid"]
    parsed=native.EventTicketsNode.parse_config(data)
    assert "credentialIds" not in parsed.config.model_dump()
