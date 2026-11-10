"""Browse AI v2 operations and unsigned webhook triggers.

Contract: https://developers.browse.ai/ (published OpenAPI v2).
Delivery: https://help.browse.ai/en/articles/12683642-webhooks-set-up-guide
"""
from __future__ import annotations
import json
import math
from typing import Annotated, Literal, Union
from urllib.parse import quote
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase

BASE = "https://api.browse.ai/v2"

class BrowseaiAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Browse AI API Key", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://dashboard.browse.ai/api",
            "x-credential-instructions": "Paste your Browse AI secret API key from Dashboard → API. Do not include the Bearer prefix."})
    credential_type: Literal["browseai_api_key"] = Field("browseai_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API Key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API key without a Bearer prefix or whitespace")
        return value

class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

class BrowseaiListTeamsConfig(_Input):
    """Retrieve list of teams under user account."""
    operation: Literal["list_teams"] = Field("list_teams", title="List Teams", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})

class BrowseaiListRobotsConfig(_Input):
    """Retrieve list of robots under your account."""
    operation: Literal["list_robots"] = Field("list_robots", title="List Robots", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})

class BrowseaiGetRobotConfig(_Input):
    """Retrieve single robot by ID."""
    operation: Literal["get_robot"] = Field("get_robot", title="Get Robot", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})
    robotId: str = Field(..., title='Robot ID', description="Unique robot ID You can find a robot's ID by opening it on the dashboard and copying its ID in the browser address bar.\n")

class BrowseaiListTasksConfig(_Input):
    """Get all tasks by a robot."""
    operation: Literal["list_tasks"] = Field("list_tasks", title="List Tasks", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})
    robotId: str = Field(..., title='Robot ID', description="Unique robot ID\n\nYou can find a robot's ID by opening it on the dashboard and copying its ID in the browser address bar.\n")
    page: int | None = Field(None, title='Page', description='Page number', ge=1)
    pageSize: int | None = Field(None, title='Page Size', description='Page size', ge=1, le=10)
    status: Literal['failed', 'successful', 'in-progress'] | None = Field(None, title='Status', description='Task status')
    robotBulkRunId: str | None = Field(None, title='Robot Bulk Run ID', description='filter the result based on robot bulk run ID')
    sort: str | None = Field(None, title='Sort', description="A comma separated list of fields to sort by. Default sorting is ascending and prefixing field names with a hyphen '-' yields a descending order.")
    includeRetried: bool | None = Field(None, title='Include Retried', description='by passing false you can exclude the retried tasks')
    fromDate: int | None = Field(None, title='From Date', description='From task creation date and time in the form of a Unix timestamp')
    toDate: int | None = Field(None, title='To Date', description='To task creation date and time in the form of a Unix timestamp')

class BrowseaiRunTaskConfig(_Input):
    """Run a robot."""
    operation: Literal["run_task"] = Field("run_task", title="Run Task", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})
    robotId: str = Field(..., title='Robot ID', description="Unique robot ID\n\nYou can find a robot's ID by opening it on the dashboard and copying its ID in the browser address bar.\n")
    recordVideo: bool | None = Field(None, title='Record Video', description='Try to record a video while running the task. This is not guaranteed to work as the robot might skip video recording if the site is too heavy.')
    inputParameters_json: str | None = Field(None, title='Input Parameters', description='An object of input parameters to override default input parameters. Enter JSON.', json_schema_extra={'ui:widget': 'code_editor', 'x-code-language': 'json'})

class BrowseaiGetTaskConfig(_Input):
    """Retrieve a task."""
    operation: Literal["get_task"] = Field("get_task", title="Get Task", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})
    robotId: str = Field(..., title='Robot ID', description="Unique robot ID\n\nYou can find a robot's ID by opening it on the dashboard and copying its ID in the browser address bar.\n")
    taskId: str = Field(..., title='Task ID', description='Unique task ID')

class BrowseaiListMonitorsConfig(_Input):
    """Retrieve a robot's monitors."""
    operation: Literal["list_monitors"] = Field("list_monitors", title="List Monitors", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})
    robotId: str = Field(..., title='Robot ID', description="Unique robot ID\n\nYou can find a robot's ID by opening it on the dashboard and copying its ID in the browser address bar.\n")

