"""
Tests for dynamic field options loading (load_field_options).

Covers three contracts:
- Excel/OneDrive: dropdown population works and method signatures don't collide.
- Missing-credential contract (all credential-backed nodes): when no credential
  is connected, the loader must RAISE (not return an empty list) so the
  load-options handler emits ``success=False`` and the frontend's
  DynamicOptionsField shows the "Open Credentials" button instead of a
  misleading "No options available".
- Fail-loud-on-error vs genuine-empty (representative node): an API error must
  RAISE, but a successful response with zero items must still return empty so
  the UI correctly shows "No options available" for an empty workspace.
"""

import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from nodes.excel_node import ExcelNode
from nodes.onedrive_node import OneDriveNode


def _httpx_response(status_code, json_data):
    """Build a stand-in for an httpx.Response (sync .json()/.text/.status_code)."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.text = str(json_data)
    return resp


def _patch_httpx_get(response):
    """Patch httpx.AsyncClient so `async with` + `await client.get(...)` yields response."""
    patcher = patch("httpx.AsyncClient")
    mock_client = patcher.start()
    instance = AsyncMock()
    mock_client.return_value.__aenter__.return_value = instance
    instance.get.return_value = response
    return patcher


class TestExcelDynamicOptions:
    """Test Excel node's load_field_options functionality"""

    CRED = {
        'access_token': 'test_token',
        'refresh_token': 'test_refresh',
        'expires_at': '2099-12-31T23:59:59Z',
        'email': 'test@example.com',
    }

    @pytest.mark.asyncio
    async def test_load_workbook_options(self):
        """Dispatch + signature: a successful (empty) response yields a dict."""
        patcher = _patch_httpx_get(_httpx_response(200, {"value": []}))
        try:
            result = await ExcelNode.load_field_options(
                field_name="workbook_id",
                credential_data=self.CRED,
                context=None,
                page_token=None,
            )
        finally:
            patcher.stop()
        assert isinstance(result, dict)
        assert 'options' in result

    @pytest.mark.asyncio
    async def test_load_worksheet_options(self):
        """Dispatch + signature for the context-dependent worksheet field."""
        patcher = _patch_httpx_get(_httpx_response(200, {"value": []}))
        try:
            result = await ExcelNode.load_field_options(
                field_name="worksheet_name",
                credential_data=self.CRED,
                context={'workbook_id': 'test_workbook_123'},
                page_token=None,
            )
        finally:
            patcher.stop()
        assert isinstance(result, dict)
        assert 'options' in result

    @pytest.mark.asyncio
    async def test_load_workbook_options_no_credential_raises(self):
        """No credential -> raise so the Open Credentials button shows."""
        with pytest.raises(Exception) as excinfo:
            await ExcelNode.load_field_options(
                field_name="workbook_id", credential_data={}
            )
        assert "connect" in str(excinfo.value).lower()


class TestOneDriveDynamicOptions:
    """Test OneDrive node's load_field_options functionality"""

    CRED = {
        'access_token': 'test_token',
        'refresh_token': 'test_refresh',
        'expires_at': '2099-12-31T23:59:59Z',
        'email': 'test@example.com',
    }

    @pytest.mark.asyncio
    async def test_load_item_options(self):
        """Dispatch + signature: a successful (empty) response yields a dict."""
        patcher = _patch_httpx_get(_httpx_response(200, {"value": []}))
        try:
            result = await OneDriveNode.load_field_options(
                field_name="item_id",
                credential_data=self.CRED,
                context=None,
                page_token=None,
            )
        finally:
            patcher.stop()
        assert isinstance(result, dict)
        assert 'options' in result

    @pytest.mark.asyncio
    async def test_load_folder_options(self):
        """Dispatch + signature for the folder field."""
        patcher = _patch_httpx_get(_httpx_response(200, {"value": []}))
        try:
            result = await OneDriveNode.load_field_options(
                field_name="folder_id",
                credential_data=self.CRED,
                context=None,
                page_token=None,
            )
        finally:
            patcher.stop()
        assert isinstance(result, dict)
        assert 'options' in result


