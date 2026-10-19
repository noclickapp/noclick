"""A workflow NoClick runs itself (``settings.system``), over real PostgreSQL:
its owner may open and run it, nobody changes it, and no list of a person's
workflows shows it."""

import pytest

from repositories.workflow import WorkflowRepo
from tests.fixtures.cas_fixtures import TEST_USER_ID, codec_pool, make_workflow  # noqa: F401
from utils.access_control import AccessResult, Permission, check_resource_access

pytestmark = pytest.mark.asyncio
USER = str(TEST_USER_ID)


async def _listed(conn, repo):
    """The workflow ids each of the person's lists shows: Automations, the AI builder's."""
    return (
        {str(r["id"]) for r in await repo.list_workflows_personal(conn, user_id=TEST_USER_ID, folder_id=None)},
        {str(r["id"]) for r in await repo.list_workflows_builder(conn, user_id=TEST_USER_ID, organization_id=None,
                                                                 query=None, limit=50)},
    )


async def test_its_owner_views_it_and_no_list_shows_it(codec_pool):
    repo = WorkflowRepo(codec_pool)
    own, system = str(await make_workflow(codec_pool)), str(await make_workflow(codec_pool))
    async with codec_pool.acquire() as conn:
        await repo.mark_system(conn, system, "your NoClick assistant")

        assert await check_resource_access(conn, USER, "workflow", own) == AccessResult(True, Permission.OWNER, "owner")
        access = await check_resource_access(conn, USER, "workflow", system)
        assert access == AccessResult(True, Permission.VIEW, "owner", "your NoClick assistant")
        assert access.edit_refusal("No edit access") == (
            "This automation runs your NoClick assistant, so NoClick keeps it: it can't be edited, renamed or deleted.")
        assert AccessResult(True, Permission.OWNER).edit_refusal("No edit access") == "No edit access"

        automations, builder = await _listed(conn, repo)
        assert own in automations and own in builder
        assert system not in automations and system not in builder
        assert await repo.owned_workflow_system(conn, system, TEST_USER_ID) == "your NoClick assistant"
        assert await repo.owned_workflow_system(conn, own, TEST_USER_ID) == ""
