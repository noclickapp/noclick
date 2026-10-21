"""Parallel calls against one connected account stay under the provider's limits: the graph-free seam every agent
tool call, connection call and lookup goes through (``nodes/core/run_op.py``) runs at most
``CREDENTIAL_CONCURRENCY`` of them at once per credential. Microsoft Graph refuses a fifth concurrent request to one
mailbox (429 ``MailboxConcurrency``), and an agent's parallel tool calls all land on the same account. Other
credentials, and operations that need none, go on beside them."""

import asyncio
from collections import Counter

import pytest

from nodes.core import run_op
from nodes.core.registry import NODE_REGISTRY

pytestmark = pytest.mark.asyncio


class Probe:
    """How many calls reach the provider at once per account; ``failing`` makes each one fail."""

    def __init__(self):
        self.running, self.most, self.failing = Counter(), Counter(), False

    async def call(self, account):
        self.running[account] += 1
        self.most[account] = max(self.most[account], self.running[account])
        try:
            await asyncio.sleep(0.02)
            if self.failing:
                raise RuntimeError("Microsoft Graph API error: boom")
            return {"status": "success"}
        finally:
            self.running[account] -= 1


@pytest.fixture
def probe(monkeypatch):
    probe = Probe()

    async def resolve(credential_id, *_args, **_kwargs):
        return {"account": credential_id}

    class Node:
        def __init__(self, credential):
            self.credential = credential

        async def run(self, inputs):
            return await probe.call(self.credential)

    monkeypatch.setattr(run_op, "resolve_operation_credential", resolve)
    monkeypatch.setattr(run_op.NodeFactory, "create_node",
                        staticmethod(lambda **kw: Node(kw["node_data"].get("credential_id"))))
    return probe


async def _operation(credential_id):
    return await run_op.run_node_operation(node_type="automation-outlook", operation="read_inbox_emails",
                                           arguments={}, user_id="user-1", credential_id=credential_id)


async def test_one_account_runs_at_most_its_limit_at_once(probe):
    results = await asyncio.gather(*(_operation("mailbox") for _ in range(10)))
    assert results == [{"status": "success"}] * 10
    assert probe.most["mailbox"] == run_op.CREDENTIAL_CONCURRENCY < 10


async def test_other_accounts_and_operations_needing_none_go_on_beside_it(probe):
    await asyncio.gather(*(_operation("mailbox") for _ in range(8)), *(_operation("calendar") for _ in range(8)),
                         *(_operation(None) for _ in range(8)))
    assert probe.most["mailbox"] == probe.most["calendar"] == run_op.CREDENTIAL_CONCURRENCY
    assert probe.most[None] == 8


async def test_a_failing_call_frees_its_place(probe):
    probe.failing = True
    failed = await asyncio.gather(*(_operation("mailbox") for _ in range(run_op.CREDENTIAL_CONCURRENCY + 2)),
                                  return_exceptions=True)
    assert all(isinstance(e, RuntimeError) for e in failed)
    probe.failing = False
    assert await asyncio.wait_for(_operation("mailbox"), timeout=1) == {"status": "success"}


async def test_lookups_take_the_same_accounts_places(probe, monkeypatch):
    class Lookup:
        @classmethod
        async def freshen_credential(cls, credential_data, **_):
            return credential_data

        @classmethod
        async def load_field_options(cls, *, credential_data, **_):
            await probe.call(credential_data["account"])
            return {"options": []}

    async def admitted(**_):
        return None

    monkeypatch.setitem(NODE_REGISTRY, "automation-probe", Lookup)
    monkeypatch.setattr("utils.credential_approval.admit_lookup", admitted)

    async def lookup():
        return await run_op.run_node_lookup(node_type="automation-probe", field_name="folder", user_id="user-1",
                                            credential_id="mailbox")

    await asyncio.gather(*(lookup() for _ in range(6)), *(_operation("mailbox") for _ in range(6)))
    assert probe.most["mailbox"] == run_op.CREDENTIAL_CONCURRENCY
