"""Microsoft Graph Security v1.0: tenant alert triage, incidents and posture.

Contract: microsoftgraph/msgraph-metadata openapi/v1.0/openapi.yaml.
Polls drain all pages before advancing their seen baseline; updates are keyed
by resource ID and lastUpdateDateTime. Graph URLs never come from config.
"""
from __future__ import annotations
from typing import Annotated, Literal, Union
from urllib.parse import quote, urlsplit
import httpx
from pydantic import BaseModel, ConfigDict, Field, create_model
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from nodes.scopes.microsoft_graph_security import GRAPH_SECURITY_SCOPES

ROOT = "https://graph.microsoft.com/v1.0/security"

class MicrosoftGraphSecurityOAuth(BaseModel):
    model_config = ConfigDict(title="Microsoft Graph Security OAuth", json_schema_extra={
        "x-credential-type": "oauth", "x-oauth-provider": "microsoft",
        "x-oauth-scopes": sorted(GRAPH_SECURITY_SCOPES.declared_scopes()),
    })
    credential_type: Literal["microsoft_oauth"] = Field("microsoft_oauth", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., title="Access Token", json_schema_extra={"ui:widget": "password"})
    refresh_token: str = Field("", title="Refresh Token", json_schema_extra={"ui:widget": "password"})
    expires_at: str = ""
    email: str = ""

OPERATIONS = {'list_alerts': ('GET', '/alerts_v2', 'SecurityAlert.ReadWrite.All'), 'get_alert': ('GET', '/alerts_v2/{alert_id}', 'SecurityAlert.ReadWrite.All'), 'update_alert': ('PATCH', '/alerts_v2/{alert_id}', 'SecurityAlert.ReadWrite.All'), 'list_incidents': ('GET', '/incidents', 'SecurityIncident.ReadWrite.All'), 'get_incident': ('GET', '/incidents/{incident_id}', 'SecurityIncident.ReadWrite.All'), 'update_incident': ('PATCH', '/incidents/{incident_id}', 'SecurityIncident.ReadWrite.All'), 'list_incident_alerts': ('GET', '/incidents/{incident_id}/alerts', 'SecurityIncident.ReadWrite.All'), 'list_secure_scores': ('GET', '/secureScores', 'SecurityEvents.Read.All'), 'get_secure_score': ('GET', '/secureScores/{score_id}', 'SecurityEvents.Read.All'), 'list_control_profiles': ('GET', '/secureScoreControlProfiles', 'SecurityEvents.Read.All'), 'get_control_profile': ('GET', '/secureScoreControlProfiles/{profile_id}', 'SecurityEvents.Read.All'), 'on_updated_alert': ('GET', '/alerts_v2', 'SecurityAlert.ReadWrite.All'), 'on_updated_incident': ('GET', '/incidents', 'SecurityIncident.ReadWrite.All')}

class Page(BaseModel):
    top: int = Field(100, ge=1, le=100, title="Page Size")
    skip: int = Field(0, ge=0, title="Offset")
    filter: str | None = Field(None, title="OData Filter")

class AlertUpdate(BaseModel):
    status: Literal["new", "inProgress", "resolved"] = Field(..., title="Status")
    assigned_to: str | None = Field(None, title="Assigned To")
    classification: Literal["unknown", "falsePositive", "truePositive", "informationalExpectedActivity"] | None = None
    determination: Literal["unknown", "apt", "malware", "securityPersonnel", "securityTesting", "unwantedSoftware", "other", "multiStagedAttack", "compromisedAccount", "phishing", "maliciousUserActivity", "notMalicious", "notEnoughDataToValidate", "confirmedActivity", "lineOfBusinessApplication", "unknownFutureValue"] | None = None

class IncidentUpdate(BaseModel):
    status: Literal["active", "resolved", "redirected"] = Field(..., title="Status")
    assigned_to: str | None = Field(None, title="Assigned To")
    classification: Literal["unknown", "falsePositive", "truePositive", "informationalExpectedActivity"] | None = None
    determination: Literal["unknown", "apt", "malware", "securityPersonnel", "securityTesting", "unwantedSoftware", "other", "multiStagedAttack", "compromisedAccount", "phishing", "maliciousUserActivity", "notMalicious", "notEnoughDataToValidate", "confirmedActivity", "lineOfBusinessApplication", "unknownFutureValue"] | None = None
    display_name: str | None = None

MODELS = {}
for name, (method, path, _) in OPERATIONS.items():
    trigger = name.startswith("on_")
    base = PollTriggerConfigBase if trigger else (AlertUpdate if name == "update_alert" else IncidentUpdate if name == "update_incident" else Page if name.startswith("list_") else BaseModel)
    fields = {"operation": (Literal[name], Field(name, title=name.replace("_", " ").title(), json_schema_extra={"ui:hidden": True, **({"x-is-trigger": True, "x-category": "Triggers"} if trigger else {})}))}
    for part in path.split("/"):
        if part.startswith("{"):
            key = part[1:-1]
            fields[key] = (str, Field(..., min_length=1, title=key.replace("_", " ").title()))
    MODELS[name] = create_model("GraphSecurity" + name.title().replace("_", "") + "Config", __base__=base, **fields)
