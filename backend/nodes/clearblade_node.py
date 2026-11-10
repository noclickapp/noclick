"""ClearBlade user-token API. Contract: published ClearBlade APIs 3.0 OpenAPI.

Webhooks in this API are inbound code-service endpoints, not subscriptions to
external callback URLs. Collection polling uses the documented SORT query.
"""
import hashlib
import json
from typing import Annotated, Literal, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from utils.ssrf import guarded_async_client


def segment(value):
    if value in {".", ".."} or any(ord(c) < 32 for c in value):
        raise ValueError("A resource name without controls or dot segments is required")
    return quote(value, safe="")


class ClearBladeCredential(BaseModel):
    model_config = ConfigDict(title="ClearBlade User Token", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://docs.clearblade.com/iotenterprise/user-authentication"})
    credential_type: Literal["clearblade_user_token"] = Field("clearblade_user_token", json_schema_extra={"ui:hidden": True})
    user_token: str = Field(..., min_length=1, title="User Token", description="Paste a ClearBlade user authentication token. Expired tokens must be replaced.", repr=False, json_schema_extra={"ui:widget": "password"})
    system_key: str = Field(..., min_length=1, title="System Key", description="System key from the ClearBlade console.")


class OperationBase(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CollectionBase(OperationBase):
    collection_name: str = Field(..., min_length=1, title="Collection Name")


class QueryBase(CollectionBase):
    query: dict = Field(default_factory=dict, title="Query", description="ClearBlade REST query object: FILTERS, SORT, PAGESIZE and PAGENUM.")


class ListRows(QueryBase):
    operation: Literal["list_rows"] = Field("list_rows", title="List Collection Rows", json_schema_extra={"ui:hidden": True})


class CreateRows(CollectionBase):
    operation: Literal["create_rows"] = Field("create_rows", title="Create Collection Rows", json_schema_extra={"ui:hidden": True})
    rows: list[dict] = Field(..., min_length=1, title="Rows", description="Array of column-value objects, as in the published ColumnField schema.")


class UpdateRows(CollectionBase):
    operation: Literal["update_rows"] = Field("update_rows", title="Update Collection Rows", json_schema_extra={"ui:hidden": True})
    query: dict = Field(..., min_length=1, title="Filter Query", description="Explicit query limiting the rows to update.")
    values: dict = Field(..., min_length=1, title="Column Values")


class DeleteRows(CollectionBase):
    operation: Literal["delete_rows"] = Field("delete_rows", title="Delete Collection Rows", json_schema_extra={"ui:hidden": True})
    query: dict = Field(..., min_length=1, title="Filter Query", description="Explicit query limiting the rows to delete permanently.")


class CountRows(QueryBase):
    operation: Literal["count_rows"] = Field("count_rows", title="Count Collection Rows", json_schema_extra={"ui:hidden": True})


class CollectionColumns(CollectionBase):
    operation: Literal["collection_columns"] = Field("collection_columns", title="Get Collection Columns", json_schema_extra={"ui:hidden": True})


class ListCollections(OperationBase):
    operation: Literal["list_collections"] = Field("list_collections", title="List Collections", json_schema_extra={"ui:hidden": True})


class ListDevices(OperationBase):
    operation: Literal["list_devices"] = Field("list_devices", title="List Devices", json_schema_extra={"ui:hidden": True})
    query: dict = Field(default_factory=dict, title="Query")


class CountDevices(OperationBase):
    operation: Literal["count_devices"] = Field("count_devices", title="Count Devices", json_schema_extra={"ui:hidden": True})


class DeviceColumns(OperationBase):
    operation: Literal["device_columns"] = Field("device_columns", title="Get Device Columns", json_schema_extra={"ui:hidden": True})


class CreateDevice(OperationBase):
    operation: Literal["create_device"] = Field("create_device", title="Create Device", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, title="Device Name")
    description: str = Field("", title="Description")
    state: str = Field("", title="State")
    type: str = Field("", title="Device Type")


class UpdateDevice(OperationBase):
    operation: Literal["update_device"] = Field("update_device", title="Update Device State", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, title="Device Name")
    state: str = Field(..., title="State")


class ExecuteService(OperationBase):
    operation: Literal["execute_service"] = Field("execute_service", title="Execute Code Service", json_schema_extra={"ui:hidden": True})
    service_name: str = Field(..., min_length=1, title="Service Name")
    parameters: dict = Field(default_factory=dict, title="Parameters")


class PublishMessage(OperationBase):
    operation: Literal["publish_message"] = Field("publish_message", title="Publish MQTT Message", json_schema_extra={"ui:hidden": True})
    topic: str = Field(..., min_length=1, title="Topic")
    payload: str = Field(..., title="Message")


class NewOrUpdatedRows(PollTriggerConfigBase):
    operation: Literal["on_new_or_updated_rows"] = Field("on_new_or_updated_rows", title="On New or Updated Collection Rows", json_schema_extra={"ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers"})
    collection_name: str = Field(..., min_length=1, title="Collection Name")
    time_column: str = Field(..., min_length=1, title="Created or Updated Time Column", description="Existing collection timestamp column to order descending. Monitors the latest 100 rows; changes outside that window are not observed.")


Operation = Annotated[Union[ListRows, CreateRows, UpdateRows, DeleteRows, CountRows, CollectionColumns, ListCollections, ListDevices, CountDevices, DeviceColumns, CreateDevice, UpdateDevice, ExecuteService, PublishMessage, NewOrUpdatedRows], Field(discriminator="operation")]


class ClearBladeNodeConfig(NodeConfig[Operation, ClearBladeCredential]):
    pass


class ClearBladeNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-clearblade"
    connection_evidence = ConnectionEvidence(operation="list_collections", noun="collections")

    @classmethod
    def get_config_model(cls):
        return ClearBladeNodeConfig

    @classmethod
    def should_propagate_output(cls, output, config):
        return bool(output.get("rows")) if config.get("operation") == "on_new_or_updated_rows" else True

    @classmethod
    def resolve_agent_event(cls, output):
        rows = output.get("rows")
        if not rows:
            return None
        return {"text": f"ClearBlade: {len(rows)} new or changed row(s) in collection {output['collection_name']} (system {output['system_key']}). Row contents and identifiers: " + json.dumps(rows, ensure_ascii=False), "conversation_key": None}

    async def execute(self, inputs):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a ClearBlade user token")
        c = self.config.config
        op = c.operation
        key = segment(credential.system_key)
        method, params, body = "GET", {}, None
        if isinstance(c, (CollectionBase, NewOrUpdatedRows)):
            collection = segment(c.collection_name)
            path = f"/api/v/1/collection/{key}/{collection}"
            if op in {"count_rows", "collection_columns"}:
                path = f"/api/v/2/collection/{key}/{collection}/" + ("count" if op == "count_rows" else "columns")
            if op in {"list_rows", "count_rows", "delete_rows"}:
                params["query"] = json.dumps(c.query)
            if op == "create_rows":
                method, body = "POST", c.rows
            elif op == "update_rows":
                method, body = "PUT", {"query": c.query, "$set": c.values}
            elif op == "delete_rows":
                method = "DELETE"
            elif op == "on_new_or_updated_rows":
                params["query"] = json.dumps({"SORT": [{"DESC": c.time_column}], "PAGESIZE": 100, "PAGENUM": 1})
        elif op == "list_collections":
            path = f"/api/v/3/allcollections/{key}"
        elif op in {"list_devices", "count_devices", "device_columns", "create_device", "update_device"}:
            path = f"/api/v/2/devices/{key}"
            if op == "list_devices":
                params["query"] = json.dumps(c.query)
            elif op in {"count_devices", "device_columns"}:
                path = f"/api/v/3/devices/{key}/" + ("count" if op == "count_devices" else "columns")
            else:
                path += "/" + segment(c.name)
                method = "POST" if op == "create_device" else "PUT"
                body = c.model_dump(exclude={"operation"}) if op == "create_device" else {"state": c.state}
        elif op == "execute_service":
            path, method, body = f"/api/v/1/code/{key}/{segment(c.service_name)}", "POST", c.parameters
        elif op == "publish_message":
            path, method, body = f"/api/v/1/message/{key}/publish", "POST", {"topic": c.topic, "body": c.payload}
        else:
            raise ValueError("Unsupported ClearBlade operation")
        headers = {"ClearBlade-UserToken": credential.user_token, "Accept": "application/json"}
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, "https://platform.clearblade.com" + path, headers=headers, params=params, **({"json": body} if body is not None else {}))
        response.raise_for_status()
        data = response.json() if response.content else None
        if op != "on_new_or_updated_rows" and isinstance(data, dict) and data.get("error"):
            raise ValueError("ClearBlade returned an error response")
        if op == "on_new_or_updated_rows":
            if not isinstance(data, dict) or not isinstance(data.get("DATA"), list):
                raise ValueError("Expected ClearBlade collection DATA rows")
            rows = await self._filter_unseen(data["DATA"], lambda row: hashlib.sha256(json.dumps(row, sort_keys=True).encode()).hexdigest())
            return {"rows": rows, "collection_name": c.collection_name, "system_key": credential.system_key}
        return {"data": data}
