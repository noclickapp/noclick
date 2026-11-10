"""Kubernetes REST operations pinned to the upstream API contract.

Pasted bearer tokens use the caller's RBAC permissions. Public HTTPS API servers
only; DNS/IP pinning and TLS verification also apply to custom-CA clusters.
Kubernetes watches are streams, not registered webhooks or timestamp poll APIs.
"""
from __future__ import annotations

import base64
import json
import re
import ssl
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client, normalize_https_origin

CREDENTIAL_TYPE = "kubernetes_bearer_token"
AUTH_DOC = "https://kubernetes.io/docs/reference/access-authn-authz/authentication/#putting-a-bearer-token-in-a-request"


def _origin(value):
    origin = normalize_https_origin(value, field_name="Kubernetes API server URL")
    if httpx.URL(origin).port == 0:
        raise ValueError("Use a valid Kubernetes API server port")
    return origin


def _json_object(value):
    try:
        obj = json.loads(value)
        if not isinstance(obj, dict) or not obj:
            raise ValueError()
    except (ValueError, TypeError, RecursionError):
        raise ValueError("Enter a nonempty JSON object") from None
    return value


class KubernetesBearerTokenCredential(BaseModel):
    model_config = ConfigDict(title="Kubernetes Bearer Token", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": AUTH_DOC,
            "x-credential-instructions": "Paste the cluster API server URL and an existing bearer token, without the Bearer prefix. The API server must be publicly reachable over HTTPS. RBAC must allow listing namespaces for the connection check and the resources you automate. For a private certificate authority, paste the base64 certificate-authority-data from kubeconfig (or a PEM certificate). TLS verification is always enabled. Replace expiring tokens manually."})
    credential_type: Literal["kubernetes_bearer_token"] = Field(CREDENTIAL_TYPE, json_schema_extra={"ui:hidden": True})
    api_server_url: str = Field(..., title="API Server URL", description="Public HTTPS cluster API origin, for example https://cluster.example.com:6443.")
    token: str = Field(..., min_length=1, max_length=16384, title="Bearer Token", repr=False,
        description="An existing token with the RBAC permissions needed by your operations; omit the Bearer prefix.", json_schema_extra={"ui:widget": "password"})
    ca_certificate: str | None = Field(None, max_length=100000, title="CA Certificate Data",
        description="Optional base64 certificate-authority-data from kubeconfig, or a PEM CA certificate. Leave empty to use public trusted certificate authorities.", json_schema_extra={"ui:widget": "textarea"})
    _server = field_validator("api_server_url", mode="before")(_origin)

    @field_validator("token", mode="before")
    @classmethod
    def bearer(cls, value):
        value = clean_secret(value, field_name="Bearer token", key=True)
        if not re.fullmatch(r"[A-Za-z0-9._~+/-]+=*", value):
            raise ValueError("Paste the bearer token without a prefix or whitespace")
        return value

    @field_validator("ca_certificate", mode="before")
    @classmethod
    def ca(cls, value):
        if value is None or isinstance(value, str) and not value.strip():
            return None
        try:
            if not isinstance(value, str):
                raise ValueError()
            pem = value.strip() if "-----BEGIN CERTIFICATE-----" in value else base64.b64decode(value.strip(), validate=True).decode("ascii")
            if "PRIVATE KEY" in pem or "-----BEGIN CERTIFICATE-----" not in pem:
                raise ValueError()
            pem = pem.strip() + "\n"
            ssl.create_default_context(cadata=pem)
        except (ValueError, UnicodeError, ssl.SSLError):
            raise ValueError("Paste valid base64 certificate-authority-data or a PEM CA certificate, without a private key") from None
        return base64.b64encode(pem.encode("ascii")).decode("ascii")


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Namespaced(_Input):
    namespace: str = Field(..., min_length=1, max_length=63, pattern=r"^[a-z0-9](?:[-a-z0-9]*[a-z0-9])?$", title="Namespace")


class _Named(_Namespaced):
    name: str = Field(..., min_length=1, max_length=253, pattern=r"^[a-z0-9](?:[-a-z0-9.]*[a-z0-9])?$", title="Resource Name")


class _List(_Input):
    limit: int = Field(100, ge=1, le=500, title="Page Size")
    continue_token: str | None = Field(None, max_length=8192, title="Continue Token", description="Opaque metadata.continue from the previous page; keep the same selectors.")
    label_selector: str | None = Field(None, max_length=4096, title="Label Selector", description="Kubernetes selector, for example app=nginx.")
    field_selector: str | None = Field(None, max_length=4096, title="Field Selector", description="Only fields supported by this Kubernetes resource kind.")


class _NamespacedList(_Namespaced, _List):
    pass


class _Write(_Namespaced):
    dry_run: bool = Field(False, title="Dry Run", description="Validate without persisting changes (dryRun=All).")


