"""Ex Libris Alma task lists, pinned to the provider's Task Lists OpenAPI 1.0.

Contract: https://developers.exlibrisgroup.com/wp-content/uploads/alma/openapi/tasklists.yaml
API keys require Task-lists read/write permission for the selected operation.
"""
from __future__ import annotations

from datetime import date
from typing import Annotated, Literal, Union
from urllib.parse import quote
from xml.etree import ElementTree

import httpx

from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from utils.ssrf import guarded_async_client


class ExLibrisCredential(BaseModel):
    model_config = ConfigDict(
        title="Ex Libris API Key",
        hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://developers.exlibrisgroup.com/alma/apis/#defining",
            "x-credential-instructions": "Paste your Alma API key with Task-lists permissions and select your institution's API region. Writes require read/write access. NoClick checks the institution's authority control tasks when connecting.",
        },
    )
    credential_type: Literal["exlibrisgroup_api_key"] = Field(
        "exlibrisgroup_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ...,
        title="API key",
        min_length=1,
        repr=False,
        json_schema_extra={"ui:widget": "password"},
    )
    region: Literal["eu", "na", "ap", "aps", "cn", "ca"] = Field(
        "eu",
        title="API region",
        description="Choose the region used by your institution.",
    )

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        return clean_secret(value, field_name="API key")


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def identifiers_and_dates(cls, value, info):
        if isinstance(value, str) and info.field_name in {"task_id", "printout_id"}:
            if value in {".", ".."} or any(c in value for c in "/\\?#"):
                raise ValueError("Paste a single resource ID")
        if value and info.field_name in {"submit_date_from", "submit_date_to"}:
            date.fromisoformat(value)
        return value


class ExLibrisPrinter(_Input):
    value: str = Field(..., min_length=1, title="Printer code")
    desc: str | None = Field(None, title="Printer name")


class ExLibrisPrintoutBody(_Input):
    printout: str = Field(..., min_length=1, title="Printout name")
    printer: ExLibrisPrinter = Field(..., title="Printer")
    letter: str = Field(
        ...,
        min_length=1,
        title="Letter HTML",
        json_schema_extra={"ui:widget": "textarea"},
    )


class ExLibrisListAuthorityControlTasksConfig(_Input):
    """This API returns a list of authority control tasks in Alma."""

    operation: Literal["list_authority_control_tasks"] = Field(
        "list_authority_control_tasks",
        title="List Authority Control Tasks",
        json_schema_extra={"ui:hidden": True},
    )
    mode: Literal["review", "all"] = Field(
        "review",
        description="Mode. Optional. Valid values: review (as in the Review tab), all (as in the All tab). Default: review.",
    )
    mms_id: str | None = Field(None, description="Filter by MMS ID. Optional.")
    title: str | None = Field(None, description="Filter by title. Optional.")
    bib_heading_before: str | None = Field(
        None, description="Filter by bib heading before. Optional."
    )
    report_type: str | None = Field(
        None, description="Filter by report type. Optional."
    )
    vocabulary_code: str | None = Field(
        None, description="Filter by vocabulary code. Optional."
    )
    field: str | None = Field(None, description="Filter by field. Optional.")
    linked_inventory_type: str | None = Field(
        None,
        description="Filter by linked inventory type. Optional. Valid values: PHYSICAL, DIGITAL, ELECTRONIC, NO_INVENTORY.",
    )
    brief_level: str | None = Field(
        None, description="Filter by brief level. Optional. Numeric value."
    )
    suppressed_from_discovery: Literal["true", "false"] | None = Field(
        None,
        description="Filter by suppressed from discovery. Optional. If omitted, all records are returned. Valid values: true (suppressed only), false (not suppressed only).",
    )
    linked_to_community_zone: Literal["true", "false"] | None = Field(
        None,
        description="Filter by linked to community zone. Optional. If omitted, all records are returned. Valid values: true (linked to CZ only), false (not linked to CZ only).",
    )
    submit_date_from: str | None = Field(
        None,
        json_schema_extra={"format": "date"},
        description="Filter by submit date from (inclusive). Optional. Format: yyyy-MM-dd.",
    )
    submit_date_to: str | None = Field(
        None,
        json_schema_extra={"format": "date"},
        description="Filter by submit date to (inclusive). Optional. Format: yyyy-MM-dd.",
    )
    order_by: Literal[
        "create_date", "mms_id", "title", "field", "vocabulary_code", "type"
    ] = Field(
        "create_date",
        description="Sort field. Optional. Valid values: create_date, mms_id, title, field, vocabulary_code, type.",
    )
    direction: Literal["asc", "desc"] = Field(
        "asc", description="Sort direction. Optional. Valid values: asc, desc."
    )
    limit: int = Field(
        10,
        ge=0,
        le=100,
        description="Limits the number of results. Optional. Valid values are 0-100. Default value: 10.",
    )
    offset: int = Field(
        0,
        ge=0,
        description="Offset of the results returned. Optional. Default value: 0.",
    )


