"""A device sign-in, a setup code and the account a key is in: what a command line needs, read with no key."""

import httpx
import pytest

import noclick as nc


def test_a_sign_in_starts_and_polls_with_no_key(api):
    start = api.post("/v1/cli/logins").respond(201, json={
        "object": "cli_login", "device_code": "dc_1", "user_code": "WDJB-MJHT", "verification_url": "https://noclick.com/cli",
        "verification_url_complete": "https://noclick.com/cli?code=WDJB-MJHT", "interval_s": 5, "expires_at": "2026-11-25T14:00:00Z"})
    poll = api.post("/v1/cli/logins/token").mock(side_effect=[
        httpx.Response(200, json={"status": "slow_down", "interval_s": 10}),
        httpx.Response(200, json={"status": "approved", "key": "nk_live_k", "key_id": "key_1", "email": "a@example.com"})])
    begun = nc.CliLogin.start(name="noclick-cli", hostname="laptop")
    assert (begun.user_code, begun.interval_s) == ("WDJB-MJHT", 5)
    assert "authorization" not in start.calls.last.request.headers
    assert nc.CliLogin.poll("dc_1").status == "slow_down"
    approved = nc.CliLogin.poll("dc_1")
    assert (approved.status, approved.key) == ("approved", "nk_live_k")
    assert poll.calls.last.request.content == b'{"device_code":"dc_1"}'


def test_an_expired_sign_in_raises_expired(api):
    api.post("/v1/cli/logins/token").respond(410, json={"error": {"type": "expired", "message": "The code expired."}})
    with pytest.raises(nc.Expired):
        nc.CliLogin.poll("dc_1")