class _Manifest(_Write):
    manifest_json: str = Field(..., max_length=1000000, title="Resource Manifest (JSON)", description="Complete resource object with apiVersion, kind, metadata.name and the desired spec/data. The namespace must match the selected namespace.", json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})
    _object = field_validator("manifest_json")(_json_object)

    @model_validator(mode="after")
    def manifest_scope(self):
        body = json.loads(self.manifest_json)
        metadata = body.get("metadata")
        if not isinstance(metadata, dict) or not isinstance(metadata.get("name"), str) or not metadata["name"]:
            raise ValueError("The manifest must include metadata.name")
        if metadata.get("namespace", self.namespace) != self.namespace:
            raise ValueError("The manifest namespace must match the selected namespace")
        expected = {"create_pod": ("v1", "Pod"), "create_deployment": ("apps/v1", "Deployment"),
            "create_service": ("v1", "Service"), "create_configmap": ("v1", "ConfigMap"), "create_job": ("batch/v1", "Job")}.get(self.operation)
        if expected and (body.get("apiVersion"), body.get("kind")) != expected:
            raise ValueError("Use the apiVersion and kind for this operation")
        return self


class _Patch(_Named, _Write):
    patch_json: str = Field(..., max_length=1000000, title="JSON Merge Patch", description="RFC 7386 merge patch. Arrays are replaced as a whole; null removes a field. For deployment images, include the complete containers array.", json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})
    _object = field_validator("patch_json")(_json_object)

    @model_validator(mode="after")
    def patch_scope(self):
        metadata = json.loads(self.patch_json).get("metadata", {})
        if not isinstance(metadata, dict) or metadata.get("name", self.name) != self.name or metadata.get("namespace", self.namespace) != self.namespace:
            raise ValueError("A patch cannot change the selected name or namespace")
        return self


class _Delete(_Named, _Write):
    propagation_policy: Literal["Background", "Foreground", "Orphan"] = Field("Background", title="Propagation Policy", description="How Kubernetes garbage-collects dependents. Deletion is asynchronous.")
    grace_period_seconds: int | None = Field(None, ge=0, title="Grace Period (Seconds)")


class _Scale(_Named, _Write):
    replicas: int = Field(..., ge=0, le=2147483647, title="Replicas", description="Desired deployment replicas; zero stops its pods.")


class _Logs(_Named):
    container: str | None = Field(None, max_length=253, title="Container", description="Required by Kubernetes for some multi-container pods.")
    tail_lines: int = Field(100, ge=1, le=10000, title="Tail Lines")
    since_seconds: int | None = Field(None, ge=1, title="Since Seconds")
    previous: bool = Field(False, title="Previous Container Instance")
    timestamps: bool = Field(False, title="Include Timestamps")


class ListNamespaces(_List):
    operation: Literal["list_namespaces"] = Field("list_namespaces", title="List Namespaces", json_schema_extra={"ui:hidden": True})


class ListNodes(_List):
    operation: Literal["list_nodes"] = Field("list_nodes", title="List Nodes", json_schema_extra={"ui:hidden": True})


class ListPods(_NamespacedList):
    operation: Literal["list_pods"] = Field("list_pods", title="List Pods", json_schema_extra={"ui:hidden": True})


class GetPod(_Named):
    operation: Literal["get_pod"] = Field("get_pod", title="Get Pod", json_schema_extra={"ui:hidden": True})


class CreatePod(_Manifest):
    operation: Literal["create_pod"] = Field("create_pod", title="Create Pod", json_schema_extra={"ui:hidden": True})


class DeletePod(_Delete):
    operation: Literal["delete_pod"] = Field("delete_pod", title="Delete Pod", json_schema_extra={"ui:hidden": True})


class GetPodLogs(_Logs):
    operation: Literal["get_pod_logs"] = Field("get_pod_logs", title="Get Pod Logs", json_schema_extra={"ui:hidden": True})


class ListDeployments(_NamespacedList):
    operation: Literal["list_deployments"] = Field("list_deployments", title="List Deployments", json_schema_extra={"ui:hidden": True})


class GetDeployment(_Named):
    operation: Literal["get_deployment"] = Field("get_deployment", title="Get Deployment", json_schema_extra={"ui:hidden": True})


class CreateDeployment(_Manifest):
    operation: Literal["create_deployment"] = Field("create_deployment", title="Create Deployment", json_schema_extra={"ui:hidden": True})


class PatchDeployment(_Patch):
    operation: Literal["patch_deployment"] = Field("patch_deployment", title="Patch Deployment", json_schema_extra={"ui:hidden": True})


class DeleteDeployment(_Delete):
    operation: Literal["delete_deployment"] = Field("delete_deployment", title="Delete Deployment", json_schema_extra={"ui:hidden": True})


