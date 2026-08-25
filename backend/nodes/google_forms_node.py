"""
Google Forms workflow node implementation.
Enables managing forms and reading responses via Google Forms API with OAuth credentials.

Supports 6 operations:
- Forms: list_forms, get_form, create_form, update_form
- Responses: list_responses, get_response
"""

import time
import logging
from typing import Dict, Any, Optional, Union, Type, List, Literal, Annotated
from pydantic import BaseModel, ConfigDict, Discriminator, Field
import httpx

from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.dynamic_options import require_credential_token
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from nodes.oauth.google_oauth import is_token_expired, refresh_access_token
from nodes.oauth.google_token import ensure_fresh_google_token
from nodes.scopes.google import GOOGLE_FORMS_SCOPES

logger = logging.getLogger(__name__)

GOOGLE_FORMS_API_BASE = "https://forms.googleapis.com/v1/forms"
GOOGLE_DRIVE_API_BASE = "https://www.googleapis.com/drive/v3"


async def forms_list_responses(
    access_token: str, form_id: str
) -> List[Dict[str, Any]]:
    """List every response to a form (paginated)."""
    responses: List[Dict[str, Any]] = []
    page_token = None
    async with httpx.AsyncClient(timeout=30.0) as client:
        while True:
            params: Dict[str, Any] = {"pageSize": 100}
            if page_token:
                params["pageToken"] = page_token
            response = await client.get(
                f"{GOOGLE_FORMS_API_BASE}/{form_id}/responses",
                headers={"Authorization": f"Bearer {access_token}"},
                params=params,
            )
            response.raise_for_status()
            data = response.json()
            responses.extend(data.get("responses", []))
            page_token = data.get("nextPageToken")
            if not page_token:
                return responses


# ============================================================================
# Google Forms Node Credential Schema
# ============================================================================


class GoogleFormsOAuthCredential(BaseModel):
    """
    OAuth credential for Google Forms access.
    Tokens are obtained via OAuth flow, not entered manually.
    """

    credential_type: Literal["google_forms_oauth"] = Field(
        "google_forms_oauth", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(
        ..., title="Access Token", description="OAuth 2.0 access token from Google"
    )
    refresh_token: str = Field(
        ...,
        title="Refresh Token",
        description="OAuth 2.0 refresh token for automatic renewal",
    )
    expires_at: str = Field(
        ...,
        title="Token Expiry",
        description="ISO 8601 timestamp when access token expires",
    )
    email: str = Field(
        ...,
        title="Google Account",
        description="Email address of the connected Google account",
    )

    model_config = ConfigDict(json_schema_extra={
        "x-credential-type": "oauth",
        "x-oauth-provider": "google",
        "x-oauth-scopes": [
            "https://www.googleapis.com/auth/forms.body",
            "https://www.googleapis.com/auth/forms.responses.readonly",
            "https://www.googleapis.com/auth/drive",
        ],
    })


# ============================================================================
# Google Forms Node Configuration Models
# ============================================================================


class GoogleFormsListFormsConfig(BaseModel):
    """Configuration for listing forms from Google Drive"""

    operation: Literal["list_google_drive_forms"] = Field(
        "list_google_drive_forms",
        title="List Google Drive Forms",
        description="List Google Forms",
        json_schema_extra={
            "ui:hidden": True,
            "const": "list_google_drive_forms",
            "x-category": "Form",
            "x-is-trigger": False,
            "x-display-name": "List Google Drive Forms",
        },
    )
    page_size: Optional[int] = Field(
        50,
        title="Page Size",
        description="Maximum number of forms to return (1-100)",
        ge=1,
        le=100,
    )
    search_query: Optional[str] = Field(
        None,
        title="Search Query",
        description="Search term to filter forms by name",
        json_schema_extra={"placeholder": "Form name (optional)"},
    )


class GoogleFormsGetFormConfig(BaseModel):
    """Configuration for getting a form"""

    operation: Literal["get_form_metadata"] = Field(
        "get_form_metadata",
        title="Get Form Metadata",
        description="Get a form",
        json_schema_extra={
            "ui:hidden": True,
            "const": "get_form_metadata",
            "x-category": "Form",
            "x-is-trigger": False,
            "x-display-name": "Get Form Metadata",
        },
    )
    form_id: str = Field(
        ...,
        title="Form",
        description="Select a Google Form",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "form_id",
                "placeholder": "Select a form...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste form ID",
            },
            "x-resource-type": "google_form",
        },
    )


