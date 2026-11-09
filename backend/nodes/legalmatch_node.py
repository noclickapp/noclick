"""LegalMatch QBI Service v1.0.0, pinned to its published OpenAPI contract.

These are QBI administrative operations, not a legal lead or case API.
The contract defines Basic authentication, no OAuth flow and no trigger source.
"""
from __future__ import annotations

import base64
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://qbi.legalmatch.com"
CONTRACT_URL = BASE_URL + "/openapi.json"


class LegalMatchBasicCredential(BaseModel):
    model_config = ConfigDict(
        title="LegalMatch QBI Account",
        extra="ignore",
        hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": CONTRACT_URL,
            "x-credential-instructions": "Enter your existing LegalMatch QBI service username and password. This is the QBI administrative service, not a LegalMatch consumer account. NoClick uses HTTP Basic authentication only at qbi.legalmatch.com. Reading sync status checks access, not identity or permission to write.",
        },
    )
    credential_type: Literal["legalmatch_basic"] = Field(
        "legalmatch_basic", json_schema_extra={"ui:hidden": True}
    )
    username: str = Field(..., min_length=1, max_length=1024, title="QBI username")
    password: str = Field(
        ...,
        min_length=1,
        max_length=4096,
        title="QBI password",
        repr=False,
        json_schema_extra={"ui:widget": "password"},
    )

    @field_validator("username", mode="before")
    @classmethod
    def valid_username(cls, value):
        if (
            not isinstance(value, str)
            or ":" in value
            or any(ord(c) < 32 or ord(c) == 127 for c in value)
        ):
            raise ValueError(
                "Enter a QBI username without a colon or control characters"
            )
        return value.strip()

    @field_validator("password", mode="before")
    @classmethod
    def valid_password(cls, value):
        value = clean_secret(value, field_name="QBI password")
        if any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Enter the password without control characters")
        return value


