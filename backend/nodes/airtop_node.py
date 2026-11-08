"""Airtop public browser automation API (pinned OpenAPI 1.0.0).

Each operation issues one request. Lists preserve provider pagination; browser
mutations and AI actions are never retried automatically.
"""
from typing import Annotated, Literal, Union
from urllib.parse import quote
import httpx
from pydantic import BaseModel, ConfigDict, Field
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence

class AirtopApiKey(BaseModel):
    model_config = ConfigDict(title="Airtop API Key", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://portal.airtop.ai/api-keys",
        "x-credential-instructions": "Create an API key in the Airtop portal and paste it here."})
    credential_type: Literal["airtop_api_key"] = Field("airtop_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, title="API Key", repr=False,
        description="Paste your Airtop API key without the Bearer prefix.", json_schema_extra={"ui:widget": "password"})

class _Operation(BaseModel):
    model_config = ConfigDict(extra="forbid")

class ListAutomations(_Operation):
    operation: Literal["list_automations"] = Field("list_automations", title="List Automations", json_schema_extra={"ui:hidden": True})

class DeleteAutomation(_Operation):
    operation: Literal["delete_automation"] = Field("delete_automation", title="Delete Automation", json_schema_extra={"ui:hidden": True})
    automation_id: str = Field(... , description='ID of the automation to delete', min_length=1)

class GetAutomation(_Operation):
    operation: Literal["get_automation"] = Field("get_automation", title="Get Automation", json_schema_extra={"ui:hidden": True})
    automation_id: str = Field(... , description='ID of the automation to retrieve', min_length=1)

class GetRequestStatus(_Operation):
    operation: Literal["get_request_status"] = Field("get_request_status", title="Get Request Status", json_schema_extra={"ui:hidden": True})
    request_id: str = Field(... , description='The ID of the request to check.', min_length=1)

class ListSessions(_Operation):
    operation: Literal["list_sessions"] = Field("list_sessions", title="List Sessions", json_schema_extra={"ui:hidden": True})
    status: Literal['awaitingCapacity', 'initializing', 'running', 'ended', 'completed', 'cancelled', 'all'] | None = Field(None , description='Status of the session to get.')
    offset: int | None = Field(None , description='Offset for pagination.')
    limit: int | None = Field(None , description='Limit for pagination.')

class SessionConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profileName: str | None = Field(None, title="Profile Name")
    timeoutMinutes: int | None = Field(None, ge=1, le=10080, title="Idle Timeout (Minutes)")
    record: bool | None = Field(None, title="Record Session")
    solveCaptcha: bool | None = Field(None, title="Solve Captcha")

class CreateSession(_Operation):
    configuration: SessionConfiguration | None = Field(None, title="Session Configuration")
    operation: Literal["create_session"] = Field("create_session", title="Create Session", json_schema_extra={"ui:hidden": True})

class TerminateSession(_Operation):
    operation: Literal["terminate_session"] = Field("terminate_session", title="Terminate Session", json_schema_extra={"ui:hidden": True})
    session_id: str = Field(... , description='ID of the session to delete.', min_length=1)

class GetSession(_Operation):
    operation: Literal["get_session"] = Field("get_session", title="Get Session", json_schema_extra={"ui:hidden": True})
    session_id: str = Field(... , description='Id of the session to get', min_length=1)

class ListWindows(_Operation):
    operation: Literal["list_windows"] = Field("list_windows", title="List Windows", json_schema_extra={"ui:hidden": True})
    session_id: str = Field(... , description='ID of the session to list windows for.', min_length=1)

class CreateWindow(_Operation):
    operation: Literal["create_window"] = Field("create_window", title="Create Window", json_schema_extra={"ui:hidden": True})
    session_id: str = Field(... , description='ID of the session that owns the window.', min_length=1)
    url: str | None = Field(None , description='Initial url to navigate to')
    wait_until: Literal['load', 'domContentLoaded', 'complete', 'noWait'] | None = Field(None , description="Wait until the specified loading event occurs. Defaults to 'load', which waits until the page dom and it's assets have loaded. 'domContentLoaded' will wait until the dom has loaded, 'complete' will wait until the page and all it's iframes have loaded it's dom and assets. 'noWait' will not wait for any loading event and will return immediately.")
    wait_until_timeout_seconds: int | None = Field(None , description='Maximum time in seconds to wait for the specified loading event to occur. If the timeout is reached, the operation will still succeed but return a warning indicating the page may still be loading resources.')
    screen_resolution: str | None = Field(None , description='Affects the live view configuration. By default, a live view will fill the parent frame (or local window if loaded directly) when initially loaded, causing the browser window to be resized to match. This parameter can be used to instead configure the returned liveViewUrl so that the live view is loaded with fixed dimensions (e.g. 1280x720), resizing the browser window to match, and then disallows any further resizing from the live view.')

