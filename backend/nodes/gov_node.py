"""BC Data Catalogue v3 reads, pinned to the provider's OpenAPI 3.0.1.

The published contract has no writes or webhook registration. Dataset polling
uses package_search's documented metadata-modified ordering and watches
its first result window; narrow the query for busy catalogues.
"""
import hashlib
import json
from typing import Annotated, Any, Literal, Optional, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin

BASE_URL = "https://catalogue.data.gov.bc.ca/api/3"
DOCS = "https://docs.ckan.org/en/2.5/api/index.html"


class GovAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="BC Data Catalogue API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://catalogue.data.gov.bc.ca/",
            "x-credential-instructions": "Paste your existing BC Data Catalogue API key from your catalogue user profile. NoClick sends it in the ckan_api_key header documented by BC's OpenAPI. The connection check lists organizations this key can edit.",
        })
    credential_type: Literal["gov_api_key"] = Field("gov_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, max_length=4096,
                         json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API Key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without a header prefix or whitespace")
        return value


OPERATIONS = {
    'tag_list': ('List Tags', ('offset', 'limit'), ()),
    'get_site_status': ('Get Site Status', (), ()),
    'package_list': ('List Datasets', ('offset', 'limit'), ()),
    'package_search': ('Search Datasets', ('q',), ()),
    'package_show': ('Get Dataset', ('id',), ('id',)),
    'package_activity_list': ('List Dataset Activity', ('id', 'offset', 'limit'), ('id',)),
    'package_autocomplete': ('Autocomplete Datasets', ('q', 'limit'), ('q',)),
    'package_relationships_list': ('List Dataset Relationships', ('id', 'id2', 'rel'), ('id', 'id2')),
    'organization_activity_list': ('List Organization Activity', ('id',), ('id',)),
    'organization_follower_count': ('Get Organization Follower Count', ('id',), ('id',)),
    'organization_follower_list': ('List Organization Followers', ('id',), ('id',)),
    'list_my_organizations': ('List My Organizations', ('permission',), ()),
    'organization_show': ('Get Organization', ('id', 'include_datasets'), ('id',)),
    'organization_list': ('List Organizations', ('offset', 'limit'), ()),
    'organization_autocomplete': ('Autocomplete Organizations', ('q', 'limit'), ('q',)),
    'resource_search': ('Search Resources', ('query', 'fields', 'order_by', 'offset', 'limit'), ('query',)),
    'resource_show': ('Get Resource', ('id', 'include_tracking'), ('id',)),
    'related_list': ('List Related Items', ('id', 'dataset', 'type_filter', 'sort', 'featured'), ('id',)),
}

class GovOperationBase(BaseModel):
    model_config = ConfigDict(extra="ignore")


def _operation(name, label, parameters, required):
    fields = {}
    for parameter in parameters:
        kind = int if parameter in {"limit", "offset"} else bool if parameter in {"include_datasets", "include_tracking"} else str
        options = {"title": parameter.replace("_", " ").title()}
        if kind is int:
            options.update(ge=0, le=1000 if parameter == "limit" else 1000000)
        elif kind is str:
            options.update(min_length=1, max_length=4000)
        fields[parameter] = (kind if parameter in required else Optional[kind],
                             Field(... if parameter in required else None, **options))
    return create_model("Gov" + "".join(p.title() for p in name.split("_")) + "Config",
        __base__=GovOperationBase, __module__=__name__,
        operation=(Literal[name], Field(name, title=label, json_schema_extra={
            "ui:hidden": True, "x-display-name": label, "x-is-trigger": False,
            "x-category": "Datasets" if name.startswith(("package", "related")) else "Resources" if name.startswith("resource") else "Catalogue",
        })), **fields)


CONFIG_MODELS = {name: _operation(name, *details) for name, details in OPERATIONS.items()}
globals().update({model.__name__: model for model in CONFIG_MODELS.values()})


class GovOnDatasetChangeConfig(PollTriggerConfigBase):
    operation: Literal["on_new_or_updated_dataset"] = Field("on_new_or_updated_dataset",
        title="On New or Updated Dataset", json_schema_extra={"ui:hidden": True,
        "x-is-trigger": True, "x-category": "Triggers", "x-display-name": "On New or Updated Dataset"})
    q: str = Field("*:*", max_length=4000, title="Dataset Query",
        description="CKAN Solr query. Watches the first search window ordered by metadata_modified descending. Narrow this query if more datasets change between polls than fit in that window. Changes to returned metadata emit a new event; deletions are not detected.")


GovConfig = Annotated[Union[tuple(CONFIG_MODELS.values()) + (GovOnDatasetChangeConfig,)], Field(discriminator="operation")]


class GovNodeConfig(NodeConfig[GovConfig, GovAPIKeyCredential]):
    pass


class GovNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-gov"
    connection_evidence = ConnectionEvidence(operation="list_my_organizations", noun="catalogue organizations you can edit")

    @classmethod
    def get_config_model(cls):
        return GovNodeConfig

    async def _request(self, action, params):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a BC Data Catalogue API key")
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            response = await client.request("GET", BASE_URL + "/action/" + action,
                params=params, headers={"ckan_api_key": credential.api_key, "Accept": "application/json"})
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict) or body.get("success") is not True:
            error = body.get("error") if isinstance(body, dict) else None
            raise ValueError("BC Data Catalogue: " + json.dumps(error if error is not None else "Invalid action response"))
        if "result" not in body:
            raise ValueError("BC Data Catalogue response has no result")
        return body["result"]

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        config = self.config.config
        if isinstance(config, GovOnDatasetChangeConfig):
            result = await self._request("package_search", {"q": config.q, "sort": "metadata_modified desc"})
            if not isinstance(result, dict) or not isinstance(result.get("results"), list):
                raise ValueError("BC Data Catalogue search response has no dataset list")
            rows = result["results"]
            for row in rows:
                if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row["id"]:
                    raise ValueError("BC Data Catalogue dataset has no id")
            fresh = await self._filter_unseen(rows, lambda row: row["id"] + ":" +
                hashlib.sha256(json.dumps(row, sort_keys=True, ensure_ascii=False).encode()).hexdigest())
            return {"datasets": fresh, "new_or_updated_count": len(fresh)}
        params = config.model_dump(exclude_none=True, exclude={"operation"})
        return {"data": await self._request({"get_site_status": "status_show", "list_my_organizations": "organization_list_for_user"}.get(config.operation, config.operation), params)}

    @classmethod
    def should_propagate_output(cls, output, config):
        if config.get("operation") == "on_new_or_updated_dataset":
            return bool(output.get("new_or_updated_count"))
        return True

    @classmethod
    def resolve_agent_event(cls, output):
        rows = output.get("datasets")
        if not isinstance(rows, list):
            return super().resolve_agent_event(output)
        if not rows:
            return None
        lines = [f"- {row.get('title') or row['id']} (dataset {row['id']})" for row in rows[:10]]
        return {"text": "BC Data Catalogue: new or updated dataset metadata:\n" + "\n".join(lines),
                "conversation_key": None}
