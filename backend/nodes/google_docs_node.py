"""
Google Docs workflow node implementation.
Enables creating, reading, and modifying Google Documents via OAuth credentials.

Supports 6 operations:
- Documents: list_documents, get_document, create_document, update_document, append_text, batch_update
"""

import time
import logging
from typing import Dict, Any, Optional, Union, Type, List, Literal, Annotated
from pydantic import BaseModel, ConfigDict, Discriminator, Field
import httpx

from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.dynamic_options import require_credential_token
from nodes.oauth.google_oauth import is_token_expired, refresh_access_token
from nodes.scopes.google import GOOGLE_DOCS_SCOPES

logger = logging.getLogger(__name__)

GOOGLE_DOCS_API_BASE = "https://docs.googleapis.com/v1/documents"
GOOGLE_DRIVE_API_BASE = "https://www.googleapis.com/drive/v3"


# ============================================================================
# Google Docs Node Credential Schema
# ============================================================================


class GoogleDocsOAuthCredential(BaseModel):
    """
    OAuth credential for Google Docs access.
    Tokens are obtained via OAuth flow, not entered manually.
    """

    credential_type: Literal["google_docs_oauth"] = Field(
        "google_docs_oauth", json_schema_extra={"ui:hidden": True}
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

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-type": "oauth",
            "x-oauth-provider": "google",
            "x-oauth-scopes": [
                "https://www.googleapis.com/auth/documents",
                "https://www.googleapis.com/auth/drive",
            ],
        }
    )


# ============================================================================
# Google Docs Node Configuration Models
# ============================================================================


class GoogleDocsListDocumentsConfig(BaseModel):
    """Configuration for listing documents from Google Drive"""

    operation: Literal["list_google_drive_documents"] = Field(
        "list_google_drive_documents",
        title="List Google Drive Documents",
        description="List Google Docs documents",
        json_schema_extra={
            "ui:hidden": True,
            "const": "list_google_drive_documents",
            "x-category": "Document",
            "x-is-trigger": False,
            "x-display-name": "List Google Drive Documents",
            "x-keywords": [
                "list docs",
                "browse drive",
                "my documents",
                "all google docs",
                "find files",
            ],
        },
    )
    page_size: Optional[int] = Field(
        50,
        title="Page Size",
        description="Maximum number of documents to return (1-100)",
        ge=1,
        le=100,
    )
    search_query: Optional[str] = Field(
        None,
        title="Search Query",
        description="Search term to filter documents by name",
        json_schema_extra={"placeholder": "Document name (optional)"},
    )


class GoogleDocsGetDocumentConfig(BaseModel):
    """Configuration for getting a document"""

    operation: Literal["fetch_document_content"] = Field(
        "fetch_document_content",
        title="Fetch Document Content",
        description="Get a document",
        json_schema_extra={
            "ui:hidden": True,
            "const": "fetch_document_content",
            "x-category": "Document",
            "x-is-trigger": False,
            "x-display-name": "Fetch Document Content",
            "x-keywords": [
                "read doc",
                "get doc text",
                "document contents",
                "open document",
                "pull doc body",
            ],
        },
    )
    document_id: str = Field(
        ...,
        title="Document",
        description="Select a Google Doc",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "document_id",
                "placeholder": "Select a document...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste document ID",
            },
            "x-resource-type": "google_doc",
        },
    )
    include_content: Optional[bool] = Field(
        True,
        title="Include Content",
        description="Whether to include the document's full content",
    )


class GoogleDocsCreateDocumentConfig(BaseModel):
    """Configuration for creating a new document"""

    operation: Literal["create_new_document"] = Field(
        "create_new_document",
        title="Create New Document",
        description="Create a new document",
        json_schema_extra={
            "ui:hidden": True,
            "const": "create_new_document",
            "x-category": "Document",
            "x-is-trigger": False,
            "x-display-name": "Create New Document",
            "x-keywords": [
                "new doc",
                "start document",
                "blank document",
                "make google doc",
            ],
            # Auto-extend scope: when this op runs successfully, the newly
            # created document's ID is appended to every google_doc scope on
            # this provider's allowlist (so the agent that just created the
            # doc can immediately read/edit it on subsequent turns).
            "x-creates-resource": True,
            "x-resource-type": "google_doc",
            "x-resource-id-path": "document.documentId",
        },
    )
    title: str = Field(
        ...,
        title="Title",
        description="Title for the new document",
        json_schema_extra={"placeholder": "My Document"},
    )
    initial_content: Optional[str] = Field(
        None,
        title="Initial Content",
        description="Initial text content for the document",
        json_schema_extra={
            "ui:widget": "textarea",
            "placeholder": "Enter initial content... (optional)",
        },
    )