class CloseWindow(_Operation):
    operation: Literal["close_window"] = Field("close_window", title="Close Window", json_schema_extra={"ui:hidden": True})
    session_id: str = Field(... , description='ID of the session that owns the window.', min_length=1)
    window_id: str = Field(... , description='Airtop window ID of the browser window.', min_length=1)

class GetWindow(_Operation):
    operation: Literal["get_window"] = Field("get_window", title="Get Window", json_schema_extra={"ui:hidden": True})
    session_id: str = Field(... , description='ID of the session that owns the window.', min_length=1)
    window_id: str = Field(... , description='ID of the browser window, which can either be a normal AirTop windowId or a [CDP TargetId](https://chromedevtools.github.io/devtools-protocol/tot/Target/#type-TargetID) from a browser automation library like Puppeteer (typically associated with the page or main frame). Our SDKs will handle retrieving a TargetId for you from various popular browser automation libraries, but we also have details in our guides on how to do it manually.', min_length=1)
    include_navigation_bar: bool | None = Field(None , description='Affects the live view configuration. A navigation bar is not shown in the live view of a browser by default. Set this to true to configure the returned liveViewUrl so that a navigation bar is rendered, allowing users to easily navigate the browser to other pages from the live view.')
    disable_resize: bool | None = Field(None , description='Affects the live view configuration. Set to true to configure the returned liveViewUrl so that the ability to resize the browser window from the live view is disabled (resizing is allowed by default). Note that, at initial load, the live view will automatically fill the parent frame (or local window if loaded directly) and cause the browser window to be resized to match. This parameter does not affect that initial load behavior. See screenResolution for a way to set a fixed size for the live view.')
    screen_resolution: str | None = Field(None , description='Affects the live view configuration. By default, a live view will fill the parent frame (or local window if loaded directly) when initially loaded, causing the browser window to be resized to match. This parameter can be used to instead configure the returned liveViewUrl so that the live view is loaded with fixed dimensions (e.g. 1280x720), resizing the browser window to match, and then disallows any further resizing from the live view.')

class LoadUrl(_Operation):
    operation: Literal["load_url"] = Field("load_url", title="Load Url", json_schema_extra={"ui:hidden": True})
    session_id: str = Field(... , description='ID of the session that owns the window.', min_length=1)
    window_id: str = Field(... , description='Airtop window ID of the browser window.', min_length=1)
    url: str = Field(... , description='Url to navigate to', min_length=1)
    wait_until: Literal['load', 'domContentLoaded', 'complete', 'noWait'] | None = Field(None , description="Wait until the specified loading event occurs. Defaults to 'load', which waits until the page dom and it's assets have loaded. 'domContentLoaded' will wait until the dom has loaded, 'complete' will wait until the page and all it's iframes have loaded it's dom and assets. 'noWait' will not wait for any loading event and will return immediately.")
    wait_until_timeout_seconds: int | None = Field(None , description='Maximum time in seconds to wait for the specified loading event to occur. If the timeout is reached, the operation will still succeed but return a warning indicating the page may still be loading resources.')

class Click(_Operation):
    operation: Literal["click"] = Field("click", title="Click", json_schema_extra={"ui:hidden": True})
    session_id: str = Field(... , description='The session id for the window.', min_length=1)
    window_id: str = Field(... , description='The Airtop window id of the browser window.', min_length=1)
    element_description: str = Field(... , description='A natural language description of the element to click.', min_length=1)
    wait_for_navigation: bool | None = Field(None , description='If true, Airtop AI will wait for the navigation to complete after clicking the element.')

class Hover(_Operation):
    operation: Literal["hover"] = Field("hover", title="Hover", json_schema_extra={"ui:hidden": True})
    session_id: str = Field(... , description='The session id for the window.', min_length=1)
    window_id: str = Field(... , description='The Airtop window id of the browser window.', min_length=1)
    element_description: str = Field(... , description="A natural language description of where to hover (e.g. 'the search box', 'username field'). The interaction will be aborted if the target element cannot be found.", min_length=1)

class QueryPage(_Operation):
    operation: Literal["query_page"] = Field("query_page", title="Query Page", json_schema_extra={"ui:hidden": True})
    session_id: str = Field(... , description='The session id for the window.', min_length=1)
    window_id: str = Field(... , description='The Airtop window id of the browser window.', min_length=1)
    prompt: str = Field(... , description='The prompt to submit about the content in the browser window.', min_length=1)
    follow_pagination_links: bool | None = Field(None , description='Make a best effort attempt to load more content items than are originally displayed on the page, e.g. by following pagination links, clicking controls to load more content, utilizing infinite scrolling, etc. This can be quite a bit more costly, but may be necessary for sites that require additional interaction to show the needed results. You can provide constraints in your prompt (e.g. on the total number of pages or results to consider).')

