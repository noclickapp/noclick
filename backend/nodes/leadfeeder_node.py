"""Native Leadfeeder v1 company reads; account witnesses never imply free entitlement."""
import base64
from datetime import date, datetime
import hashlib
import hmac
import json
import math
import re
from typing import Annotated, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence

FAMILY = "leadfeeder_api_key"
ORIGIN = "https://api.leadfeeder.com"
Id = Annotated[str, Field(min_length=1, max_length=256)]
Token = Optional[Annotated[str, Field(max_length=16384)]]


def _id(value):
    # IDs are opaque; current numeric strings and legacy IDs remain supported.
    if (not isinstance(value, str) or not value or len(value) > 256 or value in {".", ".."}
            or re.search(r"[\x00-\x20\x7f/?#\\]", value)):
        raise ValueError("Enter the exact Leadfeeder resource ID, without a URL.")
    return value


def _key(value):
    if (not isinstance(value, str) or not value or len(value) > 4096
            or re.search(r"[\x00-\x20\x7f]", value)
            or value.casefold() in {"example", "placeholder", "your-api-key", "changeme"}):
        raise ValueError("Enter the issued Leadfeeder personal API key.")
    return value


class LeadfeederApiCredential(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True, json_schema_extra={
        "title": "Leadfeeder API Access", "x-credential-url": "https://docs.leadfeeder.com/api/public/authentication-354547m0"})
    credential_type: Literal["leadfeeder_api_key"] = Field(FAMILY, json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="Personal API Key", json_schema_extra={"ui:widget": "password"})
    account_id: Optional[Id] = Field(None, description="Optional exact account binding. Every selected account must be accessible to this key.")

    @field_validator("api_key")
    @classmethod
    def issued_key(cls, value):
        return _key(value)

    @field_validator("account_id", mode="before")
    @classmethod
    def account_binding(cls, value):
        return _id(value) if value is not None else None


def _shape(data):
    if not isinstance(data, dict) or data.get("credential_type") != FAMILY:
        raise ValueError("Connect a credential of type Leadfeeder API Access.")
    account = data.get("account_id")
    return {"credential_type": FAMILY, "api_key": _key(data.get("api_key")),
            "account_id": _id(account) if account is not None else None}


def _picker(field, parent="account_id"):
    options = {"field_name": field, "searchable": True, "allow_custom": True,
               "placeholder": "Select a resource or enter its exact ID"}
    if parent and field != "account_id":
        options["depends_on"] = parent
    resource = {"account_id": "account", "company_id": "company", "list_id": "company_list",
                "custom_feed_id": "custom_feed", "campaign_id": "campaign"}[field]
    return {"x-dynamic-options": options, "x-resource-type": "leadfeeder_" + resource}


