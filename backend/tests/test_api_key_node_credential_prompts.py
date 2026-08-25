"""Pins the builder's credential-prompt signal for API-key (non-OAuth) nodes.

Added after the 2026-07-29 exa incident: `get_credential_info` gated on
OAuth-ness, so ~51 API-key node types produced NO credential line at all in the
brain's snapshot (neither "needed" nor "not required"). The brain, told never to
assume a third-party node needs an account, built an exa workflow that could
never run. These tests assert every credentialed node now emits exactly one
polarity, and that the truly-optional nodes stay quiet.
"""

import json
import re
from pathlib import Path

import pytest

from coder.workflow.operation_catalog import (
    TRULY_OPTIONAL_CREDENTIAL_NODES,
    credential_status_line,
    get_credential_info,
    node_requires_credentials,
)
from nodes.core.registry import NODE_REGISTRY


def test_api_key_node_gets_credentials_needed_line():
    """The exa case itself: an API-key node must name its DB credential type."""
    line = credential_status_line('automation-exa', None, {}, 'exa-search')
    assert line is not None
    assert line.startswith('[credentials needed: exa]')
    assert 'exa_api_key' in line


@pytest.mark.parametrize(
    'node_type,credential_type',
    [
        ('automation-exa', 'exa_api_key'),
        ('automation-firecrawl', 'firecrawl_api_key'),
        ('automation-perplexity', 'perplexity_api_key'),
        ('automation-resend', 'resend_api_key'),
    ],
)
def test_api_key_nodes_expose_credential_info(node_type, credential_type):
    info = get_credential_info(node_type, None, {})
    assert info is not None, f"{node_type} must auto-prompt for credentials"
    assert info.credential_type == credential_type


def test_oauth_nodes_unaffected():
    info = get_credential_info('automation-gmail', None, {})
    assert info is not None
    assert info.credential_type == 'google_gmail_oauth'
    assert info.is_oauth is True


def test_every_credentialed_node_emits_a_status_line():
    """No node may be silent: silence reads to the brain as "unremarkable",
    which is exactly how exa slipped through."""
    silent = [
        nt for nt in NODE_REGISTRY
        if node_requires_credentials(nt, None, {})
        and credential_status_line(nt, None, {}, 'n1') is None
    ]
    assert silent == [], f"nodes with no credential signal: {silent}"


@pytest.mark.parametrize('node_type', sorted(TRULY_OPTIONAL_CREDENTIAL_NODES))
def test_truly_optional_nodes_say_not_required(node_type):
    """Public feeds/endpoints must get the POSITIVE signal, not silence and
    not a demand — the brain treats a bare node as needing nothing."""
    assert get_credential_info(node_type, None, {}) is None
    assert credential_status_line(node_type, None, {}, 'n1') == (
        '[credentials: not required for this operation]'
    )


def test_optional_node_set_matches_frontend():
    """Drift pin: the FE's TRULY_OPTIONAL_CREDENTIALS is the same judgement
    call, and a node added to one side must be added to the other."""
    source = (
        Path(__file__).resolve().parents[2]
        / 'frontend/app/components/workflow/NodeCredentials.tsx'
    ).read_text()
    block = re.search(
        r'TRULY_OPTIONAL_CREDENTIALS:\s*Set<string>\s*=\s*new Set\(\[(.*?)\]\)',
        source,
        re.S,
    )
    assert block, "FE TRULY_OPTIONAL_CREDENTIALS set not found — did it move?"
    # Strip trailing `// …` first: the comments quote values too ('none').
    entries = '\n'.join(
        line.split('//')[0] for line in block.group(1).splitlines()
    )
    frontend = set(re.findall(r"'([^']+)'", entries))
    assert frontend == TRULY_OPTIONAL_CREDENTIAL_NODES


def _state_with(node_id, node_type, config=None):
    from coder.workflow.graph_state import GraphState, NodeState

    state = GraphState()
    state.nodes[node_id] = NodeState(
        id=node_id, type=node_type, label=node_id, goal='',
        operation='default', config=dict(config or {}),
    )
    return state


def test_uncredentialed_api_key_node_reaches_the_done_backstop():
    """The other half of the exa fix: even if the brain ignores the status
    line, the <done/> backstop must list the node."""
    from coder.workflow.agentic.commands import nodes_missing_credentials

    state = _state_with('exa-search', 'automation-exa')
    assert [n.id for n in nodes_missing_credentials(state)] == ['exa-search']


@pytest.mark.parametrize('node_type', sorted(TRULY_OPTIONAL_CREDENTIAL_NODES))
def test_truly_optional_nodes_never_reach_the_done_backstop(node_type):
    from coder.workflow.agentic.commands import nodes_missing_credentials

    state = _state_with('n1', node_type)
    assert nodes_missing_credentials(state) == []


def test_input_request_carries_db_credential_type():
    """The drawer writes credentialIds[credentialType] = id, so this field must
    be the DB type (exa_api_key), not the display provider key (exa)."""
    info = get_credential_info('automation-exa', None, {})
    assert (info.credential_type or info.provider_key) == 'exa_api_key'