class ExtractPaginated(_Operation):
    operation: Literal["extract_paginated"] = Field("extract_paginated", title="Extract Paginated", json_schema_extra={"ui:hidden": True})
    session_id: str = Field(... , description='The session id for the window.', min_length=1)
    window_id: str = Field(... , description='The Airtop window id of the browser window.', min_length=1)
    prompt: str = Field(... , description='A prompt providing the Airtop AI model with additional direction or constraints about the page and the details you want to extract from the page.', min_length=1)

class ScrapePage(_Operation):
    operation: Literal["scrape_page"] = Field("scrape_page", title="Scrape Page", json_schema_extra={"ui:hidden": True})
    session_id: str = Field(... , description='The session id for the window.', min_length=1)
    window_id: str = Field(... , description='The Airtop window id of the browser window to scrape.', min_length=1)

class Scroll(_Operation):
    operation: Literal["scroll"] = Field("scroll", title="Scroll", json_schema_extra={"ui:hidden": True})
    session_id: str = Field(... , description='The session id for the window.', min_length=1)
    window_id: str = Field(... , description='The Airtop window id of the browser window.', min_length=1)
    scroll_to_element: str = Field(... , description="A natural language description of where to scroll (e.g. 'the search box', 'username field'). The interaction will be aborted if the target element cannot be found. If provided, scrollToEdge/scrollBy values will be ignored.")
    scroll_within: str | None = Field(None , description='A natural language description of the scrollable area on the web page. This identifies the container or region that should be scrolled. If missing, the entire page will be scrolled. You can also describe a visible reference point inside the container. Note: This is different from scrollToElement, which specifies the target element to scroll to. The target may be located inside the scrollable area defined by scrollWithin.')

class TypeText(_Operation):
    operation: Literal["type_text"] = Field("type_text", title="Type Text", json_schema_extra={"ui:hidden": True})
    session_id: str = Field(... , description='The session id for the window.', min_length=1)
    window_id: str = Field(... , description='The Airtop window id of the browser window.', min_length=1)
    text: str = Field(... , description='The text to type into the browser window.', min_length=1)
    element_description: str | None = Field(None , description="A natural language description of where to type (e.g. 'the search box', 'username field'). The interaction will be aborted if the target element cannot be found.")
    clear_input_field: bool | None = Field(None , description='If true, and an HTML input field is active, clears the input field before typing the text.')
    press_enter_key: bool | None = Field(None , description='If true, simulates pressing the Enter key after typing the text.')
    press_tab_key: bool | None = Field(None , description='If true, simulates pressing the Tab key after typing the text. Note that the tab key will be pressed after the Enter key if both options are configured.')

Operation = Annotated[Union[ListAutomations, DeleteAutomation, GetAutomation, GetRequestStatus, ListSessions, CreateSession, TerminateSession, GetSession, ListWindows, CreateWindow, CloseWindow, GetWindow, LoadUrl, Click, Hover, QueryPage, ExtractPaginated, ScrapePage, Scroll, TypeText], Field(discriminator="operation")]

class AirtopNodeConfig(NodeConfig[Operation, AirtopApiKey]):
    pass

