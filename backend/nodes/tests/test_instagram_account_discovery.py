"""Facebook Login discovery must distinguish missing assets from denied access."""

import logging

import httpx
import pytest

from utils.instagram_account_discovery import discover_instagram_accounts

BASE = "https://graph.facebook.com/v21.0"


async def discover(responses):
    requests = []

    def respond(request):
        requests.append(request)
        status, body = responses[len(requests) - 1]
        return httpx.Response(status, json=body)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        accounts, detail = await discover_instagram_accounts(client, "user-secret", base=BASE)
    assert len(requests) == len(responses)
    assert all("access_token" not in req.url.params for req in requests)
    return accounts, detail, requests


def linked(page_id, ig_id):
    return {"id": page_id, "instagram_business_account": {"id": ig_id, "username": "hermodbot"}}


async def test_account_on_later_page_is_discovered_without_following_provider_url():
    accounts, detail, requests = await discover([
        (200, {"data": [], "paging": {"next": "https://untrusted.invalid/?access_token=secret", "cursors": {"after": "opaque+cursor"}}}),
        (200, {"data": [linked("123", "456")]}),
    ])
    assert [account["instagram_user_id"] for account in accounts] == ["456"]
    assert detail is None
    assert requests[1].url.host == "graph.facebook.com"
    assert requests[1].url.path == "/v21.0/me/accounts"
    assert requests[1].url.params["after"] == "opaque+cursor"
    assert requests[1].headers["Authorization"] == "Bearer user-secret"


async def test_all_pages_and_fallbacks_contribute_to_account_selection():
    accounts, _, requests = await discover([
        (200, {"data": [linked("123", "456")], "paging": {"next": "next", "cursors": {"after": "second"}}}),
        (200, {"data": [{"id": "789", "name": "Second Page", "access_token": "page-secret"}, linked("123", "456")]}),
        (200, {"connected_instagram_account": {"id": "999", "username": "second"}}),
    ])
    assert [account["instagram_user_id"] for account in accounts] == ["456", "999"]
    assert accounts[1]["facebook_page_name"] == "Second Page"
    assert requests[2].headers["Authorization"] == "Bearer page-secret"


async def test_no_pages_explains_page_selection_instead_of_missing_instagram():
    accounts, detail, _ = await discover([(200, {"data": []})])
    assert not accounts
    assert "Facebook returned no Pages" in detail
    assert "personal Facebook profile" in detail
    assert "consent screen" in detail


async def test_page_without_instagram_identifies_returned_page():
    accounts, detail, _ = await discover([
        (200, {"data": [{"id": "123", "access_token": "page-secret"}]}),
        (200, {"name": "My Page"}),
    ])
    assert not accounts
    assert "1 Page(s) (IDs: 123)" in detail
    assert "No linked Instagram Business or Creator" in detail
    assert "Linked accounts" in detail


async def test_denied_page_lookup_is_reported_without_provider_secrets(caplog):
    caplog.set_level(logging.DEBUG)
    accounts, detail, _ = await discover([
        (200, {"data": [{"id": "123", "access_token": "page-secret"}]}),
        (400, {"error": {"code": 200, "message": "provider echo page-secret"}}),
    ])
    assert not accounts
    assert "discovery could not be completed" in detail
    assert "Facebook Page 123 account authorization is unavailable" in detail
    assert "No linked Instagram" not in detail
    for secret in ("user-secret", "page-secret", "provider echo"):
        assert secret not in detail + caplog.text


async def test_missing_page_token_is_access_failure_not_unlinked_account():
    accounts, detail, _ = await discover([(200, {"data": [{"id": "123"}]})])
    assert not accounts
    assert "did not grant Page access tokens for: 123" in detail
    assert "No linked Instagram" not in detail


@pytest.mark.parametrize("paging", [
    {"next": "next"},
    {"next": "next", "cursors": {"after": ""}},
    {"next": "next", "cursors": {"after": "x" * 8193}},
])
async def test_incomplete_pagination_never_selects_a_partial_result(paging):
    with pytest.raises(ValueError, match="pagination is incomplete"):
        await discover([(200, {"data": [linked("123", "456")], "paging": paging})])


async def test_repeated_cursor_fails_without_looping():
    page = {"data": [], "paging": {"next": "next", "cursors": {"after": "same"}}}
    with pytest.raises(ValueError, match="pagination is incomplete"):
        await discover([(200, page), (200, page)])


async def test_provider_failure_is_not_reported_as_no_pages():
    with pytest.raises(ValueError, match="account authorization is unavailable"):
        await discover([(400, {"error": {"code": 190, "message": "user-secret"}})])
