"""FieldView Platform v4 operations and scheduled agronomic activity triggers.

Routes and payloads follow the provider's pinned 4.0.11 OpenAPI document.
OAuth is mandatory; the separate partner API key supplies the quota header.
"""
from __future__ import annotations

import base64
import os
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any, Literal, Optional, Union
from uuid import UUID
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from nodes.scopes.climate import CLIMATE_SCOPES
from utils.ssrf import guarded_async_client

BASE_URL = "https://platform.climate.com"
DOCS = "https://dev.fieldview.com/openapi/platform.yaml"


class ClimateOAuthCredential(BaseModel):
    model_config = ConfigDict(title="Climate FieldView OAuth", hide_input_in_errors=True,
        json_schema_extra={"x-credential-type": "oauth", "x-oauth-provider": "climate",
            "x-oauth-scopes": CLIMATE_SCOPES.declared_scopes(),
            "x-credential-url": "https://dev.fieldview.com/join-us",
            "x-credential-instructions": "Sign in with FieldView. A partner API key is also required: paste your onboarded partner key, or use the instance's configured CLIMATE_API_KEY. For a manual connection, paste a current OAuth access token; it expires after four hours. Provide a refresh token and token expiry for automatic renewal with the configured OAuth client."})
    credential_type: Literal["climate_oauth"] = Field("climate_oauth", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., title="Access token", json_schema_extra={"ui:widget": "password"})
    api_key: Optional[str] = Field(None, title="Partner API key", json_schema_extra={"ui:widget": "password"})
    refresh_token: Optional[str] = Field(None, title="Refresh token", json_schema_extra={"ui:widget": "password"})
    expires_at: Optional[str] = Field(None, title="Token expiry")
    scope: Optional[str] = None

    @field_validator("access_token", "api_key", "refresh_token", mode="before")
    @classmethod
    def secret(cls, value):
        if value is None:
            return value
        value = clean_secret(value, field_name="FieldView token or key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the token or key without a header or whitespace")
        return value


class Input(BaseModel):
    model_config = ConfigDict(extra="ignore")

    @model_validator(mode="after")
    def filter_values(self):
        for name in ("occurredAfter", "occurredBefore", "updatedAfter"):
            value = getattr(self, name, None)
            if value is not None and value.tzinfo is None:
                raise ValueError("Use ISO 8601 timestamps with a timezone")
        after, before = getattr(self, "occurredAfter", None), getattr(self, "occurredBefore", None)
        if after is not None and before is not None and after > before:
            raise ValueError("Occurred-after must be at or before occurred-before")
        owner = getattr(self, "resourceOwnerId", None)
        if isinstance(owner, str):
            values = owner.split(",") if getattr(self, "operation", None) == "list_operations" else [owner]
            for value in values:
                UUID(value)
        return self


class Geometry(Input):
    type: Literal["Point", "Polygon", "MultiPolygon"]
    coordinates: list[Any] = Field(..., min_length=1)

    @model_validator(mode="after")
    def geojson(self):
        # The OpenAPI's string items contradict its own numeric GeoJSON example.
        def point(v):
            if not isinstance(v, list) or len(v) < 2 or any(type(n) not in (int, float) for n in v):
                raise ValueError("GeoJSON positions require numeric coordinates")
            if not -180 <= v[0] <= 180 or not -90 <= v[1] <= 90:
                raise ValueError("Use WGS84 longitude and latitude")
        if self.type == "Point":
            point(self.coordinates)
        else:
            polygons = [self.coordinates] if self.type == "Polygon" else self.coordinates
            for polygon in polygons:
                if not isinstance(polygon, list) or not polygon:
                    raise ValueError("A polygon requires a linear ring")
                for ring in polygon:
                    if not isinstance(ring, list) or len(ring) < 4 or ring[0] != ring[-1]:
                        raise ValueError("GeoJSON rings require at least four positions and must be closed")
                    for position in ring:
                        point(position)
        return self


@dataclass(frozen=True)
class Operation:
    label: str
    method: str
    path: str
    fields: tuple[str, ...] = ()
    query: tuple[str, ...] = ()
    body: tuple[str, ...] = ()
    paged: bool = False


