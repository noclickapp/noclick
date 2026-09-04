"""
Provider credential mapping and detection utilities.

Maps LiteLLM model prefixes to required environment variable names.
"""

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import urlsplit

# Map of model prefixes to required environment variables
PROVIDER_REQUIRED_CREDENTIALS: Dict[str, List[str]] = {
    # Simple providers (single API key)
    "openrouter/": ["OPENROUTER_API_KEY"],
    "anthropic/": ["ANTHROPIC_API_KEY"],
    "openai/": ["OPENAI_API_KEY"],
    # OpenCode Zen tiers (opencode/* and opencode-go/*) both read OPENCODE_API_KEY
    # (see handlers/opencode.py:_OPENCODE_ZEN_PREFIXES). Without these, the prefix
    # match falls through to the OPENAI_API_KEY fallback below — so the pre-flight
    # gate passes on NoClick's usage-based OpenAI key while opencode has NO Zen
    # auth, and its /message call then hangs the full 300s with no response. Naming
    # the real requirement makes the gate fail fast with a clear message instead.
    "opencode/": ["OPENCODE_API_KEY"],
    "opencode-go/": ["OPENCODE_API_KEY"],
    "gemini/": ["GEMINI_API_KEY"],
    "google/": ["GOOGLE_API_KEY"],
    "cohere/": ["COHERE_API_KEY"],
    "mistral/": ["MISTRAL_API_KEY"],
    "groq/": ["GROQ_API_KEY"],
    "together/": ["TOGETHERAI_API_KEY"],
    "together_ai/": ["TOGETHERAI_API_KEY"],
    "fireworks/": ["FIREWORKS_API_KEY"],
    "fireworks_ai/": ["FIREWORKS_API_KEY"],
    "deepseek/": ["DEEPSEEK_API_KEY"],
    "perplexity/": ["PERPLEXITYAI_API_KEY"],
    "cerebras/": ["CEREBRAS_API_KEY"],
    "xai/": ["XAI_API_KEY"],
    "replicate/": ["REPLICATE_API_TOKEN"],
    "deepinfra/": ["DEEPINFRA_API_KEY"],
    "huggingface/": ["HF_TOKEN"],
    "palm/": ["PALM_API_KEY"],
    "ai21/": ["AI21_API_KEY"],
    "nlp_cloud/": ["NLP_CLOUD_API_KEY"],
    "aleph_alpha/": ["ALEPH_ALPHA_API_KEY"],
    "voyage/": ["VOYAGE_API_KEY"],
    "nvidia_nim/": ["NVIDIA_NIM_API_KEY"],
    "sambanova/": ["SAMBANOVA_API_KEY"],
    "moonshot/": ["MOONSHOT_API_KEY"],
    "dashscope/": ["DASHSCOPE_API_KEY"],

    # Complex providers (multiple credentials required)
    "azure/": ["AZURE_API_KEY", "AZURE_API_BASE", "AZURE_API_VERSION"],
    "bedrock/": ["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_REGION_NAME"],
    "bedrock_converse/": ["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_REGION_NAME"],
    "sagemaker/": ["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_REGION_NAME"],
    "vertex_ai/": ["GOOGLE_APPLICATION_CREDENTIALS", "VERTEXAI_PROJECT", "VERTEXAI_LOCATION"],
    "cloudflare/": ["CLOUDFLARE_API_KEY", "CLOUDFLARE_ACCOUNT_ID"],
    "databricks/": ["DATABRICKS_API_KEY", "DATABRICKS_API_BASE"],
    "azure_ai/": ["AZURE_AI_API_KEY", "AZURE_AI_API_BASE"],
    "predibase/": ["PREDIBASE_API_KEY", "PREDIBASE_TENANT_ID"],
    "snowflake/": ["SNOWFLAKE_JWT", "SNOWFLAKE_ACCOUNT_ID"],

    "volcengine/": ["VOLCENGINE_API_KEY"],

    # OpenCode sub-model providers (also reachable via the OpenCode CLI;
    # these prefix entries match when agent_node.execute() rewrites
    # _cred_model to the sub-model id for an opencode_model selection).
    # Env var names are the exact strings the opencode-ai CLI reads —
    # see models.dev/providers/<id>/provider.toml `auth.env` for each.
    # github-models: PAT with models:read scope. NB this is the same env
    # var GitHub Actions injects, but it is unambiguous in the runner because
    # the process environment is constructed explicitly.
    "github-models/": ["GITHUB_TOKEN"],
    # build.nvidia.com NIM. Distinct from NVIDIA_NIM_API_KEY (on-prem NIM
    # used by the litellm nvidia_nim/ prefix above) — opencode's `nvidia`
    # provider uses NVIDIA_API_KEY.
    "nvidia/": ["NVIDIA_API_KEY"],

    # Local CLI agent harnesses
    "codex": ["OPENAI_API_KEY"],
    "claude-code": ["ANTHROPIC_API_KEY"],
    # opencode: when no sub-model is set, default to the OpenCode Zen key
    # (the typical onboarding path). When opencode_model is set,
    # agent_node.execute() rewrites _cred_model to the sub-model so this
    # entry only matches the bare wrapper or opencode/* Zen sub-models —
    # both of which require OPENCODE_API_KEY. anthropic/*, openai/*, …
    # sub-models inside OpenCode are matched by their respective prefix
    # entries above (anthropic/, openai/, etc.).
    "opencode": ["OPENCODE_API_KEY"],
    # hermes: credentials resolved dynamically from hermes_agent_model prefix
    # (e.g. openrouter/... → OPENROUTER_API_KEY, anthropic/... → ANTHROPIC_API_KEY)

    # Video/image generation providers
    "kling/": ["KLING_ACCESS_KEY", "KLING_SECRET_KEY"],
}


