"""Tests for WorkflowExecutionHandler._check_output_for_error.

Nodes that report failure by RETURNING output (instead of raising) must halt
the run: agent nodes emit type='agent' status='failed' with the provider error
in 'response'/'error' — letting that flow downstream templated a raw
litellm.APIError into WhatsApp DMs (2026-06/07 incident).
"""
import sys

sys.path.insert(0, "backend")

from wss.handlers.workflow_execution_handler import WorkflowExecutionHandler

check = WorkflowExecutionHandler._check_output_for_error


def test_agent_failed_output_is_an_error():
    output = {
        "type": "agent",
        "status": "failed",
        "response": "Error: litellm.APIError: OpenrouterException - requires more credits",
        "error": "litellm.APIError: OpenrouterException - requires more credits",
    }
    assert check(None, output) == "litellm.APIError: OpenrouterException - requires more credits"


def test_agent_failed_without_error_key_uses_response():
    output = {"type": "agent", "status": "failed", "response": "Error: rate limited"}
    assert check(None, output) == "Error: rate limited"


def test_agent_completed_output_passes():
    output = {"type": "agent", "status": "completed", "response": "All done!"}
    assert check(None, output) is None


def test_non_agent_failed_status_passes():
    """Integration nodes can return provider payloads with status='failed'
    (e.g. a fetched payment object) — that's a successful node run."""
    output = {"id": "pi_123", "status": "failed", "amount": 500}
    assert check(None, output) is None


def test_error_status_still_detected():
    output = {"status": "error", "error": "boom"}
    assert check(None, output) == "boom"


def test_nonzero_exit_code_still_detected():
    output = {"exit_code": 2, "stderr": "traceback"}
    assert check(None, output) == "traceback"


def test_non_dict_output_passes():
    assert check(None, "plain text") is None
    assert check(None, None) is None
