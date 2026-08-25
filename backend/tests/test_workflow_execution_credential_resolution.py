from unittest.mock import AsyncMock

import pytest

from wss.handlers.workflow_execution_handler import WorkflowExecutionHandler


@pytest.mark.asyncio
async def test_resolve_credentials_runs_as_workflow_owner_for_collaborator(monkeypatch):
    """A collaborator (non-owner) running a shared flow resolves the node credential
    as the workflow OWNER — so they can run it WITHOUT the credential being shared
    into their account (and thus they can't use it outside this workflow)."""
    handler = WorkflowExecutionHandler(sio=AsyncMock())
    handler.get_pool = AsyncMock(return_value=object())
    handler._get_workflow_owner_id = AsyncMock(return_value="owner-1")
    # The credential is in the workflow's owner-authorized set. The shared
    # policy calls the fail-closed check directly from utils.credentials.
    monkeypatch.setattr(
        "utils.credentials.is_credential_authorized_for_workflow",
        AsyncMock(return_value=True),
    )

    # The credential resolves ONLY for the owner (no resource_shares for the runner).
    async def fake_get_credential(credential_id, user_id, pool, org_id):
        return {"api_key": "owner-secret"} if user_id == "owner-1" else None

    # Patched at utils.credentials: the handler delegates to the shared
    # resolve_credential_with_owner_fallback policy, which reads from there.
    monkeypatch.setattr("utils.credentials.get_credential", fake_get_credential)
    node_config = {"credentialIds": {"api_key": "cred-1"}, "field": "v"}

    # Authorized + workflow context → the runner-miss falls back to the owner → resolves.
    resolved = await handler._resolve_credentials(node_config, user_id="collab-2", org_id=None, workflow_id="wf-1")
    assert resolved["credentials"] == {"api_key": "owner-secret"}
    assert resolved["credential_id"] == "cred-1"

    # NOT authorized (a collaborator pointed a node at an owner credential the owner
    # never placed on this flow) → the owner fallback is BLOCKED → ValueError. This
    # is the exfiltration guard: ownership of the credential alone is not sufficient.
    monkeypatch.setattr(
        "utils.credentials.is_credential_authorized_for_workflow",
        AsyncMock(return_value=False),
    )
    with pytest.raises(ValueError):
        await handler._resolve_credentials(node_config, user_id="collab-2", org_id=None, workflow_id="wf-1")

    # Without workflow context (e.g. the collaborator's own personal workflow),
    # there's no owner fallback — the credential is NOT resolvable for them.
    monkeypatch.setattr(
        "utils.credentials.is_credential_authorized_for_workflow",
        AsyncMock(return_value=True),
    )
    with pytest.raises(ValueError):
        await handler._resolve_credentials(node_config, user_id="collab-2", org_id=None, workflow_id=None)


@pytest.mark.asyncio
async def test_resolve_credentials_skips_empty_values_and_uses_non_empty_id(monkeypatch):
    handler = WorkflowExecutionHandler(sio=AsyncMock())
    handler.get_pool = AsyncMock(return_value=object())

    captured = {}

    async def fake_get_credential(credential_id, user_id, pool, org_id):
        captured["credential_id"] = credential_id
        captured["user_id"] = user_id
        return {"access_token": "abc", "instagram_user_id": "123"}

    # Patched at utils.credentials: the handler delegates to the shared
    # resolve_credential_with_owner_fallback policy, which reads from there.
    monkeypatch.setattr("utils.credentials.get_credential", fake_get_credential)

    node_config = {
        "action": "get_user_profile",
        "credentialIds": {
            "instagram_system_user_token": "",
            "instagram_oauth": "cred-uuid-123",
            "instagram_page_access_token": "",
        },
    }

    resolved = await handler._resolve_credentials(node_config, user_id="user-1", org_id=None)

    assert captured["credential_id"] == "cred-uuid-123"
    assert captured["user_id"] == "user-1"
    assert resolved["credentials"]["instagram_user_id"] == "123"
    assert resolved["credential_id"] == "cred-uuid-123"
    assert resolved["config"]["action"] == "get_user_profile"


