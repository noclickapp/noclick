"""Model-keyed agent credential resolution (second BYOK regression, 2026-08-09).

credentialIds is written by many surfaces (FE panel, builder, MCP, restores) and
any of them can leave a stale entry behind after a model switch. Downstream,
build_litellm_env treats ANY user env as "this run is BYOK" and masks every
platform key — so a mismatched bundle poisons the call (OpenRouter 401 /
OpenAI "Incorrect API key: N/A"). These tests pin the run-time guarantee in
AgentNode._resolve_model_env_overrides + match_model_credential: the env riding
a model call always belongs to that model's provider, no matter which surface
wrote the graph.
"""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from nodes.agent.config.providers import (
    filter_provider_credential_env,
    match_model_credential,
    model_credential_accepted_types,
)
from nodes.agent_node import AgentNode

GROQ_ID = "11111111-1111-1111-1111-111111111111"
OPENROUTER_ID = "22222222-2222-2222-2222-222222222222"


def _cfg(model, model_type="llm"):
    return SimpleNamespace(model=model, model_type=model_type)


class TestMatchModelCredential:
    def test_groq_key_does_not_match_openrouter_model(self):
        cfg = _cfg("openrouter/openai/gpt-5.6-luna")
        assert match_model_credential(cfg, {"agent_groq": GROQ_ID}) is None

    def test_byok_openrouter_key_is_honored_on_openrouter_model(self):
        # agent_credential_requirement says required=False for openrouter/*
        # (platform-billed) — but an ATTACHED openrouter key must still win.
        cfg = _cfg("openrouter/openai/gpt-5.6-luna")
        match = match_model_credential(cfg, {"agent_openrouter": OPENROUTER_ID})
        assert match == ("agent_openrouter", OPENROUTER_ID)

    def test_matching_provider_key_matches(self):
        cfg = _cfg("groq/llama-3.3-70b-versatile")
        assert match_model_credential(cfg, {"agent_groq": GROQ_ID}) == (
            "agent_groq",
            GROQ_ID,
        )

    def test_primary_type_beats_legacy_generic(self):
        cfg = _cfg("groq/llama-3.3-70b-versatile")
        ids = {"agent_api_key": OPENROUTER_ID, "agent_groq": GROQ_ID}
        assert match_model_credential(cfg, ids) == ("agent_groq", GROQ_ID)

    def test_legacy_generic_bundle_accepted_for_any_provider(self):
        cfg = _cfg("together_ai/meta-llama/Llama-3.3-70B-Instruct-Turbo")
        match = match_model_credential(cfg, {"agent_api_key": GROQ_ID})
        assert match == ("agent_api_key", GROQ_ID)

    def test_agent_env_is_never_a_model_credential(self):
        cfg = _cfg("groq/llama-3.3-70b-versatile")
        assert match_model_credential(cfg, {"agent_env": GROQ_ID}) is None

    def test_empty_and_unresolved_ids_are_skipped(self):
        cfg = _cfg("groq/llama-3.3-70b-versatile")
        assert match_model_credential(cfg, {"agent_groq": ""}) is None
        assert match_model_credential(cfg, {"agent_groq": "{{cred}}"}) is None
        assert match_model_credential(cfg, None) is None

    def test_bare_gpt_model_resolves_to_openai_types(self):
        # Documents the current inference: a bare gpt-* id is an OpenAI model,
        # so a groq attachment must not ride it.
        accepted = model_credential_accepted_types(_cfg("gpt-5.6-luna"))
        assert accepted[0] == "agent_openai"
        assert match_model_credential(_cfg("gpt-5.6-luna"), {"agent_groq": GROQ_ID}) is None

    def test_media_models_have_no_accepted_types(self):
        assert model_credential_accepted_types(_cfg("dall-e-3", "image")) == ()

    def test_cli_harness_accepts_provider_and_oauth_types(self):
        accepted = model_credential_accepted_types(_cfg("claude-code", "claude_code"))
        assert accepted[0] == "agent_claude_code"
        assert "agent_claude_code_oauth" in accepted
        assert "agent_api_key" in accepted



def _make_node(credential_ids, decrypted_id=None):
    node = AgentNode.__new__(AgentNode)
    node.node_data = {"credentialIds": credential_ids}
    if decrypted_id:
        node.node_data["credential_id"] = decrypted_id
    node.user_id = "user-1"
    node.organization_id = None
    node.workflow_id = "wf-1"
    return node


def _bundle(d):
    return SimpleNamespace(credentials=d)


@pytest.fixture
def identity_freshen(monkeypatch):
    async def _identity(bundle, **_kwargs):
        return bundle

    import nodes.agent.harness_oauth as harness_oauth

    monkeypatch.setattr(harness_oauth, "ensure_fresh_harness_tokens", _identity)