class BrowseaiCreateMonitorConfig(_Input):
    """Create a new monitor on a robot."""
    operation: Literal["create_monitor"] = Field("create_monitor", title="Create Monitor", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})
    robotId: str = Field(..., title='Robot ID', description="Unique robot ID\n\nYou can find a robot's ID by opening it on the dashboard and copying its ID in the browser address bar.\n")
    name: str = Field(..., title='Name', description='Monitor name', min_length=1, max_length=200)
    inputParameters_json: str = Field(..., title='Input Parameters', description='An object of input parameters to override default input parameters. Enter JSON.', json_schema_extra={'ui:widget': 'code_editor', 'x-code-language': 'json'})
    schedule: str | None = Field(None, title='Schedule', description='recurring schedule.\n')
    notifyOnCapturedScreenshotChange: bool = Field(..., title='Notify On Captured Screenshot Change', description='If set to `true`, an email notification will be sent to you when a change is detected in captured screenshots.')
    notifyOnCapturedTextChange: bool = Field(..., title='Notify On Captured Text Change', description='If set to `true`, an email notification will be sent to you when a change is detected in captured texts.')
    capturedScreenshotNotificationThreshold: float = Field(..., title='Captured Screenshot Notification Threshold', description='The "screenshot changed" email notification will be sent to you if the change is greater than this threshold (in percent).')

class BrowseaiGetMonitorConfig(_Input):
    """Retrieve a robot's monitor."""
    operation: Literal["get_monitor"] = Field("get_monitor", title="Get Monitor", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})
    robotId: str = Field(..., title='Robot ID', description="Unique robot ID\n\nYou can find a robot's ID by opening it on the dashboard and copying its ID in the browser address bar.\n")
    monitorId: str = Field(..., title='Monitor ID', description="Unique monitor ID\n\nYou can find a monitor's ID by opening it on the dashboard and copying its ID in the browser address bar.\n")

class BrowseaiUpdateMonitorConfig(_Input):
    """Update a robot's monitor."""
    operation: Literal["update_monitor"] = Field("update_monitor", title="Update Monitor", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})
    robotId: str = Field(..., title='Robot ID', description="Unique robot ID\n\nYou can find a robot's ID by opening it on the dashboard and copying its ID in the browser address bar.\n")
    monitorId: str = Field(..., title='Monitor ID', description="Unique monitor ID\n\nYou can find a monitor's ID by opening it on the dashboard and copying its ID in the browser address bar.\n")
    name: str | None = Field(None, title='Name', description='Monitor name')
    status: Literal['active', 'paused'] | None = Field(None, title='Status', description='If set to `paused`, the monitor will stop working until an `active` status is sent.')
    inputParameters_json: str | None = Field(None, title='Input Parameters', description='An object of input parameters to override default input parameters. Enter JSON.', json_schema_extra={'ui:widget': 'code_editor', 'x-code-language': 'json'})
    schedule: str | None = Field(None, title='Schedule', description='recurring schedule.\n')
    notifyOnCapturedScreenshotChange: bool | None = Field(None, title='Notify On Captured Screenshot Change', description='If set to `true`, an email notification will be sent to you when a change is detected in captured screenshots.')
    notifyOnCapturedTextChange: bool | None = Field(None, title='Notify On Captured Text Change', description='If set to `true`, an email notification will be sent to you when a change is detected in captured texts.')
    capturedScreenshotNotificationThreshold: float | None = Field(None, title='Captured Screenshot Notification Threshold', description='The "screenshot changed" email notification will be sent to you if the change is greater than this threshold (in percent).')

class BrowseaiDeleteMonitorConfig(_Input):
    """Delete a robot's monitor."""
    operation: Literal["delete_monitor"] = Field("delete_monitor", title="Delete Monitor", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})
    robotId: str = Field(..., title='Robot ID', description="Unique robot ID\n\nYou can find a robot's ID by opening it on the dashboard and copying its ID in the browser address bar.\n")
    monitorId: str = Field(..., title='Monitor ID', description="Unique monitor ID\n\nYou can find a monitor's ID by opening it on the dashboard and copying its ID in the browser address bar.\n")

