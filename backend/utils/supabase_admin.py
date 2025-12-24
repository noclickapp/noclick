"""
Supabase Admin API client for SSO provider management.
Uses SUPABASE_SECRET_KEY to manage SAML SSO providers via the Supabase Auth Admin API.

This module provides functions to create, read, update, and delete SSO identity providers
which allows enterprise customers to self-configure their SAML SSO settings.
"""

import os
import logging
import httpx
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class SSOProvider:
    """Represents a SAML SSO identity provider configuration."""
    id: str
    type: str  # 'saml'
    domains: List[str]
    metadata_url: Optional[str] = None
    entity_id: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    saml_config: Dict[str, Any] = field(default_factory=dict)


class SupabaseAdminError(Exception):
    """Exception raised for Supabase Admin API errors."""

    def __init__(self, message: str, status_code: Optional[int] = None, response_body: Optional[str] = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


class SupabaseAdminClient:
    """
    Client for Supabase Auth Admin API (SSO management).

    Uses SUPABASE_SECRET_KEY for admin operations like creating/managing
    SSO identity providers for enterprise customers.
    """

    def __init__(self, base_url: Optional[str] = None, secret_key: Optional[str] = None):
        """
        Initialize the Supabase Admin client.

        Args:
            base_url: Supabase project URL (defaults to SUPABASE_URL env var)
            secret_key: Supabase secret key (defaults to SUPABASE_SECRET_KEY env var)
        """
        self.base_url = base_url or os.getenv('SUPABASE_URL')
        self.secret_key = secret_key or os.getenv('SUPABASE_SECRET_KEY')

        if not self.base_url:
            raise ValueError("SUPABASE_URL is required")
        if not self.secret_key:
            raise ValueError("SUPABASE_SECRET_KEY is required for Admin API operations")

        # Remove trailing slash from base URL
        self.base_url = self.base_url.rstrip('/')

    @property
    def _headers(self) -> Dict[str, str]:
        """Get headers for Admin API requests."""
        return {
            'Authorization': f'Bearer {self.secret_key}',
            'apikey': self.secret_key,
            'Content-Type': 'application/json'
        }

    def _parse_provider(self, data: Dict[str, Any]) -> SSOProvider:
        """Parse API response into SSOProvider object."""
        saml_config = data.get('saml', {})
        return SSOProvider(
            id=data['id'],
            type=data.get('type', 'saml'),
            domains=data.get('domains', []),
            metadata_url=saml_config.get('metadata_url'),
            entity_id=saml_config.get('entity_id'),
            created_at=data.get('created_at'),
            updated_at=data.get('updated_at'),
            saml_config=saml_config
        )

    async def create_sso_provider(
        self,
        metadata_url: str,
        domains: List[str],
        attribute_mapping: Optional[Dict[str, Any]] = None
    ) -> SSOProvider:
        """
        Create a new SAML SSO provider in Supabase.

        This registers an identity provider that users with matching email domains
        will be redirected to for authentication.

        Args:
            metadata_url: IdP SAML metadata URL (e.g., https://company.okta.com/app/.../sso/saml/metadata)
            domains: Email domains to associate (e.g., ['acme.com', 'acme.co.uk'])
            attribute_mapping: Optional SAML attribute mapping for user properties

        Returns:
            Created SSOProvider with Supabase-assigned ID

        Raises:
            SupabaseAdminError: If the API request fails
        """
        async with httpx.AsyncClient() as client:
            payload: Dict[str, Any] = {
                'type': 'saml',
                'metadata_url': metadata_url,
                'domains': domains
            }

            if attribute_mapping:
                payload['attribute_mapping'] = attribute_mapping

            logger.info(f"[SupabaseAdmin] Creating SSO provider for domains: {domains}")

            try:
                response = await client.post(
                    f'{self.base_url}/auth/v1/admin/sso/providers',
                    headers=self._headers,
                    json=payload,
                    timeout=30.0
                )

                if response.status_code != 201:
                    logger.error(f"[SupabaseAdmin] Failed to create SSO provider: {response.status_code} - {response.text}")
                    raise SupabaseAdminError(
                        f"Failed to create SSO provider: {response.text}",
                        status_code=response.status_code,
                        response_body=response.text
                    )

                data = response.json()
                provider = self._parse_provider(data)
                logger.info(f"[SupabaseAdmin] Created SSO provider: {provider.id}")
                return provider

            except httpx.TimeoutException:
                raise SupabaseAdminError("Request timed out while creating SSO provider")
            except httpx.RequestError as e:
                raise SupabaseAdminError(f"Request failed: {str(e)}")

    async def get_sso_provider(self, provider_id: str) -> Optional[SSOProvider]:
        """
        Get SSO provider by ID.

        Args:
            provider_id: UUID of the SSO provider

        Returns:
            SSOProvider if found, None if not found

        Raises:
            SupabaseAdminError: If the API request fails (except 404)
        """
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(
                    f'{self.base_url}/auth/v1/admin/sso/providers/{provider_id}',
                    headers=self._headers,
                    timeout=30.0
                )

                if response.status_code == 404:
                    return None

                if response.status_code != 200:
                    raise SupabaseAdminError(
                        f"Failed to get SSO provider: {response.text}",
                        status_code=response.status_code,
                        response_body=response.text
                    )

                return self._parse_provider(response.json())

            except httpx.TimeoutException:
                raise SupabaseAdminError("Request timed out while getting SSO provider")
            except httpx.RequestError as e:
                raise SupabaseAdminError(f"Request failed: {str(e)}")

    async def update_sso_provider(
        self,
        provider_id: str,
        metadata_url: Optional[str] = None,
        domains: Optional[List[str]] = None,
        attribute_mapping: Optional[Dict[str, Any]] = None
    ) -> SSOProvider:
        """
        Update an existing SSO provider.

        Commonly used when:
        - Cryptographic keys are rotated or expired
        - Metadata URL has changed
        - Domain associations need updating

        Args:
            provider_id: UUID of the SSO provider to update
            metadata_url: New IdP metadata URL (optional)
            domains: New domain associations (optional)
            attribute_mapping: New attribute mapping (optional)

        Returns:
            Updated SSOProvider

        Raises:
            SupabaseAdminError: If the API request fails
        """
        async with httpx.AsyncClient() as client:
            payload: Dict[str, Any] = {}

            if metadata_url:
                payload['metadata_url'] = metadata_url
            if domains:
                payload['domains'] = domains
            if attribute_mapping:
                payload['attribute_mapping'] = attribute_mapping

            if not payload:
                raise ValueError("At least one field must be provided for update")

            logger.info(f"[SupabaseAdmin] Updating SSO provider: {provider_id}")

            try:
                response = await client.put(
                    f'{self.base_url}/auth/v1/admin/sso/providers/{provider_id}',
                    headers=self._headers,
                    json=payload,
                    timeout=30.0
                )

                if response.status_code not in (200, 201):
                    raise SupabaseAdminError(
                        f"Failed to update SSO provider: {response.text}",
                        status_code=response.status_code,
                        response_body=response.text
                    )

                provider = self._parse_provider(response.json())
                logger.info(f"[SupabaseAdmin] Updated SSO provider: {provider.id}")
                return provider

            except httpx.TimeoutException:
                raise SupabaseAdminError("Request timed out while updating SSO provider")
            except httpx.RequestError as e:
                raise SupabaseAdminError(f"Request failed: {str(e)}")

    async def delete_sso_provider(self, provider_id: str) -> bool:
        """
        Delete an SSO provider.

        WARNING: This will immediately log out all users from that provider
        and prevent them from signing in. User accounts remain but become
        inaccessible.

        Args:
            provider_id: UUID of the SSO provider to delete

        Returns:
            True if deleted successfully

        Raises:
            SupabaseAdminError: If the API request fails
        """
        async with httpx.AsyncClient() as client:
            logger.warning(f"[SupabaseAdmin] Deleting SSO provider: {provider_id}")

            try:
                response = await client.delete(
                    f'{self.base_url}/auth/v1/admin/sso/providers/{provider_id}',
                    headers=self._headers,
                    timeout=30.0
                )

                if response.status_code == 404:
                    logger.warning(f"[SupabaseAdmin] SSO provider not found: {provider_id}")
                    return False

                if response.status_code not in (200, 204):
                    raise SupabaseAdminError(
                        f"Failed to delete SSO provider: {response.text}",
                        status_code=response.status_code,
                        response_body=response.text
                    )

                logger.info(f"[SupabaseAdmin] Deleted SSO provider: {provider_id}")
                return True

            except httpx.TimeoutException:
                raise SupabaseAdminError("Request timed out while deleting SSO provider")
            except httpx.RequestError as e:
                raise SupabaseAdminError(f"Request failed: {str(e)}")

    async def list_sso_providers(self) -> List[SSOProvider]:
        """
        List all SSO providers configured for this project.

        Returns:
            List of SSOProvider objects

        Raises:
            SupabaseAdminError: If the API request fails
        """
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(
                    f'{self.base_url}/auth/v1/admin/sso/providers',
                    headers=self._headers,
                    timeout=30.0
                )

                if response.status_code != 200:
                    raise SupabaseAdminError(
                        f"Failed to list SSO providers: {response.text}",
                        status_code=response.status_code,
                        response_body=response.text
                    )

                data = response.json()
                items = data.get('items', [])
                return [self._parse_provider(item) for item in items]

            except httpx.TimeoutException:
                raise SupabaseAdminError("Request timed out while listing SSO providers")
            except httpx.RequestError as e:
                raise SupabaseAdminError(f"Request failed: {str(e)}")

    def get_saml_metadata_url(self) -> str:
        """Get the SAML metadata URL for this Supabase project (SP metadata)."""
        return f"{self.base_url}/auth/v1/sso/saml/metadata"

    def get_saml_acs_url(self) -> str:
        """Get the SAML Assertion Consumer Service URL for this project."""
        return f"{self.base_url}/auth/v1/sso/saml/acs"

    def get_saml_entity_id(self) -> str:
        """Get the SAML Entity ID for this Supabase project."""
        return f"{self.base_url}/auth/v1/sso/saml/metadata"


# Module-level singleton instance
_admin_client: Optional[SupabaseAdminClient] = None


def get_supabase_admin() -> SupabaseAdminClient:
    """
    Get the singleton Supabase Admin client instance.

    Returns:
        SupabaseAdminClient instance
    """
    global _admin_client
    if _admin_client is None:
        _admin_client = SupabaseAdminClient()
    return _admin_client