class Operation(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("account_id", "company_id", "list_id", "custom_feed_id", "campaign_id", mode="before", check_fields=False)
    @classmethod
    def exact_ids(cls, value):
        return _id(value) if value is not None else None


class AccountOperation(Operation):
    account_id: Id = Field(..., json_schema_extra=_picker("account_id"))


class Page(AccountOperation):
    page_size: int = Field(20, ge=1, le=100, strict=True, description="One documented page; no automatic pagination.")
    page_token: Token = Field(None, description="Use next_page_token from the same key, account, parent and filters.")


class ListAccounts(Operation):
    operation: Literal["list_accounts"] = "list_accounts"


class GetAccount(AccountOperation):
    operation: Literal["get_account"] = "get_account"


class SearchCompanies(Page):
    operation: Literal["search_companies"] = "search_companies"
    search_terms: list[Annotated[str, Field(min_length=1, max_length=128)]] = Field(..., min_length=1, max_length=20,
        description="Company names or websites; documented read-semantic POST search consumes no credits.")
    country_code: Optional[Annotated[str, Field(pattern=r"^[A-Z]{2}$")]] = None
    employee_range: Optional[Literal["1-10", "11-100", "101-500", "501-1.000", "1.001-5.000", "5.001-10.000", "10.000+"]] = None

    @field_validator("search_terms")
    @classmethod
    def nonblank_terms(cls, value):
        if any(not term.strip() for term in value):
            raise ValueError("Enter nonblank company search terms.")
        return value


class GetCompany(AccountOperation):
    operation: Literal["get_company"] = "get_company"
    company_id: Id = Field(..., json_schema_extra=_picker("company_id"))
    acknowledge_credit_use: bool = Field(False, strict=True,
        description="Required before this request: full company data can consume 1 Leadfeeder credit unless accessed in the previous 12 months.")


class ListVisitorCompanies(Page):
    operation: Literal["list_visitor_companies"] = "list_visitor_companies"
    start_date: date
    end_date: date
    custom_feed_id: Optional[Id] = Field(None, json_schema_extra=_picker("custom_feed_id"))

    @model_validator(mode="after")
    def bounded_dates(self):
        if not 0 <= (self.end_date - self.start_date).days <= 366:
            raise ValueError("Select a date range in order spanning at most 366 days.")
        return self


class ListCustomFeeds(AccountOperation):
    operation: Literal["list_custom_feeds"] = "list_custom_feeds"


class GetCustomFeed(AccountOperation):
    operation: Literal["get_custom_feed"] = "get_custom_feed"
    custom_feed_id: Id = Field(..., json_schema_extra=_picker("custom_feed_id"))


class ListFeedFolders(AccountOperation):
    operation: Literal["list_feed_folders"] = "list_feed_folders"


class ListCampaigns(Page):
    operation: Literal["list_campaigns"] = "list_campaigns"


class GetCampaign(AccountOperation):
    operation: Literal["get_campaign"] = "get_campaign"
    campaign_id: Id = Field(..., json_schema_extra=_picker("campaign_id"))


class ListCompanyLists(Page):
    operation: Literal["list_company_lists"] = "list_company_lists"


class GetCompanyList(AccountOperation):
    operation: Literal["get_company_list"] = "get_company_list"
    list_id: Id = Field(..., json_schema_extra=_picker("list_id"))


class ListCompanyListMembers(Page):
    operation: Literal["list_company_list_members"] = "list_company_list_members"
    list_id: Id = Field(..., json_schema_extra=_picker("list_id"))


class ListTags(Page):
    operation: Literal["list_tags"] = "list_tags"


class ListCompanyFields(Page):
    operation: Literal["list_company_fields"] = "list_company_fields"
    field_type: Optional[Literal["text", "number", "boolean", "date", "ai_score", "ai_text", "ai_number", "ai_boolean"]] = None


class ListCountries(AccountOperation):
    operation: Literal["list_countries"] = "list_countries"


class ListIndustries(AccountOperation):
    operation: Literal["list_industries"] = "list_industries"
    classification: Literal["internal", "nace", "wz"] = "internal"
    code: Optional[Annotated[str, Field(min_length=1, max_length=64)]] = None


LeadfeederOperation = Annotated[Union[ListAccounts, GetAccount, SearchCompanies, GetCompany,
    ListVisitorCompanies, ListCustomFeeds, GetCustomFeed, ListFeedFolders, ListCampaigns,
    GetCampaign, ListCompanyLists, GetCompanyList, ListCompanyListMembers, ListTags,
    ListCompanyFields, ListCountries, ListIndustries], Field(discriminator="operation")]


class LeadfeederNodeConfig(NodeConfig[LeadfeederOperation, LeadfeederApiCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)
    credentials: Optional[LeadfeederApiCredential] = Field(None, description="Connect a Leadfeeder personal API key.")


class LeadfeederAccessDenied(ValueError):
    pass


def _text(value, *, required=False, maximum=512):
    if value is None and not required:
        return None
    if not isinstance(value, str) or len(value) > maximum or (required and not value.strip()):
        raise ValueError("Leadfeeder returned invalid scalar metadata.")
    return value


def _number(value):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError("Leadfeeder returned invalid numeric metadata.")
    return value


def _boolean(value):
    if type(value) is not bool:
        raise ValueError("Leadfeeder returned invalid boolean metadata.")
    return value


def _ref(value, resource):
    if not isinstance(value, dict) or value.get("type") != resource:
        raise ValueError("Leadfeeder returned a different resource type.")
    return {"id": _id(value.get("id")), "type": resource}


def _entity(value, resource, ident=None, *, reference=False):
    result = _ref(value, resource)
    attrs = value.get("attributes")
    rel = value.get("relationships")
    if resource == "company_location":
        if not isinstance(rel, dict):
            raise ValueError("Leadfeeder returned invalid company relationships.")
        # Company-only references, never visitor IDs, addresses, IPs or visit histories.
        result["company"] = _ref(rel.get("company"), "company")
        return result
    if reference:
        return result
    if not isinstance(attrs, dict):
        raise ValueError("Leadfeeder returned invalid resource attributes.")
    result["name"] = _text(attrs.get("name"), required=True)
    for key in ("created_at", "updated_at"):
        if key in attrs and attrs[key] is not None:
            text = _text(attrs[key], required=True, maximum=64)
            try:
                parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    raise ValueError()
            except ValueError:
                raise ValueError("Leadfeeder returned invalid timestamp metadata.") from None
            result[key] = text
    if resource in {"company", "company_summary", "masked_company_summary"}:
        meta = attrs.get("meta")
        if not isinstance(meta, dict):
            raise ValueError("Leadfeeder returned invalid company ID lifecycle metadata.")
        changed = _boolean(meta.get("has_updated_id"))
        result["has_updated_id"] = changed
        if "do_not_contact" in meta:
            result["do_not_contact"] = _boolean(meta["do_not_contact"])
        if ident is not None:
            requested = _id(ident)
            if result["id"] != requested and not changed:
                raise ValueError("Leadfeeder returned a different company without an ID-change witness.")
            result["requested_company_id"] = requested
            result["id_changed"] = result["id"] != requested
        for key in ("employee_range", "role"):
            if key in attrs:
                result[key] = _text(attrs[key])
        if resource == "masked_company_summary":
            result["masked"] = True
        if "address" in attrs:
            if not isinstance(attrs["address"], dict):
                raise ValueError("Leadfeeder returned invalid company address metadata.")
            result["country_code"] = _text(attrs["address"].get("country_code"))
        if "previous_ids" in attrs:
            previous = attrs["previous_ids"]
            if not isinstance(previous, list) or len(previous) > 1000:
                raise ValueError("Leadfeeder returned invalid company previous IDs.")
            result["previous_ids"] = [_id(item) for item in previous]
            if ident is not None and result["id"] != ident and ident not in result["previous_ids"]:
                raise ValueError("Leadfeeder company history does not contain the requested prior ID.")
        if ident is not None and result["id"] != ident and "previous_ids" not in result:
            raise ValueError("Leadfeeder returned a changed company without its prior-ID history.")
    else:
        if ident is not None and result["id"] != _id(ident):
            raise ValueError("Leadfeeder returned a different resource ID.")
    if resource in {"list", "custom_field"}:
        if attrs.get("scope") != "company":
            raise ValueError("Select a company-scoped Leadfeeder resource.")
        result["scope"] = "company"
    if resource == "custom_field":
        result["field_type"] = _text(attrs.get("type"), required=True)
        result["read_only"] = _boolean(attrs.get("read_only"))
        result["source"] = _text(attrs.get("source"), required=True)
    if resource == "campaign":
        status = attrs.get("status")
        if status not in {"draft", "scheduled", "running", "paused", "stopped", "terminated", "ended"}:
            raise ValueError("Leadfeeder returned invalid campaign status.")
        result["status"] = status
    if resource == "custom_feed" and "viewable" in attrs:
        result["viewable"] = _boolean(attrs["viewable"])
    if resource in {"company_industry", "country"}:
        result["code"] = _text(attrs.get("code"), required=True, maximum=64)
    return result


def _envelope(value, *, array=True, maximum=100):
    if not isinstance(value, dict) or "errors" in value or not isinstance(value.get("meta"), dict):
        raise ValueError("Leadfeeder returned an invalid success envelope; access is unverified.")
    _text(value["meta"].get("request_id"), required=True, maximum=256)
    data = value.get("data")
    if array and (not isinstance(data, list) or len(data) > maximum):
        raise ValueError("Leadfeeder returned an invalid or oversized bounded collection.")
    if not array and not isinstance(data, dict):
        raise ValueError("Leadfeeder returned an invalid resource envelope.")
    return data, value["meta"]


def _rows(data, resource, *, reference=False):
    items = [_entity(row, resource, reference=reference) for row in data]
    if len({row["id"] for row in items}) != len(items):
        raise ValueError("Leadfeeder returned repeated resource IDs.")
    return items


class _Client:
    def __init__(self, data):
        self.credential = _shape(data)
        self.witness = None

    def scrub(self, value):
        if isinstance(value, str):
            return value.replace(self.credential["api_key"], "[REDACTED]")
        if isinstance(value, list):
            return [self.scrub(row) for row in value]
        if isinstance(value, dict):
            return {key: self.scrub(row) for key, row in value.items()}
        return value

    async def request(self, path, *, method="GET", params=None, body=None):
        try:
            async with httpx.AsyncClient(timeout=20, trust_env=False, follow_redirects=False) as http:
                response = await http.request(method, ORIGIN + "/v1" + path, params=params, json=body,
                    headers={"X-Api-Key": self.credential["api_key"], "Accept": "application/json"})
        except httpx.HTTPError:
            raise ValueError("Leadfeeder read failed; access is unverified. Retry later.") from None
        if len(response.content) > 2_000_000:
            raise ValueError("Leadfeeder exceeded the bounded response size.")
        try:
            payload = response.json()
        except ValueError:
            raise ValueError("Leadfeeder returned invalid JSON; access is unverified.") from None
        if response.status_code in (401, 403):
            errors = payload.get("errors") if isinstance(payload, dict) else None
            codes = {item.get("code") for item in errors if isinstance(item, dict) and isinstance(item.get("code"), str)} if isinstance(errors, list) else set()
            if isinstance(payload, dict) and isinstance(payload.get("code"), str):
                codes.add(payload["code"])
            if codes & {"invalid_api_key", "api_key_expired", "missing_api_key", "missing_token"}:
                raise LeadfeederAccessDenied("Leadfeeder did not accept the personal API key; reconnect it.")
        if response.status_code != 200:
            raise ValueError("Leadfeeder read was not completed; permissions, entitlement or temporary availability are unverified.")
        return payload

    async def accounts(self, account_id=None):
        bound = self.credential["account_id"]
        if account_id is not None and bound is not None and account_id != bound:
            raise ValueError("The selected account differs from this credential account binding.")
        data, _ = _envelope(await self.request("/accounts"), maximum=1000)
        rows = _rows(data, "account_summary")
        witness = sorted(({"id": row["id"], "name": row["name"]} for row in rows), key=lambda row: row["id"])
        if self.witness is not None and self.witness != witness:
            raise ValueError("Leadfeeder protected accessible-account witness changed during this read.")
        self.witness = witness
        selected = account_id or bound
        if selected is not None:
            rows = [row for row in rows if row["id"] == selected]
            if len(rows) != 1:
                raise ValueError("The selected Leadfeeder account is not in this key’s accessible accounts.")
        return rows

    def page_token(self, binding, *, cursor=None, token=None):
        binding = {**binding, "account_witness": hashlib.sha256(json.dumps(self.witness, sort_keys=True).encode()).hexdigest(),
                   "credential_account": self.credential["account_id"]}
        key = self.credential["api_key"].encode()
        try:
            if token is not None:
                encoded, signature = token.split(".")
                if not hmac.compare_digest(hmac.new(key, encoded.encode(), hashlib.sha256).hexdigest(), signature):
                    raise ValueError()
                payload = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
                if payload["binding"] != binding:
                    raise ValueError()
                return payload["cursor"]
            encoded = base64.urlsafe_b64encode(json.dumps({"binding": binding, "cursor": cursor}, separators=(",", ":"), sort_keys=True).encode()).decode().rstrip("=")
            return encoded + "." + hmac.new(key, encoded.encode(), hashlib.sha256).hexdigest()
        except (ValueError, TypeError, KeyError, AttributeError):
            raise ValueError("Leadfeeder page token must match this key, account, parent and filters.") from None

    async def detail(self, path, resource, config, ident):
        data, meta = _envelope(await self.request(path + "/" + quote(ident, safe=""), params={"account_id": config.account_id}), array=False)
        result = _entity(data, resource, ident)
        if resource == "company":
            credits = meta.get("credits")
            if not isinstance(credits, dict):
                raise ValueError("Leadfeeder returned missing credit accounting.")
            result["credits_charged"] = _number(credits.get("charged"))
        return result

    async def page(self, path, resource, config, *, params=None, body=None, cursor_mode=False, reference=False):
        params = {"account_id": config.account_id, "page[size]": config.page_size, **(params or {})}
        binding = {"path": path, "params": dict(params), "body": body}
        previous = self.page_token(binding, token=config.page_token) if config.page_token else None
        page = previous if previous is not None else 1
        if cursor_mode:
            if previous is not None:
                if not isinstance(previous, str) or not previous or len(previous) > 4096 or re.search(r"[\x00-\x1f\x7f]", previous):
                    raise ValueError("Leadfeeder returned an invalid page cursor.")
                params["page[cursor]"] = previous
        else:
            if type(page) is not int or not 1 <= page <= 1000:
                raise ValueError("Leadfeeder numbered pages are locally limited to 1–1,000.")
            params["page[num]"] = page
        payload = await self.request(path, method="POST" if body is not None else "GET", params=params, body=body)
        data, meta = _envelope(payload, maximum=config.page_size)
        if resource == "company_search":
            kinds = {row.get("type") for row in data if isinstance(row, dict)}
            if not kinds <= {"company_summary", "masked_company_summary"} or len(kinds) > 1:
                raise ValueError("Leadfeeder returned invalid company search types.")
            rows = _rows(data, next(iter(kinds), "company_summary"))
            credits = meta.get("credits")
            if not isinstance(credits, dict) or _number(credits.get("charged")) != 0:
                raise ValueError("Leadfeeder zero-credit company search returned unexpected credit accounting.")
        else:
            rows = _rows(data, resource, reference=reference)
        pagination = meta.get("pagination")
        if not isinstance(pagination, dict) or type(pagination.get("total_count")) is not int or pagination["total_count"] < len(rows):
            raise ValueError("Leadfeeder returned invalid pagination totals.")
        total = pagination["total_count"]
        if cursor_mode:
            if "next_cursor" not in pagination and resource != "company_search":
                raise ValueError("Leadfeeder returned missing cursor pagination.")
            next_cursor = pagination.get("next_cursor")
            if next_cursor is not None and (not isinstance(next_cursor, str) or not next_cursor or len(next_cursor) > 4096
                    or re.search(r"[\x00-\x1f\x7f]", next_cursor) or next_cursor == previous or not rows):
                raise ValueError("Leadfeeder returned an invalid or non-advancing cursor.")
        else:
            count = pagination.get("page_count")
            if (type(count) is not int or count < 0 or type(pagination.get("page_num")) is not int
                    or pagination["page_num"] != page or (count < page and not (count == 0 and total == 0 and page == 1))
                    or (page - 1) * config.page_size + len(rows) > total):
                raise ValueError("Leadfeeder returned inconsistent numbered pagination.")
            next_cursor = page + 1 if page < count and page < 1000 else None
        next_token = self.page_token(binding, cursor=next_cursor) if next_cursor is not None else None
        return {"items": rows, "total_count": total, "next_page_token": next_token,
                "coverage_limited": total > len(rows) or next_token is not None or (not cursor_mode and page < pagination["page_count"]),
                "coverage": "one bounded provider page"}

    async def run(self, config):
        if config.operation == "get_company" and not config.acknowledge_credit_use:
            raise ValueError("Acknowledge potential Leadfeeder credit use before reading full company data.")
        account_id = getattr(config, "account_id", None)
        accounts = await self.accounts(account_id)
        op = config.operation
        if op == "list_accounts":
            return {"items": accounts, "account_verified": bool(accounts), "reachability_verified": True}
        if op == "get_account":
            data, _ = _envelope(await self.request("/accounts", params={"account_id": account_id}), maximum=1)
            if len(data) != 1:
                raise ValueError("Leadfeeder did not return the selected account.")
            result = _entity(data[0], "account", account_id)
            if result["name"] != accounts[0]["name"]:
                raise ValueError("Leadfeeder account name changed during this read.")
            credits = data[0]["attributes"].get("credits")
            if not isinstance(credits, dict):
                raise ValueError("Leadfeeder returned invalid account credit metadata.")
            result["credits"] = {key: _number(credits.get(key)) for key in ("available", "remaining", "used")}
            try:
                result["credits"]["next_reset_on"] = date.fromisoformat(credits["next_reset_on"]).isoformat()
            except (ValueError, TypeError, KeyError):
                raise ValueError("Leadfeeder returned invalid credit reset metadata.") from None
        elif op == "search_companies":
            body = {"search_terms": config.search_terms}
            if config.country_code:
                body["locations"] = [{"country_code": config.country_code}]
            if config.employee_range:
                body["employee_ranges"] = [config.employee_range]
            result = await self.page("/companies/search", "company_search", config, body=body, cursor_mode=True)
        elif op == "get_company":
            result = await self.detail("/companies", "company", config, config.company_id)
        elif op == "list_visitor_companies":
            params = {"start_date": config.start_date.isoformat(), "end_date": config.end_date.isoformat()}
            if config.custom_feed_id:
                await self.detail("/web-visits/custom-feeds", "custom_feed", config, config.custom_feed_id)
                params["custom_feed_id"] = config.custom_feed_id
            result = await self.page("/web-visits/companies", "company_location", config, params=params)
        elif op in {"list_campaigns", "list_company_lists", "list_tags", "list_company_fields"}:
            path, kind = {"list_campaigns": ("/campaigns", "campaign"), "list_company_lists": ("/lists", "list"),
                          "list_tags": ("/tags", "tag"), "list_company_fields": ("/custom-fields", "custom_field")}[op]
            params = {"filter[scope]": "company"} if op in {"list_company_lists", "list_company_fields"} else {}
            if op == "list_company_fields" and config.field_type:
                params["filter[type]"] = config.field_type
            result = await self.page(path, kind, config, params=params)
        elif op in {"get_campaign", "get_custom_feed", "get_company_list"}:
            path, kind, field = {"get_campaign": ("/campaigns", "campaign", "campaign_id"),
                "get_custom_feed": ("/web-visits/custom-feeds", "custom_feed", "custom_feed_id"),
                "get_company_list": ("/lists", "list", "list_id")}[op]
            result = await self.detail(path, kind, config, getattr(config, field))
        elif op == "list_company_list_members":
            await self.detail("/lists", "list", config, config.list_id)
            result = await self.page("/lists/" + quote(config.list_id, safe="") + "/items", "company", config, cursor_mode=True, reference=True)
        elif op in {"list_custom_feeds", "list_feed_folders", "list_countries", "list_industries"}:
            path, kind, bound = {"list_custom_feeds": ("/web-visits/custom-feeds", "custom_feed", 1000),
                "list_feed_folders": ("/web-visits/custom-feeds-folders", "custom_feed_folder", 1000),
                "list_countries": ("/countries", "country", 1000), "list_industries": ("/industries", "company_industry", 20000)}[op]
            params = {"account_id": account_id}
            if op == "list_industries":
                params["classification"] = config.classification
                if config.code:
                    params["code"] = config.code
            data, _ = _envelope(await self.request(path, params=params), maximum=bound)
            result = {"items": _rows(data, kind), "next_page_token": None, "coverage": "documented unpaged collection; local size bound"}
        else:
            raise ValueError("Unsupported Leadfeeder operation.")
        await self.accounts(account_id)
        return result


class LeadfeederNode(WorkflowNode):
    integration_type = "automation-leadfeeder"
    agent_tool_provider = True
    connection_evidence = ConnectionEvidence(operation="list_accounts", noun="accessible accounts")

    @classmethod
    def get_config_model(cls):
        return LeadfeederNodeConfig

    @classmethod
    def parse_config(cls, config_data):
        # Check the actual family before the base credential reconciliation.
        if config_data.get("credentials") is not None:
            _shape(config_data["credentials"])
        return super().parse_config(config_data)

    @classmethod
    async def validate_credential_access(cls, credential_data):
        # Staging supplies the accessible decrypted credential to this hook.
        try:
            accounts = await _Client(credential_data).accounts()
            return {"valid": True, "account_verified": bool(accounts)}
        except LeadfeederAccessDenied as exc:
            return {"valid": False, "error": str(exc)}
        except Exception:
            return {"valid": None, "error": "Leadfeeder access could not be verified; retry later."}

    async def execute(self, inputs):
        credential = self.node_data.get("credentials")
        if credential is None and not self.node_data.get("credential_id") and self.config.credentials is not None:
            credential = self.config.credentials.model_dump(exclude_none=True)
        client = _Client(credential)
        result = await client.run(self.config.config)
        return {"status": "success", "data": client.scrub(result), "account_verified": bool(client.witness)}

    @classmethod
    async def load_field_options(cls, field_name, credential_data=None, context=None, page_token=None, search=None):
        if context is not None and not isinstance(context, dict):
            raise ValueError("Leadfeeder picker context must be an object.")
        if search is not None and (not isinstance(search, str) or len(search) > 128):
            raise ValueError("Leadfeeder picker search must contain at most 128 characters.")
        context = context or {}
        models = {"account_id": ListAccounts, "company_id": SearchCompanies, "list_id": ListCompanyLists,
                  "custom_feed_id": ListCustomFeeds, "campaign_id": ListCampaigns}
        if field_name not in models:
            raise ValueError("Unsupported Leadfeeder picker field.")
        client = _Client(credential_data)
        kwargs = {}
        if field_name != "account_id":
            try:
                kwargs["account_id"] = _id(context.get("account_id"))
            except ValueError:
                raise ValueError("Select a valid account before looking up this resource.") from None
        if field_name == "company_id":
            if not search or not search.strip():
                if page_token:
                    raise ValueError("Retain the company search text when continuing this picker.")
                return {"options": [], "next_page_token": None, "message": "Search by company name or website; no full-data credit request is used."}
            kwargs.update(search_terms=[search], page_size=100, page_token=page_token)
        elif field_name in {"list_id", "campaign_id"}:
            kwargs.update(page_size=100, page_token=page_token)
        elif page_token:
            raise ValueError("This Leadfeeder picker has no documented continuation.")
        config = models[field_name](**kwargs)
        result = await client.run(config)
        rows = result["items"]
        if search and field_name != "company_id":
            rows = [row for row in rows if search.casefold() in row["name"].casefold()]
        return {"options": client.scrub([{"value": row["id"], "label": row.get("name") or row["id"]} for row in rows]),
                "next_page_token": result.get("next_page_token"), "coverage_limited": result.get("coverage_limited", False),
                "scope": {"account_id": kwargs["account_id"]} if "account_id" in kwargs else {}}
