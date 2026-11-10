"""OpenFEC public campaign-finance reads and receipt-date filing polling."""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from nodes.fec_operations import CONFIG_MODELS, OPERATIONS
from utils.ssrf import guarded_async_client

BASE = "https://api.open.fec.gov"


class FECApiKeyCredential(BaseModel):
    model_config = ConfigDict(title="OpenFEC API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://api.open.fec.gov/developers/",
        "x-credential-instructions": "Paste your OpenFEC API key. Public data reads verify that the key is accepted; they do not identify a private account.",
    })
    credential_type: Literal["fec_api_key"] = Field("fec_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, max_length=4096, repr=False,
                         json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if "{{" in value or "}}" in value or not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste a single API key without a header prefix")
        return value


class FECOnNewFilingConfig(PollTriggerConfigBase):
    operation: Literal["on_new_filing"] = Field("on_new_filing", json_schema_extra={
        "ui:hidden": True, "x-is-trigger": True, "x-display-name": "On New Filing", "x-category": "Triggers"})
    committee_id: str = Field(..., title="Committee ID", min_length=1, max_length=50, pattern=r"^[A-Za-z0-9_-]+$")
    min_receipt_date: str | None = Field(None, title="Received Since", pattern=r"\d{4}-\d{2}-\d{2}",
        description="Optional inclusive receipt date (YYYY-MM-DD). Narrow the window if it exceeds 1,000 filings. New file numbers, including amendments, fire once.")


FECConfig = Annotated[Union[tuple(CONFIG_MODELS) + (FECOnNewFilingConfig,)], Field(discriminator="operation")]


class FECNodeConfig(NodeConfig[FECConfig, FECApiKeyCredential]):
    model_config = ConfigDict(title="OpenFEC Node Configuration")


class FECNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-fec"
    connection_evidence = ConnectionEvidence(operation="list_candidates", noun="OpenFEC public candidates", proves="reachability")

    @classmethod
    def get_config_model(cls):
        return FECNodeConfig

    async def _request(self, path, params):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect an OpenFEC API key")
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request("GET", BASE + path, params=params,
                headers={"X-Api-Key": credential.api_key, "Accept": "application/json"})
        if response.status_code != 200:
            try:
                body = response.json()
                message = body.get("error", {}).get("message") if isinstance(body.get("error"), dict) else body.get("message")
            except (ValueError, AttributeError):
                message = None
            message = str(message or 'request failed').replace(credential.api_key, '[redacted]')
            raise ValueError(f"OpenFEC HTTP {response.status_code}: {message}")
        body = response.json()
        if not isinstance(body, dict) or not isinstance(body.get("results"), list) or any(not isinstance(row, dict) for row in body["results"]):
            raise ValueError("OpenFEC returned an invalid results page")
        if not isinstance(body.get("pagination"), dict):
            raise ValueError("OpenFEC returned invalid pagination")
        return body

    async def execute(self, inputs):
        config = self.config.config
        if isinstance(config, FECOnNewFilingConfig):
            params = {"committee_id": [config.committee_id], "sort": ["-receipt_date"], "per_page": 100}
            if config.min_receipt_date:
                params["min_receipt_date"] = config.min_receipt_date
            items = []
            for page in range(1, 11):
                body = await self._request("/v1/filings/", {**params, "page": page})
                items.extend(body["results"])
                pages = body["pagination"].get("pages")
                if not isinstance(pages, int) or pages < 0:
                    raise ValueError("OpenFEC returned invalid page count")
                if page >= pages:
                    break
            else:
                raise ValueError("More than 1,000 filings in this scope; narrow Received Since before polling")
            fresh = await self._filter_unseen(items, lambda row: str(row["file_number"]) if row.get("file_number") is not None else None)
            return {"filings": fresh, "new_filing_count": len(fresh)}
        path = OPERATIONS[config.operation]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        for name in tuple(values):
            marker = "{" + name + "}"
            if marker in path:
                path = path.replace(marker, quote(str(values.pop(name)), safe=""))
        return await self._request(path, values)

    @classmethod
    def resolve_agent_event(cls, output):
        import json
        filings = output.get("filings", [])
        if not filings:
            return None
        return {"title": "New OpenFEC filings", "conversation_key": None,
                "text": "New federal campaign-finance filings were received. Filing records include the filer/committee, receipt date, form and file number needed to investigate:\n" + json.dumps(filings, ensure_ascii=False, default=str)[:24000]}
