"""Native Metricool brand analytics and strictly unpublished Facebook drafts.

Closed routes follow the current public OpenAPI and X-Mc-Auth guide. Scoped
list witnesses precede post lookup; private diagnostics and media are omitted.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import hmac
import json
import math
import re
from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://app.metricool.com/api"
MAX_BYTES, MAX_ROWS = 2 * 1024 * 1024, 100
ID = r"[1-9][0-9]{0,9}"
TIME = r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?"
METRICS = {
    "instagram": {"count", "interactions", "engagement", "reach", "impressions", "likes", "comments", "saves", "shares"},
    "facebook": {"count", "interactions", "engagement", "impressionsunique", "impressions", "clicks", "comments", "shares", "reactions"},
    "linkedin": {"posts", "clicks", "likes", "comments", "shares", "engagement", "impressions", "interactions"},
}


def _id(value):
    if isinstance(value, bool) or not isinstance(value, (str, int)) or not re.fullmatch(ID, str(value)) or int(value) > 2147483647:
        raise ValueError("Select a positive Metricool int32 ID")
    return str(value)


def _time(value):
    if not isinstance(value, str) or not re.fullmatch(TIME, value):
        raise ValueError("Use local ISO date and time with seconds")
    try: value = datetime.fromisoformat(value).isoformat()
    except ValueError: raise ValueError("Enter a valid local date and time") from None
    return value


def _timezone(value):
    if not isinstance(value, str) or len(value) > 128 or not re.fullmatch(r"[A-Za-z0-9_+-]+(?:/[A-Za-z0-9_+-]+)*", value):
        raise ValueError("Enter the provider's timezone name, such as Europe/Madrid or UTC")
    return value


def _op(value, label, category):
    return {"const": value, "ui:hidden": True, "x-display-name": label, "x-category": category, "x-is-trigger": False}


class MetricoolAPIKeyCredential(BaseModel):
    credential_type: Literal["metricool_api_key"] = Field("metricool_api_key", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., min_length=1, max_length=4096, repr=False, title="API Token", json_schema_extra={"ui:widget": "password"})
    user_id: str = Field(..., title="Metricool User ID", description="Your supplied account userId; it is never inferred from a shared brand's owner.")
    blog_id: str = Field(..., title="Default Brand ID", description="Existing accessible brand used for connection validation and the brand list. Other selected brands require a current list witness.")
    model_config = ConfigDict(title="Metricool API Token", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://help.metricool.com/basic-guide-for-api-integration-r97af",
        "x-credential-instructions": "Supply an existing API token and the userId/blogId from your Metricool account. Current authentication uses X-Mc-Auth, not Authorization. API access is documented for Advanced and Custom plans; your actual entitlement is unverified. No login, mint, refresh or token introspection is performed."})

    @field_validator("api_token", mode="before")
    @classmethod
    def secret(cls, value):
        if not isinstance(value, str): raise ValueError("Paste the existing Metricool API token")
        value = clean_secret(value, field_name="api_token")
        if not value or not value.isascii() or any(ord(c) <= 32 or ord(c) == 127 for c in value):
            raise ValueError("Metricool API token must be a printable single value")
        return value

    @field_validator("user_id", "blog_id", mode="before")
    @classmethod
    def resource_id(cls, value): return _id(value)


class _Config(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("blog_id", "post_id", mode="before", check_fields=False)
    @classmethod
    def resource_id(cls, value): return _id(value)

    @field_validator("start", "end", "planning_time", mode="before", check_fields=False)
    @classmethod
    def local_time(cls, value): return _time(value)

    @field_validator("timezone", mode="before", check_fields=False)
    @classmethod
    def zone(cls, value): return _timezone(value)


class _Brand(_Config):
    blog_id: str = Field(..., title="Brand", json_schema_extra={"x-dynamic-options": {"field_name": "blog_id"}})


class _Range(_Brand):
    start: str = Field(..., title="Start", description="Local ISO time, e.g.2026-10-01T00:00:00; the selected timezone applies.")
    end: str = Field(..., title="End", description="Later than Start, at most31 days; no automatic unbounded pagination.")
    timezone: str = Field("UTC", title="Timezone")

    @model_validator(mode="after")
    def bounded_range(self):
        delta = datetime.fromisoformat(self.end) - datetime.fromisoformat(self.start)
        if not timedelta(0) < delta <= timedelta(days=31): raise ValueError("Select a positive date window of at most31 days")
        return self


class _Post(_Range):
    post_id: str = Field(..., title="Post ID", description="Must appear in List Scheduler Posts for this exact brand and date window before direct lookup.")


class MetricoolListBrands(_Config):
    operation: Literal["list_brands"] = Field("list_brands", json_schema_extra=_op("list_brands", "List Accessible Brands", "Brands"))


class MetricoolGetDefaultBrand(_Config):
    operation: Literal["get_default_brand"] = Field("get_default_brand", json_schema_extra=_op("get_default_brand", "Get Default Brand Metadata", "Brands"))


class MetricoolGetSocialTimeline(_Range):
    operation: Literal["get_social_timeline"] = Field("get_social_timeline", json_schema_extra=_op("get_social_timeline", "Get Social Post Timeline", "Analytics"))
    network: Literal["instagram", "facebook", "linkedin"] = Field(..., title="Network")
    metric: Literal["count", "posts", "interactions", "engagement", "reach", "impressions", "likes", "comments", "saves", "shares", "impressionsunique", "clicks", "reactions"] = Field(..., title="Post Metric")

    @model_validator(mode="after")
    def metric_binding(self):
        if self.metric not in METRICS[self.network]: raise ValueError("Select a documented post metric for this network")
        return self


class MetricoolListInstagramPosts(_Range):
    operation: Literal["list_instagram_posts"] = Field("list_instagram_posts", json_schema_extra=_op("list_instagram_posts", "List Instagram Post Analytics", "Analytics"))


class MetricoolListFacebookPosts(_Range):
    operation: Literal["list_facebook_posts"] = Field("list_facebook_posts", json_schema_extra=_op("list_facebook_posts", "List Facebook Post Analytics", "Analytics"))


class MetricoolListLinkedinPosts(_Range):
    operation: Literal["list_linkedin_posts"] = Field("list_linkedin_posts", json_schema_extra=_op("list_linkedin_posts", "List LinkedIn Post Analytics", "Analytics"))


class MetricoolListSchedulerPosts(_Range):
    operation: Literal["list_scheduler_posts"] = Field("list_scheduler_posts", json_schema_extra=_op("list_scheduler_posts", "List Scheduler Post Metadata", "Scheduler"))


class MetricoolGetSchedulerPost(_Post):
    operation: Literal["get_scheduler_post"] = Field("get_scheduler_post", json_schema_extra=_op("get_scheduler_post", "Get Scoped Scheduler Post", "Scheduler"))


class MetricoolGetSchedulerCounters(_Brand):
    operation: Literal["get_scheduler_counters"] = Field("get_scheduler_counters", json_schema_extra=_op("get_scheduler_counters", "Get Publishing Counters", "Scheduler"))


class MetricoolListLibraryStates(_Brand):
    operation: Literal["list_library_states"] = Field("list_library_states", json_schema_extra=_op("list_library_states", "List Library Workflow States", "Scheduler"))


class MetricoolCreateDraft(_Brand):
    operation: Literal["create_draft"] = Field("create_draft", json_schema_extra=_op("create_draft", "Create Unpublished Facebook Draft", "Drafts"))
    text: str = Field(..., min_length=1, max_length=10000, title="Draft Text")
    planning_time: str = Field(..., title="Draft Planning Time", description="Required provider publicationDate metadata; draft is always true, so this does not schedule the post. Use a future local ISO time.")
    timezone: str = Field("UTC", title="Timezone")


class MetricoolUpdateDraft(_Post):
    operation: Literal["update_draft"] = Field("update_draft", json_schema_extra=_op("update_draft", "Update Unpublished Draft Text", "Drafts"))
    text: str = Field(..., min_length=1, max_length=10000, title="Draft Text", description="Retains the draft's existing planning time and Facebook network; threads, media and approval workflows are refused.")


class MetricoolDeleteDraft(_Post):
    operation: Literal["delete_draft"] = Field("delete_draft", json_schema_extra=_op("delete_draft", "Delete Unpublished Draft", "Drafts"))


MetricoolOperation = Annotated[Union[MetricoolListBrands, MetricoolGetDefaultBrand, MetricoolGetSocialTimeline,
    MetricoolListInstagramPosts, MetricoolListFacebookPosts, MetricoolListLinkedinPosts, MetricoolListSchedulerPosts,
    MetricoolGetSchedulerPost, MetricoolGetSchedulerCounters, MetricoolListLibraryStates,
    MetricoolCreateDraft, MetricoolUpdateDraft, MetricoolDeleteDraft], Field(discriminator="operation")]


class MetricoolNodeConfig(NodeConfig[MetricoolOperation, MetricoolAPIKeyCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


class MetricoolFailure(Exception):
    def __init__(self, message, category, http_status=None):
        super().__init__(message)
        self.category, self.http_status = category, http_status


def _credential(value):
    if not isinstance(value, dict) or value.get("credential_type") != "metricool_api_key":
        raise MetricoolFailure("Metricool credential is unavailable or has the wrong type", "authority")
    try: return MetricoolAPIKeyCredential.model_validate(value)
    except Exception: raise MetricoolFailure("Metricool credential fields are invalid", "authority") from None


def _route(method, path, params, body):
    if not isinstance(params, dict): return False
    try:
        _id(params["userId"]); _id(params["blogId"])
    except (KeyError, ValueError): return False
    extras = set(params) - {"userId", "blogId"}
    if method == "GET":
        if body is not None: return False
        if path in {"/admin/simpleProfiles", "/v2/scheduler/counters", "/v2/scheduler/library/states"} or re.fullmatch(r"/v2/scheduler/posts/" + ID, path): return not extras
        if path == "/v2/scheduler/posts": return extras == {"start", "end", "timezone"}
        if path in {"/v2/analytics/posts/instagram", "/v2/analytics/posts/facebook", "/v2/analytics/posts/linkedin"}: return extras == {"from", "to", "timezone"}
        if path == "/v2/analytics/timelines": return extras == {"from", "to", "timezone", "network", "metric", "subject"} and params["subject"] == "posts" and params["metric"] in METRICS.get(params["network"], set())
        return False
    if extras: return False
    if method == "DELETE": return body is None and bool(re.fullmatch(r"/v2/scheduler/posts/" + ID, path))
    if method not in {"POST", "PUT"} or not isinstance(body, dict): return False
    selected = re.fullmatch(r"/v2/scheduler/posts/(" + ID + r")", path)
    if (method == "POST" and path != "/v2/scheduler/posts") or (method == "PUT" and not selected): return False
    return (set(body) == {"text", "publicationDate", "providers", "draft"} | ({"id"} if method == "PUT" else set())
        and body["draft"] is True and body["providers"] == [{"network": "facebook"}]
        and isinstance(body["text"], str) and 1 <= len(body["text"]) <= 10000
        and isinstance(body["publicationDate"], dict) and set(body["publicationDate"]) == {"dateTime", "timezone"}
        and (method != "PUT" or body["id"] == int(selected[1])))


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result: raise ValueError("Duplicate JSON field")
        result[key] = value
    return result


async def _request(credential, method, path, *, params, body=None):
    if not _route(method, path, params, body) or str(params["userId"]) != credential.user_id:
        raise MetricoolFailure("Unsupported Metricool request or account scope", "validation")
    try:
        async with guarded_async_client(timeout=httpx.Timeout(25.0, connect=8.0), trust_env=False, follow_redirects=False) as client:
            async with client.stream(method, BASE + path, headers={"X-Mc-Auth": credential.api_token, "Accept": "application/json"}, params=params, json=body) as response:
                status = response.status_code
                if status != 200:
                    category = "authentication" if status == 401 else "permission" if status == 403 else "not_found" if status == 404 else "conflict" if status == 409 else "rate_limit" if status == 429 else "unavailable" if status >= 500 else "protocol"
                    raise MetricoolFailure(f"Metricool request refused (HTTP {status})", category, status)
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    content.extend(chunk)
                    if len(content) > MAX_BYTES: raise MetricoolFailure("Metricool response exceeds the native limit", "response_limit")
                if "application/json" not in response.headers.get("content-type", "").lower():
                    raise MetricoolFailure("Metricool returned an unexpected response format", "protocol")
                try:
                    return json.loads(content.decode("utf-8"), object_pairs_hook=_pairs,
                        parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Nonfinite JSON")))
                except Exception: raise MetricoolFailure("Metricool returned invalid JSON", "protocol") from None
    except MetricoolFailure: raise
    except Exception: raise MetricoolFailure("Metricool request could not complete", "network") from None


def _unwrap(payload):
    if not isinstance(payload, dict) or "data" not in payload:
        raise MetricoolFailure("Metricool omitted the typed JsonOk data envelope", "protocol")
    more = False
    if payload.get("page") is not None:
        page = payload["page"]
        if not isinstance(page, dict) or page.get("next") is not None and not isinstance(page["next"], str):
            raise MetricoolFailure("Metricool returned invalid paging metadata", "protocol")
        more = bool(page.get("next"))
    # JsonPaging.next is not documented as a request argument. Never expose/follow its URL.
    return payload["data"], more


def _text(value, limit=10000):
    if value is not None and (not isinstance(value, str) or len(value) > limit):
        raise MetricoolFailure("Metricool returned invalid bounded text", "protocol")
    return value


def _number(value):
    if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or isinstance(value, int) and abs(value) > 9223372036854775807 or isinstance(value, float) and not math.isfinite(value)):
        raise MetricoolFailure("Metricool returned an invalid metric", "protocol")
    return value


def _date_info(value):
    if not isinstance(value, dict): raise MetricoolFailure("Metricool omitted date metadata", "protocol")
    try: return {"dateTime": _time(value.get("dateTime")), "timezone": _timezone(value["timezone"]) if value.get("timezone") is not None else None}
    except ValueError: raise MetricoolFailure("Metricool returned invalid local date metadata", "protocol") from None


def _brand(row):
    if not isinstance(row, dict): raise MetricoolFailure("Metricool returned an invalid brand", "protocol")
    try: result = {"id": _id(row.get("id"))}
    except ValueError: raise MetricoolFailure("Metricool returned an invalid brand ID", "protocol") from None
    for key in ("label", "title", "timezone", "role"):
        if key in row: result[key] = _text(row[key], 4096)
    if "isShared" in row:
        if type(row["isShared"]) is not bool: raise MetricoolFailure("Metricool returned an invalid shared-brand marker", "protocol")
        result["isShared"] = row["isShared"]
    return result


def _list(rows, parser):
    if not isinstance(rows, list) or len(rows) > MAX_ROWS:
        raise MetricoolFailure("Metricool returned an invalid bounded list", "response_limit")
    return [parser(row) for row in rows]


def _post(row, selected=None):
    if not isinstance(row, dict): raise MetricoolFailure("Metricool post is unavailable", "protocol")
    try: result = {"id": _id(row.get("id"))}
    except ValueError: raise MetricoolFailure("Metricool returned an invalid post ID", "protocol") from None
    if selected is not None and result["id"] != selected: raise MetricoolFailure("Metricool returned a different post", "protocol")
    if type(row.get("draft")) is not bool: raise MetricoolFailure("Metricool omitted the explicit draft state", "protocol")
    result["draft"] = row["draft"]
    result["publicationDate"] = _date_info(row.get("publicationDate"))
    if "text" in row: result["text"] = _text(row["text"])
    providers = row.get("providers")
    if not isinstance(providers, list) or not 1 <= len(providers) <= 10: raise MetricoolFailure("Metricool omitted provider metadata", "protocol")
    result["providers"] = []
    for provider in providers:
        if not isinstance(provider, dict) or not isinstance(provider.get("network"), str): raise MetricoolFailure("Metricool returned invalid provider metadata", "protocol")
        status = provider.get("status")
        if status is not None and (not isinstance(status, str) or status not in {"PUBLISHED", "PUBLISHING", "PENDING", "AWAITING_CONFIRMATION", "ERROR", "DRAFT"}): raise MetricoolFailure("Metricool returned an unknown post state", "protocol")
        result["providers"].append({"network": _text(provider["network"], 128), "status": status})
    if "targetBrandId" in row and row["targetBrandId"] is not None:
        try: result["targetBrandId"] = _id(row["targetBrandId"])
        except ValueError: raise MetricoolFailure("Metricool returned an invalid target brand", "protocol") from None
    return result


def _draft(row):
    record = _post(row)
    if (record["draft"] is not True or record["providers"] != [{"network": "facebook", "status": "DRAFT"}]
        or record["publicationDate"]["timezone"] is None
        or not {"parentId", "descendants", "media", "postApprovalData", "libraryPostId"}.issubset(row)
        or "parentId" not in row or not (row["parentId"] is None or type(row["parentId"]) is int and row["parentId"] == 0) or row.get("descendants") != []
        or row.get("media") != [] or row.get("postApprovalData") is not None or row.get("libraryPostId") is not None):
        raise MetricoolFailure("An explicit standalone text-only unpublished Facebook draft is required; thread/media/approval state must be known", "validation")
    return record


ANALYTIC_FIELDS = {
    "instagram": ("likes", "comments", "shares", "interactions", "engagement", "reach", "saved", "follows", "views", "clicks", "impressions"),
    "facebook": ("shares", "comments", "reactions", "impressions", "impressionsOrganic", "impressionsUnique", "clicks", "engagement", "videoViews", "linkclicks"),
    "linkedin": ("clicks", "comments", "likes", "shares", "impressions", "uniqueImpressions", "engagement", "videoViews", "viewers", "timeWatched"),
}


def _analytics(row, network, blog_id):
    if not isinstance(row, dict) or not isinstance(row.get("postId"), str) or not 1 <= len(row["postId"]) <= 512:
        raise MetricoolFailure("Metricool returned invalid social post metadata", "protocol")
    result = {"postId": row["postId"]}
    if "blogId" in row:
        try:
            if _id(row["blogId"]) != blog_id: raise ValueError("Different brand")
        except ValueError: raise MetricoolFailure("Metricool returned social metadata for a different brand", "protocol") from None
    for key in ANALYTIC_FIELDS[network]:
        if key in row: result[key] = _number(row[key])
    return result


def _timeline(row, metric):
    if not isinstance(row, dict) or not isinstance(row.get("metric"), str) or row["metric"].casefold() != metric.casefold():
        raise MetricoolFailure("Metricool returned a different timeline metric", "protocol")
    values = row.get("values")
    if not isinstance(values, list) or len(values) > 1000: raise MetricoolFailure("Metricool returned an oversized timeline", "response_limit")
    points = []
    for point in values:
        if not isinstance(point, dict) or not isinstance(point.get("dateTime"), str): raise MetricoolFailure("Metricool returned invalid timeline points", "protocol")
        points.append({"dateTime": _text(point["dateTime"], 128), "value": _number(point.get("value"))})
    result = {"metric": row["metric"], "values": points}
    if row.get("aggregate") is not None:
        aggregate = row["aggregate"]
        if not isinstance(aggregate, dict): raise MetricoolFailure("Metricool returned invalid aggregate metadata", "protocol")
        result["aggregate"] = {"aggregation": _text(aggregate.get("aggregation"), 128), "value": _number(aggregate.get("value"))}
    return result


class MetricoolNode(WorkflowNode):
    integration_type = "automation-metricool"
    connection_evidence = ConnectionEvidence(noun="brands", operation="list_brands", label_keys=("label", "title", "id"), proves="account")

    @classmethod
    def get_config_model(cls): return MetricoolNodeConfig

    @classmethod
    async def validate_credential_access(cls, credential_data, *, validation_context=None):
        if validation_context is not None:
            result = await validation_context.run_operation("list_brands", {})
        else:
            try:
                credential = _credential(credential_data)
            except MetricoolFailure:
                return {"valid": False, "error": "Metricool credential fields are invalid"}
            data = {"config": {"operation": "list_brands"}, "credentials": credential.model_dump()}
            node = cls(node_id="metricool-validation", node_type=cls.integration_type,
                       node_data=data, config=MetricoolNodeConfig.model_validate(data))
            result = await node.execute({})
        if result.get("status") == "success": return {"valid": True}
        return {"valid": False if result.get("category") in {"authority", "authentication", "permission"} else None}

    async def _current_credential(self):
        supplied = self.config.credentials
        if supplied is None: raise MetricoolFailure("Connect a Metricool credential", "authority")
        if not self.node_data.get("credential_id"): return supplied
        if not self.user_id: raise MetricoolFailure("Metricool credential authority is unavailable", "authority")
        from nodes.core.run_op import resolve_operation_credential
        try:
            current = _credential(await resolve_operation_credential(
                str(self.node_data["credential_id"]), self.user_id,
                self.node_data.get("_approval_pool"), self.organization_id, self.workflow_id,
            ))
        except Exception:
            raise MetricoolFailure("Metricool credential is unavailable or access denied", "authority") from None
        if (current.user_id, current.blog_id) != (supplied.user_id, supplied.blog_id) or not hmac.compare_digest(current.api_token.encode(), supplied.api_token.encode()):
            raise MetricoolFailure("Metricool token/account/default brand changed; reload before retrying", "authority")
        return current

    async def _provider(self, credential, method, path, blog_id, *, extra=None, body=None):
        await self._current_credential()
        if method != "GET": self._mutation_started = True
        payload = await _request(credential, method, path, params={"userId": credential.user_id, "blogId": blog_id, **(extra or {})}, body=body)
        if method == "POST" and isinstance(payload, dict) and isinstance(payload.get("data"), dict):
            try: self._created_id = _id(payload["data"].get("id"))
            except ValueError: pass
        await self._current_credential()
        return payload

    async def _brands(self, credential):
        rows = _list(await self._provider(credential, "GET", "/admin/simpleProfiles", credential.blog_id), _brand)
        if len({row["id"] for row in rows}) != len(rows): raise MetricoolFailure("Metricool returned duplicate brand IDs", "protocol")
        if not any(row["id"] == credential.blog_id for row in rows): raise MetricoolFailure("The saved default brand is not currently accessible", "permission")
        return rows

    async def _scheduler(self, credential, blog_id, start, end, timezone):
        rows, more = _unwrap(await self._provider(credential, "GET", "/v2/scheduler/posts", blog_id, extra={"start": start, "end": end, "timezone": timezone}))
        projected = _list(rows, _post)
        if len({row["id"] for row in projected}) != len(projected): raise MetricoolFailure("Metricool returned duplicate post IDs", "protocol")
        return {"items": projected, "has_more": more, "pagination_following_supported": False}

    async def _scoped_post(self, credential, blog_id, post_id, start, end, timezone):
        listed = await self._scheduler(credential, blog_id, start, end, timezone)
        if not any(row["id"] == post_id for row in listed["items"]):
            raise MetricoolFailure("Post is outside the selected brand/date window or bounded list", "permission")
        row, _ = _unwrap(await self._provider(credential, "GET", "/v2/scheduler/posts/" + post_id, blog_id))
        _post(row, post_id)
        return row

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, *, page_token=None, search=None):
        if field_name != "blog_id": return {"options": [], "next_page_token": None}
        if page_token is not None: raise MetricoolFailure("Metricool brand paging is not documented", "validation")
        credential = _credential(credential_data)
        data = {"config": {"operation": "list_brands"}, "credentials": credential.model_dump()}
        node = cls(node_id="metricool-picker", node_type="automation-metricool", node_data=data, config=MetricoolNodeConfig.model_validate(data))
        rows = await node._brands(credential)
        term = str(search or "")[:200].casefold()
        options = []
        for row in rows:
            label = row.get("label") or row.get("title") or row["id"]
            if not term or term in (label + " " + row["id"]).casefold(): options.append({"value": row["id"], "label": label, "metadata": {"user_id": credential.user_id}})
        return {"options": options, "next_page_token": None}

    async def execute(self, inputs):
        config, op = self.config.config, self.config.config.operation
        writes = {"create_draft", "update_draft", "delete_draft"}
        self._mutation_started, self._created_id = False, None
        selected = getattr(config, "post_id", None)
        try:
            credential = await self._current_credential()
            brands = await self._brands(credential)
            blog_id = getattr(config, "blog_id", credential.blog_id)
            if not any(row["id"] == blog_id for row in brands): raise MetricoolFailure("Selected brand is not currently accessible", "permission")
            if op == "list_brands": data = {"items": brands}
            elif op == "get_default_brand": data = {"record": next(row for row in brands if row["id"] == credential.blog_id)}
            elif op == "list_scheduler_posts": data = await self._scheduler(credential, blog_id, config.start, config.end, config.timezone)
            elif op in {"get_scheduler_post", "update_draft", "delete_draft"}:
                before = await self._scoped_post(credential, blog_id, config.post_id, config.start, config.end, config.timezone)
                if op == "get_scheduler_post": data = {"record": _post(before, config.post_id)}
                else:
                    record = _draft(before)
                    if op == "update_draft":
                        body = {"id": int(config.post_id), "draft": True, "text": config.text, "providers": [{"network": "facebook"}], "publicationDate": record["publicationDate"]}
                        ack, _ = _unwrap(await self._provider(credential, "PUT", "/v2/scheduler/posts/" + config.post_id, blog_id, body=body))
                        if _draft(ack)["id"] != config.post_id: raise MetricoolFailure("Metricool acknowledged a different draft", "protocol")
                        after = _draft(await self._scoped_post(credential, blog_id, config.post_id, config.start, config.end, config.timezone))
                        if after.get("text") != config.text or after["publicationDate"] != record["publicationDate"]: raise MetricoolFailure("Draft text/planning readback differs", "protocol")
                        data = {"record": after, "readback_performed": True}
                    else:
                        ack, _ = _unwrap(await self._provider(credential, "DELETE", "/v2/scheduler/posts/" + config.post_id, blog_id))
                        if ack is not True: raise MetricoolFailure("Metricool did not acknowledge draft deletion", "protocol")
                        after = await self._scheduler(credential, blog_id, config.start, config.end, config.timezone)
                        if any(row["id"] == config.post_id for row in after["items"]): raise MetricoolFailure("Deleted draft remains in the scoped date window", "protocol")
                        data = {"deleted": True, "selected_id": config.post_id, "readback_performed": True, "readback_scope": "same_brand_and_date_window"}
            elif op == "create_draft":
                planning = {"dateTime": config.planning_time, "timezone": config.timezone}
                ack, _ = _unwrap(await self._provider(credential, "POST", "/v2/scheduler/posts", blog_id,
                    body={"draft": True, "text": config.text, "providers": [{"network": "facebook"}], "publicationDate": planning}))
                selected = _post(ack)["id"]
                _draft(ack)
                center = datetime.fromisoformat(config.planning_time)
                after = _draft(await self._scoped_post(credential, blog_id, selected, (center - timedelta(days=1)).isoformat(), (center + timedelta(days=1)).isoformat(), config.timezone))
                if after.get("text") != config.text or after["publicationDate"] != planning: raise MetricoolFailure("New draft readback differs", "protocol")
                data = {"record": after, "readback_performed": True}
            else:
                path = "/v2/analytics/timelines" if op == "get_social_timeline" else "/v2/analytics/posts/" + op.removeprefix("list_").removesuffix("_posts") if op.startswith("list_") and op != "list_library_states" else "/v2/scheduler/library/states" if op == "list_library_states" else "/v2/scheduler/counters"
                extra = {"from": config.start, "to": config.end, "timezone": config.timezone} if hasattr(config, "start") else None
                if op == "get_social_timeline": extra.update(network=config.network, metric=config.metric, subject="posts")
                value, more = _unwrap(await self._provider(credential, "GET", path, blog_id, extra=extra))
                if op == "get_social_timeline": data = {"items": _list(value, lambda row: _timeline(row, config.metric)), "has_more": more, "pagination_following_supported": False}
                elif op in {"list_instagram_posts", "list_facebook_posts", "list_linkedin_posts"}:
                    network = op.removeprefix("list_").removesuffix("_posts")
                    data = {"items": _list(value, lambda row: _analytics(row, network, blog_id)), "has_more": more, "pagination_following_supported": False}
                elif op == "get_scheduler_counters":
                    if not isinstance(value, dict): raise MetricoolFailure("Metricool returned invalid scheduler counters", "protocol")
                    data = {"counters": {key: _number(value[key]) for key in ("monthPublishedPostsByUser", "monthPublishedPostsByBrand", "last24HoursPublishedYoutubePostsByBrand") if key in value}}
                else:
                    def state(row):
                        if not isinstance(row, dict) or type(row.get("id")) is not int or row["id"] <= 0: raise MetricoolFailure("Metricool returned an invalid library state", "protocol")
                        return {"id": str(row["id"]), "name": _text(row.get("name"), 4096), "color": _text(row.get("color"), 128), "position": _number(row.get("position"))}
                    data = {"items": _list(value, state), "has_more": more, "pagination_following_supported": False}
            return {"status": "success", "blog_id": blog_id, **data}
        except MetricoolFailure as exc:
            return {"status": "error", "success": False, "error": str(exc), "category": exc.category, "http_status": exc.http_status,
                "selected_id": selected or self._created_id, "mutation_outcome": "unverified" if self._mutation_started else "not_attempted" if op in writes else None}
