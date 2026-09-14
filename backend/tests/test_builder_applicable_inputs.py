"""Reconcile generated input requests against the credential-aware schema.

QR registration must not leave the builder asking for Cloud API fields.
"""
import pytest
from coder.workflow.graph_state import GraphState, NodeState
from coder.workflow.workflow_xml import XmlOp
from coder.workflow.agentic.commands import build_node_summary, extract_ask_requests


def graph(credential_type):
    state = GraphState()
    state.nodes["wa"] = NodeState(
        id="wa",
        type="automation-whatsapp",
        label="Monitor",
        goal="Private alerts",
        operation="receive_message",
        config={"credentialIds": {credential_type: "saved"}},
        user_fields=["webhook_url", "verify_token", "include_group_messages"],
    )
    return state


@pytest.mark.parametrize("field", ["webhook_url", "verify_token"])
def test_qr_cannot_be_asked_for_automatic_or_inapplicable_field(field):
    state = graph("whatsapp_qr")
    requests, reasons = extract_ask_requests(
        [XmlOp(tag="ask", attrs={"node": "wa", "field": field})], state
    )
    assert requests == []
    assert field in reasons[0]
    assert (
        field
        not in build_node_summary(state.nodes["wa"], state)
        .split("[needs user input:")[1]
        .split("]")[0]
    )


def test_cloud_token_and_optional_group_preference_remain_answerable():
    state = graph("whatsapp_access_token")
    requests, errors = extract_ask_requests(
        [XmlOp(tag="ask", attrs={"node": "wa", "field": "verify_token"})], state
    )
    assert errors == []
    assert requests[0]["fieldKey"] == "verify_token"
    state.to_xml()
    assert state.nodes["wa"].user_fields == ["verify_token", "include_group_messages"]


def test_changing_credentials_clears_stale_asks_on_resume():
    state = graph("whatsapp_access_token")
    state.nodes["wa"].config["credentialIds"] = {"whatsapp_qr": "existing-qr"}
    state = GraphState.from_dict(state.to_workflow_data())
    state.to_xml()
    assert state.nodes["wa"].user_fields == ["include_group_messages"]
