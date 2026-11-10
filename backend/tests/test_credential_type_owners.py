"""Each credential type has one owner; a node using another integration's type declares it borrowed.

Lookups of "the node for a credential type" (credential connect, the connection catalog, a provide link's
methods) put the owner first, so registration order never hands a type to the node that borrows it.
"""
import pytest

from nodes.core import credential_connect, registry
from nodes.core.credential_connect import (
    credential_classes_for_node,
    credential_type_of,
    credential_type_owners,
    owners_first,
    resolve_credential_class,
)
from nodes.core.registry import NODE_REGISTRY


def test_every_credential_type_has_one_owner():
    owners = credential_type_owners.__wrapped__()
    declared = {
        credential_type_of(cls)
        for node_cls in NODE_REGISTRY.values() for cls in credential_classes_for_node(node_cls)
    } - {None}
    assert set(owners) == declared


def test_borrowed_types_are_ones_the_node_accepts_and_another_owns():
    owners = credential_type_owners()
    for node_type, node_cls in NODE_REGISTRY.items():
        accepted = {credential_type_of(cls) for cls in credential_classes_for_node(node_cls)}
        for credential_type in node_cls.borrowed_credential_types:
            assert credential_type in accepted, f"{node_type} borrows {credential_type} but doesn't accept it"
            assert owners[credential_type] != node_type


def test_two_owners_of_one_type_is_an_error(monkeypatch):
    reddit_ads = NODE_REGISTRY['automation-reddit-ads']

    class NotBorrowing(reddit_ads):
        borrowed_credential_types = frozenset()

    monkeypatch.setattr(registry, 'NODE_REGISTRY', {
        'automation-reddit-ads': NotBorrowing, 'automation-reddit': NODE_REGISTRY['automation-reddit'],
    })
    with pytest.raises(ValueError, match='both own credential type reddit_oauth'):
        credential_connect.credential_type_owners.__wrapped__()


@pytest.mark.parametrize('credential_type, owner', [
    ('reddit_oauth', 'automation-reddit'),
    ('microsoft_onedrive_oauth', 'automation-onedrive'),
    ('google_oauth', 'automation-google-classroom'),
])
def test_the_owner_wins_whatever_the_registration_order(credential_type, owner):
    borrowers = [t for t, c in NODE_REGISTRY.items() if credential_type in c.borrowed_credential_types]
    assert borrowers
    candidates = [(t, credential_type) for t in [*borrowers, owner]]
    assert owners_first(candidates)[0] == (owner, credential_type)
    assert resolve_credential_class(credential_type)[0] == owner
