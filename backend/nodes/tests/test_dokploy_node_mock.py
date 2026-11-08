"""Native Dokploy schema, parsed execute, fixed wire, projections and empty-object readbacks."""
from copy import deepcopy
from types import SimpleNamespace
import json
from unittest.mock import AsyncMock
import httpx
import pytest
from pydantic import TypeAdapter
from nodes import dokploy_node as D

USER = "00000000-0000-4000-8000-000000000001"
AUTH = {"credential_type": D.FAMILY, "instance_url": "https://deploy.fixture-company.com",
    "api_key": "synthetic-dokploy-key-only", "user_id": "dokploy-user", "organization_id": "dokploy-org", "api_contract": D.CONTRACT}


def args(operation):
    value = {"operation": operation}
    if operation not in {"get_current_user", "list_projects", "create_project"}:
        value["project_id"] = "project-one"
    if operation in {"get_environment", "list_services", "get_application", "get_compose", "list_application_deployments", "list_compose_deployments", "update_environment", "delete_environment"}:
        value["environment_id"] = "environment-one"
    if "application" in operation:
        value["application_id"] = "application-one"
    if "compose" in operation:
        value["compose_id"] = "compose-one"
    if operation.startswith(("create_", "update_", "delete_")):
        value["owned_disposable_confirmed"] = True
        if operation != "create_project": value["expected_project_name"] = "noclick-project-one"
        if operation in {"update_environment", "delete_environment"}: value["expected_environment_name"] = "noclick-environment-one"
        if not operation.startswith("delete_"): value.update(name="noclick-new-object", description="Synthetic metadata")
    return value


class World:
    def __init__(self):
        self.calls, self.after_request = [], None
        self.status, self.body_override = 200, None
        self.role = "owner"
        self.identity_user, self.identity_org = AUTH["user_id"], AUTH["organization_id"]
        self.projects = {"project-one": {"projectId": "project-one", "name": "noclick-project-one", "description": "Synthetic project",
            "organizationId": AUTH["organization_id"], "createdAt": "2026-10-06T00:00:00Z", "env": "private-provider-environment-value"}}
        self.envs = {"environment-one": {"environmentId": "environment-one", "projectId": "project-one", "name": "noclick-environment-one",
            "description": "", "isDefault": False, "env": "private-provider-environment-value", **{k: [] for k in D.SERVICE_KEYS}}}
        self.with_services()
    def with_services(self):
        self.envs["environment-one"]["applications"] = [{"applicationId": "application-one", "name": "Fixture app", "applicationStatus": "done", "env": "private-provider-secret"}]
        self.envs["environment-one"]["compose"] = [{"composeId": "compose-one", "name": "Fixture compose", "composeStatus": "idle", "composeFile": "private-provider-source"}]
    def empty(self):
        for env in self.envs.values():
            for key in D.SERVICE_KEYS: env[key] = []
    def env(self, key):
        raw = deepcopy(self.envs[key]); raw["project"] = deepcopy(self.projects[raw["projectId"]]); return raw
    def project(self, key):
        raw = deepcopy(self.projects[key]); raw["environments"] = [self.env(k) for k, v in self.envs.items() if v["projectId"] == key]; return raw
    def handle(self, request):
        self.calls.append(request)
        assert request.headers["x-api-key"] == AUTH["api_key"]
        assert request.headers["accept"] == "application/json"
        assert str(request.url).startswith(AUTH["instance_url"] + "/api/")
        name = request.url.path.removeprefix("/api/")
        query, body = dict(request.url.params), json.loads(request.content) if request.content else {}
        if self.status != 200: return httpx.Response(self.status, json={"code": "PRIVATE_ERROR", "message": "private-provider-body"})
        if self.body_override is not None: return httpx.Response(200, content=self.body_override, headers={"content-type": "application/json"})
        try:
            if name == "user.get":
                raw = {"id": "member-one", "userId": self.identity_user, "organizationId": self.identity_org, "role": self.role,
                    "canAccessToSSHKeys": True, "user": {"id": self.identity_user, "email": "private-provider@example.invalid", "apiKeys": [{"prefix": "private-provider-key-prefix"}], "stripeCustomerId": "private-provider-billing"}}
            elif name == "project.all": raw = [self.project(k) for k in self.projects]
            elif name == "project.one": raw = self.project(query["projectId"])
            elif name == "environment.one": raw = self.env(query["environmentId"])
            elif name == "environment.byProjectId": raw = [self.env(k) for k, v in self.envs.items() if v["projectId"] == query["projectId"]]
            elif name in {"deployment.all", "deployment.allByCompose"}:
                key = "applicationId" if name == "deployment.all" else "composeId"
                raw = [{"deploymentId": "deployment-one", key: query[key], "status": "done", "title": "Existing receipt",
                    "logPath": "private-provider-log", "errorMessage": "private-provider-error", "pid": "private-provider-pid", "createdAt": "2026-10-06T00:00:00Z"}]
            elif name == "project.create":
                assert set(body) <= {"name", "description"} and request.method == "POST"
                self.projects["created-project"] = {**body, "projectId": "created-project", "organizationId": AUTH["organization_id"]}
                self.envs["created-default"] = {"environmentId": "created-default", "projectId": "created-project", "name": "production", "isDefault": True, **{k: [] for k in D.SERVICE_KEYS}}
                raw = {"project": deepcopy(self.projects["created-project"]), "environment": deepcopy(self.envs["created-default"])}
            elif name == "project.update":
                assert set(body) <= {"projectId", "name", "description"}
                self.projects[body["projectId"]].update(body); raw = deepcopy(self.projects[body["projectId"]])
            elif name == "project.remove":
                assert set(body) == {"projectId"}
                raw = self.projects.pop(body["projectId"])
                self.envs = {k:v for k,v in self.envs.items() if v["projectId"] != body["projectId"]}
            elif name == "environment.create":
                assert set(body) <= {"projectId", "name", "description"}
                self.envs["created-environment"] = {**body, "environmentId": "created-environment", "isDefault": False, **{k: [] for k in D.SERVICE_KEYS}}
                raw = deepcopy(self.envs["created-environment"])
            elif name == "environment.update":
                assert set(body) <= {"environmentId", "name", "description"}
                self.envs[body["environmentId"]].update(body); raw = deepcopy(self.envs[body["environmentId"]])
            elif name == "environment.remove":
                assert set(body) == {"environmentId"}; raw = self.envs.pop(body["environmentId"])
            else: raise AssertionError("No unverified or effectful service procedure")
        except KeyError:
            return httpx.Response(404, json={"code": "NOT_FOUND"})
        if self.after_request: self.after_request(request)
        return httpx.Response(200, json=raw)