ROUTES = {'list_automations': ('GET', '/v1/automations', {}), 'delete_automation': ('DELETE', '/v1/automations/{automationId}', {'automation_id': ('path', 'automationId')}), 'get_automation': ('GET', '/v1/automations/{automationId}', {'automation_id': ('path', 'automationId')}), 'get_request_status': ('GET', '/v1/requests/{requestId}/status', {'request_id': ('path', 'requestId')}), 'list_sessions': ('GET', '/v1/sessions', {'status': ('query', 'status'), 'offset': ('query', 'offset'), 'limit': ('query', 'limit')}), 'create_session': ('POST', '/v1/sessions', {'configuration': ('body', 'configuration')}), 'terminate_session': ('DELETE', '/v1/sessions/{id}', {'session_id': ('path', 'id')}), 'get_session': ('GET', '/v1/sessions/{id}', {'session_id': ('path', 'id')}), 'list_windows': ('GET', '/v1/sessions/{sessionId}/windows', {'session_id': ('path', 'sessionId')}), 'create_window': ('POST', '/v1/sessions/{sessionId}/windows', {'session_id': ('path', 'sessionId'), 'url': ('body', 'url'), 'wait_until': ('body', 'waitUntil'), 'wait_until_timeout_seconds': ('body', 'waitUntilTimeoutSeconds'), 'screen_resolution': ('body', 'screenResolution')}), 'close_window': ('DELETE', '/v1/sessions/{sessionId}/windows/{windowId}', {'session_id': ('path', 'sessionId'), 'window_id': ('path', 'windowId')}), 'get_window': ('GET', '/v1/sessions/{sessionId}/windows/{windowId}', {'session_id': ('path', 'sessionId'), 'window_id': ('path', 'windowId'), 'include_navigation_bar': ('query', 'includeNavigationBar'), 'disable_resize': ('query', 'disableResize'), 'screen_resolution': ('query', 'screenResolution')}), 'load_url': ('POST', '/v1/sessions/{sessionId}/windows/{windowId}', {'session_id': ('path', 'sessionId'), 'window_id': ('path', 'windowId'), 'url': ('body', 'url'), 'wait_until': ('body', 'waitUntil'), 'wait_until_timeout_seconds': ('body', 'waitUntilTimeoutSeconds')}), 'click': ('POST', '/v1/sessions/{sessionId}/windows/{windowId}/click', {'session_id': ('path', 'sessionId'), 'window_id': ('path', 'windowId'), 'element_description': ('body', 'elementDescription'), 'wait_for_navigation': ('body', 'waitForNavigation')}), 'hover': ('POST', '/v1/sessions/{sessionId}/windows/{windowId}/hover', {'session_id': ('path', 'sessionId'), 'window_id': ('path', 'windowId'), 'element_description': ('body', 'elementDescription')}), 'query_page': ('POST', '/v1/sessions/{sessionId}/windows/{windowId}/page-query', {'session_id': ('path', 'sessionId'), 'window_id': ('path', 'windowId'), 'prompt': ('body', 'prompt'), 'follow_pagination_links': ('body', 'followPaginationLinks')}), 'extract_paginated': ('POST', '/v1/sessions/{sessionId}/windows/{windowId}/paginated-extraction', {'session_id': ('path', 'sessionId'), 'window_id': ('path', 'windowId'), 'prompt': ('body', 'prompt')}), 'scrape_page': ('POST', '/v1/sessions/{sessionId}/windows/{windowId}/scrape-content', {'session_id': ('path', 'sessionId'), 'window_id': ('path', 'windowId')}), 'scroll': ('POST', '/v1/sessions/{sessionId}/windows/{windowId}/scroll', {'session_id': ('path', 'sessionId'), 'window_id': ('path', 'windowId'), 'scroll_to_element': ('body', 'scrollToElement'), 'scroll_within': ('body', 'scrollWithin')}), 'type_text': ('POST', '/v1/sessions/{sessionId}/windows/{windowId}/type', {'session_id': ('path', 'sessionId'), 'window_id': ('path', 'windowId'), 'text': ('body', 'text'), 'element_description': ('body', 'elementDescription'), 'clear_input_field': ('body', 'clearInputField'), 'press_enter_key': ('body', 'pressEnterKey'), 'press_tab_key': ('body', 'pressTabKey')})}

class AirtopNode(WorkflowNode):
    integration_type = "automation-airtop"
    connection_evidence = ConnectionEvidence(operation="list_sessions", noun="sessions")

    @classmethod
    def get_config_model(cls):
        return AirtopNodeConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect an Airtop API key")
        op = self.config.config
        key = self.config.credentials.api_key
        method, path, mapping = ROUTES[op.operation]
        query, body = {}, {}
        for field, value in op.model_dump(exclude_none=True).items():
            if field == "operation":
                continue
            destination, wire_name = mapping[field]
            if destination == "path":
                path = path.replace("{" + wire_name + "}", quote(str(value), safe=""))
            elif destination == "query":
                query[wire_name] = value
            else:
                body[wire_name] = value
        async with httpx.AsyncClient(timeout=180, follow_redirects=False) as client:
            response = await client.request(method, "https://api.airtop.ai/api" + path,
                headers={"Authorization": "Bearer " + key, "Accept": "application/json"},
                params=query, **({"json": body} if method == "POST" else {}))
        if response.is_error or response.is_redirect:
            raise ValueError(("Airtop HTTP " + str(response.status_code) + ": " + response.text).replace(key, "[redacted]"))
        result = response.json() if response.content else {"success": True}
        if isinstance(result, dict) and result.get("errors"):
            raise ValueError(("Airtop: " + str(result["errors"])).replace(key, "[redacted]"))
        await self.emit(result)
        return result
