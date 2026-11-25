"""Claiming an account an AI agent made for itself: the claim link it hands a person (``noclick.com/claim/<token>``)
names a token, which the signed-in person reads (``preview_claim``) and answers (``answer_claim``). Both are a
signed-in person's own calls (a session), never a key."""

from __future__ import annotations

from typing import Any, Dict, Optional

from ._client import Client, resolve_client
from ._sync import synced


class AgentSignup:
    """Claiming an account an AI agent made for itself."""

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
