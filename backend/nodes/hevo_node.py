"""Regional Hevo metadata and documented pipeline lifecycle configuration.

Issued Basic key/secret credentials bind the team and fixed regional API. Closed
projections omit source/destination config, data samples and private diagnostics.
"""
from __future__ import annotations

import base64
import hmac
import json
import re
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

REGIONS = ("us", "us2", "eu", "in", "asia", "au", "us-gcp")
MAX_BYTES, MAX_ROWS = 2 * 1024 * 1024, 100
ID = r"[1-9][0-9]{0,18}"
NAME = r"[^/?#%\x00-\x1f\x7f]{1,256}"


def _op(value, label, category):
    return {"const": value, "ui:hidden": True, "x-display-name": label, "x-category": category, "x-is-trigger": False}


def _picker(field):
    return {"x-dynamic-options": {"type": "hevo", "field": field}}


def _id(value):
    if isinstance(value, bool) or not isinstance(value, (str, int)) or not re.fullmatch(ID, str(value)) or int(value) > 9223372036854775807:
        raise ValueError("Select a positive Hevo resource ID")
    return str(value)


def _name(value):
    if not isinstance(value, str) or not re.fullmatch(NAME, value) or value in {".", ".."}:
        raise ValueError("Enter a bounded Hevo object or table name")
    return value


def _cursor(value):
    if not isinstance(value, str) or not value or len(value) > 2048 or any(ord(c) <= 32 or ord(c) == 127 for c in value):
        raise ValueError("Use the provider's nonempty starting_after cursor")
    return value


class HevoAPIKeyCredential(BaseModel):
    credential_type: Literal["hevo_api_key"] = Field("hevo_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, repr=False, title="API Key", json_schema_extra={"ui:widget": "password"})
    api_secret: str = Field(..., min_length=1, max_length=4096, repr=False, title="API Secret", json_schema_extra={"ui:widget": "password"})
    region: Literal["us", "us2", "eu", "in", "asia", "au", "us-gcp"] = Field(..., title="Hevo Account Region", description="The supplied key and secret bind your existing Hevo team. Select its documented region; no caller URL or team-header authority is accepted.", json_schema_extra={"enumNames": ["US East", "US West", "Europe", "India", "Asia", "Australia", "US GCP"]})
    model_config = ConfigDict(title="Hevo API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://api-docs.hevodata.com/reference/building-your-first-api",
        "x-credential-instructions": "Supply an existing API key and secret issued by your Hevo account owner for the selected region. Basic username is the key and password is the secret. No account login, generation, mint or renewal is performed. Actual entitlement and per-operation permission are not inferred."})

    @field_validator("api_key", "api_secret", mode="before")
    @classmethod
    def secret(cls, value, info):
        if not isinstance(value, str):
            raise ValueError("Paste the existing Hevo credential value")
        value = clean_secret(value, field_name=info.field_name)
        if not value or not value.isascii() or any(ord(c) <= 32 or ord(c) == 127 for c in value) or info.field_name == "api_key" and ":" in value:
            raise ValueError("Hevo credential values must be printable single values")
        return value

    @property
    def base_url(self):
        return f"https://{self.region}.hevodata.com/api/public/v2.0"


