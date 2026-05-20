"""Prompt-cache structure tests for the agentic builder.

The builder splits its system prompt into a stable bulk (node types,
XML command docs, output rules — byte-identical for every turn within
an edit session) and a variable tail (workflow snapshot, user context,
edit scope — turns over per turn / per session). When the brain talks
to a provider that honors Anthropic-style ``cache_control`` markers we
emit the litellm content-array form so the stable bulk gets cached;
for every other provider we send a flat string and let the upstream
prefix cache (Friendli, OpenAI, etc.) do its own thing.
"""

from coder.workflow.agentic.builder import (
    _build_system_message,
    _supports_anthropic_cache_control,
)
from coder.workflow.agentic.prompts import (
    build_system_prompt,
    build_system_prompt_parts,
)


def test_parts_match_string_form():
    """The legacy single-string ``build_system_prompt`` must equal the
    concatenation of ``build_system_prompt_parts`` — guarantees that
    existing callers / snapshot tests don't see the prompt move."""
    stable, variable = build_system_prompt_parts(silent=False)
    concatenated = stable + variable
    assert concatenated == build_system_prompt(silent=False)


def test_parts_stable_bulk_is_constant_across_turns():
    """Within a session the stable half must be byte-identical regardless
    of the workflow snapshot / user context — otherwise the cache hit is
    wasted."""
    stable_a, _ = build_system_prompt_parts(
        user_context={'has_workflow': True, 'workflow_id': 'a'},
    )
    stable_b, _ = build_system_prompt_parts(
        user_context={'has_workflow': True, 'workflow_id': 'b', 'inner_tab': 'canvas'},
    )
    assert stable_a == stable_b


def test_parts_variable_section_carries_workflow_context():
    """The workflow snapshot, user context, and edit scope must land in
    the variable half — anything else would invalidate the cache hit."""
    stable, variable = build_system_prompt_parts(
        user_context={'has_workflow': True, 'workflow_id': 'wf-1', 'inner_tab': 'canvas'},
    )
    assert 'Current User Context' in variable
    assert 'wf-1' in variable
    assert 'Current User Context' not in stable
    assert 'wf-1' not in stable


def test_anthropic_detection():
    assert _supports_anthropic_cache_control('claude-sonnet-4-6')
    assert _supports_anthropic_cache_control('anthropic/claude-opus-4-7')
    assert _supports_anthropic_cache_control('openrouter/anthropic/claude-3.5-sonnet')
    assert not _supports_anthropic_cache_control('openrouter/minimax/minimax-m2.5')
    assert not _supports_anthropic_cache_control('gpt-4o')
    assert not _supports_anthropic_cache_control('openrouter/openai/gpt-oss-120b')
    assert not _supports_anthropic_cache_control('')


def test_system_message_anthropic_emits_cache_breakpoint():
    """For Anthropic models the stable prefix gets a cache_control marker
    so the Anthropic Messages API caches it for the rest of the session."""
    msg = _build_system_message('STABLE', 'VAR', 'anthropic/claude-opus-4-7')
    assert msg['role'] == 'system'
    assert isinstance(msg['content'], list)
    assert msg['content'][0] == {
        'type': 'text',
        'text': 'STABLE',
        'cache_control': {'type': 'ephemeral'},
    }
    assert msg['content'][1] == {'type': 'text', 'text': 'VAR'}


def test_system_message_non_anthropic_uses_flat_string():
    """Minimax / OpenAI / OpenRouter-Friendli get a plain string so we
    don't risk content-array compatibility issues. The stable bulk still
    comes first so any provider-side prefix cache can hit on it."""
    msg = _build_system_message('STABLE', 'VAR', 'openrouter/minimax/minimax-m2.5')
    assert msg == {'role': 'system', 'content': 'STABLEVAR'}


def test_system_message_anthropic_skips_variable_block_when_empty():
    msg = _build_system_message('STABLE', '', 'claude-sonnet-4-6')
    assert msg['content'] == [
        {'type': 'text', 'text': 'STABLE', 'cache_control': {'type': 'ephemeral'}},
    ]
