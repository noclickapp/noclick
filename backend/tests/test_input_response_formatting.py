"""B6: the resume answer surfaced to the brain must name each answer's target
(node + field, or the question label) and carry the exact mutation command,
instead of the opaque positional ``ask_i`` the brain never saw. Echoing
``- ask_0: <value>`` forced the brain to guess which question an answer belonged
to, causing misattributed values and re-asks.
"""

from wss.handlers.workflow_builder_handler import WorkflowBuilderHandler

_fmt = WorkflowBuilderHandler._format_input_response_content


def _pending(*inputs):
    return {"inputs": list(inputs)}


def test_field_bound_answer_names_node_field_and_command():
    pending = _pending({"id": "ask_0", "nodeId": "sheets_trigger",
                        "fieldKey": "spreadsheet_id", "label": "Which sheet?"})
    out = _fmt({"ask_0": "1hWCabc"}, pending)
    assert "[System: User Input Response]" in out
    assert 'Field "spreadsheet_id" on node "sheets_trigger"' in out
    assert "Which sheet?" in out
    assert '<field node="sheets_trigger" name="spreadsheet_id" value="1hWCabc" />' in out
    # the opaque positional id is never echoed back to the brain
    assert "ask_0" not in out


def test_credential_answer_carries_set_credentials_command():
    pending = _pending({"id": "ask_0", "nodeId": "sheets_trigger",
                        "fieldKey": "credential", "credentialType": "google_sheets_oauth"})
    out = _fmt({"ask_0": "cred-123"}, pending)
    assert '<set_credentials node="sheets_trigger" id="cred-123" />' in out
    assert "google_sheets_oauth" in out


def test_free_form_answer_uses_label_not_ask_id():
    pending = _pending({"id": "ask_0", "label": "What is your Retell From Number?"})
    out = _fmt({"ask_0": "+12025550137"}, pending)
    assert "- What is your Retell From Number?: +12025550137" in out
    assert "ask_0" not in out


def test_unknown_id_falls_back_to_key():
    # An answer whose id isn't in the persisted inputs still surfaces (keyed),
    # rather than being silently dropped.
    out = _fmt({"ask_9": "x"}, _pending())
    assert "- ask_9: x" in out


def test_empty_values_are_skipped():
    pending = _pending({"id": "ask_0", "label": "Q"})
    out = _fmt({"ask_0": ""}, pending)
    assert out == "[System: User Input Response]\n"


def test_message_only_matches_legacy_reply_shape():
    # A free-form chatbox reply with no form answers surfaces verbatim with the
    # "honor this reply" nudge — the shape the brain saw before message+values
    # were unified into one renderer.
    out = _fmt({}, _pending(), message="proceed without a credential")
    assert out == (
        "[System: User Input Response]\n"
        "proceed without a credential\n"
        "Honor this reply and continue the workflow."
    )


def test_partial_values_plus_message_surfaces_both():
    # The user filled one field in the form, then typed a reply in the chatbox
    # instead of finishing the wizard. Both must reach the brain so the answered
    # field isn't lost and the user never repeats themselves.
    pending = _pending(
        {"id": "ask_0", "nodeId": "sheets_trigger", "fieldKey": "spreadsheet_id",
         "label": "Which sheet?"},
        {"id": "ask_1", "label": "Which tab?"},
    )
    out = _fmt({"ask_0": "1hWCabc"}, pending, message="use the first tab you find")
    # the answered field still carries its exact mutation command
    assert '<field node="sheets_trigger" name="spreadsheet_id" value="1hWCabc" />' in out
    # the typed reply is appended, flagged as an addition to the form answers
    assert "The user also replied: use the first tab you find" in out
    assert "Honor this reply and continue the workflow." in out
