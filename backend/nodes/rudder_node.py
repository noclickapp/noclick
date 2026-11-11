"""Rudder configuration management API v12 (not RudderStack).

Contract: https://docs.rudder.io/api/v/12/openapi.yml
Inventory polling reads the complete, unpaginated accepted-node collection and
keys each revision by the documented id + lastInventoryDate. No webhook API is
published in this contract. The first poll establishes a baseline.
"""
from __future__ import annotations

import re
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote, urlsplit

from pydantic import BaseModel, ConfigDict, Field, Json, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from utils.ssrf import guarded_async_client


class RudderTokenCredential(BaseModel):
    model_config = ConfigDict(title="Rudder API Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://docs.rudder.io/api/v/12/",
            "x-credential-instructions": "In Rudder, open Administration → API Accounts and create an account with the permissions your operations need. Paste its token and your public HTTPS server origin. NoClick sends X-API-Token to that server and lists its managed nodes to check access. API accounts are separate from user accounts; the read does not identify a person.",
        })
    credential_type: Literal["rudder_api_token"] = Field("rudder_api_token", json_schema_extra={"ui:hidden": True})
    server_url: str = Field(..., title="Server URL", description="Public HTTPS origin, for example https://rudder.example.com. Omit /rudder/api/latest.")
    api_token: str = Field(..., min_length=1, max_length=4096, title="API Token", repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("server_url")
    @classmethod
    def server(cls, value):
        value = value.strip().rstrip("/")
        try:
            p = urlsplit(value)
            if (p.scheme != "https" or not p.hostname or "." not in p.hostname
                or p.username is not None or p.password is not None or p.port not in {None, 443}
                or p.path or p.query or p.fragment or "\\" in value
                or not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value)):
                raise ValueError()
        except ValueError:
            raise ValueError("Use the public HTTPS server origin without a path, credentials, query or fragment") from None
        return "https://" + p.hostname.lower()

    @field_validator("api_token")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API Token", key=True)
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the token without a header prefix or whitespace")
        return value


class Input(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)


def _segment(value):
    if value in {".", ".."} or any(c in "/\\" or ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("Use a single resource ID without path separators")
    return value


class NodeInput(Input):
    node_id: str = Field(..., min_length=1, max_length=255, title="Node ID", description="Rudder node UUID, or root for the policy server.")
    _id = field_validator("node_id")(_segment)


class RuleInput(Input):
    rule_id: str = Field(..., min_length=1, max_length=255, title="Rule ID")
    _id = field_validator("rule_id")(_segment)


class DirectiveInput(Input):
    directive_id: str = Field(..., min_length=1, max_length=255, title="Directive ID")
    _id = field_validator("directive_id")(_segment)


class GroupInput(Input):
    group_id: str = Field(..., min_length=1, max_length=255, title="Group ID")
    _id = field_validator("group_id")(_segment)


class ParameterInput(Input):
    parameter_id: str = Field(..., min_length=1, max_length=255, title="Parameter Name")
    _id = field_validator("parameter_id")(_segment)


class Change(Input):
    reason: str | None = Field(None, title="Change Reason", description="Sent in the query string. Required if your Rudder server enforces change messages.")
    change_request_name: str | None = Field(None, title="Change Request Name")
    change_request_description: str | None = Field(None, title="Change Request Description")


class Criterion(Input):
    objectType: str = Field(..., title="Object Type", description="For example node.")
    attribute: str = Field(..., title="Attribute", description="For example OS.")
    comparator: str = Field(..., title="Comparator", description="For example eq.")
    value: str = Field(..., title="Value", description="For example Linux.")


class NodeQuery(Input):
    select: str = Field("node", title="Selection")
    composition: Literal["and", "or"] = Field("and", title="Composition")
    where: list[Criterion] = Field(..., title="Criteria")


class Property(Input):
    name: str = Field(..., min_length=1, title="Property Name")
    value: Any = Field(..., title="Property Value", description="String or JSON value.")


class RuleFields(Input):
    display_name: str | None = Field(None, min_length=1, title="Rule Name")
    short_description: str | None = Field(None, title="Short Description")
    long_description: str | None = Field(None, title="Documentation")
    category: str | None = Field(None, title="Category ID")
    directives: list[str] | None = Field(None, title="Directive IDs")
    targets: list[str] | None = Field(None, title="Group Targets", description="Rudder target expressions, such as group:<uuid>.")
    enabled: bool | None = Field(None, title="Enabled")


class ListNodes(Input):
    operation: Literal["list_nodes"] = Field("list_nodes", title="List Managed Nodes", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})
    include: str = Field("default", title="Inventory Fields", description="minimal, default or full, optionally followed by comma-separated inventory field names.")
    query: NodeQuery | None = Field(None, title="Node Search")