OPERATIONS = {
    "list_fields": Operation("List Fields", "GET", "/v4/fields", ("fieldName",), ("fieldName",), paged=True),
    "get_field": Operation("Get Field", "GET", "/v4/fields/{fieldId}", ("fieldId",)),
    "list_operations": Operation("List Farm Operations", "GET", "/v4/operations/all", ("resourceOwnerId",), ("resourceOwnerId",)),
    "get_resource_owner": Operation("Get Resource Owner", "GET", "/v4/resourceOwners/{resourceOwnerId}", ("resourceOwnerId",)),
    "get_boundary": Operation("Get Boundary", "GET", "/v4/boundaries/{boundaryId}", ("boundaryId",)),
    "query_boundaries": Operation("Get Boundaries in Batch", "POST", "/v4/boundaries/query", ("ids",), body=("ids",)),
    "upload_boundary": Operation("Upload Boundary Geometry", "POST", "/v4/boundaries", ("geometry",), body=("geometry",)),
    "create_upload": Operation("Initiate Field Boundary Upload", "POST", "/v4/uploads", ("contentType", "md5", "length", "metadata", "recipient_email"), body=("contentType", "md5", "length", "metadata")),
    "upload_chunk": Operation("Upload Data Chunk", "PUT", "/v4/uploads/{uploadId}", ("uploadId", "content_range", "data_base64")),
    "get_upload_status": Operation("Get Upload Status", "GET", "/v4/uploads/{uploadId}/status", ("uploadId",)),
    "query_upload_statuses": Operation("Get Upload Statuses in Batch", "POST", "/v4/uploads/status/query", ("ids",), body=("ids",)),
    "create_export": Operation("Request Agronomic Export", "POST", "/v4/exports", ("contentType", "definition"), body=("contentType", "definition")),
    "get_export_status": Operation("Get Export Status", "GET", "/v4/exports/{exportId}/status", ("exportId",)),
    "download_export_chunk": Operation("Download Export Chunk", "GET", "/v4/exports/{exportId}/contents", ("exportId", "byte_range")),
    "list_scouting_observations": Operation("List Scouting Observations", "GET", "/v4/layers/scoutingObservations", ("occurredAfter", "occurredBefore"), ("occurredAfter", "occurredBefore"), paged=True),
    "get_scouting_observation": Operation("Get Scouting Observation", "GET", "/v4/layers/scoutingObservations/{scoutingObservationId}", ("scoutingObservationId",)),
}
for kind, wire in (("planting", "asPlanted"), ("application", "asApplied"), ("harvest", "asHarvested")):
    OPERATIONS["list_" + kind + "_activities"] = Operation("List " + kind.title() + " Activities", "GET", "/v4/layers/" + wire,
        ("resourceOwnerId", "occurredAfter", "occurredBefore", "updatedAfter"), ("resourceOwnerId", "occurredAfter", "occurredBefore", "updatedAfter"), paged=True)
    OPERATIONS["get_" + kind + "_summary"] = Operation("Get " + kind.title() + " Activity Summary", "GET", "/v4/layers/" + wire + "/{activityId}", ("activityId",))

TRIGGERS = {"on_updated_" + kind + "_activity": "list_" + kind + "_activities" for kind in ("planting", "application", "harvest")}


def _field(name, op):
    if name == "resourceOwnerId" and name in op.query:
        return (Optional[str], Field(None, title="Resource owner ID", description="Optional account UUID; farm operations also accept comma-separated UUIDs."))
    if name.endswith("Id"):
        return (UUID, Field(..., title=re.sub(r"([A-Z])", r" \1", name).title()))
    if name in {"occurredAfter", "occurredBefore", "updatedAfter"}:
        return (Optional[datetime], Field(None, title=name))
    if name == "fieldName":
        return (Optional[str], Field(None, min_length=3, title="Field name prefix"))
    if name == "ids":
        return (list[UUID], Field(..., min_length=1, max_length=100, title="IDs"))
    if name == "geometry":
        return (Geometry, Field(..., title="GeoJSON geometry"))
    if name == "contentType":
        if op.path == "/v4/exports":
            return (Literal["application/vnd.climate.acrsi.geojson", "application/vnd.climate.harvest.geojson"], Field(..., title="Export content type"))
        return (Literal["application/vnd.climate.field.geojson"], Field("application/vnd.climate.field.geojson", title="Content type", description="Field boundary GeoJSON upload; metadata and the file must follow the Field & Boundary Format."))
    if name == "definition":
        return (dict[str, Any], Field(..., title="Export definition", description="plantingStartDate/plantingEndDate or harvestStartDate/harvestEndDate, and resourceOwnerId, as documented for this content type."))
    if name == "metadata":
        return (Optional[dict[str, Any]], Field(None, title="Upload metadata"))
    if name == "length":
        return (int, Field(..., ge=1, le=524288000, title="Total file length in bytes"))
    if name == "md5":
        return (str, Field(..., pattern=r"^[A-Za-z0-9+/]{22}==$", title="Base64 MD5 checksum"))
    if name == "recipient_email":
        return (Optional[str], Field(None, title="Recipient account email"))
    if name == "content_range":
        return (Optional[str], Field(None, pattern=r"^bytes [0-9]+-[0-9]+/[0-9]+$", title="Content range", description="bytes start-end/total; contiguous 5 MiB chunks except the final chunk. Omit for a single complete chunk."))
    if name == "byte_range":
        return (str, Field(..., pattern=r"^bytes=[0-9]+-[0-9]+$", title="Byte range", description="bytes=start-end; use 1–5 MiB chunks except the final chunk."))
    if name == "data_base64":
        return (str, Field(..., min_length=4, max_length=6990508, title="Chunk bytes as base64", json_schema_extra={"contentMediaType": "application/octet-stream", "contentEncoding": "base64"}))
    raise ValueError(name)


