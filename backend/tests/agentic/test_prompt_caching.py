"""Structural tests for the agentic builder's system prompt split.

We send the same system prompt every turn (the chat-completion API is
stateless — there's no way to "not send it"). The win comes from
arranging the prompt so a long stable prefix is byte-identical across
turns: upstream providers with prefix caching (Friendli for Minimax,
OpenAI's automatic cache) hit on the prefix and skip re-billing the
input tokens. These tests pin the contract:

  1. ``build_system_prompt`` (legacy single-string) equals
     ``stable + variable`` (the parts form).
  2. The stable half is byte-identical across turns within a session,
     regardless of workflow / user context.
  3. The variable half is where per-session state lives.

No provider-specific cache markers are sent today — every brain model
we route to (Minimax via Friendli, OpenAI via OpenRouter) caches its
prefix implicitly. If we ever switch to Anthropic Claude as the brain
model, that route requires an explicit ``cache_control`` marker, and
this is the obvious place to add it.
"""

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
    """Within a session the stable half must be byte-identical
    regardless of the workflow snapshot / user context — otherwise the
    upstream prefix cache (Friendli, OpenAI) won't hit."""
    stable_a, _ = build_system_prompt_parts(
        user_context={'has_workflow': True, 'workflow_id': 'a'},
    )
    stable_b, _ = build_system_prompt_parts(
        user_context={'has_workflow': True, 'workflow_id': 'b', 'inner_tab': 'canvas'},
    )
    assert stable_a == stable_b


def test_parts_variable_section_carries_workflow_context():
    """The workflow snapshot, user context, and edit scope must land in
    the variable half — leaking them into the stable half would
    invalidate the prefix cache hit."""
    stable, variable = build_system_prompt_parts(
        user_context={'has_workflow': True, 'workflow_id': 'wf-1', 'inner_tab': 'canvas'},
    )
    assert 'Current User Context' in variable
    assert 'wf-1' in variable
    assert 'Current User Context' not in stable
    assert 'wf-1' not in stable
