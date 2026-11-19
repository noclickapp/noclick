"""A browser's live view for a page of your own: ``live_view`` asks for a single-use token for its websocket,
watching (full size or a thumbnail) or, once the browser is taken over, driving it; the token never shows in its
repr."""

import pytest

import noclick as nc
from platform_helpers import body

BROWSER = {"object": "browser", "id": "br_1", "status": "running", "user_id": "user_42", "held": False}
VIEW = {"object": "browser_live_view", "browser_id": "br_1", "control": False, "thumb": True,
        "url": "wss://api.test/v1/browsers/live_views/attach", "token": "tok_1",
        "token_expires_at": "2026-11-19T10:02:00Z"}


def test_live_view_watches_or_drives(api, client):
    api.get("/v1/browsers/br_1").respond(json=BROWSER)
    watch = api.post("/v1/browsers/br_1/live_view").respond(json=VIEW)
    drive = api.post("/v1/browsers/br_1/live_control").respond(json={**VIEW, "control": True, "thumb": False,
                                                                      "token": "tok_2"})
    browser = nc.Browser.get("br_1")

    tile = browser.live_view(thumb=True)
    assert body(watch.calls.last.request) == {"thumb": True}
    assert watch.calls.last.request.headers["NoClick-User"] == "user_42"  # the browser's own user
    assert isinstance(tile, nc.BrowserLiveView)
    assert (tile.browser_id, tile.thumb, tile.control, tile.url, tile.token) == (
        "br_1", True, False, "wss://api.test/v1/browsers/live_views/attach", "tok_1")
    assert tile.token_expires_at.isoformat() == "2026-11-19T10:02:00+00:00"
    assert "tok_1" not in repr(tile)
    browser.live_view()
    assert body(watch.calls.last.request) == {"thumb": False}

    driving = browser.live_view(control=True)
    assert drive.call_count == 1 and driving.control is True and driving.token == "tok_2"
    with pytest.raises(ValueError, match="full size"):
        browser.live_view(control=True, thumb=True)
