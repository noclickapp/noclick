"""
Tests for folder-share support in get_accessible_resources.

The accessible-resources listing must include workflows reachable via a shared
folder (or an ancestor folder), matching the folder branch of
check_resource_access. Folder logic is workflow-only.
"""

import pytest

from utils.access_control import get_accessible_resources


class FakeConn:
    """Returns canned rows for each successive conn.fetch() call, in order."""

    def __init__(self, results):
        self._results = list(results)

    async def fetch(self, query, *args):
        if not self._results:
            raise AssertionError("unexpected extra conn.fetch() call")
        return self._results.pop(0)


@pytest.mark.asyncio
async def test_workflow_listing_includes_folder_shares():
    # Query order: owned, direct_share, org_share, folder_user, folder_org.
    conn = FakeConn([
        [{"id": "w-own"}],
        [{"resource_id": "w-direct", "permission": "view"}],
        [{"resource_id": "w-org", "permission": "edit"}],
        [{"resource_id": "w-fuser", "permission": "view"}],
        [{"resource_id": "w-forg", "permission": "edit"}],
    ])
    res = await get_accessible_resources(conn, "u1", "workflow")
    by_via = {r["via"]: r["resource_id"] for r in res}
    assert by_via["owner"] == "w-own"
    assert by_via["direct_share"] == "w-direct"
    assert by_via["org_share"] == "w-org"
    assert by_via["folder_share"] == "w-fuser"
    assert by_via["org_folder_share"] == "w-forg"


@pytest.mark.asyncio
async def test_database_listing_skips_folder_queries():
    # databases have no folders → exactly 3 fetches (owned, direct, org). A 4th
    # call would pop from an empty FakeConn and raise.
    conn = FakeConn([
        [{"id": "d-own"}],
        [],
        [],
    ])
    res = await get_accessible_resources(conn, "u1", "database")
    assert {r["via"] for r in res} == {"owner"}