# Prefixes whose provider NAME folds into another's: the two OpenCode Zen
# tiers share one key and one opencode.ai/auth dashboard, so both resolve to
# the `opencode` provider (credential type `agent_opencode`). Mirrors the FE
# fold in agentCredentialModel.ts:inferProviderFromPrefix — without it the two
# sides save/search different credential types for the same key.
_PROVIDER_NAME_FOLD: Dict[str, str] = {
    "opencode-go": "opencode",
}


def get_provider_credentials(model: str) -> Tuple[List[str], str]:
    """
    Determine the required credential env vars for a given model.

    Returns:
        Tuple of (list_of_env_var_names, provider_name) for the model
    """
    model_lower = model.lower()

    for prefix, env_vars in PROVIDER_REQUIRED_CREDENTIALS.items():
        if model_lower.startswith(prefix):
            provider = prefix.rstrip("/")
            return env_vars, _PROVIDER_NAME_FOLD.get(provider, provider)

    if "claude" in model_lower:
        return ["ANTHROPIC_API_KEY"], "anthropic"
    if "gpt" in model_lower or "o1" in model_lower or "o3" in model_lower:
        return ["OPENAI_API_KEY"], "openai"
    if "gemini" in model_lower:
        return ["GEMINI_API_KEY"], "gemini"

    return ["OPENAI_API_KEY"], "openai"


@dataclass(frozen=True)
class ZenGatewayRoute:
    """How the SDK LLM path reaches an OpenCode Zen/Go model via LiteLLM."""
    litellm_model: str  # "openai/<bare id>" — the gateway is OpenAI-compatible
    base_url: str
    api_key_env: str    # env var on the agent credential holding the key


