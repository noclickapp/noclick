"""
{SERVICE_NAME} REST API automation node.

Provides workflow integration with {SERVICE_NAME} for operations including:
{OPERATION_CATEGORIES}

Authentication: {AUTH_TYPE}
API Base URL: {API_BASE_URL}
Documentation: {DOCS_URL}
"""

import logging
import time
from typing import Dict, Any, Optional, List, Literal, Union, Annotated
from pydantic import BaseModel, Field, Discriminator
import httpx

from nodes.core.base import WorkflowNode, NodeConfig

logger = logging.getLogger(__name__)

# ============================================================================
# Constants
# ============================================================================

{SERVICE_UPPER}_API_BASE = "{API_BASE_URL}"
{SERVICE_UPPER}_API_VERSION = "{API_VERSION}"

# ============================================================================
# Credential Schemas
# ============================================================================

# TEMPLATE A: API Key Credential
class {ServiceName}ApiKeyCredential(BaseModel):
    """
    API Key credential for {SERVICE_NAME}.

    Get your API key at: {CREDENTIAL_URL}
    """
    api_key: str = Field(
        ...,
        title="API Key",
        description="Your {SERVICE_NAME} API key",
        json_schema_extra={"ui:widget": "password"}
    )

    class Config:
        json_schema_extra = {
            "x-credential-url": "{CREDENTIAL_URL}"
        }


# TEMPLATE B: OAuth Credential (use if service uses OAuth)
class {ServiceName}OAuthCredential(BaseModel):
    """
    OAuth credential for {SERVICE_NAME}.
    """
    access_token: str = Field(..., title="Access Token")
    refresh_token: str = Field(..., title="Refresh Token")
    expires_at: str = Field(..., title="Token Expiry")
    email: Optional[str] = Field(None, title="Account Email")

    class Config:
        json_schema_extra = {
            "x-credential-type": "oauth",
            "x-oauth-provider": "{service_name}",
            "x-credential-url": "{OAUTH_SETUP_URL}"
        }


# TEMPLATE C: Bearer Token Credential
class {ServiceName}BearerCredential(BaseModel):
    """
    Bearer token credential for {SERVICE_NAME}.
    """
    token: str = Field(
        ...,
        title="Access Token",
        description="Bearer token for authentication",
        json_schema_extra={"ui:widget": "password"}
    )


# Choose the appropriate credential type
{ServiceName}Credential = {ServiceName}ApiKeyCredential  # or OAuth/Bearer


# ============================================================================
# Operation Config Models
# ============================================================================

# -----------------------------------------------------------------------------
# {Category1} Operations
# -----------------------------------------------------------------------------

class {ServiceName}List{Resource}Config(BaseModel):
    """List all {resources}"""
    operation: Literal["list_{resources}"] = Field(
        "list_{resources}",
        json_schema_extra={"const": "list_{resources}", "ui:hidden": True}
    )
    # Optional pagination
    page: Optional[int] = Field(1, title="Page", description="Page number")
    per_page: Optional[int] = Field(
        20,
        title="Per Page",
        description="Results per page (max 100)"
    )
    # Optional filters (customize per API)
    status: Optional[str] = Field(
        None,
        title="Status",
        description="Filter by status",
        json_schema_extra={"enum": ["active", "inactive", "all"]}
    )


class {ServiceName}Get{Resource}Config(BaseModel):
    """Get a specific {resource}"""
    operation: Literal["get_{resource}"] = Field(
        "get_{resource}",
        json_schema_extra={"const": "get_{resource}", "ui:hidden": True}
    )
    {resource}_id: str = Field(
        ...,
        title="{Resource} ID",
        description="The unique identifier of the {resource}"
    )


class {ServiceName}Create{Resource}Config(BaseModel):
    """Create a new {resource}"""
    operation: Literal["create_{resource}"] = Field(
        "create_{resource}",
        json_schema_extra={"const": "create_{resource}", "ui:hidden": True}
    )
    name: str = Field(..., title="Name", description="{Resource} name")
    description: Optional[str] = Field(
        None,
        title="Description",
        description="{Resource} description",
        json_schema_extra={"ui:widget": "textarea"}
    )
    # Add other required/optional fields