@pytest.mark.asyncio
class TestResolveModelEnvOverrides:
    async def test_mismatched_bundle_is_ignored_entirely(self, identity_freshen):
        """The mis-keyed-credential case: openrouter model, groq credential attached and
        decrypted by the handler — the run must behave as unattached."""
        node = _make_node({"agent_groq": GROQ_ID}, decrypted_id=GROQ_ID)
        env = await node._resolve_model_env_overrides(
            _cfg("openrouter/openai/gpt-5.6-luna"),
            _bundle({"GROQ_API_KEY": "gsk_x"}),
            "user-1",
            provider_name="openrouter",
            required_vars=["OPENROUTER_API_KEY"],
            cred_model="openrouter/openai/gpt-5.6-luna",
        )
        assert env is None

    async def test_matching_handler_decrypt_allows_only_provider_keys(
        self, identity_freshen
    ):
        node = _make_node({"agent_groq": GROQ_ID}, decrypted_id=GROQ_ID)
        env = await node._resolve_model_env_overrides(
            _cfg("groq/llama-3.3-70b-versatile"),
            _bundle(
                {
                    "GROQ_API_KEY": "gsk_x",
                    "OPENAI_BASE_URL": "http://169.254.169.254/latest/meta-data",
                    "HTTP_PROXY": "http://attacker.invalid:8080",
                    "AWS_ENDPOINT_URL": "http://127.0.0.1:9000",
                }
            ),
            "user-1",
            provider_name="groq",
            required_vars=["GROQ_API_KEY"],
            cred_model="groq/llama-3.3-70b-versatile",
        )
        assert env == {"GROQ_API_KEY": "gsk_x"}

    async def test_wrong_handler_decrypt_resolves_the_matching_id(
        self, identity_freshen, monkeypatch
    ):
        """Two credentials attached; the handler decrypted the wrong one
        (pick order) — the node must resolve the model-matching id itself."""
        import nodes.core.run_op as run_op

        resolver = AsyncMock(
            return_value={"credentials": {"OPENROUTER_API_KEY": "sk-or-x"}}
        )
        monkeypatch.setattr(run_op, "resolve_operation_credential", resolver)

        node = _make_node(
            {"agent_groq": GROQ_ID, "agent_openrouter": OPENROUTER_ID},
            decrypted_id=GROQ_ID,
        )
        env = await node._resolve_model_env_overrides(
            _cfg("openrouter/openai/gpt-5.6-luna"),
            _bundle({"GROQ_API_KEY": "gsk_x"}),
            "user-1",
            provider_name="openrouter",
            required_vars=["OPENROUTER_API_KEY"],
            cred_model="openrouter/openai/gpt-5.6-luna",
        )
        assert env == {"OPENROUTER_API_KEY": "sk-or-x"}
        assert resolver.await_args.args[0] == OPENROUTER_ID

    async def test_flat_legacy_blob_shape_is_tolerated(
        self, identity_freshen, monkeypatch
    ):
        import nodes.core.run_op as run_op

        resolver = AsyncMock(
            return_value={
                "GROQ_API_KEY": "gsk_flat",
                "OPENAI_API_BASE": "http://127.0.0.1:8000",
                "HTTPS_PROXY": "http://attacker.invalid:8080",
                "credential_type": "agent_groq",
            }
        )
        monkeypatch.setattr(run_op, "resolve_operation_credential", resolver)

        node = _make_node({"agent_groq": GROQ_ID})  # handler decrypted nothing
        env = await node._resolve_model_env_overrides(
            _cfg("groq/llama-3.3-70b-versatile"),
            None,
            "user-1",
            provider_name="groq",
            required_vars=["GROQ_API_KEY"],
            cred_model="groq/llama-3.3-70b-versatile",
        )
        assert env == {"GROQ_API_KEY": "gsk_flat"}

    async def test_media_model_keeps_only_fast_path_key(self, identity_freshen):
        node = _make_node({"agent_groq": GROQ_ID}, decrypted_id=GROQ_ID)
        env = await node._resolve_model_env_overrides(
            _cfg("dall-e-3", "image"),
            _bundle(
                {
                    "OPENROUTER_API_KEY": "sk_or_img",
                    "OPENAI_API_KEY": "sk_wrong_path",
                    "OPENAI_BASE_URL": "http://127.0.0.1:8000",
                }
            ),
            "user-1",
            provider_name="openai",
            required_vars=["OPENAI_API_KEY"],
            cred_model="dall-e-3",
        )
        assert env == {"OPENROUTER_API_KEY": "sk_or_img"}

    async def test_imagen_media_accepts_google_aliases_only(self, identity_freshen):
        node = _make_node({"agent_api_key": GROQ_ID}, decrypted_id=GROQ_ID)
        env = await node._resolve_model_env_overrides(
            _cfg("gemini/imagen-4.0-generate-001", "image"),
            _bundle(
                {
                    "GOOGLE_API_KEY": "google-img",
                    "GEMINI_API_KEY": "gemini-img",
                    "GOOGLE_API_BASE": "http://127.0.0.1:8000",
                }
            ),
            "user-1",
            provider_name="gemini",
            required_vars=["GEMINI_API_KEY"],
            cred_model="gemini/imagen-4.0-generate-001",
        )
        assert env == {
            "GEMINI_API_KEY": "gemini-img",
            "GOOGLE_API_KEY": "google-img",
        }

    async def test_matching_oauth_metadata_survives_but_endpoints_do_not(
        self, identity_freshen
    ):
        node = _make_node(
            {"agent_claude_code_oauth": GROQ_ID}, decrypted_id=GROQ_ID
        )
        env = await node._resolve_model_env_overrides(
            _cfg("claude-code", "claude_code"),
            _bundle(
                {
                    "CLAUDE_CODE_ACCESS_TOKEN": "access",
                    "CLAUDE_CODE_REFRESH_TOKEN": "refresh",
                    "CLAUDE_CODE_EXPIRES_AT": "2026-08-23T00:00:00+00:00",
                    "CLAUDE_CODE_EXPIRES_IN": "3600",
                    "ANTHROPIC_BASE_URL": "http://169.254.169.254",
                }
            ),
            "user-1",
            provider_name="claude-code",
            required_vars=["ANTHROPIC_API_KEY"],
            cred_model="claude-code",
        )
        assert env == {
            "CLAUDE_CODE_ACCESS_TOKEN": "access",
            "CLAUDE_CODE_REFRESH_TOKEN": "refresh",
            "CLAUDE_CODE_EXPIRES_AT": "2026-08-23T00:00:00+00:00",
            "CLAUDE_CODE_EXPIRES_IN": "3600",
        }


    async def test_unknown_only_bundle_is_unattached(self, identity_freshen):
        node = _make_node({"agent_groq": GROQ_ID}, decrypted_id=GROQ_ID)
        env = await node._resolve_model_env_overrides(
            _cfg("groq/llama-3.3-70b-versatile"),
            _bundle({"OPENAI_BASE_URL": "https://attacker.invalid"}),
            "user-1",
            provider_name="groq",
            required_vars=["GROQ_API_KEY"],
            cred_model="groq/llama-3.3-70b-versatile",
        )
        assert env is None

    async def test_nothing_attached_returns_none(self, identity_freshen):
        node = _make_node({})
        env = await node._resolve_model_env_overrides(
            _cfg("openrouter/openai/gpt-5.6-luna"),
            None,
            "user-1",
            provider_name="openrouter",
            required_vars=["OPENROUTER_API_KEY"],
            cred_model="openrouter/openai/gpt-5.6-luna",
        )
        assert env is None