class BrowseaiCreateBulkRunConfig(_Input):
    """Bulk run tasks."""
    operation: Literal["create_bulk_run"] = Field("create_bulk_run", title="Create Bulk Run", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})
    robotId: str = Field(..., title='Robot ID', description="Unique robot ID\n\nYou can find a robot's ID by opening it on the dashboard and copying its ID in the browser address bar.\n")
    title: str | None = Field(None, title='Title', description='A string that describes the bulk run.', min_length=1, max_length=200)
    inputParameters_json: str = Field(..., title='Input Parameters', description="An array of input parameters to override the task's default input parameters. Enter JSON.", json_schema_extra={'ui:widget': 'code_editor', 'x-code-language': 'json'})

class BrowseaiListBulkRunsConfig(_Input):
    """Retrieve a robot's bulk runs list."""
    operation: Literal["list_bulk_runs"] = Field("list_bulk_runs", title="List Bulk Runs", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})
    robotId: str = Field(..., title='Robot ID', description="Unique robot ID\n\nYou can find a robot's ID by opening it on the dashboard and copying its ID in the browser address bar.\n")
    page: int | None = Field(None, title='Page', description='Page number', ge=1)

class BrowseaiGetBulkRunConfig(_Input):
    """Retrieve a robot's bulk run."""
    operation: Literal["get_bulk_run"] = Field("get_bulk_run", title="Get Bulk Run", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})
    robotId: str = Field(..., title='Robot ID', description="Unique robot ID\n\nYou can find a robot's ID by opening it on the dashboard and copying its ID in the browser address bar.\n")
    bulkRunId: str = Field(..., title='Bulk Run ID', description='Unique bulk run ID\n')
    page: int | None = Field(None, title='Page', description='Page number', ge=1)

class BrowseaiListWebhooksConfig(_Input):
    """Retrieve a robot's webhooks."""
    operation: Literal["list_webhooks"] = Field("list_webhooks", title="List Webhooks", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})
    robotId: str = Field(..., title='Robot ID', description="Unique robot ID\n\nYou can find a robot's ID by opening it on the dashboard and copying its ID in the browser address bar.\n")

class BrowseaiCreateWebhookConfig(_Input):
    """Create a new webhook on a robot."""
    operation: Literal["create_webhook"] = Field("create_webhook", title="Create Webhook", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})
    robotId: str = Field(..., title='Robot ID', description="Unique robot ID\n\nYou can find a robot's ID by opening it on the dashboard and copying its ID in the browser address bar.\n")
    hookUrl: str = Field(..., title='Hook URL', description='Webhook URL')
    eventType: Literal['taskCapturedDataChanged', 'taskFinished', 'taskFinishedSuccessfully', 'taskFinishedWithError', 'tableExportFinishedSuccessfully'] = Field(..., title='Event Type', description='')

class BrowseaiDeleteWebhookConfig(_Input):
    """Delete a robot's webhook."""
    operation: Literal["delete_webhook"] = Field("delete_webhook", title="Delete Webhook", json_schema_extra={"ui:hidden": True, "x-is-trigger": False})
    robotId: str = Field(..., title='Robot ID', description="Unique robot ID\n\nYou can find a robot's ID by opening it on the dashboard and copying its ID in the browser address bar.\n")
    webhookId: str = Field(..., title='Webhook ID', description='Unique webhookId ID\n')

