"""
Brandfetch brand intelligence automation node.

Provides workflow integration with the Brandfetch REST API for operations including:
- Brand lookups: by domain, ticker, ISIN, crypto symbol, or auto-detect identifier
- Brand context (AI/LLM-oriented): JSON or Markdown
- Brand search (autocomplete by name)
- Transaction identification (map a statement descriptor to a brand)
- Logo CDN URLs: by domain, ticker, crypto, ISIN, plus themed/sized variants
- Webhook Trigger: receive brand-change events (brand.updated, brand.company.updated)

Authentication:
- API key (Bearer token) for the Brand / Brand Context / Transaction APIs (server-side, secret).
- A separate public Client ID (?c= query param) for the Logo CDN and Brand Search APIs.

API Base URL: https://api.brandfetch.io/v2 (data APIs); https://cdn.brandfetch.io (Logo CDN)
Documentation: https://docs.brandfetch.com
"""

import logging
import time
from typing import Dict, Any, Optional, Literal, Union, Annotated, List
from pydantic import BaseModel, Field, ConfigDict, Discriminator
from utils.webhook_signatures import verify_svix
import httpx

from nodes.core.base import WorkflowNode, NodeConfig

logger = logging.getLogger(__name__)

BRANDFETCH_API_BASE = "https://api.brandfetch.io/v2"
BRANDFETCH_CDN_BASE = "https://cdn.brandfetch.io"

# Brandfetch webhook event types (Standard Webhooks v1.0.0). The inbound payload
# carries the event identifier in its top-level ``type`` field. Brandfetch
# delivers every event to a single endpoint with no per-subscription filter, so
# the trigger filters by ``type`` at runtime against the user-selected events.
# The "*" sentinel means "any event".
BRANDFETCH_WEBHOOK_EVENT_ALL = "*"
BRANDFETCH_WEBHOOK_EVENTS: List[str] = [
    BRANDFETCH_WEBHOOK_EVENT_ALL,
    "brand.updated",
    "brand.company.updated",
    "brand.claimed",
    "brand.verified",
    "brand.deleted",
]
BRANDFETCH_WEBHOOK_EVENT_NAMES: List[str] = [
    "All brand events",
    "Brand updated",
    "Brand company data updated",
    "Brand claimed",
    "Brand verified",
    "Brand deleted",
]


# ============================================================================
# Credential Schema
# ============================================================================


class BrandfetchApiKeyCredential(BaseModel):
    """API key (Bearer) + public Client ID credential for Brandfetch.

    The API key is a secret used for the Brand / Brand Context / Transaction
    APIs. The Client ID is a public identifier required by the Logo CDN and
    Brand Search APIs (passed as ?c=). Both are issued from the developer portal.
    """

    credential_type: Literal["brandfetch_api_key"] = Field(
        "brandfetch_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ...,
        title="API Key",
        description="Your Brandfetch API key (Bearer token) for Brand, Context, and Transaction APIs",
        json_schema_extra={"ui:widget": "password"},
    )
    client_id: Optional[str] = Field(
        None,
        title="Client ID",
        description="Public Client ID required by the Logo CDN and Brand Search operations (passed as ?c=)",
        json_schema_extra={
            "ui:help": "Optional. Only needed for Logo and Search operations.",
        },
    )

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-url": "https://developers.brandfetch.com/register",
            "x-credential-instructions": (
                "Create a free account at developers.brandfetch.com, then copy your API key "
                "(Bearer, keep secret) and your public Client ID from the dashboard."
            ),
        }
    )


BrandfetchCredential = BrandfetchApiKeyCredential


# ============================================================================
# Operation Configs
# ============================================================================


