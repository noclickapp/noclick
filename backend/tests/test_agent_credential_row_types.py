"""An agent node parses its credential under every row type it can be stored as.

`utils.credentials.get_credential` stamps the credentials ROW type onto the
decrypted blob (the row is authoritative; blob tags are optional and can be
stale). Agent rows are typed per provider — `agent_openrouter`,
`agent_codex_oauth`, legacy `agents` — while the config model once declared a
single literal, so the stamping made every credentialed agent fail at parse
(2026-09-07 → 09-08: 86 runs across 7 workflows before it was noticed). These
tests parse each real row type through the same resolver production uses.
"""
from unittest.mock import AsyncMock

import pytest

from nodes.agent.config import AgentNodeConfig
from nodes.agent.config.providers import agent_credential_types
from tests.test_credential_type_resolution import _fixture

CONFIG = {"model": "codex", "message": "hello"}
# Row types seen in production that the registry does not derive.
LEGACY_ROW_TYPES = ("agents",)


@pytest.mark.parametrize("row_type", sorted(agent_credential_types()) + list(LEGACY_ROW_TYPES))
def test_every_agent_credential_row_type_parses(row_type):
    parsed = AgentNodeConfig(config=CONFIG, credentials={"credential_type": row_type, "OPENAI_API_KEY": "synthetic"})
    assert parsed.credentials.credential_type == row_type
    assert parsed.credentials.credentials == {"OPENAI_API_KEY": "synthetic"}


def test_schema_still_names_the_generic_identifier():
    # frontend/app/utils/credentialTypes.ts keys credential pickers on this const.
    schema = AgentNodeConfig.model_json_schema()
    prop = schema["$defs"]["AgentCredentials"]["properties"]["credential_type"]
    assert prop["const"] == "agent_api_key" and prop["default"] == "agent_api_key"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "row_type, blob",
    [
        # OAuth sign-ins store tokens with no type tag at all.
        ("agent_codex_oauth", {"access_token": "synthetic-token-only", "refresh_token": "synthetic-refresh-only"}),
        ("agent_claude_code_oauth", {"access_token": "synthetic-token-only"}),
        # API-key bundles carry the generic tag the frontend saved; the row wins.
        ("agent_openrouter", {"credential_type": "agent_api_key", "OPENROUTER_API_KEY": "synthetic-key-only"}),
        ("agent_opencode", {"credential_type": "agent_api_key", "OPENCODE_API_KEY": "synthetic-key-only"}),
    ],
)
async def test_agent_parses_the_authoritative_row_type_through_the_resolver(monkeypatch, row_type, blob):
    from wss.handlers.workflow_execution_handler import WorkflowExecutionHandler

    pool, _ = _fixture(monkeypatch, row_type, blob)
    handler = WorkflowExecutionHandler(sio=AsyncMock())
    handler.get_pool = AsyncMock(return_value=pool)

    resolved = await handler._resolve_credentials(
        {**CONFIG, "credentialIds": {row_type: "credential-fixture"}},
        user_id="user-fixture", org_id="org-fixture",
    )
    config = AgentNodeConfig.model_validate(resolved)
    assert config.credentials.credential_type == row_type
    secrets = {k: v for k, v in blob.items() if k != "credential_type"}
    assert config.credentials.credentials == secrets