OPERATIONS = {'list_teams': {'method': 'GET',
                'path': '/teams',
                'query': [],
                'body': [],
                'json': [],
                'contract': 'getUserTeams'},
 'list_robots': {'method': 'GET',
                 'path': '/robots',
                 'query': [],
                 'body': [],
                 'json': [],
                 'contract': 'getRobots'},
 'get_robot': {'method': 'GET',
               'path': '/robots/{robotId}',
               'query': [],
               'body': [],
               'json': [],
               'contract': 'getRobot'},
 'list_tasks': {'method': 'GET',
                'path': '/robots/{robotId}/tasks',
                'query': ['page',
                          'pageSize',
                          'status',
                          'robotBulkRunId',
                          'sort',
                          'includeRetried',
                          'fromDate',
                          'toDate'],
                'body': [],
                'json': [],
                'contract': 'getRobotTasks'},
 'run_task': {'method': 'POST',
              'path': '/robots/{robotId}/tasks',
              'query': [],
              'body': ['recordVideo', 'inputParameters'],
              'json': ['inputParameters'],
              'contract': 'newRobotTask'},
 'get_task': {'method': 'GET',
              'path': '/robots/{robotId}/tasks/{taskId}',
              'query': [],
              'body': [],
              'json': [],
              'contract': 'getRobotTask'},
 'list_monitors': {'method': 'GET',
                   'path': '/robots/{robotId}/monitors',
                   'query': [],
                   'body': [],
                   'json': [],
                   'contract': 'getMonitors'},
 'create_monitor': {'method': 'POST',
                    'path': '/robots/{robotId}/monitors',
                    'query': [],
                    'body': ['name',
                             'inputParameters',
                             'schedule',
                             'notifyOnCapturedScreenshotChange',
                             'notifyOnCapturedTextChange',
                             'capturedScreenshotNotificationThreshold'],
                    'json': ['inputParameters'],
                    'contract': 'createNewMonitor'},
 'get_monitor': {'method': 'GET',
                 'path': '/robots/{robotId}/monitors/{monitorId}',
                 'query': [],
                 'body': [],
                 'json': [],
                 'contract': 'getMonitor'},
 'update_monitor': {'method': 'PATCH',
                    'path': '/robots/{robotId}/monitors/{monitorId}',
                    'query': [],
                    'body': ['name',
                             'status',
                             'inputParameters',
                             'schedule',
                             'notifyOnCapturedScreenshotChange',
                             'notifyOnCapturedTextChange',
                             'capturedScreenshotNotificationThreshold'],
                    'json': ['inputParameters'],
                    'contract': 'updateMonitor'},
 'delete_monitor': {'method': 'DELETE',
                    'path': '/robots/{robotId}/monitors/{monitorId}',
                    'query': [],
                    'body': [],
                    'json': [],
                    'contract': 'deleteMonitor'},
 'create_bulk_run': {'method': 'POST',
                     'path': '/robots/{robotId}/bulk-runs',
                     'query': [],
                     'body': ['title', 'inputParameters'],
                     'json': ['inputParameters'],
                     'contract': 'newBulkRun'},
 'list_bulk_runs': {'method': 'GET',
                    'path': '/robots/{robotId}/bulk-runs',
                    'query': ['page'],
                    'body': [],
                    'json': [],
                    'contract': 'getBulkRuns'},
 'get_bulk_run': {'method': 'GET',
                  'path': '/robots/{robotId}/bulk-runs/{bulkRunId}',
                  'query': ['page'],
                  'body': [],
                  'json': [],
                  'contract': 'getBulkRun'},
 'list_webhooks': {'method': 'GET',
                   'path': '/robots/{robotId}/webhooks',
                   'query': [],
                   'body': [],
                   'json': [],
                   'contract': 'getWebhooks'},
 'create_webhook': {'method': 'POST',
                    'path': '/robots/{robotId}/webhooks',
                    'query': [],
                    'body': ['hookUrl', 'eventType'],
                    'json': [],
                    'contract': 'createNewWebhook'},
 'delete_webhook': {'method': 'DELETE',
                    'path': '/robots/{robotId}/webhooks/{webhookId}',
                    'query': [],
                    'body': [],
                    'json': [],
                    'contract': 'deleteWebhook'}}

class BrowseaiOnTaskFinishedConfig(WebhookTriggerConfigBase):
    operation: Literal["on_task_finished"] = Field("on_task_finished", title="On Task Finished", json_schema_extra={"ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers"})
    robotId: str = Field(..., title="Robot ID", min_length=1)
    webhook_url: str | None = Field(None, title="Webhook URL", description="Registered automatically. Browse AI sends unsigned deliveries; keep this URL private.", json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True})

class BrowseaiOnDataChangedConfig(WebhookTriggerConfigBase):
    operation: Literal["on_data_changed"] = Field("on_data_changed", title="On Data Changed", json_schema_extra={"ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers"})
    robotId: str = Field(..., title="Robot ID", min_length=1)
    webhook_url: str | None = Field(None, title="Webhook URL", description="Registered automatically. Browse AI sends unsigned deliveries; keep this URL private.", json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True})