class ClimatePollInput(PollTriggerConfigBase, Input):
    pass


def _make_model(name, op, trigger=False):
    extras = {"ui:hidden": True, "x-is-trigger": trigger, "x-display-name": op.label if not trigger else name.replace("_", " ").title()}
    fields = {"operation": (Literal[name], Field(name, json_schema_extra=extras))}
    fields.update({f: _field(f, op) for f in op.fields})
    if op.paged:
        fields["limit"] = (int, Field(100, ge=1, le=100, title="Page size"))
        if not trigger:
            fields["next_token"] = (Optional[str], Field(None, title="Next page token", description="X-Next-Token from the previous response; keep all filters unchanged."))
    return create_model("Climate" + "".join(x.title() for x in name.split("_")) + "Config", __base__=ClimatePollInput if trigger else Input, **fields)


CONFIG_MODELS = {name: _make_model(name, op) for name, op in OPERATIONS.items()}
CONFIG_MODELS.update({name: _make_model(name, OPERATIONS[target], True) for name, target in TRIGGERS.items()})
globals().update({model.__name__: model for model in CONFIG_MODELS.values()})
ClimateConfig = Annotated[Union[tuple(CONFIG_MODELS.values())], Field(discriminator="operation")]


class ClimateNodeConfig(NodeConfig[ClimateConfig, ClimateOAuthCredential]):
    pass


def partner_api_key(credential_key=None):
    value = credential_key or os.environ.get("CLIMATE_API_KEY")
    if not value:
        raise ValueError("Supply the onboarded partner API key or configure CLIMATE_API_KEY")
    value = clean_secret(value, field_name="Partner API key")
    if any(c.isspace() for c in value):
        raise ValueError("Paste the partner API key without whitespace")
    return value


class ClimateNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-climate"
    scope_registry = CLIMATE_SCOPES
    connection_evidence = ConnectionEvidence(operation="list_fields", noun="fields", label_keys=("name", "id"))
    edit_examples = ["List my FieldView fields", "Export this season's planting data", "Watch for updated harvest activities"]

    @classmethod
    def get_config_model(cls):
        return ClimateNodeConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.climate_oauth import refresh_access_token
        if not credential_data.get("refresh_token"):
            return credential_data
        return await freshen_oauth_credential(credential_data, pool=pool, user_id=user_id,
            credential_id=credential_id, refresh=refresh_access_token, provider="climate")

    async def _access_token(self, credential):
        if not credential.refresh_token:
            return credential.access_token
        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        from nodes.oauth.climate_oauth import refresh_access_token
        data = credential.model_dump()
        token = await ensure_fresh_oauth_token(credential_id=(self.node_data or {}).get("credential_id"),
            user_id=self.user_id, credential=data, refresh=refresh_access_token,
            provider="climate", caller_path="execute")
        for key in ("access_token", "refresh_token", "expires_at"):
            setattr(credential, key, data.get(key))
        return token

    async def _request(self, op, config, token, key, next_token=None):
        values = config.model_dump(mode="json", exclude_none=True)
        path = op.path
        for name in op.fields:
            if "{" + name + "}" in path:
                path = path.replace("{" + name + "}", quote(str(values[name]), safe=""))
        headers = {"Authorization": "Bearer " + token, "X-Api-Key": key, "Accept": "*/*"}
        if op.paged:
            headers["X-Limit"] = str(config.limit)
            if next_token:
                headers["X-Next-Token"] = next_token
        if values.get("recipient_email"):
            headers["X-Recipient-Email"] = values["recipient_email"]
        if config.operation == "download_export_chunk":
            start, end = map(int, config.byte_range.removeprefix("bytes=").split("-"))
            if not 0 <= start < end or end - start + 1 > 5242880:
                raise ValueError("Use a forward byte range of at most 5 MiB")
            headers["Range"] = config.byte_range
        params = {name: values[name] for name in op.query if name in values}
        body = {name: values[name] for name in op.body if name in values}
        kwargs = {"params": params, "headers": headers}
        if op.body:
            kwargs["json"] = body
        if config.operation == "upload_chunk":
            try:
                content = base64.b64decode(config.data_base64, validate=True)
            except ValueError:
                raise ValueError("Use valid base64 chunk bytes") from None
            content_range = config.content_range or f"bytes 0-{len(content) - 1}/{len(content)}"
            match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", content_range)
            start, end, total = map(int, match.groups())
            if not (0 <= start <= end < total <= 524288000) or len(content) != end - start + 1 or len(content) > 5242880:
                raise ValueError("Chunk bytes and Content-Range must agree within the 500 MiB upload limit")
            if start % 5242880 or (end + 1 < total and len(content) != 5242880):
                raise ValueError("Use contiguous 5 MiB chunks except for the final chunk")
            headers.update({"Content-Type": "application/octet-stream", "Content-Range": content_range})
            kwargs["content"] = content
        async with guarded_async_client(timeout=60, follow_redirects=False, trust_env=False) as client:
            response = await client.request(op.method, BASE_URL + path, **kwargs)
        if response.status_code not in {200, 201, 204, 206, 304}:
            # Provider messages can echo credentials; redact both secrets before surfacing.
            message = response.text[:2000]
            for secret in (token, key, self.config.credentials.refresh_token):
                if secret:
                    message = message.replace(secret, "[redacted]")
            raise ValueError(f"FieldView HTTP {response.status_code}: {message}")
        if config.operation == "download_export_chunk":
            if len(response.content) > 5242880:
                raise ValueError("FieldView download exceeds the requested chunk limit")
            return {"data_base64": base64.b64encode(response.content).decode(),
                "content_type": response.headers.get("Content-Type"),
                "content_range": response.headers.get("Content-Range")}, None, response.status_code
        if response.status_code in {204, 304}:
            data = {"results": []} if op.paged else {}
        else:
            data = response.json()
            if config.operation == "create_upload":
                data = {"id": str(UUID(data))}
            if not isinstance(data, dict):
                raise ValueError("Expected a FieldView JSON object")
            if "error" in data and config.operation != "get_export_status":
                raise ValueError("FieldView returned an error envelope")
        next_page = response.headers.get("X-Next-Token")
        if op.paged and response.status_code == 206 and not next_page:
            raise ValueError("FieldView partial response is missing X-Next-Token")
        return data, next_page, response.status_code

    async def execute(self, inputs):
        if not self.config or self.config.credentials is None:
            raise ValueError("Connect a Climate FieldView account")
        config = self.config.config
        name = config.operation
        self.scope_registry.require(name)
        target = TRIGGERS.get(name, name)
        op = OPERATIONS[target]
        # Validate content-dependent export requirements before sending any write.
        if target == "create_export":
            prefix = "planting" if config.contentType.endswith("acrsi.geojson") else "harvest"
            required = (prefix + "StartDate", prefix + "EndDate", "resourceOwnerId")
            if any(not config.definition.get(field) for field in required):
                raise ValueError("Export definition requires " + ", ".join(required))
        key = partner_api_key(self.config.credentials.api_key)
        token = await self._access_token(self.config.credentials)
        if name in TRIGGERS:
            items, seen, cursor = [], set(), None
            for _ in range(100):
                data, following, status = await self._request(op, config, token, key, cursor)
                rows = data.get("results")
                if not isinstance(rows, list) or any(not isinstance(row, dict) or not row.get("id") or not row.get("updatedAt") for row in rows):
                    raise ValueError("Activity response requires results with id and updatedAt")
                items.extend(rows)
                if status != 206:
                    break
                if following in seen:
                    raise ValueError("FieldView repeated an activity pagination token")
                seen.add(following)
                cursor = following
            else:
                raise ValueError("Activity poll exceeds 100 pages; narrow the time or account filter")
            fresh = await self._filter_unseen(items, lambda row: str(row["id"]) + ":" + str(row["updatedAt"]))
            output = {"activities": fresh, "activity_type": target.removeprefix("list_").removesuffix("_activities"), "new_activity_count": len(fresh)}
        else:
            data, cursor, status = await self._request(op, config, token, key, getattr(config, "next_token", None))
            payload = {"export": data} if target == "get_export_status" else data
            output = {**payload, "http_status": status, "next_token": cursor, "has_more": status == 206}
        await self.emit(output)
        return output

    @classmethod
    def should_propagate_output(cls, output, config):
        return bool(output.get("new_activity_count")) if config.get("operation") in TRIGGERS else True

    @classmethod
    def resolve_agent_event(cls, output):
        activities = output.get("activities") if isinstance(output, dict) else None
        if not isinstance(activities, list):
            return super().resolve_agent_event(output)
        if not activities:
            return None
        lines = [f"Activity {row['id']} updated {row['updatedAt']}; fields: {', '.join(row.get('fieldIds', []))}; occurred {row.get('startTime')} to {row.get('endTime')}" for row in activities[:20]]
        return {"text": f"FieldView {output.get('activity_type', 'agronomic')} activities in the connected account: " + str(len(activities)) + " new or updated.\n" + "\n".join(lines), "conversation_key": None}