@pytest.fixture
def world(monkeypatch):
    value = World()
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(value.handle), **{k:v for k,v in kwargs.items() if k != "require_public"})
    monkeypatch.setattr(D, "guarded_async_client", client)
    return value


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", D.OPS)
async def test_every_discriminated_operation_schema_and_parsed_execute(operation, world):
    config = args(operation)
    parsed = TypeAdapter(D.DokployOperation).validate_python(config)
    assert parsed.operation == operation
    assert TypeAdapter(D.DokployOperation).json_schema()["discriminator"]["propertyName"] == "operation"
    if operation.startswith(("create_", "update_", "delete_")): world.empty()
    node_data = {"config": config, "credentials": deepcopy(AUTH)}
    node = D.DokployNode(node_id="fixture", node_type=D.NODE_TYPE, node_data=node_data,
        config=D.DokployNode.parse_config(node_data), sio=None, sid=None, user_id=USER)
    result = await node.execute({})
    assert result["read_completed"] and result["identity_verified"]
    assert "private-provider" not in json.dumps(result)
    assert all(r.url.path.removeprefix("/api/") in D.GET_PARAMETERS | D.POST_PARAMETERS for r in world.calls)
    if operation.startswith(("create_", "update_", "delete_")):
        assert result["mutation_completed"]
        assert len([r for r in world.calls if r.method == "POST"]) == 1
        if operation.startswith("delete_"): assert result["absence_readback"]


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["missing-identity", "wrong-user", "wrong-team"])
async def test_generic_openapi_example_and_foreign_identity_are_not_proof(world, bad):
    if bad == "missing-identity": world.body_override = b"{}"
    elif bad == "wrong-team": world.identity_org = "foreign"
    else: world.identity_user = "foreign"
    with pytest.raises((ValueError, RuntimeError)): await D.records(AUTH, args("list_services"))
    assert len(world.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 401, 403, 404, 422, 429, 500, 202, 204, 302])