class GetNode(NodeInput):
    operation: Literal["get_node"] = Field("get_node", title="Get Node", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})
    include: str = Field("default", title="Inventory Fields")


class UpdateNode(NodeInput, Change):
    operation: Literal["update_node"] = Field("update_node", title="Update Node Properties and Policy Mode", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})
    properties: list[Property] | None = Field(None, title="Properties", description="Properties to set; an empty property value removes the property according to Rudder semantics.")
    policy_mode: Literal["audit", "enforce", "default"] | None = Field(None, title="Policy Mode")
    state: Literal["enabled", "ignored", "empty-policies", "initializing", "preparing-eol"] | None = Field(None, title="Lifecycle State")


class ListPendingNodes(Input):
    operation: Literal["list_pending_nodes"] = Field("list_pending_nodes", title="List Pending Nodes", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})
    include: str = Field("default", title="Inventory Fields")


class SetPendingNodeStatus(NodeInput, Change):
    operation: Literal["set_pending_node_status"] = Field("set_pending_node_status", title="Accept or Refuse Pending Node", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})
    status: Literal["accepted", "refused"] = Field(..., title="New Status")


class ListRules(Input):
    operation: Literal["list_rules"] = Field("list_rules", title="List Rules", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})


class GetRule(RuleInput):
    operation: Literal["get_rule"] = Field("get_rule", title="Get Rule", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})


class CreateRule(RuleFields, Change):
    operation: Literal["create_rule"] = Field("create_rule", title="Create Rule", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})
    display_name: str = Field(..., min_length=1, title="Rule Name")
    category: str = Field(..., min_length=1, title="Parent Category ID")
    enabled: bool = Field(False, title="Enabled", description="New rules start disabled unless you explicitly enable them.")


class UpdateRule(RuleInput, RuleFields, Change):
    operation: Literal["update_rule"] = Field("update_rule", title="Update Rule", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})


class DeleteRule(RuleInput, Change):
    operation: Literal["delete_rule"] = Field("delete_rule", title="Delete Rule", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})


class ListDirectives(Input):
    operation: Literal["list_directives"] = Field("list_directives", title="List Directives", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})


class GetDirective(DirectiveInput):
    operation: Literal["get_directive"] = Field("get_directive", title="Get Directive", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})


class UpdateDirective(DirectiveInput, Change):
    operation: Literal["update_directive"] = Field("update_directive", title="Update Directive", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})
    display_name: str | None = Field(None, min_length=1, title="Directive Name")
    short_description: str | None = Field(None, title="Short Description")
    long_description: str | None = Field(None, title="Documentation")
    technique_version: str | None = Field(None, title="Technique Version")
    priority: int | None = Field(None, ge=0, le=10, title="Priority")
    enabled: bool | None = Field(None, title="Enabled")
    policy_mode: Literal["enforce", "audit"] | None = Field(None, title="Policy Mode")
    parameters: dict[str, Any] | None = Field(None, title="Technique Parameters", description="Rudder sections/vars object for the technique; obtain it from Get Directive.")


class ListGroups(Input):
    operation: Literal["list_groups"] = Field("list_groups", title="List Groups", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})


class GetGroup(GroupInput):
    operation: Literal["get_group"] = Field("get_group", title="Get Group", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})


class CreateGroup(Change):
    operation: Literal["create_group"] = Field("create_group", title="Create Group", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})
    display_name: str = Field(..., min_length=1, title="Group Name")
    description: str | None = Field(None, title="Description")
    query: NodeQuery = Field(..., title="Group Criteria")
    dynamic: bool = Field(True, title="Dynamic Membership")
    enabled: bool = Field(True, title="Enabled")


class UpdateGroup(GroupInput, Change):
    operation: Literal["update_group"] = Field("update_group", title="Update Group", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})
    query: NodeQuery = Field(..., title="Group Criteria", description="Explicit criteria are required because Rudder empties the group when this is omitted.")
    display_name: str | None = Field(None, min_length=1, title="Group Name")
    description: str | None = Field(None, title="Description")
    dynamic: bool | None = Field(None, title="Dynamic Membership")
    enabled: bool | None = Field(None, title="Enabled")
    category: str | None = Field(None, title="Category ID")