globals().update({model.__name__: model for model in MODELS.values()})
Operations = Annotated[Union[tuple(MODELS.values())], Field(discriminator="operation")]
class MicrosoftGraphSecurityConfig(NodeConfig[Operations, MicrosoftGraphSecurityOAuth]):
    pass

class MicrosoftGraphSecurityNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-microsoft-graph-security"
    borrowed_credential_types = frozenset({"microsoft_oauth"})
    credential_provider_labels = {"microsoft": "Microsoft Account"}
    scope_registry = GRAPH_SECURITY_SCOPES
    connection_evidence = ConnectionEvidence(operation="list_incidents", noun="security incidents")

    @classmethod
    def get_config_model(cls):
        return MicrosoftGraphSecurityConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.microsoft_oauth import refresh_access_token
        return await freshen_oauth_credential(credential_data, pool=pool, user_id=user_id, credential_id=credential_id, refresh=refresh_access_token, provider="microsoft")

    async def _token(self):
        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        from nodes.oauth.microsoft_oauth import refresh_access_token
        if not self.config.credentials:
            raise ValueError("Connect a Microsoft work or school account with Security permissions")
        return await ensure_fresh_oauth_token(credential_id=(self.node_data or {}).get("credential_id"), user_id=self.user_id, credential=self.config.credentials.model_dump(), refresh=refresh_access_token, provider="microsoft", caller_path="execute")

    async def _request(self, token, method, url, **kwargs):
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            response = await client.request(method, url, headers={"Authorization": "Bearer " + token, "Accept": "application/json"}, **kwargs)
        if response.is_error:
            try:
                message = response.json()["error"]["message"]
            except (ValueError, KeyError, TypeError):
                message = response.reason_phrase
            raise ValueError(f"Microsoft Graph Security ({response.status_code}): {message}")
        if not response.content:
            return {}
        return response.json()

    @staticmethod
    def _continuation(url, path):
        p = urlsplit(url)
        if p.scheme != "https" or p.netloc != "graph.microsoft.com" or p.path != "/v1.0/security" + path or p.fragment:
            raise ValueError("Graph continuation must stay on the same security resource")
        return url

    @classmethod
    def should_propagate_output(cls, output, config):
        return bool(output.get("items")) if config.get("operation", "").startswith("on_") else True

    @classmethod
    def resolve_agent_event(cls, output):
        if not output.get("operation", "").startswith("on_"):
            return super().resolve_agent_event(output)
        items = output.get("items", [])
        if not items:
            return None
        alert = output["operation"] == "on_updated_alert"
        lines = []
        for r in items:
            title = r.get("title") if alert else r.get("displayName")
            url = r.get("alertWebUrl") if alert else r.get("incidentWebUrl")
            incident = r.get("incidentId") if alert else r.get("id")
            lines.append(f"- {title or 'Security item'}: {r.get('severity')} / {r.get('status')}; owner {r.get('assignedTo')}; id {r.get('id')}; incident {incident}; {r.get('description') or ''} {url or ''}")
        return {"text": "Microsoft Graph Security: new or updated items\n" + "\n".join(lines), "conversation_key": None}

    async def execute(self, inputs):
        config = self.config.config
        name = config.operation
        self.scope_registry.require(name)
        method, path, _ = OPERATIONS[name]
        for key, value in config.model_dump().items():
            path = path.replace("{" + key + "}", quote(str(value), safe=""))
        token = await self._token()
        kwargs = {}
        if name.startswith("list_"):
            kwargs["params"] = {"$top": config.top, "$skip": config.skip}
            if config.filter:
                kwargs["params"]["$filter"] = config.filter
        if method == "PATCH":
            values = config.model_dump(exclude_none=True, exclude={"operation", "alert_id", "incident_id"})
            kwargs["json"] = { {"assigned_to": "assignedTo", "display_name": "displayName"}.get(k,k): v for k,v in values.items() }
        if method == "PATCH":
            kwargs["json"]["@odata.type"] = "#microsoft.graph.security." + ("alert" if name == "update_alert" else "incident")
        poll = name.startswith("on_")
        if poll:
            kwargs["params"] = {"$top": 100, "$filter": "lastUpdateDateTime ge 1970-01-01T00:00:00Z"}
        data = await self._request(token, method, ROOT + path, **kwargs)
        output = {"operation": name, "status": "success"}
        if name.startswith("list_") or poll:
            if not isinstance(data, dict) or not isinstance(data.get("value"), list):
                raise ValueError("Graph Security collection lacks value array")
            items = data["value"]
            next_url = data.get("@odata.nextLink")
            if poll:
                visited = set()
                while next_url:
                    if next_url in visited or len(visited) >= 100:
                        raise ValueError("Graph Security polling pagination did not finish")
                    visited.add(next_url)
                    page = await self._request(token, "GET", self._continuation(next_url, path))
                    if not isinstance(page.get("value"), list):
                        raise ValueError("Graph Security collection lacks value array")
                    items.extend(page["value"])
                    next_url = page.get("@odata.nextLink")
                for item in items:
                    if not item.get("id") or not item.get("lastUpdateDateTime"):
                        raise ValueError("Polling requires resource id and lastUpdateDateTime")
                items = await self._filter_unseen(items, lambda item: str(item["id"]) + ":" + item["lastUpdateDateTime"])
            return {**output, "items": items, "count": len(items), "next_link": next_url}
        return {**output, "data": data}