@pytest.mark.parametrize(
    ("provider", "key_name", "base_name", "base_url"),
    [
        (
            "azure",
            "AZURE_API_KEY",
            "AZURE_API_BASE",
            "https://my-resource.openai.azure.com",
        ),
        (
            "azure",
            "AZURE_API_KEY",
            "AZURE_API_BASE",
            "https://my-resource.services.ai.azure.com/openai/deployments/main",
        ),
        (
            "azure-ai",
            "AZURE_AI_API_KEY",
            "AZURE_AI_API_BASE",
            "https://endpoint.eastus.inference.ai.azure.com/models",
        ),
        (
            "databricks",
            "DATABRICKS_API_KEY",
            "DATABRICKS_API_BASE",
            "https://dbc-123.cloud.databricks.com",
        ),
        (
            "databricks",
            "DATABRICKS_API_KEY",
            "DATABRICKS_API_BASE",
            "https://adb-123.azuredatabricks.net",
        ),
        (
            "databricks",
            "DATABRICKS_API_KEY",
            "DATABRICKS_API_BASE",
            "https://workspace.gcp.databricks.com",
        ),
    ],
)
def test_provider_managed_base_urls_are_preserved(
    provider, key_name, base_name, base_url
):
    env = filter_provider_credential_env(
        {key_name: "secret", base_name: base_url},
        provider_name=provider,
        required_vars=[key_name, base_name],
        cred_model=f"{provider}/model",
    )
    assert env == {key_name: "secret", base_name: base_url}


@pytest.mark.parametrize(
    "base_url",
    [
        "http://resource.openai.azure.com",
        "https://127.0.0.1",
        "https://resource.openai.azure.com.attacker.invalid",
        "https://openai.azure.com",
        "https://user@resource.openai.azure.com",
        "https://resource.openai.azure.com:8443",
        "https://evil.com\\resource.openai.azure.com",
        "https://-invalid.openai.azure.com",
    ],
)
def test_azure_base_url_rejects_non_provider_origins(base_url):
    with pytest.raises(ValueError, match="AZURE_API_BASE"):
        filter_provider_credential_env(
            {"AZURE_API_KEY": "secret", "AZURE_API_BASE": base_url},
            provider_name="azure",
            required_vars=["AZURE_API_KEY", "AZURE_API_BASE"],
            cred_model="azure/deployment",
        )