class ExLibrisGetAuthorityControlTaskConfig(_Input):
    """This API returns an authority control task in Alma."""

    operation: Literal["get_authority_control_task"] = Field(
        "get_authority_control_task",
        title="Get Authority Control Task",
        json_schema_extra={"ui:hidden": True},
    )
    task_id: str = Field(..., min_length=1, description="The Authority Control Task ID")


class ExLibrisDismissAuthorityControlTaskConfig(_Input):
    """This API operates on an authority control task. given a Authority Control Task ID."""

    operation: Literal["dismiss_authority_control_task"] = Field(
        "dismiss_authority_control_task",
        title="Dismiss Authority Control Task",
        json_schema_extra={"ui:hidden": True},
    )
    task_id: str = Field(..., min_length=1, description="The Authority Control Task ID")
    op: Literal["dismiss"] = Field(
        "dismiss",
        description="The operation to perform on the authority control task. Currently, the option 'dismiss' is supported",
    )


class ExLibrisListPrintoutsConfig(_Input):
    """This API returns a list of Printouts."""

    operation: Literal["list_printouts"] = Field(
        "list_printouts", title="List Printouts", json_schema_extra={"ui:hidden": True}
    )
    letter: str = Field("ALL", description="Printout Name. Optional. ")
    status: str = Field(
        "ALL",
        description="Printout status. Optional. Valid values are: Printed, Pending, Canceled.",
    )
    printer_id: str = Field("ALL", description="Printout Printer")
    printed_by: str = Field(
        "ALL",
        description="Printed by: ALL/ME. This field is relevant when using the API from within Cloud Apps.",
    )
    printout_id: str = Field(
        "ALL",
        description="A list of Printout IDs (for example: 123,456,778) from 1 to the limit of 100 Optional. Use of this option overrides all of the filtering parameters",
    )
    limit: int = Field(
        10,
        ge=0,
        le=100,
        description="Limits the number of results. Optional. Valid values are 0-100. Default value: 10.",
    )
    offset: int = Field(
        0,
        ge=0,
        description="Offset of the results returned. Optional. Default value: 0, which means that the first results will be returned.",
    )


class ExLibrisActOnPrintoutsConfig(_Input):
    """This API performs an action on printouts: mark as printed or canceled. 10,000 records can be handled in one requests. Only printouts which were updated will be returned."""

    operation: Literal["act_on_printouts"] = Field(
        "act_on_printouts",
        title="Act On Printouts",
        json_schema_extra={"ui:hidden": True},
    )
    letter: str = Field("ALL", description="Printout Name. Optional. ")
    status: str = Field(
        "ALL",
        description="Printout status. Optional. Valid values are: Printed, Pending, Canceled.",
    )
    printer_id: str = Field("ALL", description="Printout Printer")
    printed_by: str = Field(
        "ALL",
        description="Printed by: ALL/ME. This field is relevant when using the API from within Cloud Apps.",
    )
    printout_id: str = Field(
        "ALL",
        description="A list of Printout IDs (for example: 123,456,778) from 1 to the limit of 100 Optional. Use of this option overrides all of the filtering parameters",
    )
    op: Literal["mark_as_printed", "mark_as_canceled"] = Field(
        ...,
        description="The operation to perform on the printout. Currently, the options are: 'mark_as_printed','mark_as_canceled'",
    )


