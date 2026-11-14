"""A credential's operation catalog is built off the event loop, once per process per credential type.

Listing what a credential can run builds the schema of every provider its type powers (a Google sign-in powers 24),
which the coordinator's credential tools and the permissions page did on the event loop at every call."""

import threading

import pytest

from nodes.agent import node_op_tools
from utils import credential_operations

CREDENTIAL = "google_gmail_oauth"


@pytest.fixture
def built_in(monkeypatch):
    """The threads each provider's operations were listed on, with no catalog built yet."""
    listed = node_op_tools.list_node_operations
    threads = []

    def list_node_operations(node_type):
        threads.append(threading.current_thread())
        return listed(node_type)

    monkeypatch.setattr(credential_operations, "_CATALOGS", {})
    monkeypatch.setattr(node_op_tools, "list_node_operations", list_node_operations)
    return threads


def _as_it_was(node_type=None):
    """What the catalog answered when it listed every provider's operations at each call."""
    return [{"node_type": provider, **operation, "key": f"{provider}.{operation['operation']}"}
            for provider in ([node_type] if node_type else credential_operations.compatible_providers(CREDENTIAL))
            for operation in node_op_tools.list_node_operations(provider)]


async def test_the_catalog_reads_as_it_did(built_in):
    assert len(credential_operations.compatible_providers(CREDENTIAL)) > 1
    assert await credential_operations.operation_catalog(CREDENTIAL) == _as_it_was()
    assert await credential_operations.operation_catalog(CREDENTIAL, "automation-gmail") == \
        _as_it_was("automation-gmail")
    with pytest.raises(ValueError, match="does not support"):
        await credential_operations.operation_catalog(CREDENTIAL, "automation-slack")


async def test_the_catalog_is_built_in_a_thread_once_per_credential_type(built_in):
    first = await credential_operations.operation_catalog(CREDENTIAL)
    assert built_in and all(thread is not threading.current_thread() for thread in built_in)
    listed = len(built_in)
    first[0]["display_name"] = "changed by its caller"
    again = await credential_operations.operation_catalog(CREDENTIAL)
    await credential_operations.operation_catalog(CREDENTIAL, "automation-gmail")
    assert len(built_in) == listed, "read as it was built"
    assert again[0]["display_name"] != "changed by its caller"