class BrowseaiOnTableExportFinishedConfig(WebhookTriggerConfigBase):
    operation: Literal["on_table_export_finished"] = Field("on_table_export_finished", title="On Table Export Finished", json_schema_extra={"ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers"})
    robotId: str = Field(..., title="Robot ID", min_length=1)
    webhook_url: str | None = Field(None, title="Webhook URL", description="Registered automatically. Browse AI sends unsigned deliveries; keep this URL private.", json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True})

TRIGGERS = {'on_task_finished': ('taskFinished', ['task.finishedSuccessfully', 'task.finishedWithError']),
 'on_data_changed': ('taskCapturedDataChanged', ['task.capturedDataChanged']),
 'on_table_export_finished': ('tableExportFinishedSuccessfully', [])}

BrowseaiConfig = Annotated[Union[BrowseaiListTeamsConfig, BrowseaiListRobotsConfig, BrowseaiGetRobotConfig, BrowseaiListTasksConfig, BrowseaiRunTaskConfig, BrowseaiGetTaskConfig, BrowseaiListMonitorsConfig, BrowseaiCreateMonitorConfig, BrowseaiGetMonitorConfig, BrowseaiUpdateMonitorConfig, BrowseaiDeleteMonitorConfig, BrowseaiCreateBulkRunConfig, BrowseaiListBulkRunsConfig, BrowseaiGetBulkRunConfig, BrowseaiListWebhooksConfig, BrowseaiCreateWebhookConfig, BrowseaiDeleteWebhookConfig, BrowseaiOnTaskFinishedConfig, BrowseaiOnDataChangedConfig, BrowseaiOnTableExportFinishedConfig], Field(discriminator="operation")]

class BrowseaiNodeConfig(NodeConfig[BrowseaiConfig, BrowseaiAPIKeyCredential]):
    pass