class ExLibrisCreatePrintoutConfig(_Input):
    """This Web service creates a Printout given a Printout Obj."""

    operation: Literal["create_printout"] = Field(
        "create_printout",
        title="Create Printout",
        json_schema_extra={"ui:hidden": True},
    )
    body: ExLibrisPrintoutBody = Field(..., title="Printout")


class ExLibrisGetPrintoutConfig(_Input):
    """This Web service returns a Printout given a Printout ID."""

    operation: Literal["get_printout"] = Field(
        "get_printout", title="Get Printout", json_schema_extra={"ui:hidden": True}
    )
    printout_id: str = Field(..., min_length=1, description="The Printout ID")


class ExLibrisActOnPrintoutConfig(_Input):
    """This API operates on an printout. given a Printout ID."""

    operation: Literal["act_on_printout"] = Field(
        "act_on_printout",
        title="Act On Printout",
        json_schema_extra={"ui:hidden": True},
    )
    printout_id: str = Field(..., min_length=1, description="The Printout ID")
    op: Literal["mark_as_printed", "mark_as_canceled"] = Field(
        ...,
        description="The operation to perform on the printout. Currently, the options are 'mark_as_printed','mark_as_canceled'",
    )


class ExLibrisListRequestedResourcesConfig(_Input):
    """This API returns a list of requested resources to be picked from the shelf in Alma"""

    operation: Literal["list_requested_resources"] = Field(
        "list_requested_resources",
        title="List Requested Resources",
        json_schema_extra={"ui:hidden": True},
    )
    library: str = Field(
        ...,
        min_length=1,
        description="The library of the given circulation desk or department where the resources are located. Mandatory.",
    )
    circ_desk: str = Field(
        ...,
        min_length=1,
        description="The circulation desk where the action is being performed. Mandatory.",
    )
    location: str | None = Field(None, description="The location code. Optional.")
    order_by: Literal["location", "call_number"] = Field(
        "call_number",
        description="The order in which to retrieve the results: location/call_number (default).",
    )
    direction: Literal["asc", "desc"] = Field(
        "asc",
        description="The order direction in which to retrieve the results. Optional.",
    )
    pickup_inst: str | None = Field(
        None, description="The pickup institution. Optional."
    )
    reported: Literal["Y", "N"] | None = Field(
        None, description="Show reported results: Y/N. Optional."
    )
    printed: Literal["Y", "N"] | None = Field(
        None, description="Show printed results: Y/N. Optional."
    )
    limit: int = Field(
        10,
        ge=0,
        le=100,
        description="Limits the number of results. Optional. Valid values are 0-100. Default value: 10.",
    )
    offset: int = Field(
        0,
        ge=0,
        description="Offset of the results returned. Optional. Default value: 0, which means that the first results will be returned.",
    )


class ExLibrisMarkRequestedResourcesReportedConfig(_Input):
    """This API performs an action on requested resources that are on the shelf in Alma"""

    operation: Literal["mark_requested_resources_reported"] = Field(
        "mark_requested_resources_reported",
        title="Mark Requested Resources Reported",
        json_schema_extra={"ui:hidden": True},
    )
    library: str = Field(
        ...,
        min_length=1,
        description="The library of the given circulation desk or department where the resources are located. Mandatory.",
    )
    circ_desk: str = Field(
        ...,
        min_length=1,
        description="The circulation desk where the action is being performed. Mandatory.",
    )
    op: Literal["mark_reported"] = Field(
        "mark_reported",
        description="Operation to be preformed on the list of given requests. Currently the only supported action is 'mark_reported'. Mandatory.",
    )
    location: str | None = Field(None, description="The location code. Optional.")
    pickup_inst: str | None = Field(
        None, description="The pickup institution. Optional."
    )
    reported: Literal["Y", "N"] | None = Field(
        None, description="Show reported results: Y/N. Optional."
    )
    printed: Literal["Y", "N"] | None = Field(
        None, description="Show printed results: Y/N. Optional."
    )


