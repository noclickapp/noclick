"""
Meta (Marketing / Ads / Business) automation node.

Covers the cross-cutting Meta business surface that isn't tied to a single
product node (Facebook Pages, Instagram, WhatsApp, Threads have their own):
the **Marketing / Ads API**, **Conversions API (CAPI)**, **Business
Management**, **Product Catalogs**, and **Lead Ads** (retrieval + webhook
triggers).

Coverage (built in phases):
- Core ad objects: Ad Account, Campaign, Ad Set, Ad, Ad Creative, Ad Image,
  Ad Video — full CRUD + copy + preview + insights (ODAX objectives).
- Audiences + targeting: Custom / Lookalike / Saved audiences, targeting
  search/browse/validate, reach + delivery estimates.
- Insights / reporting: sync + async report runs.
- Conversions API: server/offline/test events, pixel/dataset management.
- Business Management: businesses, system users, asset assignment, catalogs.
- Lead Ads: lead gen forms, lead retrieval, test leads, leadgen webhook trigger.

Authentication: Facebook Login OAuth (meta_oauth — a user token with ads +
business scopes) or a manually supplied user / Business-Manager **System User**
token (meta_access_token), with optional appsecret_proof.

API Base URL: https://graph.facebook.com/v25.0
Docs: https://developers.facebook.com/docs/marketing-api
"""

import hashlib
import hmac
import json
import logging
import os
import time
from typing import Annotated, Any, Dict, List, Literal, Optional, Union

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field, create_model
from starlette.responses import PlainTextResponse

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.oauth.meta_oauth import is_token_expired, refresh_access_token
from nodes.scopes.meta import META_SCOPES

logger = logging.getLogger(__name__)

GRAPH_API_VERSION = "v25.0"
META_API_BASE = f"https://graph.facebook.com/{GRAPH_API_VERSION}"

META_OAUTH_SCOPES = [
    "public_profile",
    "ads_management",
    "ads_read",
    "business_management",
    "leads_retrieval",
    "pages_show_list",
    "pages_read_engagement",
    # Required by subscribe_page_webhooks (POST /{page_id}/subscribed_apps) so
    # the on_leadgen trigger can be armed programmatically.
    "pages_manage_metadata",
    "catalog_management",
]


# ============================================================================
# Credentials
# ============================================================================


class MetaOAuthCredential(BaseModel):
    """Meta Login OAuth token (user token with ads + business scopes)."""

    credential_type: Literal["meta_oauth"] = Field(
        "meta_oauth", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(
        ..., title="Access Token", description="Long-lived Meta user access token",
        json_schema_extra={"ui:widget": "password"},
    )
    expires_at: Optional[str] = Field(None, title="Token Expiry", description="ISO 8601 expiry of the long-lived token")
    email: Optional[str] = Field(None, title="Account Email", description="Connected Meta account email")
    facebook_user_id: Optional[str] = Field(None, title="Meta User ID", description="Connected Meta user ID")

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-url": "https://developers.facebook.com/apps/",
            "x-credential-type": "oauth",
            "x-oauth-provider": "meta",
            # Hidden until Meta approves the ads/business scopes — existing OAuth
            # credentials still parse/execute; new connections use the access
            # token (System User) method below. Reveal by removing this flag.
            # PostHog flag reveals it for allow-listed accounts (e.g. Meta reviewers).
            "x-credential-hidden": True,
            "x-credential-preview-flag": "meta-oauth-preview",
            "x-oauth-scopes": META_OAUTH_SCOPES,
        }
    )


class MetaAccessTokenCredential(BaseModel):
    """Manually supplied Meta user or Business-Manager System User token."""

    credential_type: Literal["meta_access_token"] = Field(
        "meta_access_token", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(
        ..., title="Access Token", description="Meta user or System User access token",
        json_schema_extra={"ui:widget": "password"},
    )
    expires_at: Optional[str] = Field(None, title="Token Expiry", description="ISO 8601 expiry, if the token expires")
    app_secret: Optional[str] = Field(
        None, title="App Secret (Optional)",
        description="App secret for appsecret_proof on apps that require secure server requests.",
        json_schema_extra={"ui:widget": "password"},
    )


MetaCredential = Union[MetaOAuthCredential, MetaAccessTokenCredential]


# ============================================================================
# Request helper
# ============================================================================


def _appsecret_proof(access_token: str, app_secret: str) -> str:
    return hmac.new(app_secret.encode("utf-8"), access_token.encode("utf-8"), hashlib.sha256).hexdigest()


def _acct(ad_account_id: str) -> str:
    """Normalize an ad account id to the act_{id} form the Graph API expects."""
    s = str(ad_account_id).strip()
    return s if s.startswith("act_") else f"act_{s}"


def _parse_json_field(raw: Optional[str], label: str) -> Any:
    if raw is None or raw == "":
        return None
    if not isinstance(raw, str):
        return raw
    try:
        return json.loads(raw)
    except Exception as e:
        raise ValueError(f"{label} must be valid JSON: {e}")


def _ascii(s: Any) -> str:
    return str(s).encode("ascii", errors="replace").decode("ascii")


def _extract_meta_error(response: httpx.Response) -> tuple[str, Optional[Dict[str, Any]]]:
    """Pull the most actionable message + structured detail out of a Graph API
    error. Meta buries the real reason in ``error_user_title``/``error_user_msg``
    (and the offending field in ``error_data``); the top-level ``message`` is
    often a useless generic like "Invalid parameter". Prefer the user message,
    keep the technical one, and return the structured fields for callers."""
    try:
        body = response.json()
    except Exception:
        return _ascii(response.text), None
    eo = body.get("error") if isinstance(body, dict) else None
    if not isinstance(eo, dict):
        msg = body.get("message") if isinstance(body, dict) else body
        return _ascii(msg if msg is not None else body), None
    technical = eo.get("message") or ""
    user_title = eo.get("error_user_title")
    user_msg = eo.get("error_user_msg")
    if user_msg:
        message = f"{technical} — {user_title}: {user_msg}" if user_title else f"{technical} — {user_msg}"
    else:
        message = technical or str(eo)
    details = {k: eo.get(k) for k in
               ("code", "error_subcode", "type", "fbtrace_id",
                "error_user_title", "error_user_msg", "error_data")
               if eo.get(k) is not None}
    return _ascii(message), (details or None)


async def _meta_request(
    access_token: str,
    method: str,
    endpoint: str,
    params: Optional[Dict[str, Any]] = None,
    data: Optional[Dict[str, Any]] = None,
    app_secret: Optional[str] = None,
    action_name: str = "request",
) -> Dict[str, Any]:
    """Authenticated Graph/Marketing API request → structured result. Reads use
    query params; writes use form-encoded data (arrays/objects JSON-encoded by
    the caller). Bearer token auth + optional appsecret_proof on every call."""
    url = f"{META_API_BASE}{endpoint}"
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {k: v for k, v in (params or {}).items() if v not in (None, "")}
    if app_secret:
        proof = _appsecret_proof(access_token, app_secret)
        params["appsecret_proof"] = proof
        if data is not None:
            data = {**data, "appsecret_proof": proof}
    if not params:
        params = None
    if data:
        data = {k: v for k, v in data.items() if v not in (None, "")}

    start = time.time()
    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            response = await client.request(method=method, url=url, headers=headers, params=params, data=data)
            api_ms = round((time.time() - start) * 1000, 2)
            if response.status_code >= 400:
                message, details = _extract_meta_error(response)
                logger.error(f"[MetaNode] API error ({action_name}): {message}")
                result = {"status": "error", "action": action_name, "error": message,
                          "status_code": response.status_code, "timing_ms": {"api_request": api_ms}}
                if details:
                    result["error_details"] = details
                return result
            payload: Any = {"success": True} if response.status_code == 204 else (
                response.json() if response.content else {"success": True})
            return {"status": "success", "action": action_name, "data": payload,
                    "status_code": response.status_code, "timing_ms": {"api_request": api_ms}}
        except httpx.TimeoutException:
            return {"status": "error", "action": action_name, "error": "Request timed out",
                    "status_code": 408, "timing_ms": {"api_request": round((time.time() - start) * 1000, 2)}}
        except Exception as e:
            msg = str(e).encode("ascii", errors="replace").decode("ascii")
            logger.error(f"[MetaNode] Request failed ({action_name}): {msg}")
            return {"status": "error", "action": action_name, "error": msg,
                    "status_code": 500, "timing_ms": {"api_request": round((time.time() - start) * 1000, 2)}}


async def _resolve_page_token(user_token: str, page_id: str, app_secret: Optional[str]):
    """Resolve a Page access token for a page-scoped call. Some Page edges
    (e.g. GET /{page}/leadgen_forms) reject the user token with (#190) and
    require the Page's OWN token. Returns (page_token, error_result_or_None)."""
    r = await _meta_request(user_token, "GET", f"/{page_id}", params={"fields": "access_token"},
                            app_secret=app_secret, action_name="resolve_page_token")
    if r.get("status") != "success":
        return None, r
    token = (r.get("data") or {}).get("access_token")
    if not token:
        return None, {"status": "error", "action": "resolve_page_token", "status_code": 403,
                      "error": "No Page access token available for this Page. The connected account "
                               "must manage the Page (pages_show_list + pages_manage_ads)."}
    return token, None


# ============================================================================
# Operation registry
# ============================================================================

OPERATION_CONFIGS: List[type] = []
OPERATION_HANDLERS: Dict[str, Any] = {}

# Dynamic-options spec for ad-account fields (backed by /me/adaccounts).
_ACCOUNT_DYNAMIC = {
    "x-dynamic-options": {
        "field_name": "ad_account_id",
        "placeholder": "Select an ad account...",
        "searchable": True,
        "allow_custom": True,
        "custom_placeholder": "Or paste an ad account ID (act_...)",
    }
}


def _reg(cfg, op=None, handler=None) -> None:
    # Op name is derived from the config's operation default, so this accepts both
    # _reg(cfg, "op", handler) and the factory splat _reg(*_make_x(...)) → _reg(cfg, handler).
    if handler is None:
        handler = op
    op_name = cfg.model_fields["operation"].default
    OPERATION_CONFIGS.append(cfg)
    OPERATION_HANDLERS[op_name] = handler


def _op_extra(op: str, display: str, category: str) -> dict:
    return {"const": op, "x-category": category,
            "x-is-trigger": False, "x-display-name": display}


# ---------------------------------------------------------------------------
# Ad Account
# ---------------------------------------------------------------------------

class MetaListAdAccountsConfig(BaseModel):
    """List the ad accounts the token can access (/me/adaccounts)."""
    operation: Literal["list_ad_accounts"] = Field("list_ad_accounts",
        json_schema_extra=_op_extra("list_ad_accounts", "List Ad Accounts", "Ad Account"), title="List Ad Accounts")
    fields: str = Field("id,name,account_status,currency,timezone_name,amount_spent,spend_cap,balance",
                        title="Fields", description="Comma-separated account fields.")
    limit: Optional[str] = Field("100", title="Limit", description="Max accounts per page.")


async def _list_ad_accounts(c, token, secret):
    return await _meta_request(token, "GET", "/me/adaccounts", params={"fields": c.fields, "limit": c.limit},
                               app_secret=secret, action_name="list_ad_accounts")


class MetaGetAdAccountConfig(BaseModel):
    """Read an ad account, including spend / funding / limits."""
    operation: Literal["get_ad_account"] = Field("get_ad_account",
        json_schema_extra=_op_extra("get_ad_account", "Get Ad Account", "Ad Account"), title="Get Ad Account")
    ad_account_id: str = Field(..., title="Ad Account", description="Ad account ID (act_...).", json_schema_extra=_ACCOUNT_DYNAMIC)
    fields: str = Field("name,account_status,currency,timezone_name,funding_source_details,spend_cap,amount_spent,balance,min_daily_budget",
                        title="Fields", description="Comma-separated account fields.")


async def _get_ad_account(c, token, secret):
    return await _meta_request(token, "GET", f"/{_acct(c.ad_account_id)}", params={"fields": c.fields},
                               app_secret=secret, action_name="get_ad_account")


class MetaUpdateAdAccountConfig(BaseModel):
    """Update ad account settings (name, spend cap, ...)."""
    operation: Literal["update_ad_account"] = Field("update_ad_account",
        json_schema_extra=_op_extra("update_ad_account", "Update Ad Account", "Ad Account"), title="Update Ad Account")
    ad_account_id: str = Field(..., title="Ad Account", description="Ad account ID (act_...).", json_schema_extra=_ACCOUNT_DYNAMIC)
    fields_json: str = Field("{}", title="Fields (JSON)",
                             description='Fields to update, e.g. {"name":"...","spend_cap":50000}.',
                             json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})


async def _update_ad_account(c, token, secret):
    data = {k: (json.dumps(v) if isinstance(v, (dict, list)) else v)
            for k, v in (_parse_json_field(c.fields_json, "Fields") or {}).items()}
    return await _meta_request(token, "POST", f"/{_acct(c.ad_account_id)}", data=data,
                               app_secret=secret, action_name="update_ad_account")


_reg(MetaListAdAccountsConfig, "list_ad_accounts", _list_ad_accounts)
_reg(MetaGetAdAccountConfig, "get_ad_account", _get_ad_account)
_reg(MetaUpdateAdAccountConfig, "update_ad_account", _update_ad_account)


# ---------------------------------------------------------------------------
# Factories for the repetitive object patterns (get / delete / account-list)
# ---------------------------------------------------------------------------

def _make_object_get(op: str, display: str, id_title: str, default_fields: str, category: str):
    """GET /{object_id} with a selectable field set."""
    from pydantic import create_model
    cfg = create_model(
        f"Meta_{op}_Config", __base__=BaseModel,
        operation=(Literal[op], Field(op, json_schema_extra=_op_extra(op, display, category), title=display)),
        object_id=(str, Field(..., title=id_title, description=f"The {id_title}.")),
        fields=(str, Field(default_fields, title="Fields", description="Comma-separated fields.")),
    )

    async def handler(c, token, secret):
        return await _meta_request(token, "GET", f"/{c.object_id}", params={"fields": c.fields},
                                   app_secret=secret, action_name=op)

    return cfg, handler


def _make_object_delete(op: str, display: str, id_title: str, category: str):
    """DELETE /{object_id} (soft delete → status DELETED)."""
    from pydantic import create_model
    cfg = create_model(
        f"Meta_{op}_Config", __base__=BaseModel,
        operation=(Literal[op], Field(op, json_schema_extra=_op_extra(op, display, category), title=display)),
        object_id=(str, Field(..., title=id_title, description=f"The {id_title}.")),
    )

    async def handler(c, token, secret):
        return await _meta_request(token, "DELETE", f"/{c.object_id}", app_secret=secret, action_name=op)

    return cfg, handler


def _make_account_list(op: str, display: str, edge: str, default_fields: str, category: str, with_status: bool = True):
    """GET /act_{id}/{edge} — list child objects under an ad account."""
    from pydantic import create_model
    fields_def = {
        "operation": (Literal[op], Field(op, json_schema_extra=_op_extra(op, display, category), title=display)),
        "ad_account_id": (str, Field(..., title="Ad Account", description="Ad account ID (act_...).", json_schema_extra=_ACCOUNT_DYNAMIC)),
        "fields": (str, Field(default_fields, title="Fields", description="Comma-separated fields.")),
        "limit": (Optional[str], Field("100", title="Limit", description="Max items per page.")),
        "filtering_json": (Optional[str], Field(None, title="Filtering (JSON)",
                           description='Optional [{"field","operator","value"}] filter.',
                           json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})),
    }
    if with_status:
        fields_def["effective_status_json"] = (Optional[str], Field(None, title="Effective Status (JSON)",
            description='Optional ["ACTIVE","PAUSED",...] filter.',
            json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"}))
    cfg = create_model(f"Meta_{op}_Config", __base__=BaseModel, **fields_def)

    async def handler(c, token, secret):
        params = {"fields": c.fields, "limit": c.limit}
        filt = _parse_json_field(c.filtering_json, "Filtering")
        if filt is not None:
            params["filtering"] = json.dumps(filt)
        if with_status:
            es = _parse_json_field(getattr(c, "effective_status_json", None), "Effective Status")
            if es is not None:
                params["effective_status"] = json.dumps(es)
        return await _meta_request(token, "GET", f"/{_acct(c.ad_account_id)}/{edge}", params=params,
                                   app_secret=secret, action_name=op)

    return cfg, handler


# ---------------------------------------------------------------------------
# Campaign
# ---------------------------------------------------------------------------

_OBJECTIVES = ["OUTCOME_TRAFFIC", "OUTCOME_SALES", "OUTCOME_LEADS", "OUTCOME_ENGAGEMENT",
               "OUTCOME_AWARENESS", "OUTCOME_APP_PROMOTION"]


class MetaCreateCampaignConfig(BaseModel):
    """Create an ad campaign (ODAX objective)."""
    operation: Literal["create_campaign"] = Field("create_campaign",
        json_schema_extra=_op_extra("create_campaign", "Create Campaign", "Campaign"), title="Create Campaign")
    ad_account_id: str = Field(..., title="Ad Account", description="Ad account ID (act_...).", json_schema_extra=_ACCOUNT_DYNAMIC)
    name: str = Field(..., title="Name", description="Campaign name.")
    objective: str = Field("OUTCOME_TRAFFIC", title="Objective",
                           json_schema_extra={"enum": _OBJECTIVES, "x-enum-searchable": True},
                           description="ODAX campaign objective.")
    status: str = Field("PAUSED", title="Status", json_schema_extra={"enum": ["ACTIVE", "PAUSED"], "x-enum-searchable": True},
                        description="Initial status.")
    special_ad_categories_json: str = Field('[]', title="Special Ad Categories (JSON)",
        description='Required. e.g. [] or ["HOUSING","CREDIT","EMPLOYMENT",...].',
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})
    is_adset_budget_sharing_enabled: str = Field("false", title="Ad Set Budget Sharing",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True},
        description="Required by Meta when the campaign has no campaign-level budget: allow ad sets to share 20% of budget.")
    fields_json: str = Field("{}", title="Additional Fields (JSON)",
        description='Optional extra fields (daily_budget, lifetime_budget, bid_strategy, buying_type, ...).',
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})


