"""
Google Contacts workflow node implementation.
Enables managing contacts via Google People API with OAuth credentials.

Supports 8 operations:
- Contacts: list_contacts, get_contact, create_contact, update_contact, delete_contact, search_contacts
- Contact Groups: list_contact_groups, get_contact_group
"""

import time
import logging
from typing import Dict, Any, Optional, Union, Type, List, Literal, Annotated
from pydantic import BaseModel, ConfigDict, Discriminator, Field
import httpx

from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.oauth.google_oauth import is_token_expired, refresh_access_token
from nodes.scopes.google import GOOGLE_CONTACTS_SCOPES

logger = logging.getLogger(__name__)

GOOGLE_PEOPLE_API_BASE = "https://people.googleapis.com/v1"


# ============================================================================
# Google Contacts Node Credential Schema
# ============================================================================


class GoogleContactsOAuthCredential(BaseModel):
    """
    OAuth credential for Google Contacts access.
    Tokens are obtained via OAuth flow, not entered manually.
    """

    credential_type: Literal["google_contacts_oauth"] = Field(
        "google_contacts_oauth", json_schema_extra={"ui:hidden": True}
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
        "x-oauth-scopes": ["https://www.googleapis.com/auth/contacts"],
    })


# ============================================================================
# Google Contacts Node Configuration Models
# ============================================================================


class GoogleContactsListContactsConfig(BaseModel):
    """Configuration for listing contacts"""

    operation: Literal["list_contacts"] = Field(
        "list_contacts",
        title="List Contacts",
        description="List all contacts",
        json_schema_extra={
            "ui:hidden": True,
            "const": "list_contacts",
            "x-category": "Contact",
            "x-is-trigger": False,
            "x-display-name": "List Contacts",
        },
    )
    page_size: Optional[int] = Field(
        100,
        title="Page Size",
        description="Maximum number of contacts to return (1-1000)",
        ge=1,
        le=1000,
    )
    sort_order: Optional[
        Literal[
            "LAST_MODIFIED_ASCENDING",
            "LAST_MODIFIED_DESCENDING",
            "FIRST_NAME_ASCENDING",
            "LAST_NAME_ASCENDING",
        ]
    ] = Field(None, title="Sort Order", description="How to sort the contacts")


class GoogleContactsGetContactConfig(BaseModel):
    """Configuration for getting a single contact"""

    operation: Literal["get_contact"] = Field(
        "get_contact",
        title="Get Contact",
        description="Get a specific contact",
        json_schema_extra={
            "ui:hidden": True,
            "const": "get_contact",
            "x-category": "Contact",
            "x-is-trigger": False,
            "x-display-name": "Get Contact",
        },
    )
    resource_name: str = Field(
        ...,
        title="Contact Resource Name",
        description="The resource name of the contact (e.g., 'people/c1234567890')",
        json_schema_extra={"placeholder": "people/c1234567890"},
    )


class GoogleContactsCreateContactConfig(BaseModel):
    """Configuration for creating a new contact"""

    operation: Literal["create_contact"] = Field(
        "create_contact",
        title="Create Contact",
        description="Create a new contact",
        json_schema_extra={
            "ui:hidden": True,
            "const": "create_contact",
            "x-category": "Contact",
            "x-is-trigger": False,
            "x-display-name": "Create Contact",
        },
    )
    given_name: str = Field(
        ...,
        title="First Name",
        description="Contact's first/given name",
        json_schema_extra={"placeholder": "John"},
    )
    family_name: Optional[str] = Field(
        None,
        title="Last Name",
        description="Contact's last/family name",
        json_schema_extra={"placeholder": "Doe (optional)"},
    )
    email: Optional[str] = Field(
        None,
        title="Email",
        description="Contact's email address",
        json_schema_extra={"placeholder": "john@example.com (optional)"},
    )
    phone: Optional[str] = Field(
        None,
        title="Phone",
        description="Contact's phone number",
        json_schema_extra={"placeholder": "+1 555-123-4567 (optional)"},
    )
    organization: Optional[str] = Field(
        None,
        title="Organization",
        description="Contact's company or organization",
        json_schema_extra={"placeholder": "Acme Inc. (optional)"},
    )
    job_title: Optional[str] = Field(
        None,
        title="Job Title",
        description="Contact's job title",
        json_schema_extra={"placeholder": "Software Engineer (optional)"},
    )
    notes: Optional[str] = Field(
        None,
        title="Notes",
        description="Additional notes about the contact",
        json_schema_extra={
            "ui:widget": "textarea",
            "placeholder": "Notes about the contact... (optional)",
        },
    )