class BrowseaiNode(ExternalWebhookTriggerMixin, WorkflowNode):
    integration_type = "automation-browseai"
    connection_evidence = ConnectionEvidence(operation="list_robots", noun="robots")
    webhook_signing_secret_not_issued = True

    @classmethod
    def get_config_model(cls):
        return BrowseaiNodeConfig

    @staticmethod
    async def _request(credential, method, path, *, params=None, body=None):
        key = BrowseaiAPIKeyCredential.model_validate(credential).api_key
        async with httpx.AsyncClient(timeout=45) as client:
            response = await client.request(method, BASE + path,
                headers={"Authorization": f"Bearer {key}", "Accept": "application/json"}, params=params, json=body)
        try:
            data = response.json()
        except ValueError:
            raise ValueError(f"Browse AI returned a non-JSON response (HTTP {response.status_code})") from None
        if response.is_error or not isinstance(data, dict) or data.get("messageCode") != "success":
            detail = data.get("messageCode", "Invalid API response") if isinstance(data, dict) else "Invalid API response"
            raise ValueError(f"Browse AI HTTP {response.status_code}: {detail}")
        return data

    async def execute(self, inputs):
        if self.config is None:
            raise ValueError("Browse AI configuration is required")
        op = self.config.config
        if op.operation in TRIGGERS:
            return self.no_event_output(op.operation)
        if self.config.credentials is None:
            raise ValueError("Connect a Browse AI API key")
        spec = OPERATIONS[op.operation]
        values = op.model_dump(exclude_none=True, exclude={"operation"})
        path = spec["path"]
        for key, value in values.items():
            path = path.replace("{" + key + "}", quote(str(value), safe=""))
        params = {key: values[key] for key in spec["query"] if key in values}
        params = {key: str(value).lower() if isinstance(value, bool) else value for key, value in params.items()}
        body = {key: values[key] for key in spec["body"] if key in values}
        for key in spec["json"]:
            if key + "_json" in values:
                try:
                    body[key] = json.loads(values[key + "_json"])
                except ValueError:
                    raise ValueError(f"{key} must contain valid JSON") from None
                expected = list if key == "inputParameters" and op.operation == "create_bulk_run" else dict
                if not isinstance(body[key], expected):
                    raise ValueError(f"{key} must be a JSON {expected.__name__}")
                parameters = body[key] if isinstance(body[key], list) else [body[key]]
                if not parameters or any(not isinstance(item, dict) for item in parameters):
                    raise ValueError("Provide a nonempty array of input parameter objects")
                for item in parameters:
                    for value in item.values():
                        if isinstance(value, str) or (type(value) in {int, float} and math.isfinite(value)):
                            continue
                        if isinstance(value, list) and all(isinstance(v, str) for v in value):
                            continue
                        raise ValueError("Input parameter values must be strings, numbers, or arrays of strings")
        data = await self._request(self.config.credentials.model_dump(), spec["method"], path,
            params=params or None, body=body if spec["method"] in {"POST", "PATCH"} else None)
        output = {"status": "success", "operation": op.operation, "data": data}
        await self.emit(output)
        return output

    @classmethod
    def registration_fingerprint_fields(cls, config):
        return {"robotId": config.get("robotId")}

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        operation, robot_id = config.get("operation"), config.get("robotId")
        if operation not in TRIGGERS or not robot_id:
            raise ValueError("Choose a Browse AI trigger and Robot ID")
        data = await cls._request(credential, "POST", "/robots/" + quote(robot_id, safe="") + "/webhooks",
            body={"hookUrl": webhook_url, "eventType": TRIGGERS[operation][0]})
        endpoint_id = data.get("webhook", {}).get("id")
        if not endpoint_id:
            raise ValueError("Browse AI did not return a webhook ID")
        return {"external_webhook_id": str(endpoint_id)}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        endpoint_id = config.get("external_webhook_id")
        if not endpoint_id:
            return
        if not credential or not config.get("robotId"):
            raise ValueError("Browse AI credentials and Robot ID are required for webhook cleanup")
        await cls._request(credential, "DELETE", "/robots/" + quote(config["robotId"], safe="") + "/webhooks/" + quote(str(endpoint_id), safe=""))

    @classmethod
    def verify_webhook_signature(cls, body, headers, config):
        # Browse AI explicitly documents unsigned deliveries. The private
        # callback URL is the capability; the provider supplies no HMAC.
        return True

    @classmethod
    def filter_trigger_payload(cls, payload, config):
        operation = config.get("operation")
        if operation not in TRIGGERS:
            return False
        if operation == "on_table_export_finished":
            return bool(payload.get("exportId")) and payload.get("robotId") == config.get("robotId")
        if payload.get("event") not in TRIGGERS[operation][1]:
            return False
        task = payload.get("task")
        return isinstance(task, dict) and bool(task.get("id")) and task.get("robotId") == config.get("robotId")

    @classmethod
    def resolve_trigger_payload(cls, payload, config):
        return {"status": "success", "operation": config.get("operation"), "data": payload}

    @classmethod
    def resolve_agent_event(cls, output):
        if not isinstance(output, dict):
            return None
        data = output.get("data", output)
        if not isinstance(data, dict):
            return None
        if output.get("operation") == "on_table_export_finished":
            rid, eid = data.get("robotId"), data.get("exportId")
            if not rid or not eid:
                return None
            return {"text": f"Browse AI table export {eid} finished for robot {rid}. Files: {json.dumps(data.get('filesTemporaryUrl'))}. Retrieve robot details with get_robot robotId={rid}.",
                "conversation_key": str(rid), "title": "Browse AI table export finished"}
        task = data.get("task")
        if not isinstance(task, dict) or not task.get("id"):
            return None
        tid, rid = task["id"], task.get("robotId")
        text = f"Browse AI {data.get('event')}: task {tid} for robot {rid}, status {task.get('status')}."
        text += f"\nCaptured data: {json.dumps(task.get('capturedTexts', {}), ensure_ascii=False)}"
        if "capturedLists" in task:
            text += f"\nLists: {json.dumps(task['capturedLists'], ensure_ascii=False)}"
        if "userFriendlyError" in task:
            text += f"\nError: {task['userFriendlyError']}"
        text += f"\nRobot: https://dashboard.browse.ai/robots/{quote(str(rid), safe='')}"
        text += f"\nTo act: get_task robotId={rid} taskId={tid}; run_task robotId={rid} to run again."
        return {"text": text, "conversation_key": str(rid), "title": f"Browse AI task {tid}"}