def resolve_zen_gateway_route(model: str) -> Optional[ZenGatewayRoute]:
    """Route an ``opencode/*`` / ``opencode-go/*`` model to its Zen gateway.

    LiteLLM has no native opencode provider, so the in-process SDK path
    (coder/openai_agent) rewrites the id to LiteLLM's ``openai/`` provider
    against the tier's base URL, authenticated by the tier's key from
    PROVIDER_REQUIRED_CREDENTIALS. Returns None for every other model.
    """
    from utils.opencode_zen import ZEN_TIER_BASE_URLS

    model_lower = model.lower()
    for tier, base_url in ZEN_TIER_BASE_URLS.items():
        prefix = f"{tier}/"
        if model_lower.startswith(prefix):
            return ZenGatewayRoute(
                litellm_model=f"openai/{model[len(prefix):]}",
                base_url=base_url,
                api_key_env=PROVIDER_REQUIRED_CREDENTIALS[prefix][0],
            )
    return None


# Subscription-OAuth access-token env var per provider (agent_node sets these when
# an OAuth credential is attached). A model with no API key is still credentialed
# if its provider's OAuth token is present.
_PROVIDER_OAUTH_TOKEN: Dict[str, Tuple[str, str]] = {
    "anthropic": ("CLAUDE_CODE_ACCESS_TOKEN", "a Claude subscription"),
    "openai": ("CODEX_ACCESS_TOKEN", "a ChatGPT subscription"),
}


# A provider credential is decrypted from a user-controlled row. It must never
# become a general-purpose process environment: LiteLLM and the CLI harnesses
# honor many endpoint/proxy variables, so passing the whole row through would
# let a credential smuggle an API token to an attacker-selected origin. These
# are the only subscription-login fields our OAuth flows mint and runtimes
# consume for each matching provider.
_PROVIDER_OAUTH_ENV_KEYS: Dict[str, Tuple[str, ...]] = {
    "anthropic": (
        "CLAUDE_CODE_ACCESS_TOKEN",
        "CLAUDE_CODE_REFRESH_TOKEN",
        "CLAUDE_CODE_EXPIRES_AT",
        "CLAUDE_CODE_EXPIRES_IN",
    ),
    "claude-code": (
        "CLAUDE_CODE_ACCESS_TOKEN",
        "CLAUDE_CODE_REFRESH_TOKEN",
        "CLAUDE_CODE_EXPIRES_AT",
        "CLAUDE_CODE_EXPIRES_IN",
    ),
    "openai": (
        "CODEX_ACCESS_TOKEN",
        "CODEX_REFRESH_TOKEN",
        "CODEX_ID_TOKEN",
        "CODEX_EXPIRES_AT",
        "CODEX_ACCOUNT_ID",
    ),
    "codex": (
        "CODEX_ACCESS_TOKEN",
        "CODEX_REFRESH_TOKEN",
        "CODEX_ID_TOKEN",
        "CODEX_EXPIRES_AT",
        "CODEX_ACCOUNT_ID",
    ),
}

_PROVIDER_OAUTH_ACCESS_KEYS = frozenset(
    {
        "CLAUDE_CODE_ACCESS_TOKEN",
        "CODEX_ACCESS_TOKEN",
    }
)

# Provider-defined base URLs are legitimate credentials metadata, but unlike an
# API key they are also network destinations. Keep support for the documented
# managed endpoints while rejecting private, lookalike, userinfo, non-TLS, and
# nonstandard-port destinations. A leading dot means an actual tenant/workspace
# label is required before the provider-owned suffix.
_PROVIDER_BASE_HOST_SUFFIXES: Dict[str, Tuple[str, ...]] = {
    "AZURE_API_BASE": (
        ".openai.azure.com",
        ".services.ai.azure.com",
    ),
    "AZURE_AI_API_BASE": (
        ".services.ai.azure.com",
        ".inference.ai.azure.com",
    ),
    "DATABRICKS_API_BASE": (
        ".cloud.databricks.com",
        ".azuredatabricks.net",
        ".gcp.databricks.com",
    ),
}