class GoogleContactsUpdateContactConfig(BaseModel):
    """Configuration for updating a contact"""

    operation: Literal["update_contact"] = Field(
        "update_contact",
        title="Update Contact",
        description="Update a contact",
        json_schema_extra={
            "ui:hidden": True,
            "const": "update_contact",
            "x-category": "Contact",
            "x-is-trigger": False,
            "x-display-name": "Update Contact",
        },
    )
    resource_name: str = Field(
        ...,
        title="Contact Resource Name",
        description="The resource name of the contact to update",
        json_schema_extra={"placeholder": "people/c1234567890"},
    )
    given_name: Optional[str] = Field(
        None,
        title="First Name",
        description="New first name (leave empty to keep current)",
        json_schema_extra={"placeholder": "New first name (optional)"},
    )
    family_name: Optional[str] = Field(
        None,
        title="Last Name",
        description="New last name (leave empty to keep current)",
        json_schema_extra={"placeholder": "New last name (optional)"},
    )
    email: Optional[str] = Field(
        None,
        title="Email",
        description="New email address (leave empty to keep current)",
        json_schema_extra={"placeholder": "new@example.com (optional)"},
    )
    phone: Optional[str] = Field(
        None,
        title="Phone",
        description="New phone number (leave empty to keep current)",
        json_schema_extra={"placeholder": "+1 555-123-4567 (optional)"},
    )
    organization: Optional[str] = Field(
        None,
        title="Organization",
        description="New organization (leave empty to keep current)",
        json_schema_extra={"placeholder": "New company (optional)"},
    )
    job_title: Optional[str] = Field(
        None,
        title="Job Title",
        description="New job title (leave empty to keep current)",
        json_schema_extra={"placeholder": "New title (optional)"},
    )


class GoogleContactsDeleteContactConfig(BaseModel):
    """Configuration for deleting a contact"""

    operation: Literal["delete_contact"] = Field(
        "delete_contact",
        title="Delete Contact",
        description="Delete a contact",
        json_schema_extra={
            "ui:hidden": True,
            "const": "delete_contact",
            "x-category": "Contact",
            "x-is-trigger": False,
            "x-display-name": "Delete Contact",
        },
    )
    resource_name: str = Field(
        ...,
        title="Contact Resource Name",
        description="The resource name of the contact to delete",
        json_schema_extra={"placeholder": "people/c1234567890"},
    )


class GoogleContactsSearchContactsConfig(BaseModel):
    """Configuration for searching contacts"""

    operation: Literal["search_contacts"] = Field(
        "search_contacts",
        title="Search Contacts",
        description="Search contacts",
        json_schema_extra={
            "ui:hidden": True,
            "const": "search_contacts",
            "x-category": "Contact",
            "x-is-trigger": False,
            "x-display-name": "Search Contacts",
        },
    )
    query: str = Field(
        ...,
        title="Search Query",
        description="Search term to find contacts (searches names, email addresses, phone numbers)",
        json_schema_extra={"placeholder": "John Doe or john@example.com"},
    )
    page_size: Optional[int] = Field(
        30,
        title="Page Size",
        description="Maximum number of results to return (1-30)",
        ge=1,
        le=30,
    )