class {ServiceName}Update{Resource}Config(BaseModel):
    """Update an existing {resource}"""
    operation: Literal["update_{resource}"] = Field(
        "update_{resource}",
        json_schema_extra={"const": "update_{resource}", "ui:hidden": True}
    )
    {resource}_id: str = Field(..., title="{Resource} ID")
    name: Optional[str] = Field(None, title="Name")
    description: Optional[str] = Field(
        None,
        title="Description",
        json_schema_extra={"ui:widget": "textarea"}
    )


class {ServiceName}Delete{Resource}Config(BaseModel):
    """Delete a {resource}"""
    operation: Literal["delete_{resource}"] = Field(
        "delete_{resource}",
        json_schema_extra={"const": "delete_{resource}", "ui:hidden": True}
    )
    {resource}_id: str = Field(..., title="{Resource} ID")


# -----------------------------------------------------------------------------
# {Category2} Operations (repeat pattern for other categories)
# -----------------------------------------------------------------------------

# ... more config classes


# ============================================================================
# Discriminated Union
# ============================================================================

{ServiceName}Config = Annotated[
    Union[
        # {Category1}
        {ServiceName}List{Resource}Config,
        {ServiceName}Get{Resource}Config,
        {ServiceName}Create{Resource}Config,
        {ServiceName}Update{Resource}Config,
        {ServiceName}Delete{Resource}Config,
        # {Category2}
        # ... more configs
    ],
    Discriminator("operation")
]


# ============================================================================
# Full Node Configuration
# ============================================================================

class {ServiceName}NodeConfig(NodeConfig[{ServiceName}Config, {ServiceName}Credential]):
    """Full configuration for {SERVICE_NAME} node including credentials"""
    pass


# ============================================================================
# Node Implementation
# ============================================================================