async def _create_campaign(c, token, secret):
    data = {"name": c.name, "objective": c.objective, "status": c.status,
            "is_adset_budget_sharing_enabled": c.is_adset_budget_sharing_enabled,
            "special_ad_categories": json.dumps(_parse_json_field(c.special_ad_categories_json, "Special Ad Categories") or [])}
    for k, v in (_parse_json_field(c.fields_json, "Additional Fields") or {}).items():
        data[k] = json.dumps(v) if isinstance(v, (dict, list)) else v
    return await _meta_request(token, "POST", f"/{_acct(c.ad_account_id)}/campaigns", data=data,
                               app_secret=secret, action_name="create_campaign")


class MetaUpdateCampaignConfig(BaseModel):
    """Update a campaign (fields incl. status, budget, name)."""
    operation: Literal["update_campaign"] = Field("update_campaign",
        json_schema_extra=_op_extra("update_campaign", "Update Campaign", "Campaign"), title="Update Campaign")
    campaign_id: str = Field(..., title="Campaign ID", description="The campaign ID.")
    fields_json: str = Field("{}", title="Fields (JSON)",
        description='Fields to update, e.g. {"status":"ACTIVE","daily_budget":5000}.',
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})


async def _update_campaign(c, token, secret):
    data = {k: (json.dumps(v) if isinstance(v, (dict, list)) else v)
            for k, v in (_parse_json_field(c.fields_json, "Fields") or {}).items()}
    return await _meta_request(token, "POST", f"/{c.campaign_id}", data=data,
                               app_secret=secret, action_name="update_campaign")


_c, _h = _make_account_list("list_campaigns", "List Campaigns", "campaigns",
                            "id,name,objective,status,effective_status,daily_budget,lifetime_budget,buying_type,created_time", "Campaign")
_reg(_c, "list_campaigns", _h)
_c, _h = _make_object_get("get_campaign", "Get Campaign", "Campaign ID",
                          "name,objective,status,effective_status,daily_budget,lifetime_budget,bid_strategy,buying_type,created_time", "Campaign")
_reg(_c, "get_campaign", _h)
_reg(MetaCreateCampaignConfig, "create_campaign", _create_campaign)
_reg(MetaUpdateCampaignConfig, "update_campaign", _update_campaign)
_c, _h = _make_object_delete("delete_campaign", "Delete Campaign", "Campaign ID", "Campaign")
_reg(_c, "delete_campaign", _h)


# ---------------------------------------------------------------------------
# Ad Set
# ---------------------------------------------------------------------------

class MetaCreateAdSetConfig(BaseModel):
    """Create an ad set (targeting + budget + optimization)."""
    operation: Literal["create_adset"] = Field("create_adset",
        json_schema_extra=_op_extra("create_adset", "Create Ad Set", "Ad Set"), title="Create Ad Set")
    ad_account_id: str = Field(..., title="Ad Account", description="Ad account ID (act_...).", json_schema_extra=_ACCOUNT_DYNAMIC)
    name: str = Field(..., title="Name", description="Ad set name.")
    campaign_id: str = Field(..., title="Campaign ID", description="Parent campaign ID.")
    optimization_goal: str = Field(..., title="Optimization Goal", description="e.g. LINK_CLICKS, OFFSITE_CONVERSIONS, REACH.")
    billing_event: str = Field("IMPRESSIONS", title="Billing Event", description="e.g. IMPRESSIONS, LINK_CLICKS.")
    targeting_json: str = Field(..., title="Targeting (JSON)",
        description='Targeting spec, must include geo_locations, e.g. {"geo_locations":{"countries":["US"]}}.',
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})
    status: str = Field("PAUSED", title="Status", json_schema_extra={"enum": ["ACTIVE", "PAUSED"], "x-enum-searchable": True})
    fields_json: str = Field("{}", title="Additional Fields (JSON)",
        description='Extra fields (daily_budget, lifetime_budget, bid_amount, bid_strategy, start_time, end_time, promoted_object, ...).',
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})


async def _create_adset(c, token, secret):
    data = {"name": c.name, "campaign_id": c.campaign_id, "optimization_goal": c.optimization_goal,
            "billing_event": c.billing_event, "status": c.status,
            "targeting": json.dumps(_parse_json_field(c.targeting_json, "Targeting") or {})}
    for k, v in (_parse_json_field(c.fields_json, "Additional Fields") or {}).items():
        data[k] = json.dumps(v) if isinstance(v, (dict, list)) else v
    return await _meta_request(token, "POST", f"/{_acct(c.ad_account_id)}/adsets", data=data,
                               app_secret=secret, action_name="create_adset")


class MetaUpdateAdSetConfig(BaseModel):
    """Update an ad set."""
    operation: Literal["update_adset"] = Field("update_adset",
        json_schema_extra=_op_extra("update_adset", "Update Ad Set", "Ad Set"), title="Update Ad Set")
    adset_id: str = Field(..., title="Ad Set ID", description="The ad set ID.")
    fields_json: str = Field("{}", title="Fields (JSON)",
        description='Fields to update, e.g. {"status":"ACTIVE","daily_budget":3000,"targeting":{...}}.',
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})


async def _update_adset(c, token, secret):
    data = {k: (json.dumps(v) if isinstance(v, (dict, list)) else v)
            for k, v in (_parse_json_field(c.fields_json, "Fields") or {}).items()}
    return await _meta_request(token, "POST", f"/{c.adset_id}", data=data,
                               app_secret=secret, action_name="update_adset")


_c, _h = _make_account_list("list_adsets", "List Ad Sets", "adsets",
                            "id,name,campaign_id,optimization_goal,billing_event,status,effective_status,daily_budget,lifetime_budget", "Ad Set")
_reg(_c, "list_adsets", _h)
_c, _h = _make_object_get("get_adset", "Get Ad Set", "Ad Set ID",
                          "name,campaign_id,optimization_goal,billing_event,bid_amount,daily_budget,lifetime_budget,targeting,status,effective_status,start_time,end_time,promoted_object", "Ad Set")
_reg(_c, "get_adset", _h)
_reg(MetaCreateAdSetConfig, "create_adset", _create_adset)
_reg(MetaUpdateAdSetConfig, "update_adset", _update_adset)
_c, _h = _make_object_delete("delete_adset", "Delete Ad Set", "Ad Set ID", "Ad Set")
_reg(_c, "delete_adset", _h)


# ---------------------------------------------------------------------------
# Ad
# ---------------------------------------------------------------------------

class MetaCreateAdConfig(BaseModel):
    """Create an ad (links an ad set to a creative; enters review)."""
    operation: Literal["create_ad"] = Field("create_ad",
        json_schema_extra=_op_extra("create_ad", "Create Ad", "Ad"), title="Create Ad")
    ad_account_id: str = Field(..., title="Ad Account", description="Ad account ID (act_...).", json_schema_extra=_ACCOUNT_DYNAMIC)
    name: str = Field(..., title="Name", description="Ad name.")
    adset_id: str = Field(..., title="Ad Set ID", description="Parent ad set ID.")
    creative_json: str = Field(..., title="Creative (JSON)",
        description='Creative reference, e.g. {"creative_id":"123"} or an inline spec.',
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})
    status: str = Field("PAUSED", title="Status", json_schema_extra={"enum": ["ACTIVE", "PAUSED"], "x-enum-searchable": True})
    fields_json: str = Field("{}", title="Additional Fields (JSON)",
        description='Extra fields (tracking_specs, conversion_domain, ...).',
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})


async def _create_ad(c, token, secret):
    data = {"name": c.name, "adset_id": c.adset_id, "status": c.status,
            "creative": json.dumps(_parse_json_field(c.creative_json, "Creative") or {})}
    for k, v in (_parse_json_field(c.fields_json, "Additional Fields") or {}).items():
        data[k] = json.dumps(v) if isinstance(v, (dict, list)) else v
    return await _meta_request(token, "POST", f"/{_acct(c.ad_account_id)}/ads", data=data,
                               app_secret=secret, action_name="create_ad")


class MetaUpdateAdConfig(BaseModel):
    """Update an ad."""
    operation: Literal["update_ad"] = Field("update_ad",
        json_schema_extra=_op_extra("update_ad", "Update Ad", "Ad"), title="Update Ad")
    ad_id: str = Field(..., title="Ad ID", description="The ad ID.")
    fields_json: str = Field("{}", title="Fields (JSON)",
        description='Fields to update, e.g. {"status":"ACTIVE","name":"..."}.',
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})


async def _update_ad(c, token, secret):
    data = {k: (json.dumps(v) if isinstance(v, (dict, list)) else v)
            for k, v in (_parse_json_field(c.fields_json, "Fields") or {}).items()}
    return await _meta_request(token, "POST", f"/{c.ad_id}", data=data, app_secret=secret, action_name="update_ad")


class MetaPreviewAdConfig(BaseModel):
    """Generate a rendered preview for an ad."""
    operation: Literal["preview_ad"] = Field("preview_ad",
        json_schema_extra=_op_extra("preview_ad", "Preview Ad", "Ad"), title="Preview Ad")
    ad_id: str = Field(..., title="Ad ID", description="The ad ID.")
    ad_format: str = Field("DESKTOP_FEED_STANDARD", title="Ad Format",
                           description="e.g. DESKTOP_FEED_STANDARD, MOBILE_FEED_STANDARD, INSTAGRAM_STANDARD.")


async def _preview_ad(c, token, secret):
    return await _meta_request(token, "GET", f"/{c.ad_id}/previews", params={"ad_format": c.ad_format},
                               app_secret=secret, action_name="preview_ad")


_c, _h = _make_account_list("list_ads", "List Ads", "ads",
                            "id,name,adset_id,campaign_id,status,effective_status,created_time", "Ad")
_reg(_c, "list_ads", _h)
_c, _h = _make_object_get("get_ad", "Get Ad", "Ad ID",
                          "name,adset_id,campaign_id,creative,status,effective_status,tracking_specs,created_time,ad_review_feedback", "Ad")
_reg(_c, "get_ad", _h)
_reg(MetaCreateAdConfig, "create_ad", _create_ad)
_reg(MetaUpdateAdConfig, "update_ad", _update_ad)
_reg(MetaPreviewAdConfig, "preview_ad", _preview_ad)
_c, _h = _make_object_delete("delete_ad", "Delete Ad", "Ad ID", "Ad")
_reg(_c, "delete_ad", _h)


# ---------------------------------------------------------------------------
# Ad Creative
# ---------------------------------------------------------------------------

class MetaCreateCreativeConfig(BaseModel):
    """Create an ad creative in the account library."""
    operation: Literal["create_creative"] = Field("create_creative",
        json_schema_extra=_op_extra("create_creative", "Create Ad Creative", "Ad Creative"), title="Create Ad Creative")
    ad_account_id: str = Field(..., title="Ad Account", description="Ad account ID (act_...).", json_schema_extra=_ACCOUNT_DYNAMIC)
    name: str = Field(..., title="Name", description="Creative name.")
    fields_json: str = Field("{}", title="Creative Fields (JSON)",
        description='Creative spec — object_story_spec OR object_story_id, plus optional image_hash, video_id, asset_feed_spec, url_tags.',
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})


async def _create_creative(c, token, secret):
    data = {"name": c.name}
    for k, v in (_parse_json_field(c.fields_json, "Creative Fields") or {}).items():
        data[k] = json.dumps(v) if isinstance(v, (dict, list)) else v
    return await _meta_request(token, "POST", f"/{_acct(c.ad_account_id)}/adcreatives", data=data,
                               app_secret=secret, action_name="create_creative")


class MetaUpdateCreativeConfig(BaseModel):
    """Update a creative (limited mutable fields: name, status, adlabels)."""
    operation: Literal["update_creative"] = Field("update_creative",
        json_schema_extra=_op_extra("update_creative", "Update Ad Creative", "Ad Creative"), title="Update Ad Creative")
    creative_id: str = Field(..., title="Creative ID", description="The creative ID.")
    fields_json: str = Field("{}", title="Fields (JSON)", description='e.g. {"name":"..."}.',
                             json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})


async def _update_creative(c, token, secret):
    data = {k: (json.dumps(v) if isinstance(v, (dict, list)) else v)
            for k, v in (_parse_json_field(c.fields_json, "Fields") or {}).items()}
    return await _meta_request(token, "POST", f"/{c.creative_id}", data=data, app_secret=secret, action_name="update_creative")


_c, _h = _make_account_list("list_creatives", "List Ad Creatives", "adcreatives",
                            "id,name,object_story_id,image_hash,video_id,thumbnail_url,status", "Ad Creative", with_status=False)
_reg(_c, "list_creatives", _h)
_c, _h = _make_object_get("get_creative", "Get Ad Creative", "Creative ID",
                          "name,object_story_spec,object_story_id,image_hash,image_url,video_id,thumbnail_url,body,title,call_to_action_type,status", "Ad Creative")
_reg(_c, "get_creative", _h)
_reg(MetaCreateCreativeConfig, "create_creative", _create_creative)
_reg(MetaUpdateCreativeConfig, "update_creative", _update_creative)
_c, _h = _make_object_delete("delete_creative", "Delete Ad Creative", "Creative ID", "Ad Creative")
_reg(_c, "delete_creative", _h)


# ---------------------------------------------------------------------------
# Ad Image & Ad Video
# ---------------------------------------------------------------------------

class MetaUploadImageConfig(BaseModel):
    """Upload an image to the ad account (by URL). Returns a hash for creatives."""
    operation: Literal["upload_image"] = Field("upload_image",
        json_schema_extra=_op_extra("upload_image", "Upload Ad Image", "Media"), title="Upload Ad Image")
    ad_account_id: str = Field(..., title="Ad Account", description="Ad account ID (act_...).", json_schema_extra=_ACCOUNT_DYNAMIC)
    url: str = Field(..., title="Image URL", description="Publicly reachable image URL.")


async def _upload_image(c, token, secret):
    return await _meta_request(token, "POST", f"/{_acct(c.ad_account_id)}/adimages", data={"url": c.url},
                               app_secret=secret, action_name="upload_image")


class MetaUploadVideoConfig(BaseModel):
    """Upload a video to the ad account (by hosted URL)."""
    operation: Literal["upload_video"] = Field("upload_video",
        json_schema_extra=_op_extra("upload_video", "Upload Ad Video", "Media"), title="Upload Ad Video")
    ad_account_id: str = Field(..., title="Ad Account", description="Ad account ID (act_...).", json_schema_extra=_ACCOUNT_DYNAMIC)
    file_url: str = Field(..., title="Video URL", description="Publicly reachable video URL.")
    title: Optional[str] = Field(None, title="Title", description="Video title.")
    description: Optional[str] = Field(None, title="Description", description="Video description.")


async def _upload_video(c, token, secret):
    return await _meta_request(token, "POST", f"/{_acct(c.ad_account_id)}/advideos",
                               data={"file_url": c.file_url, "title": c.title, "description": c.description},
                               app_secret=secret, action_name="upload_video")


_reg(MetaUploadImageConfig, "upload_image", _upload_image)
_c, _h = _make_account_list("list_images", "List Ad Images", "adimages",
                            "hash,name,url,permalink_url,width,height,status", "Media", with_status=False)
_reg(_c, "list_images", _h)
_reg(MetaUploadVideoConfig, "upload_video", _upload_video)
_c, _h = _make_account_list("list_videos", "List Ad Videos", "advideos",
                            "id,title,description,created_time,length,thumbnails", "Media", with_status=False)
_reg(_c, "list_videos", _h)
_c, _h = _make_object_get("get_video", "Get Ad Video", "Video ID", "id,title,description,status,length,created_time", "Media")
_reg(_c, "get_video", _h)
_c, _h = _make_object_delete("delete_video", "Delete Ad Video", "Video ID", "Media")
_reg(_c, "delete_video", _h)


# ---------------------------------------------------------------------------
# Insights (sync — works on account / campaign / adset / ad ids)
# ---------------------------------------------------------------------------

class MetaGetInsightsConfig(BaseModel):
    """Read performance insights for any ad object (account/campaign/adset/ad)."""
    operation: Literal["get_insights"] = Field("get_insights",
        json_schema_extra=_op_extra("get_insights", "Get Insights", "Insights"), title="Get Insights")
    object_id: str = Field(..., title="Object ID", description="act_{id} / campaign / adset / ad id.")
    level: Optional[str] = Field(None, title="Level",
                                 json_schema_extra={"enum": ["account", "campaign", "adset", "ad"], "x-enum-searchable": True},
                                 description="Aggregation level.")
    fields: str = Field("impressions,reach,clicks,spend,cpc,cpm,ctr,actions", title="Fields",
                        description="Comma-separated insight metrics.")
    date_preset: Optional[str] = Field("last_30d", title="Date Preset",
        json_schema_extra={"enum": ["today", "yesterday", "last_7d", "last_14d", "last_28d", "last_30d",
                                    "last_90d", "this_month", "last_month", "maximum"], "x-enum-searchable": True},
        description="Date range preset (ignored if Time Range set).")
    time_range_json: Optional[str] = Field(None, title="Time Range (JSON)",
        description='Optional {"since":"YYYY-MM-DD","until":"YYYY-MM-DD"} (overrides preset).',
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})
    breakdowns: Optional[str] = Field(None, title="Breakdowns", description="Comma-separated breakdowns (age,gender,country,...).")
    time_increment: Optional[str] = Field(None, title="Time Increment", description="1..90 (per-day rows), 'monthly', or 'all_days'.")
    filtering_json: Optional[str] = Field(None, title="Filtering (JSON)",
        description='Optional [{"field","operator","value"}] filter.',
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})
    limit: Optional[str] = Field("100", title="Limit", description="Max rows per page.")


