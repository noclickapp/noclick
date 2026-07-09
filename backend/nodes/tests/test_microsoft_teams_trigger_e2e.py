"""End-to-end webhook roundtrip tests for Microsoft Teams triggers.

Exercises the REAL inbound-webhook path (``utils.webhook_routes.receive_webhook``)
end to end — only the DB config lookup and the background workflow execution are
mocked; routing, the Microsoft Graph subscription validation handshake, signature
(clientState) verification, node resolution and trigger-payload injection all run
for real:

- Graph subscription validation handshake echoes the ``validationToken`` (this is
  what makes ``POST /subscriptions`` succeed; without it every Teams trigger fails
  to register).
- A Graph change notification with a valid clientState routes to the trigger node,
  injects the payload, and dispatches the workflow from that node.
- A notification with a wrong clientState is rejected (401), never firing.
"""
import uuid
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from utils.webhook_routes import router


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    return app


def _teams_config(webhook_id, node_id, operation, secret, **fields):
    return {
        "id": webhook_id,
        "user_id": str(uuid.uuid4()),
        "workflow_id": str(uuid.uuid4()),
        "node_id": node_id,
        "is_active": True,
        "secret": secret,
        "workflow_config": {
            "nodes": [
                {
                    "id": node_id,
                    "type": "automation-microsoft-teams",
                    "config": {
                        "operation": operation,
                        "webhook_id": webhook_id,
                        "signing_secret": secret,
                        **fields,
                    },
                }
            ],
            "edges": [],
        },
    }


class TestTeamsGraphValidationHandshake:
    def test_validation_token_echoed_as_plaintext(self):
        """Graph's subscription-validation request must be echoed verbatim."""
        webhook_id = str(uuid.uuid4())
        cfg = _teams_config(webhook_id, "n1", "on_channel_message", "sec", team_id="t1", channel_id="c1")
        token = "Validation Token abc123=="
        with patch("utils.webhook_routes.get_webhook_config", return_value=cfg):
            client = TestClient(_app())
            resp = client.post(f"/webhook/{webhook_id}", params={"validationToken": token}, content=b"")
        assert resp.status_code == 200
        assert resp.text == token
        assert resp.headers["content-type"].startswith("text/plain")

    def test_validation_works_before_row_activated(self):
        """Validation happens during registration, while the row is still
        inactive — it must NOT 410."""
        webhook_id = str(uuid.uuid4())
        cfg = _teams_config(webhook_id, "n1", "on_chat_message", "sec", chat_id="ch1")
        cfg["is_active"] = False  # registration time: row not yet activated
        token = "tok-inactive"
        with patch("utils.webhook_routes.get_webhook_config", return_value=cfg):
            client = TestClient(_app())
            resp = client.post(f"/webhook/{webhook_id}", params={"validationToken": token}, content=b"")
        assert resp.status_code == 200
        assert resp.text == token


class TestTeamsNotificationRoundtrip:
    def test_channel_message_notification_fires_trigger(self):
        webhook_id = str(uuid.uuid4())
        node_id = "teams-trigger-1"
        secret = "topsecret-clientstate"
        cfg = _teams_config(webhook_id, node_id, "on_channel_message", secret, team_id="t1", channel_id="c1")
        notification = {
            "value": [
                {
                    "clientState": secret,
                    "changeType": "created",
                    "resource": "teams('t1')/channels('c1')/messages('m1')",
                    "resourceData": {"id": "m1"},
                }
            ]
        }
        with patch("utils.webhook_routes.get_webhook_config", return_value=cfg), patch(
            "utils.webhook_routes.update_webhook_stats"
        ), patch("utils.webhook_routes._execute_workflow_with_relay") as mock_exec:
            client = TestClient(_app())
            resp = client.post(f"/webhook/{webhook_id}", json=notification)

        assert resp.status_code == 200
        # workflow dispatched from the trigger node...
        assert mock_exec.called
        kwargs = mock_exec.call_args.kwargs
        assert kwargs["start_node_id"] == node_id
        # ...with the Graph notification injected as the trigger payload
        fired = next(n for n in kwargs["nodes"] if n["id"] == node_id)
        injected = fired["config"]["_triggerPayload"]
        assert injected["value"][0]["resource"].startswith("teams")

    def test_bad_client_state_is_rejected(self):
        webhook_id = str(uuid.uuid4())
        node_id = "teams-trigger-2"
        secret = "the-real-secret"
        cfg = _teams_config(webhook_id, node_id, "on_channel_message", secret, team_id="t1", channel_id="c1")
        bad = {"value": [{"clientState": "forged", "resource": "teams('t1')/channels('c1')/messages('m1')"}]}
        with patch("utils.webhook_routes.get_webhook_config", return_value=cfg), patch(
            "utils.webhook_routes.update_webhook_stats"
        ), patch("utils.webhook_routes._execute_workflow_with_relay") as mock_exec:
            client = TestClient(_app())
            resp = client.post(f"/webhook/{webhook_id}", json=bad)

        assert resp.status_code == 401
        assert not mock_exec.called

    def test_chat_message_notification_fires_trigger(self):
        webhook_id = str(uuid.uuid4())
        node_id = "teams-trigger-3"
        secret = "chat-secret"
        cfg = _teams_config(webhook_id, node_id, "on_chat_message", secret, chat_id="ch1")
        notification = {"value": [{"clientState": secret, "resource": "chats('ch1')/messages('m9')"}]}
        with patch("utils.webhook_routes.get_webhook_config", return_value=cfg), patch(
            "utils.webhook_routes.update_webhook_stats"
        ), patch("utils.webhook_routes._execute_workflow_with_relay") as mock_exec:
            client = TestClient(_app())
            resp = client.post(f"/webhook/{webhook_id}", json=notification)

        assert resp.status_code == 200
        assert mock_exec.called
        assert mock_exec.call_args.kwargs["start_node_id"] == node_id
