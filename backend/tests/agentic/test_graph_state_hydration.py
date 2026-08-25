"""Regression tests for GraphState.from_dict and NodeState.to_execution_config.

Pins the round-trip between the FE persisted shape (top-level metadata
flattened into the `config` blob by `buildSaveConfig` in
applyNodeUpdate.ts) and the in-memory NodeState the agentic builder
expects. Before the fix, the resume-after-ask path hydrated
node.operation / node.label / etc. from top-level keys that don't exist
in the saved shape, leaving operation=None — then to_execution_config
overwrote the real `config['operation']` value with None at run time
and the executor failed with "operation field is required".
"""

from coder.workflow.graph_state import GraphState


# Flat saved-blob shape: what `serializeNodeForSave` writes to public.workflows.
# operation / label / goal / userFields / operationReason / content live INSIDE
# config alongside actual schema fields and credentialIds.
FLAT_SAVED_SHAPE = {
    'nodes': [
        {
            'id': 'slack',
            'type': 'automation-slack',
            'position': {'x': 0, 'y': 0},
            'config': {
                'label': 'Slack',
                'goal': 'Get channels and messages',
                'operation': 'get_channel_messages',
                'operationReason': 'Retrieves messages',
                'userFields': ['channel'],
                'content': 'Slack',
                'channel': 'C0000000004',
                'credentialIds': {'slack_oauth': 'cred-123'},
            },
        }
    ],
    'edges': [],
}

# Canvas-edit shape: what `useCanvasWorkflowEdit.ts` sends (hoisted top-level).
CANVAS_EDIT_SHAPE = {
    'nodes': [
        {
            'id': 'slack',
            'type': 'automation-slack',
            'position': {'x': 0, 'y': 0},
            'label': 'Slack',
            'goal': 'Get channels and messages',
            'operation': 'get_channel_messages',
            'config': {
                'channel': 'C0000000004',
                'credentialIds': {'slack_oauth': 'cred-123'},
                # The canvas path also includes operation here because
                # n.data.config carries everything; the loader must not be
                # tripped up by the duplicate.
                'operation': 'get_channel_messages',
            },
        }
    ],
    'edges': [],
}


def test_from_dict_flat_saved_shape_hoists_metadata():
    """The resume path passes the saved blob unmodified — operation,
    label, goal, userFields must populate the NodeState attrs even
    though they live inside `config`."""
    state = GraphState.from_dict(FLAT_SAVED_SHAPE)
    node = state.get_node('slack')

    assert node is not None
    assert node.operation == 'get_channel_messages'
    assert node.operation_reason == 'Retrieves messages'
    assert node.label == 'Slack'
    assert node.goal == 'Get channels and messages'
    assert node.user_fields == ['channel']
    assert node.content == 'Slack'

    # Metadata gets *moved* out of config so the brain snapshot doesn't
    # render it twice (once as the <node> attribute, once as a child).
    # Actual schema fields and credentialIds stay put.
    assert 'operation' not in node.config
    assert 'label' not in node.config
    assert 'goal' not in node.config
    assert 'userFields' not in node.config
    assert node.config['channel'] == 'C0000000004'
    assert node.config['credentialIds'] == {'slack_oauth': 'cred-123'}


def test_from_dict_canvas_edit_shape_still_works():
    """Top-level metadata still wins when both shapes are present."""
    state = GraphState.from_dict(CANVAS_EDIT_SHAPE)
    node = state.get_node('slack')

    assert node is not None
    assert node.operation == 'get_channel_messages'
    assert node.label == 'Slack'
    assert node.goal == 'Get channels and messages'
    assert node.config['channel'] == 'C0000000004'
    # The duplicate `operation` inside config got popped (top-level won
    # the precedence check; the config copy is stripped to avoid drift).
    assert 'operation' not in node.config


def test_to_execution_config_keeps_operation_when_attr_set():
    state = GraphState.from_dict(FLAT_SAVED_SHAPE)
    node = state.get_node('slack')
    exec_config = node.to_execution_config()

    assert exec_config['operation'] == 'get_channel_messages'
    assert exec_config['label'] == 'Slack'
    assert exec_config['channel'] == 'C0000000004'
    assert exec_config['credentialIds'] == {'slack_oauth': 'cred-123'}


def test_to_execution_config_does_not_wipe_operation_with_none():
    """If hydration ever leaves node.operation=None while config still
    holds an operation value (defense in depth), the merge must NOT
    overwrite it with None — that was the original run-time failure."""
    state = GraphState.from_dict({
        'nodes': [{
            'id': 'slack',
            'type': 'automation-slack',
            'config': {'operation': 'get_channel_messages', 'channel': 'X'},
        }],
        'edges': [],
    })
    node = state.get_node('slack')
    # Force the pathological state: pretend the hoist didn't run.
    node.operation = None
    node.config['operation'] = 'get_channel_messages'

    exec_config = node.to_execution_config()
    assert exec_config['operation'] == 'get_channel_messages'


def test_from_dict_empty_config_does_not_crash():
    state = GraphState.from_dict({
        'nodes': [{'id': 'n1', 'type': 'agent'}],
        'edges': [],
    })
    node = state.get_node('n1')
    assert node is not None
    assert node.operation is None
    assert node.config == {}
