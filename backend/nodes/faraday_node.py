"""Faraday customer prediction workflows using the published v1 API.

Reruns acknowledge queued work; they never claim predictions are already built.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.faraday.ai/v1"


class FaradayAPIKeyCredential(BaseModel):
    model_config = ConfigDict(
        title="Faraday API Key",
        hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://faraday.ai/docs/abstractions/accounts",
            "x-credential-instructions": "Paste your Faraday account API key. NoClick sends it as a Bearer token to api.faraday.ai. The current-account read verifies which account accepts it.",
        },
    )
    credential_type: Literal["faraday_api_key"] = Field(
        "faraday_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ...,
        title="API Key",
        min_length=1,
        max_length=4096,
        repr=False,
        json_schema_extra={"ui:widget": "password"},
    )

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(
            c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value
        ):
            raise ValueError("Paste the API key without the Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Name(_Input):
    name: str = Field(..., min_length=1, max_length=64, title="Name")

    @field_validator("name")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Name must not be blank")
        return value


class _CohortFields(_Name):
    stream_name: str | None = Field(
        None,
        title="Event Stream Name",
        description="For example transaction. Omit to use the provider's default cohort population.",
    )
    min_count: float | None = Field(None, title="Minimum Event Count")
    max_count: float | None = Field(None, title="Maximum Event Count")
    min_value: float | None = Field(None, title="Minimum Event Value")
    max_value: float | None = Field(None, title="Maximum Event Value")


class _OutcomeFields(_Name):
    attainment_cohort_id: UUID = Field(..., title="Attainment Cohort ID")
    eligible_cohort_id: UUID | None = Field(
        None, title="Eligible Cohort ID", description="Omit to use the US population."
    )
    attrition_cohort_id: UUID | None = Field(None, title="Attrition Cohort ID")
    prediction_mode: Literal["auto", "static"] = Field("auto", title="Prediction Mode")
    preview: bool = Field(
        True,
        title="Preview",
        description="A preview outcome does not build until preview is disabled.",
    )


class GetCurrentAccount(_Input):
    operation: Literal["get_current_account"] = Field(
        "get_current_account",
        title="Get Current Account",
        json_schema_extra={"ui:hidden": True},
    )


class ListDatasets(_Input):
    operation: Literal["list_datasets"] = Field(
        "list_datasets", title="List Datasets", json_schema_extra={"ui:hidden": True}
    )


class GetDataset(_Input):
    operation: Literal["get_dataset"] = Field(
        "get_dataset", title="Get Dataset", json_schema_extra={"ui:hidden": True}
    )
    dataset_id: UUID = Field(..., title="Dataset Id")


class RerunDataset(_Input):
    operation: Literal["rerun_dataset"] = Field(
        "rerun_dataset",
        title="Rerun Dataset (Queue Build)",
        json_schema_extra={"ui:hidden": True},
    )
    dataset_id: UUID = Field(..., title="Dataset Id")


class ListCohorts(_Input):
    operation: Literal["list_cohorts"] = Field(
        "list_cohorts", title="List Cohorts", json_schema_extra={"ui:hidden": True}
    )


class GetCohort(_Input):
    operation: Literal["get_cohort"] = Field(
        "get_cohort", title="Get Cohort", json_schema_extra={"ui:hidden": True}
    )
    cohort_id: UUID = Field(..., title="Cohort Id")


class CreateCohort(_CohortFields):
    operation: Literal["create_cohort"] = Field(
        "create_cohort", title="Create Cohort", json_schema_extra={"ui:hidden": True}
    )


class UpdateCohort(_CohortFields):
    operation: Literal["update_cohort"] = Field(
        "update_cohort", title="Update Cohort", json_schema_extra={"ui:hidden": True}
    )
    cohort_id: UUID = Field(..., title="Cohort Id")


class DeleteCohort(_Input):
    operation: Literal["delete_cohort"] = Field(
        "delete_cohort",
        title="Delete Cohort Permanently",
        json_schema_extra={"ui:hidden": True},
    )
    cohort_id: UUID = Field(..., title="Cohort Id")


class RerunCohort(_Input):
    operation: Literal["rerun_cohort"] = Field(
        "rerun_cohort",
        title="Rerun Cohort (Queue Build)",
        json_schema_extra={"ui:hidden": True},
    )
    cohort_id: UUID = Field(..., title="Cohort Id")


class ListOutcomes(_Input):
    operation: Literal["list_outcomes"] = Field(
        "list_outcomes", title="List Outcomes", json_schema_extra={"ui:hidden": True}
    )


class GetOutcome(_Input):
    operation: Literal["get_outcome"] = Field(
        "get_outcome", title="Get Outcome", json_schema_extra={"ui:hidden": True}
    )
    outcome_id: UUID = Field(..., title="Outcome Id")


class CreateOutcome(_OutcomeFields):
    operation: Literal["create_outcome"] = Field(
        "create_outcome", title="Create Outcome", json_schema_extra={"ui:hidden": True}
    )


class UpdateOutcome(_Name):
    operation: Literal["update_outcome"] = Field(
        "update_outcome", title="Rename Outcome", json_schema_extra={"ui:hidden": True}
    )
    outcome_id: UUID = Field(..., title="Outcome Id")


class RerunOutcome(_Input):
    operation: Literal["rerun_outcome"] = Field(
        "rerun_outcome",
        title="Rerun Outcome (Queue Build)",
        json_schema_extra={"ui:hidden": True},
    )
    outcome_id: UUID = Field(..., title="Outcome Id")


class ListScopes(_Input):
    operation: Literal["list_scopes"] = Field(
        "list_scopes", title="List Scopes", json_schema_extra={"ui:hidden": True}
    )


class GetScope(_Input):
    operation: Literal["get_scope"] = Field(
        "get_scope", title="Get Scope", json_schema_extra={"ui:hidden": True}
    )
    scope_id: UUID = Field(..., title="Scope Id")


class RerunScope(_Input):
    operation: Literal["rerun_scope"] = Field(
        "rerun_scope",
        title="Rerun Scope (Queue Build)",
        json_schema_extra={"ui:hidden": True},
    )
    scope_id: UUID = Field(..., title="Scope Id")


class ListTargets(_Input):
    operation: Literal["list_targets"] = Field(
        "list_targets", title="List Targets", json_schema_extra={"ui:hidden": True}
    )


class GetTarget(_Input):
    operation: Literal["get_target"] = Field(
        "get_target", title="Get Target", json_schema_extra={"ui:hidden": True}
    )
    target_id: UUID = Field(..., title="Target Id")


class RerunTarget(_Input):
    operation: Literal["rerun_target"] = Field(
        "rerun_target",
        title="Rerun Target (Queue Build)",
        json_schema_extra={"ui:hidden": True},
    )
    target_id: UUID = Field(..., title="Target Id")


class LookupTarget(_Input):
    operation: Literal["lookup_target"] = Field(
        "lookup_target", title="Lookup Target", json_schema_extra={"ui:hidden": True}
    )
    target_id: UUID = Field(..., title="Target Id")
    email: str = Field(
        ...,
        title="Email",
        min_length=3,
        description="Email identifier for an identified Lookup API target. Sent inside identity_sets.",
    )


FaradayOperation = Annotated[
    Union[
        GetCurrentAccount,
        ListDatasets,
        GetDataset,
        RerunDataset,
        ListCohorts,
        GetCohort,
        CreateCohort,
        UpdateCohort,
        DeleteCohort,
        RerunCohort,
        ListOutcomes,
        GetOutcome,
        CreateOutcome,
        UpdateOutcome,
        RerunOutcome,
        ListScopes,
        GetScope,
        RerunScope,
        ListTargets,
        GetTarget,
        RerunTarget,
        LookupTarget,
    ],
    Field(discriminator="operation"),
]


class FaradayNodeConfig(NodeConfig[FaradayOperation, FaradayAPIKeyCredential]):
    pass


ROUTES = {
    "get_current_account": ("GET", "/accounts/current", None),
    "list_datasets": ("GET", "/datasets", None),
    "get_dataset": ("GET", "/datasets/{dataset_id}", "dataset_id"),
    "rerun_dataset": ("POST", "/datasets/{dataset_id}/force_update", "dataset_id"),
    "list_cohorts": ("GET", "/cohorts", None),
    "get_cohort": ("GET", "/cohorts/{cohort_id}", "cohort_id"),
    "create_cohort": ("POST", "/cohorts", None),
    "update_cohort": ("PATCH", "/cohorts/{cohort_id}", "cohort_id"),
    "delete_cohort": ("DELETE", "/cohorts/{cohort_id}", "cohort_id"),
    "rerun_cohort": ("POST", "/cohorts/{cohort_id}/force_update", "cohort_id"),
    "list_outcomes": ("GET", "/outcomes", None),
    "get_outcome": ("GET", "/outcomes/{outcome_id}", "outcome_id"),
    "create_outcome": ("POST", "/outcomes", None),
    "update_outcome": ("PATCH", "/outcomes/{outcome_id}", "outcome_id"),
    "rerun_outcome": ("POST", "/outcomes/{outcome_id}/force_update", "outcome_id"),
    "list_scopes": ("GET", "/scopes", None),
    "get_scope": ("GET", "/scopes/{scope_id}", "scope_id"),
    "rerun_scope": ("POST", "/scopes/{scope_id}/force_update", "scope_id"),
    "list_targets": ("GET", "/targets", None),
    "get_target": ("GET", "/targets/{target_id}", "target_id"),
    "rerun_target": ("POST", "/targets/{target_id}/force_update", "target_id"),
    "lookup_target": ("POST", "/targets/{target_id}/lookup", "target_id"),
}


def _redact(value, key):
    if isinstance(value, dict):
        return {
            k: _redact(v, key)
            for k, v in value.items()
            if k.lower()
            not in {
                "api_key",
                "access_token",
                "refresh_token",
                "password",
                "secret",
                "token",
            }
        }
    if isinstance(value, list):
        return [_redact(v, key) for v in value]
    if isinstance(value, str):
        return value.replace(key, "[redacted]")
    return value


class FaradayNode(WorkflowNode):
    integration_type = "automation-faraday"
    connection_evidence = ConnectionEvidence(
        noun="Faraday account", identity_operation="get_current_account"
    )

    @classmethod
    def get_config_model(cls):
        return FaradayNodeConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Faraday API key")
        config = self.config.config
        key = self.config.credentials.api_key
        method, path, id_field = ROUTES[config.operation]
        if id_field:
            path = path.replace("{" + id_field + "}", str(getattr(config, id_field)))
        body = None
        if config.operation.startswith(("create_", "update_")):
            body = config.model_dump(
                mode="json",
                exclude_none=True,
                exclude={"operation", id_field} if id_field else {"operation"},
            )
        elif config.operation == "lookup_target":
            body = {"identity_sets": [{"email": config.email}]}
        headers = {"Authorization": "Bearer " + key, "Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = (
                "application/merge-patch+json"
                if method == "PATCH"
                else "application/json"
            )
        try:
            async with guarded_async_client(
                timeout=30.0, follow_redirects=False, trust_env=False
            ) as client:
                response = await client.request(
                    method,
                    BASE_URL + path,
                    headers=headers,
                    **({"json": body} if body is not None else {}),
                )
        except (httpx.HTTPError, OSError):
            raise ValueError(
                "Faraday request did not complete; inspect the resource before retrying a write"
            ) from None
        expected = (
            202
            if config.operation.startswith("rerun_")
            else 204
            if method == "DELETE"
            else 201
            if config.operation.startswith("create_")
            else 200
        )
        if response.status_code != expected:
            note = "Faraday request was not confirmed"
            try:
                error = response.json()
                if isinstance(error, dict) and isinstance(error.get("note"), str):
                    note = error["note"][:2000]
            except ValueError:
                pass
            raise ValueError(
                _redact(f"Faraday HTTP {response.status_code}: {note}", key)
            )
        if expected in {202, 204}:
            result = {
                "status": "accepted" if expected == 202 else "success",
                "http_status": expected,
                "operation": config.operation,
                "data": {id_field: str(getattr(config, id_field))},
                "message": "Build queued; poll the resource status for completion"
                if expected == 202
                else "Deletion acknowledged",
            }
        else:
            if (
                response.headers.get("content-type", "").split(";", 1)[0].lower()
                != "application/json"
            ):
                raise ValueError("Faraday returned an unexpected content type")
            try:
                data = response.json()
            except ValueError:
                raise ValueError("Faraday returned invalid JSON") from None
            if (
                isinstance(data, dict)
                and data.get("error")
                and not (
                    config.operation == "lookup_target"
                    and data["error"]
                    == "Could not match an identity with the provided information"
                )
            ):
                raise ValueError(_redact(str(data.get("note") or data["error"]), key))
            if config.operation.startswith("list_"):
                if not isinstance(data, list) or any(
                    not isinstance(row, dict) or not row.get("id") for row in data
                ):
                    raise ValueError("Faraday returned an invalid resource list")
            elif not isinstance(data, dict) or (
                config.operation != "lookup_target"
                and (not data.get("id") or not isinstance(data.get("name"), str))
            ):
                raise ValueError("Faraday returned an invalid resource")
            result = {
                "status": "success",
                "http_status": expected,
                "operation": config.operation,
                "data": data,
            }
        if config.operation == "lookup_target":
            result["matched"] = bool(data.get("match_type")) and not bool(
                data.get("error")
            )
        result = _redact(result, key)
        await self.emit(result)
        return result