class ScaleDeployment(_Scale):
    operation: Literal["scale_deployment"] = Field("scale_deployment", title="Scale Deployment", json_schema_extra={"ui:hidden": True})


class ListServices(_NamespacedList):
    operation: Literal["list_services"] = Field("list_services", title="List Services", json_schema_extra={"ui:hidden": True})


class GetService(_Named):
    operation: Literal["get_service"] = Field("get_service", title="Get Service", json_schema_extra={"ui:hidden": True})


class CreateService(_Manifest):
    operation: Literal["create_service"] = Field("create_service", title="Create Service", json_schema_extra={"ui:hidden": True})


class DeleteService(_Delete):
    operation: Literal["delete_service"] = Field("delete_service", title="Delete Service", json_schema_extra={"ui:hidden": True})


class ListConfigmaps(_NamespacedList):
    operation: Literal["list_configmaps"] = Field("list_configmaps", title="List Configmaps", json_schema_extra={"ui:hidden": True})


class GetConfigmap(_Named):
    operation: Literal["get_configmap"] = Field("get_configmap", title="Get Configmap", json_schema_extra={"ui:hidden": True})


class CreateConfigmap(_Manifest):
    operation: Literal["create_configmap"] = Field("create_configmap", title="Create Configmap", json_schema_extra={"ui:hidden": True})


class PatchConfigmap(_Patch):
    operation: Literal["patch_configmap"] = Field("patch_configmap", title="Patch Configmap", json_schema_extra={"ui:hidden": True})


class DeleteConfigmap(_Delete):
    operation: Literal["delete_configmap"] = Field("delete_configmap", title="Delete Configmap", json_schema_extra={"ui:hidden": True})


class ListJobs(_NamespacedList):
    operation: Literal["list_jobs"] = Field("list_jobs", title="List Jobs", json_schema_extra={"ui:hidden": True})


class CreateJob(_Manifest):
    operation: Literal["create_job"] = Field("create_job", title="Create Job", json_schema_extra={"ui:hidden": True})


class ListEvents(_NamespacedList):
    operation: Literal["list_events"] = Field("list_events", title="List Events", json_schema_extra={"ui:hidden": True})


Operation = Annotated[Union[ListNamespaces, ListNodes, ListPods, GetPod, CreatePod, DeletePod, GetPodLogs, ListDeployments, GetDeployment, CreateDeployment, PatchDeployment, DeleteDeployment, ScaleDeployment, ListServices, GetService, CreateService, DeleteService, ListConfigmaps, GetConfigmap, CreateConfigmap, PatchConfigmap, DeleteConfigmap, ListJobs, CreateJob, ListEvents], Field(discriminator="operation")]


class KubernetesNodeConfig(NodeConfig[Operation, KubernetesBearerTokenCredential]):
    pass


ROUTES = {'list_namespaces': ('GET', '/api/v1/namespaces'),
 'list_nodes': ('GET', '/api/v1/nodes'),
 'list_pods': ('GET', '/api/v1/namespaces/{namespace}/pods'),
 'get_pod': ('GET', '/api/v1/namespaces/{namespace}/pods/{name}'),
 'create_pod': ('POST', '/api/v1/namespaces/{namespace}/pods'),
 'delete_pod': ('DELETE', '/api/v1/namespaces/{namespace}/pods/{name}'),
 'get_pod_logs': ('GET', '/api/v1/namespaces/{namespace}/pods/{name}/log'),
 'list_deployments': ('GET', '/apis/apps/v1/namespaces/{namespace}/deployments'),
 'get_deployment': ('GET', '/apis/apps/v1/namespaces/{namespace}/deployments/{name}'),
 'create_deployment': ('POST', '/apis/apps/v1/namespaces/{namespace}/deployments'),
 'patch_deployment': ('PATCH', '/apis/apps/v1/namespaces/{namespace}/deployments/{name}'),
 'delete_deployment': ('DELETE', '/apis/apps/v1/namespaces/{namespace}/deployments/{name}'),
 'scale_deployment': ('PUT', '/apis/apps/v1/namespaces/{namespace}/deployments/{name}/scale'),
 'list_services': ('GET', '/api/v1/namespaces/{namespace}/services'),
 'get_service': ('GET', '/api/v1/namespaces/{namespace}/services/{name}'),
 'create_service': ('POST', '/api/v1/namespaces/{namespace}/services'),
 'delete_service': ('DELETE', '/api/v1/namespaces/{namespace}/services/{name}'),
 'list_configmaps': ('GET', '/api/v1/namespaces/{namespace}/configmaps'),
 'get_configmap': ('GET', '/api/v1/namespaces/{namespace}/configmaps/{name}'),
 'create_configmap': ('POST', '/api/v1/namespaces/{namespace}/configmaps'),
 'patch_configmap': ('PATCH', '/api/v1/namespaces/{namespace}/configmaps/{name}'),
 'delete_configmap': ('DELETE', '/api/v1/namespaces/{namespace}/configmaps/{name}'),
 'list_jobs': ('GET', '/apis/batch/v1/namespaces/{namespace}/jobs'),
 'create_job': ('POST', '/apis/batch/v1/namespaces/{namespace}/jobs'),
 'list_events': ('GET', '/api/v1/namespaces/{namespace}/events')}


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, dict):
        return {k: _redact(v, token) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v, token) for v in value]
    return value