async def _get_insights(c, token, secret):
    params = {"fields": c.fields, "level": c.level, "breakdowns": c.breakdowns,
              "time_increment": c.time_increment, "limit": c.limit}
    tr = _parse_json_field(c.time_range_json, "Time Range")
    if tr is not None:
        params["time_range"] = json.dumps(tr)
    else:
        params["date_preset"] = c.date_preset
    filt = _parse_json_field(c.filtering_json, "Filtering")
    if filt is not None:
        params["filtering"] = json.dumps(filt)
    return await _meta_request(token, "GET", f"/{c.object_id}/insights", params=params,
                               app_secret=secret, action_name="get_insights")


_reg(MetaGetInsightsConfig, "get_insights", _get_insights)


# ---------------------------------------------------------------------------
# Generic escape hatches
# ---------------------------------------------------------------------------

class MetaGetObjectConfig(BaseModel):
    """Read any Graph object by ID with a field set."""
    operation: Literal["get_object"] = Field("get_object",
        json_schema_extra=_op_extra("get_object", "Get Object", "Advanced"), title="Get Object")
    object_id: str = Field(..., title="Object ID", description="Any Graph object ID.")
    fields: Optional[str] = Field(None, title="Fields", description="Comma-separated fields (optional).")


async def _get_object(c, token, secret):
    return await _meta_request(token, "GET", f"/{c.object_id}", params={"fields": c.fields},
                               app_secret=secret, action_name="get_object")


class MetaGraphRequestConfig(BaseModel):
    """Make an arbitrary Graph/Marketing API request (escape hatch)."""
    operation: Literal["graph_request"] = Field("graph_request",
        json_schema_extra=_op_extra("graph_request", "Custom Graph Request", "Advanced"), title="Custom Graph Request")
    endpoint: str = Field(..., title="Endpoint", description="Path after the version, e.g. /act_123/campaigns.")
    method: str = Field("GET", title="Method", json_schema_extra={"enum": ["GET", "POST", "DELETE"], "x-enum-searchable": True})
    params_json: str = Field("{}", title="Query Params (JSON)", json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
                             description="Query parameters as a JSON object.")
    data_json: str = Field("{}", title="Body (JSON)", json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
                           description="Form body as a JSON object (nested values are JSON-encoded).")


async def _graph_request(c, token, secret):
    endpoint = c.endpoint if c.endpoint.startswith("/") else f"/{c.endpoint}"
    params = _parse_json_field(c.params_json, "Query Params") or {}
    raw = _parse_json_field(c.data_json, "Body") or {}
    data = {k: (json.dumps(v) if isinstance(v, (dict, list)) else v) for k, v in raw.items()}
    return await _meta_request(token, c.method, endpoint, params=params or None, data=data or None,
                               app_secret=secret, action_name="graph_request")


_reg(MetaGetObjectConfig, "get_object", _get_object)
_reg(MetaGraphRequestConfig, "graph_request", _graph_request)


# ---- Audiences ----

class MetaCustomAudienceCreateConfig(BaseModel):
    """Create a custom audience in an ad account."""
    operation: Literal["create_custom_audience"] = Field("create_custom_audience",
        json_schema_extra=_op_extra("create_custom_audience", "Create Custom Audience", "Audiences"), title="Create Custom Audience")
    ad_account_id: str = Field(..., title="Ad Account", description="Ad account ID (act_...).", json_schema_extra=_ACCOUNT_DYNAMIC)
    name: str = Field(..., title="Name", description="Custom audience name.")
    subtype: str = Field("CUSTOM", title="Subtype", description="Custom audience subtype.",
        json_schema_extra={"enum": ["CUSTOM", "WEBSITE", "ENGAGEMENT", "LOOKALIKE", "VIDEO"], "x-enum-searchable": True})
    fields_json: str = Field("{}", title="Additional Fields (JSON)",
        description="Optional extra fields (description, customer_file_source, retention_days, rule, pixel_id, ...).",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})

async def _create_custom_audience(c, token, secret):
    data = {"name": c.name, "subtype": c.subtype}
    for k, v in (_parse_json_field(c.fields_json, "Additional Fields") or {}).items():
        data[k] = json.dumps(v) if isinstance(v, (dict, list)) else v
    return await _meta_request(token, "POST", f"/{_acct(c.ad_account_id)}/customaudiences", data=data, app_secret=secret, action_name="create_custom_audience")

_reg(MetaCustomAudienceCreateConfig, "create_custom_audience", _create_custom_audience)

_reg(*_make_object_get("get_custom_audience", "Get Custom Audience", "Custom Audience",
    "name,subtype,approximate_count,delivery_status,operation_status,retention_days,rule,pixel_id,time_created,time_updated", "Audiences"))


