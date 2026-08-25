"""
Mock tests for Google Contacts workflow node.

Tests Google Contacts operations with mocked HTTP responses:
- Contacts: list_contacts, get_contact, create_contact, update_contact, delete_contact, search_contacts
- Contact Groups: list_contact_groups, get_contact_group

Uses httpx mocking to simulate Google People API responses without real credentials.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import httpx

from nodes.google_contacts_node import (
    GoogleContactsNode,
    GoogleContactsNodeConfig,
    GoogleContactsOAuthCredential,
    # Contact operations
    GoogleContactsListContactsConfig,
    GoogleContactsGetContactConfig,
    GoogleContactsCreateContactConfig,
    GoogleContactsUpdateContactConfig,
    GoogleContactsDeleteContactConfig,
    GoogleContactsSearchContactsConfig,
    # Contact Group operations
    GoogleContactsListContactGroupsConfig,
    GoogleContactsGetContactGroupConfig,
)


# ============================================================================
# Test Fixtures
# ============================================================================

TEST_CREDENTIALS = GoogleContactsOAuthCredential(
    access_token="mock_access_token",
    refresh_token="mock_refresh_token",
    expires_at="2099-12-31T23:59:59Z",
    email="test@example.com"
)


def create_node(config) -> GoogleContactsNode:
    """Create a GoogleContactsNode instance with the given config."""
    node_config = GoogleContactsNodeConfig(config=config, credentials=TEST_CREDENTIALS)
    return GoogleContactsNode(
        node_id="test-node",
        node_type="automation-google-contacts",
        node_data={},
        config=node_config,
        sio=None,
        sid=None,
        workflow_id="test-workflow"
    )


def mock_response(status_code: int, json_data: dict = None, text: str = ""):
    """Create a mock httpx.Response."""
    response = MagicMock(spec=httpx.Response)
    response.status_code = status_code
    response.text = text or ""
    response.json.return_value = json_data or {}
    return response


# ============================================================================
# Contact Operations Tests
# ============================================================================

class TestListContacts:
    """Test list_contacts operation."""

    @pytest.mark.asyncio
    async def test_list_contacts_success(self):
        """Test listing contacts returns contacts successfully."""
        config = GoogleContactsListContactsConfig(page_size=100)
        node = create_node(config)

        mock_contacts = {
            "connections": [
                {
                    "resourceName": "people/c1234567890",
                    "etag": "%EgYBAi43PjcuGgQBAgUH",
                    "names": [{"displayName": "John Doe", "givenName": "John", "familyName": "Doe"}],
                    "emailAddresses": [{"value": "john@example.com"}],
                    "phoneNumbers": [{"value": "+1 555-123-4567"}]
                },
                {
                    "resourceName": "people/c9876543210",
                    "etag": "%EgYBAi43PjcuGgQBAgUH",
                    "names": [{"displayName": "Jane Smith", "givenName": "Jane", "familyName": "Smith"}],
                    "emailAddresses": [{"value": "jane@example.com"}]
                }
            ],
            "totalPeople": 2,
            "totalItems": 2
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.get.return_value = mock_response(200, mock_contacts)

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "list_contacts"
            assert result["contact_count"] == 2
            assert len(result["contacts"]) == 2

    @pytest.mark.asyncio
    async def test_list_contacts_empty(self):
        """Test listing contacts when none exist."""
        config = GoogleContactsListContactsConfig()
        node = create_node(config)

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.get.return_value = mock_response(200, {})

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["contact_count"] == 0
            assert result["contacts"] == []


class TestGetContact:
    """Test get_contact operation."""

    @pytest.mark.asyncio
    async def test_get_contact_success(self):
        """Test getting a single contact."""
        config = GoogleContactsGetContactConfig(resource_name="people/c1234567890")
        node = create_node(config)

        mock_contact = {
            "resourceName": "people/c1234567890",
            "etag": "%EgYBAi43PjcuGgQBAgUH",
            "names": [{"displayName": "John Doe", "givenName": "John", "familyName": "Doe"}],
            "emailAddresses": [{"value": "john@example.com", "type": "work"}],
            "phoneNumbers": [{"value": "+1 555-123-4567", "type": "mobile"}],
            "organizations": [{"name": "Acme Inc.", "title": "Engineer"}],
            "biographies": [{"value": "Some notes about John"}]
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.get.return_value = mock_response(200, mock_contact)

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "get_contact"
            assert "contact" in result


class TestCreateContact:
    """Test create_contact operation."""

    @pytest.mark.asyncio
    async def test_create_contact_success(self):
        """Test creating a new contact."""
        config = GoogleContactsCreateContactConfig(
            given_name="Alice",
            family_name="Johnson",
            email="alice@example.com",
            phone="+1 555-987-6543",
            organization="Tech Corp",
            job_title="Developer"
        )
        node = create_node(config)

        mock_created = {
            "resourceName": "people/c1111111111",
            "etag": "%EgYBAi43PjcuGgQBAgUH",
            "names": [{"displayName": "Alice Johnson", "givenName": "Alice", "familyName": "Johnson"}],
            "emailAddresses": [{"value": "alice@example.com"}],
            "phoneNumbers": [{"value": "+1 555-987-6543"}],
            "organizations": [{"name": "Tech Corp", "title": "Developer"}]
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.post.return_value = mock_response(200, mock_created)

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "create_contact"
            assert result["resource_name"] == "people/c1111111111"

    @pytest.mark.asyncio
    async def test_create_contact_minimal(self):
        """Test creating a contact with just a name."""
        config = GoogleContactsCreateContactConfig(given_name="Bob")
        node = create_node(config)

        mock_created = {
            "resourceName": "people/c2222222222",
            "etag": "%EgYBAi43PjcuGgQBAgUH",
            "names": [{"displayName": "Bob", "givenName": "Bob"}]
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.post.return_value = mock_response(200, mock_created)

            result = await node.execute({})

            assert result["status"] == "success"


class TestUpdateContact:
    """Test update_contact operation."""

    @pytest.mark.asyncio
    async def test_update_contact_success(self):
        """Test updating an existing contact."""
        config = GoogleContactsUpdateContactConfig(
            resource_name="people/c1234567890",
            given_name="John",
            family_name="Updated",
            email="john.updated@example.com"
        )
        node = create_node(config)

        mock_current = {
            "resourceName": "people/c1234567890",
            "etag": "%EgYBAi43PjcuGgQBAgUH",
            "names": [{"givenName": "John", "familyName": "Doe"}]
        }
        mock_updated = {
            "resourceName": "people/c1234567890",
            "etag": "%EgYBAi43PjcuGgQBAgUI",
            "names": [{"displayName": "John Updated", "givenName": "John", "familyName": "Updated"}],
            "emailAddresses": [{"value": "john.updated@example.com"}]
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.get.return_value = mock_response(200, mock_current)
            mock_instance.patch.return_value = mock_response(200, mock_updated)

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "update_contact"


class TestDeleteContact:
    """Test delete_contact operation."""

    @pytest.mark.asyncio
    async def test_delete_contact_success(self):
        """Test deleting a contact."""
        config = GoogleContactsDeleteContactConfig(resource_name="people/c1234567890")
        node = create_node(config)

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.delete.return_value = mock_response(200)

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "delete_contact"
            assert result["resource_name"] == "people/c1234567890"


class TestSearchContacts:
    """Test search_contacts operation."""

    @pytest.mark.asyncio
    async def test_search_contacts_success(self):
        """Test searching for contacts."""
        config = GoogleContactsSearchContactsConfig(
            query="john",
            page_size=20
        )
        node = create_node(config)

        mock_results = {
            "results": [
                {
                    "person": {
                        "resourceName": "people/c1234567890",
                        "names": [{"displayName": "John Doe"}],
                        "emailAddresses": [{"value": "john@example.com"}]
                    }
                }
            ]
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.get.return_value = mock_response(200, mock_results)

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "search_contacts"
            assert result["result_count"] == 1

    @pytest.mark.asyncio
    async def test_search_contacts_no_results(self):
        """Test searching with no matching contacts."""
        config = GoogleContactsSearchContactsConfig(query="nonexistent")
        node = create_node(config)

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.get.return_value = mock_response(200, {"results": []})

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["result_count"] == 0


# ============================================================================
# Contact Group Operations Tests
# ============================================================================

class TestListContactGroups:
    """Test list_contact_groups operation."""

    @pytest.mark.asyncio
    async def test_list_contact_groups_success(self):
        """Test listing contact groups."""
        config = GoogleContactsListContactGroupsConfig(page_size=50)
        node = create_node(config)

        mock_groups = {
            "contactGroups": [
                {
                    "resourceName": "contactGroups/family",
                    "etag": "%EgYBAi43PjcuGgQBAgUH",
                    "name": "Family",
                    "memberCount": 5,
                    "groupType": "USER_CONTACT_GROUP"
                },
                {
                    "resourceName": "contactGroups/friends",
                    "etag": "%EgYBAi43PjcuGgQBAgUH",
                    "name": "Friends",
                    "memberCount": 10,
                    "groupType": "USER_CONTACT_GROUP"
                }
            ],
            "totalItems": 2
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.get.return_value = mock_response(200, mock_groups)

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "list_contact_groups"
            assert result["group_count"] == 2
            assert len(result["groups"]) == 2


class TestGetContactGroup:
    """Test get_contact_group operation."""

    @pytest.mark.asyncio
    async def test_get_contact_group_success(self):
        """Test getting a single contact group."""
        config = GoogleContactsGetContactGroupConfig(resource_name="contactGroups/family")
        node = create_node(config)

        mock_group = {
            "resourceName": "contactGroups/family",
            "etag": "%EgYBAi43PjcuGgQBAgUH",
            "name": "Family",
            "memberCount": 5,
            "groupType": "USER_CONTACT_GROUP",
            "memberResourceNames": [
                "people/c1111111111",
                "people/c2222222222"
            ]
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.get.return_value = mock_response(200, mock_group)

            result = await node.execute({})

            assert result["status"] == "success"
            assert result["operation"] == "get_contact_group"
            assert "group" in result


# ============================================================================
# Error Handling Tests
# ============================================================================

class TestErrorHandling:
    """Test error handling scenarios."""

    @pytest.mark.asyncio
    async def test_api_error_not_found(self):
        """Test handling of 404 errors."""
        config = GoogleContactsGetContactConfig(resource_name="people/nonexistent")
        node = create_node(config)

        error_response = {
            "error": {
                "code": 404,
                "message": "Contact not found"
            }
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.get.return_value = mock_response(404, error_response, "Contact not found")

            with pytest.raises(Exception) as exc_info:
                await node.execute({})

            assert "404" in str(exc_info.value) or "not found" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_api_error_rate_limit(self):
        """Test handling of rate limit errors."""
        config = GoogleContactsListContactsConfig()
        node = create_node(config)

        error_response = {
            "error": {
                "code": 429,
                "message": "Rate limit exceeded"
            }
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.get.return_value = mock_response(429, error_response, "Rate limit exceeded")

            with pytest.raises(Exception) as exc_info:
                await node.execute({})

            assert "429" in str(exc_info.value) or "rate" in str(exc_info.value).lower()


# ============================================================================
# Dynamic Field Options Tests
# ============================================================================

class TestDynamicFieldOptions:
    """Test dynamic field options loading."""

    @pytest.mark.asyncio
    async def test_load_contact_group_options(self):
        """Test loading contact group options for dropdown."""
        credential_data = {
            "access_token": "mock_token",
            "refresh_token": "mock_refresh",
            "expires_at": "2099-12-31T23:59:59Z",
            "email": "test@example.com"
        }

        mock_groups = {
            "contactGroups": [
                {"resourceName": "contactGroups/family", "name": "Family"},
                {"resourceName": "contactGroups/friends", "name": "Friends"}
            ]
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.get.return_value = mock_response(200, mock_groups)

            result = await GoogleContactsNode.load_field_options(
                "contact_group_id",
                credential_data,
                None
            )

            # Dynamic options return a list
            assert isinstance(result, list)