class GoogleDocsAppendTextConfig(BaseModel):
    """Configuration for appending text to a document"""

    operation: Literal["append_text_to_document"] = Field(
        "append_text_to_document",
        title="Append Text to Document",
        description="Append text to document",
        json_schema_extra={
            "ui:hidden": True,
            "const": "append_text_to_document",
            "x-category": "Document",
            "x-is-trigger": False,
            "x-display-name": "Append Text to Document",
            "x-keywords": [
                "append text",
                "add to end",
                "write at bottom",
                "add paragraph",
                "concatenate text",
            ],
        },
    )
    document_id: str = Field(
        ...,
        title="Document",
        description="Select a Google Doc",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "document_id",
                "placeholder": "Select a document...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste document ID",
            },
            "x-resource-type": "google_doc",
        },
    )
    text: str = Field(
        ...,
        title="Text",
        description="Text to append to the document",
        json_schema_extra={"ui:widget": "textarea", "placeholder": "Text to append..."},
    )
    add_newline: Optional[bool] = Field(
        True, title="Add Newline", description="Add a newline before the text"
    )


class GoogleDocsInsertTextConfig(BaseModel):
    """Configuration for inserting text at a specific location"""

    operation: Literal["insert_text_in_document"] = Field(
        "insert_text_in_document",
        title="Insert Text in Document",
        description="Insert text at position",
        json_schema_extra={
            "ui:hidden": True,
            "const": "insert_text_in_document",
            "x-category": "Document",
            "x-is-trigger": False,
            "x-display-name": "Insert Text in Document",
            "x-keywords": [
                "insert at index",
                "place text",
                "add text at position",
                "inject text",
                "write at offset",
            ],
        },
    )
    document_id: str = Field(
        ...,
        title="Document",
        description="Select a Google Doc",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "document_id",
                "placeholder": "Select a document...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste document ID",
            },
            "x-resource-type": "google_doc",
        },
    )
    text: str = Field(
        ...,
        title="Text",
        description="Text to insert",
        json_schema_extra={"ui:widget": "textarea", "placeholder": "Text to insert..."},
    )
    index: int = Field(
        1,
        title="Index",
        description="Character position to insert at (1 = beginning of document)",
        ge=1,
    )


class GoogleDocsReplaceTextConfig(BaseModel):
    """Configuration for replacing text in a document"""

    operation: Literal["replace_document_text"] = Field(
        "replace_document_text",
        title="Replace Document Text",
        description="Replace text in document",
        json_schema_extra={
            "ui:hidden": True,
            "const": "replace_document_text",
            "x-category": "Document",
            "x-is-trigger": False,
            "x-display-name": "Replace Document Text",
            "x-keywords": [
                "find and replace",
                "swap text",
                "substitute words",
                "replace all",
                "overwrite text",
            ],
        },
    )
    document_id: str = Field(
        ...,
        title="Document",
        description="Select a Google Doc",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "document_id",
                "placeholder": "Select a document...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste document ID",
            },
            "x-resource-type": "google_doc",
        },
    )
    find_text: str = Field(
        ...,
        title="Find Text",
        description="Text to find and replace",
        json_schema_extra={"placeholder": "Text to find"},
    )
    replace_with: str = Field(
        ...,
        title="Replace With",
        description="Replacement text",
        json_schema_extra={"placeholder": "Replacement text"},
    )
    match_case: Optional[bool] = Field(
        True, title="Match Case", description="Whether the search is case-sensitive"
    )


# Union of all config types for oneOf schema
GoogleDocsConfig = Annotated[
    Union[
        GoogleDocsListDocumentsConfig,
        GoogleDocsGetDocumentConfig,
        GoogleDocsCreateDocumentConfig,
        GoogleDocsAppendTextConfig,
        GoogleDocsInsertTextConfig,
        GoogleDocsReplaceTextConfig,
    ],
    Discriminator("operation"),
]


class GoogleDocsNodeConfig(NodeConfig[GoogleDocsConfig, GoogleDocsOAuthCredential]):
    """Full configuration for Google Docs node including credentials"""

    pass


# ============================================================================
# Google Docs Node Implementation
# ============================================================================