async def test_status_refusal_has_no_raw_provider_body_or_retry(world, status):
    world.status = status
    with pytest.raises((ValueError, RuntimeError)) as caught: await D.records(AUTH, args("get_current_user"))
    assert "private-provider" not in str(caught.value) and AUTH["api_key"] not in str(caught.value)
    assert len(world.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [b"null", b'"private-provider"', b'{"id":"a","id":"b"}', b'{"code":"BAD_REQUEST","message":"private-provider"}', b'{"x":NaN}'])
async def test_malformed_envelopes_are_unverified(world, payload):
    world.body_override = payload
    with pytest.raises((ValueError, RuntimeError)): await D.records(AUTH, args("get_current_user"))


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["missing-parent", "foreign-environment", "foreign-service"])
async def test_scoped_picker_and_native_parent_witness(world, bad):
    if bad == "missing-parent":
        with pytest.raises(ValueError): await D.DokployNode.load_field_options("application_id", AUTH, {"environment_id": "environment-one"})
        assert not world.calls
    elif bad == "foreign-environment":
        world.envs["environment-one"]["projectId"] = "missing-project"
        with pytest.raises((ValueError, RuntimeError)): await D.records(AUTH, args("get_environment"))
    else:
        config = args("list_application_deployments"); config["application_id"] = "outside-service"
        with pytest.raises(ValueError): await D.records(AUTH, config)
        assert all(r.url.path != "/api/deployment.all" for r in world.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["member", "service", "missing-collection", "default", "changed-name", "confirmation"])
async def test_empty_object_controls_refuse_before_post(world, bad):
    config = args("delete_environment"); world.empty()
    if bad == "member": world.role = "member"
    elif bad == "service": world.with_services()
    elif bad == "missing-collection": del world.envs["environment-one"]["libsql"]
    elif bad == "default": world.envs["environment-one"]["isDefault"] = True
    elif bad == "changed-name": world.envs["environment-one"]["name"] = "customer-production"
    else: config["owned_disposable_confirmed"] = 1
    with pytest.raises((ValueError, RuntimeError)): await D.records(AUTH, config)
    assert not [r for r in world.calls if r.method == "POST"]


@pytest.mark.asyncio
async def test_body_allowlist_and_separate_readback(world):
    world.empty()
    result = await D.records(AUTH, {**args("update_project"), "env": "private-provider-injection", "organizationId": "outside", "_settings": {}})
    write = next(r for r in world.calls if r.method == "POST")
    assert set(json.loads(write.content)) == {"projectId", "name", "description"}
    assert result["record"]["name"] == "noclick-new-object"
    assert world.calls[-1].url.path == "/api/project.one"


@pytest.mark.asyncio
async def test_current_provider_owner_role_change_blocks_post(world):
    world.empty()
    def demote(request):
        if request.url.path == "/api/project.one":
            world.role = "member"
            world.after_request = None
    world.after_request = demote
    with pytest.raises(ValueError): await D.records(AUTH, args("delete_project"))
    assert not [r for r in world.calls if r.method == "POST"]


@pytest.mark.parametrize("origin", ["http://deploy.example.com", "https://127.0.0.1", "https://[::1]", "https://x.local", "https://deploy.example.com/api", "https://u:p@deploy.example.com", "https://deploy.example.com:3000", "https://deploy.example.com?token=a"])
def test_invalid_instance_origin_and_foreign_family_refuse(origin):
    with pytest.raises(ValueError): D.credential({**AUTH, "instance_url": origin})
    with pytest.raises(ValueError): D.DokployNode.parse_config({"config": args("get_current_user"), "credentials": {**AUTH, "credential_type": "slack_oauth"}})


def test_disposable_name_constraints_are_visible_in_generated_schema():
    schema = D.DokployNodeConfig.model_json_schema()
    for operation in D.OPS:
        if not operation.startswith(("create_", "update_", "delete_")):
            continue
        config = TypeAdapter(D.DokployOperation).validate_python(args(operation))
        definition = schema["$defs"][type(config).__name__]
        for name in ("name", "expected_project_name", "expected_environment_name"):
            if name in definition["properties"]:
                field = definition["properties"][name]
                assert field["pattern"] == D.DISPOSABLE_NAME_PATTERN
                assert (field["minLength"], field["maxLength"]) == (9, 83)
