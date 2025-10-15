"""
Mock implementations for boto3 components used in testing.

This module provides test-friendly mocks for AWS S3 operations
to avoid actual AWS API calls during testing.
"""

import sys
import logging
from typing import Any, Dict
from unittest.mock import MagicMock

logger = logging.getLogger(__name__)

# Set R2/S3 environment variables before any imports
import os
r2_env_vars = {
    "R2_ACCESS_KEY_ID": "test-r2-key",
    "R2_SECRET_ACCESS_KEY": "test-r2-secret", 
    "R2_BUCKET_NAME": "test-bucket"
}
for key, value in r2_env_vars.items():
    if key not in os.environ:
        os.environ[key] = value

# Create mock boto3 module to prevent AWS authentication
mock_boto3 = MagicMock()
mock_s3_client = MagicMock()
mock_boto3.client.return_value = mock_s3_client
sys.modules['boto3'] = mock_boto3

# Export mock_s3_client for use in tests
__all__ = ['mock_s3_client', 'configure_mock_s3_responses', 'patch_boto3_components']

# Global state for configurable S3 responses
_mock_s3_responses: Dict[str, Any] = {}


def configure_mock_s3_responses(responses: Dict[str, Any] = None):
    """
    Configure S3 operation responses for testing.
    
    Args:
        responses: Dict mapping S3 operations to response data
                  e.g., {
                      "list_objects_v2": {"Contents": [{"Key": "subdomain/file"}]},
                      "put_object": {"ETag": '"test-etag"'},
                      "delete_object": {}
                  }
    """
    global _mock_s3_responses
    _mock_s3_responses = responses or {}
    
    # Reset all side effects first - must clear both mock state and side_effect
    mock_s3_client.reset_mock()
    
    # Clear all side_effects explicitly (reset_mock doesn't do this)
    for attr_name in dir(mock_s3_client):
        if not attr_name.startswith('_'):
            attr = getattr(mock_s3_client, attr_name)
            if hasattr(attr, 'side_effect'):
                attr.side_effect = None
            if hasattr(attr, 'return_value'):
                attr.return_value = None
    
    # Apply responses to mock S3 client
    for operation, response in _mock_s3_responses.items():
        if hasattr(mock_s3_client, operation):
            if isinstance(response, Exception):
                getattr(mock_s3_client, operation).side_effect = response
            else:
                getattr(mock_s3_client, operation).return_value = response
    
    # Set default responses for operations not specified
    if "list_objects_v2" not in _mock_s3_responses:
        mock_s3_client.list_objects_v2.return_value = {'Contents': []}
    if "put_object" not in _mock_s3_responses:
        mock_s3_client.put_object.return_value = {'ETag': '"mock-etag"'}
    if "delete_object" not in _mock_s3_responses:
        mock_s3_client.delete_object.return_value = {}
    if "head_object" not in _mock_s3_responses:
        mock_s3_client.head_object.return_value = {'ContentType': 'text/html', 'ContentLength': 1024}
    if "copy_object" not in _mock_s3_responses:
        mock_s3_client.copy_object.return_value = {'ETag': '"mock-copy-etag"'}
    
    logger.debug(f"Mock S3 responses configured: {list(_mock_s3_responses.keys())}")


def patch_boto3_components():
    """
    Patch boto3 components with test-friendly mocks.
    
    Call this function in test setup to replace boto3 with mocks
    that don't require actual AWS credentials or API calls.
    """
    import boto3
    
    # Apply patches
    boto3.client = mock_boto3.client
    
    # Configure default S3 responses
    mock_s3_client.put_object.return_value = {'ETag': '"mock-etag"'}
    mock_s3_client.delete_object.return_value = {}
    mock_s3_client.head_object.return_value = {'ContentLength': 1024}
    mock_s3_client.list_objects_v2.return_value = {'Contents': []}  # Default: no objects
    
    logger.debug("boto3 components patched for testing")