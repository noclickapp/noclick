"""An account an AI agent makes for itself: ``sign_up`` makes it (with no key) and answers its key and a claim link
for the agent's person, and ``current`` reads whether a person has claimed it. The claim link
(``noclick.com/claim/<token>``) names a token, which the signed-in person reads (``preview_claim``) and answers
(``answer_claim``), each a signed-in person's own call (a session), never a key."""

from __future__ import annotations

from typing import Any, Dict, Optional

from ._client import Client, resolve_client
from ._sync import synced


class AgentSignup:
    """An account an AI agent made for itself, and claiming it."""

    @synced
    @staticmethod
    async def sign_up(agent: str, *, accept_terms: bool, purpose: Optional[str] = None, email: Optional[str] = None,
                      client: Optional[Client] = None) -> Dict[str, Any]:
        """Make a NoClick account for the agent calling, sent with no key. ``accept_terms`` must be ``True``: it
        accepts NoClick's Developer Terms and Acceptable Use Policy for whoever runs the agent. ``purpose`` is what
        the account is for, which the person sees as they claim it; ``email``, the only person who may claim it.

        Returns:
            The sign-up: its ``key`` (shown this once: keep it out of anything you print), ``claim_url`` for the
            agent's person, ``expires_at``, ``limits`` (what waits for a claim) and ``terms``.

        Raises:
            PermissionDenied: With ``reason`` ``not_launched`` while agent sign-up is switched off.

        Usage::

            made = noclick.AgentSignup.sign_up("claude-code", accept_terms=True, purpose="Track a bakery's orders")
            print(f"Claim it: {made['claim_url']}")
        """
        body: Dict[str, Any] = {"agent": agent, "accept_terms": accept_terms}
        if purpose is not None:
            body["purpose"] = purpose
        if email is not None:
            body["email"] = email
        return await resolve_client(client).request(
            "POST", "/v1/agent_signups", json=body, user=None, anonymous=True) or {}

    @synced
    @staticmethod
    async def current(*, client: Optional[Client] = None) -> Dict[str, Any]:
        """The sign-up that made this key.

        Returns:
            Its ``status`` (``unclaimed``, ``claimed``, ``declined`` or ``expired``), ``expires_at`` and, while
            unclaimed, ``limits`` (``funds_usd`` and what waits for a claim).

        Raises:
            NotFound: The key wasn't made by an agent's sign-up.

        Usage::

            if noclick.AgentSignup.current()["status"] == "unclaimed":
                ...
        """
        return await resolve_client(client).request("GET", "/v1/agent_signups/current", user=None) or {}

    @synced
    @staticmethod
    async def preview_claim(token: str, *, client: Optional[Client] = None) -> Dict[str, Any]:
        """The claim page's view, for the signed-in person.

        Returns:
            The agent and what it made, what waits for the claim (its spending included), and whether the signed-in
            person may claim it.

        Usage::

            claim = noclick.AgentSignup.preview_claim(token)
        """
        return await resolve_client(client).request(
            "POST", "/v1/agent_signups/claims/preview", json={"token": token}, user=None) or {}

    @synced
    @staticmethod
    async def answer_claim(token: str, decision: str, *, accept_terms: Optional[bool] = None,
                           key_access: Optional[str] = None, client: Optional[Client] = None) -> Dict[str, Any]:
        """Answer a claim: ``"claim"`` folds the agent's account and what it made into the signed-in person's (it
        needs ``accept_terms``: the person accepting NoClick's Terms for it), its key acting there as ``key_access``
        says (``full`` by default, ``build``, or ``revoked``); ``"decline"`` ends the agent's account now.

        Returns:
            The claim's view as it is then.

        Usage::

            noclick.AgentSignup.answer_claim(token, "claim", accept_terms=True, key_access="build")
        """
        body: Dict[str, Any] = {"token": token, "decision": decision}
        if accept_terms is not None:
            body["accept_terms"] = accept_terms
        if key_access is not None:
            body["key_access"] = key_access
        return await resolve_client(client).request(
            "POST", "/v1/agent_signups/claims/answer", json=body, user=None) or {}