_PROVIDER_NON_AUTH_METADATA_KEYS = frozenset(
    {
        "AZURE_API_BASE",
        "AZURE_API_VERSION",
        "AZURE_AI_API_BASE",
        "DATABRICKS_API_BASE",
        "AWS_REGION_NAME",
        "VERTEXAI_PROJECT",
        "VERTEXAI_LOCATION",
        "CLOUDFLARE_ACCOUNT_ID",
        "PREDIBASE_TENANT_ID",
        "SNOWFLAKE_ACCOUNT_ID",
        "CLAUDE_CODE_REFRESH_TOKEN",
        "CLAUDE_CODE_EXPIRES_AT",
        "CLAUDE_CODE_EXPIRES_IN",
        "CODEX_REFRESH_TOKEN",
        "CODEX_ID_TOKEN",
        "CODEX_EXPIRES_AT",
        "CODEX_ACCOUNT_ID",
    }
)

_GOOGLE_PROVIDER_KEYS = frozenset(
    {"GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GENERATIVE_AI_API_KEY"}
)

_DNS_LABEL_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_VERTEX_LOCATION_RE = re.compile(r"^(?:global|[a-z][a-z0-9-]{0,62})$")
_VERTEX_PROJECT_RE = re.compile(
    r"^(?:[a-z][a-z0-9-]{4,28}[a-z0-9]|[0-9]{6,20})$"
)
_SERVICE_ACCOUNT_EMAIL_RE = re.compile(
    r"^[a-z0-9][a-z0-9._-]{0,126}@"
    r"[a-z][a-z0-9-]{4,28}[a-z0-9]\.iam\.gserviceaccount\.com$"
)
_MAX_VERTEX_CREDENTIAL_BYTES = 128 * 1024
_GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"


def _is_canonical_dns_hostname(hostname: str) -> bool:
    return (
        len(hostname) <= 253
        and all(_DNS_LABEL_RE.fullmatch(label) for label in hostname.split("."))
    )


def _validate_provider_base_url(env_name: str, value: str) -> None:
    """Fail closed unless a provider base URL names its managed HTTPS origin."""
    suffixes = _PROVIDER_BASE_HOST_SUFFIXES[env_name]
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ValueError(f"{env_name} must be a valid provider HTTPS URL") from exc

    hostname = (parsed.hostname or "").rstrip(".").lower()
    if (
        parsed.scheme.lower() != "https"
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
        or parsed.query
        or parsed.fragment
        or not _is_canonical_dns_hostname(hostname)
        or not any(hostname.endswith(suffix) for suffix in suffixes)
    ):
        raise ValueError(
            f"{env_name} must use a provider-managed HTTPS endpoint"
        )


def _sanitize_vertex_credentials(value: str) -> str:
    """Accept inline Google service-account JSON, never a local file path.

    LiteLLM treats an existing string as a path before attempting JSON parsing.
    Requiring and re-serializing a narrow service-account object prevents a
    credential row from reading a backend-mounted file or selecting the
    executable/URL sources supported by Google's external-account format.
    """
    if len(value.encode("utf-8")) > _MAX_VERTEX_CREDENTIAL_BYTES:
        raise ValueError(
            "GOOGLE_APPLICATION_CREDENTIALS inline JSON is too large"
        )
    try:
        raw = json.loads(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "GOOGLE_APPLICATION_CREDENTIALS must be inline service-account JSON, "
            "not a filesystem path"
        ) from exc
    if not isinstance(raw, dict) or raw.get("type") != "service_account":
        raise ValueError(
            "GOOGLE_APPLICATION_CREDENTIALS must contain a Google service-account JSON object"
        )

    client_email = raw.get("client_email")
    private_key = raw.get("private_key")
    token_uri = raw.get("token_uri")
    if (
        not isinstance(client_email, str)
        or not _SERVICE_ACCOUNT_EMAIL_RE.fullmatch(client_email.lower())
        or not isinstance(private_key, str)
        or not private_key.startswith("-----BEGIN PRIVATE KEY-----")
        or not private_key.rstrip().endswith("-----END PRIVATE KEY-----")
        or token_uri != _GOOGLE_TOKEN_URI
    ):
        raise ValueError(
            "GOOGLE_APPLICATION_CREDENTIALS must use a standard Google service account and token endpoint"
        )

    project_id = raw.get("project_id")
    if project_id is not None and (
        not isinstance(project_id, str)
        or not _VERTEX_PROJECT_RE.fullmatch(project_id)
    ):
        raise ValueError("Google service-account project_id is invalid")

    # These are the only fields google-auth needs for service-account signing.
    # In particular, omit universe_domain, trust_boundary, auth_uri, x509 URLs,
    # and every external-account credential source.
    safe = {
        key: raw[key]
        for key in (
            "type",
            "project_id",
            "private_key_id",
            "private_key",
            "client_email",
            "client_id",
            "token_uri",
        )
        if isinstance(raw.get(key), str) and raw[key]
    }
    return json.dumps(safe, separators=(",", ":"), sort_keys=True)