class GoogleDocsNode(WorkflowNode):
    """
    Google Docs workflow node for managing Google Documents.
    """

    edit_examples = [
        "Create a new meeting notes document and append today's discussion",
        'Replace all instances of "2024" with "2025" in the handbook',
        "Get the content from the template and insert at position for new section",
        "List all shared documents and find which ones haven't been updated",
        "Append the monthly report data to the tracking document",
        "Get the design proposal document and extract specific paragraphs",
        "Create project documentation from template and customize for client",
    ]

    scope_registry = GOOGLE_DOCS_SCOPES
    connection_evidence = ConnectionEvidence(
        field="document_id",
        noun="documents",
    )

    @classmethod
    def get_config_model(cls) -> Optional[Union[Type, type]]:
        """Get Pydantic config model for Google Docs node"""
        return GoogleDocsNodeConfig

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
        logger.info(f"[GoogleDocsNode] load_field_options called: field={field_name}")
        if field_name == "document_id":
            return await cls._list_documents_options(credential_data, search=search)
        return []

    @classmethod
    async def _list_documents_options(
        cls, credential_data: Dict[str, Any], search: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """List Google Docs for dropdown options."""
        access_token = require_credential_token(
            credential_data.get("access_token"),
            "Connect a Google account to load documents",
        )

        # Query Drive API for Google Docs files
        url = f"{GOOGLE_DRIVE_API_BASE}/files"
        query_parts = [
            "mimeType='application/vnd.google-apps.document'",
            "trashed=false",
        ]
        if search:
            # Escape single quotes in search term per Drive API query syntax
            escaped = search.replace("\\", "\\\\").replace("'", "\\'")
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
                    logger.error(f"[GoogleDocsNode] Drive API error: {error_msg}")
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

                logger.info(f"[GoogleDocsNode] Found {len(options)} documents")
                return options

        except ValueError:
            raise
        except Exception as e:
            logger.error(f"[GoogleDocsNode] Error listing documents: {e}")
            raise ValueError(f"Failed to load Google Docs options: {e}") from e

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Execute Google Docs operation."""
        logger.info(f"[GoogleDocsNode] Executing node {self.node_id}")

        node_config = self.config
        if not node_config:
            raise ValueError(
                f"[GoogleDocsNode] Configuration is required but not provided for node {self.node_id}"
            )

        if not isinstance(node_config, GoogleDocsNodeConfig):
            raise ValueError(
                f"[GoogleDocsNode] Invalid config type: {type(node_config)}, expected GoogleDocsNodeConfig"
            )

        config = node_config.config
        credentials = node_config.credentials

        if not credentials:
            raise ValueError(
                f"[GoogleDocsNode] Google Docs credentials are required but not provided. "
                f"Please connect a Google account in the node's credentials tab."
            )

        access_token = await self._ensure_fresh_token(credentials)

        # Execute operation based on config type
        if isinstance(config, GoogleDocsListDocumentsConfig):
            output = await self._list_documents(config, access_token)
        elif isinstance(config, GoogleDocsGetDocumentConfig):
            output = await self._get_document(config, access_token)
        elif isinstance(config, GoogleDocsCreateDocumentConfig):
            output = await self._create_document(config, access_token)
        elif isinstance(config, GoogleDocsAppendTextConfig):
            output = await self._append_text(config, access_token)
        elif isinstance(config, GoogleDocsInsertTextConfig):
            output = await self._insert_text(config, access_token)
        elif isinstance(config, GoogleDocsReplaceTextConfig):
            output = await self._replace_text(config, access_token)
        else:
            raise ValueError(f"Unexpected config type: {type(config)}")

        await self.emit(output)
        return output

    @classmethod
    async def freshen_credential(
        cls, credential_data, *, pool=None, user_id=None, credential_id=None
    ):
        """Refresh an expiring OAuth token at credential load (dropdowns,
        trigger registration). No-op for non-rotating credentials (API keys /
        offline / non-expiring tokens)."""
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.google_oauth import refresh_access_token

        return await freshen_oauth_credential(
            credential_data,
            pool=pool,
            user_id=user_id,
            credential_id=credential_id,
            refresh=refresh_access_token,
            provider="google",
        )

    async def _ensure_fresh_token(self, credentials: GoogleDocsOAuthCredential) -> str:
        """Return a valid Google Docs access token, refreshing + persisting if expired."""
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

    def _extract_plain_text(self, content: Dict[str, Any]) -> str:
        """Extract plain text from document content."""
        text_parts = []
        body = content.get("body", {})
        elements = body.get("content", [])

        for element in elements:
            if "paragraph" in element:
                paragraph = element["paragraph"]
                for pe in paragraph.get("elements", []):
                    if "textRun" in pe:
                        text_parts.append(pe["textRun"].get("content", ""))

        return "".join(text_parts)

    async def _list_documents(
        self, config: GoogleDocsListDocumentsConfig, access_token: str
    ) -> Dict[str, Any]:
        """List Google Docs documents from Drive."""
        logger.info(f"[GoogleDocsNode] Listing documents")

        url = f"{GOOGLE_DRIVE_API_BASE}/files"

        # Build query for Google Docs
        query_parts = [
            "mimeType='application/vnd.google-apps.document'",
            "trashed=false",
        ]
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
                logger.error(f"[GoogleDocsNode] List documents failed: {error_msg}")
                raise ValueError(f"Google Drive API error: {error_msg}")

            data = response.json()
            files = data.get("files", [])

            documents = []
            for f in files:
                documents.append(
                    {
                        "id": f.get("id"),
                        "name": f.get("name"),
                        "modifiedTime": f.get("modifiedTime"),
                        "createdTime": f.get("createdTime"),
                        "owners": f.get("owners", []),
                    }
                )

            output = {
                "type": "google_docs",
                "operation": "list_google_drive_documents",
                "document_count": len(documents),
                "documents": documents,
                "timestamp": time.time(),
                "status": "success",
            }

            logger.info(f"[GoogleDocsNode] Listed {len(documents)} documents")
            return output

    async def _get_document(
        self, config: GoogleDocsGetDocumentConfig, access_token: str
    ) -> Dict[str, Any]:
        """Get a document."""
        logger.info(f"[GoogleDocsNode] Getting document {config.document_id}")

        url = f"{GOOGLE_DOCS_API_BASE}/{config.document_id}"

        async with httpx.AsyncClient() as client:
            response = await client.get(
                url,
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code != 200:
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", response.text)
                logger.error(f"[GoogleDocsNode] Get document failed: {error_msg}")
                raise ValueError(f"Google Docs API error: {error_msg}")

            doc = response.json()

            result: Dict[str, Any] = {
                "documentId": doc.get("documentId"),
                "title": doc.get("title"),
                "revisionId": doc.get("revisionId"),
            }

            if config.include_content:
                result["plainText"] = self._extract_plain_text(doc)
                result["body"] = doc.get("body")

            output = {
                "type": "google_docs",
                "operation": "fetch_document_content",
                "document": result,
                "timestamp": time.time(),
                "status": "success",
            }

            logger.info(f"[GoogleDocsNode] Retrieved document: {doc.get('title')}")
            return output

    async def _create_document(
        self, config: GoogleDocsCreateDocumentConfig, access_token: str
    ) -> Dict[str, Any]:
        """Create a new document."""
        logger.info(f"[GoogleDocsNode] Creating document: {config.title}")

        url = GOOGLE_DOCS_API_BASE

        async with httpx.AsyncClient() as client:
            # Create the document
            response = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json={"title": config.title},
            )

            if response.status_code not in (200, 201):
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", response.text)
                logger.error(f"[GoogleDocsNode] Create document failed: {error_msg}")
                raise ValueError(f"Google Docs API error: {error_msg}")

            doc = response.json()
            document_id = doc.get("documentId")

            # If initial content provided, insert it
            if config.initial_content:
                batch_url = f"{GOOGLE_DOCS_API_BASE}/{document_id}:batchUpdate"
                batch_response = await client.post(
                    batch_url,
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "requests": [
                            {
                                "insertText": {
                                    "location": {"index": 1},
                                    "text": config.initial_content,
                                }
                            }
                        ]
                    },
                )

                if batch_response.status_code != 200:
                    logger.warning(f"[GoogleDocsNode] Failed to insert initial content")

            output = {
                "type": "google_docs",
                "operation": "create_new_document",
                "document_id": document_id,
                "document": {
                    "documentId": document_id,
                    "title": doc.get("title"),
                    "revisionId": doc.get("revisionId"),
                },
                "timestamp": time.time(),
                "status": "success",
            }

            logger.info(f"[GoogleDocsNode] Created document: {document_id}")
            return output

    async def _append_text(
        self, config: GoogleDocsAppendTextConfig, access_token: str
    ) -> Dict[str, Any]:
        """Append text to a document."""
        logger.info(f"[GoogleDocsNode] Appending text to document {config.document_id}")

        # First get the document to find the end index
        get_url = f"{GOOGLE_DOCS_API_BASE}/{config.document_id}"

        async with httpx.AsyncClient() as client:
            get_response = await client.get(
                get_url,
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if get_response.status_code != 200:
                error_data = get_response.json()
                error_msg = error_data.get("error", {}).get(
                    "message", get_response.text
                )
                logger.error(f"[GoogleDocsNode] Get document failed: {error_msg}")
                raise ValueError(f"Google Docs API error: {error_msg}")

            doc = get_response.json()
            body = doc.get("body", {})
            content = body.get("content", [])

            # Find end index (last element's endIndex - 1 for before final newline)
            end_index = 1
            if content:
                last_element = content[-1]
                end_index = last_element.get("endIndex", 1) - 1

            # Prepare text to insert
            text_to_insert = config.text
            if config.add_newline:
                text_to_insert = "\n" + text_to_insert

            # Batch update to insert text
            batch_url = f"{GOOGLE_DOCS_API_BASE}/{config.document_id}:batchUpdate"
            response = await client.post(
                batch_url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json={
                    "requests": [
                        {
                            "insertText": {
                                "location": {"index": end_index},
                                "text": text_to_insert,
                            }
                        }
                    ]
                },
            )

            if response.status_code != 200:
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", response.text)
                logger.error(f"[GoogleDocsNode] Append text failed: {error_msg}")
                raise ValueError(f"Google Docs API error: {error_msg}")

            output = {
                "type": "google_docs",
                "operation": "append_text_to_document",
                "document_id": config.document_id,
                "text_length": len(config.text),
                "timestamp": time.time(),
                "status": "success",
            }

            logger.info(
                f"[GoogleDocsNode] Appended text to document: {config.document_id}"
            )
            return output

    async def _insert_text(
        self, config: GoogleDocsInsertTextConfig, access_token: str
    ) -> Dict[str, Any]:
        """Insert text at a specific position."""
        logger.info(
            f"[GoogleDocsNode] Inserting text into document {config.document_id}"
        )

        url = f"{GOOGLE_DOCS_API_BASE}/{config.document_id}:batchUpdate"

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json={
                    "requests": [
                        {
                            "insertText": {
                                "location": {"index": config.index},
                                "text": config.text,
                            }
                        }
                    ]
                },
            )

            if response.status_code != 200:
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", response.text)
                logger.error(f"[GoogleDocsNode] Insert text failed: {error_msg}")
                raise ValueError(f"Google Docs API error: {error_msg}")

            output = {
                "type": "google_docs",
                "operation": "insert_text_in_document",
                "document_id": config.document_id,
                "index": config.index,
                "text_length": len(config.text),
                "timestamp": time.time(),
                "status": "success",
            }

            logger.info(f"[GoogleDocsNode] Inserted text at index {config.index}")
            return output

    async def _replace_text(
        self, config: GoogleDocsReplaceTextConfig, access_token: str
    ) -> Dict[str, Any]:
        """Replace text in a document."""
        logger.info(f"[GoogleDocsNode] Replacing text in document {config.document_id}")

        url = f"{GOOGLE_DOCS_API_BASE}/{config.document_id}:batchUpdate"

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json={
                    "requests": [
                        {
                            "replaceAllText": {
                                "containsText": {
                                    "text": config.find_text,
                                    "matchCase": config.match_case,
                                },
                                "replaceText": config.replace_with,
                            }
                        }
                    ]
                },
            )

            if response.status_code != 200:
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", response.text)
                logger.error(f"[GoogleDocsNode] Replace text failed: {error_msg}")
                raise ValueError(f"Google Docs API error: {error_msg}")

            result = response.json()
            replies = result.get("replies", [])
            occurrences_changed = 0
            if replies and "replaceAllText" in replies[0]:
                occurrences_changed = replies[0]["replaceAllText"].get(
                    "occurrencesChanged", 0
                )

            output = {
                "type": "google_docs",
                "operation": "replace_document_text",
                "document_id": config.document_id,
                "find_text": config.find_text,
                "replace_with": config.replace_with,
                "occurrences_changed": occurrences_changed,
                "timestamp": time.time(),
                "status": "success",
            }

            logger.info(f"[GoogleDocsNode] Replaced {occurrences_changed} occurrences")
            return output