class BrandfetchGetBrandByDomainConfig(BaseModel):
    """Fetch the full brand record for a domain (logos, colors, fonts, social links)."""

    operation: Literal["get_brand_by_domain"] = Field(
        "get_brand_by_domain",
        json_schema_extra={
            "const": "get_brand_by_domain",
            "ui:hidden": True,
            "x-category": "Brand",
            "x-is-trigger": False,
            "x-display-name": "Get Brand by Domain",
        },
        title="Get Brand by Domain",
    )
    domain: str = Field(
        ..., title="Domain", description="Domain to look up, e.g. nike.com"
    )
    allow_nsfw: str = Field(
        "false",
        title="Allow NSFW",
        description="Include NSFW brands in results",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class BrandfetchGetBrandByTickerConfig(BaseModel):
    """Look up a brand by stock/ETF ticker symbol (e.g. NKE)."""

    operation: Literal["get_brand_by_ticker"] = Field(
        "get_brand_by_ticker",
        json_schema_extra={
            "const": "get_brand_by_ticker",
            "ui:hidden": True,
            "x-category": "Brand",
            "x-is-trigger": False,
            "x-display-name": "Get Brand by Ticker",
        },
        title="Get Brand by Ticker",
    )
    ticker: str = Field(
        ..., title="Ticker", description="Stock or ETF ticker symbol, e.g. NKE"
    )


class BrandfetchGetBrandByIsinConfig(BaseModel):
    """Look up a brand by ISIN code (e.g. US6541061031)."""

    operation: Literal["get_brand_by_isin"] = Field(
        "get_brand_by_isin",
        json_schema_extra={
            "const": "get_brand_by_isin",
            "ui:hidden": True,
            "x-category": "Brand",
            "x-is-trigger": False,
            "x-display-name": "Get Brand by ISIN",
        },
        title="Get Brand by ISIN",
    )
    isin: str = Field(
        ..., title="ISIN", description="ISIN code, e.g. US6541061031"
    )


class BrandfetchGetBrandByCryptoConfig(BaseModel):
    """Look up a brand by cryptocurrency symbol (e.g. BTC)."""

    operation: Literal["get_brand_by_crypto"] = Field(
        "get_brand_by_crypto",
        json_schema_extra={
            "const": "get_brand_by_crypto",
            "ui:hidden": True,
            "x-category": "Brand",
            "x-is-trigger": False,
            "x-display-name": "Get Brand by Crypto",
        },
        title="Get Brand by Crypto",
    )
    symbol: str = Field(
        ..., title="Crypto Symbol", description="Cryptocurrency symbol, e.g. BTC"
    )


class BrandfetchGetBrandConfig(BaseModel):
    """Auto-detect lookup: resolves identifier in order domain -> ticker -> ISIN -> crypto."""

    operation: Literal["get_brand"] = Field(
        "get_brand",
        json_schema_extra={
            "const": "get_brand",
            "ui:hidden": True,
            "x-category": "Brand",
            "x-is-trigger": False,
            "x-display-name": "Get Brand (Auto-detect)",
        },
        title="Get Brand (Auto-detect)",
    )
    identifier: str = Field(
        ...,
        title="Identifier",
        description="Domain, ticker, ISIN, or crypto symbol (auto-detected)",
    )


class BrandfetchGetContextJsonConfig(BaseModel):
    """Get AI/LLM-oriented structured brand intelligence as JSON."""

    operation: Literal["get_context_json"] = Field(
        "get_context_json",
        json_schema_extra={
            "const": "get_context_json",
            "ui:hidden": True,
            "x-category": "Context",
            "x-is-trigger": False,
            "x-display-name": "Get Brand Context (JSON)",
        },
        title="Get Brand Context (JSON)",
    )
    domain: str = Field(
        ..., title="Domain", description="Domain to fetch brand context for, e.g. nike.com"
    )


class BrandfetchGetContextMarkdownConfig(BaseModel):
    """Get AI/LLM-ready brand intelligence as Markdown to drop into a prompt."""

    operation: Literal["get_context_markdown"] = Field(
        "get_context_markdown",
        json_schema_extra={
            "const": "get_context_markdown",
            "ui:hidden": True,
            "x-category": "Context",
            "x-is-trigger": False,
            "x-display-name": "Get Brand Context (Markdown)",
        },
        title="Get Brand Context (Markdown)",
    )
    domain: str = Field(
        ..., title="Domain", description="Domain to fetch brand context for, e.g. nike.com"
    )


class BrandfetchSearchConfig(BaseModel):
    """Autocomplete-style brand search by name (requires the public Client ID)."""

    operation: Literal["search_brands"] = Field(
        "search_brands",
        json_schema_extra={
            "const": "search_brands",
            "ui:hidden": True,
            "x-category": "Search",
            "x-is-trigger": False,
            "x-display-name": "Search Brands",
        },
        title="Search Brands",
    )
    name: str = Field(
        ..., title="Brand Name", description="Brand name to search for, e.g. Nike"
    )


class BrandfetchTransactionConfig(BaseModel):
    """Map a raw bank/card statement descriptor to a merchant brand."""

    operation: Literal["identify_transaction"] = Field(
        "identify_transaction",
        json_schema_extra={
            "const": "identify_transaction",
            "ui:hidden": True,
            "x-category": "Transaction",
            "x-is-trigger": False,
            "x-display-name": "Identify Brand from Transaction",
        },
        title="Identify Brand from Transaction",
    )
    transaction_label: str = Field(
        ...,
        title="Transaction Label",
        description="Raw statement descriptor, e.g. 'SQ *COFFEE SHOP'",
    )
    country_code: str = Field(
        ...,
        title="Country Code",
        description="ISO 3166-1 alpha-2 country code, e.g. US (required by the API)",
    )


# Logo CDN type enum shared across logo operations.
_LOGO_TYPE_EXTRA = {
    "enum": ["logo", "icon", "symbol"],
    "enumNames": ["Logo", "Icon", "Symbol"],
    "x-enum-searchable": True,
}


class BrandfetchLogoByDomainConfig(BaseModel):
    """Build a Logo CDN URL for a domain (requires the public Client ID)."""

    operation: Literal["logo_by_domain"] = Field(
        "logo_by_domain",
        json_schema_extra={
            "const": "logo_by_domain",
            "ui:hidden": True,
            "x-category": "Logo",
            "x-is-trigger": False,
            "x-display-name": "Fetch Logo by Domain",
        },
        title="Fetch Logo by Domain",
    )
    domain: str = Field(
        ..., title="Domain", description="Domain to fetch the logo for, e.g. nike.com"
    )
    logo_type: str = Field(
        "logo",
        title="Logo Type",
        description="Which asset variant to return",
        json_schema_extra=_LOGO_TYPE_EXTRA,
    )


class BrandfetchLogoByTickerConfig(BaseModel):
    """Build a Logo CDN URL for a stock ticker (requires the public Client ID)."""

    operation: Literal["logo_by_ticker"] = Field(
        "logo_by_ticker",
        json_schema_extra={
            "const": "logo_by_ticker",
            "ui:hidden": True,
            "x-category": "Logo",
            "x-is-trigger": False,
            "x-display-name": "Fetch Logo by Ticker",
        },
        title="Fetch Logo by Ticker",
    )
    ticker: str = Field(
        ..., title="Ticker", description="Stock or ETF ticker symbol, e.g. NKE"
    )
    logo_type: str = Field(
        "logo",
        title="Logo Type",
        description="Which asset variant to return",
        json_schema_extra=_LOGO_TYPE_EXTRA,
    )


class BrandfetchLogoByCryptoConfig(BaseModel):
    """Build a Logo CDN URL for a crypto symbol (requires the public Client ID)."""

    operation: Literal["logo_by_crypto"] = Field(
        "logo_by_crypto",
        json_schema_extra={
            "const": "logo_by_crypto",
            "ui:hidden": True,
            "x-category": "Logo",
            "x-is-trigger": False,
            "x-display-name": "Fetch Logo by Crypto",
        },
        title="Fetch Logo by Crypto",
    )
    symbol: str = Field(
        ..., title="Crypto Symbol", description="Cryptocurrency symbol, e.g. BTC"
    )
    logo_type: str = Field(
        "logo",
        title="Logo Type",
        description="Which asset variant to return",
        json_schema_extra=_LOGO_TYPE_EXTRA,
    )


class BrandfetchLogoByIsinConfig(BaseModel):
    """Build a Logo CDN URL for an ISIN (requires the public Client ID)."""

    operation: Literal["logo_by_isin"] = Field(
        "logo_by_isin",
        json_schema_extra={
            "const": "logo_by_isin",
            "ui:hidden": True,
            "x-category": "Logo",
            "x-is-trigger": False,
            "x-display-name": "Fetch Logo by ISIN",
        },
        title="Fetch Logo by ISIN",
    )
    isin: str = Field(
        ..., title="ISIN", description="ISIN code, e.g. US6541061031"
    )
    logo_type: str = Field(
        "logo",
        title="Logo Type",
        description="Which asset variant to return",
        json_schema_extra=_LOGO_TYPE_EXTRA,
    )


class BrandfetchThemedLogoConfig(BaseModel):
    """Build a transformed Logo CDN URL with theme, size, format, and fallback options."""

    operation: Literal["logo_themed"] = Field(
        "logo_themed",
        json_schema_extra={
            "const": "logo_themed",
            "ui:hidden": True,
            "x-category": "Logo",
            "x-is-trigger": False,
            "x-display-name": "Fetch Themed/Sized Logo",
        },
        title="Fetch Themed/Sized Logo",
    )
    domain: str = Field(
        ..., title="Domain", description="Domain to fetch the logo for, e.g. nike.com"
    )
    logo_type: str = Field(
        "logo",
        title="Logo Type",
        description="Which asset variant to return",
        json_schema_extra=_LOGO_TYPE_EXTRA,
    )
    theme: Optional[str] = Field(
        None,
        title="Theme",
        description="Color theme for the logo",
        json_schema_extra={
            "enum": ["", "light", "dark"],
            "enumNames": ["Default", "Light", "Dark"],
            "x-enum-searchable": True,
        },
    )
    width: Optional[str] = Field(
        None, title="Width", description="Target width in pixels"
    )
    height: Optional[str] = Field(
        None, title="Height", description="Target height in pixels"
    )
    image_format: Optional[str] = Field(
        None,
        title="Format",
        description="Output image format",
        json_schema_extra={
            "enum": ["", "webp", "png", "jpg", "svg"],
            "enumNames": ["Default", "WebP", "PNG", "JPG", "SVG"],
            "x-enum-searchable": True,
        },
    )
    fallback: Optional[str] = Field(
        None,
        title="Fallback",
        description="Fallback rendering when no logo exists, e.g. lettermark",
    )


# ============================================================================
# Webhook Trigger Config
# ============================================================================


class BrandfetchReceiveWebhookConfig(BaseModel):
    """Receive brand-change events from Brandfetch (brand.updated, brand.company.updated).

    Brandfetch webhooks are Enterprise-plan only and registered from the
    Brandfetch dashboard (no self-serve subscription API), so this trigger
    simply provisions an inbound URL the user pastes into their dashboard.
    """

    model_config = ConfigDict(json_schema_extra={"x-requires-webhook": True})

    operation: Literal["receive_webhook"] = Field(
        "receive_webhook",
        json_schema_extra={
            "const": "receive_webhook",
            "ui:hidden": True,
            "x-category": None,
            "x-is-trigger": True,
            "x-display-name": "Receive Brand Change Events",
        },
        title="Receive Brand Change Events",
    )
    event_type: str = Field(
        BRANDFETCH_WEBHOOK_EVENT_ALL,
        title="Event Type",
        description=(
            "Which Brandfetch event fires this workflow. Brandfetch delivers all "
            "events to one endpoint, so the trigger filters inbound deliveries by "
            "their `type` and skips events you did not select. Options: "
            "'All brand events' (any event); 'brand.updated' (a brand's data "
            "changed); 'brand.company.updated' (a brand's company/firmographic "
            "data changed); 'brand.claimed' (a brand was claimed by its owner); "
            "'brand.verified' (a brand was human-reviewed by Brandfetch); "
            "'brand.deleted' (a brand was soft-deleted, rare)."
        ),
        json_schema_extra={
            "enum": BRANDFETCH_WEBHOOK_EVENTS,
            "enumNames": BRANDFETCH_WEBHOOK_EVENT_NAMES,
            "x-enum-searchable": True,
        },
    )
    webhook_url: Optional[str] = Field(
        default=None,
        title="Webhook URL",
        description="Add this URL as a webhook endpoint in your Brandfetch dashboard (Enterprise plan)",
        json_schema_extra={
            "ui:widget": "webhook",
            "ui:copyable": True,
            "ui:loadValue": True,
        },
    )
    webhook_secret: Optional[str] = Field(
        default=None,
        title="Webhook Secret",
        description=(
            "Svix signing secret from your Brandfetch webhook dashboard — starts with "
            "whsec_. Used to verify inbound delivery signatures. Leave blank to skip "
            "verification (not recommended for production)."
        ),
        json_schema_extra={"ui:widget": "password", "ui:placeholder": "whsec_..."},
    )
    webhook_id: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})
    relay_connected: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})
    is_production: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})