def _validate_vertex_metadata(key: str, value: str) -> str:
    if key == "GOOGLE_APPLICATION_CREDENTIALS":
        return _sanitize_vertex_credentials(value)
    if key == "VERTEXAI_PROJECT" and not _VERTEX_PROJECT_RE.fullmatch(value):
        raise ValueError("VERTEXAI_PROJECT must be a Google project ID or number")
    if key == "VERTEXAI_LOCATION" and not _VERTEX_LOCATION_RE.fullmatch(value):
        raise ValueError("VERTEXAI_LOCATION must be a Google Cloud region")
    return value


def _media_provider_keys(
    *, model_type: str, cred_model: str, required_vars: Sequence[str]
) -> frozenset[str]:
    """Credential keys actually consumed by each media fast path."""
    model = cred_model.strip().lower()
    if model_type == "image":
        if "imagen" in model and "openrouter/" not in model:
            return _GOOGLE_PROVIDER_KEYS
        return frozenset({"OPENROUTER_API_KEY"})
    if model_type == "video":
        if "gemini/" in model or "google/" in model:
            return _GOOGLE_PROVIDER_KEYS
        return frozenset(required_vars)
    if model_type == "kling":
        return frozenset({"KLING_ACCESS_KEY", "KLING_SECRET_KEY"})
    return frozenset()


def filter_provider_credential_env(
    bundle: Optional[Mapping[str, Any]],
    *,
    provider_name: str,
    required_vars: Sequence[str],
    cred_model: str,
    model_type: str = "llm",
) -> Optional[Dict[str, str]]:
    """Return the least-privilege environment for one model credential.

    Stored and imported credential rows are user-controlled and may predate
    current schemas, so this check intentionally runs after decryption on every
    dispatch. Unknown variables (including ``*_BASE_URL``, proxy, and AWS
    endpoint overrides) are discarded. The few provider-required base URLs are
    retained only after an exact managed-origin check.

    ``None`` means the row contained no usable authentication material. This is
    important to billing as well as security: an unknown metadata variable must
    not classify a platform-key call as BYOK and mask the real platform key.
    """
    if not bundle:
        return None

    normalized_type = (model_type or "llm").strip().lower()
    if normalized_type in {"image", "video", "kling"}:
        allowed = _media_provider_keys(
            model_type=normalized_type,
            cred_model=cred_model,
            required_vars=required_vars,
        )
    else:
        allowed_set = set(required_vars)
        provider = provider_name.strip().lower().replace("_", "-")
        allowed_set.update(_PROVIDER_OAUTH_ENV_KEYS.get(provider, ()))
        if provider in {"gemini", "google"}:
            allowed_set.update(_GOOGLE_PROVIDER_KEYS)
        allowed = frozenset(allowed_set)

    filtered: Dict[str, str] = {}
    for key in allowed:
        value = bundle.get(key)
        if not isinstance(value, str) or not value.strip():
            continue
        if key in _PROVIDER_BASE_HOST_SUFFIXES:
            _validate_provider_base_url(key, value)
        if key in {
            "GOOGLE_APPLICATION_CREDENTIALS",
            "VERTEXAI_PROJECT",
            "VERTEXAI_LOCATION",
        }:
            value = _validate_vertex_metadata(key, value)
        filtered[key] = value

    usable_keys = allowed.difference(_PROVIDER_NON_AUTH_METADATA_KEYS)
    usable_keys = usable_keys.union(_PROVIDER_OAUTH_ACCESS_KEYS)
    if not any(key in filtered for key in usable_keys):
        return None
    return filtered


