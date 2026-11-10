"""elmah.io API v3 operations, pinned to the provider's published Swagger contract.

API keys are pasted by the person. No sign-in or OAuth application is required.
The polling trigger baselines existing messages and paginates before deduplication.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
)
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin

BASE = "https://api.elmah.io"


class ElmahAPIKeyCredential(BaseModel):
    model_config = ConfigDict(
        title="elmah.io API Key",
        hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://docs.elmah.io/where-is-my-api-key/",
            "x-credential-instructions": "Paste an organization API key from elmah.io Organization settings → API Keys. Grant Logs: Read for the connection check and the read/write permissions needed by your operations. Deployment Tracking and Heartbeats require those features on your plan.",
        },
    )
    credential_type: Literal["elmah_api_key"] = Field(
        "elmah_api_key", json_schema_extra={"ui:hidden": True}
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
        value = clean_secret(value, field_name="API Key")
        if not value.isascii() or any(c.isspace() for c in value):
            raise ValueError("Paste the API key without a header or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(
        extra="forbid", hide_input_in_errors=True, populate_by_name=True
    )


class ElmahListMessagesConfig(_Input):
    """Fetch messages from a log."""

    operation: Literal["list_messages"] = Field(
        "list_messages", title="List Messages", json_schema_extra={"ui:hidden": True}
    )
    log_id: str = Field(
        ..., min_length=1, max_length=256, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$"
    )
    pageIndex: int = Field(
        0,
        ge=0,
        description="The page number of the result. When using pageIndex and pageSize only 10,000 messages can be returned. For example, if setting pageSize to 100 and pageIndex to 100, no log messages will be returned. To request more than 10,000 log messages you should use the searchAfter property instead.",
    )
    pageSize: int = Field(
        15,
        ge=1,
        le=100,
        description="The number of messages to load (max 100) or 15 if not set.",
    )
    query: str | None = Field(
        None, description="A full-text or Lucene query to limit the messages by."
    )
    from_time: AwareDatetime | None = Field(
        None,
        alias="from",
        description="A start date and time to search from (not included).",
    )
    to: AwareDatetime | None = Field(
        None, description="An end date and time to search to (not included)."
    )
    includeHeaders: bool = Field(
        False,
        description="Include headers like server variables and cookies in the result (slower).",
    )
    searchAfter: str | None = Field(
        None,
        description="Search after is an alternative to using pageIndex that will let you get more than 10,000 messages. Each search result contains a searchAfter property that should be set on future requests to continue from the end of the previous request, but only until the returned list of log messages is empty. When using searchAfter any value in the pageIndex property will be ignored.",
    )


class ElmahGetMessageConfig(_Input):
    """Fetch a message by its ID."""

    operation: Literal["get_message"] = Field(
        "get_message", title="Get Message", json_schema_extra={"ui:hidden": True}
    )
    message_id: str = Field(
        ..., min_length=1, max_length=256, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$"
    )
    log_id: str = Field(
        ..., min_length=1, max_length=256, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$"
    )


class Item(_Input):
    key: str | None = Field(None, description="The key of the item.")
    value: str | None = Field(None, description="The value of the item.")


class Breadcrumb(_Input):
    dateTime: AwareDatetime | None = Field(
        None,
        description="The date and time in UTC of the breadcrumb. If no date and time is provided, we will use the current date and time in UTC.",
    )
    severity: str | None = Field(
        None,
        description="An enum value representing the severity of this breadcrumb. The following values are allowed: Verbose, Debug, Information, Warning, Error, Fatal.",
    )
    action: str | None = Field(
        None,
        description="An action representing the breadcrumb. You can set a custom action or use one of the built-in: click, submit, navigation, request, error.",
    )
    message: str | None = Field(
        None,
        description="A message representing the breadcrumb. This should elaborate on the action.",
    )


class CreateMessage(_Input):
    application: str | None = Field(
        None,
        description="Used to identify which application logged this message. You can use this if you have multiple applications and services logging to the same log",
    )
    detail: str | None = Field(
        None,
        description="A longer description of the message. For errors this could be a stacktrace, but it's really up to you what to log in there.",
    )
    hostname: str | None = Field(
        None, description="The hostname of the server logging the message."
    )
    title: str = Field(
        ...,
        min_length=1,
        description="The textual title or headline of the message to log. The first 50k characters are searchable.",
    )
    titleTemplate: str | None = Field(
        None,
        description='The title template of the message to log. This property can be used from logging frameworks that supports\r\nstructured logging like: "{user} says {quote}". In the example, titleTemplate will be this string and title\r\nwill be "Gilfoyle says It\'s not magic. It\'s talent and sweat". The first 50k characters are searchable.',
    )
    source: str | None = Field(
        None,
        description="The source of the code logging the message. This could be the assembly name.",
    )
    statusCode: int | None = Field(
        None,
        description="If the message logged relates to a HTTP status code, you can put the code in this property. This would probably only be relevant for errors,\r\nbut could be used for logging successful status codes as well.",
    )
    dateTime: AwareDatetime | None = Field(
        None,
        description="The date and time in UTC of the message. If you don't provide us with a value in dateTime, we will set the current date and time in UTC.",
    )
    type: str | None = Field(
        None,
        description="The type of message. If logging an error, the type of the exception would go into type but you can put anything in there, that makes sense for your domain.",
    )
    user: str | None = Field(
        None,
        description="An identification of the user triggering this message. You can put the users email address or your user key into this property.",
    )
    severity: str | None = Field(
        None,
        description="An enum value representing the severity of this message. The following values are allowed: Verbose, Debug, Information, Warning, Error, Fatal",
    )
    url: str | None = Field(
        None,
        description="If message relates to a HTTP request, you may send the URL of that request. If you don't provide us with an URL, we will try to find a key named URL in serverVariables.",
    )
    method: str | None = Field(
        None,
        description="If message relates to a HTTP request, you may send the HTTP method of that request. If you don't provide us with a method, we will try to find a key named REQUEST_METHOD in serverVariables.",
    )
    version: str | None = Field(
        None,
        description="Versions can be used to distinguish messages from different versions of your software. The value of version can be a SemVer compliant string or any other\r\nsyntax that you are using as your version numbering scheme.",
    )
    correlationId: str | None = Field(
        None,
        description="CorrelationId can be used to group similar log messages together into a single discoverable batch. A correlation ID could be a session ID from ASP.NET Core,\r\na unique string spanning multiple microsservices handling the same request, or similar.",
    )
    code: str | None = Field(
        None,
        description="Code can be used to include source code related to the log message. The code will typically span from a few lines before the line causing the log message\r\nto a few lines after. For now, all lines above 21 will be removed. This makes room for showing 10 lines before the logging line, the logging line, and\r\n10 lines after the logging line. Don't include a very large string in this property since that will quickly make the entire messages exceed the max limit\r\nof 256 kb.",
    )
    category: str | None = Field(
        None,
        description="The log message category. Category can be a string of choice but typically contain a logging category set by a logging framework like NLog or Serilog.\r\nWhen logging through a logging framework, this field will be provided by the framework and not something that needs to be set manually.",
    )
    cookies: list[Item] | None = Field(
        None,
        description="A key/value pair of cookies. This property only makes sense for logging messages related to web requests.",
    )
    form: list[Item] | None = Field(
        None,
        description="A key/value pair of form fields and their values. This property makes sense if logging message related to users inputting data in a form.",
    )
    queryString: list[Item] | None = Field(
        None,
        description="A key/value pair of query string parameters. This property makes sense if logging message related to a HTTP request.",
    )
    serverVariables: list[Item] | None = Field(
        None,
        description="A key/value pair of server values. Server variables are typically related to handling requests in a webserver but could be used for other types of information as well.",
    )
    data: list[Item] | None = Field(
        None,
        description="A key/value pair of user-defined fields and their values. When logging an exception, the Data dictionary of\r\nthe exception is copied to this property. You can add additional key/value pairs, by modifying the Data\r\ndictionary on the exception or by supplying additional key/values to this API.",
    )
    breadcrumbs: list[Breadcrumb] | None = Field(
        None, description="A list of breadcrumbs preceding this log message."
    )


class ElmahCreateMessageConfig(_Input):
    """Create a new message."""

    operation: Literal["create_message"] = Field(
        "create_message", title="Create Message", json_schema_extra={"ui:hidden": True}
    )
    log_id: str = Field(
        ..., min_length=1, max_length=256, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$"
    )
    body: CreateMessage = Field(...)


class ElmahCreateMessagesBulkConfig(_Input):
    """Create one or more new messages."""

    operation: Literal["create_messages_bulk"] = Field(
        "create_messages_bulk",
        title="Create Messages Bulk",
        json_schema_extra={"ui:hidden": True},
    )
    log_id: str = Field(
        ..., min_length=1, max_length=256, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$"
    )
    body: list[CreateMessage] = Field(...)


class ElmahFixMessageConfig(_Input):
    """Fix a message by its ID."""

    operation: Literal["fix_message"] = Field(
        "fix_message", title="Fix Message", json_schema_extra={"ui:hidden": True}
    )
    message_id: str = Field(
        ..., min_length=1, max_length=256, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$"
    )
    log_id: str = Field(
        ..., min_length=1, max_length=256, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$"
    )
    markAllAsFixed: bool = Field(
        False,
        description="If set to true, all instances of the log message are set to fixed.",
    )


class ElmahHideMessageConfig(_Input):
    """Hide a message by its ID."""

    operation: Literal["hide_message"] = Field(
        "hide_message", title="Hide Message", json_schema_extra={"ui:hidden": True}
    )
    message_id: str = Field(
        ..., min_length=1, max_length=256, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$"
    )
    log_id: str = Field(
        ..., min_length=1, max_length=256, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$"
    )


class ElmahDeleteMessageConfig(_Input):
    """Delete a message by its ID."""

    operation: Literal["delete_message"] = Field(
        "delete_message", title="Delete Message", json_schema_extra={"ui:hidden": True}
    )
    message_id: str = Field(
        ..., min_length=1, max_length=256, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$"
    )
    log_id: str = Field(
        ..., min_length=1, max_length=256, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$"
    )


class Search(_Input):
    query: str | None = Field(None, description="Lucene query.")
    from_time: AwareDatetime | None = Field(
        None, alias="from", description="Search from this date."
    )
    to: AwareDatetime | None = Field(None, description="Search to this date.")


class ElmahFixMessagesConfig(_Input):
    """Mark a list of messages as fixed by logid and query."""

    operation: Literal["fix_messages"] = Field(
        "fix_messages", title="Fix Messages", json_schema_extra={"ui:hidden": True}
    )
    log_id: str = Field(
        ..., min_length=1, max_length=256, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$"
    )
    body: Search = Field(...)


class ElmahDeleteMessagesConfig(_Input):
    """Deletes a list of messages by logid and query."""

    operation: Literal["delete_messages"] = Field(
        "delete_messages",
        title="Delete Messages",
        json_schema_extra={"ui:hidden": True},
    )
    log_id: str = Field(
        ..., min_length=1, max_length=256, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$"
    )
    body: Search = Field(...)


class ElmahListLogsConfig(_Input):
    """Fetch a list of logs."""

    operation: Literal["list_logs"] = Field(
        "list_logs", title="List Logs", json_schema_extra={"ui:hidden": True}
    )


class ElmahGetLogConfig(_Input):
    """Fetch a log by its ID."""

    operation: Literal["get_log"] = Field(
        "get_log", title="Get Log", json_schema_extra={"ui:hidden": True}
    )
    log_id: str = Field(
        ..., min_length=1, max_length=256, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$"
    )


class CreateLog(_Input):
    name: str = Field(
        ..., min_length=1, max_length=256, description="Name of the new log."
    )
    color: str | None = Field(
        None,
        description="Color of the log. The color must be one of the following (green on unknown value or missing):\r\ngreen, lightgreen, lime, yellow, orange, deeporange, red, pink, purple, deeppurple, blue, lightblue",
    )
    environmentName: str | None = Field(
        None,
        description='Environment name of the new log. Must match an environment name (case insensitive).\r\nIf a matching environment name was not found or the property is not set, the log\r\nwill appear under "Other" in the UI.',
    )
    disabled: bool | None = Field(
        None,
        description="Set to true to disable the log on creation. Defaults to false. A log can be enabled/disabled\r\nafterwards by calling the _disable and _enable endpoints.",
    )


class ElmahCreateLogConfig(_Input):
    """Create a new log."""

    operation: Literal["create_log"] = Field(
        "create_log", title="Create Log", json_schema_extra={"ui:hidden": True}
    )
    body: CreateLog = Field(...)


class ElmahEnableLogConfig(_Input):
    """Enable a log by its ID."""

    operation: Literal["enable_log"] = Field(
        "enable_log", title="Enable Log", json_schema_extra={"ui:hidden": True}
    )
    log_id: str = Field(
        ..., min_length=1, max_length=256, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$"
    )


class ElmahDisableLogConfig(_Input):
    """Disable a log by its ID."""

    operation: Literal["disable_log"] = Field(
        "disable_log", title="Disable Log", json_schema_extra={"ui:hidden": True}
    )
    log_id: str = Field(
        ..., min_length=1, max_length=256, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$"
    )


class ElmahDiagnoseLogConfig(_Input):
    """Help diagnose logging problems."""

    operation: Literal["diagnose_log"] = Field(
        "diagnose_log", title="Diagnose Log", json_schema_extra={"ui:hidden": True}
    )
    log_id: str = Field(
        ..., min_length=1, max_length=256, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$"
    )


class ElmahDeleteLogConfig(_Input):
    """Delete a log by its ID."""

    operation: Literal["delete_log"] = Field(
        "delete_log", title="Delete Log", json_schema_extra={"ui:hidden": True}
    )
    log_id: str = Field(
        ..., min_length=1, max_length=256, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$"
    )


class CreateDeployment(_Input):
    version: str = Field(
        ...,
        min_length=1,
        max_length=256,
        description="The version number of this deployment. The value of version can be a SemVer compliant string or any other\r\nsyntax that you are using as your version numbering scheme.",
    )
    created: AwareDatetime | None = Field(
        None,
        description="When was this deployment created in UTC. Defaults to current time if not specified.",
    )
    description: str | None = Field(
        None,
        max_length=8192,
        description="Optional description of this deployment. Can be markdown or clear text.",
    )
    userName: str | None = Field(
        None,
        max_length=256,
        description="The name of the person responsible for creating this deployment. This can be the name taken from\r\nyour deployment server (like Azure DevOps or Octopus).",
    )
    userEmail: EmailStr | None = Field(
        None,
        max_length=320,
        description="The email of the person responsible for creating this deployment. This can be the email taken from\r\nyour deployment server (like Azure DevOps or Octopus).",
    )
    logId: str | None = Field(
        None,
        description="As default, deployments are attached all logs of the organization. If you want a deployment to\r\nattach to a single log only, set this to the ID of that log.",
    )


class ElmahCreateDeploymentConfig(_Input):
    """Create a new deployment."""

    operation: Literal["create_deployment"] = Field(
        "create_deployment",
        title="Create Deployment",
        json_schema_extra={"ui:hidden": True},
    )
    body: CreateDeployment = Field(...)


class ElmahListDeploymentsConfig(_Input):
    """Fetch a list of deployments."""

    operation: Literal["list_deployments"] = Field(
        "list_deployments",
        title="List Deployments",
        json_schema_extra={"ui:hidden": True},
    )


class ElmahGetDeploymentConfig(_Input):
    """Fetch a deployment by its ID."""

    operation: Literal["get_deployment"] = Field(
        "get_deployment", title="Get Deployment", json_schema_extra={"ui:hidden": True}
    )
    deployment_id: str = Field(
        ..., min_length=1, max_length=256, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$"
    )


class ElmahDeleteDeploymentConfig(_Input):
    """Delete a deployment by its ID."""

    operation: Literal["delete_deployment"] = Field(
        "delete_deployment",
        title="Delete Deployment",
        json_schema_extra={"ui:hidden": True},
    )
    deployment_id: str = Field(
        ..., min_length=1, max_length=256, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$"
    )


class Check(_Input):
    name: str | None = Field(None, max_length=256, description="The name of the check.")
    took: int | None = Field(
        None,
        description="Optional long for specifying how many milliseconds it took to execute the check.",
    )
    result: str | None = Field(
        None,
        max_length=9,
        description='The result of this check. Can be "Healthy, "Degraded", or "Unhealthy". Defaults to "Healthy"',
    )
    reason: str | None = Field(
        None,
        max_length=8192,
        description='If result is "Degraded" or "Unhealthy" you can use this property to specify why.',
    )


class CreateHeartbeat(_Input):
    result: str | None = Field(
        None,
        max_length=9,
        description='The result of this heartbeat. Can be "Healthy, "Degraded", or "Unhealthy". Defaults to "Healthy"',
    )
    reason: str | None = Field(
        None,
        max_length=8192,
        description='If result is "Degraded" or "Unhealthy" you can use this property to specify why.',
    )
    application: str | None = Field(
        None,
        max_length=256,
        description='Optional string to identify which application logged this message. You can use this if you have multiple applications and services logging to the same log.\r\nIf not set, the application name "Heartbeats" will be set on all log messages generated from this heartbeat.',
    )
    version: str | None = Field(
        None,
        max_length=256,
        description="Optional string to identify which version of your application logged this message. If not specified, any errors, warnings, or information messages will get\r\nthe newest version number created through deployment tracking as with normal log messages.",
    )
    took: int | None = Field(
        None,
        description="Optional long for specifying how many milliseconds it took to execute the task resulting in this heartbeat. This can be used to get a better overview\r\nof how long a scheduled task or service is running or to figure out if the grace period should be increased.",
    )
    checks: list[Check] | None = Field(
        None, description="A list of checks in this heartbeat."
    )


class ElmahSendHeartbeatConfig(_Input):
    """Create a new heartbeat."""

    operation: Literal["send_heartbeat"] = Field(
        "send_heartbeat", title="Send Heartbeat", json_schema_extra={"ui:hidden": True}
    )
    heartbeat_id: str = Field(
        ..., min_length=1, max_length=256, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$"
    )
    log_id: str = Field(
        ..., min_length=1, max_length=256, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$"
    )
    body: CreateHeartbeat = Field(...)


class ElmahOnNewMessageConfig(PollTriggerConfigBase):
    """New log messages, checked on a schedule; existing messages form a baseline."""

    operation: Literal["on_new_message"] = Field(
        "on_new_message",
        title="On New Message",
        json_schema_extra={
            "ui:hidden": True,
            "x-is-trigger": True,
            "x-category": "Triggers",
            "x-display-name": "On New Message",
        },
    )
    log_id: str = Field(
        ..., min_length=1, max_length=256, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$"
    )
    from_time: AwareDatetime | None = Field(
        None,
        description="Only watch messages after this UTC timestamp. Set a recent start time for logs with more than 2,000 matching messages.",
    )
    query: str | None = Field(
        None,
        description="Optional full-text or Lucene query, for example severity:Error.",
    )


ElmahConfig = Annotated[
    Union[
        ElmahListMessagesConfig,
        ElmahGetMessageConfig,
        ElmahCreateMessageConfig,
        ElmahCreateMessagesBulkConfig,
        ElmahFixMessageConfig,
        ElmahHideMessageConfig,
        ElmahDeleteMessageConfig,
        ElmahFixMessagesConfig,
        ElmahDeleteMessagesConfig,
        ElmahListLogsConfig,
        ElmahGetLogConfig,
        ElmahCreateLogConfig,
        ElmahEnableLogConfig,
        ElmahDisableLogConfig,
        ElmahDiagnoseLogConfig,
        ElmahDeleteLogConfig,
        ElmahCreateDeploymentConfig,
        ElmahListDeploymentsConfig,
        ElmahGetDeploymentConfig,
        ElmahDeleteDeploymentConfig,
        ElmahSendHeartbeatConfig,
        ElmahOnNewMessageConfig,
    ],
    Field(discriminator="operation"),
]


class ElmahNodeConfig(NodeConfig[ElmahConfig, ElmahAPIKeyCredential]):
    pass


OPERATIONS = {
    "list_messages": {
        "method": "GET",
        "path": "/v3/messages/{logId}",
        "paths": {"logId": "log_id"},
        "params": {
            "pageIndex": "pageIndex",
            "pageSize": "pageSize",
            "query": "query",
            "from": "from_time",
            "to": "to",
            "includeHeaders": "includeHeaders",
            "searchAfter": "searchAfter",
        },
        "body": False,
        "contract_operation": "Messages_GetAll",
    },
    "get_message": {
        "method": "GET",
        "path": "/v3/messages/{logId}/{id}",
        "paths": {"id": "message_id", "logId": "log_id"},
        "params": {},
        "body": False,
        "contract_operation": "Messages_Get",
    },
    "create_message": {
        "method": "POST",
        "path": "/v3/messages/{logId}",
        "paths": {"logId": "log_id"},
        "params": {},
        "body": True,
        "contract_operation": "Messages_Create",
    },
    "create_messages_bulk": {
        "method": "POST",
        "path": "/v3/messages/{logId}/_bulk",
        "paths": {"logId": "log_id"},
        "params": {},
        "body": True,
        "contract_operation": "Messages_CreateBulk",
    },
    "fix_message": {
        "method": "POST",
        "path": "/v3/messages/{logId}/{id}/_fix",
        "paths": {"id": "message_id", "logId": "log_id"},
        "params": {"markAllAsFixed": "markAllAsFixed"},
        "body": False,
        "contract_operation": "Messages_Fix",
    },
    "hide_message": {
        "method": "POST",
        "path": "/v3/messages/{logId}/{id}/_hide",
        "paths": {"id": "message_id", "logId": "log_id"},
        "params": {},
        "body": False,
        "contract_operation": "Messages_Hide",
    },
    "delete_message": {
        "method": "DELETE",
        "path": "/v3/messages/{logId}/{id}",
        "paths": {"id": "message_id", "logId": "log_id"},
        "params": {},
        "body": False,
        "contract_operation": "Messages_Delete",
    },
    "fix_messages": {
        "method": "POST",
        "path": "/v3/messages/{logId}/_fix",
        "paths": {"logId": "log_id"},
        "params": {},
        "body": True,
        "contract_operation": "Messages_FixAll",
    },
    "delete_messages": {
        "method": "DELETE",
        "path": "/v3/messages/{logId}",
        "paths": {"logId": "log_id"},
        "params": {},
        "body": True,
        "contract_operation": "Messages_DeleteAll",
    },
    "list_logs": {
        "method": "GET",
        "path": "/v3/logs",
        "paths": {},
        "params": {},
        "body": False,
        "contract_operation": "Logs_GetAll",
    },
    "get_log": {
        "method": "GET",
        "path": "/v3/logs/{id}",
        "paths": {"id": "log_id"},
        "params": {},
        "body": False,
        "contract_operation": "Logs_Get",
    },
    "create_log": {
        "method": "POST",
        "path": "/v3/logs",
        "paths": {},
        "params": {},
        "body": True,
        "contract_operation": "Logs_Create",
    },
    "enable_log": {
        "method": "POST",
        "path": "/v3/logs/{id}/_enable",
        "paths": {"id": "log_id"},
        "params": {},
        "body": False,
        "contract_operation": "Logs_Enable",
    },
    "disable_log": {
        "method": "POST",
        "path": "/v3/logs/{id}/_disable",
        "paths": {"id": "log_id"},
        "params": {},
        "body": False,
        "contract_operation": "Logs_Disable",
    },
    "diagnose_log": {
        "method": "GET",
        "path": "/v3/logs/{id}/_diagnose",
        "paths": {"id": "log_id"},
        "params": {},
        "body": False,
        "contract_operation": "Logs_Diagnose",
    },
    "delete_log": {
        "method": "DELETE",
        "path": "/v3/logs/{id}",
        "paths": {"id": "log_id"},
        "params": {},
        "body": False,
        "contract_operation": "Logs_Delete",
    },
    "create_deployment": {
        "method": "POST",
        "path": "/v3/deployments",
        "paths": {},
        "params": {},
        "body": True,
        "contract_operation": "Deployments_Create",
    },
    "list_deployments": {
        "method": "GET",
        "path": "/v3/deployments",
        "paths": {},
        "params": {},
        "body": False,
        "contract_operation": "Deployments_GetAll",
    },
    "get_deployment": {
        "method": "GET",
        "path": "/v3/deployments/{id}",
        "paths": {"id": "deployment_id"},
        "params": {},
        "body": False,
        "contract_operation": "Deployments_Get",
    },
    "delete_deployment": {
        "method": "DELETE",
        "path": "/v3/deployments/{id}",
        "paths": {"id": "deployment_id"},
        "params": {},
        "body": False,
        "contract_operation": "Deployments_Delete",
    },
    "send_heartbeat": {
        "method": "POST",
        "path": "/v3/heartbeats/{logId}/{id}",
        "paths": {"id": "heartbeat_id", "logId": "log_id"},
        "params": {},
        "body": True,
        "contract_operation": "Heartbeats_Create",
    },
}


class ElmahNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-elmah"
    connection_evidence = ConnectionEvidence(noun="logs", operation="list_logs")

    @classmethod
    def get_config_model(cls):
        return ElmahNodeConfig

    @staticmethod
    async def _request(api_key, method, path, *, params=None, body=None):
        # Query placement is exactly the security scheme in the published Swagger.
        # Never propagate an httpx exception: it can contain the key-bearing URL.
        try:
            async with httpx.AsyncClient(
                timeout=30, follow_redirects=False, trust_env=False
            ) as client:
                response = await client.request(
                    method,
                    BASE + path,
                    params={**(params or {}), "api_key": api_key},
                    json=body,
                    headers={"Accept": "application/json"},
                )
        except httpx.HTTPError:
            raise ValueError(
                "elmah.io request could not be completed; check the service before retrying a write"
            ) from None
        if not 200 <= response.status_code < 300:
            detail = response.text.replace(api_key, "[redacted]")[:1000]
            raise ValueError(f"elmah.io API error {response.status_code}: {detail}")
        try:
            data = response.json() if response.content else None
        except ValueError:
            raise ValueError("elmah.io returned an invalid JSON response") from None
        # Raw API data stays inside data; empty acknowledgments and creation
        # locations retain their documented semantics (200 need not create).
        return {"data": data, "http_status": response.status_code}

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect an elmah.io API key")
        config = self.config.config
        key = self.config.credentials.api_key
        if isinstance(config, ElmahOnNewMessageConfig):
            return await self._poll_messages(key, config)
        spec = OPERATIONS[config.operation]
        values = config.model_dump(mode="json", exclude_none=True)
        path = spec["path"]
        for wire, name in spec["paths"].items():
            path = path.replace("{" + wire + "}", quote(values[name], safe=""))
        params = {
            wire: values[name]
            for wire, name in spec["params"].items()
            if name in values
        }
        result = await self._request(
            key,
            spec["method"],
            path,
            params=params,
            body=config.model_dump(mode="json", exclude_none=True, by_alias=True).get(
                "body"
            )
            if spec["body"]
            else None,
        )
        if config.operation == "create_message":
            result["message_created"] = result["http_status"] == 201
        await self.emit(result)
        return result

    async def _poll_messages(self, key, config):
        values = config.model_dump(mode="json", exclude_none=True)
        params = {"pageSize": 100}
        if config.from_time is not None:
            params["from"] = values["from_time"]
        if config.query is not None:
            params["query"] = config.query
        messages, cursors = [], set()
        for page in range(20):
            result = await self._request(
                key,
                "GET",
                "/v3/messages/" + quote(config.log_id, safe=""),
                params=params,
            )
            data = result["data"]
            if not isinstance(data, dict) or not isinstance(data.get("messages"), list):
                raise ValueError("elmah.io returned an invalid messages list")
            rows = data["messages"]
            if any(
                not isinstance(row, dict)
                or not isinstance(row.get("id"), str)
                or not row["id"]
                for row in rows
            ):
                raise ValueError("elmah.io returned a message without an ID")
            messages.extend(rows)
            cursor = data.get("searchAfter")
            total = data.get("total")
            if not rows or (isinstance(total, int) and len(messages) >= total):
                break
            if cursor:
                if cursor in cursors:
                    raise ValueError("elmah.io repeated a message pagination cursor")
                cursors.add(cursor)
                params["searchAfter"] = cursor
            elif len(rows) < 100:
                break
            else:
                params["pageIndex"] = page + 1
        else:
            raise ValueError(
                "More than 2,000 messages match this poll; narrow the start time or query"
            )
        fresh = await self._filter_unseen(messages, lambda item: item["id"])
        return {
            "messages": fresh,
            "new_message_count": len(fresh),
            "log_id": config.log_id,
        }

    @classmethod
    def resolve_agent_event(cls, output):
        rows = output.get("messages") or []
        if not rows:
            return None
        log_id = output.get("log_id")
        lines = [f"New elmah.io messages in log {log_id}:"]
        for row in rows[:20]:
            lines.append(
                f"{row.get('severity', 'Message')}: {row.get('title', '')} "
                f"(message {row.get('id')}, at {row.get('dateTime', '')}, "
                f"application {row.get('application', '')}, user {row.get('user', '')})"
            )
            if row.get("detail"):
                lines.append(str(row["detail"])[:2000])
        return {
            "text": "\n".join(lines)[:12000],
            "conversation_key": f"elmah:{log_id}",
            "title": "New elmah.io messages",
        }