# ============================================================================
# Discriminated Union
# ============================================================================


BrandfetchConfig = Annotated[
    Union[
        BrandfetchGetBrandByDomainConfig,
        BrandfetchGetBrandByTickerConfig,
        BrandfetchGetBrandByIsinConfig,
        BrandfetchGetBrandByCryptoConfig,
        BrandfetchGetBrandConfig,
        BrandfetchGetContextJsonConfig,
        BrandfetchGetContextMarkdownConfig,
        BrandfetchSearchConfig,
        BrandfetchTransactionConfig,
        BrandfetchLogoByDomainConfig,
        BrandfetchLogoByTickerConfig,
        BrandfetchLogoByCryptoConfig,
        BrandfetchLogoByIsinConfig,
        BrandfetchThemedLogoConfig,
        BrandfetchReceiveWebhookConfig,
    ],
    Discriminator("operation"),
]


class BrandfetchNodeConfig(NodeConfig[BrandfetchConfig, BrandfetchCredential]):
    """Full configuration for the Brandfetch node including credentials."""

    pass


# ============================================================================
# HTTP Request Helper
# ============================================================================


async def _brandfetch_request(
    method: str,
    endpoint: str,
    *,
    api_key: Optional[str] = None,
    client_id: Optional[str] = None,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None,
    accept: str = "application/json",
    action_name: str = "request",
) -> Dict[str, Any]:
    """Make a Brandfetch v2 request and return a structured result.

    Bearer-authed (api_key) for Brand/Context/Transaction; client_id (?c=) for Search.
    """
    url = f"{BRANDFETCH_API_BASE}{endpoint}"
    headers: Dict[str, str] = {"Accept": accept}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    if json_body is not None:
        headers["Content-Type"] = "application/json"

    query: Dict[str, Any] = dict(params or {})
    if client_id:
        query["c"] = client_id
    query = {k: v for k, v in query.items() if v not in (None, "")}
    if json_body is not None:
        json_body = {k: v for k, v in json_body.items() if v is not None}

    start = time.time()
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.request(
                method=method, url=url, headers=headers, params=query or None, json=json_body
            )
            api_ms = round((time.time() - start) * 1000, 2)
            if response.status_code >= 400:
                try:
                    err = response.json()
                    message = (
                        err.get("message")
                        or err.get("error")
                        or err.get("detail")
                        or str(err)
                        if isinstance(err, dict)
                        else str(err)
                    )
                except Exception:
                    message = response.text
                if isinstance(message, str):
                    message = message.encode("ascii", errors="replace").decode("ascii")
                logger.error(f"[BrandfetchNode] API error ({action_name}): {message}")
                return {
                    "status": "error",
                    "action": action_name,
                    "error": message,
                    "status_code": response.status_code,
                    "timing_ms": {"api_request": api_ms},
                }

            if accept == "text/markdown":
                data: Any = {"markdown": response.text}
            else:
                try:
                    data = response.json()
                except Exception:
                    data = {"raw": response.text}
            return {
                "status": "success",
                "action": action_name,
                "data": data,
                "status_code": response.status_code,
                "timing_ms": {"api_request": api_ms},
            }
        except httpx.TimeoutException:
            return {
                "status": "error",
                "action": action_name,
                "error": "Request timed out",
                "status_code": 408,
                "timing_ms": {"api_request": round((time.time() - start) * 1000, 2)},
            }
        except Exception as e:
            msg = str(e).encode("ascii", errors="replace").decode("ascii")
            logger.error(f"[BrandfetchNode] Request failed ({action_name}): {msg}")
            return {
                "status": "error",
                "action": action_name,
                "error": msg,
                "status_code": 500,
                "timing_ms": {"api_request": round((time.time() - start) * 1000, 2)},
            }