class ExLibrisListLendingRequestsConfig(_Input):
    """This API returns a list of lending requests in Alma"""

    operation: Literal["list_lending_requests"] = Field(
        "list_lending_requests",
        title="List Lending Requests",
        json_schema_extra={"ui:hidden": True},
    )
    library: str = Field(
        ...,
        min_length=1,
        description="The resource sharing library for which lending requests should be retrieved. Mandatory. List of possible libraries can be retrieved using the [GET /almaws/v1/conf/libraries API](https://developers.exlibrisgroup.com/alma/apis/conf/GET/gwPcGly021p29HpB7XTI4Dp4I8TKv6CAxBlD4LyRaVE=/37088dc9-c685-4641-bc7f-60b5ca7cabed).",
    )
    status: str | None = Field(
        None,
        description="The status of lending requests to retrieve. Optional. List of possible statuses can be retrieved using the [GET almaws/v1/conf/code-tables/MandatoryLendingWorkflowSteps API](https://developers.exlibrisgroup.com/alma/apis/conf/GET/gwPcGly021p29HpB7XTI4K7cQ0vuYHLS4NSgDGmcRpRYqx5hIMRTng9SIKO5Vof+/37088dc9-c685-4641-bc7f-60b5ca7cabed) and the  [GET almaws/v1/conf/code-tables/OptionalLendingWorkflowSteps API](https://developers.exlibrisgroup.com/alma/apis/conf/GET/gwPcGly021p29HpB7XTI4K7cQ0vuYHLS4NSgDGmcRpRYqx5hIMRTng9SIKO5Vof+/37088dc9-c685-4641-bc7f-60b5ca7cabed).",
    )
    printed: Literal["Y", "N"] | None = Field(
        None,
        description="The 'printed' value of lending requests to retrieve. Optional. Possible values: Y, N.",
    )
    reported: Literal["Y", "N"] | None = Field(
        None,
        description="The 'reported' value of lending requests to retrieve. Optional. Possible values: Y, N.",
    )
    partner: str | None = Field(
        None,
        description="The partner value. Only lending requests from this partner should be retrieved. Optional. List of possible partners can be retrieved using the [GET almaws/v1/partners API](https://developers.exlibrisgroup.com/alma/apis/partners/GET/gwPcGly021piAVNPLaef7suP1zfa6Lui/8883ef41-c3b8-4792-9ff8-cb6b729d6e07).",
    )
    requested_format: str | None = Field(
        None,
        description="Requested format of the resource. Optional. List of possible formats can be retrieved using the [GET almaws/v1/conf/code-tables/RequestFormats API](https://developers.exlibrisgroup.com/alma/apis/conf/GET/gwPcGly021p29HpB7XTI4K7cQ0vuYHLS4NSgDGmcRpRYqx5hIMRTng9SIKO5Vof+/37088dc9-c685-4641-bc7f-60b5ca7cabed).",
    )
    supplied_format: str | None = Field(
        None,
        description="Supplied Format of the resource. Optional. List of possible formats can be retrieved using the [GET almaws/v1/conf/code-tables/RequestFormats API](https://developers.exlibrisgroup.com/alma/apis/conf/GET/gwPcGly021p29HpB7XTI4K7cQ0vuYHLS4NSgDGmcRpRYqx5hIMRTng9SIKO5Vof+/37088dc9-c685-4641-bc7f-60b5ca7cabed).",
    )