# (NodeClass, field_name) for every credential-backed dynamic-options picker.
# Contract: with no credential connected, load_field_options must RAISE a
# "Connect a <provider> account ..." error — never return empty options. The
# load-options handler turns the raise into success=False, the only signal
# DynamicOptionsField uses to render the "Open Credentials" button; a silent
# empty return renders "No options available" and hides the affordance. This
# whole class regressed when the handler-level credential guard was dropped and
# only Slack was migrated to the per-loader raise contract — Slack/Discord
# already have their own node tests for the raise, so they're not duplicated
# here.
CREDENTIAL_BACKED_PICKERS = [
    ("nodes.elevenlabs_node", "ElevenLabsNode", "voice_id"),
    ("nodes.excel_node", "ExcelNode", "workbook_id"),
    ("nodes.github_rest_node", "GithubRestNode", "repository"),
    ("nodes.gmail_node", "GmailNode", "label_ids"),
    ("nodes.google_ads_node", "GoogleAdsNode", "customer_id"),
    ("nodes.google_analytics_node", "GoogleAnalyticsNode", "property_id"),
    ("nodes.google_business_profile_node", "GoogleBusinessProfileNode", "account_id"),
    ("nodes.google_calendar_node", "GoogleCalendarNode", "calendar_id"),
    ("nodes.google_docs_node", "GoogleDocsNode", "document_id"),
    ("nodes.google_drive_node", "GoogleDriveNode", "folder_id"),
    ("nodes.google_forms_node", "GoogleFormsNode", "form_id"),
    ("nodes.google_search_console_node", "GoogleSearchConsoleNode", "site_url"),
    ("nodes.google_sheets_node", "GoogleSheetsNode", "spreadsheet_id"),
    ("nodes.google_slides_node", "GoogleSlidesNode", "presentation_id"),
    ("nodes.google_tasks_node", "GoogleTasksNode", "task_list_id"),
    ("nodes.linear_node", "LinearNode", "team_id"),
    ("nodes.notion_node", "NotionNode", "database_id"),
    ("nodes.onedrive_node", "OneDriveNode", "item_id"),
    ("nodes.twilio_node", "TwilioNode", "phone_number_sid"),
    ("nodes.twitter_node", "TwitterNode", "list_id"),
    ("nodes.typeform_node", "TypeformNode", "form_id"),
    ("nodes.word_node", "WordNode", "document_id"),
]


@pytest.mark.parametrize(
    "module_path,class_name,field_name",
    CREDENTIAL_BACKED_PICKERS,
    ids=[f"{c}.{f}" for _, c, f in CREDENTIAL_BACKED_PICKERS],
)
@pytest.mark.asyncio
async def test_missing_credential_raises_connect_message(
    module_path, class_name, field_name
):
    """No credential connected -> loader raises a "Connect ..." error.

    Pins the per-loader fail-loud contract so a future node can't silently
    regress back to returning empty options (which hides the Open Credentials
    button). The credential guard is the loader's first statement, so this
    raises before any network call — no mocking needed.
    """
    import importlib

    node_class = getattr(importlib.import_module(module_path), class_name)

    with pytest.raises(Exception) as excinfo:
        await node_class.load_field_options(
            field_name=field_name, credential_data={}
        )
    assert "connect" in str(excinfo.value).lower(), (
        f"{class_name}.load_field_options({field_name!r}) with no credential "
        f"must raise a 'Connect ...' error so the UI shows the Open Credentials "
        f"button; got: {excinfo.value!r}"
    )


class TestFailLoudVsGenuineEmpty:
    """A credential IS present, but the load can't (or does) succeed.

    Uses GoogleSheetsNode._list_spreadsheets as the representative loader; the
    same fail-loud-on-error / preserve-genuine-empty contract holds across all
    dynamic-options loaders.
    """

    CRED = {"access_token": "valid-token"}

    @pytest.mark.asyncio
    async def test_api_error_raises(self):
        """Non-2xx from the API must RAISE, not silently return empty."""
        from nodes.google_sheets_node import GoogleSheetsNode

        patcher = _patch_httpx_get(
            _httpx_response(403, {"error": {"message": "insufficient permission"}})
        )
        try:
            with pytest.raises(Exception) as excinfo:
                await GoogleSheetsNode.load_field_options(
                    field_name="spreadsheet_id", credential_data=self.CRED
                )
        finally:
            patcher.stop()
        msg = str(excinfo.value).lower()
        assert "api error" in msg or "insufficient permission" in msg, (
            f"API error must surface a real error, got: {excinfo.value!r}"
        )

    @pytest.mark.asyncio
    async def test_genuine_empty_result_returns_empty(self):
        """A successful response with zero items must return empty (NOT raise)
        so the UI shows 'No options available' for an empty workspace."""
        from nodes.google_sheets_node import GoogleSheetsNode

        patcher = _patch_httpx_get(_httpx_response(200, {"files": []}))
        try:
            result = await GoogleSheetsNode.load_field_options(
                field_name="spreadsheet_id", credential_data=self.CRED
            )
        finally:
            patcher.stop()
        assert result.get("options") == []
