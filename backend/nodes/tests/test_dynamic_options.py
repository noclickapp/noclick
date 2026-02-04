"""
Tests for dynamic field options loading (load_field_options) in Excel and OneDrive nodes.
This ensures dropdown population works correctly and catches method name collisions.
"""

import pytest
from nodes.excel_node import ExcelNode
from nodes.onedrive_node import OneDriveNode


class TestExcelDynamicOptions:
    """Test Excel node's load_field_options functionality"""

    @pytest.mark.asyncio
    async def test_load_workbook_options(self):
        """Test loading workbook dropdown options"""
        credential_data = {
            'access_token': 'test_token',
            'refresh_token': 'test_refresh',
            'expires_at': '2099-12-31T23:59:59Z',
            'email': 'test@example.com'
        }
        
        # This should not raise an error about missing positional arguments
        try:
            result = await ExcelNode.load_field_options(
                field_name="workbook_id",
                credential_data=credential_data,
                context=None,
                page_token=None
            )
            # We expect it to fail with HTTP errors, not argument errors
            assert isinstance(result, dict)
            assert 'options' in result or 'next_page_token' in result
        except TypeError as e:
            pytest.fail(f"Method signature mismatch: {e}")

    @pytest.mark.asyncio
    async def test_load_worksheet_options(self):
        """Test loading worksheet dropdown options"""
        credential_data = {
            'access_token': 'test_token',
            'refresh_token': 'test_refresh',
            'expires_at': '2099-12-31T23:59:59Z',
            'email': 'test@example.com'
        }
        
        context = {'workbook_id': 'test_workbook_123'}
        
        # This should not raise an error about missing positional arguments
        try:
            result = await ExcelNode.load_field_options(
                field_name="worksheet_name",
                credential_data=credential_data,
                context=context,
                page_token=None
            )
            assert isinstance(result, dict)
            assert 'options' in result
        except TypeError as e:
            pytest.fail(f"Method signature mismatch: {e}")


class TestOneDriveDynamicOptions:
    """Test OneDrive node's load_field_options functionality"""

    @pytest.mark.asyncio
    async def test_load_item_options(self):
        """Test loading file/folder dropdown options"""
        credential_data = {
            'access_token': 'test_token',
            'refresh_token': 'test_refresh',
            'expires_at': '2099-12-31T23:59:59Z',
            'email': 'test@example.com'
        }
        
        # This should not raise an error about missing positional arguments
        try:
            result = await OneDriveNode.load_field_options(
                field_name="item_id",
                credential_data=credential_data,
                context=None,
                page_token=None
            )
            assert isinstance(result, dict)
            assert 'options' in result
        except TypeError as e:
            pytest.fail(f"Method signature mismatch: {e}")

    @pytest.mark.asyncio
    async def test_load_folder_options(self):
        """Test loading folder dropdown options"""
        credential_data = {
            'access_token': 'test_token',
            'refresh_token': 'test_refresh',
            'expires_at': '2099-12-31T23:59:59Z',
            'email': 'test@example.com'
        }
        
        try:
            result = await OneDriveNode.load_field_options(
                field_name="folder_id",
                credential_data=credential_data,
                context=None,
                page_token=None
            )
            assert isinstance(result, dict)
            assert 'options' in result
        except TypeError as e:
            pytest.fail(f"Method signature mismatch: {e}")