def validate_provider_credentials(model: str, env_overrides: Optional[Dict[str, str]]) -> None:
    """Raise ``ValueError`` when ``model``'s provider has neither its required API
    key nor a matching subscription-OAuth token in ``env_overrides``.

    The CLI path's pre-flight gate: a missing credential fails fast here with a
    clear message instead of starting a process that errors at turn time. Only
    reliable for provider-prefixed models (openrouter/anthropic/openai/xai/…)."""
    required_vars, provider_name = get_provider_credentials(model)
    env = env_overrides or {}
    if any(env.get(v) for v in required_vars):
        return
    oauth = _PROVIDER_OAUTH_TOKEN.get(provider_name)
    if oauth and env.get(oauth[0]):
        return
    # Name the one sign-in that would work here, not the whole list: the reader
    # has already chosen a provider.
    suffix = f", or sign in with {oauth[1]}" if oauth else ""
    raise ValueError(
        f"Missing credentials for {provider_name}: provide "
        f"{' or '.join(required_vars)}{suffix} on the agent node."
    )


# ============================================================================
# Agent credential requirement (builder-facing)
# ============================================================================

# Wrapper model id → sub-model config field. Mirrors agent_node.execute()'s
# _cred_model rewrite and the FE's WRAPPER_SUBMODEL_FIELD_BY_MODEL
# (agentCredentialModel.ts): the sub-model's provider decides which credential
# the harness needs. codex/claude-code have fixed providers (codex_model only
# picks the OpenAI model, never the credential).
HARNESS_SUBMODEL_FIELDS: Dict[str, str] = {
    "hermes": "hermes_agent_model",
    "openclaw": "openclaw_model",
    "opencode": "opencode_model",
}

# model_type discriminator → wrapper model id (the FE mirror is agentChat.ts
# CLI_MODEL_PROVIDER, inverted; pinned by tests/test_agent_harness_credentials.py).
WRAPPER_ID_BY_MODEL_TYPE: Dict[str, str] = {
    "codex": "codex",
    "claude_code": "claude-code",
    "opencode": "opencode",
    "openclaw": "openclaw",
    "hermes_agent": "hermes",
}

# Subscription-OAuth credential_type per provider stem. Mirrors the FE alias
# map in agentCredentialModel.ts:getAgentCredentialIdForProvider; the OAuth
# socket handlers (wss/handlers/oauth/*) mint exactly these type strings.
AGENT_OAUTH_CREDENTIAL_TYPES: Dict[str, str] = {
    "codex": "agent_codex_oauth",
    "openai": "agent_codex_oauth",
    "claude-code": "agent_claude_code_oauth",
    "anthropic": "agent_claude_code_oauth",
}


def register_subscription_provider(
    *,
    model_prefix: str,
    credential_type: str,
    access_token_env: str,
    env_keys: Tuple[str, ...],
    subscription: Optional[str] = None,
    metadata_keys: Tuple[str, ...] = (),
    oauth_only: bool = False,
) -> None:
    """A subscription sign-in this deployment offers for the ``<model_prefix>/``
    model family: the credential type it mints, the env vars the runtimes
    receive for it (``env_keys``; ``metadata_keys`` are the non-auth ones —
    refresh tokens, expiries), and, when the family has no API-key path at
    all, the token as its required credential. ``subscription`` names it in
    "missing credential" messages for families that also accept a key."""
    global _PROVIDER_OAUTH_ACCESS_KEYS, _PROVIDER_NON_AUTH_METADATA_KEYS
    if oauth_only:
        PROVIDER_REQUIRED_CREDENTIALS[f"{model_prefix}/"] = [access_token_env]
    if subscription:
        _PROVIDER_OAUTH_TOKEN[model_prefix] = (access_token_env, subscription)
    _PROVIDER_OAUTH_ENV_KEYS[model_prefix] = tuple(env_keys)
    _PROVIDER_OAUTH_ACCESS_KEYS = frozenset(_PROVIDER_OAUTH_ACCESS_KEYS | {access_token_env})
    _PROVIDER_NON_AUTH_METADATA_KEYS = frozenset(_PROVIDER_NON_AUTH_METADATA_KEYS | set(metadata_keys))
    AGENT_OAUTH_CREDENTIAL_TYPES[model_prefix] = credential_type