class GoogleFormsCreateFormConfig(BaseModel):
    """Configuration for creating a new form"""

    operation: Literal["create_new_form"] = Field(
        "create_new_form",
        title="Create New Form",
        description="Create a new form",
        json_schema_extra={
            "ui:hidden": True,
            "const": "create_new_form",
            "x-category": "Form",
            "x-is-trigger": False,
            "x-display-name": "Create New Form",
            "x-creates-resource": True,
            "x-resource-type": "google_form",
            "x-resource-id-path": "form.formId",
        },
    )
    title: str = Field(
        ...,
        title="Title",
        description="Title for the new form",
        json_schema_extra={"placeholder": "My Survey"},
    )
    document_title: Optional[str] = Field(
        None,
        title="Document Title",
        description="Title shown in Google Drive (defaults to form title)",
        json_schema_extra={"placeholder": "Drive filename (optional)"},
    )


class GoogleFormsUpdateFormConfig(BaseModel):
    """Configuration for updating a form's metadata"""

    operation: Literal["update_form_metadata"] = Field(
        "update_form_metadata",
        title="Update Form Metadata",
        description="Update form metadata",
        json_schema_extra={
            "ui:hidden": True,
            "const": "update_form_metadata",
            "x-category": "Form",
            "x-is-trigger": False,
            "x-display-name": "Update Form Metadata",
        },
    )
    form_id: str = Field(
        ...,
        title="Form",
        description="Select a Google Form",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "form_id",
                "placeholder": "Select a form...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste form ID",
            },
            "x-resource-type": "google_form",
        },
    )
    title: Optional[str] = Field(
        None,
        title="New Title",
        description="New title for the form",
        json_schema_extra={"placeholder": "New title (optional)"},
    )
    description: Optional[str] = Field(
        None,
        title="Description",
        description="Description shown at the top of the form",
        json_schema_extra={
            "ui:widget": "textarea",
            "placeholder": "Form description (optional)",
        },
    )


class GoogleFormsListResponsesConfig(BaseModel):
    """Configuration for listing form responses"""

    operation: Literal["list_form_responses"] = Field(
        "list_form_responses",
        title="List Form Responses",
        description="List form responses",
        json_schema_extra={
            "ui:hidden": True,
            "const": "list_form_responses",
            "x-category": "Response",
            "x-is-trigger": False,
            "x-display-name": "List Form Responses",
        },
    )
    form_id: str = Field(
        ...,
        title="Form",
        description="Select a Google Form",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "form_id",
                "placeholder": "Select a form...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste form ID",
            },
            "x-resource-type": "google_form",
        },
    )
    page_size: Optional[int] = Field(
        50,
        title="Page Size",
        description="Maximum number of responses to return (1-5000)",
        ge=1,
        le=5000,
    )


class GoogleFormsGetResponseConfig(BaseModel):
    """Configuration for getting a single response"""

    operation: Literal["get_form_response"] = Field(
        "get_form_response",
        title="Get Form Response",
        description="Get a specific response",
        json_schema_extra={
            "ui:hidden": True,
            "const": "get_form_response",
            "x-category": "Response",
            "x-is-trigger": False,
            "x-display-name": "Get Form Response",
        },
    )
    form_id: str = Field(
        ...,
        title="Form",
        description="Select a Google Form",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "form_id",
                "placeholder": "Select a form...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste form ID",
            },
            "x-resource-type": "google_form",
        },
    )
    response_id: str = Field(
        ...,
        title="Response ID",
        description="The ID of the response to retrieve",
        json_schema_extra={"placeholder": "Response ID"},
    )