class GoogleContactsListContactGroupsConfig(BaseModel):
    """Configuration for listing contact groups"""

    operation: Literal["list_contact_groups"] = Field(
        "list_contact_groups",
        title="List Contact Groups",
        description="List all contact groups",
        json_schema_extra={
            "ui:hidden": True,
            "const": "list_contact_groups",
            "x-category": "Contact Group",
            "x-is-trigger": False,
            "x-display-name": "List Contact Groups",
        },
    )
    page_size: Optional[int] = Field(
        100,
        title="Page Size",
        description="Maximum number of groups to return (1-1000)",
        ge=1,
        le=1000,
    )


class GoogleContactsGetContactGroupConfig(BaseModel):
    """Configuration for getting a contact group"""

    operation: Literal["get_contact_group"] = Field(
        "get_contact_group",
        title="Get Contact Group",
        description="Get a specific contact group",
        json_schema_extra={
            "ui:hidden": True,
            "const": "get_contact_group",
            "x-category": "Contact Group",
            "x-is-trigger": False,
            "x-display-name": "Get Contact Group",
        },
    )
    resource_name: str = Field(
        ...,
        title="Group Resource Name",
        description="The resource name of the contact group",
        json_schema_extra={"placeholder": "contactGroups/abc123"},
    )


class GoogleContactsCreateContactGroupConfig(BaseModel):
    """Configuration for creating a contact group"""

    operation: Literal["create_contact_group"] = Field(
        "create_contact_group",
        title="Create Contact Group",
        description="Create a new contact group",
        json_schema_extra={
            "ui:hidden": True,
            "const": "create_contact_group",
            "x-category": "Contact Group",
            "x-is-trigger": False,
            "x-display-name": "Create Contact Group",
        },
    )
    name: str = Field(
        ...,
        title="Group Name",
        description="Name for the new contact group",
        json_schema_extra={"placeholder": "My Group"},
    )


class GoogleContactsUpdateContactGroupConfig(BaseModel):
    """Configuration for updating a contact group"""

    operation: Literal["update_contact_group"] = Field(
        "update_contact_group",
        title="Update Contact Group",
        description="Update a contact group",
        json_schema_extra={
            "ui:hidden": True,
            "const": "update_contact_group",
            "x-category": "Contact Group",
            "x-is-trigger": False,
            "x-display-name": "Update Contact Group",
        },
    )
    resource_name: str = Field(
        ...,
        title="Group Resource Name",
        description="The resource name of the contact group to update",
        json_schema_extra={"placeholder": "contactGroups/abc123"},
    )
    name: str = Field(
        ...,
        title="New Name",
        description="New name for the contact group",
        json_schema_extra={"placeholder": "Updated Group Name"},
    )


class GoogleContactsDeleteContactGroupConfig(BaseModel):
    """Configuration for deleting a contact group"""

    operation: Literal["delete_contact_group"] = Field(
        "delete_contact_group",
        title="Delete Contact Group",
        description="Delete a contact group",
        json_schema_extra={
            "ui:hidden": True,
            "const": "delete_contact_group",
            "x-category": "Contact Group",
            "x-is-trigger": False,
            "x-display-name": "Delete Contact Group",
        },
    )
    resource_name: str = Field(
        ...,
        title="Group Resource Name",
        description="The resource name of the contact group to delete",
        json_schema_extra={"placeholder": "contactGroups/abc123"},
    )
    delete_contacts: Optional[bool] = Field(
        False, title="Delete Contacts", description="Also delete contacts in the group"
    )


# Union of all config types for oneOf schema
GoogleContactsConfig = Annotated[
    Union[
        GoogleContactsListContactsConfig,
        GoogleContactsGetContactConfig,
        GoogleContactsCreateContactConfig,
        GoogleContactsUpdateContactConfig,
        GoogleContactsDeleteContactConfig,
        GoogleContactsSearchContactsConfig,
        GoogleContactsListContactGroupsConfig,
        GoogleContactsGetContactGroupConfig,
        GoogleContactsCreateContactGroupConfig,
        GoogleContactsUpdateContactGroupConfig,
        GoogleContactsDeleteContactGroupConfig,
    ],
    Discriminator("operation"),
]


