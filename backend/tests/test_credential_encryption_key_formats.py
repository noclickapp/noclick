"""The encryption key is accepted in both spellings of the same 32 bytes.

A one-click deploy generates this key with whatever its platform can express:
Render emits base64, Railway hex. Reading only one of them would put the
operator back to generating a key by hand, which is the question these deploys
exist to remove.
"""

import base64
import secrets

import pytest
from cryptography.fernet import Fernet

from utils.encryption import CredentialEncryption, _as_fernet_key


def test_hex_and_base64_spellings_are_the_same_key(monkeypatch):
    raw = secrets.token_bytes(32)
    monkeypatch.setenv("CREDENTIALS_ENCRYPTION_KEY", raw.hex())
    sealed = CredentialEncryption().encrypt_credential({"token": "shhh"})

    # The same bytes, written the other way, read it back.
    monkeypatch.setenv(
        "CREDENTIALS_ENCRYPTION_KEY", base64.urlsafe_b64encode(raw).decode()
    )
    assert CredentialEncryption().decrypt_credential(sealed) == {"token": "shhh"}


def test_an_existing_key_is_never_reinterpreted():
    for key in (Fernet.generate_key(), b"z" * 64, base64.urlsafe_b64encode(b"k" * 32)):
        assert _as_fernet_key(key) == key


def test_a_key_that_is_neither_still_fails_loudly(monkeypatch):
    monkeypatch.setenv("CREDENTIALS_ENCRYPTION_KEY", "not-a-key")
    with pytest.raises(ValueError):
        CredentialEncryption()