@pytest.mark.asyncio
async def test_resolve_credentials_does_not_misclassify_flat_payload_with_config_key(monkeypatch):
    """If flat payload has a mirrored `config` key, credentialIds must still resolve."""
    handler = WorkflowExecutionHandler(sio=AsyncMock())
    handler.get_pool = AsyncMock(return_value=object())

    async def fake_get_credential(credential_id, user_id, pool, org_id):
        assert credential_id == "cred-uuid-456"
        return {"access_token": "abc", "instagram_user_id": "456"}

    # Patched at utils.credentials: the handler delegates to the shared
    # resolve_credential_with_owner_fallback policy, which reads from there.
    monkeypatch.setattr("utils.credentials.get_credential", fake_get_credential)

    node_config = {
        "action": "get_profile",
        "config": {"action": "get_profile"},  # mirrored nested config from frontend
        "credentialIds": {"instagram_oauth": "cred-uuid-456"},
    }

    resolved = await handler._resolve_credentials(node_config, user_id="user-1", org_id=None)
    assert resolved["credentials"]["instagram_user_id"] == "456"
    assert resolved["credential_id"] == "cred-uuid-456"


@pytest.mark.asyncio
async def test_resolve_credentials_accepts_snake_case_credential_ids(monkeypatch):
    handler = WorkflowExecutionHandler(sio=AsyncMock())
    handler.get_pool = AsyncMock(return_value=object())

    async def fake_get_credential(credential_id, user_id, pool, org_id):
        assert credential_id == "cred-uuid-789"
        return {"access_token": "abc", "instagram_user_id": "789"}

    # Patched at utils.credentials: the handler delegates to the shared
    # resolve_credential_with_owner_fallback policy, which reads from there.
    monkeypatch.setattr("utils.credentials.get_credential", fake_get_credential)

    node_config = {
        "action": "get_profile",
        "credential_ids": {"instagram_oauth": "cred-uuid-789"},
    }

    resolved = await handler._resolve_credentials(node_config, user_id="user-1", org_id=None)
    assert resolved["credentials"]["instagram_user_id"] == "789"
    assert resolved["credential_id"] == "cred-uuid-789"


@pytest.mark.asyncio
async def test_resolve_credentials_uses_inline_credentials_fallback():
    handler = WorkflowExecutionHandler(sio=AsyncMock())
    handler.get_pool = AsyncMock(return_value=object())

    node_config = {
        "action": "get_profile",
        "credentials": {
            "credential_type": "instagram_oauth",
            "access_token": "inline-token",
            "instagram_user_id": "321",
            "expires_at": "2099-01-01T00:00:00+00:00",
        },
    }

    resolved = await handler._resolve_credentials(node_config, user_id="user-1", org_id=None)
    assert resolved["credentials"]["instagram_user_id"] == "321"
    assert resolved["credentials"]["access_token"] == "inline-token"


# ---------------------------------------------------------------------------
# Agent node model resolution tests — the exact bug from the logs:
#
#   config_keys=['model', 'config', 'message', 'credentialIds', 'system_prompt']
#   → Using model: openrouter/openai/gpt-4o-mini   (WRONG — stale nested config)
#
# The frontend sends BOTH a top-level 'model' (from the visual dropdown) AND a
# nested 'config.model' (the mirrored sub-object). The top-level is always more
# recent. The old code's early-return path discarded it when credentialIds was
# an empty dict {}, falling back to the stale nested value.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agent_node_toplevel_model_overrides_stale_nested_config_model():
    """
    Reproduces the exact bug from the logs.

    The user selects 'openrouter/google/gemini-3-pro-image-preview' in the UI.
    The frontend sends:
        {
            "model": "openrouter/google/gemini-3-pro-image-preview",   ← top-level (current)
            "config": {"model": "openrouter/openai/gpt-4o-mini", ...}, ← nested (stale default)
            "message": "Generate an image of Hulk",
            "system_prompt": "...",
            "credentialIds": {},
        }

    Before the fix, _resolve_credentials returned config['model'] = 'gpt-4o-mini'.
    After the fix, the top-level 'model' wins.
    """
    handler = WorkflowExecutionHandler(sio=AsyncMock())
    handler.get_pool = AsyncMock(return_value=object())

    node_config = {
        "model": "openrouter/google/gemini-3-pro-image-preview",  # top-level from dropdown
        "config": {                                                  # stale mirrored sub-object
            "model": "openrouter/openai/gpt-4o-mini",
            "system_prompt": "You are a helpful assistant.",
            "message": "Generate an image of Hulk",
            "temperature": 0.7,
        },
        "message": "Generate an image of Hulk",
        "system_prompt": "You are a helpful assistant.",
        "temperature": 0.7,
        "credentialIds": {},
    }

    resolved = await handler._resolve_credentials(node_config, user_id="user-1", org_id=None)

    assert resolved["config"]["model"] == "openrouter/google/gemini-3-pro-image-preview", (
        "Top-level 'model' from dropdown must override stale nested config.model. "
        "Got: " + resolved["config"].get("model", "MISSING")
    )