class _Operation(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class LegalMatchRunFullSyncConfig(_Operation):
    """Trigger Full Pipeline: Trigger the full sync pipeline (backfill → mapping → banner → reconcile → gap detection)."""

    operation: Literal["run_full_sync"] = Field(
        "run_full_sync", json_schema_extra={"ui:hidden": True}
    )


class LegalMatchRunBannerSyncConfig(_Operation):
    """Trigger Banner Sync: Manually trigger banner sync."""

    operation: Literal["run_banner_sync"] = Field(
        "run_banner_sync", json_schema_extra={"ui:hidden": True}
    )


class LegalMatchRunBackfillsConfig(_Operation):
    """Trigger All Backfills: Manually trigger all 4 backfill entity types sequentially."""

    operation: Literal["run_backfills"] = Field(
        "run_backfills", json_schema_extra={"ui:hidden": True}
    )
    mode: Literal["incremental", "full"] = Field("incremental", max_length=4096)


class LegalMatchRunMappingSyncConfig(_Operation):
    """Trigger Mapping Sync: Manually trigger mapping sync."""

    operation: Literal["run_mapping_sync"] = Field(
        "run_mapping_sync", json_schema_extra={"ui:hidden": True}
    )


class LegalMatchRunReconciliationConfig(_Operation):
    """Trigger Reconciliation: Manually trigger reconciliation."""

    operation: Literal["run_reconciliation"] = Field(
        "run_reconciliation", json_schema_extra={"ui:hidden": True}
    )


class LegalMatchRunGapDetectionConfig(_Operation):
    """Trigger Gap Detection: Manually trigger gap detection."""

    operation: Literal["run_gap_detection"] = Field(
        "run_gap_detection", json_schema_extra={"ui:hidden": True}
    )


class LegalMatchGetMappingSuggestionsConfig(_Operation):
    """Get Suggestions: Get suggested SF account matches for a QBO customer."""

    operation: Literal["get_mapping_suggestions"] = Field(
        "get_mapping_suggestions", json_schema_extra={"ui:hidden": True}
    )
    qbo_customer_id: str = Field(..., max_length=4096, min_length=1)


class LegalMatchGetSyncStatusConfig(_Operation):
    """Admin Sync Status: JSON endpoint polled by dashboard for real-time sync card updates."""

    operation: Literal["get_sync_status"] = Field(
        "get_sync_status", json_schema_extra={"ui:hidden": True}
    )


class LegalMatchGetGapSummaryConfig(_Operation):
    """Admin Gap Summary: JSON endpoint for gap summary — polled by dashboard after gap detection."""

    operation: Literal["get_gap_summary"] = Field(
        "get_gap_summary", json_schema_extra={"ui:hidden": True}
    )


class LegalMatchGetLearningInsightsConfig(_Operation):
    """Admin Learning Data: JSON API: all learning insights for programmatic access."""

    operation: Literal["get_learning_insights"] = Field(
        "get_learning_insights", json_schema_extra={"ui:hidden": True}
    )


class LegalMatchListLogsConfig(_Operation):
    """Admin Logs Raw: Parsed log entries as JSON array (for programmatic access)."""

    operation: Literal["list_logs"] = Field(
        "list_logs", json_schema_extra={"ui:hidden": True}
    )
    max_lines: int = Field(1000, ge=1, le=10000)
    level: str = Field("", max_length=4096)


class LegalMatchAssignMappingConfig(_Operation):
    """Admin Assign Mapping: Form handler: manually assign a QBO customer to an SF account."""

    operation: Literal["assign_mapping"] = Field(
        "assign_mapping", json_schema_extra={"ui:hidden": True}
    )
    qbo_customer_id: str = Field(..., max_length=4096, min_length=1)
    sf_account: str = Field(..., max_length=4096, min_length=1)
    match_method: str = Field("manual", max_length=4096)
    redirect_to: str = Field(
        "/admin/unmatched", max_length=4096, json_schema_extra={"ui:hidden": True}
    )


class LegalMatchMarkPaidConfig(_Operation):
    """Admin Mark Paid: Set grace_period_cleared = 1 for an attorney's qb_record — hides the payment banner."""

    operation: Literal["mark_paid"] = Field(
        "mark_paid", json_schema_extra={"ui:hidden": True}
    )
    sf_account: str = Field(..., max_length=4096, min_length=1)
    redirect_to: str = Field(
        "/admin/mappings", max_length=4096, json_schema_extra={"ui:hidden": True}
    )


class LegalMatchUnmarkPaidConfig(_Operation):
    """Admin Unmark Paid: Clear grace_period_cleared back to 0 — re-shows the payment banner."""

    operation: Literal["unmark_paid"] = Field(
        "unmark_paid", json_schema_extra={"ui:hidden": True}
    )
    sf_account: str = Field(..., max_length=4096, min_length=1)
    redirect_to: str = Field(
        "/admin/mappings", max_length=4096, json_schema_extra={"ui:hidden": True}
    )


class LegalMatchResolveGapConfig(_Operation):
    """Admin Resolve Gap: Resolve a single gap: dismissed, false_alarm, or fixed."""

    operation: Literal["resolve_gap"] = Field(
        "resolve_gap", json_schema_extra={"ui:hidden": True}
    )
    gap_id: int = Field(...)
    resolution: Literal["dismissed", "false_alarm", "fixed"] = Field(
        ..., max_length=4096, min_length=1
    )


class LegalMatchResolveAllGapsConfig(_Operation):
    """Admin Resolve All Gaps: Batch-resolve all open gaps of a specific type."""

    operation: Literal["resolve_all_gaps"] = Field(
        "resolve_all_gaps", json_schema_extra={"ui:hidden": True}
    )
    gap_type: str = Field(..., max_length=4096, min_length=1)
    resolution: str = Field("false_alarm", max_length=4096)


class LegalMatchGetBannerAuditStatusConfig(_Operation):
    """Admin Banner Audit Status: Current job state, for the page to poll. Cheap and read-only."""

    operation: Literal["get_banner_audit_status"] = Field(
        "get_banner_audit_status", json_schema_extra={"ui:hidden": True}
    )


class LegalMatchGetBannerAuditConfig(_Operation):
    """Admin Banner Audit Json: JSON API for banner audit — for programmatic/scheduled checks."""

    operation: Literal["get_banner_audit"] = Field(
        "get_banner_audit", json_schema_extra={"ui:hidden": True}
    )
    limit: int = Field(0, ge=0)


class LegalMatchAdjustMappingConfidenceConfig(_Operation):
    """Admin Adjust Confidence: Trigger L1 confidence adjustment: apply learned feedback to mapping confidence scores."""

    operation: Literal["adjust_mapping_confidence"] = Field(
        "adjust_mapping_confidence", json_schema_extra={"ui:hidden": True}
    )


class LegalMatchAcknowledgeReviewConfig(_Operation):
    """Admin Acknowledge Review: Accept a finding as reviewed-and-correct."""

    operation: Literal["acknowledge_review"] = Field(
        "acknowledge_review", json_schema_extra={"ui:hidden": True}
    )
    sf_account: str = Field(..., max_length=4096, min_length=1)
    qbo_customer_id: str = Field("", max_length=4096)
    reason: str = Field("", max_length=4096)
    finding_type: str = Field("owner_mismatch", max_length=4096)
    redirect_to: str = Field(
        "/admin/sf-validation", max_length=4096, json_schema_extra={"ui:hidden": True}
    )


class LegalMatchRevokeReviewConfig(_Operation):
    """Admin Revoke Review: Withdraw a verdict, bringing the finding back to the live list."""

    operation: Literal["revoke_review"] = Field(
        "revoke_review", json_schema_extra={"ui:hidden": True}
    )
    sf_account: str = Field(..., max_length=4096, min_length=1)
    finding_type: str = Field("owner_mismatch", max_length=4096)
    redirect_to: str = Field(
        "/admin/sf-validation", max_length=4096, json_schema_extra={"ui:hidden": True}
    )


LegalMatchOperation = Annotated[
    Union[
        LegalMatchRunFullSyncConfig,
        LegalMatchRunBannerSyncConfig,
        LegalMatchRunBackfillsConfig,
        LegalMatchRunMappingSyncConfig,
        LegalMatchRunReconciliationConfig,
        LegalMatchRunGapDetectionConfig,
        LegalMatchGetMappingSuggestionsConfig,
        LegalMatchGetSyncStatusConfig,
        LegalMatchGetGapSummaryConfig,
        LegalMatchGetLearningInsightsConfig,
        LegalMatchListLogsConfig,
        LegalMatchAssignMappingConfig,
        LegalMatchMarkPaidConfig,
        LegalMatchUnmarkPaidConfig,
        LegalMatchResolveGapConfig,
        LegalMatchResolveAllGapsConfig,
        LegalMatchGetBannerAuditStatusConfig,
        LegalMatchGetBannerAuditConfig,
        LegalMatchAdjustMappingConfidenceConfig,
        LegalMatchAcknowledgeReviewConfig,
        LegalMatchRevokeReviewConfig,
    ],
    Field(discriminator="operation"),
]


class LegalMatchNodeConfig(NodeConfig[LegalMatchOperation, LegalMatchBasicCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


ROUTES = {
    "run_full_sync": {
        "method": "POST",
        "path": "/sync/run-full",
        "path_fields": [],
        "query_fields": [],
        "form_fields": [],
    },
    "run_banner_sync": {
        "method": "POST",
        "path": "/sync/banner",
        "path_fields": [],
        "query_fields": [],
        "form_fields": [],
    },
    "run_backfills": {
        "method": "POST",
        "path": "/sync/backfill/all",
        "path_fields": [],
        "query_fields": ["mode"],
        "form_fields": [],
    },
    "run_mapping_sync": {
        "method": "POST",
        "path": "/sync/mapping",
        "path_fields": [],
        "query_fields": [],
        "form_fields": [],
    },
    "run_reconciliation": {
        "method": "POST",
        "path": "/sync/reconcile",
        "path_fields": [],
        "query_fields": [],
        "form_fields": [],
    },
    "run_gap_detection": {
        "method": "POST",
        "path": "/sync/gap-detection",
        "path_fields": [],
        "query_fields": [],
        "form_fields": [],
    },
    "get_mapping_suggestions": {
        "method": "GET",
        "path": "/mapping/{qbo_customer_id}/suggestions",
        "path_fields": ["qbo_customer_id"],
        "query_fields": [],
        "form_fields": [],
    },
    "get_sync_status": {
        "method": "GET",
        "path": "/admin/sync-status",
        "path_fields": [],
        "query_fields": [],
        "form_fields": [],
    },
    "get_gap_summary": {
        "method": "GET",
        "path": "/admin/gap-summary",
        "path_fields": [],
        "query_fields": [],
        "form_fields": [],
    },
    "get_learning_insights": {
        "method": "GET",
        "path": "/admin/learning/data",
        "path_fields": [],
        "query_fields": [],
        "form_fields": [],
    },
    "list_logs": {
        "method": "GET",
        "path": "/admin/logs/raw",
        "path_fields": [],
        "query_fields": ["max_lines", "level"],
        "form_fields": [],
    },
    "assign_mapping": {
        "method": "POST",
        "path": "/admin/assign",
        "path_fields": [],
        "query_fields": [],
        "form_fields": ["qbo_customer_id", "sf_account", "match_method", "redirect_to"],
    },
    "mark_paid": {
        "method": "POST",
        "path": "/admin/mark-paid",
        "path_fields": [],
        "query_fields": [],
        "form_fields": ["sf_account", "redirect_to"],
    },
    "unmark_paid": {
        "method": "POST",
        "path": "/admin/unmark-paid",
        "path_fields": [],
        "query_fields": [],
        "form_fields": ["sf_account", "redirect_to"],
    },
    "resolve_gap": {
        "method": "POST",
        "path": "/admin/gap/{gap_id}/resolve",
        "path_fields": ["gap_id"],
        "query_fields": [],
        "form_fields": ["resolution"],
    },
    "resolve_all_gaps": {
        "method": "POST",
        "path": "/admin/gaps/resolve-all",
        "path_fields": [],
        "query_fields": [],
        "form_fields": ["gap_type", "resolution"],
    },
    "get_banner_audit_status": {
        "method": "GET",
        "path": "/admin/banner-audit/status",
        "path_fields": [],
        "query_fields": [],
        "form_fields": [],
    },
    "get_banner_audit": {
        "method": "GET",
        "path": "/admin/banner-audit/json",
        "path_fields": [],
        "query_fields": ["limit"],
        "form_fields": [],
    },
    "adjust_mapping_confidence": {
        "method": "POST",
        "path": "/admin/learning/adjust-confidence",
        "path_fields": [],
        "query_fields": [],
        "form_fields": [],
    },
    "acknowledge_review": {
        "method": "POST",
        "path": "/admin/review/acknowledge",
        "path_fields": [],
        "query_fields": [],
        "form_fields": [
            "sf_account",
            "qbo_customer_id",
            "reason",
            "finding_type",
            "redirect_to",
        ],
    },
    "revoke_review": {
        "method": "POST",
        "path": "/admin/review/revoke",
        "path_fields": [],
        "query_fields": [],
        "form_fields": ["sf_account", "finding_type", "redirect_to"],
    },
}


def _redact(value, credential):
    secrets = (
        credential.password,
        base64.b64encode(
            (credential.username + ":" + credential.password).encode()
        ).decode(),
    )
    if isinstance(value, str):
        for secret in secrets:
            value = value.replace(secret, "[redacted]")
        return value
    if isinstance(value, dict):
        return {
            _redact(k, credential): _redact(v, credential) for k, v in value.items()
        }
    if isinstance(value, list):
        return [_redact(v, credential) for v in value]
    return value


class LegalMatchNode(WorkflowNode):
    integration_type = "automation-legalmatch"
    connection_evidence = ConnectionEvidence(
        noun="QBI sync status", operation="get_sync_status", proves="reachability"
    )

    @classmethod
    def get_config_model(cls):
        return LegalMatchNodeConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a LegalMatch QBI account")
        credential = self.config.credentials
        op = self.config.config
        route = ROUTES[op.operation]
        path = route["path"]
        for field in route["path_fields"]:
            value = str(getattr(op, field))
            if value in {".", ".."}:
                raise ValueError("Use a resource ID, not a path segment")
            path = path.replace("{" + field + "}", quote(value, safe=""))
        query = {
            k: getattr(op, k)
            for k in route["query_fields"]
            if getattr(op, k) is not None
        }
        form = {
            k: getattr(op, k)
            for k in route["form_fields"]
            if getattr(op, k) is not None
        }
        try:
            async with guarded_async_client(
                timeout=30, trust_env=False, follow_redirects=False
            ) as client:
                response = await client.request(
                    route["method"],
                    BASE_URL + path,
                    auth=httpx.BasicAuth(credential.username, credential.password),
                    headers={"Accept": "application/json"},
                    params=query,
                    **({"data": form} if route["form_fields"] else {}),
                )
        except (httpx.HTTPError, OSError):
            # No retries: a timed out write may already have been applied.
            raise ValueError(
                "LegalMatch QBI did not confirm the request; inspect writes before retrying"
            ) from None
        if not 200 <= response.status_code < 300:
            output = {
                "status": "error",
                "success": False,
                "http_status": response.status_code,
                "message": _redact(response.text, credential)[:2000]
                or "LegalMatch QBI rejected the request",
            }
        else:
            try:
                data = response.json()
            except ValueError:
                raise ValueError(
                    "LegalMatch QBI returned an undocumented non-JSON response; inspect writes before retrying"
                ) from None
            # The contract intentionally leaves JSON response shapes unconstrained.
            # Preserve them; do not infer resource IDs or completion from arbitrary fields.
            output = {
                "status": "success",
                "success": True,
                "operation": op.operation,
                "http_status": response.status_code,
                "data": _redact(data, credential),
            }
            if route["method"] != "GET":
                output["request_accepted"] = True
                output["completion_verified"] = False
        await self.emit(output)
        return output