@dataclass(frozen=True)
class AgentCredentialRequirement:
    """Whether an agent node's config needs a user credential, and which."""
    required: bool
    credential_type: str = ""  # primary DB type to search, e.g. "agent_codex"
    accepted_types: Tuple[str, ...] = ()  # every credentialIds key that satisfies it
    env_vars: Tuple[str, ...] = ()
    provider: str = ""  # FE provider stem, e.g. "codex", "openrouter"
    label: str = ""


def _submodel_default(wrapper_id: str) -> str:
    field = HARNESS_SUBMODEL_FIELDS.get(wrapper_id)
    if not field:
        return ""
    # Local imports: these modules import only .base, so no cycle — but keep
    # them off providers.py's module load, which handlers import standalone.
    from .hermes_agent import HermesAgentConfig
    from .openclaw import OpenClawConfig
    from .opencode import OpenCodeConfig
    cls = {
        "hermes": HermesAgentConfig,
        "openclaw": OpenClawConfig,
        "opencode": OpenCodeConfig,
    }[wrapper_id]
    default = cls.model_fields[field].default
    return default if isinstance(default, str) else ""


def resolve_agent_cred_model(config: Any) -> str:
    """The model whose provider decides the agent's credential.

    The sub-model wins for hermes/openclaw/opencode (the schema default applies
    when the config lacks it); codex/claude-code keep the wrapper id (their
    sub-model only picks which OpenAI/Anthropic model runs, never the
    credential); everything else passes through unchanged. Accepts the
    validated Pydantic config (execute path) or a raw config dict (builder
    paths) — the ONE sub-model-resolution rule for both.
    """
    get = config.get if isinstance(config, dict) else (lambda k: getattr(config, k, None))
    model = str(get("model") or "").strip()
    field = HARNESS_SUBMODEL_FIELDS.get(model)
    if not field:
        return model
    sub = str(get(field) or "").strip()
    return sub or _submodel_default(model) or model


def _requirement_for(cred_model: str, *, oauth_capable: bool) -> AgentCredentialRequirement:
    env_vars, provider_name = get_provider_credentials(cred_model)
    stem = provider_name.replace("-", "_")
    primary = f"agent_{stem}"
    accepted = [primary, "agent_api_key"]  # legacy generic env-var bundles
    if provider_name == "opencode":
        accepted.append("agent_opencode_go")  # pre-fold rows saved under the Go stem
    if oauth_capable:
        oauth_type = AGENT_OAUTH_CREDENTIAL_TYPES.get(provider_name)
        if oauth_type:
            accepted.append(oauth_type)
    label = f"{stem.replace('_', ' ').title()} agent credential ({' or '.join(env_vars)})"
    return AgentCredentialRequirement(
        required=True,
        credential_type=primary,
        accepted_types=tuple(accepted),
        env_vars=tuple(env_vars),
        provider=stem,
        label=label,
    )