class ExLibrisMarkLendingRequestsReportedConfig(_Input):
    """This API preforms the requested action on a list (specified by given filters) of lending requests in Alma"""

    operation: Literal["mark_lending_requests_reported"] = Field(
        "mark_lending_requests_reported",
        title="Mark Lending Requests Reported",
        json_schema_extra={"ui:hidden": True},
    )
    library: str = Field(
        ...,
        min_length=1,
        description="The resource sharing library from which lending requests should be retrieved. Mandatory. List of possible libraries can be retrieved using the [GET /almaws/v1/conf/libraries API](https://developers.exlibrisgroup.com/alma/apis/conf/GET/gwPcGly021p29HpB7XTI4Dp4I8TKv6CAxBlD4LyRaVE=/37088dc9-c685-4641-bc7f-60b5ca7cabed).",
    )
    op: Literal["mark_reported"] = Field(
        "mark_reported",
        description="Operation to be preformed on the list of given requests. Currently the only supported action is 'mark_reported'. Mandatory.",
    )
    status: str | None = Field(
        None,
        description="The status of lending requests to retrieve. Optional. List of possible statuses can be retrieved using the [GET almaws/v1/conf/code-tables/MandatoryLendingWorkflowSteps API](https://developers.exlibrisgroup.com/alma/apis/conf/GET/gwPcGly021p29HpB7XTI4K7cQ0vuYHLS4NSgDGmcRpRYqx5hIMRTng9SIKO5Vof+/37088dc9-c685-4641-bc7f-60b5ca7cabed).and the  [GET almaws/v1/conf/code-tables/OptionalLendingWorkflowSteps API](https://developers.exlibrisgroup.com/alma/apis/conf/GET/gwPcGly021p29HpB7XTI4K7cQ0vuYHLS4NSgDGmcRpRYqx5hIMRTng9SIKO5Vof+/37088dc9-c685-4641-bc7f-60b5ca7cabed).",
    )
    printed: Literal["Y", "N"] | None = Field(
        None,
        description="The 'printed' value of lending requests to retrieve. Optional. Possible values: Y, N.",
    )
    reported: Literal["Y", "N"] | None = Field(
        None,
        description="The 'reported' value of lending requests to retrieve. Optional. Possible values: Y, N.",
    )
    partner: str | None = Field(
        None,
        description="The partner value. Only lending requests from this partner should be. Optional. List of possible partners can be retrieved using the [GET almaws/v1/partners API](https://developers.exlibrisgroup.com/alma/apis/partners/GET/gwPcGly021piAVNPLaef7suP1zfa6Lui/8883ef41-c3b8-4792-9ff8-cb6b729d6e07).",
    )
    requested_format: str | None = Field(
        None,
        description="Requested format of the resource. Optional. List of possible formats can be retrieved using the [GET almaws/v1/conf/code-tables/RequestFormats API](https://developers.exlibrisgroup.com/alma/apis/conf/GET/gwPcGly021p29HpB7XTI4K7cQ0vuYHLS4NSgDGmcRpRYqx5hIMRTng9SIKO5Vof+/37088dc9-c685-4641-bc7f-60b5ca7cabed).",
    )
    supplied_format: str | None = Field(
        None,
        description="Supplied Format of the resource. Optional. List of possible formats can be retrieved using the [GET almaws/v1/conf/code-tables/RequestFormats API](https://developers.exlibrisgroup.com/alma/apis/conf/GET/gwPcGly021p29HpB7XTI4K7cQ0vuYHLS4NSgDGmcRpRYqx5hIMRTng9SIKO5Vof+/37088dc9-c685-4641-bc7f-60b5ca7cabed).",
    )


class ExLibrisGetConnectionTestConfig(_Input):
    """This API is used to test if the API key was configured correctly.It returns a short XML (no schema available - the output is subject to changes) with the following structure:<test>GET - OK - institutionCode: 01ABC_INST</test>"""

    operation: Literal["get_connection_test"] = Field(
        "get_connection_test",
        title="Get Connection Test",
        json_schema_extra={"ui:hidden": True},
    )


class ExLibrisTestWritePermissionsConfig(_Input):
    """This API is used to test if the API key was configured correctly, including read/write permissions.It returns a short XML (no schema available - the output is subject to changes) with the following structure:<test>POST - OK</test>"""

    operation: Literal["test_write_permissions"] = Field(
        "test_write_permissions",
        title="Test Write Permissions",
        json_schema_extra={"ui:hidden": True},
    )


