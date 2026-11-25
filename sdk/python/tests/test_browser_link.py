"""A person's page for a browser through its link (``noclick.BrowserLink``): it reads the link, starts a sign-in's
browser, types and finishes with the link alone, never a key, and one that stopped working raises in its own words."""

import httpx
import pytest

import noclick as nc
from platform_helpers import BASE, body

ID = "5d2f1c0b-7a9e-4c3d-8b6a-1f0e9d8c7b6a"
PATH = f"/v1/public/browser_links/{ID}"
LINK = {"object": "browser_link", "id": ID, "purpose": "login", "status": "open", "domain": "portal.example.com",
        "reason": "To download your invoices.", "expires_at": "2026-10-03T00:00:00+00:00",
        "brand": {"name": "Acme Travel", "logo_url": "https://cdn.acme.test/logo.png", "color": "#1a73e8",
                  "support_url": None}}


def test_reads_starts_types_and_finishes_with_the_link_alone(api):
    read = api.get(PATH).respond(json=LINK)
    started = api.post(f"{PATH}/start").respond(json={**LINK, "status": "live"})
    typed = api.post(f"{PATH}/type").respond(json={"object": "browser_link", "id": ID, "typed": True})
    done = api.post(f"{PATH}/done").respond(json={**LINK, "status": "done"})
    link = nc.BrowserLink(ID, base_url=BASE)

    page = link.read()
    assert (page.id, page.purpose, page.status, page.domain, page.reason) == (
        ID, "login", "open", "portal.example.com", "To download your invoices.")
    assert page.expires_at.isoformat() == "2026-10-03T00:00:00+00:00" and page.raw == LINK
    assert page.brand == nc.BrowserLinkBrand(name="Acme Travel", logo_url="https://cdn.acme.test/logo.png",
                                             color="#1a73e8", support_url=None)
    assert link.start().status == "live"
    link.type(text="482913")
    link.type(key="Enter")
    assert link.done().status == "done"

    assert [body(call.request) for call in typed.calls] == [{"text": "482913"}, {"key": "Enter"}]
    assert body(started.calls.last.request) == {}
    for route in (read, started, typed, done):
        assert "authorization" not in route.calls.last.request.headers, "the link is the capability: no key goes"


def test_a_link_that_stopped_working_raises_in_its_own_words(api):
    api.post(f"{PATH}/done").mock(return_value=httpx.Response(
        409, json={"error": {"type": "not_available", "message": "This link no longer works."}}))
    api.get("/v1/public/browser_links/gone").mock(return_value=httpx.Response(
        404, json={"error": {"type": "not_found", "message": "This link no longer works."}}))
    with pytest.raises(nc.NotAvailable, match="This link no longer works."):
        nc.BrowserLink(ID, base_url=BASE).done()
    with pytest.raises(nc.NotFound):
        nc.BrowserLink("gone", base_url=BASE).read()