class DeleteGroup(GroupInput, Change):
    operation: Literal["delete_group"] = Field("delete_group", title="Delete Group", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})


class ReloadGroup(GroupInput, Change):
    operation: Literal["reload_group"] = Field("reload_group", title="Recompute Group Membership", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})


class ListParameters(Input):
    operation: Literal["list_parameters"] = Field("list_parameters", title="List Global Parameters", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})


class GetParameter(ParameterInput):
    operation: Literal["get_parameter"] = Field("get_parameter", title="Get Global Parameter", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})


class CreateParameter(Change):
    operation: Literal["create_parameter"] = Field("create_parameter", title="Create Global Parameter", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})
    parameter_id: str = Field(..., min_length=1, title="Parameter Name")
    value: Json[Any] = Field(..., title="Parameter Value (JSON)", description='Enter JSON: "text", "", null, true, 42, an object or an array.', json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})
    description: str | None = Field(None, title="Description")
    overridable: bool = Field(False, title="Overridable by Nodes")


class GetGlobalCompliance(Input):
    operation: Literal["get_global_compliance"] = Field("get_global_compliance", title="Get Global Compliance", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})


class GetNodesCompliance(Input):
    operation: Literal["get_nodes_compliance"] = Field("get_nodes_compliance", title="Get All Nodes Compliance", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})
    level: int = Field(1, ge=1, title="Detail Level", description="Depth of compliance detail; 1 rules, 2 directives, 3 components, 4 nodes, 5 values, 6 reports.")


class OnInventoryUpdated(PollTriggerConfigBase):
    operation: Literal["on_inventory_updated"] = Field("on_inventory_updated", title="On New or Updated Node Inventory", description="Poll the complete accepted-node list. Existing inventory revisions are baselined on arming; subsequent node ID + inventory timestamp pairs fire once. Inventory changes between polls can coalesce to the latest revision. Supports fleets of up to 10000 nodes.", json_schema_extra={"ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers"})


RudderOperation = Annotated[Union[ListNodes, GetNode, UpdateNode, ListPendingNodes, SetPendingNodeStatus, ListRules, GetRule, CreateRule, UpdateRule, DeleteRule, ListDirectives, GetDirective, UpdateDirective, ListGroups, GetGroup, CreateGroup, UpdateGroup, DeleteGroup, ReloadGroup, ListParameters, GetParameter, CreateParameter, GetGlobalCompliance, GetNodesCompliance, OnInventoryUpdated], Field(discriminator="operation")]


class RudderNodeConfig(NodeConfig[RudderOperation, RudderTokenCredential]):
    pass


# Each action makes exactly one request to its pinned OpenAPI operation.
ROUTES = {
    "list_nodes": ("GET", "/nodes"),
    "get_node": ("GET", "/nodes/{nodeId}"),
    "update_node": ("POST", "/nodes/{nodeId}"),
    "list_pending_nodes": ("GET", "/nodes/pending"),
    "set_pending_node_status": ("POST", "/nodes/pending/{nodeId}"),
    "list_rules": ("GET", "/rules"),
    "get_rule": ("GET", "/rules/{ruleId}"),
    "create_rule": ("PUT", "/rules"),
    "update_rule": ("POST", "/rules/{ruleId}"),
    "delete_rule": ("DELETE", "/rules/{ruleId}"),
    "list_directives": ("GET", "/directives"),
    "get_directive": ("GET", "/directives/{directiveId}"),
    "update_directive": ("POST", "/directives/{directiveId}"),
    "list_groups": ("GET", "/groups"),
    "get_group": ("GET", "/groups/{groupId}"),
    "create_group": ("PUT", "/groups"),
    "update_group": ("POST", "/groups/{groupId}"),
    "delete_group": ("DELETE", "/groups/{groupId}"),
    "reload_group": ("POST", "/groups/{groupId}/reload"),
    "list_parameters": ("GET", "/parameters"),
    "get_parameter": ("GET", "/parameters/{parameterId}"),
    "create_parameter": ("PUT", "/parameters"),
    "get_global_compliance": ("GET", "/compliance"),
    "get_nodes_compliance": ("GET", "/compliance/nodes"),
}
PATH_FIELDS = {"node_id": "nodeId", "rule_id": "ruleId", "directive_id": "directiveId", "group_id": "groupId", "parameter_id": "parameterId"}
QUERY_FIELDS = {"reason": "reason", "change_request_name": "changeRequestName", "change_request_description": "changeRequestDescription"}
BODY_FIELDS = {"display_name": "displayName", "short_description": "shortDescription", "long_description": "longDescription", "policy_mode": "policyMode", "technique_version": "techniqueVersion", "parameter_id": "id"}


class RudderNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-rudder"
    connection_evidence = ConnectionEvidence(noun="managed nodes", operation="list_nodes", label_keys=("hostname", "id"))

    @classmethod
    def get_config_model(cls):
        return RudderNodeConfig

    async def _request(self, method, path, *, params=None, body=None):
        credential = self.config.credentials
        # Keep the /latest server base exactly as published in the v12 contract.
        async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
            response = await client.request(method, credential.server_url + "/rudder/api/latest" + path,
                headers={"X-API-Token": credential.api_token, "Accept": "application/json"},
                params=params, **({"json": body} if body is not None else {}))
        payload = None
        if len(response.content) <= 10_000_000 and response.headers.get("Content-Type", "").split(";")[0].lower() == "application/json":
            try:
                payload = response.json()
            except ValueError:
                pass
        if response.status_code >= 300 or isinstance(payload, dict) and payload.get("result") == "error":
            detail = payload.get("errorDetails") if isinstance(payload, dict) else None
            error = detail if isinstance(detail, str) else "Rudder request failed"
            return {"status": "error", "http_status": response.status_code,
                    "error": error.replace(credential.api_token, "[redacted]")[:2000]}
        if not isinstance(payload, dict) or payload.get("result") != "success" or not isinstance(payload.get("data"), dict):
            raise ValueError("Expected a Rudder success envelope containing data; check the server URL")
        collection = path.split("/")[1]
        if collection in {"nodes", "rules", "directives", "groups", "parameters"}:
            if not isinstance(payload["data"].get(collection), list):
                raise ValueError("Rudder success envelope is missing its resource collection")
        return {"status": "success", **payload}

    async def _poll_inventory(self):
        # The v12 list has no pagination. Explicit projection includes each field
        # we read and avoids pulling full software/process inventories.
        result = await self._request("GET", "/nodes", params={"include": "minimal,lastInventoryDate"})
        if result["status"] != "success":
            return result
        rows = result["data"].get("nodes")
        if not isinstance(rows, list):
            raise ValueError("Rudder inventory list is missing nodes")
        if len(rows) > 10000:
            raise ValueError("Inventory polling supports up to 10000 nodes; no baseline was changed")
        revisions = []
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row["id"]:
                raise ValueError("Rudder inventory revision needs a node ID")
            timestamp = row.get("lastInventoryDate")
            # The schema documents this timestamp only when an inventory exists.
            if timestamp is None:
                continue
            if not isinstance(timestamp, str) or not timestamp:
                raise ValueError("Rudder inventory timestamp is invalid")
            revisions.append(row)
        fresh = await self._filter_unseen(revisions, lambda row: (row["id"] + ":" + row["lastInventoryDate"]))
        return {"status": "success", "nodes": fresh, "new_inventory_count": len(fresh)}

    async def execute(self, inputs):
        if not isinstance(self.config, RudderNodeConfig) or self.config.credentials is None:
            raise ValueError("Connect a Rudder API token")
        config = self.config.config
        if isinstance(config, OnInventoryUpdated):
            return await self._poll_inventory()
        method, path = ROUTES[config.operation]
        values = {key: value for key, value in config.model_dump(exclude={"operation"}).items() if value is not None}
        for key, wire in PATH_FIELDS.items():
            if "{" + wire + "}" in path:
                path = path.replace("{" + wire + "}", quote(str(values.pop(key)), safe=""))
        params = {wire: values.pop(key) for key, wire in QUERY_FIELDS.items() if key in values}
        if method == "GET":
            if "query" in values:
                import json
                values["query"] = json.dumps(values["query"], separators=(",", ":"))
            return await self._request(method, path, params={**params, **values})
        body = {BODY_FIELDS.get(key, key): value for key, value in values.items()}
        if isinstance(config, CreateParameter):
            body["value"] = config.value  # JSON null is a parameter value too.
        return await self._request(method, path, params=params, body=body if body else None)
