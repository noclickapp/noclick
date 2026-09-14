"""Real graph validation and persisted provenance at the activation boundary."""
import json
import uuid
from unittest.mock import AsyncMock

import pytest
from tests.fixtures.real_db_fixture import real_database
from utils.workflow_readiness import (
    activation_issues,
    readiness_report,
    WorkflowNotReadyError,
)
from utils.webhook_manager import WebhookManager
from nodes.whatsapp_node import WhatsAppNode


def monitor_graph(message=None):
    return {
        "nodes": [
            {
                "id": "in",
                "type": "automation-whatsapp",
                "config": {
                    "operation": "receive_message",
                    "credentialIds": {"whatsapp_qr": str(uuid.uuid4())},
                },
            },
            {
                "id": "brain",
                "type": "agent",
                "config": {
                    "model": "claude-code",
                    "message": message,
                    "credentialIds": {"agent_claude_code_oauth": str(uuid.uuid4())},
                },
            },
            {
                "id": "alerts",
                "type": "automation-whatsapp",
                "config": {
                    "operation": "send_text_message",
                    "to": "manager-private",
                    "agent_tool_operations": ["send_text_message"],
                    "credentialIds": {"whatsapp_qr": str(uuid.uuid4())},
                },
            },
        ],
        "edges": [
            {"source": "in", "target": "brain"},
            {"source": "alerts", "target": "brain", "targetHandle": "bottom"},
        ],
    }


def test_missing_message_blocks_only_its_enabled_reachable_path():
    graph = monitor_graph()
    assert any(
        "message" in i["message"].lower() for i in activation_issues(graph, "in")
    )
    graph["nodes"][1]["config"][
        "message"
    ] = "Review update and privately alert the manager."
    assert activation_issues(graph, "in") == []
    graph["nodes"].append(
        {"id": "unrelated", "type": "agent", "config": {"model": "claude-code"}}
    )
    assert activation_issues(graph, "in") == []
    graph["nodes"][1]["config"]["disabled"] = True
    graph["nodes"][1]["config"].pop("message")
    assert activation_issues(graph, "in") == []
    graph["nodes"][0]["config"]["disabled"] = True
    assert activation_issues(graph, "in")[0]["code"] == "disabled"


async def test_broken_path_cannot_register_and_repair_can(real_database, monkeypatch):
    graph = monitor_graph()
    loader = AsyncMock(
        return_value={"values": {"webhook_url": "https://example.test/hook"}}
    )
    monkeypatch.setattr(WhatsAppNode, "load_field_value", loader)
    kwargs = dict(
        user_id=str(uuid.uuid4()),
        workflow_id=str(uuid.uuid4()),
        node_id="in",
        node_type="automation-whatsapp",
        operation="receive_message",
        config=graph["nodes"][0]["config"],
        workflow_graph=graph,
    )
    with pytest.raises(WorkflowNotReadyError, match="message"):
        await WebhookManager.provision_node_webhook(real_database.pool, **kwargs)
    loader.assert_not_awaited()
    graph["nodes"][1]["config"]["message"] = "Review this update."
    assert (await WebhookManager.provision_node_webhook(real_database.pool, **kwargs))[
        "webhook_url"
    ]
    loader.assert_awaited_once()


async def test_only_retained_real_input_establishes_observation(real_database):
    db = real_database
    owner, wid = str(uuid.uuid4()), str(uuid.uuid4())
    await db.execute(
        "INSERT INTO auth.users (id,email) VALUES ($1,$2)",
        owner,
        f"{owner}@example.test",
    )
    graph = monitor_graph("Inspect the update.")
    await db.execute(
        "INSERT INTO workflows (id,owner_id,name,workflow) VALUES ($1,$2,'Monitor',$3::jsonb)",
        wid,
        owner,
        json.dumps(graph),
    )
    # A rehearsal and manual empty run both complete successfully but prove no input.
    for _ in range(2):
        eid = str(uuid.uuid4())
        # Rehearsals are stored with the ordinary manual source, distinguished
        # by rehearsal metadata; neither source can establish webhook receipt.
        await db.execute(
            "INSERT INTO workflow_executions(id,workflow_id,user_id,status,trigger_source) VALUES($1,$2,$3,'completed','manual')",
            eid,
            wid,
            owner,
        )
        await db.execute(
            "INSERT INTO cas_manifests(workflow_id,execution_id,node_id,manifest,last_run_status) VALUES($1,$2,'in','{}'::jsonb,'completed')",
            wid,
            eid,
        )
    report = await readiness_report(db.pool, wid, graph, credential_health={})
    assert report["status"] == "configured"
    assert report["observations"] == []
    assert report["destinations"][0]["recipients"] == ["manager-private"]
    eid = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO workflow_executions(id,workflow_id,user_id,status,trigger_source) VALUES($1,$2,$3,'error','webhook')",
        eid,
        wid,
        owner,
    )
    await db.execute(
        "INSERT INTO cas_manifests(workflow_id,execution_id,node_id,manifest,last_run_status) VALUES($1,$2,'in','{}'::jsonb,'completed')",
        wid,
        eid,
    )
    report = await readiness_report(db.pool, wid, graph, credential_health={})
    assert report["status"] == "input_observed"
    assert report["observations"][0]["run_status"] == "error"


async def test_whatsapp_repair_clears_old_registration_error(
    real_database, monkeypatch
):
    from unittest.mock import Mock
    from utils.encryption import get_encryption

    db = real_database
    owner, wid = str(uuid.uuid4()), str(uuid.uuid4())
    await db.execute(
        "INSERT INTO auth.users(id,email) VALUES($1,$2)", owner, f"{owner}@example.test"
    )
    cid = str(
        await db.fetchval(
            "INSERT INTO credentials(owner_id, name, credential_type, credential) VALUES($1,'WhatsApp','whatsapp_qr',$2) RETURNING id",
            owner,
            get_encryption().encrypt_credential({"connection_id": "test-connection"}),
        )
    )
    cfg = {
        "operation": "receive_message",
        "credentialIds": {"whatsapp_qr": cid},
        "trigger_error": "Old registration failure",
    }
    graph = {
        "nodes": [{"id": "in", "type": "automation-whatsapp", "config": cfg}],
        "edges": [],
    }
    await db.execute(
        "INSERT INTO workflows(id,owner_id,name,workflow) VALUES($1,$2,'Monitor',$3::jsonb)",
        wid,
        owner,
        json.dumps(graph),
    )
    monkeypatch.setenv("WAHOOKS_API_KEY", "test-key")
    monkeypatch.setattr("utils.webhook_delivery.relay_in_use", lambda: False)
    monkeypatch.setattr(
        "utils.webhook_delivery.get_webhook_url",
        lambda key: f"https://example.test/{key}",
    )
    monkeypatch.setattr(
        "utils.whatsapp_qr.dead_session_status", AsyncMock(return_value=None)
    )
    provider = Mock()
    monkeypatch.setattr("nodes.whatsapp_node._wahooks_ensure_webhook", provider)
    patch = await WebhookManager.provision_node_webhook(
        db.pool,
        user_id=owner,
        workflow_id=wid,
        node_id="in",
        node_type="automation-whatsapp",
        operation="receive_message",
        config=cfg,
    )
    cfg.update(patch)
    assert cfg["trigger_registered"] is True
    assert not cfg["trigger_error"]
    provider.assert_called_once()
    report = await readiness_report(db.pool, wid, graph, credential_health={})
    assert report["status"] == "waiting_for_input"
    assert report["registered_trigger_ids"] == ["in"]
