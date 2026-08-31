"""A credential key can be changed without a flag day.

The key seals every stored credential, so swapping it in one step would strand
every existing row. Retiring the old key alongside the new one keeps those rows
readable while they are re-sealed in the background.
"""

import base64
import secrets

import pytest

from utils.encryption import CredentialEncryption


def _key() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()


def test_without_a_retired_key_nothing_changes(monkeypatch):
    monkeypatch.setenv("CREDENTIALS_ENCRYPTION_KEY", _key())
    monkeypatch.delenv("CREDENTIALS_ENCRYPTION_KEY_OLD", raising=False)
    enc = CredentialEncryption()
    assert enc.decrypt_credential(enc.encrypt_credential({"token": "shhh"})) == {"token": "shhh"}


def test_rows_sealed_with_the_old_key_still_open_after_the_swap(monkeypatch):
    old, new = _key(), _key()
    monkeypatch.setenv("CREDENTIALS_ENCRYPTION_KEY", old)
    sealed = CredentialEncryption().encrypt_credential({"token": "shhh"})

    monkeypatch.setenv("CREDENTIALS_ENCRYPTION_KEY", new)
    monkeypatch.setenv("CREDENTIALS_ENCRYPTION_KEY_OLD", old)
    assert CredentialEncryption().decrypt_credential(sealed) == {"token": "shhh"}


def test_the_new_key_alone_cannot_open_an_old_row(monkeypatch):
    old, new = _key(), _key()
    monkeypatch.setenv("CREDENTIALS_ENCRYPTION_KEY", old)
    sealed = CredentialEncryption().encrypt_credential({"token": "shhh"})

    monkeypatch.setenv("CREDENTIALS_ENCRYPTION_KEY", new)
    monkeypatch.delenv("CREDENTIALS_ENCRYPTION_KEY_OLD", raising=False)
    with pytest.raises(ValueError):
        CredentialEncryption().decrypt_credential(sealed)


def test_rotating_reseals_under_the_primary_key(monkeypatch):
    old, new = _key(), _key()
    monkeypatch.setenv("CREDENTIALS_ENCRYPTION_KEY", old)
    sealed = CredentialEncryption().encrypt_credential({"token": "shhh"})

    monkeypatch.setenv("CREDENTIALS_ENCRYPTION_KEY", new)
    monkeypatch.setenv("CREDENTIALS_ENCRYPTION_KEY_OLD", old)
    resealed = CredentialEncryption().rotate_credential(sealed)

    # Re-sealed rows survive the retired key being withdrawn; that withdrawal
    # is the last step of a rotation, so this is what makes it safe.
    monkeypatch.delenv("CREDENTIALS_ENCRYPTION_KEY_OLD", raising=False)
    assert CredentialEncryption().decrypt_credential(resealed) == {"token": "shhh"}


def test_several_retired_keys_are_accepted(monkeypatch):
    older, old, new = _key(), _key(), _key()
    monkeypatch.setenv("CREDENTIALS_ENCRYPTION_KEY", older)
    from_older = CredentialEncryption().encrypt_credential({"token": "a"})
    monkeypatch.setenv("CREDENTIALS_ENCRYPTION_KEY", old)
    from_old = CredentialEncryption().encrypt_credential({"token": "b"})

    monkeypatch.setenv("CREDENTIALS_ENCRYPTION_KEY", new)
    monkeypatch.setenv("CREDENTIALS_ENCRYPTION_KEY_OLD", f"{old},{older}")
    enc = CredentialEncryption()
    assert enc.decrypt_credential(from_older) == {"token": "a"}
    assert enc.decrypt_credential(from_old) == {"token": "b"}