class KubernetesNode(WorkflowNode):
    integration_type = "automation-kubernetes"
    connection_evidence = ConnectionEvidence(noun="namespaces", operation="list_namespaces")
    edit_examples = ["List pods in this namespace", "Scale this deployment to three replicas", "Create a Kubernetes job"]

    @classmethod
    def get_config_model(cls):
        return KubernetesNodeConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a Kubernetes API server and bearer token")
        op, auth = self.config.config, self.config.credentials
        method, template = ROUTES[op.operation]
        path = template.format(**{key: quote(getattr(op, key), safe="") for key in ("namespace", "name") if "{" + key + "}" in template})
        params, body = {}, None
        if isinstance(op, _List):
            params["limit"] = op.limit
            for field, wire in (("continue_token", "continue"), ("label_selector", "labelSelector"), ("field_selector", "fieldSelector")):
                value = getattr(op, field)
                if value is not None:
                    params[wire] = value
        if isinstance(op, _Write) and op.dry_run:
            params["dryRun"] = "All"
        if isinstance(op, _Manifest):
            body = json.loads(op.manifest_json)
        elif isinstance(op, _Patch):
            body = json.loads(op.patch_json)
        elif isinstance(op, _Scale):
            body = {"apiVersion": "autoscaling/v1", "kind": "Scale", "metadata": {"name": op.name, "namespace": op.namespace}, "spec": {"replicas": op.replicas}}
        elif isinstance(op, _Delete):
            params["propagationPolicy"] = op.propagation_policy
            if op.grace_period_seconds is not None:
                params["gracePeriodSeconds"] = op.grace_period_seconds
        if isinstance(op, _Logs):
            params.update({"tailLines": op.tail_lines, "previous": str(op.previous).lower(), "timestamps": str(op.timestamps).lower(), "follow": "false"})
            if op.container is not None:
                params["container"] = op.container
            if op.since_seconds is not None:
                params["sinceSeconds"] = op.since_seconds
        headers = {"Authorization": "Bearer " + auth.token, "Accept": "text/plain" if isinstance(op, _Logs) else "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/merge-patch+json" if method == "PATCH" else "application/json"
        tls = ssl.create_default_context(cadata=base64.b64decode(auth.ca_certificate).decode("ascii")) if auth.ca_certificate else True
        async with guarded_async_client(verify=tls, trust_env=False, follow_redirects=False, timeout=30.0) as client:
            async with client.stream(method, auth.api_server_url + path, params=params, headers=headers,
                    **({"json": body} if body is not None else {})) as response:
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    raw.extend(chunk)
                    if len(raw) > 8 * 1024 * 1024:
                        raise ValueError("Kubernetes response exceeds 8 MiB; reduce the page size or log tail")
                if not 200 <= response.status_code < 300:
                    try:
                        message = json.loads(raw).get("message", "Kubernetes rejected the request")
                    except (ValueError, AttributeError):
                        message = "Kubernetes returned an unexpected response; check the API server URL"
                    result = {"status": "error", "http_status": response.status_code,
                        "error": _redact(str(message), auth.token)}
                elif isinstance(op, _Logs):
                    result = {"status": "success", "http_status": response.status_code, "logs": bytes(raw).decode("utf-8", errors="replace")}
                else:
                    try:
                        data = json.loads(raw)
                        if not isinstance(data, dict):
                            raise ValueError()
                    except (ValueError, UnicodeError):
                        raise ValueError("Kubernetes returned an invalid JSON resource") from None
                    if data.get("kind") == "Status" and data.get("status") == "Failure":
                        result = {"status": "error", "http_status": response.status_code, "error": data.get("message", "Kubernetes reported failure")}
                    else:
                        result = {"status": "success", "http_status": response.status_code, "data": data}
                        if isinstance(op, _List):
                            rows = data.get("items")
                            if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                                raise ValueError("Kubernetes returned an invalid resource list")
                            result["items"] = [{**row, "name": row.get("metadata", {}).get("name", "")} for row in rows]
                            result["continue_token"] = data.get("metadata", {}).get("continue") or None
                        if isinstance(op, _Delete):
                            result["deletion_requested"] = True
        result = _redact(result, auth.token)
        await self.emit(result)
        return result