def test_google_provider_key_aliases_are_kept_but_proxy_is_not():
    env = filter_provider_credential_env(
        {
            "GEMINI_API_KEY": "gemini",
            "GOOGLE_API_KEY": "google",
            "GOOGLE_GENERATIVE_AI_API_KEY": "generative-ai",
            "ALL_PROXY": "http://attacker.invalid:8080",
        },
        provider_name="gemini",
        required_vars=["GEMINI_API_KEY"],
        cred_model="gemini/gemini-2.5-pro",
    )
    assert env == {
        "GEMINI_API_KEY": "gemini",
        "GOOGLE_API_KEY": "google",
        "GOOGLE_GENERATIVE_AI_API_KEY": "generative-ai",
    }


def _vertex_service_account(**overrides):
    value = {
        "type": "service_account",
        "project_id": "sample-project-123",
        "private_key_id": "key-id",
        "private_key": (
            "-----BEGIN PRIVATE KEY-----\nnot-a-real-test-key\n"
            "-----END PRIVATE KEY-----\n"
        ),
        "client_email": "agent@sample-project-123.iam.gserviceaccount.com",
        "client_id": "1234567890",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
    value.update(overrides)
    return json.dumps(value)


def test_vertex_accepts_sanitized_inline_service_account_json():
    credentials = json.loads(
        _vertex_service_account(
            auth_uri="https://attacker.invalid/auth",
            universe_domain="attacker.invalid",
            unexpected="discard-me",
        )
    )
    env = filter_provider_credential_env(
        {
            "GOOGLE_APPLICATION_CREDENTIALS": json.dumps(credentials),
            "VERTEXAI_PROJECT": "sample-project-123",
            "VERTEXAI_LOCATION": "us-central1",
        },
        provider_name="vertex_ai",
        required_vars=[
            "GOOGLE_APPLICATION_CREDENTIALS",
            "VERTEXAI_PROJECT",
            "VERTEXAI_LOCATION",
        ],
        cred_model="vertex_ai/gemini-2.5-pro",
    )
    assert env is not None
    sanitized = json.loads(env["GOOGLE_APPLICATION_CREDENTIALS"])
    assert sanitized["token_uri"] == "https://oauth2.googleapis.com/token"
    assert "auth_uri" not in sanitized
    assert "universe_domain" not in sanitized
    assert "unexpected" not in sanitized


@pytest.mark.parametrize(
    "credentials",
    [
        "/var/run/secrets/google.json",
        "../../mounted-platform-service-account.json",
        json.dumps(
            {
                "type": "external_account",
                "credential_source": {"url": "http://169.254.169.254/metadata"},
            }
        ),
        _vertex_service_account(token_uri="https://attacker.invalid/token"),
        _vertex_service_account(client_email="agent@attacker.invalid"),
    ],
)
def test_vertex_rejects_paths_external_accounts_and_custom_token_hosts(credentials):
    with pytest.raises(ValueError, match="GOOGLE_APPLICATION_CREDENTIALS"):
        filter_provider_credential_env(
            {
                "GOOGLE_APPLICATION_CREDENTIALS": credentials,
                "VERTEXAI_PROJECT": "sample-project-123",
                "VERTEXAI_LOCATION": "us-central1",
            },
            provider_name="vertex_ai",
            required_vars=[
                "GOOGLE_APPLICATION_CREDENTIALS",
                "VERTEXAI_PROJECT",
                "VERTEXAI_LOCATION",
            ],
            cred_model="vertex_ai/gemini-2.5-pro",
        )


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("VERTEXAI_PROJECT", "../../metadata"),
        ("VERTEXAI_LOCATION", "attacker.invalid/anything"),
    ],
)
def test_vertex_rejects_url_shaping_metadata(key, value):
    bundle = {
        "GOOGLE_APPLICATION_CREDENTIALS": _vertex_service_account(),
        "VERTEXAI_PROJECT": "sample-project-123",
        "VERTEXAI_LOCATION": "us-central1",
    }
    bundle[key] = value
    with pytest.raises(ValueError, match=key):
        filter_provider_credential_env(
            bundle,
            provider_name="vertex_ai",
            required_vars=[
                "GOOGLE_APPLICATION_CREDENTIALS",
                "VERTEXAI_PROJECT",
                "VERTEXAI_LOCATION",
            ],
            cred_model="vertex_ai/gemini-2.5-pro",
        )