def _inbound_event_type(payload: Any) -> Optional[str]:
    """Read the Brandfetch event identifier from an inbound webhook payload.

    Standard Webhooks deliveries carry the event in the top-level ``type``
    field; the ``x-brandfetch-event`` / ``webhook-event`` header is honoured as a
    fallback when the body is opaque.
    """
    if isinstance(payload, dict):
        event = payload.get("type")
        if event:
            return str(event)
        webhook_meta = payload.get("_webhook")
        if isinstance(webhook_meta, dict):
            headers = webhook_meta.get("headers") or {}
            for key, value in headers.items():
                if str(key).lower() in ("x-brandfetch-event", "webhook-event") and value:
                    return str(value)
    return None


def _event_selected(event_type: Optional[str], selected: Optional[str]) -> bool:
    """Whether an inbound *event_type* matches the user-*selected* filter.

    A ``*`` (or empty) selection means "any event". An unknown/missing inbound
    event type is allowed through only when the filter is "any event".
    """
    if not selected or selected == BRANDFETCH_WEBHOOK_EVENT_ALL:
        return True
    return event_type == selected


def _build_logo_url(path: str, client_id: Optional[str]) -> str:
    """Construct a Logo CDN URL. Only ?c= is a query param; all other transform
    params (theme, w, h, format, fallback) are path segments built by the caller."""
    url = f"{BRANDFETCH_CDN_BASE}/{path}"
    if client_id:
        from urllib.parse import urlencode
        url = f"{url}?{urlencode({'c': client_id})}"
    return url