class GoogleFormsOnResponseConfig(PollTriggerConfigBase):
    """Trigger: polls a form on a schedule and fires for new responses."""

    operation: Literal["on_form_response"] = Field(
        "on_form_response",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": None,
            "x-is-trigger": True,
            "x-display-name": "On Form Response",
        },
        title="On Form Response",
    )
    form_id: str = Field(
        ...,
        title="Form",
        description="The form to watch for new responses",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "form_id",
                "placeholder": "Select a form...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a form ID",
            }
        },
    )


# Union of all config types for oneOf schema
GoogleFormsConfig = Annotated[
    Union[
        GoogleFormsOnResponseConfig,
        GoogleFormsListFormsConfig,
        GoogleFormsGetFormConfig,
        GoogleFormsCreateFormConfig,
        GoogleFormsUpdateFormConfig,
        GoogleFormsListResponsesConfig,
        GoogleFormsGetResponseConfig,
    ],
    Discriminator("operation"),
]


class GoogleFormsNodeConfig(NodeConfig[GoogleFormsConfig, GoogleFormsOAuthCredential]):
    """Full configuration for Google Forms node including credentials"""

    pass


# ============================================================================
# Google Forms Node Implementation
# ============================================================================


class GoogleFormsNode(ScheduledPollTriggerMixin, WorkflowNode):
    """
    Google Forms workflow node for managing forms and responses.
    """

    edit_examples = [
        "Create a new product feedback survey with 5 questions and share link",
        "Get all responses from customer satisfaction form and get statistics",
        "Update the job application form title and add new required fields",
        "List all active surveys and count total responses from this month",
        "Get a specific response and extract the answers into structured data",
        "Create an onboarding form for new employees with required documents",
        "Get form responses and filter by rating to identify detractors",
    ]

    async def _trigger_on_form_response(self, config, credentials) -> Dict[str, Any]:
        """Poll the form and emit responses submitted since the last poll."""

        cred_dict = credentials.model_dump()
        credential_id = (self.node_data or {}).get("credential_id")
        access_token = await ensure_fresh_google_token(
            None, credential_id, self.user_id, cred_dict
        )
        responses = await forms_list_responses(access_token, config.form_id)
        new_responses = await self._filter_unseen(
            responses, lambda r: r.get("responseId")
        )
        return {
            "responses": new_responses,
            "new_response_count": len(new_responses),
        }

    scope_registry = GOOGLE_FORMS_SCOPES
    connection_evidence = ConnectionEvidence(
        field="form_id",
        noun="forms",
    )

    @classmethod
    def get_config_model(cls) -> Optional[Union[Type, type]]:
        """Get Pydantic config model for Google Forms node"""
        return GoogleFormsNodeConfig

    @classmethod
    async def load_field_options(
        cls,
        field_name: str,
        credential_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        page_token: Optional[str] = None,
        search: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Load dynamic options for a field."""
        logger.info(f"[GoogleFormsNode] load_field_options called: field={field_name}")
        if field_name == "form_id":
            return await cls._list_forms_options(credential_data, search=search)
        return []

    @classmethod
    async def _list_forms_options(
        cls, credential_data: Dict[str, Any], search: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """List Google Forms for dropdown options."""
        access_token = require_credential_token(
            credential_data.get("access_token"),
            "Connect a Google account to load forms",
        )

        # Query Drive API for Google Forms files
        url = f"{GOOGLE_DRIVE_API_BASE}/files"
        query_parts = [
            "mimeType='application/vnd.google-apps.form'",
            "trashed=false",
        ]
        if search:
            # Escape single quotes for Drive query syntax
            escaped = search.replace("'", "\\'")
            query_parts.append(f"name contains '{escaped}'")
        params = {
            "q": " and ".join(query_parts),
            "fields": "files(id,name,modifiedTime)",
            "orderBy": "modifiedTime desc",
            "pageSize": 100,
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    url,
                    headers={"Authorization": f"Bearer {access_token}"},
                    params=params,
                )

                if response.status_code != 200:
                    error_data = response.json()
                    error_msg = error_data.get("error", {}).get(
                        "message", response.text
                    )
                    logger.error(f"[GoogleFormsNode] Drive API error: {error_msg}")
                    raise ValueError(f"Google Drive API error: {error_msg}")

                data = response.json()
                files = data.get("files", [])

                options = []
                for f in files:
                    options.append(
                        {
                            "value": f.get("id"),
                            "label": f.get("name", f.get("id")),
                            "metadata": {"modifiedTime": f.get("modifiedTime")},
                        }
                    )

                logger.info(f"[GoogleFormsNode] Found {len(options)} forms")
                return options

        except ValueError:
            raise
        except Exception as e:
            logger.error(f"[GoogleFormsNode] Error listing forms: {e}")
            raise ValueError(f"Failed to load Google Forms options: {e}") from e

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Execute Google Forms operation."""
        logger.info(f"[GoogleFormsNode] Executing node {self.node_id}")

        node_config = self.config
        if not node_config:
            raise ValueError(
                f"[GoogleFormsNode] Configuration is required but not provided for node {self.node_id}"
            )

        if not isinstance(node_config, GoogleFormsNodeConfig):
            raise ValueError(
                f"[GoogleFormsNode] Invalid config type: {type(node_config)}, expected GoogleFormsNodeConfig"
            )

        config = node_config.config
        credentials = node_config.credentials

        if not credentials:
            raise ValueError(
                f"[GoogleFormsNode] Google Forms credentials are required but not provided. "
                f"Please connect a Google account in the node's credentials tab."
            )

        # Trigger operation — poll the form for new responses
        if isinstance(config, GoogleFormsOnResponseConfig):
            output = await self._trigger_on_form_response(config, credentials)
            await self.emit(output)
            return output

        access_token = await self._ensure_fresh_token(credentials)

        # Execute operation based on config type
        if isinstance(config, GoogleFormsListFormsConfig):
            output = await self._list_forms(config, access_token)
        elif isinstance(config, GoogleFormsGetFormConfig):
            output = await self._get_form(config, access_token)
        elif isinstance(config, GoogleFormsCreateFormConfig):
            output = await self._create_form(config, access_token)
        elif isinstance(config, GoogleFormsUpdateFormConfig):
            output = await self._update_form(config, access_token)
        elif isinstance(config, GoogleFormsListResponsesConfig):
            output = await self._list_responses(config, access_token)
        elif isinstance(config, GoogleFormsGetResponseConfig):
            output = await self._get_response(config, access_token)
        else:
            raise ValueError(f"Unexpected config type: {type(config)}")

        await self.emit(output)
        return output

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        """Refresh an expiring OAuth token at credential load (dropdowns,
        trigger registration). No-op for non-rotating credentials (API keys /
        offline / non-expiring tokens)."""
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.google_oauth import refresh_access_token

        return await freshen_oauth_credential(
            credential_data, pool=pool, user_id=user_id, credential_id=credential_id,
            refresh=refresh_access_token,
            provider="google",
        )

    async def _ensure_fresh_token(self, credentials: GoogleFormsOAuthCredential) -> str:
        """Return a valid Google Forms access token, refreshing + persisting if expired."""
        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        from nodes.oauth.google_oauth import refresh_access_token

        cred_dict = credentials.model_dump()
        token = await ensure_fresh_oauth_token(
            credential_id=(self.node_data or {}).get("credential_id"),
            user_id=self.user_id,
            credential=cred_dict,
            refresh=refresh_access_token,
            provider="google",
        )
        credentials.access_token = cred_dict["access_token"]
        credentials.expires_at = cred_dict.get("expires_at")
        if cred_dict.get("refresh_token"):
            credentials.refresh_token = cred_dict["refresh_token"]
        return token

    async def _list_forms(
        self, config: GoogleFormsListFormsConfig, access_token: str
    ) -> Dict[str, Any]:
        """List Google Forms from Drive."""
        logger.info(f"[GoogleFormsNode] Listing forms")

        url = f"{GOOGLE_DRIVE_API_BASE}/files"

        # Build query for Google Forms
        query_parts = ["mimeType='application/vnd.google-apps.form'", "trashed=false"]
        if config.search_query:
            query_parts.append(f"name contains '{config.search_query}'")

        params: Dict[str, Any] = {
            "q": " and ".join(query_parts),
            "fields": "files(id,name,modifiedTime,createdTime,owners)",
            "orderBy": "modifiedTime desc",
        }

        if config.page_size:
            params["pageSize"] = config.page_size

        async with httpx.AsyncClient() as client:
            response = await client.get(
                url, headers={"Authorization": f"Bearer {access_token}"}, params=params
            )

            if response.status_code != 200:
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", response.text)
                logger.error(f"[GoogleFormsNode] List forms failed: {error_msg}")
                raise ValueError(f"Google Drive API error: {error_msg}")

            data = response.json()
            files = data.get("files", [])

            forms = []
            for f in files:
                forms.append(
                    {
                        "id": f.get("id"),
                        "name": f.get("name"),
                        "modifiedTime": f.get("modifiedTime"),
                        "createdTime": f.get("createdTime"),
                        "owners": f.get("owners", []),
                    }
                )

            output = {
                "type": "google_forms",
                "operation": "list_google_drive_forms",
                "form_count": len(forms),
                "forms": forms,
                "timestamp": time.time(),
                "status": "success",
            }

            logger.info(f"[GoogleFormsNode] Listed {len(forms)} forms")
            return output

    async def _get_form(
        self, config: GoogleFormsGetFormConfig, access_token: str
    ) -> Dict[str, Any]:
        """Get a form."""
        logger.info(f"[GoogleFormsNode] Getting form {config.form_id}")

        url = f"{GOOGLE_FORMS_API_BASE}/{config.form_id}"

        async with httpx.AsyncClient() as client:
            response = await client.get(
                url,
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code != 200:
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", response.text)
                logger.error(f"[GoogleFormsNode] Get form failed: {error_msg}")
                raise ValueError(f"Google Forms API error: {error_msg}")

            form = response.json()

            # Simplify items
            items = []
            for item in form.get("items", []):
                simplified_item = {
                    "itemId": item.get("itemId"),
                    "title": item.get("title"),
                    "description": item.get("description"),
                }
                if "questionItem" in item:
                    q = item["questionItem"].get("question", {})
                    simplified_item["questionType"] = q.get("questionType")
                    simplified_item["required"] = q.get("required", False)
                items.append(simplified_item)

            output = {
                "type": "google_forms",
                "operation": "get_form_metadata",
                "form": {
                    "formId": form.get("formId"),
                    "title": form.get("info", {}).get("title"),
                    "description": form.get("info", {}).get("description"),
                    "documentTitle": form.get("info", {}).get("documentTitle"),
                    "responderUri": form.get("responderUri"),
                    "linkedSheetId": form.get("linkedSheetId"),
                    "itemCount": len(items),
                    "items": items,
                },
                "timestamp": time.time(),
                "status": "success",
            }

            logger.info(
                f"[GoogleFormsNode] Retrieved form: {form.get('info', {}).get('title')}"
            )
            return output

    async def _create_form(
        self, config: GoogleFormsCreateFormConfig, access_token: str
    ) -> Dict[str, Any]:
        """Create a new form."""
        logger.info(f"[GoogleFormsNode] Creating form: {config.title}")

        url = GOOGLE_FORMS_API_BASE

        form_body: Dict[str, Any] = {
            "info": {
                "title": config.title,
            }
        }

        if config.document_title:
            form_body["info"]["documentTitle"] = config.document_title

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json=form_body,
            )

            if response.status_code not in (200, 201):
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", response.text)
                logger.error(f"[GoogleFormsNode] Create form failed: {error_msg}")
                raise ValueError(f"Google Forms API error: {error_msg}")

            form = response.json()

            output = {
                "type": "google_forms",
                "operation": "create_new_form",
                "form_id": form.get("formId"),
                "form": {
                    "formId": form.get("formId"),
                    "title": form.get("info", {}).get("title"),
                    "documentTitle": form.get("info", {}).get("documentTitle"),
                    "responderUri": form.get("responderUri"),
                },
                "timestamp": time.time(),
                "status": "success",
            }

            logger.info(f"[GoogleFormsNode] Created form: {form.get('formId')}")
            return output

    async def _update_form(
        self, config: GoogleFormsUpdateFormConfig, access_token: str
    ) -> Dict[str, Any]:
        """Update a form's metadata."""
        logger.info(f"[GoogleFormsNode] Updating form {config.form_id}")

        url = f"{GOOGLE_FORMS_API_BASE}/{config.form_id}:batchUpdate"

        requests = []

        if config.title:
            requests.append(
                {
                    "updateFormInfo": {
                        "info": {"title": config.title},
                        "updateMask": "title",
                    }
                }
            )

        if config.description is not None:
            requests.append(
                {
                    "updateFormInfo": {
                        "info": {"description": config.description},
                        "updateMask": "description",
                    }
                }
            )

        if not requests:
            raise ValueError(
                "At least one field (title or description) must be provided to update"
            )

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json={"requests": requests},
            )

            if response.status_code != 200:
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", response.text)
                logger.error(f"[GoogleFormsNode] Update form failed: {error_msg}")
                raise ValueError(f"Google Forms API error: {error_msg}")

            result = response.json()

            output = {
                "type": "google_forms",
                "operation": "update_form_metadata",
                "form_id": config.form_id,
                "form": result.get("form", {}),
                "timestamp": time.time(),
                "status": "success",
            }

            logger.info(f"[GoogleFormsNode] Updated form: {config.form_id}")
            return output

    async def _list_responses(
        self, config: GoogleFormsListResponsesConfig, access_token: str
    ) -> Dict[str, Any]:
        """List form responses."""
        logger.info(f"[GoogleFormsNode] Listing responses for form {config.form_id}")

        url = f"{GOOGLE_FORMS_API_BASE}/{config.form_id}/responses"
        params: Dict[str, Any] = {}

        if config.page_size:
            params["pageSize"] = config.page_size

        async with httpx.AsyncClient() as client:
            response = await client.get(
                url, headers={"Authorization": f"Bearer {access_token}"}, params=params
            )

            if response.status_code != 200:
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", response.text)
                logger.error(f"[GoogleFormsNode] List responses failed: {error_msg}")
                raise ValueError(f"Google Forms API error: {error_msg}")

            data = response.json()
            responses = data.get("responses", [])

            simplified_responses = []
            for r in responses:
                simplified_responses.append(
                    {
                        "responseId": r.get("responseId"),
                        "createTime": r.get("createTime"),
                        "lastSubmittedTime": r.get("lastSubmittedTime"),
                        "respondentEmail": r.get("respondentEmail"),
                        "answers": r.get("answers", {}),
                    }
                )

            output = {
                "type": "google_forms",
                "operation": "list_form_responses",
                "form_id": config.form_id,
                "response_count": len(simplified_responses),
                "responses": simplified_responses,
                "timestamp": time.time(),
                "status": "success",
            }

            logger.info(
                f"[GoogleFormsNode] Listed {len(simplified_responses)} responses"
            )
            return output

    async def _get_response(
        self, config: GoogleFormsGetResponseConfig, access_token: str
    ) -> Dict[str, Any]:
        """Get a single response."""
        logger.info(f"[GoogleFormsNode] Getting response {config.response_id}")

        url = f"{GOOGLE_FORMS_API_BASE}/{config.form_id}/responses/{config.response_id}"

        async with httpx.AsyncClient() as client:
            response = await client.get(
                url,
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code != 200:
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", response.text)
                logger.error(f"[GoogleFormsNode] Get response failed: {error_msg}")
                raise ValueError(f"Google Forms API error: {error_msg}")

            r = response.json()

            output = {
                "type": "google_forms",
                "operation": "get_form_response",
                "form_id": config.form_id,
                "response": {
                    "responseId": r.get("responseId"),
                    "createTime": r.get("createTime"),
                    "lastSubmittedTime": r.get("lastSubmittedTime"),
                    "respondentEmail": r.get("respondentEmail"),
                    "answers": r.get("answers", {}),
                },
                "timestamp": time.time(),
                "status": "success",
            }

            logger.info(f"[GoogleFormsNode] Retrieved response: {config.response_id}")
            return output