class GoogleContactsNodeConfig(
    NodeConfig[GoogleContactsConfig, GoogleContactsOAuthCredential]
):
    """Full configuration for Google Contacts node including credentials"""

    pass


# ============================================================================
# Google Contacts Node Implementation
# ============================================================================


class GoogleContactsNode(WorkflowNode):
    """
    Google Contacts workflow node for managing contacts via Google People API.
    """

    # Standard person fields to request from the API
    PERSON_FIELDS = (
        "names,emailAddresses,phoneNumbers,organizations,biographies,metadata"
    )

    edit_examples = [
        "Add new contact Sarah Chen from Acme Inc with phone and email",
        "Search for all contacts in Sales department and get their details",
        'Create a team contact group "Q2 Partners" with 15 vendor contacts',
        "Update contact job title for everyone promoted this quarter",
        "Get all contacts from the Engineering group and export their emails",
        "Delete duplicate contacts and merge info into primary contact",
        "List all contact groups and get member counts for organization chart",
    ]

    scope_registry = GOOGLE_CONTACTS_SCOPES
    connection_evidence = ConnectionEvidence(
        operation="list_contacts",
        noun="contacts",
    )

    @classmethod
    def get_config_model(cls) -> Optional[Union[Type, type]]:
        """Get Pydantic config model for Google Contacts node"""
        return GoogleContactsNodeConfig

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
        logger.info(
            f"[GoogleContactsNode] load_field_options called: field={field_name}"
        )
        # Could implement contact group dropdown here if needed
        return []

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Execute Google Contacts operation."""
        logger.info(f"[GoogleContactsNode] Executing node {self.node_id}")

        node_config = self.config
        if not node_config:
            raise ValueError(
                f"[GoogleContactsNode] Configuration is required but not provided for node {self.node_id}"
            )

        if not isinstance(node_config, GoogleContactsNodeConfig):
            raise ValueError(
                f"[GoogleContactsNode] Invalid config type: {type(node_config)}, expected GoogleContactsNodeConfig"
            )

        config = node_config.config
        credentials = node_config.credentials

        if not credentials:
            raise ValueError(
                f"[GoogleContactsNode] Google Contacts credentials are required but not provided. "
                f"Please connect a Google account in the node's credentials tab."
            )

        access_token = await self._ensure_fresh_token(credentials)

        # Execute operation based on config type
        if isinstance(config, GoogleContactsListContactsConfig):
            output = await self._list_contacts(config, access_token)
        elif isinstance(config, GoogleContactsGetContactConfig):
            output = await self._get_contact(config, access_token)
        elif isinstance(config, GoogleContactsCreateContactConfig):
            output = await self._create_contact(config, access_token)
        elif isinstance(config, GoogleContactsUpdateContactConfig):
            output = await self._update_contact(config, access_token)
        elif isinstance(config, GoogleContactsDeleteContactConfig):
            output = await self._delete_contact(config, access_token)
        elif isinstance(config, GoogleContactsSearchContactsConfig):
            output = await self._search_contacts(config, access_token)
        elif isinstance(config, GoogleContactsListContactGroupsConfig):
            output = await self._list_contact_groups(config, access_token)
        elif isinstance(config, GoogleContactsGetContactGroupConfig):
            output = await self._get_contact_group(config, access_token)
        elif isinstance(config, GoogleContactsCreateContactGroupConfig):
            output = await self._create_contact_group(config, access_token)
        elif isinstance(config, GoogleContactsUpdateContactGroupConfig):
            output = await self._update_contact_group(config, access_token)
        elif isinstance(config, GoogleContactsDeleteContactGroupConfig):
            output = await self._delete_contact_group(config, access_token)
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

    async def _ensure_fresh_token(
        self, credentials: GoogleContactsOAuthCredential
    ) -> str:
        """Return a valid Google Contacts access token, refreshing + persisting if expired."""
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

    def _simplify_contact(self, person: Dict[str, Any]) -> Dict[str, Any]:
        """Extract simplified contact info from a People API person resource."""
        names = person.get("names", [])
        emails = person.get("emailAddresses", [])
        phones = person.get("phoneNumbers", [])
        orgs = person.get("organizations", [])
        bios = person.get("biographies", [])

        return {
            "resourceName": person.get("resourceName"),
            "etag": person.get("etag"),
            "name": {
                "givenName": names[0].get("givenName") if names else None,
                "familyName": names[0].get("familyName") if names else None,
                "displayName": names[0].get("displayName") if names else None,
            }
            if names
            else None,
            "emails": [
                {"value": e.get("value"), "type": e.get("type")} for e in emails
            ],
            "phones": [
                {"value": p.get("value"), "type": p.get("type")} for p in phones
            ],
            "organization": {
                "name": orgs[0].get("name"),
                "title": orgs[0].get("title"),
            }
            if orgs
            else None,
            "notes": bios[0].get("value") if bios else None,
        }

    async def _list_contacts(
        self, config: GoogleContactsListContactsConfig, access_token: str
    ) -> Dict[str, Any]:
        """List all contacts."""
        logger.info(f"[GoogleContactsNode] Listing contacts")

        url = f"{GOOGLE_PEOPLE_API_BASE}/people/me/connections"
        params: Dict[str, Any] = {
            "personFields": self.PERSON_FIELDS,
        }

        if config.page_size:
            params["pageSize"] = config.page_size
        if config.sort_order:
            params["sortOrder"] = config.sort_order

        async with httpx.AsyncClient() as client:
            response = await client.get(
                url, headers={"Authorization": f"Bearer {access_token}"}, params=params
            )

            if response.status_code != 200:
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", response.text)
                logger.error(f"[GoogleContactsNode] List contacts failed: {error_msg}")
                raise ValueError(f"Google People API error: {error_msg}")

            data = response.json()
            connections = data.get("connections", [])

            contacts = [self._simplify_contact(c) for c in connections]

            output = {
                "type": "google_contacts",
                "operation": "list_contacts",
                "contact_count": len(contacts),
                "total_people": data.get("totalPeople"),
                "contacts": contacts,
                "timestamp": time.time(),
                "status": "success",
            }

            logger.info(f"[GoogleContactsNode] Listed {len(contacts)} contacts")
            return output

    async def _get_contact(
        self, config: GoogleContactsGetContactConfig, access_token: str
    ) -> Dict[str, Any]:
        """Get a single contact."""
        logger.info(f"[GoogleContactsNode] Getting contact {config.resource_name}")

        url = f"{GOOGLE_PEOPLE_API_BASE}/{config.resource_name}"
        params = {"personFields": self.PERSON_FIELDS}

        async with httpx.AsyncClient() as client:
            response = await client.get(
                url, headers={"Authorization": f"Bearer {access_token}"}, params=params
            )

            if response.status_code != 200:
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", response.text)
                logger.error(f"[GoogleContactsNode] Get contact failed: {error_msg}")
                raise ValueError(f"Google People API error: {error_msg}")

            person = response.json()

            output = {
                "type": "google_contacts",
                "operation": "get_contact",
                "contact": self._simplify_contact(person),
                "timestamp": time.time(),
                "status": "success",
            }

            logger.info(
                f"[GoogleContactsNode] Retrieved contact: {config.resource_name}"
            )
            return output

    async def _create_contact(
        self, config: GoogleContactsCreateContactConfig, access_token: str
    ) -> Dict[str, Any]:
        """Create a new contact."""
        logger.info(f"[GoogleContactsNode] Creating contact: {config.given_name}")

        url = f"{GOOGLE_PEOPLE_API_BASE}/people:createContact"

        # Build the person resource
        person: Dict[str, Any] = {
            "names": [
                {
                    "givenName": config.given_name,
                }
            ]
        }

        if config.family_name:
            person["names"][0]["familyName"] = config.family_name

        if config.email:
            person["emailAddresses"] = [{"value": config.email}]

        if config.phone:
            person["phoneNumbers"] = [{"value": config.phone}]

        if config.organization or config.job_title:
            person["organizations"] = [{}]
            if config.organization:
                person["organizations"][0]["name"] = config.organization
            if config.job_title:
                person["organizations"][0]["title"] = config.job_title

        if config.notes:
            person["biographies"] = [
                {"value": config.notes, "contentType": "TEXT_PLAIN"}
            ]

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json=person,
            )

            if response.status_code not in (200, 201):
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", response.text)
                logger.error(f"[GoogleContactsNode] Create contact failed: {error_msg}")
                raise ValueError(f"Google People API error: {error_msg}")

            created = response.json()

            output = {
                "type": "google_contacts",
                "operation": "create_contact",
                "resource_name": created.get("resourceName"),
                "contact": self._simplify_contact(created),
                "timestamp": time.time(),
                "status": "success",
            }

            logger.info(
                f"[GoogleContactsNode] Created contact: {created.get('resourceName')}"
            )
            return output

    async def _update_contact(
        self, config: GoogleContactsUpdateContactConfig, access_token: str
    ) -> Dict[str, Any]:
        """Update a contact."""
        logger.info(f"[GoogleContactsNode] Updating contact {config.resource_name}")

        # First get the existing contact
        get_url = f"{GOOGLE_PEOPLE_API_BASE}/{config.resource_name}"
        get_params = {"personFields": self.PERSON_FIELDS}

        async with httpx.AsyncClient() as client:
            get_response = await client.get(
                get_url,
                headers={"Authorization": f"Bearer {access_token}"},
                params=get_params,
            )

            if get_response.status_code != 200:
                error_data = get_response.json()
                error_msg = error_data.get("error", {}).get(
                    "message", get_response.text
                )
                logger.error(
                    f"[GoogleContactsNode] Get contact for update failed: {error_msg}"
                )
                raise ValueError(f"Google People API error: {error_msg}")

            existing = get_response.json()
            etag = existing.get("etag")

            # Build update fields
            update_person: Dict[str, Any] = {"etag": etag}
            update_fields = []

            if config.given_name or config.family_name:
                update_person["names"] = existing.get("names", [{}])
                if not update_person["names"]:
                    update_person["names"] = [{}]
                if config.given_name:
                    update_person["names"][0]["givenName"] = config.given_name
                if config.family_name:
                    update_person["names"][0]["familyName"] = config.family_name
                update_fields.append("names")

            if config.email:
                update_person["emailAddresses"] = [{"value": config.email}]
                update_fields.append("emailAddresses")

            if config.phone:
                update_person["phoneNumbers"] = [{"value": config.phone}]
                update_fields.append("phoneNumbers")

            if config.organization or config.job_title:
                update_person["organizations"] = existing.get("organizations", [{}])
                if not update_person["organizations"]:
                    update_person["organizations"] = [{}]
                if config.organization:
                    update_person["organizations"][0]["name"] = config.organization
                if config.job_title:
                    update_person["organizations"][0]["title"] = config.job_title
                update_fields.append("organizations")

            if not update_fields:
                raise ValueError("At least one field must be provided to update")

            update_url = (
                f"{GOOGLE_PEOPLE_API_BASE}/{config.resource_name}:updateContact"
            )
            params = {"updatePersonFields": ",".join(update_fields)}

            response = await client.patch(
                update_url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                params=params,
                json=update_person,
            )

            if response.status_code != 200:
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", response.text)
                logger.error(f"[GoogleContactsNode] Update contact failed: {error_msg}")
                raise ValueError(f"Google People API error: {error_msg}")

            updated = response.json()

            output = {
                "type": "google_contacts",
                "operation": "update_contact",
                "resource_name": updated.get("resourceName"),
                "contact": self._simplify_contact(updated),
                "timestamp": time.time(),
                "status": "success",
            }

            logger.info(
                f"[GoogleContactsNode] Updated contact: {updated.get('resourceName')}"
            )
            return output

    async def _delete_contact(
        self, config: GoogleContactsDeleteContactConfig, access_token: str
    ) -> Dict[str, Any]:
        """Delete a contact."""
        logger.info(f"[GoogleContactsNode] Deleting contact {config.resource_name}")

        url = f"{GOOGLE_PEOPLE_API_BASE}/{config.resource_name}:deleteContact"

        async with httpx.AsyncClient() as client:
            response = await client.delete(
                url,
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code not in (200, 204):
                error_data = response.json() if response.text else {}
                error_msg = error_data.get("error", {}).get("message", response.text)
                logger.error(f"[GoogleContactsNode] Delete contact failed: {error_msg}")
                raise ValueError(f"Google People API error: {error_msg}")

            output = {
                "type": "google_contacts",
                "operation": "delete_contact",
                "resource_name": config.resource_name,
                "timestamp": time.time(),
                "status": "success",
            }

            logger.info(f"[GoogleContactsNode] Deleted contact: {config.resource_name}")
            return output

    async def _search_contacts(
        self, config: GoogleContactsSearchContactsConfig, access_token: str
    ) -> Dict[str, Any]:
        """Search contacts."""
        logger.info(f"[GoogleContactsNode] Searching contacts: {config.query}")

        url = f"{GOOGLE_PEOPLE_API_BASE}/people:searchContacts"
        params: Dict[str, Any] = {
            "query": config.query,
            "readMask": self.PERSON_FIELDS,
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
                logger.error(
                    f"[GoogleContactsNode] Search contacts failed: {error_msg}"
                )
                raise ValueError(f"Google People API error: {error_msg}")

            data = response.json()
            results = data.get("results", [])

            contacts = []
            for result in results:
                person = result.get("person", {})
                contacts.append(self._simplify_contact(person))

            output = {
                "type": "google_contacts",
                "operation": "search_contacts",
                "query": config.query,
                "result_count": len(contacts),
                "contacts": contacts,
                "timestamp": time.time(),
                "status": "success",
            }

            logger.info(
                f"[GoogleContactsNode] Found {len(contacts)} contacts matching '{config.query}'"
            )
            return output

    async def _list_contact_groups(
        self, config: GoogleContactsListContactGroupsConfig, access_token: str
    ) -> Dict[str, Any]:
        """List all contact groups."""
        logger.info(f"[GoogleContactsNode] Listing contact groups")

        url = f"{GOOGLE_PEOPLE_API_BASE}/contactGroups"
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
                logger.error(
                    f"[GoogleContactsNode] List contact groups failed: {error_msg}"
                )
                raise ValueError(f"Google People API error: {error_msg}")

            data = response.json()
            contact_groups = data.get("contactGroups", [])

            groups = []
            for g in contact_groups:
                groups.append(
                    {
                        "resourceName": g.get("resourceName"),
                        "name": g.get("name"),
                        "formattedName": g.get("formattedName"),
                        "groupType": g.get("groupType"),
                        "memberCount": g.get("memberCount"),
                    }
                )

            output = {
                "type": "google_contacts",
                "operation": "list_contact_groups",
                "group_count": len(groups),
                "groups": groups,
                "timestamp": time.time(),
                "status": "success",
            }

            logger.info(f"[GoogleContactsNode] Listed {len(groups)} contact groups")
            return output

    async def _get_contact_group(
        self, config: GoogleContactsGetContactGroupConfig, access_token: str
    ) -> Dict[str, Any]:
        """Get a contact group."""
        logger.info(
            f"[GoogleContactsNode] Getting contact group {config.resource_name}"
        )

        url = f"{GOOGLE_PEOPLE_API_BASE}/{config.resource_name}"
        params = {"maxMembers": 1000}

        async with httpx.AsyncClient() as client:
            response = await client.get(
                url, headers={"Authorization": f"Bearer {access_token}"}, params=params
            )

            if response.status_code != 200:
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", response.text)
                logger.error(
                    f"[GoogleContactsNode] Get contact group failed: {error_msg}"
                )
                raise ValueError(f"Google People API error: {error_msg}")

            g = response.json()

            output = {
                "type": "google_contacts",
                "operation": "get_contact_group",
                "group": {
                    "resourceName": g.get("resourceName"),
                    "name": g.get("name"),
                    "formattedName": g.get("formattedName"),
                    "groupType": g.get("groupType"),
                    "memberCount": g.get("memberCount"),
                    "memberResourceNames": g.get("memberResourceNames", []),
                },
                "timestamp": time.time(),
                "status": "success",
            }

            logger.info(
                f"[GoogleContactsNode] Retrieved contact group: {g.get('name')}"
            )
            return output

    async def _create_contact_group(
        self, config: GoogleContactsCreateContactGroupConfig, access_token: str
    ) -> Dict[str, Any]:
        """Create a new contact group."""
        logger.info(f"[GoogleContactsNode] Creating contact group: {config.name}")

        url = f"{GOOGLE_PEOPLE_API_BASE}/contactGroups"
        body = {"contactGroup": {"name": config.name}}

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json=body,
            )

            if response.status_code not in (200, 201):
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", response.text)
                logger.error(
                    f"[GoogleContactsNode] Create contact group failed: {error_msg}"
                )
                raise ValueError(f"Google People API error: {error_msg}")

            g = response.json()

            output = {
                "type": "google_contacts",
                "operation": "create_contact_group",
                "group": {
                    "resourceName": g.get("resourceName"),
                    "name": g.get("name"),
                    "formattedName": g.get("formattedName"),
                    "groupType": g.get("groupType"),
                },
                "timestamp": time.time(),
                "status": "success",
            }

            logger.info(
                f"[GoogleContactsNode] Created contact group: {g.get('resourceName')}"
            )
            return output

    async def _update_contact_group(
        self, config: GoogleContactsUpdateContactGroupConfig, access_token: str
    ) -> Dict[str, Any]:
        """Update a contact group name."""
        logger.info(
            f"[GoogleContactsNode] Updating contact group {config.resource_name}"
        )

        url = f"{GOOGLE_PEOPLE_API_BASE}/{config.resource_name}"
        body = {"contactGroup": {"name": config.name}}

        async with httpx.AsyncClient() as client:
            response = await client.put(
                url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json=body,
            )

            if response.status_code != 200:
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", response.text)
                logger.error(
                    f"[GoogleContactsNode] Update contact group failed: {error_msg}"
                )
                raise ValueError(f"Google People API error: {error_msg}")

            g = response.json()

            output = {
                "type": "google_contacts",
                "operation": "update_contact_group",
                "group": {
                    "resourceName": g.get("resourceName"),
                    "name": g.get("name"),
                    "formattedName": g.get("formattedName"),
                    "groupType": g.get("groupType"),
                },
                "timestamp": time.time(),
                "status": "success",
            }

            logger.info(
                f"[GoogleContactsNode] Updated contact group: {g.get('resourceName')}"
            )
            return output

    async def _delete_contact_group(
        self, config: GoogleContactsDeleteContactGroupConfig, access_token: str
    ) -> Dict[str, Any]:
        """Delete a contact group."""
        logger.info(
            f"[GoogleContactsNode] Deleting contact group {config.resource_name}"
        )

        url = f"{GOOGLE_PEOPLE_API_BASE}/{config.resource_name}"
        params = {}
        if config.delete_contacts:
            params["deleteContacts"] = "true"

        async with httpx.AsyncClient() as client:
            response = await client.delete(
                url, headers={"Authorization": f"Bearer {access_token}"}, params=params
            )

            if response.status_code not in (200, 204):
                error_data = response.json() if response.text else {}
                error_msg = error_data.get("error", {}).get("message", response.text)
                logger.error(
                    f"[GoogleContactsNode] Delete contact group failed: {error_msg}"
                )
                raise ValueError(f"Google People API error: {error_msg}")

            output = {
                "type": "google_contacts",
                "operation": "delete_contact_group",
                "resource_name": config.resource_name,
                "delete_contacts": config.delete_contacts,
                "timestamp": time.time(),
                "status": "success",
            }

            logger.info(
                f"[GoogleContactsNode] Deleted contact group: {config.resource_name}"
            )
            return output
