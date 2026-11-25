"""Signing a command line in, and what it reads about the key it signed in with.

A device sign-in (``CliLogin.start``, then ``poll`` until a person approves it on the page it names) is made before
there is a key, so it sends none (a setup code is ``Key.redeem_setup_code``). ``account_status`` and
``Key.revoke_current`` act with the key the client holds.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from ._client import Client, resolve_client
from ._sync import synced

@dataclass(frozen=True)
class CliLoginStart:
    """A sign-in waiting on a person: they open ``verification_url`` and enter ``user_code``; poll with
    ``device_code``."""

    device_code: str
    user_code: str
    verification_url: str
    verification_url_complete: Optional[str]
    interval_s: float
    expires_at: Optional[str]
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)


@dataclass(frozen=True)
class CliLoginPoll:
    """A poll's answer: ``pending`` (or ``slow_down``) until approved, then the key, once."""

    status: str
    interval_s: Optional[float]
    key: Optional[str] = field(repr=False)
    key_id: Optional[str]
    key_name: Optional[str]
    email: Optional[str]
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)


class CliLogin:
    """A device sign-in: what a command line does to get a key without anyone pasting one."""

    @synced
    @staticmethod
    async def start(*, name: str, hostname: str, client: Optional[Client] = None) -> CliLoginStart:
        """Start a sign-in for ``name`` (what signs in, like ``noclick-cli``) on ``hostname`` (its key is named
        after it). Sent with no key.

        Returns:
            The sign-in: the page and code a person approves it with, and the device code to poll with.

        Usage::

            begun = noclick.CliLogin.start(name="my-tool", hostname=socket.gethostname())
            print(f"Open {begun.verification_url} and enter {begun.user_code}")
        """
        raw = await resolve_client(client).request(
            "POST", "/v1/cli/logins", json={"client": name, "hostname": hostname}, user=None, anonymous=True)
        return CliLoginStart(str(raw["device_code"]), str(raw["user_code"]), str(raw["verification_url"]),
                             raw.get("verification_url_complete"), float(raw.get("interval_s") or 5),
                             raw.get("expires_at"), raw)

    @synced
    @staticmethod
    async def poll(device_code: str, *, client: Optional[Client] = None) -> CliLoginPoll:
        """One poll of a sign-in, sent with no key. Wait ``interval_s`` between polls.

        Returns:
            ``pending`` or ``slow_down`` until a person approves it, then ``approved`` with the new ``key``, once.

        Raises:
            noclick.PermissionDenied: the person denied it.
            noclick.Expired: it expired.

        Usage::

            while (answer := noclick.CliLogin.poll(begun.device_code)).status != "approved":
                time.sleep(answer.interval_s or begun.interval_s)
            save_privately(answer.key)
        """
        raw = await resolve_client(client).request(
            "POST", "/v1/cli/logins/token", json={"device_code": device_code}, user=None, anonymous=True)
        status = raw.get("status") if raw.get("status") in ("approved", "slow_down") else "pending"
        interval = raw.get("interval_s")
        return CliLoginPoll(status, float(interval) if interval is not None else None, raw.get("key"),
                            raw.get("key_id"), raw.get("key_name"), raw.get("email"), raw)


@synced
async def account_status(*, client: Optional[Client] = None) -> Dict[str, Any]:
    """The account at a glance, as ``GET /v1/status`` answers it.

    Returns:
        Which account the key acts in (``account``, with the user a key acts for in ``account["acting_for"]``), its
        plan, balance and spend against caps, approvals waiting on a person, what failed in the last day and what ran
        last.

    Usage::

        status = noclick.account_status()
        print(status["account"]["name"])
    """
    return await resolve_client(client).request("GET", "/v1/status", user=None)
