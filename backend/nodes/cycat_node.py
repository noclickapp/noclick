"""CyCAT public API 0.9: one request per published operation.

Contract: https://api.cycat.org/swagger.json
Examples: https://www.cycat.org/services/
No account, key or OAuth flow exists in the published contract. Responses have
no declared schema, so preserve the provider JSON under data without inventing
record shapes. Pagination is an explicit start/end range, never a completeness
claim. Proposal JSON is queued for review, not proof of catalogue publication
(https://github.com/CyCat-project/cycat-service/blob/main/backend/bin/server.py).
No API webhook registration or created/updated-time list filtering is published.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from utils.ssrf import guarded_async_client

BASE = "https://api.cycat.org"


def _operation(name: str, label: str):
    return Field(name, title=label, json_schema_extra={"ui:hidden": True, "x-display-name": label})


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _UUID(_Input):
    uuid: str = Field(..., title="Resource UUID", description="UUID of a registered publisher, project or item.")

    @field_validator("uuid")
    @classmethod
    def valid_uuid(cls, value):
        UUID(value)
        return value


class _Page(_Input):
    start: int = Field(0, ge=0, le=1_000_000, title="Start Index", description="First index of the requested range.")
    end: int = Field(99, ge=0, le=1_000_000, title="End Index", description="Inclusive end index. Returns only this range, not the complete catalogue.")

    @model_validator(mode="after")
    def bounded_range(self):
        if self.end < self.start or self.end - self.start >= 1000:
            raise ValueError("Choose an ordered range of at most 1000 entries")
        return self


def _segment(value: str):
    if value in {".", ".."} or any(c in "/\\" or ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("Use one path segment without slashes or control characters")
    return value


class _Namespace(_Input):
    namespace: str = Field(..., min_length=1, max_length=512, title="Namespace", description="For example mitre-attack-id; use List Namespaces to discover names.")
    _namespace = field_validator("namespace")(_segment)


class Search(_Input):
    operation: Literal["search"] = _operation("search", "Search Cybersecurity Resources")
    searchquery: str = Field(..., min_length=1, max_length=4096, title="Search Query", description="CyCAT full-text query, for example APT33.")
    _query = field_validator("searchquery")(_segment)


class Lookup(_UUID):
    operation: Literal["lookup"] = _operation("lookup", "Look Up Resource")


class FindNamespaceUUIDs(_Namespace):
    operation: Literal["find_namespace_uuids"] = _operation("find_namespace_uuids", "Find UUIDs by Namespace ID")
    namespaceid: str = Field(..., min_length=1, max_length=4096, title="Namespace ID", description="For example T1216 in mitre-attack-id.")
    _namespaceid = field_validator("namespaceid")(_segment)


class GetRelationships(_UUID):
    operation: Literal["get_relationships"] = _operation("get_relationships", "Get Related Resource UUIDs")


class GetExpandedRelationships(_UUID):
    operation: Literal["get_expanded_relationships"] = _operation("get_expanded_relationships", "Get Expanded Relationships")


class GetChildren(_UUID):
    operation: Literal["get_children"] = _operation("get_children", "Get Child UUIDs")


class GetParents(_UUID):
    operation: Literal["get_parents"] = _operation("get_parents", "Get Parent UUIDs")


class ListProjects(_Page):
    operation: Literal["list_projects"] = _operation("list_projects", "List Projects")


class ListPublishers(_Page):
    operation: Literal["list_publishers"] = _operation("list_publishers", "List Publishers")


class ListNamespaces(_Input):
    operation: Literal["list_namespaces"] = _operation("list_namespaces", "List Namespaces")


class ListNamespaceIDs(_Namespace):
    operation: Literal["list_namespace_ids"] = _operation("list_namespace_ids", "List IDs in Namespace")


class ProposeResource(_Input):
    operation: Literal["propose_resource"] = _operation("propose_resource", "Propose Resource for Review")
    proposal: dict[str, JsonValue] = Field(..., title="Proposal JSON", description="JSON object to submit to CyCAT's review queue. CyCAT publishes no proposal field schema. A successful submission does not confirm publication.")


class GenerateUUID(_Input):
    operation: Literal["generate_uuid"] = _operation("generate_uuid", "Generate UUID")


class GetInfo(_Input):
    operation: Literal["get_info"] = _operation("get_info", "Get Service Information")


CycatConfig = Annotated[Union[Search, Lookup, FindNamespaceUUIDs, GetRelationships,
    GetExpandedRelationships, GetChildren, GetParents, ListProjects, ListPublishers,
    ListNamespaces, ListNamespaceIDs, ProposeResource, GenerateUUID, GetInfo], Field(discriminator="operation")]


class CycatFullConfig(NodeConfig[CycatConfig, None]):
    @field_validator("credentials", mode="before")
    @classmethod
    def public_api(cls, value):
        return None if value == {} else value


class CycatNode(WorkflowNode):
    integration_type = "automation-cycat"
    connection_evidence = ConnectionEvidence(operation="get_info", noun="public CyCAT service", proves="reachability")

    @classmethod
    def get_config_model(cls):
        return CycatFullConfig

    async def execute(self, inputs):
        config = self.config.config
        operation = config.operation
        method, body = "GET", None
        if isinstance(config, Search):
            path = "/search/" + quote(config.searchquery, safe="")
        elif isinstance(config, Lookup):
            path = "/lookup/" + config.uuid
        elif isinstance(config, FindNamespaceUUIDs):
            path = "/namespace/finduuid/" + quote(config.namespace, safe="") + "/" + quote(config.namespaceid, safe="")
        elif isinstance(config, GetExpandedRelationships):
            path = "/relationships/expanded/" + config.uuid
        elif isinstance(config, GetRelationships):
            path = "/relationships/" + config.uuid
        elif isinstance(config, GetChildren):
            path = "/child/" + config.uuid
        elif isinstance(config, GetParents):
            path = "/parent/" + config.uuid
        elif isinstance(config, ListProjects):
            path = f"/list/project/{config.start}/{config.end}"
        elif isinstance(config, ListPublishers):
            path = f"/list/publisher/{config.start}/{config.end}"
        elif isinstance(config, ListNamespaces):
            path = "/namespace/getall"
        elif isinstance(config, ListNamespaceIDs):
            path = "/namespace/getid/" + quote(config.namespace, safe="")
        elif isinstance(config, ProposeResource):
            method, path, body = "POST", "/propose", config.proposal
        elif isinstance(config, GenerateUUID):
            path = "/generate/uuid"
        elif isinstance(config, GetInfo):
            path = "/info"
        else:
            raise ValueError("Unsupported CyCAT operation")
        async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
            response = await client.request(method, BASE + path, headers={"Accept": "application/json"}, **({"json": body} if body is not None else {}))
        response.raise_for_status()
        if response.status_code != 200:
            raise ValueError("CyCAT did not return its documented success status")
        return {"status": "success", "operation": operation, "data": response.json()}