@pytest.mark.asyncio
async def test_agent_node_nested_config_used_when_no_toplevel_model():
    """When no top-level 'model' is present, the nested config.model is used as-is."""
    handler = WorkflowExecutionHandler(sio=AsyncMock())
    handler.get_pool = AsyncMock(return_value=object())

    node_config = {
        "config": {
            "model": "openrouter/anthropic/claude-3-5-sonnet",
            "system_prompt": "You are helpful.",
            "message": "Hello",
            "temperature": 0.5,
        },
        "credentialIds": {},
    }

    resolved = await handler._resolve_credentials(node_config, user_id="user-1", org_id=None)
    assert resolved["config"]["model"] == "openrouter/anthropic/claude-3-5-sonnet"


@pytest.mark.asyncio
async def test_agent_image_model_toplevel_reaches_config():
    """
    Specifically tests that image models selected from the dropdown (gemini-3-pro-image-preview,
    gpt-5-image, dall-e-3) are not silently replaced by the stale gpt-4o-mini default.
    """
    handler = WorkflowExecutionHandler(sio=AsyncMock())
    handler.get_pool = AsyncMock(return_value=object())

    image_models = [
        "openrouter/google/gemini-3-pro-image-preview",
        "openrouter/google/gemini-2.5-flash-image",
        "openrouter/openai/gpt-5-image",
        "openrouter/openai/gpt-5-image-mini",
        "openrouter/openai/dall-e-3",
    ]

    for image_model in image_models:
        node_config = {
            "model": image_model,
            "config": {
                "model": "openrouter/openai/gpt-4o-mini",  # stale default
                "system_prompt": "Generate images.",
                "message": "Draw a sunset",
                "temperature": 0.7,
            },
            "message": "Draw a sunset",
            "system_prompt": "Generate images.",
            "credentialIds": {},
        }

        resolved = await handler._resolve_credentials(node_config, user_id="user-1", org_id=None)
        assert resolved["config"]["model"] == image_model, (
            f"Image model '{image_model}' was replaced by stale nested config model. "
            f"Got: {resolved['config'].get('model')}"
        )


@pytest.mark.asyncio
async def test_toplevel_model_override_consistent_with_credentialids_path(monkeypatch):
    """
    The credentialIds path already applied top-level overrides correctly.
    Verify that the no-credentialIds path now behaves the same way.
    """
    handler = WorkflowExecutionHandler(sio=AsyncMock())
    handler.get_pool = AsyncMock(return_value=object())

    async def fake_get_credential(credential_id, user_id, pool, org_id):
        return {"api_key": "sk-test"}

    # Patched at utils.credentials: the handler delegates to the shared
    # resolve_credential_with_owner_fallback policy, which reads from there.
    monkeypatch.setattr("utils.credentials.get_credential", fake_get_credential)

    shared_config = {
        "model": "openrouter/google/gemini-3-pro-image-preview",
        "config": {"model": "openrouter/openai/gpt-4o-mini", "message": "hi", "system_prompt": "s"},
        "message": "hi",
        "system_prompt": "s",
    }

    # With no credentialIds — the path that was buggy
    resolved_no_creds = await handler._resolve_credentials(
        {**shared_config, "credentialIds": {}},
        user_id="user-1", org_id=None
    )

    # With credentialIds — the path that worked correctly before the fix
    resolved_with_creds = await handler._resolve_credentials(
        {**shared_config, "credentialIds": {"openrouter_api_key": "cred-123"}},
        user_id="user-1", org_id=None
    )

    assert resolved_no_creds["config"]["model"] == "openrouter/google/gemini-3-pro-image-preview", \
        "no-credentialIds path must apply top-level overrides"
    assert resolved_with_creds["config"]["model"] == "openrouter/google/gemini-3-pro-image-preview", \
        "credentialIds path must apply top-level overrides"


@pytest.mark.asyncio
async def test_state_input_preserved_in_no_credentials_path():
    """__state_input__ must still be passed through after the early-return refactor."""
    handler = WorkflowExecutionHandler(sio=AsyncMock())
    handler.get_pool = AsyncMock(return_value=object())

    node_config = {
        "model": "openrouter/anthropic/claude-3-5-sonnet",
        "config": {"model": "openrouter/openai/gpt-4o-mini", "message": "hi", "system_prompt": "s"},
        "credentialIds": {},
        "__state_input__": {"node_id": "state-1", "state": {"count": 0}, "variable_name": "state", "from_function_input": False},
    }

    resolved = await handler._resolve_credentials(node_config, user_id="user-1", org_id=None)
    assert "__state_input__" in resolved
    assert resolved["__state_input__"]["node_id"] == "state-1"
