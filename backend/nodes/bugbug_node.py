"""BugBug Public API v2: project-token test automation.

Contract: https://api.bugbug.io/docs/schema/ (v2).
Token setup and wire semantics: https://docs.bugbug.io/integrations/public-api
Each operation sends one request; run operations queue work and do not poll.
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

BASE_URL = "https://api.bugbug.io"
DOCS_URL = "https://docs.bugbug.io/integrations/public-api"


class BugbugTokenCredential(BaseModel):
    model_config = ConfigDict(title="Bugbug API Token", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": DOCS_URL,
            "x-credential-instructions": "In your BugBug project, open Integrations → API Token and copy the API Token. Paste it without the Token prefix. The Public API requires the Business plan. This token acts on one project."})
    credential_type: Literal["bugbug_api_token"] = Field("bugbug_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="API Token", min_length=1, max_length=4096, repr=False,
        description="Project API token from BugBug Integrations → API Token.", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API Token")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API token without a header prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Page(_Input):
    page: int = Field(1, ge=1, title="Page", description="Read one page. Increment this value when the response has a next page.")
    page_size: int = Field(10, ge=1, le=100, title="Page Size")


class _Search(_Page):
    query: str | None = Field(None, title="Search")
    ordering: Literal["created", "-created", "name", "-name"] | None = Field(None, title="Sort")


Tag = Annotated[str, Field(max_length=64)]
Tags = Annotated[list[Tag], Field(max_length=64)]


class _TestFields(_Input):
    name: str | None = Field(None, max_length=255, title="Name")
    screen_size_type: Literal["desktop", "mobile", "custom"] | None = Field(None, title="Screen Size")
    notes: str | None = Field(None, title="Notes")
    folder_id: UUID | None = Field(None, title="Folder ID")
    tags: Tags | None = Field(None, title="Tag Names", description="Supplied tags replace the current set when updating. An empty list clears them.")


class _SuiteFields(_Input):
    name: str | None = Field(None, max_length=100, title="Name")
    notes: str | None = Field(None, title="Notes")
    auto_add_new_tests: bool | None = Field(None, title="Add New Tests Automatically")
    auto_retry: int | None = Field(None, ge=0, le=5, title="Automatic Retries")
    before_after_all_enabled: bool | None = Field(None, title="Enable Before/After All")
    run_in_parallel: bool | None = Field(None, title="Run in Parallel")
    tests: list[UUID] | None = Field(None, title="Test IDs")
    before_all: list[UUID] | None = Field(None, title="Before All Test IDs")
    after_all: list[UUID] | None = Field(None, title="After All Test IDs")
    tags: Tags | None = Field(None, title="Tag Names")


class VariableOverride(_Input):
    key: str = Field(..., max_length=128, title="Existing Variable Key")
    value: str | None = Field(None, title="Override Value")


class _Run(_Input):
    run_profile_id: UUID | None = Field(None, title="Run Profile ID", description="Omit to use the test or suite's default profile.")
    variables: list[VariableOverride] | None = Field(None, title="Variable Overrides", description="Keys must already exist in the project.")
    tags: Tags | None = Field(None, title="Run Tag Names")


RunStatus = Literal["auto_retrying", "error", "failed", "initialized", "passed", "paused", "queued", "recording", "running", "skipped", "stopped"]


class _RunPage(_Page):
    ordering: Literal["created", "-created", "started", "-started"] | None = Field(None, title="Sort")
    status: RunStatus | None = Field(None, title="Run Status")
    tags: str | None = Field(None, title="Tags Filter")


class ListProjects(_Search):
    operation: Literal["list_projects"] = Field("list_projects", title="List Projects", json_schema_extra={"ui:hidden": True})


class ListProfiles(_Page):
    operation: Literal["list_profiles"] = Field("list_profiles", title="List Profiles", json_schema_extra={"ui:hidden": True})


class GetProfile(_Input):
    operation: Literal["get_profile"] = Field("get_profile", title="Get Profile", json_schema_extra={"ui:hidden": True})
    profile_id: UUID = Field(..., title="Profile ID")


class ListTests(_Search):
    operation: Literal["list_tests"] = Field("list_tests", title="List Tests", json_schema_extra={"ui:hidden": True})
    latest_run: bool | None = Field(None, title="Include Latest Run")
    tags: str | None = Field(None, title="Tags Filter")
    folder_id: UUID | None = Field(None, title="Folder ID")
    no_folder: bool | None = Field(None, title="Only Tests Without a Folder")


class GetTest(_Input):
    operation: Literal["get_test"] = Field("get_test", title="Get Test", json_schema_extra={"ui:hidden": True})
    test_id: UUID = Field(..., title="Test ID")


class CreateTest(_TestFields):
    operation: Literal["create_test"] = Field("create_test", title="Create Test", json_schema_extra={"ui:hidden": True})


class UpdateTest(_TestFields):
    operation: Literal["update_test"] = Field("update_test", title="Update Test", json_schema_extra={"ui:hidden": True})
    test_id: UUID = Field(..., title="Test ID")


class DeleteTest(_Input):
    operation: Literal["delete_test"] = Field("delete_test", title="Delete Test", json_schema_extra={"ui:hidden": True})
    test_id: UUID = Field(..., title="Test ID", description="Permanently delete this test.")


class ListSuites(_Search):
    operation: Literal["list_suites"] = Field("list_suites", title="List Suites", json_schema_extra={"ui:hidden": True})
    latest_run: bool | None = Field(None, title="Include Latest Run")
    tags: str | None = Field(None, title="Tags Filter")


class GetSuite(_Input):
    operation: Literal["get_suite"] = Field("get_suite", title="Get Suite", json_schema_extra={"ui:hidden": True})
    suite_id: UUID = Field(..., title="Suite ID")


class CreateSuite(_SuiteFields):
    operation: Literal["create_suite"] = Field("create_suite", title="Create Suite", json_schema_extra={"ui:hidden": True})
    run_profile_id: UUID = Field(..., title="Run Profile ID")


class UpdateSuite(_SuiteFields):
    operation: Literal["update_suite"] = Field("update_suite", title="Update Suite", json_schema_extra={"ui:hidden": True})
    suite_id: UUID = Field(..., title="Suite ID")
    run_profile_id: UUID | None = Field(None, title="Run Profile ID")


class DeleteSuite(_Input):
    operation: Literal["delete_suite"] = Field("delete_suite", title="Delete Suite", json_schema_extra={"ui:hidden": True})
    suite_id: UUID = Field(..., title="Suite ID", description="Permanently delete this suite.")


class ListTestRuns(_RunPage):
    operation: Literal["list_test_runs"] = Field("list_test_runs", title="List Test Runs", json_schema_extra={"ui:hidden": True})
    test_id: UUID | None = Field(None, title="Test ID")


class RunTest(_Run):
    operation: Literal["run_test"] = Field("run_test", title="Run Test", json_schema_extra={"ui:hidden": True})
    test_id: UUID = Field(..., title="Test ID", description="Queue a cloud test run; returns immediately without waiting for completion.")


class GetTestRun(_Input):
    operation: Literal["get_test_run"] = Field("get_test_run", title="Get Test Run", json_schema_extra={"ui:hidden": True})
    run_id: UUID = Field(..., title="Test Run ID")


class GetTestRunStatus(_Input):
    operation: Literal["get_test_run_status"] = Field("get_test_run_status", title="Get Test Run Status", json_schema_extra={"ui:hidden": True})
    run_id: UUID = Field(..., title="Test Run ID")


class StopTestRun(_Input):
    operation: Literal["stop_test_run"] = Field("stop_test_run", title="Stop Test Run", json_schema_extra={"ui:hidden": True})
    run_id: UUID = Field(..., title="Test Run ID")


class ListSuiteRuns(_RunPage):
    operation: Literal["list_suite_runs"] = Field("list_suite_runs", title="List Suite Runs", json_schema_extra={"ui:hidden": True})
    suite_id: UUID | None = Field(None, title="Suite ID")


class RunSuite(_Run):
    operation: Literal["run_suite"] = Field("run_suite", title="Run Suite", json_schema_extra={"ui:hidden": True})
    suite_id: UUID = Field(..., title="Suite ID", description="Queue a cloud suite run; returns immediately without waiting for completion.")


class GetSuiteRun(_Input):
    operation: Literal["get_suite_run"] = Field("get_suite_run", title="Get Suite Run", json_schema_extra={"ui:hidden": True})
    run_id: UUID = Field(..., title="Suite Run ID")


class GetSuiteRunStatus(_Input):
    operation: Literal["get_suite_run_status"] = Field("get_suite_run_status", title="Get Suite Run Status", json_schema_extra={"ui:hidden": True})
    run_id: UUID = Field(..., title="Suite Run ID")


class StopSuiteRun(_Input):
    operation: Literal["stop_suite_run"] = Field("stop_suite_run", title="Stop Suite Run", json_schema_extra={"ui:hidden": True})
    run_id: UUID = Field(..., title="Suite Run ID")


class ListVariables(_Input):
    operation: Literal["list_variables"] = Field("list_variables", title="List Variables", json_schema_extra={"ui:hidden": True})


class CreateVariable(_Input):
    operation: Literal["create_variable"] = Field("create_variable", title="Create Variable", json_schema_extra={"ui:hidden": True})
    key: str = Field(..., max_length=50, title="Variable Key")
    type: Literal["value", "evaluate"] = Field(..., title="Variable Type")
    value: str | None = Field(None, title="Value")
    is_secret: bool = Field(False, title="Secret Variable")
    description: str | None = Field(None, max_length=256, title="Description")


Operation = Annotated[Union[ListProjects, ListProfiles, GetProfile, ListTests, GetTest, CreateTest, UpdateTest, DeleteTest, ListSuites, GetSuite, CreateSuite, UpdateSuite, DeleteSuite, ListTestRuns, RunTest, GetTestRun, GetTestRunStatus, StopTestRun, ListSuiteRuns, RunSuite, GetSuiteRun, GetSuiteRunStatus, StopSuiteRun, ListVariables, CreateVariable], Field(discriminator="operation")]


class BugbugConfig(NodeConfig[Operation, BugbugTokenCredential]):
    pass


ROUTES = {
    "list_projects": ('GET', '/v2/projects/', None),
    "list_profiles": ('GET', '/v2/profiles/', None),
    "get_profile": ('GET', '/v2/profiles/{profile_id}/', 'profile_id'),
    "list_tests": ('GET', '/v2/tests/', None),
    "get_test": ('GET', '/v2/tests/{test_id}/', 'test_id'),
    "create_test": ('POST', '/v2/tests/', None),
    "update_test": ('PATCH', '/v2/tests/{test_id}/', 'test_id'),
    "delete_test": ('DELETE', '/v2/tests/{test_id}/', 'test_id'),
    "list_suites": ('GET', '/v2/suites/', None),
    "get_suite": ('GET', '/v2/suites/{suite_id}/', 'suite_id'),
    "create_suite": ('POST', '/v2/suites/', None),
    "update_suite": ('PATCH', '/v2/suites/{suite_id}/', 'suite_id'),
    "delete_suite": ('DELETE', '/v2/suites/{suite_id}/', 'suite_id'),
    "list_test_runs": ('GET', '/v2/testruns/', None),
    "run_test": ('POST', '/v2/testruns/', None),
    "get_test_run": ('GET', '/v2/testruns/{run_id}/', 'run_id'),
    "get_test_run_status": ('GET', '/v2/testruns/{run_id}/status/', 'run_id'),
    "stop_test_run": ('POST', '/v2/testruns/{run_id}/stop/', 'run_id'),
    "list_suite_runs": ('GET', '/v2/suiteruns/', None),
    "run_suite": ('POST', '/v2/suiteruns/', None),
    "get_suite_run": ('GET', '/v2/suiteruns/{run_id}/', 'run_id'),
    "get_suite_run_status": ('GET', '/v2/suiteruns/{run_id}/status/', 'run_id'),
    "stop_suite_run": ('POST', '/v2/suiteruns/{run_id}/stop/', 'run_id'),
    "list_variables": ('GET', '/v2/variables/', None),
    "create_variable": ('POST', '/v2/variables/', None),
}

# API pagination uses page_size in the pinned schema, not a guessed pageSize.
WIRE_NAMES = {
    "latest_run": "latestRun", "folder_id": "folderId", "no_folder": "noFolder",
    "screen_size_type": "screenSizeType", "run_profile_id": "runProfileId",
    "test_id": "testId", "suite_id": "suite_id", "auto_add_new_tests": "autoAddNewTests",
    "auto_retry": "autoRetry", "before_after_all_enabled": "beforeAfterAllEnabled",
    "run_in_parallel": "runInParallel", "before_all": "beforeAll", "after_all": "afterAll",
    "is_secret": "isSecret",
}


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, token) for item in value]
    if isinstance(value, dict):
        return {key: _redact(item, token) for key, item in value.items()}
    return value


class BugbugNode(WorkflowNode):
    integration_type = "automation-bugbug"
    connection_evidence = ConnectionEvidence(noun="tests", operation="list_tests", label_keys=("name", "id"))
    edit_examples = ["Run a BugBug test", "Check a suite run's status", "List failed test runs"]

    @classmethod
    def get_config_model(cls):
        return BugbugConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a BugBug project API token")
        config = self.config.config
        token = self.config.credentials.api_token
        method, template, identifier = ROUTES[config.operation]
        values = config.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        path = template
        if identifier:
            path = template.replace("{" + identifier + "}", values.pop(identifier))
        payload = {WIRE_NAMES.get(key, key): value for key, value in values.items()}
        if config.operation == "run_suite":
            payload["suiteId"] = payload.pop("suite_id")
        kwargs = {"params": payload} if method == "GET" else ({"json": payload} if payload else {})
        try:
            async with guarded_async_client(timeout=30.0, follow_redirects=False) as client:
                response = await client.request(method, BASE_URL + path,
                    headers={"Authorization": "Token " + token, "Accept": "application/json"}, **kwargs)
        except httpx.HTTPError:
            raise ValueError("BugBug request did not complete. Inspect the project before retrying a write.") from None
        if not 200 <= response.status_code < 300:
            try:
                detail = response.json()
            except ValueError:
                detail = "BugBug returned a non-JSON error response"
            output = {"status": "error", "success": False, "http_status": response.status_code,
                "message": _redact(str(detail), token)}
        elif response.status_code == 204:
            output = {"status": "success", "success": True, "data": None}
        else:
            try:
                body = response.json()
            except ValueError:
                raise ValueError("BugBug returned an unexpected non-JSON response") from None
            if not isinstance(body, (dict, list)):
                raise ValueError("BugBug returned an unexpected JSON response shape")
            output = {"status": "success", "success": True, "data": _redact(body, token)}
        output["action"] = config.operation
        await self.emit(output)
        return output
