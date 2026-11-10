"""ID4i v1 asset tracking API, pinned to the provider's 1.0.2 contract.

Authentication follows the official developer guide's API-key HS512 JWT flow.
Operations each make one API call; polling reads every page before recording IDs.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from datetime import datetime
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, AfterValidator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin

BASE = "https://backend.id4i.de"
DOCS = "https://backend.id4i.de/docs/reference/en/reference.html"


def _segment(value: str) -> str:
    if not value or value in {".", ".."} or any(c in value for c in "/\\%?#") or any(ord(c) < 33 or ord(c) == 127 for c in value):
        raise ValueError("Use an ID or organization namespace, without URL syntax or spaces")
    return value


Segment = Annotated[str, Field(min_length=1, max_length=255), AfterValidator(_segment)]


class ID4iCredential(BaseModel):
    model_config = ConfigDict(title="ID4i API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://backend.id4i.de/#/apikeys",
        "x-credential-instructions": "In ID4i, create an API key with HMAC signing and the permissions your workflows need. Paste its UUID, its application secret and your organization namespace. NoClick signs a fresh two-minute HS512 JWT for each request. RSA keys are not supported.",
        "x-help-url": DOCS + "#_api_key_authentication_flow",
    })
    credential_type: Literal["id4i_api_key"] = Field("id4i_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key UUID", min_length=1, max_length=255, repr=False, json_schema_extra={"ui:widget": "password"})
    api_secret: str = Field(..., title="Application secret", min_length=1, max_length=4096, repr=False, json_schema_extra={"ui:widget": "password"})
    organization_id: Segment = Field(..., title="Organization namespace", description="For example de.acme. Used for the private organization connection read and as the default organization.")

    @model_validator(mode="after")
    def secrets(self):
        self.api_key = clean_secret(self.api_key, field_name="API key UUID")
        self.api_secret = clean_secret(self.api_secret, field_name="Application secret")
        if any(c.isspace() for c in self.api_key):
            raise ValueError("Paste the API key UUID without a header")
        return self


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _authorization(credential: ID4iCredential) -> str:
    now = int(time.time())
    header = _b64(json.dumps({"alg": "HS512", "typ": "API"}, separators=(",", ":")).encode())
    claims = _b64(json.dumps({"sub": credential.api_key, "iat": now, "exp": now + 120}, separators=(",", ":")).encode())
    message = (header + "." + claims).encode()
    signature = _b64(hmac.new(credential.api_secret.encode("utf-8"), message, hashlib.sha512).digest())
    return "Bearer " + header + "." + claims + "." + signature


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class Page(Input):
    offset: int = Field(0, ge=0, le=2147483647)
    limit: int = Field(100, ge=1, le=1000, description="Maximum items in this page; next_offset continues the same request.")


class Asset(Input):
    id4n: Segment = Field(..., title="GUID or collection ID")


class AssetPage(Page, Asset):
    pass


class Organization(Input):
    organization_id: Segment | None = Field(None, description="Defaults to the connected organization namespace.")


class OrganizationPage(Page, Organization):
    pass


class Window(Input):
    from_date: datetime | None = Field(None, description="Inclusive UTC date-time filter.")
    to_date: datetime | None = Field(None, description="UTC date-time upper bound.")

    @model_validator(mode="after")
    def dates(self):
        for value in (self.from_date, self.to_date):
            if value is not None and value.utcoffset() is None:
                raise ValueError("Date-time filters require an explicit UTC offset")
        if self.from_date and self.to_date and self.from_date >= self.to_date:
            raise ValueError("to_date must be after from_date")
        return self


class Visibility(Input):
    public: bool | None = None
    sharedOrganizationIds: list[Segment] | None = None


HistoryType = Literal['CREATED', 'DESTROYED', 'RECYCLED', 'SHIPMENT_PREPARED', 'STORED', 'RETRIEVED_FROM_STORAGE', 'PACKAGED', 'DISPATCHED', 'RECEIVED', 'DELIVERY_REFUSED', 'REPROCESSING_STARTED', 'REPROCESSING_STEP_STARTED', 'REPROCESSING_STEP_CANCELLED', 'REPROCESSING_STEP_FINISHED', 'REPROCESSING_CANCELLED', 'REPROCESSING_FINISHED', 'DISASSEMBLED', 'MAINTENANCE_STARTED', 'MAINTENANCE_STEP_STARTED', 'MAINTENANCE_STEP_CANCELLED', 'MAINTENANCE_STEP_FINISHED', 'MAINTENANCE_CANCELLED', 'MAINTENANCE_FINISHED', 'PRODUCTION_STARTED', 'PRODUCTION_CANCELLED', 'PRODUCTION_FINISHED', 'PRODUCTION_STEP_STARTED', 'PRODUCTION_STEP_CANCELLED', 'PRODUCTION_STEP_FINISHED', 'QUALITY_CHECK_PERFORMED']
AliasType = Literal['gtin', 'article', 'mapp', 'item', 'rfid', 'tracking', 'eclass', 'unspsc', 'product', 'material', 'reference']
CollectionType = Literal['ROUTING_COLLECTION', 'LOGISTIC_COLLECTION', 'LABELLED_COLLECTION']

class GetOrganization(Organization):
    operation: Literal["get_organization"] = Field("get_organization", title="Get Organization", json_schema_extra={"ui:hidden": True})


class GetGuid(Asset, Organization):
    operation: Literal["get_guid"] = Field("get_guid", title="Get Guid", json_schema_extra={"ui:hidden": True})


class CreateGuids(Organization):
    operation: Literal["create_guids"] = Field("create_guids", title="Create Guids", json_schema_extra={"ui:hidden": True})
    count: int = Field(1, ge=1, le=1000)
    length: int = Field(40, ge=7, le=255)


class UpdateGuid(Asset):
    operation: Literal["update_guid"] = Field("update_guid", title="Update Guid", json_schema_extra={"ui:hidden": True})
    physical_state: Literal["UNATTACHED", "ATTACHED", "DETACHED"]


class ListCollections(OrganizationPage):
    operation: Literal["list_collections"] = Field("list_collections", title="List Collections", json_schema_extra={"ui:hidden": True})
    collection_type: CollectionType | None = None
    label: str | None = None


class GetCollection(Asset):
    operation: Literal["get_collection"] = Field("get_collection", title="Get Collection", json_schema_extra={"ui:hidden": True})


class CreateCollection(Organization):
    operation: Literal["create_collection"] = Field("create_collection", title="Create Collection", json_schema_extra={"ui:hidden": True})
    collection_type: CollectionType
    length: int = Field(40, ge=6, le=255)
    label: str | None = Field(None, min_length=5, max_length=128)


class UpdateCollection(Asset):
    operation: Literal["update_collection"] = Field("update_collection", title="Update Collection", json_schema_extra={"ui:hidden": True})
    label: str = Field(..., min_length=5, max_length=128)


class DeleteCollection(Asset):
    operation: Literal["delete_collection"] = Field("delete_collection", title="Delete Collection", json_schema_extra={"ui:hidden": True})


class ListCollectionElements(AssetPage, Organization):
    operation: Literal["list_collection_elements"] = Field("list_collection_elements", title="List Collection Elements", json_schema_extra={"ui:hidden": True})


class AddCollectionElements(Asset):
    operation: Literal["add_collection_elements"] = Field("add_collection_elements", title="Add Collection Elements", json_schema_extra={"ui:hidden": True})
    id4ns: list[Segment] = Field(..., min_length=1, max_length=1000)


class RemoveCollectionElements(Asset):
    operation: Literal["remove_collection_elements"] = Field("remove_collection_elements", title="Remove Collection Elements", json_schema_extra={"ui:hidden": True})
    id4ns: list[Segment] = Field(..., min_length=1, max_length=1000)


class GetProperties(Asset, Organization):
    operation: Literal["get_properties"] = Field("get_properties", title="Get Properties", json_schema_extra={"ui:hidden": True})


class PatchProperties(Asset, Organization):
    operation: Literal["patch_properties"] = Field("patch_properties", title="Patch Properties", json_schema_extra={"ui:hidden": True})
    properties: dict[str, str] = Field(..., min_length=1, description="Property keys start with the organization namespace. Values are strings.")


class DeleteProperties(Asset, Organization):
    operation: Literal["delete_properties"] = Field("delete_properties", title="Delete Properties", json_schema_extra={"ui:hidden": True})
    properties: list[str] = Field(..., min_length=1, max_length=1000)


class SearchGuids(Page):
    operation: Literal["search_guids"] = Field("search_guids", title="Search Guids", json_schema_extra={"ui:hidden": True})
    alias: str = Field(..., min_length=1, max_length=255)
    alias_type: AliasType


class GetAliases(Asset):
    operation: Literal["get_aliases"] = Field("get_aliases", title="Get Aliases", json_schema_extra={"ui:hidden": True})


class AddAlias(Asset):
    operation: Literal["add_alias"] = Field("add_alias", title="Add Alias", json_schema_extra={"ui:hidden": True})
    alias_type: AliasType
    alias: str = Field(..., min_length=1, max_length=255)


class RemoveAlias(Asset):
    operation: Literal["remove_alias"] = Field("remove_alias", title="Remove Alias", json_schema_extra={"ui:hidden": True})
    alias_type: AliasType


class ListHistory(AssetPage, Window):
    operation: Literal["list_history"] = Field("list_history", title="List History", json_schema_extra={"ui:hidden": True})
    include_private: bool = True


class AddHistory(Asset, Organization):
    operation: Literal["add_history"] = Field("add_history", title="Add History", json_schema_extra={"ui:hidden": True})
    history_type: HistoryType
    additional_properties: dict[str, str] | None = None
    visibility: Visibility | None = None


class GetHistoryItem(Asset, Organization):
    operation: Literal["get_history_item"] = Field("get_history_item", title="Get History Item", json_schema_extra={"ui:hidden": True})
    sequence_id: int = Field(..., ge=0, le=2147483647)


class ListChanges(OrganizationPage, Window):
    operation: Literal["list_changes"] = Field("list_changes", title="List Changes", json_schema_extra={"ui:hidden": True})


class OnNewChange(PollTriggerConfigBase, Organization, Window):
    operation: Literal["on_new_change"] = Field("on_new_change", title="On New Organization Change", json_schema_extra={"ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers"})


class OnNewHistory(PollTriggerConfigBase, Asset, Window):
    operation: Literal["on_new_history"] = Field("on_new_history", title="On New GUID History Item", json_schema_extra={"ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers"})
    include_private: bool = True


OPERATIONS = {
    "get_organization": {"method": 'GET', "path": '/api/v1/organizations/{organization_id}', "query": {}, "body": {}, "raw": None, "paged": False},
    "get_guid": {"method": 'GET', "path": '/api/v1/guids/{id4n}', "query": {'organization_id': 'organizationId'}, "body": {}, "raw": None, "paged": False},
    "create_guids": {"method": 'POST', "path": '/api/v1/guids', "query": {}, "body": {'organization_id': 'organizationId', 'count': 'count', 'length': 'length'}, "raw": None, "paged": False},
    "update_guid": {"method": 'PATCH', "path": '/api/v1/guids/{id4n}', "query": {}, "body": {'physical_state': 'physicalState'}, "raw": None, "paged": False},
    "list_collections": {"method": 'GET', "path": '/api/v1/organizations/{organization_id}/collections', "query": {'offset': 'offset', 'limit': 'limit', 'collection_type': 'type', 'label': 'label'}, "body": {}, "raw": None, "paged": True},
    "get_collection": {"method": 'GET', "path": '/api/v1/collections/{id4n}', "query": {}, "body": {}, "raw": None, "paged": False},
    "create_collection": {"method": 'POST', "path": '/api/v1/collections', "query": {}, "body": {'organization_id': 'organizationId', 'collection_type': 'type', 'length': 'length', 'label': 'label'}, "raw": None, "paged": False},
    "update_collection": {"method": 'PATCH', "path": '/api/v1/collections/{id4n}', "query": {}, "body": {'label': 'label'}, "raw": None, "paged": False},
    "delete_collection": {"method": 'DELETE', "path": '/api/v1/collections/{id4n}', "query": {}, "body": {}, "raw": None, "paged": False},
    "list_collection_elements": {"method": 'GET', "path": '/api/v1/collections/{id4n}/elements', "query": {'organization_id': 'organizationId', 'offset': 'offset', 'limit': 'limit'}, "body": {}, "raw": None, "paged": True},
    "add_collection_elements": {"method": 'POST', "path": '/api/v1/collections/{id4n}/elements', "query": {}, "body": {'id4ns': 'id4ns'}, "raw": None, "paged": False},
    "remove_collection_elements": {"method": 'DELETE', "path": '/api/v1/collections/{id4n}/elements', "query": {}, "body": {'id4ns': 'id4ns'}, "raw": None, "paged": False},
    "get_properties": {"method": 'GET', "path": '/api/v1/id4ns/{id4n}/properties', "query": {'organization_id': 'organizationId'}, "body": {}, "raw": None, "paged": False},
    "patch_properties": {"method": 'PATCH', "path": '/api/v1/id4ns/{id4n}/properties', "query": {'organization_id': 'organizationId'}, "body": {}, "raw": 'properties', "paged": False},
    "delete_properties": {"method": 'DELETE', "path": '/api/v1/id4ns/{id4n}/properties', "query": {'organization_id': 'organizationId'}, "body": {}, "raw": 'properties', "paged": False},
    "search_guids": {"method": 'GET', "path": '/api/v1/search/guids', "query": {'alias': 'alias', 'alias_type': 'aliasType', 'offset': 'offset', 'limit': 'limit'}, "body": {}, "raw": None, "paged": True},
    "get_aliases": {"method": 'GET', "path": '/api/v1/id4ns/{id4n}/alias', "query": {}, "body": {}, "raw": None, "paged": False},
    "add_alias": {"method": 'POST', "path": '/api/v1/id4ns/{id4n}/alias/{alias_type}', "query": {}, "body": {'alias': 'alias'}, "raw": None, "paged": False},
    "remove_alias": {"method": 'DELETE', "path": '/api/v1/id4ns/{id4n}/alias/{alias_type}', "query": {}, "body": {}, "raw": None, "paged": False},
    "list_history": {"method": 'GET', "path": '/api/v1/history/{id4n}', "query": {'include_private': 'includePrivate', 'from_date': 'fromDate', 'to_date': 'toDate', 'offset': 'offset', 'limit': 'limit'}, "body": {}, "raw": None, "paged": True},
    "add_history": {"method": 'POST', "path": '/api/v1/history/{id4n}', "query": {}, "body": {'organization_id': 'organizationId', 'history_type': 'type', 'additional_properties': 'additionalProperties', 'visibility': 'visibility'}, "raw": None, "paged": False},
    "get_history_item": {"method": 'GET', "path": '/api/v1/history/{id4n}/{organization_id}/{sequence_id}', "query": {}, "body": {}, "raw": None, "paged": False},
    "list_changes": {"method": 'GET', "path": '/api/v1/changelog/organization/{organization_id}/', "query": {'from_date': 'fromDate', 'to_date': 'toDate', 'offset': 'offset', 'limit': 'limit'}, "body": {}, "raw": None, "paged": True},
}

ID4iOperation = Annotated[Union[GetOrganization, GetGuid, CreateGuids, UpdateGuid, ListCollections, GetCollection, CreateCollection, UpdateCollection, DeleteCollection, ListCollectionElements, AddCollectionElements, RemoveCollectionElements, GetProperties, PatchProperties, DeleteProperties, SearchGuids, GetAliases, AddAlias, RemoveAlias, ListHistory, AddHistory, GetHistoryItem, ListChanges, OnNewChange, OnNewHistory], Field(discriminator="operation")]

class ID4iNodeConfig(NodeConfig[ID4iOperation, ID4iCredential]):
    pass


def _redact(value, credential):
    if isinstance(value, str):
        for secret in (credential.api_key, credential.api_secret):
            value = value.replace(secret, "[redacted]")
        return value
    if isinstance(value, list):
        return [_redact(v, credential) for v in value]
    if isinstance(value, dict):
        return {k: _redact(v, credential) for k, v in value.items()}
    return value


class ID4iNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-id4i"
    connection_evidence = ConnectionEvidence(noun="organization", operation="get_organization", label_keys=("name", "namespace"))
    edit_examples = ["Create GUIDs for new products", "Add GUIDs to a collection", "Record a shipment in GUID history", "Watch changes in my organization"]

    @classmethod
    def get_config_model(cls):
        return ID4iNodeConfig

    @classmethod
    def parse_config(cls, config_data):
        credential = config_data.get("credentials") if isinstance(config_data, dict) else None
        if isinstance(credential, dict) and credential.get("credential_type", "id4i_api_key") != "id4i_api_key":
            raise ValueError("Connect an ID4i API key credential")
        return super().parse_config(config_data)

    @staticmethod
    async def _request(credential, method, path, *, params=None, body=None):
        authorization = _authorization(credential)
        try:
            async with httpx.AsyncClient(timeout=45, follow_redirects=False) as client:
                response = await client.request(method, BASE + path, params=params, json=body,
                    headers={"Authorization": authorization, "Accept": "application/json"})
        except httpx.RequestError:
            raise ValueError("ID4i request failed; write outcome is unknown, inspect the resource before retrying" if method != "GET" else "ID4i could not be reached") from None
        if not 200 <= response.status_code < 300:
            try:
                error = response.json()
                detail = error.get("message", "Request rejected") if isinstance(error, dict) else "Request rejected"
            except ValueError:
                detail = "Unexpected response"
            detail = str(detail).replace(authorization, "[redacted]").replace(authorization[7:], "[redacted]")
            raise ValueError(_redact(f"ID4i API error {response.status_code}: {detail}", credential))
        try:
            data = response.json() if response.content else None
        except ValueError:
            raise ValueError("ID4i returned invalid JSON; inspect write outcome before retrying") from None
        return data, response.status_code

    @classmethod
    async def _perform(cls, credential, operation):
        spec = OPERATIONS[operation.operation]
        values = operation.model_dump(mode="json", exclude_none=True)
        if "organization_id" in type(operation).model_fields:
            values.setdefault("organization_id", credential.organization_id)
        path = spec["path"]
        for field, value in values.items():
            path = path.replace("{" + field + "}", quote(str(value), safe=""))
        if "{" in path:
            raise ValueError("ID4i path parameter missing")
        params = {target: values[source] for source, target in spec["query"].items() if source in values}
        if operation.operation == "list_changes":
            params["messageMimeType"] = "text/plain"
        body = values[spec["raw"]] if spec["raw"] else {target: values[source] for source, target in spec["body"].items() if source in values}
        if operation.operation in {"patch_properties", "delete_properties"}:
            namespace = values["organization_id"] + "."
            if any(not key.startswith(namespace) for key in operation.properties):
                raise ValueError("Property keys must start with the selected organization namespace")
        data, code = await cls._request(credential, spec["method"], path, params=params or None,
            body=body if spec["body"] or spec["raw"] else None)
        result = {"status": "accepted" if code == 202 else "success", "operation": operation.operation, "http_status": code, "data": data}
        if spec["paged"] and code != 202:
            if not isinstance(data, dict) or not isinstance(data.get("elements"), list):
                raise ValueError("ID4i list response has no elements array")
            offset, limit = data.get("offset"), data.get("limit")
            total = data.get("total")
            if type(offset) is not int or type(limit) is not int or offset < 0 or limit < 0:
                raise ValueError("ID4i returned invalid pagination")
            count = len(data["elements"])
            if offset != operation.offset or count > operation.limit:
                raise ValueError("ID4i list page differs from the requested offset or limit")
            if total is not None and (type(total) is not int or total < 0):
                raise ValueError("ID4i returned invalid total")
            more = offset + count < total if total is not None else count == operation.limit
            if more and count == 0:
                raise ValueError("ID4i pagination did not advance")
            result["next_offset"] = offset + count if more else None
        return _redact(result, credential)

    async def _poll(self, credential, operation):
        history = isinstance(operation, OnNewHistory)
        values = operation.model_dump(exclude=set(PollTriggerConfigBase.model_fields) | {"operation"})
        values["operation"] = "list_history" if history else "list_changes"
        page_model = ListHistory if history else ListChanges
        offset, rows = 0, []
        for _ in range(100):
            result = await self._perform(credential, page_model(**values, offset=offset, limit=100))
            if result["http_status"] == 202:
                raise ValueError("ID4i has not returned the poll results yet")
            rows.extend(result["data"]["elements"])
            if result["next_offset"] is None:
                break
            if result["next_offset"] <= offset:
                raise ValueError("ID4i poll pagination did not advance")
            offset = result["next_offset"]
        else:
            raise ValueError("ID4i poll exceeds 100 pages; narrow the date window before polling")
        def identity(row):
            if not isinstance(row, dict):
                raise ValueError("ID4i poll item must be an object")
            if history:
                if not isinstance(row.get("organizationId"), str) or type(row.get("sequenceId")) is not int:
                    raise ValueError("ID4i history item lacks its documented identity")
                return row["organizationId"] + ":" + str(row["sequenceId"])
            if not isinstance(row.get("id"), str) or not row["id"]:
                raise ValueError("ID4i change entry lacks its documented ID")
            return row["id"]
        identities = [identity(row) for row in rows]
        if len(set(identities)) != len(identities):
            raise ValueError("ID4i repeated an item across poll pages")
        fresh = await self._filter_unseen(rows, identity)
        return {"status": "success", "operation": operation.operation, "id4n": getattr(operation, "id4n", None),
            "organization_id": getattr(operation, "organization_id", None) or credential.organization_id,
            "history" if history else "changes": fresh, "new_item_count": len(fresh)}

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect an ID4i API key")
        credential, operation = self.config.credentials, self.config.config
        if isinstance(operation, (OnNewChange, OnNewHistory)):
            return await self._poll(credential, operation)
        return await self._perform(credential, operation)

    @classmethod
    def resolve_agent_event(cls, output):
        if not isinstance(output, dict) or output.get("operation") not in {"on_new_change", "on_new_history"}:
            return super().resolve_agent_event(output)
        history = output["operation"] == "on_new_history"
        rows = output.get("history" if history else "changes") or []
        if not rows:
            return None
        location = "GUID " + str(output.get("id4n")) if history else "organization " + str(output.get("organization_id"))
        lines = []
        for row in rows[:20]:
            if history:
                lines.append(f"{row.get('type', 'History item')} from {row.get('organizationId')} at {row.get('timestamp')} (sequence {row.get('sequenceId')}); properties: {json.dumps(row.get('additionalProperties', {}), ensure_ascii=False)}")
            else:
                lines.append(f"{row.get('message', 'Organization change')} at {row.get('timestamp')} (change {row.get('id')}); context: {json.dumps(row.get('messageProperties', {}), ensure_ascii=False)}")
        return {"text": f"ID4i: {len(rows)} new item(s) in {location}:\n" + "\n".join(lines), "conversation_key": None}