def agent_credential_requirement(config: Optional[Dict[str, Any]]) -> AgentCredentialRequirement:
    """Whether an agent node needs a USER credential for its selected model.

    The billing rule, not just "which env var":
    - CLI harnesses (codex / claude-code / opencode / openclaw / hermes) ALWAYS
      need a user credential — sandbox harness runs have no per-call cost
      capture, so a platform key would fund untracked usage.
    - The SDK LLM path on an openrouter/* model runs on NoClick's platform key
      with per-call cost capture — no user credential.
    - Media model types (image / video / kling) run on platform keys with flat
      per-unit pricing — no user credential.
    - Any other LLM model (anthropic/*, openai/*, …) needs the user's own
      provider key: platform keys for those providers are masked (ENV_MASK).
    """
    from .base import infer_model_type

    cfg = config or {}
    model = str(cfg.get("model") or "").strip()
    probe: Dict[str, Any] = {"model": model}
    if cfg.get("model_type"):
        probe["model_type"] = cfg["model_type"]
    model_type = infer_model_type(probe).get("model_type", "llm")

    if model_type in ("image", "video", "kling"):
        return AgentCredentialRequirement(required=False)

    if model_type == "llm":
        if not model or model.lower().startswith("openrouter/"):
            return AgentCredentialRequirement(required=False)
        return _requirement_for(model, oauth_capable=False)

    # CLI harness: same sub-model resolution the execute path uses.
    wrapper_id = model or WRAPPER_ID_BY_MODEL_TYPE.get(model_type, "")
    cred_model = resolve_agent_cred_model({**cfg, "model": wrapper_id})
    return _requirement_for(cred_model, oauth_capable=True)


def model_credential_accepted_types(config: Any) -> Tuple[str, ...]:
    """Every credentialIds key that can AUTHENTICATE the selected model.

    Companion to agent_credential_requirement asking a different question:
    that one's ``required`` encodes the billing rule (openrouter/media run on
    platform keys — no credential demanded), while this one always names the
    provider-matched types, so an OPTIONAL BYOK key (agent_openrouter on an
    openrouter/* model) is honored and a mismatched one can be rejected.
    Media model types return () — flat platform pricing, no provider inference.
    """
    from .base import infer_model_type

    get = config.get if isinstance(config, dict) else (lambda k: getattr(config, k, None))
    model = str(get("model") or "").strip()
    probe: Dict[str, Any] = {"model": model}
    if get("model_type"):
        probe["model_type"] = get("model_type")
    model_type = infer_model_type(probe).get("model_type", "llm")

    if model_type in ("image", "video", "kling"):
        return ()

    if model_type == "llm":
        cred_model = resolve_agent_cred_model(config)
        if not cred_model:
            return ()
        return _requirement_for(cred_model, oauth_capable=False).accepted_types

    if isinstance(config, dict) and not model:
        wrapper_id = WRAPPER_ID_BY_MODEL_TYPE.get(model_type, "")
        cred_model = resolve_agent_cred_model({**config, "model": wrapper_id})
    else:
        cred_model = resolve_agent_cred_model(config)
    if not cred_model:
        return ()
    return _requirement_for(cred_model, oauth_capable=True).accepted_types


def match_model_credential(
    config: Any, credential_ids: Optional[Dict[str, Any]]
) -> Optional[Tuple[str, str]]:
    """The ``(credential_type, credential_id)`` entry in ``credential_ids``
    that matches the selected model's provider — accepted-type order, primary
    first. None when nothing attached satisfies the model. Validity predicate
    mirrors utils.credentials.pick_credential_id."""
    for cred_type in model_credential_accepted_types(config):
        value = (credential_ids or {}).get(cred_type)
        if isinstance(value, str) and value.strip() and "{{" not in value:
            return cred_type, value
    return None


def agent_credential_types() -> frozenset:
    """Every credential_type an agent credential can be stored under.

    The FE saves API-key bundles as ``agent_<provider>`` (agentCredentialModel.ts)
    and the OAuth handlers mint the ``agent_*_oauth`` variants; none of these
    appear in node schemas, so known_credential_types() unions this in.
    """
    types = {"agent_api_key", "agent_env", "agent_openclaw", "agent_hermes_agent"}
    types.update(
        f"agent_{prefix.rstrip('/').replace('-', '_')}"
        for prefix in PROVIDER_REQUIRED_CREDENTIALS
    )
    types.update(AGENT_OAUTH_CREDENTIAL_TYPES.values())
    return frozenset(types)
