"""Workflow durable-volume cleanup for the self-hosted edition.

Permanent deletion must reclaim every portable volume family minted for a
workflow, while trash/soft-delete must leave those volumes available for a
restore.  The hosted runtime has additional storage families; those are tested
with the hosted implementation and are deliberately outside this public suite.
"""

from contextlib import contextmanager
import inspect
from unittest.mock import AsyncMock, patch

from nodes.filesystem_node import get_volume_name as fs_volume_name
from utils import workflow_resource_manager as wrm
from utils.volume_backend import workspace_volume_name
from utils.workflow_resource_manager import (
    _cleanup_workflow_volumes,
    is_workflow_volume,
)


WF = "353d0e5f-a599-41fa-926e-6fe4ab047ac7"
OTHER = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


class TestIsWorkflowVolume:
    def test_every_public_volume_family_matches(self):
        names = [
            workspace_volume_name(WF, "agent_rdgd", "__interface_chat___x"),
            fs_volume_name(WF, "fs_1", "common"),
            fs_volume_name(WF, "fs_1", "per_conversation_key", "ck-1"),
        ]
        for name in names:
            assert is_workflow_volume(name, WF), name

    def test_long_components_keep_the_workflow_id_matchable(self):
        name = workspace_volume_name(WF, "n" * 60, "c" * 60)
        assert is_workflow_volume(name, WF)

    def test_other_workflows_never_match(self):
        name = workspace_volume_name(OTHER, "agent", "ck")
        assert not is_workflow_volume(name, WF)

    def test_prefix_similar_ids_never_cross_match(self):
        assert is_workflow_volume("noclick-ws-wf1-abc", "wf1")
        assert is_workflow_volume("noclick-fs-wf1", "wf1")
        assert not is_workflow_volume("noclick-ws-wf12-abc", "wf1")
        assert not is_workflow_volume("noclick-ws-wf1x", "wf1")

    def test_foreign_and_unscoped_names_never_match(self):
        for name in (
            "random-vol",
            f"other-{WF}",
            f"myapp-ws-{WF}-x",
            f"noclick-{WF}",
            "noclick-global-sessions",
        ):
            assert not is_workflow_volume(name, WF), name


class _StubVolumeBackend:
    """Volume-backend stub with a fixed listing and injectable deletion."""

    def __init__(self, listed_names, delete_mock):
        self._names = list(listed_names)
        self.delete_mock = delete_mock

    async def list_volume_names(self):
        return list(self._names)

    async def delete_volume(self, name):
        await self.delete_mock(name)
        return True


@contextmanager
def _volume_backend_stub(listed_names, delete_mock):
    import utils.volume_backend as volume_backend

    with (
        patch.object(
            volume_backend,
            "_backend",
            _StubVolumeBackend(listed_names, delete_mock),
        ),
        patch.object(volume_backend, "_initialized", True),
    ):
        yield


class TestCleanupWorkflowVolumes:
    async def test_deletes_exactly_the_workflow_set(self):
        mine = [
            workspace_volume_name(WF, "agent", "ck"),
            fs_volume_name(WF, "fs_1", "common"),
        ]
        theirs = [
            workspace_volume_name(OTHER, "agent", "ck"),
            "noclick-global-sessions",
        ]
        delete_mock = AsyncMock()
        with _volume_backend_stub(mine + theirs, delete_mock):
            deleted = await _cleanup_workflow_volumes(WF)
        assert deleted == len(mine)
        deleted_names = {call.args[0] for call in delete_mock.await_args_list}
        assert deleted_names == set(mine)

    async def test_one_failed_delete_does_not_stop_the_sweep(self):
        mine = [
            workspace_volume_name(WF, "agent", "ck"),
            fs_volume_name(WF, "fs_1", "common"),
        ]
        delete_mock = AsyncMock(side_effect=[Exception("backend blip"), None])
        with _volume_backend_stub(mine, delete_mock):
            deleted = await _cleanup_workflow_volumes(WF)
        assert deleted == 1
        assert delete_mock.await_count == 2


class TestOnlyPermanentDeletionReachesVolumes:
    def test_full_cleanup_runs_the_sweep(self):
        assert "_cleanup_workflow_volumes" in inspect.getsource(
            wrm.cleanup_workflow_resources
        )

    def test_operational_cleanup_never_touches_volumes(self):
        source = inspect.getsource(wrm.cleanup_workflow_operational_resources)
        assert "volume" not in source.lower()
