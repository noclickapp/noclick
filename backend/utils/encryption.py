"""
Encryption utilities for secure credential storage.

Uses Fernet (symmetric encryption) from the cryptography library to encrypt/decrypt
credential data at the application level before storing in the database.
"""

import os
import logging
from typing import Dict, Any
import json
from cryptography.fernet import Fernet

logger = logging.getLogger(__name__)


class CredentialEncryption:
    """Handles encryption and decryption of credential data."""

    def __init__(self):
        """Initialize encryption with key from environment variable."""
        # Get encryption key from environment
        key_b64 = os.environ.get('CREDENTIALS_ENCRYPTION_KEY')

        if not key_b64:
            # FAIL HARD: Missing encryption key will orphan all encrypted credentials on restart
            # This prevents silent data loss in production
            raise ValueError(
                "CREDENTIALS_ENCRYPTION_KEY environment variable is required. "
                "Generate a key with: python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())' "
                "and set it as CREDENTIALS_ENCRYPTION_KEY in your environment. "
                "WARNING: Never lose this key - all encrypted credentials become permanently unreadable without it."
            )

        try:
            # Decode the base64 key
            key = key_b64.encode() if isinstance(key_b64, str) else key_b64
        except Exception as e:
            raise ValueError(f"Invalid CREDENTIALS_ENCRYPTION_KEY format: {e}")

        self.fernet = Fernet(key)

    def encrypt_credential(self, credential_data: Dict[str, Any]) -> str:
        """
        Encrypt credential data.

        Args:
            credential_data: Dictionary containing credential information

        Returns:
            Base64-encoded encrypted string (Fernet already returns base64)
        """
        try:
            # Serialize to JSON
            json_data = json.dumps(credential_data)

            # Encrypt (Fernet.encrypt already returns base64-encoded bytes)
            encrypted_bytes = self.fernet.encrypt(json_data.encode())

            # Just decode bytes to string (no additional base64 encoding needed)
            return encrypted_bytes.decode('utf-8')

        except Exception as e:
            logger.error(f"Error encrypting credential: {e}")
            raise ValueError(f"Failed to encrypt credential: {e}")

    def decrypt_credential(self, encrypted_data: str) -> Dict[str, Any]:
        """
        Decrypt credential data.

        Args:
            encrypted_data: Base64-encoded encrypted string (from Fernet)

        Returns:
            Dictionary containing decrypted credential information
        """
        try:
            # Encode string to bytes (Fernet.decrypt expects bytes)
            encrypted_bytes = encrypted_data.encode('utf-8')

            # Decrypt (Fernet handles base64 decoding internally)
            decrypted_bytes = self.fernet.decrypt(encrypted_bytes)

            # Parse JSON
            credential_data = json.loads(decrypted_bytes.decode())

            return credential_data

        except Exception as e:
            logger.error(f"Error decrypting credential: {e}")
            raise ValueError(f"Failed to decrypt credential: {e}")


# Singleton instance
_encryption_instance = None


def get_encryption() -> CredentialEncryption:
    """Get singleton encryption instance."""
    global _encryption_instance
    if _encryption_instance is None:
        _encryption_instance = CredentialEncryption()
    return _encryption_instance