# ============================================================================
# Node Implementation
# ============================================================================


class BrandfetchNode(WorkflowNode):
    """Brandfetch brand intelligence automation node."""

    edit_examples = [
        "Get the full brand record (logos, colors, fonts) for nike.com",
        "Fetch LLM-ready brand context as Markdown for a company's domain",
        "Search brands matching a name for an autocomplete field",
        "Identify the merchant brand behind a bank statement descriptor",
        "Build a themed logo CDN URL for a domain",
    ]

    @classmethod
    def get_config_model(cls):
        return BrandfetchNodeConfig

    @classmethod
    def resolve_trigger_payload(
        cls, payload: Dict[str, Any], config: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Filter inbound Brandfetch deliveries by the selected event type.

        Brandfetch posts every event to one endpoint with no per-subscription
        filter, so the trigger filters by the payload's ``type``. When the event
        is selected, the payload is the node's output. When it is not, return
        ``None`` so ``execute()`` runs and emits a ``skipped`` result instead of
        passing brand data downstream.
        """
        selected = (config or {}).get("event_type") or BRANDFETCH_WEBHOOK_EVENT_ALL
        if _event_selected(_inbound_event_type(payload), selected):
            return payload
        return None

    @classmethod
    def verify_webhook_signature(
        cls, body: bytes, headers: Dict[str, str], config: Dict[str, Any]
    ) -> bool:
        """Verify Brandfetch Svix webhook signature.

        Brandfetch delivers webhooks via Svix. The secret starts with ``whsec_``
        and is base64-decoded before use as the HMAC-SHA256 key. Signatures are
        base64-encoded and space-separated in the ``webhook-signature`` header
        (e.g. ``v1,<base64sig>``). Includes 5-minute replay protection.

        When no ``webhook_secret`` is configured the check is skipped so users
        can trial the trigger without setting up a secret first.
        """
        secret = (config or {}).get("webhook_secret")
        if not secret:
            return True
        return verify_svix(
            body=body,
            webhook_id=headers.get("webhook-id", ""),
            timestamp=headers.get("webhook-timestamp", ""),
            signature_header=headers.get("webhook-signature", ""),
            secret=secret,
        )

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        start_time = time.time()
        config = self.config
        if not config or not isinstance(config, BrandfetchNodeConfig):
            raise ValueError("Valid configuration is required")
        op = config.config

        # Webhook trigger mode — pass through the inbound event payload, skipping
        # deliveries whose event type the user did not select (Brandfetch sends
        # every event to one endpoint, so filtering happens here).
        if isinstance(op, BrandfetchReceiveWebhookConfig):
            event_type = _inbound_event_type(inputs)
            if not _event_selected(event_type, op.event_type):
                return {
                    "status": "skipped",
                    "action": "receive_webhook",
                    "reason": f"Event '{event_type}' is not in the selected event type '{op.event_type}'",
                    "data": {"event_type": event_type, "webhook_url": op.webhook_url},
                    "timing_ms": {"total": round((time.time() - start_time) * 1000, 2)},
                }
            return {
                "status": "success",
                "action": "receive_webhook",
                "event_type": event_type,
                "data": {**inputs, "webhook_url": op.webhook_url},
                "timing_ms": {"total": round((time.time() - start_time) * 1000, 2)},
            }

        credentials = config.credentials
        if not credentials:
            raise ValueError("Credentials are required. Add your Brandfetch API key.")
        api_key = credentials.api_key
        client_id = credentials.client_id

        handlers = {
            "get_brand_by_domain": self._get_brand_by_domain,
            "get_brand_by_ticker": self._get_brand_by_ticker,
            "get_brand_by_isin": self._get_brand_by_isin,
            "get_brand_by_crypto": self._get_brand_by_crypto,
            "get_brand": self._get_brand,
            "get_context_json": self._get_context_json,
            "get_context_markdown": self._get_context_markdown,
            "search_brands": self._search_brands,
            "identify_transaction": self._identify_transaction,
            "logo_by_domain": self._logo_by_domain,
            "logo_by_ticker": self._logo_by_ticker,
            "logo_by_crypto": self._logo_by_crypto,
            "logo_by_isin": self._logo_by_isin,
            "logo_themed": self._logo_themed,
        }
        handler = handlers.get(op.operation)
        if not handler:
            raise ValueError(f"Unknown operation: {op.operation}")

        result = await handler(op, api_key, client_id)
        result["timing_ms"] = {
            **result.get("timing_ms", {}),
            "total": round((time.time() - start_time) * 1000, 2),
        }
        return result

    # ------------------------------------------------------------------
    # Brand handlers (Bearer api_key)
    # ------------------------------------------------------------------
    async def _get_brand_by_domain(
        self, c: BrandfetchGetBrandByDomainConfig, api_key: str, client_id: Optional[str]
    ) -> Dict[str, Any]:
        params = {"allowNsfw": "true"} if c.allow_nsfw == "true" else None
        return await _brandfetch_request(
            "GET", f"/brands/domain/{c.domain}", api_key=api_key, params=params,
            action_name="get_brand_by_domain",
        )

    async def _get_brand_by_ticker(
        self, c: BrandfetchGetBrandByTickerConfig, api_key: str, client_id: Optional[str]
    ) -> Dict[str, Any]:
        return await _brandfetch_request(
            "GET", f"/brands/ticker/{c.ticker}", api_key=api_key,
            action_name="get_brand_by_ticker",
        )

    async def _get_brand_by_isin(
        self, c: BrandfetchGetBrandByIsinConfig, api_key: str, client_id: Optional[str]
    ) -> Dict[str, Any]:
        return await _brandfetch_request(
            "GET", f"/brands/isin/{c.isin}", api_key=api_key,
            action_name="get_brand_by_isin",
        )

    async def _get_brand_by_crypto(
        self, c: BrandfetchGetBrandByCryptoConfig, api_key: str, client_id: Optional[str]
    ) -> Dict[str, Any]:
        return await _brandfetch_request(
            "GET", f"/brands/crypto/{c.symbol}", api_key=api_key,
            action_name="get_brand_by_crypto",
        )

    async def _get_brand(
        self, c: BrandfetchGetBrandConfig, api_key: str, client_id: Optional[str]
    ) -> Dict[str, Any]:
        return await _brandfetch_request(
            "GET", f"/brands/{c.identifier}", api_key=api_key,
            action_name="get_brand",
        )

    async def _get_context_json(
        self, c: BrandfetchGetContextJsonConfig, api_key: str, client_id: Optional[str]
    ) -> Dict[str, Any]:
        return await _brandfetch_request(
            "GET", f"/context/{c.domain}", api_key=api_key, accept="application/json",
            action_name="get_context_json",
        )

    async def _get_context_markdown(
        self, c: BrandfetchGetContextMarkdownConfig, api_key: str, client_id: Optional[str]
    ) -> Dict[str, Any]:
        return await _brandfetch_request(
            "GET", f"/context/{c.domain}", api_key=api_key, accept="text/markdown",
            action_name="get_context_markdown",
        )

    async def _search_brands(
        self, c: BrandfetchSearchConfig, api_key: str, client_id: Optional[str]
    ) -> Dict[str, Any]:
        if not client_id:
            return {
                "status": "error",
                "action": "search_brands",
                "error": "A public Client ID is required for the Search operation. Add it to your Brandfetch credentials.",
                "status_code": 400,
            }
        return await _brandfetch_request(
            "GET", f"/search/{c.name}", client_id=client_id,
            action_name="search_brands",
        )

    async def _identify_transaction(
        self, c: BrandfetchTransactionConfig, api_key: str, client_id: Optional[str]
    ) -> Dict[str, Any]:
        body = {"transactionLabel": c.transaction_label, "countryCode": c.country_code}
        return await _brandfetch_request(
            "POST", "/brands/transaction", api_key=api_key, json_body=body,
            action_name="identify_transaction",
        )

    # ------------------------------------------------------------------
    # Logo CDN handlers (public client_id, URL builders)
    # ------------------------------------------------------------------
    def _require_client_id(self, action_name: str, client_id: Optional[str]) -> Optional[Dict[str, Any]]:
        if not client_id:
            return {
                "status": "error",
                "action": action_name,
                "error": "A public Client ID is required for Logo operations. Add it to your Brandfetch credentials.",
                "status_code": 400,
            }
        return None

    async def _logo_by_domain(
        self, c: BrandfetchLogoByDomainConfig, api_key: str, client_id: Optional[str]
    ) -> Dict[str, Any]:
        err = self._require_client_id("logo_by_domain", client_id)
        if err:
            return err
        url = _build_logo_url(f"{c.domain}/{c.logo_type}", client_id)
        return {"status": "success", "action": "logo_by_domain", "data": {"logo_url": url}}

    async def _logo_by_ticker(
        self, c: BrandfetchLogoByTickerConfig, api_key: str, client_id: Optional[str]
    ) -> Dict[str, Any]:
        err = self._require_client_id("logo_by_ticker", client_id)
        if err:
            return err
        url = _build_logo_url(f"ticker/{c.ticker}/{c.logo_type}", client_id)
        return {"status": "success", "action": "logo_by_ticker", "data": {"logo_url": url}}

    async def _logo_by_crypto(
        self, c: BrandfetchLogoByCryptoConfig, api_key: str, client_id: Optional[str]
    ) -> Dict[str, Any]:
        err = self._require_client_id("logo_by_crypto", client_id)
        if err:
            return err
        url = _build_logo_url(f"crypto/{c.symbol}/{c.logo_type}", client_id)
        return {"status": "success", "action": "logo_by_crypto", "data": {"logo_url": url}}

    async def _logo_by_isin(
        self, c: BrandfetchLogoByIsinConfig, api_key: str, client_id: Optional[str]
    ) -> Dict[str, Any]:
        err = self._require_client_id("logo_by_isin", client_id)
        if err:
            return err
        url = _build_logo_url(f"isin/{c.isin}/{c.logo_type}", client_id)
        return {"status": "success", "action": "logo_by_isin", "data": {"logo_url": url}}

    async def _logo_themed(
        self, c: BrandfetchThemedLogoConfig, api_key: str, client_id: Optional[str]
    ) -> Dict[str, Any]:
        err = self._require_client_id("logo_themed", client_id)
        if err:
            return err
        # CDN uses path segments for all transform params; only ?c= is a query param.
        # Format: /{domain}/[w/{w}/][h/{h}/][theme/{theme}/][fallback/{fallback}/]{type}[.{ext}]
        parts = [c.domain]
        if c.width:
            parts.append(f"w/{c.width}")
        if c.height:
            parts.append(f"h/{c.height}")
        if c.theme:
            parts.append(f"theme/{c.theme}")
        if c.fallback:
            parts.append(f"fallback/{c.fallback}")
        logo_segment = f"{c.logo_type}.{c.image_format}" if c.image_format else c.logo_type
        parts.append(logo_segment)
        url = _build_logo_url("/".join(parts), client_id)
        return {"status": "success", "action": "logo_themed", "data": {"logo_url": url}}