class MetaCustomAudienceUpdateConfig(BaseModel):
    """Update a custom audience."""
    operation: Literal["update_custom_audience"] = Field("update_custom_audience",
        json_schema_extra=_op_extra("update_custom_audience", "Update Custom Audience", "Audiences"), title="Update Custom Audience")
    custom_audience_id: str = Field(..., title="Custom Audience ID", description="Custom audience ID.")
    fields_json: str = Field("{}", title="Fields to Update (JSON)", description="Fields to update.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})

async def _update_custom_audience(c, token, secret):
    data = {}
    for k, v in (_parse_json_field(c.fields_json, "Fields to Update") or {}).items():
        data[k] = json.dumps(v) if isinstance(v, (dict, list)) else v
    return await _meta_request(token, "POST", f"/{c.custom_audience_id}", data=data, app_secret=secret, action_name="update_custom_audience")

_reg(MetaCustomAudienceUpdateConfig, "update_custom_audience", _update_custom_audience)

_reg(*_make_object_delete("delete_custom_audience", "Delete Custom Audience", "Custom Audience", "Audiences"))

_reg(*_make_account_list("list_custom_audiences", "List Custom Audiences", "customaudiences",
    "id,name,subtype,approximate_count,delivery_status,time_created", "Audiences", with_status=False))


class MetaAddAudienceUsersConfig(BaseModel):
    """Add users to a custom audience (pre-hashed data)."""
    operation: Literal["add_audience_users"] = Field("add_audience_users",
        json_schema_extra=_op_extra("add_audience_users", "Add Audience Users", "Audiences"), title="Add Audience Users")
    custom_audience_id: str = Field(..., title="Custom Audience ID", description="Custom audience ID.")
    schema_keys_json: str = Field("[\"EMAIL\"]", title="Schema (JSON)", description="JSON array of schema keys, e.g. [\"EMAIL\"].",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})
    data_json: str = Field("[]", title="Data (JSON)", description="JSON 2-D array of already-SHA256-hashed rows.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})
    is_raw: str = Field("false", title="Is Raw", description="Whether data is raw (caller pre-hashes; keep false).",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})
    session_json: str = Field("", title="Session (JSON)", description="Optional session info.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})

async def _add_audience_users(c, token, secret):
    payload = {
        "schema": _parse_json_field(c.schema_keys_json, "Schema"),
        "data": _parse_json_field(c.data_json, "Data"),
        "is_raw": c.is_raw == "true",
    }
    session = _parse_json_field(c.session_json, "Session")
    data = {"payload": json.dumps(payload), "session": json.dumps(session) if session else None}
    return await _meta_request(token, "POST", f"/{c.custom_audience_id}/users", data=data, app_secret=secret, action_name="add_audience_users")

_reg(MetaAddAudienceUsersConfig, "add_audience_users", _add_audience_users)


class MetaRemoveAudienceUsersConfig(BaseModel):
    """Remove users from a custom audience (pre-hashed data)."""
    operation: Literal["remove_audience_users"] = Field("remove_audience_users",
        json_schema_extra=_op_extra("remove_audience_users", "Remove Audience Users", "Audiences"), title="Remove Audience Users")
    custom_audience_id: str = Field(..., title="Custom Audience ID", description="Custom audience ID.")
    schema_keys_json: str = Field("[\"EMAIL\"]", title="Schema (JSON)", description="JSON array of schema keys, e.g. [\"EMAIL\"].",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})
    data_json: str = Field("[]", title="Data (JSON)", description="JSON 2-D array of already-SHA256-hashed rows.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})
    is_raw: str = Field("false", title="Is Raw", description="Whether data is raw (caller pre-hashes; keep false).",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})
    session_json: str = Field("", title="Session (JSON)", description="Optional session info.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})

async def _remove_audience_users(c, token, secret):
    payload = {
        "schema": _parse_json_field(c.schema_keys_json, "Schema"),
        "data": _parse_json_field(c.data_json, "Data"),
        "is_raw": c.is_raw == "true",
    }
    session = _parse_json_field(c.session_json, "Session")
    data = {"payload": json.dumps(payload), "session": json.dumps(session) if session else None}
    return await _meta_request(token, "DELETE", f"/{c.custom_audience_id}/users", data=data, app_secret=secret, action_name="remove_audience_users")

_reg(MetaRemoveAudienceUsersConfig, "remove_audience_users", _remove_audience_users)


class MetaLookalikeAudienceCreateConfig(BaseModel):
    """Create a lookalike audience from an origin audience."""
    operation: Literal["create_lookalike_audience"] = Field("create_lookalike_audience",
        json_schema_extra=_op_extra("create_lookalike_audience", "Create Lookalike Audience", "Audiences"), title="Create Lookalike Audience")
    ad_account_id: str = Field(..., title="Ad Account", description="Ad account ID (act_...).", json_schema_extra=_ACCOUNT_DYNAMIC)
    name: str = Field(..., title="Name", description="Lookalike audience name.")
    origin_audience_id: str = Field(..., title="Origin Audience ID", description="Source custom audience ID.")
    lookalike_spec_json: str = Field("{\"type\":\"similarity\",\"country\":\"US\"}", title="Lookalike Spec (JSON)",
        description="Lookalike spec, e.g. {\"type\":\"similarity\",\"country\":\"US\"}.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})

async def _create_lookalike_audience(c, token, secret):
    data = {
        "name": c.name,
        "subtype": "LOOKALIKE",
        "origin_audience_id": c.origin_audience_id,
        "lookalike_spec": json.dumps(_parse_json_field(c.lookalike_spec_json, "Lookalike Spec")),
    }
    return await _meta_request(token, "POST", f"/{_acct(c.ad_account_id)}/customaudiences", data=data, app_secret=secret, action_name="create_lookalike_audience")

_reg(MetaLookalikeAudienceCreateConfig, "create_lookalike_audience", _create_lookalike_audience)


class MetaSavedAudienceCreateConfig(BaseModel):
    """Create a saved audience from a targeting spec."""
    operation: Literal["create_saved_audience"] = Field("create_saved_audience",
        json_schema_extra=_op_extra("create_saved_audience", "Create Saved Audience", "Audiences"), title="Create Saved Audience")
    ad_account_id: str = Field(..., title="Ad Account", description="Ad account ID (act_...).", json_schema_extra=_ACCOUNT_DYNAMIC)
    name: str = Field(..., title="Name", description="Saved audience name.")
    targeting_json: str = Field("{}", title="Targeting (JSON)", description="Targeting spec.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})

async def _create_saved_audience(c, token, secret):
    data = {"name": c.name, "targeting": json.dumps(_parse_json_field(c.targeting_json, "Targeting"))}
    return await _meta_request(token, "POST", f"/{_acct(c.ad_account_id)}/saved_audiences", data=data, app_secret=secret, action_name="create_saved_audience")

_reg(MetaSavedAudienceCreateConfig, "create_saved_audience", _create_saved_audience)

_reg(*_make_object_get("get_saved_audience", "Get Saved Audience", "Saved Audience",
    "name,description,targeting,approximate_count_lower_bound,approximate_count_upper_bound,run_status,time_created", "Audiences"))

_reg(*_make_account_list("list_saved_audiences", "List Saved Audiences", "saved_audiences",
    "id,name,description,run_status,time_created", "Audiences", with_status=False))


class MetaSavedAudienceUpdateConfig(BaseModel):
    """Update a saved audience."""
    operation: Literal["update_saved_audience"] = Field("update_saved_audience",
        json_schema_extra=_op_extra("update_saved_audience", "Update Saved Audience", "Audiences"), title="Update Saved Audience")
    saved_audience_id: str = Field(..., title="Saved Audience ID", description="Saved audience ID.")
    fields_json: str = Field("{}", title="Fields to Update (JSON)", description="Fields to update.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})

async def _update_saved_audience(c, token, secret):
    data = {}
    for k, v in (_parse_json_field(c.fields_json, "Fields to Update") or {}).items():
        data[k] = json.dumps(v) if isinstance(v, (dict, list)) else v
    return await _meta_request(token, "POST", f"/{c.saved_audience_id}", data=data, app_secret=secret, action_name="update_saved_audience")

_reg(MetaSavedAudienceUpdateConfig, "update_saved_audience", _update_saved_audience)

_reg(*_make_object_delete("delete_saved_audience", "Delete Saved Audience", "Saved Audience", "Audiences"))


class MetaShareAudienceConfig(BaseModel):
    """Share a custom audience with other ad accounts."""
    operation: Literal["share_audience"] = Field("share_audience",
        json_schema_extra=_op_extra("share_audience", "Share Audience", "Audiences"), title="Share Audience")
    custom_audience_id: str = Field(..., title="Custom Audience ID", description="Custom audience ID.")
    adaccounts_json: str = Field("[]", title="Ad Accounts (JSON)", description="JSON list of ad account IDs to share with.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})
    permissions: str = Field("", title="Permissions", description="Optional permissions.")

async def _share_audience(c, token, secret):
    data = {"adaccounts": json.dumps(_parse_json_field(c.adaccounts_json, "Ad Accounts"))}
    if c.permissions:
        data["permissions"] = c.permissions
    return await _meta_request(token, "POST", f"/{c.custom_audience_id}/adaccounts", data=data, app_secret=secret, action_name="share_audience")

_reg(MetaShareAudienceConfig, "share_audience", _share_audience)


# ---- Targeting / Estimates / Async Insights ----

class MetaSearchTargetingConfig(BaseModel):
    """Search Meta's targeting taxonomy (interests, geo, categories)."""
    operation: Literal["search_targeting"] = Field("search_targeting",
        json_schema_extra=_op_extra("search_targeting", "Search Targeting", "Targeting"), title="Search Targeting")
    type: str = Field(..., title="Type", description="Targeting search type.",
        json_schema_extra={"enum": ["adinterest", "adinterestsuggestion", "adinterestvalid",
            "adgeolocation", "adgeolocationmeta", "adTargetingCategory", "adlocale",
            "adworkemployer", "adeducationschool", "adeducationmajor", "adcountry",
            "adzipcode", "adworkposition", "adcity"], "x-enum-searchable": True})
    q: Optional[str] = Field(None, title="Query", description="Search query string.")
    targeting_class: Optional[str] = Field(None, title="Class", description="Targeting class (sent as the 'class' query key).")
    limit: Optional[str] = Field("25", title="Limit", description="Max results.")
    locale: Optional[str] = Field(None, title="Locale", description="Result locale (e.g. en_US).")

async def _search_targeting(c, token, secret):
    params = {}
    if c.type:
        params["type"] = c.type
    if c.q:
        params["q"] = c.q
    if c.targeting_class:
        params["class"] = c.targeting_class
    if c.limit:
        params["limit"] = c.limit
    if c.locale:
        params["locale"] = c.locale
    return await _meta_request(token, "GET", "/search", params=params, app_secret=secret, action_name="search_targeting")

_reg(MetaSearchTargetingConfig, "search_targeting", _search_targeting)


class MetaValidateTargetingConfig(BaseModel):
    """Validate targeting ids/names/specs against an ad account."""
    operation: Literal["validate_targeting"] = Field("validate_targeting",
        json_schema_extra=_op_extra("validate_targeting", "Validate Targeting", "Targeting"), title="Validate Targeting")
    ad_account_id: str = Field(..., title="Ad Account", description="Ad account ID (act_...).", json_schema_extra=_ACCOUNT_DYNAMIC)
    id_list_json: str = Field("", title="ID List (JSON)", description="Optional JSON list of targeting ids.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})
    name_list_json: str = Field("", title="Name List (JSON)", description="Optional JSON list of targeting names.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})
    targeting_list_json: str = Field("", title="Targeting List (JSON)", description="Optional JSON list of targeting objects.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})
    is_exclusion: Optional[str] = Field(None, title="Is Exclusion", description="Validate as exclusions.",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})

async def _validate_targeting(c, token, secret):
    params = {}
    id_list = _parse_json_field(c.id_list_json, "ID List")
    if id_list is not None:
        params["id_list"] = json.dumps(id_list)
    name_list = _parse_json_field(c.name_list_json, "Name List")
    if name_list is not None:
        params["name_list"] = json.dumps(name_list)
    targeting_list = _parse_json_field(c.targeting_list_json, "Targeting List")
    if targeting_list is not None:
        params["targeting_list"] = json.dumps(targeting_list)
    if c.is_exclusion is not None:
        params["is_exclusion"] = c.is_exclusion
    return await _meta_request(token, "GET", f"/{_acct(c.ad_account_id)}/targetingvalidation",
                               params=params, app_secret=secret, action_name="validate_targeting")

_reg(MetaValidateTargetingConfig, "validate_targeting", _validate_targeting)


class MetaBrowseTargetingConfig(BaseModel):
    """Browse the targeting category tree for an ad account."""
    operation: Literal["browse_targeting"] = Field("browse_targeting",
        json_schema_extra=_op_extra("browse_targeting", "Browse Targeting", "Targeting"), title="Browse Targeting")
    ad_account_id: str = Field(..., title="Ad Account", description="Ad account ID (act_...).", json_schema_extra=_ACCOUNT_DYNAMIC)
    limit_type: Optional[str] = Field(None, title="Limit Type", description="Restrict browse to a targeting type.")
    regulated_categories: Optional[str] = Field(None, title="Regulated Categories", description="Regulated categories filter.")

async def _browse_targeting(c, token, secret):
    params = {}
    if c.limit_type:
        params["limit_type"] = c.limit_type
    if c.regulated_categories:
        params["regulated_categories"] = c.regulated_categories
    return await _meta_request(token, "GET", f"/{_acct(c.ad_account_id)}/targetingbrowse",
                               params=params, app_secret=secret, action_name="browse_targeting")

_reg(MetaBrowseTargetingConfig, "browse_targeting", _browse_targeting)


class MetaTargetingSuggestionsConfig(BaseModel):
    """Get targeting suggestions from a seed targeting list."""
    operation: Literal["targeting_suggestions"] = Field("targeting_suggestions",
        json_schema_extra=_op_extra("targeting_suggestions", "Targeting Suggestions", "Targeting"), title="Targeting Suggestions")
    ad_account_id: str = Field(..., title="Ad Account", description="Ad account ID (act_...).", json_schema_extra=_ACCOUNT_DYNAMIC)
    targeting_list_json: str = Field(..., title="Targeting List (JSON)", description="JSON list of {type, id} seed targetings.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})

async def _targeting_suggestions(c, token, secret):
    targeting_list = _parse_json_field(c.targeting_list_json, "Targeting List")
    params = {"targeting_list": json.dumps(targeting_list)}
    return await _meta_request(token, "GET", f"/{_acct(c.ad_account_id)}/targetingsuggestions",
                               params=params, app_secret=secret, action_name="targeting_suggestions")

_reg(MetaTargetingSuggestionsConfig, "targeting_suggestions", _targeting_suggestions)


class MetaReachEstimateConfig(BaseModel):
    """Estimate reach for a targeting spec."""
    operation: Literal["reach_estimate"] = Field("reach_estimate",
        json_schema_extra=_op_extra("reach_estimate", "Reach Estimate", "Targeting"), title="Reach Estimate")
    ad_account_id: str = Field(..., title="Ad Account", description="Ad account ID (act_...).", json_schema_extra=_ACCOUNT_DYNAMIC)
    targeting_spec_json: str = Field(..., title="Targeting Spec (JSON)", description="Targeting spec object.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})

async def _reach_estimate(c, token, secret):
    targeting_spec = _parse_json_field(c.targeting_spec_json, "Targeting Spec")
    params = {"targeting_spec": json.dumps(targeting_spec)}
    return await _meta_request(token, "GET", f"/{_acct(c.ad_account_id)}/reachestimate",
                               params=params, app_secret=secret, action_name="reach_estimate")

_reg(MetaReachEstimateConfig, "reach_estimate", _reach_estimate)


class MetaDeliveryEstimateConfig(BaseModel):
    """Estimate daily outcomes for a targeting spec + optimization goal."""
    operation: Literal["delivery_estimate"] = Field("delivery_estimate",
        json_schema_extra=_op_extra("delivery_estimate", "Delivery Estimate", "Targeting"), title="Delivery Estimate")
    ad_account_id: str = Field(..., title="Ad Account", description="Ad account ID (act_...).", json_schema_extra=_ACCOUNT_DYNAMIC)
    optimization_goal: str = Field(..., title="Optimization Goal", description="Optimization goal (e.g. LINK_CLICKS, REACH).")
    targeting_spec_json: str = Field(..., title="Targeting Spec (JSON)", description="Targeting spec object.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})

async def _delivery_estimate(c, token, secret):
    targeting_spec = _parse_json_field(c.targeting_spec_json, "Targeting Spec")
    params = {
        "optimization_goal": c.optimization_goal,
        "targeting_spec": json.dumps(targeting_spec),
    }
    return await _meta_request(token, "GET", f"/{_acct(c.ad_account_id)}/delivery_estimate",
                               params=params, app_secret=secret, action_name="delivery_estimate")

_reg(MetaDeliveryEstimateConfig, "delivery_estimate", _delivery_estimate)


class MetaCreateInsightsReportConfig(BaseModel):
    """Kick off an async insights report; returns a report_run_id to poll."""
    operation: Literal["create_insights_report"] = Field("create_insights_report",
        json_schema_extra=_op_extra("create_insights_report", "Create Insights Report (Async)", "Insights"),
        title="Create Insights Report (Async)")
    object_id: str = Field(..., title="Object ID", description="Ad account (act_...), campaign, ad set, or ad id.")
    level: Optional[str] = Field(None, title="Level", description="Aggregation level.",
        json_schema_extra={"enum": ["account", "campaign", "adset", "ad"], "x-enum-searchable": True})
    fields: str = Field("impressions,reach,clicks,spend", title="Fields", description="Comma-separated insight fields.")
    date_preset: Optional[str] = Field("last_30d", title="Date Preset", description="Relative date range preset.")
    breakdowns: Optional[str] = Field(None, title="Breakdowns", description="Comma-separated breakdown dimensions.")
    time_increment: Optional[str] = Field(None, title="Time Increment", description="Days per row, or 'monthly'/'all_days'.")

async def _create_insights_report(c, token, secret):
    data = {"fields": c.fields}
    if c.level:
        data["level"] = c.level
    if c.date_preset:
        data["date_preset"] = c.date_preset
    if c.breakdowns:
        data["breakdowns"] = c.breakdowns
    if c.time_increment:
        data["time_increment"] = c.time_increment
    return await _meta_request(token, "POST", f"/{c.object_id}/insights", data=data,
                               app_secret=secret, action_name="create_insights_report")

_reg(MetaCreateInsightsReportConfig, "create_insights_report", _create_insights_report)


_c, _h = _make_object_get("get_insights_report", "Get Insights Report Status", "Report Run ID",
                          "async_status,async_percent_completion,date_start,date_stop", "Insights")
_reg(_c, "get_insights_report", _h)


class MetaFetchInsightsReportConfig(BaseModel):
    """Fetch the results page of a completed async insights report."""
    operation: Literal["fetch_insights_report"] = Field("fetch_insights_report",
        json_schema_extra=_op_extra("fetch_insights_report", "Fetch Insights Report Results", "Insights"),
        title="Fetch Insights Report Results")
    report_run_id: str = Field(..., title="Report Run ID", description="The report run id from create_insights_report.")
    limit: Optional[str] = Field("100", title="Limit", description="Max rows per page.")

async def _fetch_insights_report(c, token, secret):
    params = {}
    if c.limit:
        params["limit"] = c.limit
    return await _meta_request(token, "GET", f"/{c.report_run_id}/insights", params=params,
                               app_secret=secret, action_name="fetch_insights_report")

_reg(MetaFetchInsightsReportConfig, "fetch_insights_report", _fetch_insights_report)


# ---- Conversions API + Pixel/Dataset ----

class MetaSendConversionEventsConfig(BaseModel):
    """Send server-side conversion events to a pixel/dataset via the Conversions API."""
    operation: Literal["send_conversion_events"] = Field("send_conversion_events",
        json_schema_extra=_op_extra("send_conversion_events", "Send Conversion Events", "Conversions API"), title="Send Conversion Events")
    pixel_id: str = Field(..., title="Pixel/Dataset ID", description="Pixel ID (same as dataset ID) to receive the events.")
    data_json: str = Field(..., title="Events (JSON Array)", description="JSON array of server event objects (each with fully-formed, hashed user_data).",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})
    test_event_code: Optional[str] = Field(None, title="Test Event Code", description="Optional test event code for validating events in Events Manager.")

async def _send_conversion_events(c, token, secret):
    events = _parse_json_field(c.data_json, "Events (JSON Array)")
    data = {"data": json.dumps(events)}
    if c.test_event_code:
        data["test_event_code"] = c.test_event_code
    return await _meta_request(token, "POST", f"/{c.pixel_id}/events", data=data, app_secret=secret, action_name="send_conversion_events")

_reg(MetaSendConversionEventsConfig, "send_conversion_events", _send_conversion_events)


class MetaSendOfflineEventsConfig(BaseModel):
    """Send offline conversion events to a dataset via the Conversions API."""
    operation: Literal["send_offline_events"] = Field("send_offline_events",
        json_schema_extra=_op_extra("send_offline_events", "Send Offline Events", "Conversions API"), title="Send Offline Events")
    dataset_id: str = Field(..., title="Dataset ID", description="Offline event dataset ID to receive the events.")
    data_json: str = Field(..., title="Events (JSON Array)", description="JSON array of offline event objects (each with fully-formed, hashed user_data).",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})
    upload_tag: Optional[str] = Field(None, title="Upload Tag", description="Optional tag grouping the events into an upload batch.")

async def _send_offline_events(c, token, secret):
    events = _parse_json_field(c.data_json, "Events (JSON Array)")
    data = {"data": json.dumps(events)}
    if c.upload_tag:
        data["upload_tag"] = c.upload_tag
    return await _meta_request(token, "POST", f"/{c.dataset_id}/events", data=data, app_secret=secret, action_name="send_offline_events")

_reg(MetaSendOfflineEventsConfig, "send_offline_events", _send_offline_events)


class MetaCreatePixelConfig(BaseModel):
    """Create a new ads pixel on an ad account."""
    operation: Literal["create_pixel"] = Field("create_pixel",
        json_schema_extra=_op_extra("create_pixel", "Create Pixel", "Pixel"), title="Create Pixel")
    ad_account_id: str = Field(..., title="Ad Account", description="Ad account ID (act_...).", json_schema_extra=_ACCOUNT_DYNAMIC)
    name: str = Field(..., title="Name", description="Pixel name.")

async def _create_pixel(c, token, secret):
    data = {"name": c.name}
    return await _meta_request(token, "POST", f"/{_acct(c.ad_account_id)}/adspixels", data=data, app_secret=secret, action_name="create_pixel")

_reg(MetaCreatePixelConfig, "create_pixel", _create_pixel)


_reg(*_make_account_list("list_pixels", "List Pixels", "adspixels",
    "id,name,code,last_fired_time,creation_time", "Pixel", with_status=False))

_reg(*_make_object_get("get_pixel", "Get Pixel", "Pixel ID",
    "name,code,last_fired_time,creation_time,data_use_setting,enable_automatic_matching", "Pixel"))


class MetaUpdatePixelConfig(BaseModel):
    """Update an existing ads pixel."""
    operation: Literal["update_pixel"] = Field("update_pixel",
        json_schema_extra=_op_extra("update_pixel", "Update Pixel", "Pixel"), title="Update Pixel")
    pixel_id: str = Field(..., title="Pixel ID", description="Pixel ID to update.")
    fields_json: str = Field("{}", title="Fields (JSON)", description="Fields to update on the pixel.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})

async def _update_pixel(c, token, secret):
    data = {}
    for k, v in (_parse_json_field(c.fields_json, "Fields") or {}).items():
        data[k] = json.dumps(v) if isinstance(v, (dict, list)) else v
    return await _meta_request(token, "POST", f"/{c.pixel_id}", data=data, app_secret=secret, action_name="update_pixel")

_reg(MetaUpdatePixelConfig, "update_pixel", _update_pixel)


class MetaGetPixelStatsConfig(BaseModel):
    """Get event statistics for a pixel."""
    operation: Literal["get_pixel_stats"] = Field("get_pixel_stats",
        json_schema_extra=_op_extra("get_pixel_stats", "Get Pixel Stats", "Pixel"), title="Get Pixel Stats")
    pixel_id: str = Field(..., title="Pixel ID", description="Pixel ID to fetch stats for.")
    aggregation: Optional[str] = Field(None, title="Aggregation", description="Aggregation dimension (e.g. event).")
    start_time: Optional[str] = Field(None, title="Start Time", description="Start of the stats window (Unix timestamp or ISO 8601).")
    end_time: Optional[str] = Field(None, title="End Time", description="End of the stats window (Unix timestamp or ISO 8601).")

async def _get_pixel_stats(c, token, secret):
    params = {}
    if c.aggregation:
        params["aggregation"] = c.aggregation
    if c.start_time:
        params["start_time"] = c.start_time
    if c.end_time:
        params["end_time"] = c.end_time
    return await _meta_request(token, "GET", f"/{c.pixel_id}/stats", params=params, app_secret=secret, action_name="get_pixel_stats")

_reg(MetaGetPixelStatsConfig, "get_pixel_stats", _get_pixel_stats)


class MetaSharePixelConfig(BaseModel):
    """Share a pixel with another ad account."""
    operation: Literal["share_pixel"] = Field("share_pixel",
        json_schema_extra=_op_extra("share_pixel", "Share Pixel", "Pixel"), title="Share Pixel")
    pixel_id: str = Field(..., title="Pixel ID", description="Pixel ID to share.")
    account_id: str = Field(..., title="Account ID", description="Ad account ID to share the pixel with.")
    business: str = Field(..., title="Business ID", description="Business ID that owns the shared account.")

async def _share_pixel(c, token, secret):
    data = {"account_id": c.account_id, "business": c.business}
    return await _meta_request(token, "POST", f"/{c.pixel_id}/shared_accounts", data=data, app_secret=secret, action_name="share_pixel")

_reg(MetaSharePixelConfig, "share_pixel", _share_pixel)


# ---- Business Management + Product Catalogs ----

# Business

class MetaListBusinessesConfig(BaseModel):
    """List businesses the user has access to."""
    operation: Literal["list_businesses"] = Field("list_businesses",
        json_schema_extra=_op_extra("list_businesses", "List Businesses", "Business"), title="List Businesses")
    fields: str = Field("id,name", title="Fields", description="Comma-separated fields to return.")
    limit: Optional[int] = Field(25, title="Limit", description="Max results.")

async def _list_businesses(c, token, secret):
    params = {"fields": c.fields}
    if c.limit is not None:
        params["limit"] = c.limit
    return await _meta_request(token, "GET", "/me/businesses", params=params, app_secret=secret, action_name="list_businesses")

_reg(MetaListBusinessesConfig, "list_businesses", _list_businesses)

_reg(*(_make_object_get("get_business", "Get Business", "Business ID",
    "id,name,created_time,verification_status,primary_page,timezone_id", "Business")))


class MetaListOwnedPagesConfig(BaseModel):
    """List pages owned by a business."""
    operation: Literal["list_owned_pages"] = Field("list_owned_pages",
        json_schema_extra=_op_extra("list_owned_pages", "List Owned Pages", "Business"), title="List Owned Pages")
    business_id: str = Field(..., title="Business ID", description="Business ID.")
    fields: str = Field("id,name,access_token,tasks", title="Fields", description="Comma-separated fields to return.")
    limit: Optional[int] = Field(25, title="Limit", description="Max results.")

async def _list_owned_pages(c, token, secret):
    params = {"fields": c.fields}
    if c.limit is not None:
        params["limit"] = c.limit
    return await _meta_request(token, "GET", f"/{c.business_id}/owned_pages", params=params, app_secret=secret, action_name="list_owned_pages")

_reg(MetaListOwnedPagesConfig, "list_owned_pages", _list_owned_pages)


class MetaListOwnedAdAccountsConfig(BaseModel):
    """List ad accounts owned by a business."""
    operation: Literal["list_owned_ad_accounts"] = Field("list_owned_ad_accounts",
        json_schema_extra=_op_extra("list_owned_ad_accounts", "List Owned Ad Accounts", "Business"), title="List Owned Ad Accounts")
    business_id: str = Field(..., title="Business ID", description="Business ID.")
    fields: str = Field("id,name,account_status,currency", title="Fields", description="Comma-separated fields to return.")
    limit: Optional[int] = Field(25, title="Limit", description="Max results.")

async def _list_owned_ad_accounts(c, token, secret):
    params = {"fields": c.fields}
    if c.limit is not None:
        params["limit"] = c.limit
    return await _meta_request(token, "GET", f"/{c.business_id}/owned_ad_accounts", params=params, app_secret=secret, action_name="list_owned_ad_accounts")

_reg(MetaListOwnedAdAccountsConfig, "list_owned_ad_accounts", _list_owned_ad_accounts)


class MetaListClientAdAccountsConfig(BaseModel):
    """List ad accounts a business has client access to."""
    operation: Literal["list_client_ad_accounts"] = Field("list_client_ad_accounts",
        json_schema_extra=_op_extra("list_client_ad_accounts", "List Client Ad Accounts", "Business"), title="List Client Ad Accounts")
    business_id: str = Field(..., title="Business ID", description="Business ID.")
    fields: str = Field("id,name,account_status", title="Fields", description="Comma-separated fields to return.")
    limit: Optional[int] = Field(25, title="Limit", description="Max results.")

async def _list_client_ad_accounts(c, token, secret):
    params = {"fields": c.fields}
    if c.limit is not None:
        params["limit"] = c.limit
    return await _meta_request(token, "GET", f"/{c.business_id}/client_ad_accounts", params=params, app_secret=secret, action_name="list_client_ad_accounts")

_reg(MetaListClientAdAccountsConfig, "list_client_ad_accounts", _list_client_ad_accounts)


class MetaListSystemUsersConfig(BaseModel):
    """List system users of a business."""
    operation: Literal["list_system_users"] = Field("list_system_users",
        json_schema_extra=_op_extra("list_system_users", "List System Users", "Business"), title="List System Users")
    business_id: str = Field(..., title="Business ID", description="Business ID.")
    fields: str = Field("id,name,role", title="Fields", description="Comma-separated fields to return.")
    limit: Optional[int] = Field(25, title="Limit", description="Max results.")

async def _list_system_users(c, token, secret):
    params = {"fields": c.fields}
    if c.limit is not None:
        params["limit"] = c.limit
    return await _meta_request(token, "GET", f"/{c.business_id}/system_users", params=params, app_secret=secret, action_name="list_system_users")

_reg(MetaListSystemUsersConfig, "list_system_users", _list_system_users)


class MetaCreateSystemUserConfig(BaseModel):
    """Create a system user under a business."""
    operation: Literal["create_system_user"] = Field("create_system_user",
        json_schema_extra=_op_extra("create_system_user", "Create System User", "Business"), title="Create System User")
    business_id: str = Field(..., title="Business ID", description="Business ID.")
    name: str = Field(..., title="Name", description="System user name.")
    role: str = Field("EMPLOYEE", title="Role", description="System user role.",
        json_schema_extra={"enum": ["ADMIN", "EMPLOYEE"], "x-enum-searchable": True})

async def _create_system_user(c, token, secret):
    data = {"name": c.name, "role": c.role}
    return await _meta_request(token, "POST", f"/{c.business_id}/system_users", data=data, app_secret=secret, action_name="create_system_user")

_reg(MetaCreateSystemUserConfig, "create_system_user", _create_system_user)


class MetaInstallAppToSystemUserConfig(BaseModel):
    """Install an app to a system user (prerequisite for minting its token)."""
    operation: Literal["install_app_to_system_user"] = Field("install_app_to_system_user",
        json_schema_extra=_op_extra("install_app_to_system_user", "Install App to System User", "Business"), title="Install App to System User")
    system_user_id: str = Field(..., title="System User ID", description="System user ID.")
    business_app: str = Field(..., title="App ID", description="App (business_app) ID to install.")

async def _install_app_to_system_user(c, token, secret):
    return await _meta_request(token, "POST", f"/{c.system_user_id}/applications",
                               data={"business_app": c.business_app}, app_secret=secret, action_name="install_app_to_system_user")

_reg(MetaInstallAppToSystemUserConfig, "install_app_to_system_user", _install_app_to_system_user)


class MetaGenerateSystemUserTokenConfig(BaseModel):
    """Generate an access token for a system user (install the app first)."""
    operation: Literal["generate_system_user_token"] = Field("generate_system_user_token",
        json_schema_extra=_op_extra("generate_system_user_token", "Generate System User Token", "Business"), title="Generate System User Token")
    system_user_id: str = Field(..., title="System User ID", description="System user ID.")
    business_app: str = Field(..., title="Business App ID", description="App ID the token is scoped to.")
    scope: str = Field(..., title="Scope", description="Comma-separated permission scopes.")

async def _generate_system_user_token(c, token, secret):
    data = {"business_app": c.business_app, "scope": c.scope}
    return await _meta_request(token, "POST", f"/{c.system_user_id}/access_tokens", data=data, app_secret=secret, action_name="generate_system_user_token")

_reg(MetaGenerateSystemUserTokenConfig, "generate_system_user_token", _generate_system_user_token)


class MetaListBusinessUsersConfig(BaseModel):
    """List business users of a business."""
    operation: Literal["list_business_users"] = Field("list_business_users",
        json_schema_extra=_op_extra("list_business_users", "List Business Users", "Business"), title="List Business Users")
    business_id: str = Field(..., title="Business ID", description="Business ID.")
    fields: str = Field("id,name,email,role", title="Fields", description="Comma-separated fields to return.")
    limit: Optional[int] = Field(25, title="Limit", description="Max results.")

async def _list_business_users(c, token, secret):
    params = {"fields": c.fields}
    if c.limit is not None:
        params["limit"] = c.limit
    return await _meta_request(token, "GET", f"/{c.business_id}/business_users", params=params, app_secret=secret, action_name="list_business_users")

_reg(MetaListBusinessUsersConfig, "list_business_users", _list_business_users)


class MetaListAssignedUsersConfig(BaseModel):
    """List users assigned to a business asset."""
    operation: Literal["list_assigned_users"] = Field("list_assigned_users",
        json_schema_extra=_op_extra("list_assigned_users", "List Assigned Users", "Business"), title="List Assigned Users")
    asset_id: str = Field(..., title="Asset ID", description="Asset ID (page, ad account, etc.).")
    business: str = Field(..., title="Business ID", description="Owning business ID.")
    fields: str = Field("id,name,tasks", title="Fields", description="Comma-separated fields to return.")

async def _list_assigned_users(c, token, secret):
    params = {"business": c.business, "fields": c.fields}
    return await _meta_request(token, "GET", f"/{c.asset_id}/assigned_users", params=params, app_secret=secret, action_name="list_assigned_users")

_reg(MetaListAssignedUsersConfig, "list_assigned_users", _list_assigned_users)


class MetaAssignAssetUserConfig(BaseModel):
    """Assign a user to a business asset with tasks."""
    operation: Literal["assign_asset_user"] = Field("assign_asset_user",
        json_schema_extra=_op_extra("assign_asset_user", "Assign Asset User", "Business"), title="Assign Asset User")
    asset_id: str = Field(..., title="Asset ID", description="Asset ID (page, ad account, etc.).")
    user: str = Field(..., title="User ID", description="User or system user ID to assign.")
    tasks_json: str = Field(..., title="Tasks (JSON)", description='JSON list of tasks, e.g. ["MANAGE"].',
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})
    business: Optional[str] = Field(None, title="Business ID", description="Owning business ID.")

async def _assign_asset_user(c, token, secret):
    tasks = _parse_json_field(c.tasks_json, "Tasks")
    data = {"user": c.user, "tasks": json.dumps(tasks)}
    if c.business:
        data["business"] = c.business
    return await _meta_request(token, "POST", f"/{c.asset_id}/assigned_users", data=data, app_secret=secret, action_name="assign_asset_user")

_reg(MetaAssignAssetUserConfig, "assign_asset_user", _assign_asset_user)


# Catalog

class MetaListCatalogsConfig(BaseModel):
    """List product catalogs owned by a business."""
    operation: Literal["list_catalogs"] = Field("list_catalogs",
        json_schema_extra=_op_extra("list_catalogs", "List Catalogs", "Catalog"), title="List Catalogs")
    business_id: str = Field(..., title="Business ID", description="Business ID.")
    fields: str = Field("id,name,vertical,product_count", title="Fields", description="Comma-separated fields to return.")
    limit: Optional[int] = Field(25, title="Limit", description="Max results.")

async def _list_catalogs(c, token, secret):
    params = {"fields": c.fields}
    if c.limit is not None:
        params["limit"] = c.limit
    return await _meta_request(token, "GET", f"/{c.business_id}/owned_product_catalogs", params=params, app_secret=secret, action_name="list_catalogs")

_reg(MetaListCatalogsConfig, "list_catalogs", _list_catalogs)


class MetaCreateCatalogConfig(BaseModel):
    """Create a product catalog under a business."""
    operation: Literal["create_catalog"] = Field("create_catalog",
        json_schema_extra=_op_extra("create_catalog", "Create Catalog", "Catalog"), title="Create Catalog")
    business_id: str = Field(..., title="Business ID", description="Business ID.")
    name: str = Field(..., title="Name", description="Catalog name.")
    vertical: str = Field("commerce", title="Vertical", description="Catalog vertical.",
        json_schema_extra={"enum": ["commerce", "hotels", "flights", "destinations", "home_listings", "vehicles", "offline_commerce"], "x-enum-searchable": True})

async def _create_catalog(c, token, secret):
    data = {"name": c.name, "vertical": c.vertical}
    return await _meta_request(token, "POST", f"/{c.business_id}/owned_product_catalogs", data=data, app_secret=secret, action_name="create_catalog")

_reg(MetaCreateCatalogConfig, "create_catalog", _create_catalog)


_reg(*(_make_object_get("get_catalog", "Get Catalog", "Catalog ID",
    "id,name,vertical,product_count", "Catalog")))


class MetaUpdateCatalogConfig(BaseModel):
    """Update a product catalog."""
    operation: Literal["update_catalog"] = Field("update_catalog",
        json_schema_extra=_op_extra("update_catalog", "Update Catalog", "Catalog"), title="Update Catalog")
    catalog_id: str = Field(..., title="Catalog ID", description="Catalog ID.")
    fields_json: str = Field("{}", title="Fields (JSON)", description="Fields to update.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})

async def _update_catalog(c, token, secret):
    data = {}
    for k, v in (_parse_json_field(c.fields_json, "Fields") or {}).items():
        data[k] = json.dumps(v) if isinstance(v, (dict, list)) else v
    return await _meta_request(token, "POST", f"/{c.catalog_id}", data=data, app_secret=secret, action_name="update_catalog")

_reg(MetaUpdateCatalogConfig, "update_catalog", _update_catalog)


_reg(*(_make_object_delete("delete_catalog", "Delete Catalog", "Catalog ID", "Catalog")))


class MetaListProductsConfig(BaseModel):
    """List products in a catalog."""
    operation: Literal["list_products"] = Field("list_products",
        json_schema_extra=_op_extra("list_products", "List Products", "Catalog"), title="List Products")
    catalog_id: str = Field(..., title="Catalog ID", description="Catalog ID.")
    fields: str = Field("id,retailer_id,name,price,availability,image_url", title="Fields", description="Comma-separated fields to return.")
    limit: Optional[int] = Field(25, title="Limit", description="Max results.")

async def _list_products(c, token, secret):
    params = {"fields": c.fields}
    if c.limit is not None:
        params["limit"] = c.limit
    return await _meta_request(token, "GET", f"/{c.catalog_id}/products", params=params, app_secret=secret, action_name="list_products")

_reg(MetaListProductsConfig, "list_products", _list_products)


class MetaCreateProductConfig(BaseModel):
    """Create a product in a catalog."""
    operation: Literal["create_product"] = Field("create_product",
        json_schema_extra=_op_extra("create_product", "Create Product", "Catalog"), title="Create Product")
    catalog_id: str = Field(..., title="Catalog ID", description="Catalog ID.")
    retailer_id: str = Field(..., title="Retailer ID", description="Merchant-side unique product ID.")
    name: str = Field(..., title="Name", description="Product name.")
    fields_json: str = Field("{}", title="Additional Fields (JSON)", description="Extra product fields (price, currency, image_url, availability, condition, url, brand, ...).",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})

async def _create_product(c, token, secret):
    data = {"retailer_id": c.retailer_id, "name": c.name}
    for k, v in (_parse_json_field(c.fields_json, "Additional Fields") or {}).items():
        data[k] = json.dumps(v) if isinstance(v, (dict, list)) else v
    return await _meta_request(token, "POST", f"/{c.catalog_id}/products", data=data, app_secret=secret, action_name="create_product")

_reg(MetaCreateProductConfig, "create_product", _create_product)


class MetaItemsBatchConfig(BaseModel):
    """Batch create/update/delete catalog items."""
    operation: Literal["items_batch"] = Field("items_batch",
        json_schema_extra=_op_extra("items_batch", "Items Batch", "Catalog"), title="Items Batch")
    catalog_id: str = Field(..., title="Catalog ID", description="Catalog ID.")
    item_type: str = Field("PRODUCT_ITEM", title="Item Type", description="Type of item being batched.",
        json_schema_extra={"enum": ["PRODUCT_ITEM"], "x-enum-searchable": True})
    requests_json: str = Field(..., title="Requests (JSON)", description="JSON array of {method, data} batch requests.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})
    allow_upsert: Optional[str] = Field(None, title="Allow Upsert", description="Whether to allow upsert.",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})

async def _items_batch(c, token, secret):
    requests = _parse_json_field(c.requests_json, "Requests")
    data = {"item_type": c.item_type, "requests": json.dumps(requests)}
    if c.allow_upsert is not None:
        data["allow_upsert"] = c.allow_upsert
    return await _meta_request(token, "POST", f"/{c.catalog_id}/items_batch", data=data, app_secret=secret, action_name="items_batch")

_reg(MetaItemsBatchConfig, "items_batch", _items_batch)


class MetaListProductSetsConfig(BaseModel):
    """List product sets in a catalog."""
    operation: Literal["list_product_sets"] = Field("list_product_sets",
        json_schema_extra=_op_extra("list_product_sets", "List Product Sets", "Catalog"), title="List Product Sets")
    catalog_id: str = Field(..., title="Catalog ID", description="Catalog ID.")
    fields: str = Field("id,name,product_count,filter", title="Fields", description="Comma-separated fields to return.")
    limit: Optional[int] = Field(25, title="Limit", description="Max results.")

async def _list_product_sets(c, token, secret):
    params = {"fields": c.fields}
    if c.limit is not None:
        params["limit"] = c.limit
    return await _meta_request(token, "GET", f"/{c.catalog_id}/product_sets", params=params, app_secret=secret, action_name="list_product_sets")

_reg(MetaListProductSetsConfig, "list_product_sets", _list_product_sets)


class MetaCreateProductSetConfig(BaseModel):
    """Create a product set in a catalog."""
    operation: Literal["create_product_set"] = Field("create_product_set",
        json_schema_extra=_op_extra("create_product_set", "Create Product Set", "Catalog"), title="Create Product Set")
    catalog_id: str = Field(..., title="Catalog ID", description="Catalog ID.")
    name: str = Field(..., title="Name", description="Product set name.")
    filter_json: str = Field("{}", title="Filter (JSON)", description="Optional product set filter spec.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})

async def _create_product_set(c, token, secret):
    data = {"name": c.name}
    filt = _parse_json_field(c.filter_json, "Filter")
    if filt:
        data["filter"] = json.dumps(filt)
    return await _meta_request(token, "POST", f"/{c.catalog_id}/product_sets", data=data, app_secret=secret, action_name="create_product_set")

_reg(MetaCreateProductSetConfig, "create_product_set", _create_product_set)


# ---- Lead Ads ----

class MetaListLeadgenFormsConfig(BaseModel):
    """List lead gen forms on a Page."""
    operation: Literal["list_leadgen_forms"] = Field("list_leadgen_forms",
        json_schema_extra=_op_extra("list_leadgen_forms", "List Lead Forms", "Lead Ads"), title="List Lead Forms")
    page_id: str = Field(..., title="Page ID", description="Facebook Page ID.")
    fields: str = Field("id,name,status,leads_count,created_time", title="Fields", description="Comma-separated fields.")
    limit: Optional[int] = Field(None, title="Limit", description="Max results to return.")

async def _list_leadgen_forms(c, token, secret):
    # GET /{page}/leadgen_forms requires the Page's own access token (#190 with a user token).
    page_token, err = await _resolve_page_token(token, c.page_id, secret)
    if err:
        return err
    params = {"fields": c.fields}
    if c.limit is not None:
        params["limit"] = c.limit
    return await _meta_request(page_token, "GET", f"/{c.page_id}/leadgen_forms", params=params, app_secret=secret, action_name="list_leadgen_forms")

_reg(MetaListLeadgenFormsConfig, "list_leadgen_forms", _list_leadgen_forms)


_reg(*_make_object_get("get_leadgen_form", "Get Lead Form", "Form ID",
    "id,name,status,questions,leads_count,created_time,privacy_policy_url", "Lead Ads"))


class MetaCreateLeadgenFormConfig(BaseModel):
    """Create a lead gen form on a Page."""
    operation: Literal["create_leadgen_form"] = Field("create_leadgen_form",
        json_schema_extra=_op_extra("create_leadgen_form", "Create Lead Form", "Lead Ads"), title="Create Lead Form")
    page_id: str = Field(..., title="Page ID", description="Facebook Page ID.")
    name: str = Field(..., title="Name", description="Form name.")
    questions_json: str = Field("[]", title="Questions (JSON)", description="JSON array of question objects.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})
    fields_json: str = Field("{}", title="Additional Fields (JSON)", description="privacy_policy, follow_up_action_url, thank_you_page, etc.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})

async def _create_leadgen_form(c, token, secret):
    data = {"name": c.name, "questions": json.dumps(_parse_json_field(c.questions_json, "Questions") or [])}
    for k, v in (_parse_json_field(c.fields_json, "Additional Fields") or {}).items():
        data[k] = json.dumps(v) if isinstance(v, (dict, list)) else v
    return await _meta_request(token, "POST", f"/{c.page_id}/leadgen_forms", data=data, app_secret=secret, action_name="create_leadgen_form")

_reg(MetaCreateLeadgenFormConfig, "create_leadgen_form", _create_leadgen_form)


class MetaArchiveLeadgenFormConfig(BaseModel):
    """Archive a lead gen form (no hard delete exists)."""
    operation: Literal["archive_leadgen_form"] = Field("archive_leadgen_form",
        json_schema_extra=_op_extra("archive_leadgen_form", "Archive Lead Form", "Lead Ads"), title="Archive Lead Form")
    form_id: str = Field(..., title="Form ID", description="Lead gen form ID.")
    status: str = Field("ARCHIVED", title="Status", description="Form status.",
        json_schema_extra={"enum": ["ACTIVE", "ARCHIVED"], "x-enum-searchable": True})

async def _archive_leadgen_form(c, token, secret):
    return await _meta_request(token, "POST", f"/{c.form_id}", data={"status": c.status}, app_secret=secret, action_name="archive_leadgen_form")

_reg(MetaArchiveLeadgenFormConfig, "archive_leadgen_form", _archive_leadgen_form)


class MetaSubscribePageWebhooksConfig(BaseModel):
    """Subscribe the app to a Page's webhook fields (e.g. leadgen) so the
    on_leadgen trigger receives events. POST /{page_id}/subscribed_apps requires
    pages_manage_metadata + the Page's own access token."""
    operation: Literal["subscribe_page_webhooks"] = Field("subscribe_page_webhooks",
        json_schema_extra=_op_extra("subscribe_page_webhooks", "Subscribe Page Webhooks", "Lead Ads"),
        title="Subscribe Page Webhooks")
    page_id: str = Field(..., title="Page ID", description="Facebook Page ID.")
    subscribed_fields: str = Field(
        "leadgen", title="Subscribed Fields",
        description="Comma-separated webhook fields to subscribe to (e.g. leadgen).")

async def _subscribe_page_webhooks(c, token, secret):
    page_token, err = await _resolve_page_token(token, c.page_id, secret)
    if err:
        return err
    return await _meta_request(page_token, "POST", f"/{c.page_id}/subscribed_apps",
                               data={"subscribed_fields": c.subscribed_fields}, app_secret=secret,
                               action_name="subscribe_page_webhooks")

_reg(MetaSubscribePageWebhooksConfig, "subscribe_page_webhooks", _subscribe_page_webhooks)


class MetaListLeadsConfig(BaseModel):
    """List leads for a lead gen form."""
    operation: Literal["list_leads"] = Field("list_leads",
        json_schema_extra=_op_extra("list_leads", "List Leads", "Lead Ads"), title="List Leads")
    form_id: str = Field(..., title="Form ID", description="Lead gen form ID.")
    fields: str = Field("id,created_time,ad_id,form_id,field_data,is_organic,platform", title="Fields", description="Comma-separated fields.")
    filtering_json: str = Field("", title="Filtering (JSON)", description="Optional filtering array.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})
    limit: Optional[int] = Field(None, title="Limit", description="Max results to return.")

async def _list_leads(c, token, secret):
    params = {"fields": c.fields}
    filtering = _parse_json_field(c.filtering_json, "Filtering")
    if filtering is not None:
        params["filtering"] = json.dumps(filtering)
    if c.limit is not None:
        params["limit"] = c.limit
    return await _meta_request(token, "GET", f"/{c.form_id}/leads", params=params, app_secret=secret, action_name="list_leads")

_reg(MetaListLeadsConfig, "list_leads", _list_leads)


_reg(*_make_object_get("get_lead", "Get Lead", "Lead ID",
    "id,created_time,ad_id,form_id,field_data,custom_disclaimer_responses", "Lead Ads"))


class MetaListAdLeadsConfig(BaseModel):
    """List leads generated by a specific ad."""
    operation: Literal["list_ad_leads"] = Field("list_ad_leads",
        json_schema_extra=_op_extra("list_ad_leads", "List Ad Leads", "Lead Ads"), title="List Ad Leads")
    ad_id: str = Field(..., title="Ad ID", description="Ad ID.")
    fields: str = Field("id,created_time,field_data", title="Fields", description="Comma-separated fields.")
    limit: Optional[int] = Field(None, title="Limit", description="Max results to return.")

async def _list_ad_leads(c, token, secret):
    params = {"fields": c.fields}
    if c.limit is not None:
        params["limit"] = c.limit
    return await _meta_request(token, "GET", f"/{c.ad_id}/leads", params=params, app_secret=secret, action_name="list_ad_leads")

_reg(MetaListAdLeadsConfig, "list_ad_leads", _list_ad_leads)


class MetaCreateTestLeadConfig(BaseModel):
    """Create a test lead for a lead gen form."""
    operation: Literal["create_test_lead"] = Field("create_test_lead",
        json_schema_extra=_op_extra("create_test_lead", "Create Test Lead", "Lead Ads"), title="Create Test Lead")
    form_id: str = Field(..., title="Form ID", description="Lead gen form ID.")
    field_data_json: str = Field("", title="Field Data (JSON)", description="Optional JSON array of {name, values} objects.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})

async def _create_test_lead(c, token, secret):
    data = {}
    field_data = _parse_json_field(c.field_data_json, "Field Data")
    if field_data is not None:
        data["field_data"] = json.dumps(field_data)
    return await _meta_request(token, "POST", f"/{c.form_id}/test_leads", data=data, app_secret=secret, action_name="create_test_lead")

_reg(MetaCreateTestLeadConfig, "create_test_lead", _create_test_lead)


class MetaListTestLeadsConfig(BaseModel):
    """List test leads for a lead gen form."""
    operation: Literal["list_test_leads"] = Field("list_test_leads",
        json_schema_extra=_op_extra("list_test_leads", "List Test Leads", "Lead Ads"), title="List Test Leads")
    form_id: str = Field(..., title="Form ID", description="Lead gen form ID.")
    fields: str = Field("id,created_time,field_data", title="Fields", description="Comma-separated fields.")
    limit: Optional[int] = Field(None, title="Limit", description="Max results to return.")

async def _list_test_leads(c, token, secret):
    params = {"fields": c.fields}
    if c.limit is not None:
        params["limit"] = c.limit
    return await _meta_request(token, "GET", f"/{c.form_id}/test_leads", params=params, app_secret=secret, action_name="list_test_leads")

_reg(MetaListTestLeadsConfig, "list_test_leads", _list_test_leads)


# ============================================================================
# Node
# ============================================================================


# ---- Custom Conversions ----
_reg(*_make_account_list("list_custom_conversions", "List Custom Conversions", "customconversions",
    "id,name,custom_event_type,rule,default_conversion_value,pixel", "Custom Conversions", with_status=False))


class MetaCustomConversionCreateConfig(BaseModel):
    """Create a custom conversion on an ad account."""
    operation: Literal["create_custom_conversion"] = Field("create_custom_conversion",
        json_schema_extra=_op_extra("create_custom_conversion", "Create Custom Conversion", "Custom Conversions"),
        title="Create Custom Conversion")
    ad_account_id: str = Field(..., title="Ad Account", description="Ad account ID (act_...).", json_schema_extra=_ACCOUNT_DYNAMIC)
    name: str = Field(..., title="Name", description="Custom conversion name.")
    custom_event_type: str = Field(..., title="Custom Event Type",
        description="Standard event type (e.g. PURCHASE, LEAD, OTHER).")
    fields_json: str = Field("{}", title="Additional Fields (JSON)",
        description="Optional extra fields: rule (dict), event_source_id/pixel_id, default_conversion_value, description.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})
async def _create_custom_conversion(c, token, secret):
    data = {"name": c.name, "custom_event_type": c.custom_event_type}
    for k, v in (_parse_json_field(c.fields_json, "Additional Fields") or {}).items():
        data[k] = json.dumps(v) if isinstance(v, (dict, list)) else v
    return await _meta_request(token, "POST", f"/{_acct(c.ad_account_id)}/customconversions", data=data,
        app_secret=secret, action_name="create_custom_conversion")
_reg(MetaCustomConversionCreateConfig, "create_custom_conversion", _create_custom_conversion)


_reg(*_make_object_get("get_custom_conversion", "Get Custom Conversion", "Custom Conversion ID",
    "id,name,custom_event_type,rule,default_conversion_value,is_archived,creation_time", "Custom Conversions"))


class MetaCustomConversionUpdateConfig(BaseModel):
    """Update a custom conversion."""
    operation: Literal["update_custom_conversion"] = Field("update_custom_conversion",
        json_schema_extra=_op_extra("update_custom_conversion", "Update Custom Conversion", "Custom Conversions"),
        title="Update Custom Conversion")
    custom_conversion_id: str = Field(..., title="Custom Conversion ID", description="Custom conversion ID.")
    fields_json: str = Field("{}", title="Fields to Update (JSON)", description="Fields to update.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})
async def _update_custom_conversion(c, token, secret):
    data = {}
    for k, v in (_parse_json_field(c.fields_json, "Fields to Update") or {}).items():
        data[k] = json.dumps(v) if isinstance(v, (dict, list)) else v
    return await _meta_request(token, "POST", f"/{c.custom_conversion_id}", data=data,
        app_secret=secret, action_name="update_custom_conversion")
_reg(MetaCustomConversionUpdateConfig, "update_custom_conversion", _update_custom_conversion)


_reg(*_make_object_delete("delete_custom_conversion", "Delete Custom Conversion", "Custom Conversion ID", "Custom Conversions"))


class MetaCustomConversionStatsConfig(BaseModel):
    """Get stats for a custom conversion."""
    operation: Literal["get_custom_conversion_stats"] = Field("get_custom_conversion_stats",
        json_schema_extra=_op_extra("get_custom_conversion_stats", "Get Custom Conversion Stats", "Custom Conversions"),
        title="Get Custom Conversion Stats")
    custom_conversion_id: str = Field(..., title="Custom Conversion ID", description="Custom conversion ID.")
    aggregation: Optional[str] = Field(None, title="Aggregation", description="Aggregation window (optional).")
    start_time: Optional[str] = Field(None, title="Start Time", description="Start time (optional).")
    end_time: Optional[str] = Field(None, title="End Time", description="End time (optional).")
async def _get_custom_conversion_stats(c, token, secret):
    params = {}
    if c.aggregation:
        params["aggregation"] = c.aggregation
    if c.start_time:
        params["start_time"] = c.start_time
    if c.end_time:
        params["end_time"] = c.end_time
    return await _meta_request(token, "GET", f"/{c.custom_conversion_id}/stats", params=params,
        app_secret=secret, action_name="get_custom_conversion_stats")
_reg(MetaCustomConversionStatsConfig, "get_custom_conversion_stats", _get_custom_conversion_stats)


# ---- Product Feeds ----
class MetaProductFeedListConfig(BaseModel):
    """List product feeds for a catalog."""
    operation: Literal["list_product_feeds"] = Field("list_product_feeds",
        json_schema_extra=_op_extra("list_product_feeds", "List Product Feeds", "Catalog"),
        title="List Product Feeds")
    catalog_id: str = Field(..., title="Catalog ID", description="Product catalog ID.")
    fields: str = Field("id,name,schedule,latest_upload,product_count", title="Fields",
        description="Comma-separated fields to return.")
    limit: Optional[int] = Field(None, title="Limit", description="Max results per page.")
async def _list_product_feeds(c, token, secret):
    params = {"fields": c.fields}
    if c.limit is not None:
        params["limit"] = c.limit
    return await _meta_request(token, "GET", f"/{c.catalog_id}/product_feeds", params=params,
        app_secret=secret, action_name="list_product_feeds")
_reg(MetaProductFeedListConfig, "list_product_feeds", _list_product_feeds)


class MetaProductFeedCreateConfig(BaseModel):
    """Create a product feed on a catalog."""
    operation: Literal["create_product_feed"] = Field("create_product_feed",
        json_schema_extra=_op_extra("create_product_feed", "Create Product Feed", "Catalog"),
        title="Create Product Feed")
    catalog_id: str = Field(..., title="Catalog ID", description="Product catalog ID.")
    name: str = Field(..., title="Name", description="Product feed name.")
    fields_json: str = Field("{}", title="Additional Fields (JSON)",
        description="Optional extra fields: schedule ({interval,url,hour}), update_schedule, default_currency, quoted_fields_mode.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})
async def _create_product_feed(c, token, secret):
    data = {"name": c.name}
    for k, v in (_parse_json_field(c.fields_json, "Additional Fields") or {}).items():
        data[k] = json.dumps(v) if isinstance(v, (dict, list)) else v
    return await _meta_request(token, "POST", f"/{c.catalog_id}/product_feeds", data=data,
        app_secret=secret, action_name="create_product_feed")
_reg(MetaProductFeedCreateConfig, "create_product_feed", _create_product_feed)


_reg(*_make_object_get("get_product_feed", "Get Product Feed", "Product Feed ID",
    "id,name,schedule,latest_upload,product_count,quoted_fields_mode", "Catalog"))


class MetaProductFeedUpdateConfig(BaseModel):
    """Update a product feed."""
    operation: Literal["update_product_feed"] = Field("update_product_feed",
        json_schema_extra=_op_extra("update_product_feed", "Update Product Feed", "Catalog"),
        title="Update Product Feed")
    product_feed_id: str = Field(..., title="Product Feed ID", description="Product feed ID.")
    fields_json: str = Field("{}", title="Fields to Update (JSON)", description="Fields to update.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})
async def _update_product_feed(c, token, secret):
    data = {}
    for k, v in (_parse_json_field(c.fields_json, "Fields to Update") or {}).items():
        data[k] = json.dumps(v) if isinstance(v, (dict, list)) else v
    return await _meta_request(token, "POST", f"/{c.product_feed_id}", data=data,
        app_secret=secret, action_name="update_product_feed")
_reg(MetaProductFeedUpdateConfig, "update_product_feed", _update_product_feed)


_reg(*_make_object_delete("delete_product_feed", "Delete Product Feed", "Product Feed ID", "Catalog"))


class MetaFeedUploadListConfig(BaseModel):
    """List uploads for a product feed."""
    operation: Literal["list_feed_uploads"] = Field("list_feed_uploads",
        json_schema_extra=_op_extra("list_feed_uploads", "List Feed Uploads", "Catalog"),
        title="List Feed Uploads")
    product_feed_id: str = Field(..., title="Product Feed ID", description="Product feed ID.")
    fields: str = Field("id,start_time,end_time,error_count,warning_count,num_detected_items", title="Fields",
        description="Comma-separated fields to return.")
    limit: Optional[int] = Field(None, title="Limit", description="Max results per page.")
async def _list_feed_uploads(c, token, secret):
    params = {"fields": c.fields}
    if c.limit is not None:
        params["limit"] = c.limit
    return await _meta_request(token, "GET", f"/{c.product_feed_id}/uploads", params=params,
        app_secret=secret, action_name="list_feed_uploads")
_reg(MetaFeedUploadListConfig, "list_feed_uploads", _list_feed_uploads)


class MetaFeedUploadCreateConfig(BaseModel):
    """Trigger an upload for a product feed."""
    operation: Literal["create_feed_upload"] = Field("create_feed_upload",
        json_schema_extra=_op_extra("create_feed_upload", "Create Feed Upload", "Catalog"),
        title="Create Feed Upload")
    product_feed_id: str = Field(..., title="Product Feed ID", description="Product feed ID.")
    url: Optional[str] = Field(None, title="Feed File URL", description="Feed file URL to upload (optional).")
    fields_json: str = Field("{}", title="Additional Fields (JSON)",
        description="Optional extra fields: url, update_only.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})
async def _create_feed_upload(c, token, secret):
    data = {}
    for k, v in (_parse_json_field(c.fields_json, "Additional Fields") or {}).items():
        data[k] = json.dumps(v) if isinstance(v, (dict, list)) else v
    if c.url:
        data["url"] = c.url
    return await _meta_request(token, "POST", f"/{c.product_feed_id}/uploads", data=data,
        app_secret=secret, action_name="create_feed_upload")
_reg(MetaFeedUploadCreateConfig, "create_feed_upload", _create_feed_upload)


_reg(*_make_object_get("get_feed_upload", "Get Feed Upload", "Upload ID",
    "id,start_time,end_time,error_count,warning_count,num_detected_items,num_persisted_items", "Catalog"))


class MetaFeedUploadErrorsConfig(BaseModel):
    """List errors for a product feed upload."""
    operation: Literal["get_feed_upload_errors"] = Field("get_feed_upload_errors",
        json_schema_extra=_op_extra("get_feed_upload_errors", "Get Feed Upload Errors", "Catalog"),
        title="Get Feed Upload Errors")
    upload_id: str = Field(..., title="Upload ID", description="Feed upload ID.")
    limit: Optional[int] = Field(None, title="Limit", description="Max results per page.")
async def _get_feed_upload_errors(c, token, secret):
    params = {}
    if c.limit is not None:
        params["limit"] = c.limit
    return await _meta_request(token, "GET", f"/{c.upload_id}/errors", params=params,
        app_secret=secret, action_name="get_feed_upload_errors")
_reg(MetaFeedUploadErrorsConfig, "get_feed_upload_errors", _get_feed_upload_errors)


# ---- Catalog Advanced ----

class MetaGetCatalogDiagnosticsConfig(BaseModel):
    """Read setup/quality diagnostics for a product catalog."""
    operation: Literal["get_catalog_diagnostics"] = Field("get_catalog_diagnostics",
        json_schema_extra=_op_extra("get_catalog_diagnostics", "Get Catalog Diagnostics", "Catalog"), title="Get Catalog Diagnostics")
    catalog_id: str = Field(..., title="Catalog ID", description="The product catalog ID.")
    affected_channels: Optional[str] = Field(None, title="Affected Channels", description="Comma-separated channels filter (e.g. ADS,MARKETPLACE).")
    affected_features: Optional[str] = Field(None, title="Affected Features", description="Comma-separated features filter (e.g. AUGMENTED_REALITY).")
    severities: Optional[str] = Field(None, title="Severities", description="Comma-separated severities filter (e.g. MUST_FIX,OPPORTUNITY).")


async def _get_catalog_diagnostics(c, token, secret):
    params = {}
    if c.affected_channels:
        params["affected_channels"] = c.affected_channels
    if c.affected_features:
        params["affected_features"] = c.affected_features
    if c.severities:
        params["severities"] = c.severities
    return await _meta_request(token, "GET", f"/{c.catalog_id}/diagnostics", params=params,
                               app_secret=secret, action_name="get_catalog_diagnostics")


class MetaGetCatalogEventStatsConfig(BaseModel):
    """Read event stats (matched/unmatched content) for a catalog."""
    operation: Literal["get_catalog_event_stats"] = Field("get_catalog_event_stats",
        json_schema_extra=_op_extra("get_catalog_event_stats", "Get Catalog Event Stats", "Catalog"), title="Get Catalog Event Stats")
    catalog_id: str = Field(..., title="Catalog ID", description="The product catalog ID.")
    breakdowns: Optional[str] = Field(None, title="Breakdowns", description="Comma-separated breakdowns (e.g. AGGREGATION_TYPE,EVENT).")


async def _get_catalog_event_stats(c, token, secret):
    params = {}
    if c.breakdowns:
        params["breakdowns"] = c.breakdowns
    return await _meta_request(token, "GET", f"/{c.catalog_id}/event_stats", params=params,
                               app_secret=secret, action_name="get_catalog_event_stats")


class MetaListExternalEventSourcesConfig(BaseModel):
    """List pixels/datasets linked to a catalog as external event sources."""
    operation: Literal["list_external_event_sources"] = Field("list_external_event_sources",
        json_schema_extra=_op_extra("list_external_event_sources", "List External Event Sources", "Catalog"), title="List External Event Sources")
    catalog_id: str = Field(..., title="Catalog ID", description="The product catalog ID.")
    fields: str = Field("id,name,source_type", title="Fields", description="Comma-separated fields.")
    limit: Optional[str] = Field("100", title="Limit", description="Max sources per page.")


async def _list_external_event_sources(c, token, secret):
    return await _meta_request(token, "GET", f"/{c.catalog_id}/external_event_sources",
                               params={"fields": c.fields, "limit": c.limit},
                               app_secret=secret, action_name="list_external_event_sources")


class MetaAddExternalEventSourceConfig(BaseModel):
    """Link pixels/datasets to a catalog as external event sources."""
    operation: Literal["add_external_event_source"] = Field("add_external_event_source",
        json_schema_extra=_op_extra("add_external_event_source", "Add External Event Source", "Catalog"), title="Add External Event Source")
    catalog_id: str = Field(..., title="Catalog ID", description="The product catalog ID.")
    external_event_sources_json: str = Field(..., title="External Event Sources (JSON)",
        description='JSON list of pixel/dataset IDs, e.g. ["1234567890"].',
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})


async def _add_external_event_source(c, token, secret):
    sources = _parse_json_field(c.external_event_sources_json, "External Event Sources")
    data = {"external_event_sources": json.dumps(sources)}
    return await _meta_request(token, "POST", f"/{c.catalog_id}/external_event_sources", data=data,
                               app_secret=secret, action_name="add_external_event_source")


class MetaCreateProductAudienceConfig(BaseModel):
    """Create a product audience (dynamic retargeting) from a product set."""
    operation: Literal["create_product_audience"] = Field("create_product_audience",
        json_schema_extra=_op_extra("create_product_audience", "Create Product Audience", "Catalog"), title="Create Product Audience")
    ad_account_id: str = Field(..., title="Ad Account", description="Ad account ID (act_...).", json_schema_extra=_ACCOUNT_DYNAMIC)
    name: str = Field(..., title="Name", description="Product audience name.")
    product_set_id: str = Field(..., title="Product Set ID", description="The product set to build the audience from.")
    fields_json: str = Field("{}", title="Additional Fields (JSON)",
        description='Optional extra fields, e.g. {"inclusions":[...],"exclusions":[...],"retention_seconds":86400,"description":"..."}.',
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})


async def _create_product_audience(c, token, secret):
    data = {"name": c.name, "product_set_id": c.product_set_id}
    for k, v in (_parse_json_field(c.fields_json, "Additional Fields") or {}).items():
        data[k] = json.dumps(v) if isinstance(v, (dict, list)) else v
    return await _meta_request(token, "POST", f"/{_acct(c.ad_account_id)}/product_audiences", data=data,
                               app_secret=secret, action_name="create_product_audience")


class MetaLocalizedItemsBatchConfig(BaseModel):
    """Batch upsert/delete localized catalog items (per-locale overrides)."""
    operation: Literal["localized_items_batch"] = Field("localized_items_batch",
        json_schema_extra=_op_extra("localized_items_batch", "Localized Items Batch", "Catalog"), title="Localized Items Batch")
    catalog_id: str = Field(..., title="Catalog ID", description="The product catalog ID.")
    item_type: str = Field("PRODUCT_ITEM", title="Item Type", description="Type of item being batched (required by Meta).",
        json_schema_extra={"enum": ["PRODUCT_ITEM"], "x-enum-searchable": True})
    requests_json: str = Field(..., title="Requests (JSON)",
        description='JSON array of batch requests, e.g. [{"method":"UPDATE","data":{...}}].',
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})
    fields_json: str = Field("{}", title="Additional Fields (JSON)",
        description='Optional extra fields, e.g. {"allow_upsert":true}.',
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})


async def _localized_items_batch(c, token, secret):
    requests = _parse_json_field(c.requests_json, "Requests")
    data = {"item_type": c.item_type, "requests": json.dumps(requests)}
    for k, v in (_parse_json_field(c.fields_json, "Additional Fields") or {}).items():
        data[k] = json.dumps(v) if isinstance(v, (dict, list)) else v
    return await _meta_request(token, "POST", f"/{c.catalog_id}/localized_items_batch", data=data,
                               app_secret=secret, action_name="localized_items_batch")


_reg(MetaGetCatalogDiagnosticsConfig, "get_catalog_diagnostics", _get_catalog_diagnostics)
_reg(MetaGetCatalogEventStatsConfig, "get_catalog_event_stats", _get_catalog_event_stats)
_reg(MetaListExternalEventSourcesConfig, "list_external_event_sources", _list_external_event_sources)
_reg(MetaAddExternalEventSourceConfig, "add_external_event_source", _add_external_event_source)
_reg(MetaCreateProductAudienceConfig, "create_product_audience", _create_product_audience)
_reg(MetaLocalizedItemsBatchConfig, "localized_items_batch", _localized_items_batch)


# ---- Ad Account Admin ----

class MetaListAdAccountUsersConfig(BaseModel):
    """List users assigned to an ad account (with their tasks/roles)."""
    operation: Literal["list_ad_account_users"] = Field("list_ad_account_users",
        json_schema_extra=_op_extra("list_ad_account_users", "List Ad Account Users", "Ad Account"), title="List Ad Account Users")
    ad_account_id: str = Field(..., title="Ad Account", description="Ad account ID (act_...).", json_schema_extra=_ACCOUNT_DYNAMIC)
    business: str = Field(..., title="Business ID", description="The business that scopes the assigned users.")
    fields: str = Field("id,name,tasks", title="Fields", description="Comma-separated fields.")
    limit: Optional[str] = Field("100", title="Limit", description="Max users per page.")


async def _list_ad_account_users(c, token, secret):
    return await _meta_request(token, "GET", f"/{_acct(c.ad_account_id)}/assigned_users",
                               params={"business": c.business, "fields": c.fields, "limit": c.limit},
                               app_secret=secret, action_name="list_ad_account_users")


class MetaAssignAdAccountUserConfig(BaseModel):
    """Assign a user to an ad account with a set of tasks."""
    operation: Literal["assign_ad_account_user"] = Field("assign_ad_account_user",
        json_schema_extra=_op_extra("assign_ad_account_user", "Assign Ad Account User", "Ad Account"), title="Assign Ad Account User")
    ad_account_id: str = Field(..., title="Ad Account", description="Ad account ID (act_...).", json_schema_extra=_ACCOUNT_DYNAMIC)
    user: str = Field(..., title="User ID", description="The user (person) ID to assign.")
    tasks_json: str = Field(..., title="Tasks (JSON)",
        description='JSON list of tasks, e.g. ["ANALYZE","ADVERTISE","MANAGE"].',
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})


async def _assign_ad_account_user(c, token, secret):
    tasks = _parse_json_field(c.tasks_json, "Tasks")
    data = {"user": c.user, "tasks": json.dumps(tasks)}
    return await _meta_request(token, "POST", f"/{_acct(c.ad_account_id)}/assigned_users", data=data,
                               app_secret=secret, action_name="assign_ad_account_user")


class MetaRemoveAdAccountUserConfig(BaseModel):
    """Remove a user's assignment from an ad account."""
    operation: Literal["remove_ad_account_user"] = Field("remove_ad_account_user",
        json_schema_extra=_op_extra("remove_ad_account_user", "Remove Ad Account User", "Ad Account"), title="Remove Ad Account User")
    ad_account_id: str = Field(..., title="Ad Account", description="Ad account ID (act_...).", json_schema_extra=_ACCOUNT_DYNAMIC)
    user: str = Field(..., title="User ID", description="The user (person) ID to remove.")


async def _remove_ad_account_user(c, token, secret):
    data = {"user": c.user}
    return await _meta_request(token, "DELETE", f"/{_acct(c.ad_account_id)}/assigned_users", data=data,
                               app_secret=secret, action_name="remove_ad_account_user")


class MetaGetTargetingSentenceLinesConfig(BaseModel):
    """Get human-readable targeting summary lines for a targeting spec."""
    operation: Literal["get_targeting_sentence_lines"] = Field("get_targeting_sentence_lines",
        json_schema_extra=_op_extra("get_targeting_sentence_lines", "Get Targeting Sentence Lines", "Ad Account"), title="Get Targeting Sentence Lines")
    ad_account_id: str = Field(..., title="Ad Account", description="Ad account ID (act_...).", json_schema_extra=_ACCOUNT_DYNAMIC)
    targeting_spec_json: str = Field(..., title="Targeting Spec (JSON)",
        description='The targeting spec object, e.g. {"geo_locations":{"countries":["US"]}}.',
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})


async def _get_targeting_sentence_lines(c, token, secret):
    spec = _parse_json_field(c.targeting_spec_json, "Targeting Spec")
    return await _meta_request(token, "GET", f"/{_acct(c.ad_account_id)}/targetingsentencelines",
                               params={"targeting_spec": json.dumps(spec)},
                               app_secret=secret, action_name="get_targeting_sentence_lines")


class MetaCreatePublisherBlockListConfig(BaseModel):
    """Create a publisher block list under an ad account."""
    operation: Literal["create_publisher_block_list"] = Field("create_publisher_block_list",
        json_schema_extra=_op_extra("create_publisher_block_list", "Create Publisher Block List", "Ad Account"), title="Create Publisher Block List")
    ad_account_id: str = Field(..., title="Ad Account", description="Ad account ID (act_...).", json_schema_extra=_ACCOUNT_DYNAMIC)
    name: str = Field(..., title="Name", description="Publisher block list name.")


async def _create_publisher_block_list(c, token, secret):
    data = {"name": c.name}
    return await _meta_request(token, "POST", f"/{_acct(c.ad_account_id)}/publisher_block_lists", data=data,
                               app_secret=secret, action_name="create_publisher_block_list")


_reg(MetaListAdAccountUsersConfig, "list_ad_account_users", _list_ad_account_users)
_reg(MetaAssignAdAccountUserConfig, "assign_ad_account_user", _assign_ad_account_user)
_reg(MetaRemoveAdAccountUserConfig, "remove_ad_account_user", _remove_ad_account_user)
_reg(*_make_account_list("list_promote_pages", "List Promote Pages", "promote_pages", "id,name", "Ad Account", with_status=False))
_reg(MetaGetTargetingSentenceLinesConfig, "get_targeting_sentence_lines", _get_targeting_sentence_lines)
_reg(*_make_account_list("list_minimum_budgets", "List Minimum Budgets", "minimum_budgets",
     "currency,min_daily_budget_imp,min_daily_budget_high_freq,min_daily_budget_low_freq", "Ad Account", with_status=False))
_reg(*_make_account_list("list_publisher_block_lists", "List Publisher Block Lists", "publisher_block_lists",
     "id,name,is_auto_blocking_on", "Ad Account", with_status=False))
_reg(MetaCreatePublisherBlockListConfig, "create_publisher_block_list", _create_publisher_block_list)
_reg(*_make_account_list("get_dsa_recommendations", "Get DSA Recommendations", "dsa_recommendations",
     "beneficiary,payer", "Ad Account", with_status=False))
_reg(*_make_account_list("get_custom_audience_tos", "Get Custom Audience TOS", "customaudiencestos",
     "id", "Ad Account", with_status=False))


# ---- Automated Ad Rules ----
_reg(*_make_account_list("list_ad_rules", "List Ad Rules", "adrules_library",
    "id,name,status,evaluation_spec,execution_spec,schedule_spec", "Ad Rules", with_status=False))


class MetaAdRuleCreateConfig(BaseModel):
    """Create an automated ad rule in the account's rules library."""
    operation: Literal["create_ad_rule"] = Field("create_ad_rule",
        json_schema_extra=_op_extra("create_ad_rule", "Create Ad Rule", "Ad Rules"), title="Create Ad Rule")
    ad_account_id: str = Field(..., title="Ad Account", description="Ad account ID (act_...).", json_schema_extra=_ACCOUNT_DYNAMIC)
    name: str = Field(..., title="Name", description="Ad rule name.")
    fields_json: str = Field("{}", title="Additional Fields (JSON)",
        description="Rule spec: evaluation_spec {evaluation_type,filters}, execution_spec {execution_type,execution_options}, schedule_spec, status.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})


async def _create_ad_rule(c, token, secret):
    data = {"name": c.name}
    for k, v in (_parse_json_field(c.fields_json, "Additional Fields") or {}).items():
        data[k] = json.dumps(v) if isinstance(v, (dict, list)) else v
    return await _meta_request(token, "POST", f"/{_acct(c.ad_account_id)}/adrules_library", data=data, app_secret=secret, action_name="create_ad_rule")
_reg(MetaAdRuleCreateConfig, "create_ad_rule", _create_ad_rule)


_reg(*_make_object_get("get_ad_rule", "Get Ad Rule", "Ad Rule ID",
    "id,name,status,evaluation_spec,execution_spec,schedule_spec,created_time", "Ad Rules"))


class MetaAdRuleUpdateConfig(BaseModel):
    """Update an automated ad rule."""
    operation: Literal["update_ad_rule"] = Field("update_ad_rule",
        json_schema_extra=_op_extra("update_ad_rule", "Update Ad Rule", "Ad Rules"), title="Update Ad Rule")
    ad_rule_id: str = Field(..., title="Ad Rule ID", description="Ad rule ID.")
    fields_json: str = Field("{}", title="Fields (JSON)", description="Fields to update.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})


async def _update_ad_rule(c, token, secret):
    data = {}
    for k, v in (_parse_json_field(c.fields_json, "Fields") or {}).items():
        data[k] = json.dumps(v) if isinstance(v, (dict, list)) else v
    return await _meta_request(token, "POST", f"/{c.ad_rule_id}", data=data, app_secret=secret, action_name="update_ad_rule")
_reg(MetaAdRuleUpdateConfig, "update_ad_rule", _update_ad_rule)


_reg(*_make_object_delete("delete_ad_rule", "Delete Ad Rule", "Ad Rule ID", "Ad Rules"))


class MetaAdRuleHistoryConfig(BaseModel):
    """Get the execution history of an automated ad rule."""
    operation: Literal["get_ad_rule_history"] = Field("get_ad_rule_history",
        json_schema_extra=_op_extra("get_ad_rule_history", "Get Ad Rule History", "Ad Rules"), title="Get Ad Rule History")
    ad_rule_id: str = Field(..., title="Ad Rule ID", description="Ad rule ID.")
    limit: Optional[int] = Field(None, title="Limit", description="Max results to return.")


async def _get_ad_rule_history(c, token, secret):
    params = {}
    if c.limit is not None:
        params["limit"] = c.limit
    return await _meta_request(token, "GET", f"/{c.ad_rule_id}/history", params=params, app_secret=secret, action_name="get_ad_rule_history")
_reg(MetaAdRuleHistoryConfig, "get_ad_rule_history", _get_ad_rule_history)


# ---- Ad Studies ----
class MetaAdStudyListConfig(BaseModel):
    """List A/B tests / ad studies under a business."""
    operation: Literal["list_ad_studies"] = Field("list_ad_studies",
        json_schema_extra=_op_extra("list_ad_studies", "List Ad Studies", "Ad Studies"), title="List Ad Studies")
    business_id: str = Field(..., title="Business ID", description="Business ID that owns the studies.")
    limit: Optional[int] = Field(None, title="Limit", description="Max results to return.")


async def _list_ad_studies(c, token, secret):
    params = {"fields": "id,name,type,start_time,end_time,status"}
    if c.limit is not None:
        params["limit"] = c.limit
    return await _meta_request(token, "GET", f"/{c.business_id}/ad_studies", params=params, app_secret=secret, action_name="list_ad_studies")
_reg(MetaAdStudyListConfig, "list_ad_studies", _list_ad_studies)


class MetaAdStudyCreateConfig(BaseModel):
    """Create an A/B test / ad study on a business."""
    operation: Literal["create_ad_study"] = Field("create_ad_study",
        json_schema_extra=_op_extra("create_ad_study", "Create Ad Study", "Ad Studies"), title="Create Ad Study")
    business_id: str = Field(..., title="Business ID", description="Business ID to create the study on.")
    name: str = Field(..., title="Name", description="Study name.")
    type: str = Field("SPLIT_TEST", title="Type", description="Study type.",
        json_schema_extra={"enum": ["SPLIT_TEST", "LIFT", "GEO_LIFT"], "x-enum-searchable": True})
    fields_json: str = Field("{}", title="Additional Fields (JSON)",
        description="Optional: cells (JSON array), objectives, start_time, end_time, description.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})


async def _create_ad_study(c, token, secret):
    data = {"name": c.name, "type": c.type}
    for k, v in (_parse_json_field(c.fields_json, "Additional Fields") or {}).items():
        data[k] = json.dumps(v) if isinstance(v, (dict, list)) else v
    return await _meta_request(token, "POST", f"/{c.business_id}/ad_studies", data=data, app_secret=secret, action_name="create_ad_study")
_reg(MetaAdStudyCreateConfig, "create_ad_study", _create_ad_study)


_reg(*_make_object_get("get_ad_study", "Get Ad Study", "Ad Study ID",
    "id,name,type,start_time,end_time,status,description", "Ad Studies"))


class MetaAdStudyUpdateConfig(BaseModel):
    """Update an A/B test / ad study."""
    operation: Literal["update_ad_study"] = Field("update_ad_study",
        json_schema_extra=_op_extra("update_ad_study", "Update Ad Study", "Ad Studies"), title="Update Ad Study")
    ad_study_id: str = Field(..., title="Ad Study ID", description="Ad study ID.")
    fields_json: str = Field("{}", title="Fields (JSON)", description="Fields to update.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})


async def _update_ad_study(c, token, secret):
    data = {}
    for k, v in (_parse_json_field(c.fields_json, "Fields") or {}).items():
        data[k] = json.dumps(v) if isinstance(v, (dict, list)) else v
    return await _meta_request(token, "POST", f"/{c.ad_study_id}", data=data, app_secret=secret, action_name="update_ad_study")
_reg(MetaAdStudyUpdateConfig, "update_ad_study", _update_ad_study)


_reg(*_make_object_delete("delete_ad_study", "Delete Ad Study", "Ad Study ID", "Ad Studies"))


class MetaStudyCellsListConfig(BaseModel):
    """List the cells (test/control groups) of an ad study."""
    operation: Literal["list_study_cells"] = Field("list_study_cells",
        json_schema_extra=_op_extra("list_study_cells", "List Study Cells", "Ad Studies"), title="List Study Cells")
    ad_study_id: str = Field(..., title="Ad Study ID", description="Ad study ID.")
    limit: Optional[int] = Field(None, title="Limit", description="Max results to return.")


async def _list_study_cells(c, token, secret):
    params = {"fields": "id,name,treatment_percentage,control_percentage"}
    if c.limit is not None:
        params["limit"] = c.limit
    return await _meta_request(token, "GET", f"/{c.ad_study_id}/cells", params=params, app_secret=secret, action_name="list_study_cells")
_reg(MetaStudyCellsListConfig, "list_study_cells", _list_study_cells)


class MetaStudyObjectivesListConfig(BaseModel):
    """List the objectives of an ad study."""
    operation: Literal["list_study_objectives"] = Field("list_study_objectives",
        json_schema_extra=_op_extra("list_study_objectives", "List Study Objectives", "Ad Studies"), title="List Study Objectives")
    ad_study_id: str = Field(..., title="Ad Study ID", description="Ad study ID.")
    limit: Optional[int] = Field(None, title="Limit", description="Max results to return.")


async def _list_study_objectives(c, token, secret):
    params = {"fields": "id,name,type"}
    if c.limit is not None:
        params["limit"] = c.limit
    return await _meta_request(token, "GET", f"/{c.ad_study_id}/objectives", params=params, app_secret=secret, action_name="list_study_objectives")
_reg(MetaStudyObjectivesListConfig, "list_study_objectives", _list_study_objectives)


# ---- Business Management (Extended) ----
class MetaListAgenciesConfig(BaseModel):
    """List agencies that have access to a business."""
    operation: Literal["list_agencies"] = Field("list_agencies",
        json_schema_extra=_op_extra("list_agencies", "List Agencies", "Business"), title="List Agencies")
    business_id: str = Field(..., title="Business", description="Business Manager ID.")
    fields: str = Field("id,name", title="Fields", description="Comma-separated fields to return.")
    limit: Optional[str] = Field(None, title="Limit", description="Max number of results.")
async def _list_agencies(c, token, secret):
    params = {"fields": c.fields}
    if c.limit:
        params["limit"] = c.limit
    return await _meta_request(token, "GET", f"/{c.business_id}/agencies", params=params, app_secret=secret, action_name="list_agencies")
_reg(MetaListAgenciesConfig, "list_agencies", _list_agencies)


class MetaRemoveAgencyConfig(BaseModel):
    """Remove an agency's access to a business."""
    operation: Literal["remove_agency"] = Field("remove_agency",
        json_schema_extra=_op_extra("remove_agency", "Remove Agency", "Business"), title="Remove Agency")
    business_id: str = Field(..., title="Business", description="Business Manager ID.")
    business: str = Field(..., title="Agency Business", description="Agency business ID to remove.")
async def _remove_agency(c, token, secret):
    data = {"business": c.business}
    return await _meta_request(token, "DELETE", f"/{c.business_id}/agencies", data=data, app_secret=secret, action_name="remove_agency")
_reg(MetaRemoveAgencyConfig, "remove_agency", _remove_agency)


class MetaListClientsConfig(BaseModel):
    """List client businesses managed by a business."""
    operation: Literal["list_clients"] = Field("list_clients",
        json_schema_extra=_op_extra("list_clients", "List Clients", "Business"), title="List Clients")
    business_id: str = Field(..., title="Business", description="Business Manager ID.")
    fields: str = Field("id,name", title="Fields", description="Comma-separated fields to return.")
    limit: Optional[str] = Field(None, title="Limit", description="Max number of results.")
async def _list_clients(c, token, secret):
    params = {"fields": c.fields}
    if c.limit:
        params["limit"] = c.limit
    return await _meta_request(token, "GET", f"/{c.business_id}/clients", params=params, app_secret=secret, action_name="list_clients")
_reg(MetaListClientsConfig, "list_clients", _list_clients)


class MetaListOwnedBusinessesConfig(BaseModel):
    """List businesses owned by a business."""
    operation: Literal["list_owned_businesses"] = Field("list_owned_businesses",
        json_schema_extra=_op_extra("list_owned_businesses", "List Owned Businesses", "Business"), title="List Owned Businesses")
    business_id: str = Field(..., title="Business", description="Business Manager ID.")
    fields: str = Field("id,name", title="Fields", description="Comma-separated fields to return.")
    limit: Optional[str] = Field(None, title="Limit", description="Max number of results.")
async def _list_owned_businesses(c, token, secret):
    params = {"fields": c.fields}
    if c.limit:
        params["limit"] = c.limit
    return await _meta_request(token, "GET", f"/{c.business_id}/owned_businesses", params=params, app_secret=secret, action_name="list_owned_businesses")
_reg(MetaListOwnedBusinessesConfig, "list_owned_businesses", _list_owned_businesses)


class MetaCreateOwnedBusinessConfig(BaseModel):
    """Create a child business owned by a business."""
    operation: Literal["create_owned_business"] = Field("create_owned_business",
        json_schema_extra=_op_extra("create_owned_business", "Create Owned Business", "Business"), title="Create Owned Business")
    business_id: str = Field(..., title="Business", description="Parent Business Manager ID.")
    name: str = Field(..., title="Name", description="Name of the new owned business.")
    vertical: str = Field(..., title="Vertical", description="Business vertical (e.g. ADVERTISING).")
    fields_json: str = Field("{}", title="Additional Fields (JSON)",
        description="Optional extra fields (timezone_id, page_permitted_tasks, sales_rep_email, ...).",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})
async def _create_owned_business(c, token, secret):
    data = {"name": c.name, "vertical": c.vertical}
    for k, v in (_parse_json_field(c.fields_json, "Additional Fields") or {}).items():
        data[k] = json.dumps(v) if isinstance(v, (dict, list)) else v
    return await _meta_request(token, "POST", f"/{c.business_id}/owned_businesses", data=data, app_secret=secret, action_name="create_owned_business")
_reg(MetaCreateOwnedBusinessConfig, "create_owned_business", _create_owned_business)


class MetaCreateAdAccountConfig(BaseModel):
    """Create a new ad account under a business."""
    operation: Literal["create_ad_account"] = Field("create_ad_account",
        json_schema_extra=_op_extra("create_ad_account", "Create Ad Account", "Business"), title="Create Ad Account")
    business_id: str = Field(..., title="Business", description="Business Manager ID.")
    name: str = Field(..., title="Name", description="Ad account name.")
    currency: str = Field(..., title="Currency", description="ISO currency code (e.g. USD).")
    timezone_id: str = Field(..., title="Timezone ID", description="Timezone ID (e.g. \"1\").")
    end_advertiser: str = Field(..., title="End Advertiser", description="Page/business ID of the advertiser, or \"NONE\".")
    media_agency: str = Field(..., title="Media Agency", description="Media agency business ID, or \"NONE\".")
    partner: str = Field(..., title="Partner", description="Partner business ID, or \"NONE\".")
async def _create_ad_account(c, token, secret):
    adaccount = {"name": c.name, "currency": c.currency, "timezone_id": c.timezone_id}
    data = {
        "adaccount": json.dumps(adaccount),
        "end_advertiser": c.end_advertiser,
        "media_agency": c.media_agency,
        "partner": c.partner,
    }
    return await _meta_request(token, "POST", f"/{c.business_id}/adaccount", data=data, app_secret=secret, action_name="create_ad_account")
_reg(MetaCreateAdAccountConfig, "create_ad_account", _create_ad_account)


class MetaListPendingUsersConfig(BaseModel):
    """List pending user invitations for a business."""
    operation: Literal["list_pending_users"] = Field("list_pending_users",
        json_schema_extra=_op_extra("list_pending_users", "List Pending Users", "Business"), title="List Pending Users")
    business_id: str = Field(..., title="Business", description="Business Manager ID.")
    fields: str = Field("id,email,role,status", title="Fields", description="Comma-separated fields to return.")
    limit: Optional[str] = Field(None, title="Limit", description="Max number of results.")
async def _list_pending_users(c, token, secret):
    params = {"fields": c.fields}
    if c.limit:
        params["limit"] = c.limit
    return await _meta_request(token, "GET", f"/{c.business_id}/pending_users", params=params, app_secret=secret, action_name="list_pending_users")
_reg(MetaListPendingUsersConfig, "list_pending_users", _list_pending_users)


class MetaListPendingClientAdAccountsConfig(BaseModel):
    """List pending client ad account requests for a business."""
    operation: Literal["list_pending_client_ad_accounts"] = Field("list_pending_client_ad_accounts",
        json_schema_extra=_op_extra("list_pending_client_ad_accounts", "List Pending Client Ad Accounts", "Business"), title="List Pending Client Ad Accounts")
    business_id: str = Field(..., title="Business", description="Business Manager ID.")
    limit: Optional[str] = Field(None, title="Limit", description="Max number of results.")
async def _list_pending_client_ad_accounts(c, token, secret):
    params = {}
    if c.limit:
        params["limit"] = c.limit
    return await _meta_request(token, "GET", f"/{c.business_id}/pending_client_ad_accounts", params=params, app_secret=secret, action_name="list_pending_client_ad_accounts")
_reg(MetaListPendingClientAdAccountsConfig, "list_pending_client_ad_accounts", _list_pending_client_ad_accounts)


class MetaListExtendedCreditsConfig(BaseModel):
    """List extended credit lines available to a business."""
    operation: Literal["list_extended_credits"] = Field("list_extended_credits",
        json_schema_extra=_op_extra("list_extended_credits", "List Extended Credits", "Business"), title="List Extended Credits")
    business_id: str = Field(..., title="Business", description="Business Manager ID.")
    fields: str = Field("id,legal_entity_name,max_balance,balance,credit_available,is_owned_by_business",
        title="Fields", description="Comma-separated fields to return.")
    limit: Optional[str] = Field(None, title="Limit", description="Max number of results.")
async def _list_extended_credits(c, token, secret):
    params = {"fields": c.fields}
    if c.limit:
        params["limit"] = c.limit
    return await _meta_request(token, "GET", f"/{c.business_id}/extendedcredits", params=params, app_secret=secret, action_name="list_extended_credits")
_reg(MetaListExtendedCreditsConfig, "list_extended_credits", _list_extended_credits)


# ============================================================================
# Webhook triggers (Graph API Webhooks — page.leadgen + ad_account events).
# CRC handshake + X-Hub-Signature-256, matched by entry[].changes[].field.
# ============================================================================

# (op, webhook field, display). The subscribed object (page / ad_account) is
# configured app-side; matching is on the change field, which is unambiguous.
META_WEBHOOK_FIELDS = [
    ("on_leadgen", "leadgen", "On New Lead (Lead Ads)"),
    ("on_ad_issues", "with_issues_ad_objects", "On Ad Issue / Disapproval"),
    ("on_ad_in_process", "in_process_ad_objects", "On Ad Review Complete"),
    ("on_creative_fatigue", "creative_fatigue", "On Creative Fatigue"),
    ("on_ad_recommendations", "ad_recommendations", "On Ad Recommendation"),
    ("on_async_ad_creation", "ads_async_creation_request", "On Async Ad Creation"),
    ("on_product_set_issue", "product_set_issue", "On Product Set Issue"),
]


class _MetaWebhookTrigger(BaseModel):
    """Base config for Meta webhook triggers."""
    webhook_url: Optional[str] = Field(
        None, title="Callback URL", description="Paste this into your Meta app's webhook config.",
        json_schema_extra={"ui:widget": "webhook", "ui:copyable": True})
    verify_token: Optional[str] = Field(
        None, title="Verify Token", description="Token Meta echoes during the subscription handshake.")
    app_secret: Optional[str] = Field(
        None, title="App Secret", description="Meta app secret for X-Hub-Signature-256 verification.",
        json_schema_extra={"ui:widget": "password"})


def _make_meta_trigger(op: str, field: str, display: str) -> type:
    return create_model(
        f"MetaTrigger_{op}", __base__=_MetaWebhookTrigger,
        operation=(Literal[op], Field(op, json_schema_extra={
            "const": op, "ui:hidden": True, "x-category": "Triggers", "x-is-trigger": True,
            "x-webhook-topic": field, "x-display-name": display}, title=display)))


META_TRIGGER_SPECS = list(META_WEBHOOK_FIELDS) + [("on_any_meta_event", "*", "On Any Meta Event")]
META_TRIGGER_EVENT = {op: field for op, field, _ in META_TRIGGER_SPECS}
META_TRIGGER_CONFIGS = {op: _make_meta_trigger(op, field, disp) for op, field, disp in META_TRIGGER_SPECS}


# ============================================================================
# Config union
# ============================================================================


def _dedup_ops(configs: List[type]) -> List[type]:
    by_op: Dict[str, type] = {}
    for cfg in configs:
        by_op[cfg.model_fields["operation"].default] = cfg
    return list(by_op.values())


MetaConfig = Annotated[
    Union[tuple([*META_TRIGGER_CONFIGS.values(), *_dedup_ops(OPERATION_CONFIGS)])],  # type: ignore[misc]
    Discriminator("operation"),
]


class MetaNodeConfig(NodeConfig[MetaConfig, MetaCredential]):
    pass


class MetaNode(WorkflowNode):
    """Meta (Marketing / Ads / Business / CAPI / Lead Ads) automation node."""

    edit_examples = [
        "Create a Facebook ad campaign",
        "Pull ad insights for my account",
        "List my ad campaigns and their spend",
        "Send a server conversion event to my pixel",
        "Retrieve new leads from my Lead Ads form",
    ]

    scope_registry = META_SCOPES
    connection_evidence = ConnectionEvidence(
        field="ad_account_id",
        noun="ad accounts",
    )

    @classmethod
    def get_config_model(cls):
        return MetaNodeConfig

    @classmethod
    def verify_webhook_signature(cls, body: bytes, headers: Dict[str, str], config: Dict[str, Any]) -> bool:
        sig = headers.get("x-hub-signature-256") or headers.get("X-Hub-Signature-256")
        app_secret = (config or {}).get("app_secret")
        if not app_secret:
            return sig is None or (sig.startswith("sha256=") and len(sig) > len("sha256="))
        if not sig or not sig.startswith("sha256="):
            return False
        expected = hmac.new(str(app_secret).encode("utf-8"), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(sig[len("sha256="):], expected)

    @classmethod
    def handle_webhook_handshake(cls, body: bytes, headers: Dict[str, str], config: Optional[Dict[str, Any]] = None):
        query = headers.get("__query_params__") or {}
        if headers.get("__method__") != "GET" or not isinstance(query, dict):
            return None
        if query.get("hub.mode") != "subscribe":
            return None
        expected_token = (config or {}).get("verify_token")
        if expected_token and query.get("hub.verify_token") != expected_token:
            return None
        challenge = query.get("hub.challenge")
        if challenge is None:
            return None
        return PlainTextResponse(content=str(challenge), status_code=200)

    @staticmethod
    def _payload_fields(payload: Dict[str, Any]) -> List[str]:
        if not isinstance(payload, dict):
            return []
        fields: List[str] = []
        top = payload.get("field")
        if top:
            fields.append(str(top))
        for entry in payload.get("entry") or []:
            if not isinstance(entry, dict):
                continue
            for change in entry.get("changes") or []:
                if isinstance(change, dict) and change.get("field"):
                    fields.append(str(change["field"]))
        seen: set = set()
        return [f for f in fields if not (f in seen or seen.add(f))]

    @classmethod
    def filter_trigger_payload(cls, payload: Dict[str, Any], config: Dict[str, Any]) -> bool:
        field = META_TRIGGER_EVENT.get((config or {}).get("operation"), "*")
        if field == "*":
            return True
        found = cls._payload_fields(payload)
        if not found:
            return True
        return field in found

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        if not credential_data or credential_data.get("credential_type") != "meta_oauth":
            return credential_data
        from nodes.core.oauth_refresh import freshen_oauth_credential
        return await freshen_oauth_credential(
            credential_data, pool=pool, user_id=user_id, credential_id=credential_id,
            refresh=refresh_access_token, is_expired=is_token_expired,
            refresh_token_key="access_token", provider="meta")

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, page_token=None, search=None):
        # Caller convention: pre-loaded/freshened credential dict as credential_data
        # (the old user_id/config_data/credential_ids signature broke the dropdown).
        if field_name != "ad_account_id":
            return {"options": []}
        access_token = (credential_data or {}).get("access_token")
        app_secret = (credential_data or {}).get("app_secret")
        if not access_token:
            return {"options": []}
        result = await _meta_request(access_token, "GET", "/me/adaccounts",
                                     params={"fields": "id,name", "limit": "200"},
                                     app_secret=app_secret, action_name="list_ad_accounts")
        if result.get("status") != "success":
            return {"options": []}
        items = (result.get("data") or {}).get("data", []) if isinstance(result.get("data"), dict) else []
        options = [{"label": str(it.get("name") or it.get("id")), "value": str(it.get("id"))}
                   for it in items if isinstance(it, dict) and it.get("id")]
        return {"options": options}

    async def _resolve(self, credentials: MetaCredential):
        """Return (access_token, app_secret), refreshing an expiring OAuth token."""
        app_secret = getattr(credentials, "app_secret", None)
        # NoClick-managed OAuth tokens are issued by META_APP_ID, whose secret
        # lives in env, not on the credential. Without it, endpoints that demand
        # appsecret_proof (e.g. POST /{system-user}/access_tokens) always fail
        # with "This method must be called with appsecret_proof". A custom-client
        # credential keeps its own app_secret (proof must match the issuing app).
        if not app_secret and isinstance(credentials, MetaOAuthCredential):
            app_secret = os.environ.get("META_APP_SECRET")
        expires_at = getattr(credentials, "expires_at", None)
        if not expires_at or not isinstance(credentials, MetaOAuthCredential):
            return credentials.access_token, app_secret
        if not is_token_expired(expires_at):
            return credentials.access_token, app_secret
        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        cred_dict = credentials.model_dump()
        await ensure_fresh_oauth_token(
            credential_id=(self.node_data or {}).get("credential_id"), user_id=self.user_id,
            credential=cred_dict, refresh=refresh_access_token, is_expired=is_token_expired,
            refresh_token_key="access_token", provider="meta", caller_path="execute")
        credentials.access_token = cred_dict["access_token"]
        credentials.expires_at = cred_dict.get("expires_at")
        return credentials.access_token, app_secret

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        start_time = time.time()
        config = self.config
        if not config or not isinstance(config, MetaNodeConfig):
            raise ValueError("Valid configuration is required")
        op = config.config

        if isinstance(op, tuple(META_TRIGGER_CONFIGS.values())):
            return {"status": "success", "action": op.operation,
                    "data": {**inputs, "webhook_url": op.webhook_url},
                    "timing_ms": {"total": round((time.time() - start_time) * 1000, 2)}}

        credentials = config.credentials
        if not credentials:
            raise ValueError("Credentials are required. Connect your Meta account.")
        access_token, app_secret = await self._resolve(credentials)

        handler = OPERATION_HANDLERS.get(op.operation)
        if not handler:
            raise ValueError(f"Unknown operation: {op.operation}")
        result = await handler(op, access_token, app_secret)
        result["timing_ms"] = {**result.get("timing_ms", {}), "total": round((time.time() - start_time) * 1000, 2)}
        return result