class _Config(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("pipeline_id", "destination_id", "workflow_id", mode="before", check_fields=False)
    @classmethod
    def resource_id(cls, value):
        return _id(value)

    @field_validator("object_name", "table_name", mode="before", check_fields=False)
    @classmethod
    def resource_name(cls, value):
        return _name(value)


class _Page(_Config):
    limit: int = Field(20, ge=1, le=100, strict=True, title="Page Size")
    starting_after: str | None = Field(None, max_length=2048, title="Starting After", description="Opaque provider cursor from the previous response; never a next-page URL.")

    @field_validator("starting_after")
    @classmethod
    def cursor(cls, value):
        return _cursor(value) if value is not None else None


class _Pipeline(_Config):
    pipeline_id: str = Field(..., title="Pipeline", json_schema_extra=_picker("pipeline_id"))


class _Object(_Pipeline):
    object_name: str = Field(..., title="Object Name", description="Exact object name from List Pipeline Objects for this selected pipeline; no arbitrary path.")


class HevoListPipelines(_Page):
    operation: Literal["list_pipelines"] = Field("list_pipelines", json_schema_extra=_op("list_pipelines", "List Pipelines", "Pipelines"))


class HevoGetPipeline(_Pipeline):
    operation: Literal["get_pipeline"] = Field("get_pipeline", json_schema_extra=_op("get_pipeline", "Get Pipeline Metadata", "Pipelines"))


class HevoGetPipelineSource(_Pipeline):
    operation: Literal["get_pipeline_source"] = Field("get_pipeline_source", json_schema_extra=_op("get_pipeline_source", "Get Pipeline Source Metadata", "Pipelines"))


class HevoGetPipelineSchedule(_Pipeline):
    operation: Literal["get_pipeline_schedule"] = Field("get_pipeline_schedule", json_schema_extra=_op("get_pipeline_schedule", "Get Pipeline Schedule", "Pipelines"))


class HevoUpdatePipelineSchedule(_Pipeline):
    operation: Literal["update_pipeline_schedule"] = Field("update_pipeline_schedule", json_schema_extra=_op("update_pipeline_schedule", "Update Pipeline Frequency", "Pipelines"))
    frequency: int = Field(..., ge=1, le=2147483647, strict=True, title="Frequency (seconds)", description="Changes future ingestion scheduling and may affect data volume/cost. Current configurable schedule and provider min/max bounds are required before the update.")


class HevoSetPipelineState(_Pipeline):
    operation: Literal["set_pipeline_state"] = Field("set_pipeline_state", json_schema_extra=_op("set_pipeline_state", "Set Pipeline Activity", "Pipelines"))
    state: Literal["ACTIVE", "PAUSED"] = Field(..., title="Activity", description="ACTIVE resumes scheduled ingestion; PAUSED stops it. This can affect data processing and spend. It does not invoke the Run Pipeline endpoint.")


class HevoUpdatePipelinePriority(_Pipeline):
    operation: Literal["update_pipeline_priority"] = Field("update_pipeline_priority", json_schema_extra=_op("update_pipeline_priority", "Update Pipeline Priority", "Pipelines"))
    priority: Literal["HIGH", "NORMAL"] = Field(..., title="Priority", description="Changes ingestion scheduling priority; account-specific processing effects require authorized verification.")


class HevoListPipelineObjects(_Page):
    operation: Literal["list_pipeline_objects"] = Field("list_pipeline_objects", json_schema_extra=_op("list_pipeline_objects", "List Pipeline Objects", "Objects"))
    pipeline_id: str = Field(..., title="Pipeline", json_schema_extra=_picker("pipeline_id"))
    search_text: str | None = Field(None, min_length=1, max_length=256, title="Object Search")
    category: Literal["ACTIVE", "INACTIVE", "FAILED", "AWAITING_MAPPING", "HAS_FAILED_EVENTS"] | None = Field(None, title="Category")


class HevoGetPipelineObject(_Object):
    operation: Literal["get_pipeline_object"] = Field("get_pipeline_object", json_schema_extra=_op("get_pipeline_object", "Get Pipeline Object", "Objects"))


class HevoGetPipelineObjectStats(_Object):
    operation: Literal["get_pipeline_object_stats"] = Field("get_pipeline_object_stats", json_schema_extra=_op("get_pipeline_object_stats", "Get Object Stage Counts", "Objects"))
    duration: int = Field(120, ge=1, le=1440, strict=True, title="Duration", description="Documented duration parameter, default120; native reporting bound1–1440. Provider documentation does not define its unit here.")


class HevoListDestinations(_Page):
    operation: Literal["list_destinations"] = Field("list_destinations", json_schema_extra=_op("list_destinations", "List Destination Metadata", "Destinations"))


class HevoGetDestination(_Config):
    operation: Literal["get_destination"] = Field("get_destination", json_schema_extra=_op("get_destination", "Get Destination Metadata", "Destinations"))
    destination_id: str = Field(..., title="Destination", json_schema_extra=_picker("destination_id"))


class HevoGetDestinationTableStats(_Config):
    operation: Literal["get_destination_table_stats"] = Field("get_destination_table_stats", json_schema_extra=_op("get_destination_table_stats", "Get Destination Table Counts", "Destinations"))
    destination_id: str = Field(..., title="Destination", json_schema_extra=_picker("destination_id"))
    table_name: str = Field(..., title="Table Name", description="Exact table name in the selected destination; no query or table mutation.")
    duration: int = Field(120, ge=1, le=1440, strict=True, title="Duration", description="Documented provider duration parameter, native reporting bound1–1440; unit not inferred.")


class HevoListWorkflows(_Config):
    operation: Literal["list_workflows"] = Field("list_workflows", json_schema_extra=_op("list_workflows", "List Workflow Status", "Workflows"))


class HevoGetWorkflow(_Config):
    operation: Literal["get_workflow"] = Field("get_workflow", json_schema_extra=_op("get_workflow", "Get Workflow Status", "Workflows"))
    workflow_id: str = Field(..., title="Hevo Workflow", json_schema_extra=_picker("workflow_id"))


HevoOperation = Annotated[Union[HevoListPipelines, HevoGetPipeline, HevoGetPipelineSource, HevoGetPipelineSchedule,
    HevoUpdatePipelineSchedule, HevoSetPipelineState, HevoUpdatePipelinePriority, HevoListPipelineObjects,
    HevoGetPipelineObject, HevoGetPipelineObjectStats, HevoListDestinations, HevoGetDestination,
    HevoGetDestinationTableStats, HevoListWorkflows, HevoGetWorkflow], Field(discriminator="operation")]


class HevoNodeConfig(NodeConfig[HevoOperation, HevoAPIKeyCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


class HevoFailure(Exception):
    def __init__(self, message, category, http_status=None):
        super().__init__(message)
        self.category, self.http_status = category, http_status


def _credential(value):
    if not isinstance(value, dict) or value.get("credential_type") != "hevo_api_key":
        raise HevoFailure("Hevo credential is unavailable or has the wrong type", "authority")
    try:
        return HevoAPIKeyCredential.model_validate(value)
    except Exception:
        raise HevoFailure("Hevo credential fields are invalid", "authority") from None


def _route(method, path, body):
    reads = (r"/pipelines(?:/" + ID + r"(?:/(?:schedule|objects(?:/[^/]+(?:/stats)?)?))?)?",
        r"/destinations(?:/" + ID + r"(?:/tables/[^/]+/stats)?)?", r"/workflows(?:/" + ID + r")?")
    if method == "GET":
        return any(re.fullmatch(route, path) for route in reads) and body is None
    if method != "PUT" or not isinstance(body, dict):
        return False
    if re.fullmatch(r"/pipelines/" + ID + r"/status", path):
        return set(body) == {"state"} and body["state"] in {"ACTIVE", "PAUSED"}
    if re.fullmatch(r"/pipelines/" + ID + r"/priority", path):
        return set(body) == {"priority"} and body["priority"] in {"HIGH", "NORMAL"}
    return bool(re.fullmatch(r"/pipelines/" + ID + r"/schedule", path)) and set(body) == {"frequency"} and type(body["frequency"]) is int and 1 <= body["frequency"] <= 2147483647


async def _request(credential, method, path, *, params=None, body=None):
    if not _route(method, path, body):
        raise HevoFailure("Unsupported Hevo route or body", "validation")
    authorization = "Basic " + base64.b64encode((credential.api_key + ":" + credential.api_secret).encode()).decode("ascii")
    try:
        async with guarded_async_client(timeout=httpx.Timeout(25.0, connect=8.0), follow_redirects=False, trust_env=False) as client:
            async with client.stream(method, credential.base_url + path, headers={"Authorization": authorization, "Accept": "application/json"}, params=params, json=body) as response:
                status = response.status_code
                if status != (204 if method == "PUT" else 200):
                    category = ("authentication" if status == 401 else "permission" if status == 403 else "not_found" if status == 404 else "conflict" if status == 409 else
                        "rate_limit" if status == 429 else "validation" if status in {400, 422} else "unavailable" if status >= 500 else "protocol")
                    raise HevoFailure(f"Hevo request refused (HTTP {status})", category, status)
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    content.extend(chunk)
                    if len(content) > MAX_BYTES:
                        raise HevoFailure("Hevo response exceeds the metadata limit", "response_limit")
                if status == 204:
                    if content:
                        raise HevoFailure("Hevo returned a body for an empty update receipt", "protocol")
                    return None
                if "application/json" not in response.headers.get("content-type", "").lower():
                    raise HevoFailure("Hevo returned an unexpected content type", "protocol")
                try:
                    payload = json.loads(content)
                except Exception:
                    raise HevoFailure("Hevo returned invalid JSON", "protocol") from None
                if not isinstance(payload, (dict, list)) or isinstance(payload, dict) and (payload.get("success") is False or "error_code" in payload or "error_message" in payload):
                    raise HevoFailure("Hevo returned a failed or invalid response envelope", "protocol")
                return payload
    except HevoFailure:
        raise
    except Exception:
        raise HevoFailure("Hevo request could not complete; saved validity is unverified", "transport") from None


def _data(payload):
    # Endpoint schemas describe the record(s); the pagination guide wraps them in data.
    return payload["data"] if isinstance(payload, dict) and "data" in payload else payload


def _fields(value, fields, *, required=()):
    if not isinstance(value, dict):
        raise HevoFailure("Hevo returned invalid metadata", "protocol")
    result = {}
    for name, kind in fields.items():
        if name not in value:
            continue
        item = value[name]
        if item is not None and type(item) is not kind:
            raise HevoFailure("Hevo returned an invalid metadata field", "protocol")
        result[name] = item
    if any(result.get(name) is None for name in required):
        raise HevoFailure("Hevo omitted required metadata", "protocol")
    return result


def _schedule(value):
    result = _fields(value, {"type": str, "schedule": str, "schedule_configurable": bool}, required=("type",))
    if result["type"] not in {"REAL_TIME", "FREQUENCY", "CRON", "LOAD"}:
        raise HevoFailure("Hevo returned an unknown schedule type", "protocol")
    if "metadata" in value and value["metadata"] is not None:
        result["metadata"] = _fields(value["metadata"], {"frequency": int, "min_allowed_frequency": int, "max_allowed_frequency": int, "cron": str, "destination_id": int})
        if "suggested_frequencies" in value["metadata"]:
            frequencies = value["metadata"]["suggested_frequencies"]
            if not isinstance(frequencies, list) or len(frequencies) > MAX_ROWS or any(type(v) is not int for v in frequencies):
                raise HevoFailure("Hevo returned invalid suggested frequencies", "protocol")
            result["metadata"]["suggested_frequencies"] = frequencies
    return result


def _source(value):
    result = _fields(value, {"name": str, "health_status": str}, required=("name",))
    if "type" in value:
        result["type"] = _fields(value["type"], {"name": str, "display_name": str, "pauseable": bool}, required=("name",))
    return result


def _record(value, resource, selected=None):
    fields = {"pipelines": {"id": int, "status": str, "health_status": str, "last_run_ts": int, "next_run_ts": int, "priority": str},
        "destinations": {"id": int, "name": str, "status": str, "health_status": str},
        "workflows": {"id": int, "name": str, "status": str, "last_run_ts": int, "last_run_status": str, "last_run_time": int},
        "objects": {"name": str, "status": str, "last_run_ts": int}, "stats": {"stage": str, "count": int}}
    required = ("name", "status") if resource == "objects" else ("stage", "count") if resource == "stats" else ("id",)
    result = _fields(value, fields[resource], required=required)
    if "id" in result:
        try:
            result["id"] = _id(result["id"])
        except ValueError:
            raise HevoFailure("Hevo returned an invalid resource ID", "protocol") from None
        if selected is not None and result["id"] != selected:
            raise HevoFailure("Hevo returned a different selected resource", "protocol")
    if resource == "objects":
        try:
            _name(result["name"])
        except ValueError:
            raise HevoFailure("Hevo returned an invalid object name", "protocol") from None
        if selected is not None and result["name"] != selected:
            raise HevoFailure("Hevo returned a different selected object", "protocol")
    if resource in {"pipelines", "destinations", "workflows"} and value.get("schedule") is not None:
        result["schedule"] = _schedule(value["schedule"])
    if resource == "pipelines":
        if value.get("source") is not None: result["source"] = _source(value["source"])
        if value.get("destination") is not None: result["destination"] = _record(value["destination"], "destinations")
    if resource == "destinations" and value.get("type") is not None:
        result["type"] = _fields(value["type"], {"name": str, "display_name": str}, required=("name",))
    return result


def _list(payload, resource, limit=MAX_ROWS, cursor=None, paged=True):
    rows = _data(payload)
    if not isinstance(rows, list) or len(rows) > limit:
        raise HevoFailure("Hevo returned an invalid bounded metadata list", "protocol")
    items = [_record(row, resource) for row in rows]
    key = "id" if resource in {"pipelines", "destinations", "workflows"} else "name" if resource == "objects" else None
    if key and len({row[key] for row in items}) != len(rows):
        raise HevoFailure("Hevo returned duplicate metadata records", "protocol")
    pagination = payload.get("pagination") if isinstance(payload, dict) else None
    next_cursor = None
    if pagination is not None:
        if not paged or not isinstance(pagination, dict) or type(pagination.get("count")) is not int or pagination["count"] != len(rows):
            raise HevoFailure("Hevo returned invalid pagination", "protocol")
        try:
            next_cursor = _cursor(pagination.get("starting_after"))
        except ValueError:
            raise HevoFailure("Hevo returned an invalid next cursor", "protocol") from None
        if next_cursor == cursor or not rows:
            raise HevoFailure("Hevo returned a nonprogressing cursor", "protocol")
    return {"items": items, "returned_count": len(items), "has_more": next_cursor is not None, "next_starting_after": next_cursor}


class HevoNode(WorkflowNode):
    integration_type = "automation-hevo"
    connection_evidence = ConnectionEvidence(noun="pipelines", operation="list_pipelines", operation_arguments={"limit": 5}, label_keys=("id",), proves="reachability")

    @classmethod
    def get_config_model(cls):
        return HevoNodeConfig

    @classmethod
    async def validate_credential_access(cls, credential_data):
        # Staging supplies the freshly decrypted credential to this hook.
        try:
            credential = _credential(credential_data)
            _list(await _request(credential, "GET", "/pipelines", params={"limit": 5}), "pipelines", limit=5)
            return {"valid": True}
        except HevoFailure as exc:
            return {"valid": False if exc.category in {"authority", "authentication", "permission"} else None,
                "error": str(exc)}

    async def _current_credential(self):
        supplied = self.config.credentials
        if supplied is None:
            raise HevoFailure("Connect a Hevo credential", "authority")
        if not self.node_data.get("credential_id"):
            return supplied
        if not self.user_id:
            raise HevoFailure("Hevo credential authority is unavailable", "authority")
        from utils.credentials import resolve_credential_with_owner_fallback
        from utils.database_pool import get_native_pool
        try:
            pool = self.node_data.get("_approval_pool") or get_native_pool()
            current = _credential(await resolve_credential_with_owner_fallback(
                str(self.node_data["credential_id"]), self.user_id, pool,
                org_id=self.organization_id, workflow_id=self.workflow_id))
        except Exception:
            raise HevoFailure("Hevo credential is unavailable or access denied", "authority") from None
        if current.region != supplied.region or any(not hmac.compare_digest(getattr(current, field).encode(), getattr(supplied, field).encode()) for field in ("api_key", "api_secret")):
            raise HevoFailure("Hevo team credential or region changed; reload before retrying", "authority")
        return current

    async def _provider(self, credential, method, path, *, params=None, body=None):
        await self._current_credential()
        if method == "PUT": self._mutation_started = True
        result = await _request(credential, method, path, params=params, body=body)
        await self._current_credential()
        return result

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, *, page_token=None, search=None):
        credential = _credential(credential_data)
        resource = {"pipeline_id": "pipelines", "destination_id": "destinations", "workflow_id": "workflows"}.get(field_name)
        if resource is None: return {"options": [], "next_page_token": None}
        try:
            cursor = _cursor(page_token) if page_token is not None else None
        except ValueError:
            raise HevoFailure("Invalid Hevo picker cursor", "validation") from None
        if resource == "workflows" and cursor is not None:
            raise HevoFailure("Hevo workflow list has no documented pagination", "validation")
        params = {"limit": 100, **({"starting_after": cursor} if cursor else {})} if resource != "workflows" else None
        result = _list(await _request(credential, "GET", "/" + resource, params=params), resource, cursor=cursor, paged=resource != "workflows")
        term = str(search or "")[:200].casefold()
        options = []
        for row in result["items"]:
            label = row.get("name") or (row.get("source") or {}).get("name") or row["id"]
            if term and term not in (str(label) + " " + row["id"]).casefold(): continue
            options.append({"value": row["id"], "label": str(label), "metadata": {"region": credential.region, "resource_type": resource}})
        return {"options": options, "next_page_token": result["next_starting_after"]}

    async def execute(self, inputs):
        config, op = self.config.config, self.config.config.operation
        selected = next((getattr(config, field) for field in ("pipeline_id", "destination_id", "workflow_id") if hasattr(config, field)), None)
        writes = {"update_pipeline_schedule", "set_pipeline_state", "update_pipeline_priority"}
        self._mutation_started = False
        try:
            credential = await self._current_credential()
            if op in writes:
                path = "/pipelines/" + config.pipeline_id
                before = _record(_data(await self._provider(credential, "GET", path)), "pipelines", config.pipeline_id)
                field, value, suffix = ("status", config.state, "/status") if op == "set_pipeline_state" else ("priority", config.priority, "/priority") if op == "update_pipeline_priority" else ("frequency", config.frequency, "/schedule")
                if field == "frequency":
                    schedule = before.get("schedule", {})
                    metadata = schedule.get("metadata", {})
                    low, high = metadata.get("min_allowed_frequency"), metadata.get("max_allowed_frequency")
                    if schedule.get("schedule_configurable") is not True or type(low) is not int or type(high) is not int or not 1 <= low <= value <= high:
                        raise HevoFailure("Current configurable schedule and allowed frequency bounds are required", "validation")
                body = {"state" if field == "status" else field: value}
                await self._provider(credential, "PUT", path + suffix, body=body)
                after = _record(_data(await self._provider(credential, "GET", path)), "pipelines", config.pipeline_id)
                readback = (after.get("schedule", {}).get("metadata", {}).get("frequency") if field == "frequency" else after.get(field))
                if readback != value:
                    raise HevoFailure("Hevo lifecycle readback differs; update outcome is unverified", "protocol")
                data = {"record": after, "readback_performed": True, "acknowledged": True}
            else:
                resource = "pipelines" if op in {"list_pipelines", "get_pipeline", "get_pipeline_source"} else "destinations" if op in {"list_destinations", "get_destination"} else "workflows"
                path, params = "/" + resource + ("/" + selected if selected is not None else ""), None
                if hasattr(config, "limit"):
                    params = {"limit": config.limit, **({"starting_after": config.starting_after} if config.starting_after else {})}
                if op == "get_pipeline_schedule": path = "/pipelines/" + config.pipeline_id + "/schedule"
                if op in {"list_pipeline_objects", "get_pipeline_object", "get_pipeline_object_stats"}:
                    resource, path = "objects", "/pipelines/" + config.pipeline_id + "/objects"
                    if op != "list_pipeline_objects": path += "/" + quote(config.object_name, safe="")
                    if op == "get_pipeline_object_stats": resource, path, params = "stats", path + "/stats", {"duration": config.duration}
                    if op == "list_pipeline_objects":
                        params.update({key: getattr(config, key) for key in ("search_text", "category") if getattr(config, key) is not None})
                if op == "get_destination_table_stats": resource, path, params = "stats", "/destinations/" + config.destination_id + "/tables/" + quote(config.table_name, safe="") + "/stats", {"duration": config.duration}
                payload = await self._provider(credential, "GET", path, params=params)
                if op == "get_pipeline_schedule":
                    rows = _data(payload)
                    if not isinstance(rows, list) or len(rows) > MAX_ROWS:
                        raise HevoFailure("Hevo returned an invalid bounded schedule list", "protocol")
                    data = {"schedules": [_schedule(row) for row in rows]}
                elif op == "get_pipeline_source":
                    record = _record(_data(payload), "pipelines", selected)
                    if "source" not in record: raise HevoFailure("Hevo omitted pipeline source metadata", "protocol")
                    data = {"source": record["source"], "pipeline_id": selected}
                elif op.startswith("get_") and resource != "stats":
                    data = {"record": _record(_data(payload), resource, config.object_name if resource == "objects" else selected)}
                else:
                    data = _list(payload, resource, getattr(config, "limit", MAX_ROWS), getattr(config, "starting_after", None), paged=hasattr(config, "limit"))
            return {"status": "success", "region": credential.region, **data}
        except HevoFailure as exc:
            return {"status": "error", "success": False, "error": str(exc), "category": exc.category, "http_status": exc.http_status,
                "selected_id": selected, "mutation_outcome": "unverified" if self._mutation_started else "not_attempted" if op in writes else None}
