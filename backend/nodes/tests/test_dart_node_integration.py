"""Dart via NoClick's real operation, credential and connection-evidence seams."""
from unittest.mock import AsyncMock

import pytest

from nodes.tests.test_dart_node_mock import ID, credential, transport


@pytest.mark.asyncio
async def test_dart_saved_credential_dispatch(monkeypatch):
    from nodes.core import run_op
    from utils import credential_approval

    requests = transport(monkeypatch, {"item": {"id": ID, "title": "Owned task"}})
    loader = AsyncMock(return_value=credential())
    monkeypatch.setattr(run_op, "resolve_operation_credential", loader)
    admission = AsyncMock(return_value=None)
    monkeypatch.setattr(credential_approval, "admit_node", admission)
    result = await run_op.run_node_operation(node_type="automation-dart", operation="get_task",
        arguments={"task_id": ID}, credential_id="00000000-0000-4000-8000-000000000042", user_id="fixture-user")
    assert result["item"]["title"] == "Owned task"
    loader.assert_awaited_once()
    admission.assert_awaited_once()
    assert requests[0].url.path.endswith("/tasks/" + ID)


@pytest.mark.asyncio
@pytest.mark.parametrize("empty", [False, True])
async def test_dart_unsaved_connection_proves_tasks_or_identity(monkeypatch, empty):
    from nodes.core.connection_evidence import collect_evidence

    def response(request):
        if request.url.path.endswith("/me"):
            return {"isLoggedIn": True, "user": {"id": "user-id", "name": "Fixture User", "email": "fixture@example.test"}}
        return {"count": 0 if empty else 1, "next": None,
            "results": [] if empty else [{"id": ID, "title": "Owned task"}]}

    requests = transport(monkeypatch, response)
    evidence = await collect_evidence(node_type="automation-dart", credential_data=credential(), user_id="fixture-user")
    assert evidence.reachable is True
    if empty:
        assert evidence.account_label == "Fixture User" and len(requests) == 2
    else:
        assert evidence.samples[0].label == "Owned task" and len(requests) == 1


@pytest.mark.asyncio
async def test_dart_rejected_token_blocks_manual_connect(monkeypatch):
    from nodes.core.connection_evidence import collect_evidence

    transport(monkeypatch, {"detail": "Invalid token."}, 401)
    result = await collect_evidence(node_type="automation-dart", credential_data=credential(), user_id="fixture-user")
    assert result.reachable is False
    assert "Invalid token." in result.error