class ExLibrisOnNewAuthorityTaskConfig(PollTriggerConfigBase):
    """Poll task creation order, baseline on arming, then emit unseen task IDs.

    Lists up to 2,000 most recent tasks. Narrow by vocabulary when the review
    queue is larger; a truncated queue fails without advancing the seen set.
    """

    operation: Literal["on_new_authority_task"] = Field(
        "on_new_authority_task",
        title="On New Authority Control Task",
        json_schema_extra={
            "ui:hidden": True,
            "x-is-trigger": True,
            "x-category": "Triggers",
        },
    )
    vocabulary_code: str | None = Field(None, title="Vocabulary code")
    mode: Literal["review", "all"] = Field("review", title="Task mode")


ExLibrisConfig = Annotated[
    Union[
        ExLibrisListAuthorityControlTasksConfig,
        ExLibrisGetAuthorityControlTaskConfig,
        ExLibrisDismissAuthorityControlTaskConfig,
        ExLibrisListPrintoutsConfig,
        ExLibrisActOnPrintoutsConfig,
        ExLibrisCreatePrintoutConfig,
        ExLibrisGetPrintoutConfig,
        ExLibrisActOnPrintoutConfig,
        ExLibrisListRequestedResourcesConfig,
        ExLibrisMarkRequestedResourcesReportedConfig,
        ExLibrisListLendingRequestsConfig,
        ExLibrisMarkLendingRequestsReportedConfig,
        ExLibrisGetConnectionTestConfig,
        ExLibrisTestWritePermissionsConfig,
        ExLibrisOnNewAuthorityTaskConfig,
    ],
    Field(discriminator="operation"),
]


class ExLibrisFullConfig(NodeConfig[ExLibrisConfig, ExLibrisCredential]):
    pass


ROUTES = {
    "list_authority_control_tasks": (
        "GET",
        "/almaws/v1/task-lists/authority-control-tasks",
    ),
    "get_authority_control_task": (
        "GET",
        "/almaws/v1/task-lists/authority-control-tasks/{task_id}",
    ),
    "dismiss_authority_control_task": (
        "POST",
        "/almaws/v1/task-lists/authority-control-tasks/{task_id}",
    ),
    "list_printouts": ("GET", "/almaws/v1/task-lists/printouts"),
    "act_on_printouts": ("POST", "/almaws/v1/task-lists/printouts"),
    "create_printout": ("POST", "/almaws/v1/task-lists/printouts/create"),
    "get_printout": ("GET", "/almaws/v1/task-lists/printouts/{printout_id}"),
    "act_on_printout": ("POST", "/almaws/v1/task-lists/printouts/{printout_id}"),
    "list_requested_resources": ("GET", "/almaws/v1/task-lists/requested-resources"),
    "mark_requested_resources_reported": (
        "POST",
        "/almaws/v1/task-lists/requested-resources",
    ),
    "list_lending_requests": ("GET", "/almaws/v1/task-lists/rs/lending-requests"),
    "mark_lending_requests_reported": (
        "POST",
        "/almaws/v1/task-lists/rs/lending-requests",
    ),
    "get_connection_test": ("GET", "/almaws/v1/task-lists/test"),
    "test_write_permissions": ("POST", "/almaws/v1/task-lists/test"),
}


class ExLibrisNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-exlibrisgroup"
    connection_evidence = ConnectionEvidence(
        operation="list_authority_control_tasks",
        noun="authority control tasks",
        label_keys=("title", "id"),
    )

    @classmethod
    def get_config_model(cls):
        return ExLibrisFullConfig

    async def _request(self, method, path, *, params=None, body=None):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect an Ex Libris API key")
        suffix = (
            "exlibrisgroup.com.cn" if credential.region == "cn" else "exlibrisgroup.com"
        )
        origin = f"https://api-{credential.region}.hosted.{suffix}"
        query = {**(params or {}), "apikey": credential.api_key}
        try:
            async with guarded_async_client(
                timeout=30, follow_redirects=False, trust_env=False
            ) as client:
                response = await client.request(
                    method,
                    origin + path,
                    params=query,
                    json=body,
                    headers={
                        "Accept": "application/json",
                        **(
                            {"Content-Type": "application/json"}
                            if body is not None
                            else {}
                        ),
                    },
                )
        except httpx.HTTPError:
            raise ValueError("Ex Libris transport failed; retry the request") from None
        if response.status_code < 200 or response.status_code >= 300:
            # Never include the request URL: Alma puts the secret in its query.
            detail = response.text[:1000].replace(credential.api_key, "[redacted]")
            raise ValueError(f"Ex Libris HTTP {response.status_code}: {detail}")
        if len(response.content) > 5_000_000:
            raise ValueError("Ex Libris response is too large")
        if path.endswith("/test") and response.text.lstrip().startswith("<"):
            # The published test endpoint explicitly returns XML despite Accept.
            root = ElementTree.fromstring(response.content)
            if root.tag != "test":
                raise ValueError("Unexpected Ex Libris test response")
            return {"test": root.text}
        payload = response.json()
        if (
            not isinstance(payload, dict)
            or ("errorsExist" in payload and payload["errorsExist"])
            or "errorList" in payload
        ):
            raise ValueError("Ex Libris returned an error or unexpected response")
        return payload

    async def execute(self, inputs):
        op = self.config.config
        if isinstance(op, ExLibrisOnNewAuthorityTaskConfig):
            return await self._poll(op)
        method, path = ROUTES[op.operation]
        values = op.model_dump(exclude_none=True, exclude={"operation"})
        body = values.pop("body", None)
        for key in tuple(values):
            marker = "{" + key + "}"
            if marker in path:
                path = path.replace(marker, quote(str(values.pop(key)), safe=""))
        payload = await self._request(method, path, params=values, body=body)
        result = {"data": payload}
        if op.operation == "list_authority_control_tasks":
            rows = payload.get("authority_control_task", [])
            if not isinstance(rows, list):
                raise ValueError("Ex Libris authority control tasks must be a list")
            result["items"] = rows
        return result

    async def _poll(self, op):
        rows = []
        for offset in range(0, 2000, 100):
            params = {
                "mode": op.mode,
                "order_by": "create_date",
                "direction": "desc",
                "limit": 100,
                "offset": offset,
            }
            if op.vocabulary_code:
                params["vocabulary_code"] = op.vocabulary_code
            payload = await self._request(
                "GET", "/almaws/v1/task-lists/authority-control-tasks", params=params
            )
            batch = payload.get("authority_control_task", [])
            if not isinstance(batch, list) or any(
                not isinstance(row, dict) or not row.get("id") for row in batch
            ):
                raise ValueError("Ex Libris authority task IDs are missing")
            rows.extend(batch)
            if len(batch) < 100:
                break
        else:
            raise ValueError(
                "More than 2,000 authority tasks; narrow the vocabulary before monitoring"
            )
        fresh = await self._filter_unseen(rows, lambda row: str(row["id"]))
        return {"tasks": fresh, "new_task_count": len(fresh)}

    @classmethod
    def should_propagate_output(cls, output, config):
        return (
            bool(output.get("new_task_count"))
            if config.get("operation") == "on_new_authority_task"
            else True
        )

    @classmethod
    def resolve_agent_event(cls, output):
        tasks = output.get("tasks") if isinstance(output, dict) else None
        if tasks is None:
            return super().resolve_agent_event(output)
        if not tasks:
            return None
        lines = [
            f"- {task.get('title') or 'Bibliographic record'}: authority task {task.get('id')}, MMS {task.get('mms_id')}; {task.get('bib_heading_before') or ''} → {task.get('bib_heading_after') or ''}"
            for task in tasks[:10]
        ]
        return {
            "text": f"Ex Libris Alma: {len(tasks)} new authority control task(s) in the monitored queue. Review or dismiss using the task IDs.\n"
            + "\n".join(lines),
            "conversation_key": None,
        }