class {ServiceName}Node(WorkflowNode):
    """
    {SERVICE_NAME} automation node.

    Executes {SERVICE_NAME} API operations for workflow automation.
    """

    @classmethod
    def get_config_model(cls):
        """Return the Pydantic model for node configuration."""
        return {ServiceName}NodeConfig

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute the configured operation.

        Args:
            inputs: Output data from upstream nodes

        Returns:
            Dict with operation results including status, action, data, and timing
        """
        start_time = time.time()

        # Validate configuration
        config = self.config
        if not config or not isinstance(config, {ServiceName}NodeConfig):
            raise ValueError("Valid configuration is required")

        # Validate credentials
        credentials = config.credentials
        if not credentials:
            raise ValueError(
                "Credentials are required. Add your {SERVICE_NAME} API credentials."
            )

        # Get the specific operation config
        op_config = config.config

        # Route to appropriate handler based on operation
        handlers = {
            # {Category1}
            "list_{resources}": self._handle_list_{resources},
            "get_{resource}": self._handle_get_{resource},
            "create_{resource}": self._handle_create_{resource},
            "update_{resource}": self._handle_update_{resource},
            "delete_{resource}": self._handle_delete_{resource},
            # {Category2}
            # ... more handlers
        }

        operation = op_config.operation
        handler = handlers.get(operation)

        if not handler:
            raise ValueError(f"Unknown operation: {operation}")

        # Execute the handler
        result = await handler(op_config, credentials)

        # Add timing information
        total_time = (time.time() - start_time) * 1000
        result["timing_ms"] = {
            **result.get("timing_ms", {}),
            "total": round(total_time, 2)
        }

        return result

    # =========================================================================
    # HTTP Request Helper
    # =========================================================================

    async def _make_request(
        self,
        method: str,
        endpoint: str,
        credentials: {ServiceName}Credential,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
        action_name: str = "request"
    ) -> Dict[str, Any]:
        """
        Make an HTTP request to the {SERVICE_NAME} API.

        Args:
            method: HTTP method (GET, POST, PUT, PATCH, DELETE)
            endpoint: API endpoint (without base URL)
            credentials: API credentials
            params: Query parameters
            json_body: JSON request body
            action_name: Name of the action (for response metadata)

        Returns:
            Dict with status, action, data, status_code, and timing
        """
        url = f"{{SERVICE_UPPER}_API_BASE}{endpoint}"

        # Build headers based on credential type
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            # API Key auth
            "Authorization": f"Bearer {credentials.api_key}",
            # Or: "X-API-Key": credentials.api_key,
            # Or for OAuth: "Authorization": f"Bearer {credentials.access_token}",
        }

        # Clean params (remove None values)
        if params:
            params = {k: v for k, v in params.items() if v is not None}

        start_time = time.time()

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.request(
                    method=method,
                    url=url,
                    headers=headers,
                    params=params,
                    json=json_body
                )

                api_time = (time.time() - start_time) * 1000

                if response.status_code >= 400:
                    error_text = response.text
                    try:
                        error_data = response.json()
                        error_message = error_data.get("message", error_data.get("error", error_text))
                    except Exception:
                        error_message = error_text

                    logger.error(f"[{ServiceName}Node] API error: {error_message}")
                    return {
                        "status": "error",
                        "action": action_name,
                        "error": error_message,
                        "status_code": response.status_code,
                        "timing_ms": {"api_request": round(api_time, 2)}
                    }

                # Parse response
                if response.status_code == 204:  # No content
                    data = {"success": True}
                else:
                    try:
                        data = response.json()
                    except Exception:
                        data = {"raw": response.text}

                return {
                    "status": "success",
                    "action": action_name,
                    "data": data,
                    "status_code": response.status_code,
                    "timing_ms": {"api_request": round(api_time, 2)}
                }

            except httpx.TimeoutException:
                return {
                    "status": "error",
                    "action": action_name,
                    "error": "Request timed out",
                    "status_code": 408,
                    "timing_ms": {"api_request": round((time.time() - start_time) * 1000, 2)}
                }
            except Exception as e:
                logger.exception(f"[{ServiceName}Node] Request failed: {e}")
                return {
                    "status": "error",
                    "action": action_name,
                    "error": str(e),
                    "status_code": 500,
                    "timing_ms": {"api_request": round((time.time() - start_time) * 1000, 2)}
                }

    # =========================================================================
    # Handler Methods
    # =========================================================================

    # -------------------------------------------------------------------------
    # {Category1} Handlers
    # -------------------------------------------------------------------------

    async def _handle_list_{resources}(
        self,
        config: {ServiceName}List{Resource}Config,
        credentials: {ServiceName}Credential
    ) -> Dict[str, Any]:
        """List all {resources}."""
        params = {
            "page": config.page,
            "per_page": config.per_page,
        }
        if config.status:
            params["status"] = config.status

        return await self._make_request(
            method="GET",
            endpoint="/{resources}",
            credentials=credentials,
            params=params,
            action_name="list_{resources}"
        )

    async def _handle_get_{resource}(
        self,
        config: {ServiceName}Get{Resource}Config,
        credentials: {ServiceName}Credential
    ) -> Dict[str, Any]:
        """Get a specific {resource}."""
        return await self._make_request(
            method="GET",
            endpoint=f"/{resources}/{config.{resource}_id}",
            credentials=credentials,
            action_name="get_{resource}"
        )

    async def _handle_create_{resource}(
        self,
        config: {ServiceName}Create{Resource}Config,
        credentials: {ServiceName}Credential
    ) -> Dict[str, Any]:
        """Create a new {resource}."""
        body = {
            "name": config.name,
        }
        if config.description:
            body["description"] = config.description

        return await self._make_request(
            method="POST",
            endpoint="/{resources}",
            credentials=credentials,
            json_body=body,
            action_name="create_{resource}"
        )

    async def _handle_update_{resource}(
        self,
        config: {ServiceName}Update{Resource}Config,
        credentials: {ServiceName}Credential
    ) -> Dict[str, Any]:
        """Update an existing {resource}."""
        body = {}
        if config.name is not None:
            body["name"] = config.name
        if config.description is not None:
            body["description"] = config.description

        return await self._make_request(
            method="PATCH",
            endpoint=f"/{resources}/{config.{resource}_id}",
            credentials=credentials,
            json_body=body,
            action_name="update_{resource}"
        )

    async def _handle_delete_{resource}(
        self,
        config: {ServiceName}Delete{Resource}Config,
        credentials: {ServiceName}Credential
    ) -> Dict[str, Any]:
        """Delete a {resource}."""
        return await self._make_request(
            method="DELETE",
            endpoint=f"/{resources}/{config.{resource}_id}",
            credentials=credentials,
            action_name="delete_{resource}"
        )

    # -------------------------------------------------------------------------
    # {Category2} Handlers (repeat pattern)
    # -------------------------------------------------------------------------

    # ... more handler methods
